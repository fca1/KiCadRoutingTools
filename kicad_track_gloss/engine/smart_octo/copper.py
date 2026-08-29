"""Copper reconstruction and exact shared safety gate for Smart Octo."""

from __future__ import annotations

from dataclasses import replace

from ..geometry import length
from ..model import AddedSegment, segment_key
from .safety import path_blocker


def path_length(path):
    return sum(length(a, b) for a, b in zip(path, path[1:]))


def map_path_to_copper(path, originals, layer, net_id):
    """Preserve ordered width/rule runs on a replacement centreline."""
    runs = []
    for segment in originals:
        run_length = length(
            (segment.start_x, segment.start_y),
            (segment.end_x, segment.end_y))
        signature = (segment.width, segment.clearance)
        if (runs and
                tuple(round(value, 6) for value in runs[-1][0]) ==
                tuple(round(value, 6) for value in signature)):
            runs[-1] = runs[-1][0], runs[-1][1] + run_length
        else:
            runs.append((signature, run_length))
    total = path_length(path)
    original_total = sum(run_length for _run, run_length in runs)
    if total <= 1e-12 or original_total <= 1e-12:
        return ()

    transitions = []
    travelled = 0.0
    for _run, run_length in runs[:-1]:
        travelled += run_length
        transitions.append(total * travelled / original_total)

    additions = []
    travelled = 0.0
    run_index = 0
    for start, end in zip(path, path[1:]):
        edge_length = length(start, end)
        if edge_length <= 1e-12:
            continue
        cuts = [travelled]
        cuts.extend(value for value in transitions
                    if travelled + 1e-12 < value <
                    travelled + edge_length - 1e-12)
        cuts.append(travelled + edge_length)
        for first, second in zip(cuts, cuts[1:]):
            midpoint = (first + second) / 2.0
            while (run_index < len(transitions) and
                   midpoint >= transitions[run_index] - 1e-12):
                run_index += 1
            local_first = (first - travelled) / edge_length
            local_second = (second - travelled) / edge_length
            a = (start[0] + local_first * (end[0] - start[0]),
                 start[1] + local_first * (end[1] - start[1]))
            b = (start[0] + local_second * (end[0] - start[0]),
                 start[1] + local_second * (end[1] - start[1]))
            width, clearance = runs[run_index][0]
            additions.append(AddedSegment(
                a, b, width, layer, net_id, clearance))
        travelled += edge_length
    return tuple(additions)


def path_is_safe(model, path, originals, *, context, immutable_cover_keys,
                 check_deadline=None):
    additions = map_path_to_copper(
        path, originals, originals[0].layer, originals[0].net_id)
    if not additions:
        return False
    replaced = frozenset(segment_key(segment) for segment in originals)
    prototype = originals[0]

    for addition in additions:
        if check_deadline is not None:
            check_deadline()
        moving = replace(
            prototype, width=addition.width, clearance=addition.clearance)
        if path_blocker(
                model, (addition.start, addition.end), moving, replaced,
                model.minimum_clearance, context, immutable_cover_keys):
            return False
    return True


__all__ = ("map_path_to_copper", "path_is_safe", "path_length")
