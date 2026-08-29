"""Continuous contraction of a routed polyline inside its current corridor."""

from __future__ import annotations

from ..geometry import length, quantize_path
from ..pads import pad_contains
from .copper import path_length


def _quantize(path, quantum):
    quantized = quantize_path(path, quantum)
    return tuple(value for index, value in enumerate(quantized)
                 if index == 0 or length(quantized[index - 1], value) > quantum)


def _quantize_aligned(path, quantum):
    """Quantize coordinates while retaining one target per current vertex."""
    return tuple((round(value[0] / quantum) * quantum,
                  round(value[1] / quantum) * quantum)
                 for value in path)


def _normalize(path, quantum):
    output = []
    for value in _quantize(path, quantum):
        output.append(value)
        while len(output) >= 3:
            a, b, c = output[-3:]
            ab = b[0] - a[0], b[1] - a[1]
            bc = c[0] - b[0], c[1] - b[1]
            if abs(ab[0] * bc[1] - ab[1] * bc[0]) > quantum:
                break
            output.pop(-2)
    return tuple(output)


def _straight_targets(path):
    """Map every current support point to equal arclength on the chord."""
    if len(path) <= 2:
        return tuple(path)
    return tuple((
        path[0][0] + index * (path[-1][0] - path[0][0]) / (len(path) - 1),
        path[0][1] + index * (path[-1][1] - path[0][1]) / (len(path) - 1),
    ) for index in range(len(path)))


def _interpolate(current, target, ratio):
    return tuple((a[0] + ratio * (b[0] - a[0]),
                  a[1] + ratio * (b[1] - a[1]))
                 for a, b in zip(current, target))


def _line_intersection(first_point, first_direction,
                       second_point, second_direction, tolerance):
    denominator = (first_direction[0] * second_direction[1] -
                   first_direction[1] * second_direction[0])
    if abs(denominator) <= tolerance:
        return None
    delta = (second_point[0] - first_point[0],
             second_point[1] - first_point[1])
    ratio = (delta[0] * second_direction[1] -
             delta[1] * second_direction[0]) / denominator
    return (first_point[0] + ratio * first_direction[0],
            first_point[1] + ratio * first_direction[1])


def _translated_interior_segment(path, edge_index, offset, tolerance):
    """Translate one line and intersect it with its unchanged neighbours."""
    first, second = path[edge_index], path[edge_index + 1]
    direction = second[0] - first[0], second[1] - first[1]
    magnitude = length(first, second)
    if magnitude <= tolerance:
        return None
    normal = -direction[1] / magnitude, direction[0] / magnitude
    shifted = (first[0] + offset * normal[0],
               first[1] + offset * normal[1])
    previous_direction = (first[0] - path[edge_index - 1][0],
                          first[1] - path[edge_index - 1][1])
    following_direction = (
        path[edge_index + 2][0] - second[0],
        path[edge_index + 2][1] - second[1])
    new_first = _line_intersection(
        path[edge_index - 1], previous_direction,
        shifted, direction, tolerance)
    new_second = _line_intersection(
        shifted, direction, second, following_direction, tolerance)
    if new_first is None or new_second is None:
        return None
    return (path[:edge_index] + (new_first, new_second) +
            path[edge_index + 2:])


def _translation_minimum(path, edge_index, tolerance):
    """Exact one-dimensional convex minimization of an interior line shift."""
    def evaluate(offset):
        candidate = _translated_interior_segment(
            path, edge_index, offset, tolerance)
        return float("inf") if candidate is None else path_length(candidate)

    centre = evaluate(0.0)
    step = max((length(path[index], path[index + 1])
                for index in range(max(0, edge_index - 1),
                                   min(len(path) - 1, edge_index + 2))),
               default=1.0)
    left, right = -step, step
    left_value, right_value = evaluate(left), evaluate(right)
    if left_value < centre and left_value <= right_value:
        right = 0.0
        for _expansion in range(64):
            farther = left * 2.0
            farther_value = evaluate(farther)
            if farther_value >= left_value:
                right, left = 0.0, farther
                break
            left, left_value = farther, farther_value
    elif right_value < centre:
        left = 0.0
        for _expansion in range(64):
            farther = right * 2.0
            farther_value = evaluate(farther)
            if farther_value >= right_value:
                right = farther
                break
            right, right_value = farther, farther_value

    golden = (5.0 ** 0.5 - 1.0) / 2.0
    first = right - golden * (right - left)
    second = left + golden * (right - left)
    first_value, second_value = evaluate(first), evaluate(second)
    for _iteration in range(80):
        if right - left <= tolerance:
            break
        if first_value <= second_value:
            right, second, second_value = second, first, first_value
            first = right - golden * (right - left)
            first_value = evaluate(first)
        else:
            left, first, first_value = first, second, second_value
            second = left + golden * (right - left)
            second_value = evaluate(second)
    optimum = (left + right) / 2.0
    candidate = _translated_interior_segment(
        path, edge_index, optimum, tolerance)
    if candidate is None or path_length(candidate) >= centre - tolerance:
        return None
    return candidate


