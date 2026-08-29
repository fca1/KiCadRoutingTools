"""API-neutral Smart Octo geometry prepared for an optional KiCad overlay."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import PlannerContext, line_bbox
from ..model import segment_key
from .clearance import effective_clearance
from .obstacles import (circular_envelope, circular_polygon, pad_envelopes,
                        pad_polygons, track_envelope, track_polygon)


@dataclass(frozen=True)
class DiagnosticPolygon:
    points: tuple
    layer: int
    role: str
    kind: str
    moving_net: int
    obstacle_net: int
    clearance: float
    winning_source: str


def _record(result, seen, points, moving, obstacle_net, role, kind,
            clearance, winning_source):
    rounded = tuple((round(x, 6), round(y, 6)) for x, y in points)
    identity = (moving.layer, role, kind, moving.net_id, obstacle_net, rounded)
    if len(rounded) < 3 or identity in seen:
        return
    seen.add(identity)
    result.append(DiagnosticPolygon(
        rounded, moving.layer, role, kind, moving.net_id, obstacle_net,
        float(clearance), winning_source))


def collect_diagnostic_polygons(model, eligible_keys, limit=4000):
    """Collect nearby sourced and effective envelopes for selected copper."""
    eligible_keys = frozenset(eligible_keys)
    context = PlannerContext(model)
    selected = [segment for segment in model.segments
                if segment_key(segment) in eligible_keys]
    result, seen = [], set()

    for moving in selected:
        moving_clearance = effective_clearance(model, moving)
        start = moving.start_x, moving.start_y
        end = moving.end_x, moving.end_y
        track_margin = (moving.width / 2.0 + context.max_segment_halfwidth +
                        context.max_net_clearance)
        for foreign in context.segments.query(
                line_bbox(start, end, track_margin)):
            if (foreign.layer != moving.layer or
                    foreign.net_id == moving.net_id):
                continue
            envelope = track_envelope(model, moving, foreign)
            obstacle_clearance = envelope.obstacle_clearance
            for role, clearance in (("moving", moving_clearance),
                                    ("obstacle", obstacle_clearance)):
                _record(result, seen, track_polygon(
                    foreign, clearance, moving.width), moving,
                    foreign.net_id, role, "track", clearance,
                    envelope.winning_source)
            _record(result, seen, envelope.support_polygon, moving,
                    foreign.net_id, "effective", "track",
                    envelope.effective_clearance, envelope.winning_source)
            if len(result) >= limit:
                return tuple(result)

        obstacle_margin = (context.max_obstacle_radius + moving.width / 2.0 +
                           context.max_net_clearance)
        for obstacle in context.obstacles.query(
                line_bbox(start, end, obstacle_margin)):
            if (obstacle.net_id == moving.net_id or
                    (obstacle.layers and moving.layer not in obstacle.layers)):
                continue
            envelope = circular_envelope(model, moving, obstacle)
            for role, clearance in (("moving", moving_clearance),
                                    ("obstacle", envelope.obstacle_clearance)):
                _record(result, seen, circular_polygon(
                    obstacle, clearance, moving.width), moving,
                    obstacle.net_id, role, obstacle.kind, clearance,
                    envelope.winning_source)
            _record(result, seen, envelope.support_polygon, moving,
                    obstacle.net_id, "effective", obstacle.kind,
                    envelope.effective_clearance, envelope.winning_source)
            if len(result) >= limit:
                return tuple(result)

        pad_margin = (context.max_pad_radius + moving.width / 2.0 +
                      context.max_net_clearance)
        for pad in context.pads.query(line_bbox(start, end, pad_margin)):
            if (pad.net_id == moving.net_id or
                    (pad.layers and moving.layer not in pad.layers)):
                continue
            envelopes = pad_envelopes(model, moving, pad)
            for role, clearance in (("moving", moving_clearance),
                                    ("obstacle", max(
                                        model.minimum_clearance,
                                        pad.clearance))):
                for polygon in pad_polygons(pad, clearance, moving.width):
                    _record(result, seen, polygon, moving, pad.net_id,
                            role, "pad", clearance,
                            envelopes[0].winning_source if envelopes else "")
            for envelope in envelopes:
                _record(result, seen, envelope.support_polygon, moving,
                        pad.net_id, "effective", "pad",
                        envelope.effective_clearance,
                        envelope.winning_source)
            if len(result) >= limit:
                return tuple(result)
    return tuple(result)


__all__ = ("DiagnosticPolygon", "collect_diagnostic_polygons")
