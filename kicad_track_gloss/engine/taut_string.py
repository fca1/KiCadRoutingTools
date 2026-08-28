"""Deterministic rubber-band contraction for an already routed connection.

This is deliberately not a router.  It keeps the routed connection's two
terminations and repeatedly pulls its existing polyline taut.  Collision and
KiCad-rule knowledge stay outside this module: callers expose already inflated
obstacles through ``is_safe`` and provide continuous contact moves through
``contact_moves``.
"""

from __future__ import annotations

from .geometry import length, octolinear_paths, quantize_path


def _normalize(path, quantum):
    quantized = quantize_path(path, quantum)
    return tuple(point for index, point in enumerate(quantized)
                 if index == 0 or
                 length(quantized[index - 1], point) > quantum)


def _path_length(path):
    return sum(length(a, b) for a, b in zip(path, path[1:]))


def _octolinear_errors(path, quantum):
    errors = 0
    for a, b in zip(path, path[1:]):
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if not (dx <= quantum or dy <= quantum or
                abs(dx - dy) <= quantum):
            errors += 1
    return errors


def _objective(path, quantum):
    return (_octolinear_errors(path, quantum),
            round(_path_length(path), 12), len(path) - 1)


def pull_taut(initial_path, *, is_safe, contact_moves, coordinate_quantum,
              check_deadline):
    """Return successive fixed-endpoint contractions of ``initial_path``.

    Every iteration examines the complete current string.  It may replace any
    sub-chain by its shortest octolinear chord, or move an existing support
    run continuously until it reaches a geometric constraint.  The globally
    best safe contraction wins, then the same rule is applied again.  Because
    the objective decreases strictly and states are quantized to KiCad's
    coordinate domain, this reaches a deterministic fixed point without a
    geometry-dependent pass limit.
    """
    quantum = max(float(coordinate_quantum), 1e-12)
    current = _normalize(initial_path, quantum)
    if len(current) < 2:
        return ()
    states = []
    seen = {current}

    while True:
        check_deadline()
        current_objective = _objective(current, quantum)
        candidates = set()

        # Pull every pair of existing support points together.  Retaining the
        # intervening points when a chord is blocked preserves the homotopy of
        # the routed connection instead of turning gloss into global routing.
        for start in range(len(current) - 2):
            for end in range(len(current) - 1, start + 1, -1):
                check_deadline()
                for chord in octolinear_paths(current[start], current[end]):
                    proposed = _normalize(
                        current[:start] + tuple(chord) + current[end + 1:],
                        quantum)
                    if (proposed not in seen and
                            _objective(proposed, quantum) < current_objective):
                        candidates.add(proposed)

        # A taut string may remain supported by an obstacle even though no
        # vertex can disappear.  Continuous contact moves slide those support
        # runs to their last safe position.
        for proposed in contact_moves(current):
            check_deadline()
            proposed = _normalize(proposed, quantum)
            if (proposed not in seen and
                    _objective(proposed, quantum) < current_objective):
                candidates.add(proposed)

        safe = []
        for candidate in sorted(
                candidates, key=lambda path: (_objective(path, quantum), path)):
            check_deadline()
            if is_safe(candidate):
                safe.append(candidate)
        if not safe:
            break
        current = min(safe, key=lambda path: (_objective(path, quantum), path))
        seen.add(current)
        states.append(current)

    return tuple(states)


__all__ = ("pull_taut",)