def _translation_targets(path, tolerance):
    return tuple(candidate for edge_index in range(1, len(path) - 2)
                 if (candidate := _translation_minimum(
                     path, edge_index, tolerance)) is not None)


def _objective_resolution(path, quantum):
    """Maximum path-length noise induced by coordinate quantization."""
    return 2.0 * len(path) * quantum


def _maximal_safe_motion(current, target, *, is_safe, quantum,
                         check_deadline=None):
    """Return the last safe state before the first contact on one motion."""
    target = _quantize_aligned(target, quantum)
    if len(target) != len(current):
        return None
    resolution = _objective_resolution(current, quantum)
    if path_length(target) >= path_length(current) - resolution:
        return None
    normalized_target = _normalize(target, quantum)
    if is_safe(normalized_target):
        return normalized_target
    safe, unsafe = 0.0, 1.0
    maximum_motion = max(
        length(a, b) for a, b in zip(current, target))
    ratio_tolerance = quantum / max(maximum_motion, quantum)
    while unsafe - safe > ratio_tolerance:
        if check_deadline is not None:
            check_deadline()
        middle = (safe + unsafe) / 2.0
        candidate = _quantize(_interpolate(current, target, middle), quantum)
        if len(candidate) != len(current):
            unsafe = middle
        elif is_safe(candidate):
            safe = middle
        else:
            unsafe = middle
    candidate = _normalize(_interpolate(current, target, safe), quantum)
    if path_length(candidate) >= path_length(current) - resolution:
        return None
    return candidate


def _project_to_rail(reference, rail):
    start, end = rail.start, rail.end
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return start
    ratio = ((reference[0] - start[0]) * dx +
             (reference[1] - start[1]) * dy) / denominator
    ratio = max(0.0, min(1.0, ratio))
    return start[0] + ratio * dx, start[1] + ratio * dy


def _pad_contact(reference, original, region, quantum):
    if pad_contains(region, reference, tolerance=quantum):
        return reference
    # ``original`` is known to be inside. The closest point along the segment
    # from the other support to the original is therefore a real boundary
    # contact, independent of a sampled direction catalogue.
    outside, inside = reference, original
    if not pad_contains(region, inside, tolerance=quantum):
        return original
    for _iteration in range(64):
        middle = ((outside[0] + inside[0]) / 2.0,
                  (outside[1] + inside[1]) / 2.0)
        if pad_contains(region, middle, tolerance=quantum):
            inside = middle
        else:
            outside = middle
    return inside


def _terminal_targets(path, terminal, at_start, quantum):
    index = 0 if at_start else -1
    neighbour = path[1] if at_start else path[-2]
    targets = []
    for rail in terminal.rails:
        targets.append(_project_to_rail(neighbour, rail))
    for region in terminal.pads:
        targets.append(_pad_contact(
            neighbour, path[index], region, quantum))
    return tuple(sorted(set(targets)))


