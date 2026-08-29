"""Deterministic selected-copper topology and T-junction semantics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from ..model import Segment, segment_key
from ..pads import pad_contains


Point = tuple[float, float]


def point(x, y):
    return round(float(x), 6), round(float(y), 6)


def endpoints(segment):
    return (point(segment.start_x, segment.start_y),
            point(segment.end_x, segment.end_y))


def other_endpoint(segment, junction):
    first, second = endpoints(segment)
    if first == junction:
        return second
    if second == junction:
        return first
    raise ValueError("segment does not terminate at junction")


def _opposite_collinear(first, second, junction, tolerance):
    a = other_endpoint(first, junction)
    b = other_endpoint(second, junction)
    ax, ay = a[0] - junction[0], a[1] - junction[1]
    bx, by = b[0] - junction[0], b[1] - junction[1]
    first_length = math.hypot(ax, ay)
    second_length = math.hypot(bx, by)
    if first_length <= tolerance or second_length <= tolerance:
        return False
    cross = abs(ax * by - ay * bx)
    scale = first_length * second_length
    dot = ax * bx + ay * by
    return cross <= tolerance * scale and dot < 0.0


@dataclass(frozen=True)
class Rail:
    """A fixed collinear support through a junction."""

    first_key: str
    second_key: str
    start: Point
    end: Point


@dataclass(frozen=True)
class Junction:
    point: Point
    incident_keys: tuple[str, ...]
    rails: tuple[Rail, ...]

    def sliding_rails(self, branch_key):
        """Return every T interpretation in which ``branch_key`` slides."""
        return tuple(rail for rail in self.rails
                     if branch_key not in
                     (rail.first_key, rail.second_key))


@dataclass(frozen=True)
class Terminal:
    point: Point
    kind: str = "fixed"
    rails: tuple[Rail, ...] = ()
    pads: tuple[object, ...] = ()


@dataclass(frozen=True)
class Chain:
    net_id: int
    layer: int
    segments: tuple[Segment, ...]
    points: tuple[Point, ...]
    start: Terminal
    end: Terminal

    @property
    def keys(self):
        return tuple(segment_key(segment) for segment in self.segments)


@dataclass(frozen=True)
class Topology:
    junctions: dict[tuple[int, int, Point], Junction]
    incidence: dict[tuple[int, int, Point], tuple[Segment, ...]]


def build_topology(model):
    """Describe endpoint junctions without inferring any routing intent."""
    buckets = defaultdict(list)
    for segment in model.segments:
        if segment.arc or segment.net_id <= 0:
            continue
        for terminal in endpoints(segment):
            buckets[(segment.net_id, segment.layer, terminal)].append(segment)

    incidence = {}
    junctions = {}
    tolerance = max(model.coordinate_quantum_mm, 1e-9)
    for identity, touching in buckets.items():
        touching = tuple(sorted(touching, key=segment_key))
        incidence[identity] = touching
        if len(touching) < 3:
            continue
        location = identity[2]
        rails = []
        for index, first in enumerate(touching):
            for second in touching[index + 1:]:
                if not _opposite_collinear(
                        first, second, location, tolerance):
                    continue
                outer = sorted((other_endpoint(first, location),
                                other_endpoint(second, location)))
                rails.append(Rail(
                    segment_key(first), segment_key(second),
                    outer[0], outer[1]))
        rails = tuple(sorted(set(rails), key=lambda rail: (
            rail.first_key, rail.second_key, rail.start, rail.end)))
        junctions[identity] = Junction(
            location, tuple(segment_key(item) for item in touching), rails)
    return Topology(junctions, incidence)


def _pad_terminals(model, segment, location):
    return tuple(region for region in model.pad_regions
                 if region.net_id == segment.net_id and
                 (not region.layers or segment.layer in region.layers) and
                 pad_contains(region, location,
                              tolerance=model.coordinate_quantum_mm))


def _terminal(model, topology, segment, location):
    identity = (segment.net_id, segment.layer, location)
    junction = topology.junctions.get(identity)
    if junction is not None:
        rails = junction.sliding_rails(segment_key(segment))
        if rails:
            return Terminal(location, "rail", rails=rails)
        return Terminal(location, "node")
    pads = _pad_terminals(model, segment, location)
    if pads:
        return Terminal(location, "pad", pads=pads)
    return Terminal(location)


def extract_chains(model, eligible_segment_keys):
    """Return maximal selected degree-two chains with explicit terminals.

    A T is always an anchor.  Whether its incident branch may slide is carried
    by the resulting terminal and never changes the geometry of its fixed
    collinear rail.
    """
    eligible = {str(key) for key in eligible_segment_keys}
    selected = [segment for segment in model.segments
                if segment_key(segment) in eligible and
                not segment.locked and not segment.arc and
                segment.net_id > 0]
    topology = build_topology(model)
    by_group = defaultdict(list)
    for segment in selected:
        by_group[(segment.net_id, segment.layer)].append(segment)

    chains = []
    for (net_id, layer), segments in sorted(by_group.items()):
        adjacency = defaultdict(list)
        for segment in segments:
            for terminal in endpoints(segment):
                adjacency[terminal].append(segment)
        for touching in adjacency.values():
            touching.sort(key=segment_key)

        def interior(location):
            identity = (net_id, layer, location)
            return (len(adjacency[location]) == 2 and
                    len(topology.incidence.get(identity, ())) == 2 and
                    identity not in topology.junctions)

        anchors = sorted(location for location in adjacency
                         if not interior(location))
        used = set()
        for anchor in anchors:
            for first in adjacency[anchor]:
                if segment_key(first) in used:
                    continue
                ordered_segments = []
                ordered_points = [anchor]
                current = anchor
                moving = first
                while True:
                    key = segment_key(moving)
                    if key in used:
                        break
                    used.add(key)
                    ordered_segments.append(moving)
                    destination = other_endpoint(moving, current)
                    ordered_points.append(destination)
                    current = destination
                    if not interior(current):
                        break
                    following = [candidate for candidate in adjacency[current]
                                 if segment_key(candidate) not in used]
                    if not following:
                        break
                    moving = following[0]
                if not ordered_segments or ordered_points[-1] == anchor:
                    continue
                chains.append(Chain(
                    net_id, layer, tuple(ordered_segments),
                    tuple(ordered_points),
                    _terminal(model, topology, ordered_segments[0],
                              ordered_points[0]),
                    _terminal(model, topology, ordered_segments[-1],
                              ordered_points[-1])))
    return tuple(sorted(chains, key=lambda chain: (
        chain.net_id, chain.layer, chain.points, chain.keys)))


__all__ = ("Chain", "Junction", "Rail", "Terminal", "Topology",
           "build_topology", "extract_chains")
