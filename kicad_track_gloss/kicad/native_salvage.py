"""Anytime native-DRC recovery for independently planned connections."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..engine.workflow import (combine_plans, interpolate_plan_backoffs,
                               plan_identity,
                               rank_candidate_plans)


@dataclass
class NativeCandidateDecision:
    """Best native-approved plan retained throughout an anytime search."""

    plan: object = None
    native: object = None
    primary_native: object = None
    fallback_used: bool = False
    salvage_used: bool = False
    salvage_attempts: int = 0
    salvage_deadline: bool = False
    connections_retained: int = 0
    connections_planned: int = 0
    initial_portfolio: bool = False
    followup_validations: int = 0
    initial_validation_ms: float = 0.0
    followup_validation_ms: float = 0.0
    salvage_ms: float = 0.0


def _is_better_plan(candidate, incumbent):
    """Return whether candidate outranks an existing approved incumbent."""
    if candidate is None:
        return False
    if incumbent is None:
        return True
    if plan_identity(candidate) == plan_identity(incumbent):
        return False
    ranked = rank_candidate_plans((candidate, incumbent))
    return plan_identity(ranked[0]) == plan_identity(candidate)


def _fixed_endpoint_only(plan):
    """Identify a native-risk core without restricting geometric planning."""
    return (bool(plan.transformations) and
            all(item.mechanism == "fixed_endpoints"
                for item in plan.transformations))


def _compose_available(model, eligible_keys, plans):
    """Greedily retain compatible plans in their existing quality order."""
    accepted = []
    for plan in plans:
        try:
            combine_plans(model, eligible_keys, accepted + [plan])
        except ValueError:
            continue
        accepted.append(plan)
    return (combine_plans(model, eligible_keys, accepted)
            if accepted else None)


def _plan_bounds(model, plan):
    removed = set(plan.remove_keys)
    points = []
    padding = 0.0
    for segment in model.segments:
        if segment.uuid not in removed:
            continue
        points.extend(((segment.start_x, segment.start_y),
                       (segment.end_x, segment.end_y)))
        padding = max(padding, segment.width * 0.5,
                      max(0.0, segment.clearance))
    for addition in plan.additions:
        points.extend((addition.start, addition.end))
        padding = max(padding, addition.width * 0.5,
                      max(0.0, addition.clearance))
    if not points:
        return None
    return (min(point[0] for point in points) - padding,
            min(point[1] for point in points) - padding,
            max(point[0] for point in points) + padding,
            max(point[1] for point in points) + padding)


def _plans_near_findings(model, plans, points):
    suspects = set()
    for plan in plans:
        bounds = _plan_bounds(model, plan)
        if bounds is None:
            continue
        if any(bounds[0] <= x <= bounds[2] and
               bounds[1] <= y <= bounds[3] for x, y in points):
            suspects.add(plan_identity(plan))
    return suspects


def maximize_safe_native_candidates(
        adapter, board, model, eligible_keys, planning_candidates, *,
        conservative_plan, connection_plans, force_native, skip_native,
        operation_deadline, wait_callback, continuation_factory=None):
    """Validate diverse candidates while never losing an approved incumbent.

    Pure geometric rank cannot predict native DRC validity.  The first wave
    therefore pairs the best geometric candidate with the conservative plan,
    when distinct, instead of discarding that safety anchor behind a fixed
    top-N cutoff.  Remaining higher-quality alternatives and connection-local
    salvage may improve the incumbent, but a timeout can only return the best
    plan already approved by KiCad.
    """
    ranked = list(rank_candidate_plans(planning_candidates))
    decision = NativeCandidateDecision()
    if not ranked:
        return decision

    primary = ranked[0]

    # Establish a zero-DRC floor before spending the native budget. Exact
    # copper-equivalent changes and the already supported strict-removal proof
    # are composable and cannot be invalidated by a later risky candidate.
    certificate = getattr(adapter, "native_plan_certificate", None)
    if certificate is not None and not force_native and not skip_native:
        certified = [plan for plan in connection_plans
                     if certificate(board, plan) is not None]
        certified_core = _compose_available(
            model, eligible_keys, certified)
        if (certified_core is not None and
                certificate(board, certified_core) is not None):
            certified_native = adapter.validate_plan(
                board, certified_core, force_native=False,
                skip_native=False, timeout_seconds=0.0,
                wait_callback=wait_callback)
            if certified_native.allowed:
                decision.plan = certified_core
                decision.native = certified_native

    initial = [primary]
    # Validate the three complementary levels in one native wave: global
    # optimum, whole-board conservative plan, and best independent connection.
    # KiCad's baseline DRC is shared, so this preserves both the historical
    # conservative success and a useful local result without another serial
    # baseline run.
    fixed_candidates = [
        plan for plan in rank_candidate_plans(
            tuple(connection_plans) + tuple(ranked))
        if _fixed_endpoint_only(plan)]
    fixed_core = _compose_available(
        model, eligible_keys, fixed_candidates)
    local_anchor = fixed_core or next((
        plan for plan in rank_candidate_plans(connection_plans)
        if plan_identity(plan) != plan_identity(primary)), None)
    conservative_identity = (
        plan_identity(conservative_plan)
        if conservative_plan is not None and conservative_plan.changed else
        None)
    if (conservative_identity is not None and
            conservative_identity != plan_identity(primary)):
        initial.append(conservative_plan)
    if (local_anchor is not None and
            all(plan_identity(local_anchor) != plan_identity(plan)
                for plan in initial)):
        initial.append(local_anchor)
    # A maximal fixed-endpoint translation and its least-invasive qualifying
    # state can differ under KiCad's zone-connectivity authority.  Use any
    # remaining native worker for the next exact fixed-endpoint candidate
    # before considering another movable-terminal basin.
    fixed_visited = [plan for plan in fixed_candidates
                     if not plan.fixed_point]
    fixed_final = [plan for plan in fixed_candidates
                   if plan.fixed_point]
    for fixed in fixed_visited + fixed_final:
        if len(initial) >= 3:
            break
        if all(plan_identity(fixed) != plan_identity(plan)
               for plan in initial):
            initial.append(fixed)
    # Fill every available native process with a distinct geometry.  This is
    # essential for one-connection glosses, which have no independent local
    # connection to use as ``local_anchor``.
    for alternate in ranked[1:]:
        if len(initial) >= 3:
            break
        if all(plan_identity(alternate) != plan_identity(plan)
               for plan in initial):
            initial.append(alternate)
    initial_identities = {plan_identity(plan) for plan in initial}

    remaining = (None if operation_deadline is None else
                 max(0.0, operation_deadline - time.monotonic()))
    stage_started = time.monotonic()
    if len(initial) > 1:
        results = adapter.validate_plan_ladder(
            board, initial, force_native=force_native,
            skip_native=skip_native, timeout_seconds=remaining,
            wait_callback=wait_callback)
        decision.initial_portfolio = True
    else:
        results = [adapter.validate_plan(
            board, initial[0], force_native=force_native,
            skip_native=skip_native, timeout_seconds=remaining,
            wait_callback=wait_callback)]
    decision.initial_validation_ms = (
        time.monotonic() - stage_started) * 1000.0
    decision.primary_native = results[0]
    last_native = results[0]
    for plan, native in zip(initial, results):
        if native.validation_mode == "not_needed":
            continue
        last_native = native
        if native.allowed and _is_better_plan(plan, decision.plan):
            decision.plan = plan
            decision.native = native

    # Infrastructure errors and timeouts are terminal.  A previously approved
    # incumbent remains usable; without one, preserve the error for fail-closed
    # reporting by the caller.
    terminal_error = next((result for result in results
                           if result.error or
                           result.validation_mode == "native_timeout"), None)
    if terminal_error is not None:
        if decision.native is None:
            decision.native = terminal_error
        decision.fallback_used = (
            decision.plan is not None and
            plan_identity(decision.plan) != plan_identity(primary))
        return decision

    # Three native processes are a concurrency width, not a quality cutoff.
    # If the first wave contains no safe state, continue through the remaining
    # geometries in rank order while time remains.  A former implicit top-three
    # rule could turn a perfectly valid fourth local translation into a no-op.
    if decision.plan is None:
        pending_ranked = [
            plan for plan in ranked
            if plan_identity(plan) not in initial_identities]
        for offset in range(0, len(pending_ranked), 3):
            if (operation_deadline is not None and
                    time.monotonic() >= operation_deadline):
                break
            wave = pending_ranked[offset:offset + 3]
            remaining = (None if operation_deadline is None else
                         max(0.0, operation_deadline - time.monotonic()))
            stage_started = time.monotonic()
            if len(wave) > 1:
                wave_results = adapter.validate_plan_ladder(
                    board, wave, force_native=force_native,
                    skip_native=skip_native, timeout_seconds=remaining,
                    wait_callback=wait_callback)
            else:
                wave_results = [adapter.validate_plan(
                    board, wave[0], force_native=force_native,
                    skip_native=skip_native, timeout_seconds=remaining,
                    wait_callback=wait_callback)]
            decision.followup_validation_ms += (
                time.monotonic() - stage_started) * 1000.0
            decision.followup_validations += sum(
                result.validation_mode != "not_needed"
                for result in wave_results)
            for plan, native in zip(wave, wave_results):
                last_native = native
                if native.allowed:
                    decision.plan = plan
                    decision.native = native
                    break
            terminal_error = next((
                result for result in wave_results
                if result.error or result.validation_mode == "native_timeout"),
                None)
            if decision.plan is not None or terminal_error is not None:
                if terminal_error is not None and decision.native is None:
                    decision.native = terminal_error
                break

    canonically_probed = set()

    def continue_incumbent():
        """Resume the complete connection after any native-approved fallback."""
        if (continuation_factory is None or decision.plan is None or
                decision.native is None or not decision.native.allowed):
            return
        identity = plan_identity(decision.plan)
        if identity in canonically_probed:
            return
        continuation_required = (
            not decision.plan.fixed_point or
            identity != plan_identity(primary))
        if not continuation_required:
            canonically_probed.add(identity)
            return
        while (continuation_required and
               (operation_deadline is None or
                time.monotonic() < operation_deadline)):
            continuations = list(continuation_factory(decision.plan))
            if not continuations:
                decision.plan.fixed_point = True
                canonically_probed.add(plan_identity(decision.plan))
                return
            accepted = None
            terminal_error = False
            rejected_taut = None
            for offset in range(0, len(continuations), 3):
                if (operation_deadline is not None and
                        time.monotonic() >= operation_deadline):
                    break
                remaining = (None if operation_deadline is None else
                             max(0.0, operation_deadline - time.monotonic()))
                wave = continuations[offset:offset + 3]
                stage_started = time.monotonic()
                if len(wave) > 1:
                    native_results = adapter.validate_plan_ladder(
                        board, wave, force_native=force_native,
                        skip_native=skip_native, timeout_seconds=remaining,
                        wait_callback=wait_callback)
                else:
                    native_results = [adapter.validate_plan(
                        board, wave[0], force_native=force_native,
                        skip_native=skip_native, timeout_seconds=remaining,
                        wait_callback=wait_callback)]
                decision.followup_validation_ms += (
                    time.monotonic() - stage_started) * 1000.0
                decision.followup_validations += sum(
                    result.validation_mode != "not_needed"
                    for result in native_results)
                accepted = next((
                    (candidate, native) for candidate, native in
                    zip(wave, native_results) if native.allowed), None)
                if accepted is not None:
                    accepted_index = wave.index(accepted[0])
                    rejected_taut = next((
                        candidate for candidate, native in
                        zip(wave[:accepted_index],
                            native_results[:accepted_index])
                        if not native.allowed and not native.error and
                        native.validation_mode != "native_timeout"), None)
                terminal_error = any(
                    native.error or
                    native.validation_mode == "native_timeout"
                    for native in native_results)
                if accepted is not None or terminal_error:
                    break
            if accepted is None:
                decision.plan.fixed_point = False
                return
            if (rejected_taut is not None and
                    (operation_deadline is None or
                     time.monotonic() < operation_deadline)):
                backoffs = list(interpolate_plan_backoffs(
                    model, eligible_keys, accepted[0], rejected_taut))
                if backoffs:
                    remaining = (
                        None if operation_deadline is None else
                        max(0.0, operation_deadline - time.monotonic()))
                    stage_started = time.monotonic()
                    if len(backoffs) > 1:
                        backoff_results = adapter.validate_plan_ladder(
                            board, backoffs, force_native=force_native,
                            skip_native=skip_native,
                            timeout_seconds=remaining,
                            wait_callback=wait_callback)
                    else:
                        backoff_results = [adapter.validate_plan(
                            board, backoffs[0], force_native=force_native,
                            skip_native=skip_native,
                            timeout_seconds=remaining,
                            wait_callback=wait_callback)]
                    decision.followup_validation_ms += (
                        time.monotonic() - stage_started) * 1000.0
                    decision.followup_validations += sum(
                        result.validation_mode != "not_needed"
                        for result in backoff_results)
                    refined = next((
                        (candidate, native) for candidate, native in
                        zip(backoffs, backoff_results) if native.allowed),
                        None)
                    if refined is not None:
                        accepted = refined
            decision.plan, decision.native = accepted
            continuation_required = not decision.plan.fixed_point
        if continuation_required:
            decision.plan.fixed_point = False
        else:
            canonically_probed.add(plan_identity(decision.plan))

    # For a single connection, finishing the physical contraction is more
    # important than exploring unrelated fallback subsets.  Spend the first
    # remaining DRC opportunity on the approved incumbent itself.
    continue_incumbent()

    # A rejected full local composition is only an upper bound.  Its safe
    # subsets may still beat the incumbent, so use the remaining budget while
    # retaining the approved plan as a floor.
    connection_upper = next((
        candidate for candidate in ranked
        if connection_plans and
        set(plan_identity(candidate)[0]) == set().union(*(
            set(plan.remove_keys) for plan in connection_plans))), None)
    should_salvage = bool(connection_plans) and (
        decision.plan is None or connection_upper is None or
        _is_better_plan(connection_upper, decision.plan))
    if (should_salvage and
            (operation_deadline is None or
             time.monotonic() < operation_deadline)):
        stage_started = time.monotonic()
        (partial_plan, partial_native, decision.salvage_attempts,
         decision.salvage_deadline, retained, total) = \
            maximize_safe_native_connections(
                adapter, board, model, eligible_keys, connection_plans,
                force_native=force_native, skip_native=skip_native,
                operation_deadline=operation_deadline,
                wait_callback=wait_callback)
        decision.salvage_ms = (
            time.monotonic() - stage_started) * 1000.0
        if (partial_plan is not None and partial_native is not None and
                partial_native.allowed and
                _is_better_plan(partial_plan, decision.plan)):
            decision.plan = partial_plan
            decision.native = partial_native
            decision.salvage_used = True
            decision.connections_retained = retained
            decision.connections_planned = total
            continue_incumbent()

    # Broad composed alternatives come last: local salvage is anytime and can
    # grow a proven incumbent, whereas one rejected monolithic follow-up can
    # otherwise consume the whole remaining budget without adding any work.
    if decision.plan is not None:
        for candidate in ranked:
            if plan_identity(candidate) in initial_identities:
                continue
            if not _is_better_plan(candidate, decision.plan):
                continue
            if (operation_deadline is not None and
                    time.monotonic() >= operation_deadline):
                break
            remaining = (None if operation_deadline is None else
                         max(0.0, operation_deadline - time.monotonic()))
            stage_started = time.monotonic()
            native = adapter.validate_plan(
                board, candidate, force_native=force_native,
                skip_native=skip_native, timeout_seconds=remaining,
                wait_callback=wait_callback)
            decision.followup_validation_ms += (
                time.monotonic() - stage_started) * 1000.0
            decision.followup_validations += 1
            last_native = native
            if native.allowed and _is_better_plan(candidate, decision.plan):
                decision.plan = candidate
                decision.native = native
                continue_incumbent()
            if native.error or native.validation_mode == "native_timeout":
                if decision.native is None:
                    decision.native = native
                break

    if decision.native is None:
        decision.native = last_native

    continue_incumbent()
    decision.fallback_used = (
        decision.plan is not None and not decision.salvage_used and
        plan_identity(decision.plan) != plan_identity(primary))
    return decision


def maximize_safe_native_connections(
        adapter, board, model, eligible_keys, connection_plans, *,
        force_native, skip_native, operation_deadline, wait_callback):
    """Return the best connection composition validated before the deadline.

    Before a safe base exists, two local plans are probed in one portfolio
    wave. Afterwards the primary candidate contains every remaining plan and
    the fallback adds only the next plan. A broad success ends immediately;
    a rejection can still extend the already safe base in the same DRC wave.
    """
    pending = list(connection_plans)
    accepted = []
    best_plan = None
    best_native = None
    attempts = 0
    deadline_reached = False
    chunks = []
    rejected_identities = set()
    suspects = set()

    def compose(plans):
        try:
            return combine_plans(model, eligible_keys, plans)
        except ValueError:
            return None

    while pending:
        if (operation_deadline is not None and
                time.monotonic() >= operation_deadline):
            deadline_reached = True
            break
        candidates = []
        meanings = []
        if accepted:
            localized = [plan for plan in pending
                         if plan_identity(plan) not in suspects]
            batch = compose(accepted + localized) if localized else None
            if batch is not None:
                candidates.append(batch)
                meanings.append(("batch", tuple(localized)))
            full_batch = compose(accepted + pending)
            if (full_batch is not None and
                    plan_identity(full_batch) not in rejected_identities and
                    all(plan_identity(full_batch) != plan_identity(item)
                        for item in candidates)):
                candidates.append(full_batch)
                meanings.append(("batch", tuple(pending)))
            if not chunks:
                midpoint = max(1, len(pending) // 2)
                chunks = [tuple(pending[:midpoint])]
                if midpoint < len(pending):
                    chunks.append(tuple(pending[midpoint:]))
            # The native ladder supports three candidate DRC processes in one
            # wave. Probe both halves beside the full batch so a bad first
            # half cannot hide a safe second half behind another serial DRC.
            while chunks and len(candidates) < 3:
                chunk = chunks.pop(0)
                incremental = compose(accepted + list(chunk))
                if (incremental is not None and
                        plan_identity(incremental) not in rejected_identities and
                        all(plan_identity(incremental) != plan_identity(item)
                            for item in candidates)):
                    candidates.append(incremental)
                    meanings.append(("chunk", chunk))
        else:
            ordered_pending = sorted(
                pending, key=lambda plan: plan_identity(plan) in suspects)
            for plan in ordered_pending[:3]:
                candidate = compose([plan])
                if (candidate is not None and
                        plan_identity(candidate) not in rejected_identities):
                    candidates.append(candidate)
                    meanings.append(("one", plan))
        if not candidates:
            pending.pop(0)
            continue
        remaining = (None if operation_deadline is None else
                     operation_deadline - time.monotonic())
        if remaining is not None and remaining <= 0.0:
            deadline_reached = True
            break
        if len(candidates) > 1:
            native_results = adapter.validate_plan_ladder(
                board, candidates, force_native=force_native,
                skip_native=skip_native, timeout_seconds=remaining,
                wait_callback=wait_callback)
        else:
            native_results = [adapter.validate_plan(
                board, candidates[0], force_native=force_native,
                skip_native=skip_native, timeout_seconds=remaining,
                wait_callback=wait_callback)]
        attempts += sum(result.validation_mode != "not_needed"
                        for result in native_results)
        accepted_index = next(
            (index for index, result in enumerate(native_results)
             if result.allowed), None)
        if accepted_index is not None:
            kind, payload = meanings[accepted_index]
            best_plan = candidates[accepted_index]
            best_native = native_results[accepted_index]
            if kind == "batch":
                accepted.extend(payload)
                pending.clear()
                break
            additions = (payload if kind == "chunk" else (payload,))
            accepted.extend(additions)
            for plan in additions:
                if plan in pending:
                    pending.remove(plan)
            chunks = []
            continue

        for candidate, result in zip(candidates, native_results):
            if not result.allowed and not result.error:
                rejected_identities.add(plan_identity(candidate))
        finding_points = tuple(point for result in native_results
                               for point in result.finding_points)
        suspects = _plans_near_findings(model, pending, finding_points)

        tested_units = [(kind, payload) for kind, payload in meanings
                        if kind in ("one", "chunk")]
        if not tested_units and len(pending) == 1:
            pending.pop()
        for kind, payload in tested_units:
            plans = (payload if kind == "chunk" else (payload,))
            if kind == "chunk" and len(plans) > 1:
                midpoint = len(plans) // 2
                chunks[0:0] = [plans[:midpoint], plans[midpoint:]]
                continue
            for plan in plans:
                if plan in pending:
                    pending.remove(plan)
        errors = [result for result in native_results if result.error]
        if errors:
            deadline_reached = any(
                result.validation_mode == "native_timeout"
                for result in errors)
            break

    if (operation_deadline is not None and
            time.monotonic() >= operation_deadline):
        deadline_reached = True
    return (best_plan, best_native, attempts, deadline_reached,
            len(accepted), len(connection_plans))


__all__ = (
    "NativeCandidateDecision", "maximize_safe_native_candidates",
    "maximize_safe_native_connections")
