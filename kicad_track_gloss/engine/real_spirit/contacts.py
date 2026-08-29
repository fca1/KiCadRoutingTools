"""Active clearance contacts for continuous polyline descent."""

from __future__ import annotations

import math

from ..candidate_geometry import (circular_obstacle_required_distance,
                                  track_pair_required_distance)
from ..context import line_bbox
from ..geometry import length
from ..model import segment_key
from .obstacles import (circular_envelope, outward_normal, track_envelope)


def _closest_segment_points(a, b, c, d):
    """Return closest points and parameters on two finite 2-D segments."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    wx, wy = a[0] - c[0], a[1] - c[1]
    aa = ux * ux + uy * uy
    bb = ux * vx + uy * vy
    cc = vx * vx + vy * vy
    dd = ux * wx + uy * wy
    ee = vx * wx + vy * wy
    denominator = aa * cc - bb * bb
    if aa <= 1e-18 and cc <= 1e-18:
        return a, c, 0.0, 0.0
    if aa <= 1e-18:
        second = max(0.0, min(1.0, ee / cc))
        return a, (c[0] + second * vx, c[1] + second * vy), 0.0, second
    if cc <= 1e-18:
        first = max(0.0, min(1.0, -dd / aa))
        return (a[0] + first * ux, a[1] + first * uy), c, first, 0.0
    first = 0.0 if abs(denominator) <= 1e-18 else (
        bb * ee - cc * dd) / denominator
    first = max(0.0, min(1.0, first))
    second = (bb * first + ee) / cc
    if second < 0.0:
        second = 0.0
        first = max(0.0, min(1.0, -dd / aa))
    elif second > 1.0:
        second = 1.0
        first = max(0.0, min(1.0, (bb - dd) / aa))
    p = a[0] + first * ux, a[1] + first * uy
    q = c[0] + second * vx, c[1] + second * vy
    return p, q, first, second


def _closest_point_on_segment(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return start, 0.0
    ratio = ((point[0] - start[0]) * dx +
             (point[1] - start[1]) * dy) / denominator
    ratio = max(0.0, min(1.0, ratio))
    return (start[0] + ratio * dx, start[1] + ratio * dy), ratio


def _normal(moving_point, obstacle_point, tolerance):
    dx = moving_point[0] - obstacle_point[0]
    dy = moving_point[1] - obstacle_point[1]
    distance = math.hypot(dx, dy)
    if distance <= tolerance:
        return None
    return dx / distance, dy / distance


def _polygon_contacts(start, end, polygon, tolerance):
    """Exact contacts between a moving edge and a convex envelope boundary."""
    contacts = []
    if len(polygon) < 2:
        return ()
    for obstacle_start, obstacle_end in zip(
            polygon, polygon[1:] + polygon[:1]):
        normal = outward_normal(obstacle_start, obstacle_end)
        if normal is None:
            continue

        def retain(point, obstacle_point, parameter):
            if length(point, obstacle_point) > tolerance:
                return
            contacts.append((max(0.0, min(1.0, parameter)), point, normal))

        point, obstacle_point, parameter, _ = _closest_segment_points(
            start, end, obstacle_start, obstacle_end)
        retain(point, obstacle_point, parameter)
        for obstacle_point in (obstacle_start, obstacle_end):
            point, parameter = _closest_point_on_segment(
                obstacle_point, start, end)
            retain(point, obstacle_point, parameter)
        for parameter, point in ((0.0, start), (1.0, end)):
            obstacle_point, _ = _closest_point_on_segment(
                point, obstacle_start, obstacle_end)
            retain(point, obstacle_point, parameter)
    return tuple(sorted(set(
        (round(parameter, 12),
         (round(point[0], 12), round(point[1], 12)),
         (round(normal[0], 12), round(normal[1], 12)))
        for parameter, point, normal in contacts)))


def _active_normals(model, path, vertex_index, moving, replaced_keys,
                    context):
    """Linearized feasible half-spaces at one supported path vertex."""
    quantum = max(model.coordinate_quantum_mm, 1e-9)
    normals = []
    edges = []
    if vertex_index > 0:
        edges.append((path[vertex_index - 1], path[vertex_index], 1.0))
    if vertex_index + 1 < len(path):
        edges.append((path[vertex_index], path[vertex_index + 1], 0.0))
    for start, end, moving_vertex_parameter in edges:
        margin = (moving.width / 2.0 + context.max_segment_halfwidth +
                  context.max_net_clearance + quantum)
        for foreign in context.segments.query(line_bbox(start, end, margin)):
            if (segment_key(foreign) in replaced_keys or
                    foreign.layer != moving.layer or
                    foreign.net_id == moving.net_id):
                continue
            for parameter, _point, normal in _polygon_contacts(
                    start, end, track_envelope(model, moving, foreign),
                    2.0 * quantum):
                coefficient = (parameter if moving_vertex_parameter == 1.0
                               else 1.0 - parameter)
                if coefficient > quantum:
                    normals.append(normal)

        obstacle_margin = (context.max_obstacle_radius + moving.width / 2.0 +
                           context.max_net_clearance + quantum)
        for obstacle in context.obstacles.query(
                line_bbox(start, end, obstacle_margin)):
            if (obstacle.net_id == moving.net_id or
                    (obstacle.layers and moving.layer not in obstacle.layers)):
                continue
            for parameter, _point, normal in _polygon_contacts(
                    start, end, circular_envelope(model, moving, obstacle),
                    2.0 * quantum):
                coefficient = (parameter if moving_vertex_parameter == 1.0
                               else 1.0 - parameter)
                if coefficient > quantum:
                    normals.append(normal)
    return tuple(sorted(set((round(x, 12), round(y, 12))
                            for x, y in normals)))


def _project_to_feasible_cone(desired, normals, tolerance):
    if not normals:
        return desired

    def feasible(candidate):
        return all(candidate[0] * nx + candidate[1] * ny >= -tolerance
                   for nx, ny in normals)

    candidates = [(0.0, 0.0)]
    if feasible(desired):
        candidates.append(desired)
    for nx, ny in normals:
        component = desired[0] * nx + desired[1] * ny
        candidate = desired[0] - component * nx, desired[1] - component * ny
        if feasible(candidate):
            candidates.append(candidate)
    return min(candidates, key=lambda candidate: (
        (candidate[0] - desired[0]) ** 2 +
        (candidate[1] - desired[1]) ** 2,
        candidate))


def _length_derivative(previous, current, following, direction, distance):
    moved = (current[0] + distance * direction[0],
             current[1] + distance * direction[1])
    derivative = 0.0
    for other in (previous, following):
        dx, dy = moved[0] - other[0], moved[1] - other[1]
        magnitude = math.hypot(dx, dy)
        if magnitude > 1e-15:
            derivative += (dx * direction[0] + dy * direction[1]) / magnitude
    return derivative


def _line_minimum(previous, current, following, direction):
    if _length_derivative(
            previous, current, following, direction, 0.0) >= -1e-12:
        return 0.0
    high = max(length(previous, current), length(current, following), 1.0)
    while _length_derivative(
            previous, current, following, direction, high) < 0.0:
        high *= 2.0
    low = 0.0
    for _iteration in range(64):
        middle = (low + high) / 2.0
        if _length_derivative(
                previous, current, following, direction, middle) < 0.0:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def insert_contact_points(model, path, moving, replaced_keys, context,
                          check_deadline=None):
    """Split the string at every exact active track/via support contact."""
    quantum = max(model.coordinate_quantum_mm, 1e-9)
    output = [path[0]]
    for start, end in zip(path, path[1:]):
        if check_deadline is not None:
            check_deadline()
        contacts = []

        def retain(parameter, location):
            if quantum < parameter < 1.0 - quantum:
                contacts.append((parameter, location))

        margin = (moving.width / 2.0 + context.max_segment_halfwidth +
                  context.max_net_clearance + quantum)
        for foreign in context.segments.query(line_bbox(start, end, margin)):
            if (segment_key(foreign) in replaced_keys or
                    foreign.layer != moving.layer or
                    foreign.net_id == moving.net_id):
                continue
            for parameter, point, _normal in _polygon_contacts(
                    start, end, track_envelope(model, moving, foreign),
                    2.0 * quantum):
                retain(parameter, point)

        obstacle_margin = (context.max_obstacle_radius + moving.width / 2.0 +
                           context.max_net_clearance + quantum)
        for obstacle in context.obstacles.query(
                line_bbox(start, end, obstacle_margin)):
            if (obstacle.net_id == moving.net_id or
                    (obstacle.layers and moving.layer not in obstacle.layers)):
                continue
            for parameter, point, _normal in _polygon_contacts(
                    start, end, circular_envelope(model, moving, obstacle),
                    2.0 * quantum):
                retain(parameter, point)

        for _parameter, location in sorted(set(
                (round(parameter, 12),
                 (round(location[0], 6), round(location[1], 6)))
                for parameter, location in contacts)):
            if length(output[-1], location) > quantum:
                output.append(location)
        if length(output[-1], end) > quantum:
            output.append(end)
    return tuple(output)


def _global_length_derivative(path, directions, distance):
    moved = tuple((value[0] + distance * direction[0],
                   value[1] + distance * direction[1])
                  for value, direction in zip(path, directions))
    derivative = 0.0
    for index, (start, end) in enumerate(zip(moved, moved[1:])):
        edge_length = length(start, end)
        if edge_length <= 1e-15:
            continue
        delta = (directions[index + 1][0] - directions[index][0],
                 directions[index + 1][1] - directions[index][1])
        derivative += ((end[0] - start[0]) * delta[0] +
                       (end[1] - start[1]) * delta[1]) / edge_length
    return derivative


def _repair_clearance(model, path, moving, replaced_keys, context,
                      check_deadline=None):
    """Project a coupled motion back onto exact physical clearance."""
    points = [list(point) for point in path]
    tolerance = max(model.coordinate_quantum_mm, 1e-9)
    for _iteration in range(128):
        if check_deadline is not None:
            check_deadline()
        largest = 0.0
        for edge_index in range(len(points) - 1):
            start, end = tuple(points[edge_index]), tuple(points[edge_index + 1])

            def correct(obstacle_point, moving_point, parameter, required):
                nonlocal largest
                separation = length(moving_point, obstacle_point)
                violation = required - separation
                if violation <= tolerance:
                    return
                normal = _normal(moving_point, obstacle_point, tolerance)
                if normal is None:
                    return
                coefficients = []
                for vertex_index, coefficient in (
                        (edge_index, 1.0 - parameter),
                        (edge_index + 1, parameter)):
                    if 0 < vertex_index < len(points) - 1:
                        coefficients.append((vertex_index, coefficient))
                denominator = sum(value * value for _index, value in
                                  coefficients)
                if denominator <= tolerance * tolerance:
                    return
                # A tiny outward reserve survives coordinate quantization and
                # the following exact safety check.
                displacement = violation + 2.0 * tolerance
                for vertex_index, coefficient in coefficients:
                    scale = displacement * coefficient / denominator
                    points[vertex_index][0] += scale * normal[0]
                    points[vertex_index][1] += scale * normal[1]
                largest = max(largest, violation)

            margin = (moving.width / 2.0 + context.max_segment_halfwidth +
                      context.max_net_clearance + tolerance)
            for foreign in context.segments.query(line_bbox(start, end, margin)):
                if (segment_key(foreign) in replaced_keys or
                        foreign.layer != moving.layer or
                        foreign.net_id == moving.net_id):
                    continue
                p, q, parameter, _ = _closest_segment_points(
                    start, end,
                    (foreign.start_x, foreign.start_y),
                    (foreign.end_x, foreign.end_y))
                correct(q, p, parameter,
                        track_pair_required_distance(model, moving, foreign))

            obstacle_margin = (
                context.max_obstacle_radius + moving.width / 2.0 +
                context.max_net_clearance + tolerance)
            for obstacle in context.obstacles.query(line_bbox(
                    start, end, obstacle_margin)):
                if (obstacle.net_id == moving.net_id or
                        (obstacle.layers and
                         moving.layer not in obstacle.layers)):
                    continue
                centre = obstacle.x, obstacle.y
                p, parameter = _closest_point_on_segment(centre, start, end)
                correct(centre, p, parameter,
                        circular_obstacle_required_distance(
                            model, moving, obstacle))
        if largest <= tolerance:
            break
    return tuple((point[0], point[1]) for point in points)


def _global_contact_target(model, path, moving, replaced_keys, context,
                           check_deadline=None):
    if len(path) < 3:
        return None
    tolerance = max(model.coordinate_quantum_mm, 1e-9)
    desired = []
    for index in range(1, len(path) - 1):
        previous, current, following = path[index - 1:index + 2]
        first_length = length(current, previous)
        second_length = length(current, following)
        if first_length <= tolerance or second_length <= tolerance:
            desired.extend((0.0, 0.0))
            continue
        desired.extend((
            (previous[0] - current[0]) / first_length +
            (following[0] - current[0]) / second_length,
            (previous[1] - current[1]) / first_length +
            (following[1] - current[1]) / second_length,
        ))
    # The physical projection below handles coupled nonlinear clearances.
    # Applying tangent half-spaces before it can falsely freeze a string that
    # starts near two touching rounded caps, so the true length gradient is the
    # trust-region direction and exact clearance performs the projection.
    projected = tuple(desired)
    magnitude = math.sqrt(sum(value * value for value in projected))
    if magnitude <= tolerance:
        return None
    projected = tuple(value / magnitude for value in projected)
    directions = [(0.0, 0.0)]
    directions.extend((projected[index], projected[index + 1])
                      for index in range(0, len(projected), 2))
    directions.append((0.0, 0.0))
    directions = tuple(directions)
    if _global_length_derivative(path, directions, 0.0) >= -tolerance:
        return None
    distance = max((length(a, b) for a, b in zip(path, path[1:])),
                   default=1.0)
    candidates = []
    while distance >= tolerance:
        if check_deadline is not None:
            check_deadline()
        proposed = tuple((value[0] + distance * direction[0],
                          value[1] + distance * direction[1])
                         for value, direction in zip(path, directions))
        repaired = _repair_clearance(
            model, proposed, moving, replaced_keys, context,
            check_deadline=check_deadline)
        if path_length := sum(length(a, b) for a, b in
                              zip(repaired, repaired[1:])):
            if path_length < sum(length(a, b) for a, b in
                                 zip(path, path[1:])) - tolerance:
                candidates.append(repaired)
        distance /= 2.0
    return min(candidates, key=lambda candidate: (
        sum(length(a, b) for a, b in zip(candidate, candidate[1:])),
        candidate), default=None)


def contact_descent_targets(model, path, moving, replaced_keys, context,
                            check_deadline=None):
    """Return exact one-vertex descent targets projected along contacts."""
    tolerance = max(model.coordinate_quantum_mm, 1e-9)
    targets = []
    combined = list(path)
    changed_indices = []
    for index in range(1, len(path) - 1):
        if check_deadline is not None:
            check_deadline()
        previous, current, following = path[index - 1:index + 2]
        first_length = length(current, previous)
        second_length = length(current, following)
        if first_length <= tolerance or second_length <= tolerance:
            continue
        desired = (
            (previous[0] - current[0]) / first_length +
            (following[0] - current[0]) / second_length,
            (previous[1] - current[1]) / first_length +
            (following[1] - current[1]) / second_length,
        )
        normals = _active_normals(
            model, path, index, moving, replaced_keys, context)
        direction = _project_to_feasible_cone(desired, normals, tolerance)
        magnitude = math.hypot(*direction)
        if magnitude <= tolerance:
            continue
        direction = direction[0] / magnitude, direction[1] / magnitude
        distance = _line_minimum(
            previous, current, following, direction)
        if distance <= tolerance:
            continue
        target = list(path)
        target[index] = (
            current[0] + distance * direction[0],
            current[1] + distance * direction[1])
        targets.append(tuple(target))
        combined[index] = target[index]
        changed_indices.append(index)
    if len(changed_indices) > 1:
        targets.append(tuple(combined))
    global_target = _global_contact_target(
        model, path, moving, replaced_keys, context,
        check_deadline=check_deadline)
    if global_target is not None:
        targets.insert(0, global_target)
    return tuple(targets)


__all__ = ("contact_descent_targets", "insert_contact_points")