def contract_polyline(initial, start_terminal, end_terminal, *, is_safe,
                      coordinate_quantum, check_deadline,
                      contact_targets=None, state_observer=None):
    """Contract a complete connection monotonically to a geometric fixed point.

    Every move is a continuous contraction of a complete sub-polyline towards
    its chord, stopped at the first clearance contact. Overlapping spans are
    reconsidered after every accepted state, so contacts can propagate through
    the connection without named geometry patterns.
    """
    quantum = max(float(coordinate_quantum), 1e-9)
    current = _normalize(initial, quantum)
    if len(current) < 2:
        return current, ()
    visited = {current}
    states = []

    while True:
        check_deadline()
        candidates = set()

        # Removing an unsupported portion is the exact first operation of a
        # taut string. It strictly reduces the number of degrees of freedom,
        # so exhaust it before moving any remaining support towards contact.
        for start in range(len(current) - 2):
            for end in range(len(current) - 1, start + 1, -1):
                check_deadline()
                candidate = _normalize(
                    current[:start + 1] + current[end:], quantum)
                if (candidate not in visited and
                        path_length(candidate) <
                        path_length(current) -
                        _objective_resolution(current, quantum) and
                        is_safe(candidate)):
                    candidates.add(candidate)
        if candidates:
            current = min(candidates, key=lambda path: (
                round(path_length(path), 12), len(path), path))
            visited.add(current)
            states.append(current)
            if state_observer is not None:
                state_observer(current)
            continue

        # Pull the complete string first. A contact reached by this motion is
        # globally relevant and avoids solving every proper subspan before the
        # main string has even met its next support.
        target = _straight_targets(current)
        candidate = _maximal_safe_motion(
            current, target, is_safe=is_safe, quantum=quantum,
            check_deadline=check_deadline)
        if candidate is not None and candidate not in visited:
            candidates.add(candidate)
        for terminal, at_start in ((start_terminal, True),
                                   (end_terminal, False)):
            for target_point in _terminal_targets(
                    current, terminal, at_start, quantum):
                target = list(current)
                target[0 if at_start else -1] = target_point
                candidate = _maximal_safe_motion(
                    current, tuple(target), is_safe=is_safe, quantum=quantum,
                    check_deadline=check_deadline)
                if candidate is not None and candidate not in visited:
                    candidates.add(candidate)

        if candidates:
            current = min(candidates, key=lambda path: (
                round(path_length(path), 12), len(path), path))
            visited.add(current)
            states.append(current)
            if state_observer is not None:
                state_observer(current)
            continue

        if contact_targets is not None:
            for target in contact_targets(current):
                check_deadline()
                candidate = _maximal_safe_motion(
                    current, target, is_safe=is_safe, quantum=quantum,
                    check_deadline=check_deadline)
                if candidate is not None and candidate not in visited:
                    candidates.add(candidate)
        # Every internal segment is a genuine continuous degree of freedom:
        # translating its supporting line moves the two adjacent corners while
        # preserving all three directions.  This is the general operation a
        # user performs when manually sliding a segment; it is not a catalogue
        # of doglegs or local geometry patterns.
        for target in _translation_targets(current, quantum):
            check_deadline()
            candidate = _maximal_safe_motion(
                current, target, is_safe=is_safe, quantum=quantum,
                check_deadline=check_deadline)
            if candidate is not None and candidate not in visited:
                candidates.add(candidate)
        if candidates:
            current = min(candidates, key=lambda path: (
                round(path_length(path), 12), len(path), path))
            visited.add(current)
            states.append(current)
            if state_observer is not None:
                state_observer(current)
            continue

        # Once the complete pull is supported, relax each proper subspan. This
        # is the same contraction operation on a smaller interval, not a
        # geometry-pattern fallback.
        for start in range(len(current) - 2):
            for end in range(len(current) - 1, start + 1, -1):
                if start == 0 and end == len(current) - 1:
                    continue
                check_deadline()
                span = current[start:end + 1]
                targets = _straight_targets(span)
                target = current[:start] + targets + current[end + 1:]
                candidate = _maximal_safe_motion(
                    current, target, is_safe=is_safe, quantum=quantum,
                    check_deadline=check_deadline)
                if candidate is not None and candidate not in visited:
                    candidates.add(candidate)

        if not candidates:
            break
        current = min(candidates, key=lambda path: (
            round(path_length(path), 12), len(path), path))
        visited.add(current)
        states.append(current)
        if state_observer is not None:
            state_observer(current)

    return current, tuple(states)


__all__ = ("contract_polyline",)
