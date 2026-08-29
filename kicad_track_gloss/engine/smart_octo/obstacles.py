"""Single sourced-clearance octagons used by the Smart Octo solver."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .clearance import effective_clearance


@dataclass(frozen=True)
class SmartEnvelope:
    """One obstacle envelope plus clearance provenance.

    ``forbidden_polygon`` contains obstacle copper and the effective clearance.
    ``support_polygon`` additionally accounts for the moving track half-width;
    it is the boundary contacted by the moving centreline. Keeping both makes
    the thick-polyline model explicit without duplicating solver obstacles.
    """

    forbidden_polygon: tuple
    support_polygon: tuple
    moving_clearance: float
    obstacle_clearance: float
    effective_clearance: float
    winning_source: str


def _clearance_sources(model, moving, obstacle_clearance):
    moving_clearance = effective_clearance(model, moving)
    obstacle_clearance = max(
        float(model.minimum_clearance), float(obstacle_clearance))
    effective = max(moving_clearance, obstacle_clearance)
    if moving_clearance > obstacle_clearance:
        source = "moving_net"
    elif obstacle_clearance > moving_clearance:
        source = "obstacle"
    else:
        source = "equal"
    return moving_clearance, obstacle_clearance, effective, source


def _cross(origin, first, second):
    return ((first[0] - origin[0]) * (second[1] - origin[1]) -
            (first[1] - origin[1]) * (second[0] - origin[0]))


def convex_hull(points):
    """Return a deterministic counter-clockwise convex hull."""
    ordered = sorted(set((float(x), float(y)) for x, y in points))
    if len(ordered) <= 2:
        return tuple(ordered)
    lower = []
    for point in ordered:
        while len(lower) >= 2 and _cross(
                lower[-2], lower[-1], point) <= 1e-15:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(ordered):
        while len(upper) >= 2 and _cross(
                upper[-2], upper[-1], point) <= 1e-15:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def octolinear_hull(points, margin=0.0):
    """Smallest convex 0/45/90-sided polygon containing points + margin."""
    points = tuple((float(x), float(y)) for x, y in points)
    if not points:
        return ()
    normals = tuple((math.cos(index * math.pi / 4.0),
                     math.sin(index * math.pi / 4.0))
                    for index in range(8))
    supports = tuple(max(x * nx + y * ny for x, y in points) + margin
                     for nx, ny in normals)
    vertices = []
    for index in range(8):
        first = normals[index]
        second = normals[(index + 1) % 8]
        first_support = supports[index]
        second_support = supports[(index + 1) % 8]
        determinant = first[0] * second[1] - first[1] * second[0]
        vertices.append((
            (first_support * second[1] - first[1] * second_support) /
            determinant,
            (first[0] * second_support - first_support * second[0]) /
            determinant,
        ))
    return convex_hull(vertices)


def octolinear_disk(centre, radius):
    """Circumscribe a disk with the smallest 0/45/90-sided octagon.

    The polygon contains the complete round clearance envelope.  Its sides,
    rather than a sampled arc, are the only possible string contacts.
    """
    if radius <= 0.0:
        return (centre,)
    return octolinear_hull((centre,), radius)


def track_envelope(model, moving, foreign):
    """Return one irregular octolinear envelope for a foreign track."""
    values = _clearance_sources(
        model, moving, effective_clearance(model, foreign))
    effective = values[2]

    forbidden = track_polygon(foreign, effective)
    support = track_polygon(foreign, effective, moving.width)
    return SmartEnvelope(forbidden, support, *values)


def track_polygon(foreign, clearance, moving_width=0.0):
    radius = (foreign.width + moving_width) / 2.0 + float(clearance)
    return octolinear_hull((
        (foreign.start_x, foreign.start_y),
        (foreign.end_x, foreign.end_y)), radius)


def circular_envelope(model, moving, obstacle):
    values = _clearance_sources(model, moving, obstacle.clearance)
    return SmartEnvelope(
        circular_polygon(obstacle, values[2]),
        circular_polygon(obstacle, values[2], moving.width),
        *values)


def circular_polygon(obstacle, clearance, moving_width=0.0):
    return octolinear_disk(
        (obstacle.x, obstacle.y),
        obstacle.radius + float(clearance) + moving_width / 2.0)


def _rotated(point, centre, angle_degrees):
    angle = math.radians(angle_degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    return (centre[0] + point[0] * cosine - point[1] * sine,
            centre[1] + point[0] * sine + point[1] * cosine)


def _pad_primitives(pad):
    """Return copper point sets whose octolinear hulls cover one pad."""
    if pad.shape == "custom":
        return tuple(outer for outer, _holes in pad.polygons if outer)
    half_width, half_height = pad.width / 2.0, pad.height / 2.0
    if pad.shape == "circle":
        return (((pad.x, pad.y),),)
    if pad.shape == "oval":
        if half_width >= half_height:
            core = half_width - half_height
            local = ((-core, 0.0), (core, 0.0))
        else:
            core = half_height - half_width
            local = ((0.0, -core), (0.0, core))
        return (tuple(_rotated(
            point, (pad.x, pad.y), pad.orientation_degrees)
                      for point in local),)
    local = ((-half_width, -half_height),
             (half_width, -half_height),
             (half_width, half_height),
             (-half_width, half_height))
    return (tuple(_rotated(
        point, (pad.x, pad.y), pad.orientation_degrees)
                  for point in local),)


def pad_envelopes(model, moving, pad):
    """Return conservative Smart Octo envelopes for a foreign pad."""
    values = _clearance_sources(model, moving, pad.clearance)
    forbidden = pad_polygons(pad, values[2])
    support = pad_polygons(pad, values[2], moving.width)
    return tuple(SmartEnvelope(first, second, *values)
                 for first, second in zip(forbidden, support))


def pad_polygons(pad, clearance, moving_width=0.0):
    if pad.shape in ("circle", "oval"):
        copper_radius = min(pad.width, pad.height) / 2.0
    else:
        copper_radius = 0.0
    margin = copper_radius + float(clearance) + moving_width / 2.0
    return tuple(octolinear_hull(primitive, margin)
                 for primitive in _pad_primitives(pad))


def outward_normal(start, end):
    """Outward unit normal of one counter-clockwise polygon edge."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    magnitude = math.hypot(dx, dy)
    if magnitude <= 1e-18:
        return None
    return dy / magnitude, -dx / magnitude


def segment_penetrates(start, end, polygon, tolerance=1e-9):
    """Whether a segment enters the strict interior of a convex polygon."""
    if len(polygon) < 3:
        return False
    lower, upper = 0.0, 1.0
    for first, second in zip(polygon, polygon[1:] + polygon[:1]):
        edge_x, edge_y = second[0] - first[0], second[1] - first[1]
        start_side = (edge_x * (start[1] - first[1]) -
                      edge_y * (start[0] - first[0]))
        end_side = (edge_x * (end[1] - first[1]) -
                    edge_y * (end[0] - first[0]))
        delta = end_side - start_side
        if abs(delta) <= 1e-18:
            if start_side <= tolerance:
                return False
            continue
        crossing = (tolerance - start_side) / delta
        if delta > 0.0:
            lower = max(lower, crossing)
        else:
            upper = min(upper, crossing)
        if lower >= upper - 1e-15:
            return False
    return lower < upper - 1e-15


__all__ = ("SmartEnvelope", "circular_envelope", "circular_polygon",
           "convex_hull", "octolinear_disk", "octolinear_hull",
           "outward_normal", "pad_envelopes", "pad_polygons",
           "segment_penetrates", "track_envelope", "track_polygon")
