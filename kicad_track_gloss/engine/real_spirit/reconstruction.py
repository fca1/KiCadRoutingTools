"""Deterministic 0/45/90 reconstruction of a contracted polyline."""

from __future__ import annotations

from ..geometry import length, octolinear_paths, quantize_path
from .copper import path_length


def _collinear(a, b, c, tolerance):
    ab = b[0] - a[0], b[1] - a[1]
    bc = c[0] - b[0], c[1] - b[1]
    return abs(ab[0] * bc[1] - ab[1] * bc[0]) <= tolerance


def _remove_collinear(path, tolerance):
    output = []
    for value in path:
        output.append(value)
        while (len(output) >= 3 and
               _collinear(output[-3], output[-2], output[-1], tolerance)):
            output.pop(-2)
    return tuple(output)


def _normalize(path, quantum):
    quantized = quantize_path(path, quantum)
    return tuple(value for index, value in enumerate(quantized)
                 if index == 0 or length(quantized[index - 1], value) > quantum)


def _progress_on_polyline(reference, value):
    travelled = 0.0
    best = None
    for start, end in zip(reference, reference[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_length = length(start, end)
        denominator = dx * dx + dy * dy
        ratio = 0.0 if denominator <= 1e-18 else max(0.0, min(1.0, (
            (value[0] - start[0]) * dx +
            (value[1] - start[1]) * dy) / denominator))
        projection = start[0] + ratio * dx, start[1] + ratio * dy
        distance = length(value, projection)
        candidate = distance, travelled + ratio * edge_length
        if best is None or candidate < best:
            best = candidate
        travelled += edge_length
    return 0.0 if best is None else best[1]


def reconstruct_octolinear(contracted, *, is_safe, coordinate_quantum,
                           check_deadline, edge_is_safe=None, baseline=None):
    """Return the shortest safe octolinear reconstruction of all supports."""
    quantum = max(float(coordinate_quantum), 1e-9)
    baseline_edges = set()
    if baseline is not None:
        baseline = tuple(baseline)
        baseline_edges = set(zip(baseline, baseline[1:]))
        middle = set(baseline[1:-1]) | set(contracted[1:-1])
        ordered = sorted(middle, key=lambda value: (
            _progress_on_polyline(baseline, value), value))
        supports = (contracted[0],) + tuple(ordered) + (contracted[-1],)
    else:
        supports = tuple(contracted)
    supports = _remove_collinear(supports, quantum)
    if len(supports) < 2:
        return None

    # For a uniform physical track, safety of one reconstructed edge is
    # independent of the other same-net edges. Dynamic programming may then
    # discard unnecessary contraction supports and add exactly the octolinear
    # length needed around a contact without an exponential combination scan.
    if edge_is_safe is not None:
        best = {0: (supports[0],)}
        for end in range(1, len(supports)):
            choices = []
            for start in range(end):
                prefix = best.get(start)
                if prefix is None:
                    continue
                options = list(octolinear_paths(
                    supports[start], supports[end]))
                # The routed copper is the valid incumbent.  Keeping one of
                # its exact edges is not a geometry candidate or a fallback:
                # it lets the dynamic program replace only the portions for
                # which it has proved a shorter safe reconstruction.  This is
                # also robust to KiCad's nanometre-scale endpoint rounding.
                edge = supports[start], supports[end]
                if edge in baseline_edges and edge not in options:
                    options.append(edge)
                for option in options:
                    check_deadline()
                    option = _normalize(option, quantum)
                    if not edge_is_safe(option):
                        continue
                    candidate = _remove_collinear(
                        prefix + option[1:], quantum)
                    choices.append(candidate)
            if choices:
                best[end] = min(set(choices), key=lambda path: (
                    round(path_length(path), 12), len(path), path))
        candidate = best.get(len(supports) - 1)
        if candidate is not None and is_safe(candidate):
            return candidate

    edge_options = []
    for start, end in zip(supports, supports[1:]):
        options = tuple(sorted(set(
            _normalize(path, quantum)
            for path in octolinear_paths(start, end))))
        if not options:
            return None
        edge_options.append(options)

    safe = []

    def visit(index, path):
        check_deadline()
        if index == len(edge_options):
            candidate = _remove_collinear(_normalize(path, quantum), quantum)
            if is_safe(candidate):
                safe.append(candidate)
            return
        for option in edge_options[index]:
            visit(index + 1, path + option[1:])

    visit(0, (supports[0],))
    if not safe:
        return None
    return min(set(safe), key=lambda path: (
        round(path_length(path), 12), len(path), path))


__all__ = ("reconstruct_octolinear",)
