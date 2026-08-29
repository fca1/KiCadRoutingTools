"""Conservative octolinear envelopes for copper clearance obstacles."""

from __future__ import annotations

import math

from ..candidate_geometry import (circular_obstacle_required_distance,
                                  track_pair_required_distance)


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


def octolinear_disk(centre, radius):
    """Circumscribe a disk with the smallest 0/45/90-sided octagon.

    The polygon contains the complete round clearance envelope.  Its sides,
    rather than a sampled arc, are the only possible string contacts.
    """
    if radius <= 0.0:
        return (centre,)
    vertex_radius = radius / math.cos(math.pi / 8.0)
    return tuple((
        centre[0] + vertex_radius * math.cos(math.pi / 8.0 + index * math.pi / 4.0),
        centre[1] + vertex_radius * math.sin(math.pi / 8.0 + index * math.pi / 4.0),
    ) for index in range(8))


def track_envelope(model, moving, foreign):
    """Minkowski sum of a foreign centreline and the clearance octagon."""
    radius = track_pair_required_distance(model, moving, foreign)
    points = (octolinear_disk(
        (foreign.start_x, foreign.start_y), radius) +
        octolinear_disk((foreign.end_x, foreign.end_y), radius))
    return convex_hull(points)


def circular_envelope(model, moving, obstacle):
    radius = circular_obstacle_required_distance(model, moving, obstacle)
    return octolinear_disk((obstacle.x, obstacle.y), radius)


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


__all__ = ("circular_envelope", "convex_hull", "octolinear_disk",
           "outward_normal", "segment_penetrates", "track_envelope")
