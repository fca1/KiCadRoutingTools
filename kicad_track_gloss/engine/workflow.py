"""Shared planning policies used by the interactive plugin and the CLI.

The front ends deliberately keep different time and convergence budgets, but
they must build equivalent candidates from equivalent scopes. Keeping the
candidate ladder here prevents those policies from drifting apart.
"""

from __future__ import annotations

import time

from .geometry import length, quantize_path, segments_intersect
from .model import AddedSegment, GlossResult, segment_key
from .planner import (_apply_to_model, _compose_refined_plan,
                      generate_converged_plan)
from .terminals import (find_pad_terminal_targets,
                        find_track_terminal_targets)
from .validation import validate_result


def plan_identity(plan):
    """Return a stable, front-end-neutral identity for a composed plan."""
    def canonical_endpoints(addition):
        return tuple(sorted((addition.start, addition.end)))

    additions = tuple(sorted((
        canonical_endpoints(addition), round(addition.width, 6),
        addition.layer, addition.net_id) for addition in plan.additions))
    return tuple(sorted(plan.remove_keys)), additions


def rank_candidate_plans(plans):
    """Deduplicate and rank plans by the shared monotone quality objective."""
    unique = {}
    for plan in plans:
        unique.setdefault(plan_identity(plan), plan)
    return tuple(sorted(unique.values(), key=lambda plan: (
        -plan.angle_corrections, -round(plan.saved_mm, 9),
        -(len(plan.remove_keys) - len(plan.additions)),
        len(plan.additions), plan_identity(plan))))


def interpolate_plan_backoffs(model, eligible_keys, safe_plan, taut_plan):
    """Add only the length needed between a safe and a taut geometry.

    This is the reconstruction half of the rubber-band model.  It applies
    only when both plans edit the same copper with the same segment topology;
    KiCad DRC then chooses the closest safe state to the taut result.
    """
    if (set(safe_plan.remove_keys) != set(taut_plan.remove_keys) or
            len(safe_plan.additions) != len(taut_plan.additions) or
            not safe_plan.additions):
        return ()
    pairs = []
    for safe, taut in zip(safe_plan.additions, taut_plan.additions):
        if ((round(safe.width, 6), safe.layer, safe.net_id,
             round(safe.clearance, 6)) !=
                (round(taut.width, 6), taut.layer, taut.net_id,
                 round(taut.clearance, 6))):
            return ()
        direct = (length(safe.start, taut.start) +
                  length(safe.end, taut.end))
        reverse = (length(safe.start, taut.end) +
                   length(safe.end, taut.start))
        pairs.append((safe, taut if direct <= reverse else AddedSegment(
            taut.end, taut.start, taut.width, taut.layer, taut.net_id,
            taut.clearance)))

    removed = {segment_key(segment): segment for segment in model.segments
               if segment_key(segment) in set(safe_plan.remove_keys)}
    removed_mm = sum(length(
        (segment.start_x, segment.start_y),
        (segment.end_x, segment.end_y)) for segment in removed.values())
    candidates = []
    for ratio in (0.875, 0.75, 0.5):
        additions = []
        valid = True
        for safe, taut in pairs:
            interpolated = quantize_path((
                (safe.start[0] + ratio * (taut.start[0] - safe.start[0]),
                 safe.start[1] + ratio * (taut.start[1] - safe.start[1])),
                (safe.end[0] + ratio * (taut.end[0] - safe.end[0]),
                 safe.end[1] + ratio * (taut.end[1] - safe.end[1])),
            ), model.coordinate_quantum_mm)
            if len(interpolated) != 2:
                valid = False
                break
            a, b = interpolated
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if not (dx <= model.coordinate_quantum_mm or
                    dy <= model.coordinate_quantum_mm or
                    abs(dx - dy) <= model.coordinate_quantum_mm):
                valid = False
                break
            additions.append(AddedSegment(
                a, b, safe.width, safe.layer, safe.net_id, safe.clearance))
        if not valid:
            continue
        candidate = GlossResult(
            remove_keys=list(safe_plan.remove_keys), additions=additions,
            saved_mm=max(0.0, removed_mm - sum(
                length(item.start, item.end) for item in additions)),
            chains_considered=safe_plan.chains_considered,
            chains_changed=safe_plan.chains_changed,
            warnings=list(safe_plan.warnings),
            angle_corrections=safe_plan.angle_corrections,
            convergence_passes=max(
                safe_plan.convergence_passes,
                taut_plan.convergence_passes),
            fixed_point=False)
        try:
            validate_result(model, set(eligible_keys), candidate)
        except ValueError:
            continue
        candidates.append(candidate)
    return rank_candidate_plans(candidates)


def plan_net_ids(model, plan):
    """Return every net modified by a composed plan."""
    removed = set(plan.remove_keys)
    net_ids = {segment.net_id for segment in model.segments
               if segment_key(segment) in removed}
    net_ids.update(addition.net_id for addition in plan.additions)
    return tuple(sorted(net_ids))


def combine_plans(model, eligible_keys, plans):
    """Compose disjoint connection-local plans and run the complete gate.

    Local plans are generated from the same original board.  Their source
    scopes must therefore be disjoint; additions may still interact, so the
    ordinary clearance and connectivity validation remains authoritative on
    every composition.
    """
    plans = tuple(plans)
    segment_by_key = {segment_key(segment): segment
                      for segment in model.segments}
    result = GlossResult()
    for plan in plans:
        result.remove_keys.extend(plan.remove_keys)
        result.additions.extend(plan.additions)
        result.chains_considered += plan.chains_considered
        result.chains_changed += plan.chains_changed
        result.warnings.extend(plan.warnings)
        result.transformations.extend(plan.transformations)
        result.angle_corrections += plan.angle_corrections
        result.convergence_passes = max(
            result.convergence_passes, plan.convergence_passes)
        for key, value in plan.search_counts.items():
            result.search_counts[key] = result.search_counts.get(key, 0) + value
        for key, value in plan.blocking_nets.items():
            result.blocking_nets[key] = result.blocking_nets.get(key, 0) + value
    result.fixed_point = bool(plans) and all(plan.fixed_point for plan in plans)
    removed = set(result.remove_keys)
    removed_mm = sum(length(
        (segment_by_key[key].start_x, segment_by_key[key].start_y),
        (segment_by_key[key].end_x, segment_by_key[key].end_y))
        for key in removed if key in segment_by_key)
    added_mm = sum(length(item.start, item.end) for item in result.additions)
    result.saved_mm = max(0.0, removed_mm - added_mm)
    result.warnings = sorted(set(result.warnings))
    validate_result(model, set(eligible_keys), result,
                    check_connectivity=True)
    return result


def split_plan_components(model, plan):
    """Return independently applicable connected regions of one edit plan.

    Native DRC can reject one local rewrite while another rewrite from the
    same electrical connection is safe.  A plan component contains every
    removed and added segment joined by copper geometry on the same net and
    layer.  Components are validated against their own removal scope, so an
    apparently separate fragment which actually depends on another edit is
    discarded rather than exposed to native salvage.
    """
    segment_by_key = {segment_key(segment): segment
                      for segment in model.segments}
    edits = []
    for key in plan.remove_keys:
        segment = segment_by_key.get(key)
        if segment is None:
            continue
        edits.append(("remove", key,
                      (segment.start_x, segment.start_y),
                      (segment.end_x, segment.end_y),
                      segment.net_id, segment.layer))
    for index, addition in enumerate(plan.additions):
        edits.append(("add", index, addition.start, addition.end,
                      addition.net_id, addition.layer))
    if not edits:
        return ()

    parent = list(range(len(edits)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        first, second = find(first), find(second)
        if first != second:
            parent[second] = first

    for first_index, first in enumerate(edits):
        for second_index in range(first_index + 1, len(edits)):
            second = edits[second_index]
            if first[4:6] != second[4:6]:
                continue
            if segments_intersect(first[2], first[3], second[2], second[3]):
                union(first_index, second_index)

    grouped = {}
    for index, edit in enumerate(edits):
        grouped.setdefault(find(index), []).append(edit)

    components = []
    available_transformations = list(plan.transformations)
    for edits_in_component in grouped.values():
        remove_keys = sorted(
            edit[1] for edit in edits_in_component if edit[0] == "remove")
        addition_indexes = sorted(
            edit[1] for edit in edits_in_component if edit[0] == "add")
        if not remove_keys or not addition_indexes:
            continue
        additions = [plan.additions[index] for index in addition_indexes]
        removed_mm = sum(length(
            (segment_by_key[key].start_x, segment_by_key[key].start_y),
            (segment_by_key[key].end_x, segment_by_key[key].end_y))
            for key in remove_keys)
        added_mm = sum(length(item.start, item.end) for item in additions)
        component = GlossResult(
            remove_keys=remove_keys, additions=additions,
            saved_mm=max(0.0, removed_mm - added_mm),
            chains_considered=1, chains_changed=1,
            convergence_passes=plan.convergence_passes,
            fixed_point=False)

        # Statistics are not needed for safety, but retain an exact matching
        # transformation when diagnostic collection supplied one.
        for transformation in list(available_transformations):
            if (transformation.net_id == edits_in_component[0][4] and
                    transformation.layer == edits_in_component[0][5] and
                    transformation.before_segments == len(remove_keys) and
                    transformation.after_segments == len(additions) and
                    abs(transformation.before_mm - removed_mm) <= 1e-6 and
                    abs(transformation.after_mm - added_mm) <= 1e-6):
                component.transformations.append(transformation)
                available_transformations.remove(transformation)
                break
        try:
            validate_result(model, set(remove_keys), component,
                            check_connectivity=True)
        except ValueError:
            continue
        components.append(component)
    return rank_candidate_plans(components)


def generate_connection_candidates(
        model, eligible_keys, connection_scopes, source_plan, *, min_gain,
        clearance, max_passes, group_max_passes,
        collect_statistics, planning_deadline, cancellation_grace_seconds):
    """Rebuild exact one-selection candidates for a larger selected scope.

    Scopes already modified by the global plan are visited first, then longer
    untouched connections. Every returned plan has independently passed the
    normal engine validation and addresses the original model directly.
    """
    eligible = set(eligible_keys)
    removed = set(source_plan.remove_keys)
    segment_by_key = {segment_key(segment): segment
                      for segment in model.segments}

    def copper(keys):
        return sum(length(
            (segment.start_x, segment.start_y),
            (segment.end_x, segment.end_y))
            for key in keys for segment in (segment_by_key.get(key),)
            if segment is not None)

    scopes = sorted(
        {frozenset(scope) & eligible for scope in connection_scopes
         if frozenset(scope) & eligible},
        key=lambda scope: (
            not bool(scope & removed), -round(copper(scope & removed), 9),
            -round(copper(scope), 9), tuple(sorted(scope))))
    plans = []
    seen = set()
    deadline_reached = False
    rejected = []
    for scope in scopes:
        if (planning_deadline is not None and
                time.monotonic() >= planning_deadline):
            deadline_reached = True
            break
        try:
            plan = generate_converged_plan(
                model, scope, max_passes=max_passes,
                return_partial_on_limit=True,
                batch_group_convergence=False,
                group_max_passes=group_max_passes,
                min_gain=min_gain,
                clearance=clearance,
                collect_statistics=collect_statistics,
                parallel=False, deadline=planning_deadline,
                cancellation_grace_seconds=cancellation_grace_seconds)
        except ValueError as error:
            rejected.append(str(error))
            continue
        except RuntimeError:
            if (planning_deadline is not None and
                    time.monotonic() >= planning_deadline):
                deadline_reached = True
                break
            raise
        if not plan.changed:
            continue
        identity = plan_identity(plan)
        if identity not in seen:
            seen.add(identity)
            plans.append(plan)
    plans.sort(key=lambda plan: (
        -plan.angle_corrections, -round(plan.saved_mm, 9),
        -(len(plan.remove_keys) - len(plan.additions)),
        len(plan.additions), plan_identity(plan)))
    return plans, rejected, deadline_reached


def generate_single_connection_alternatives(
        model, eligible_keys, primary_plan, *, min_gain,
        clearance, group_max_passes,
        collect_statistics, planning_deadline,
        cancellation_grace_seconds):
    """Return complementary local glosses and exact visited states.

    A single selected connection used to expose only the highest-ranked
    geometry to native DRC.  If that geometry moved a sensitive terminal,
    rejection ended the operation even when the same connection admitted a
    safe segment translation. Build alternative basins by retaining the KiCad
    track junctions, pad contacts, or both, and preserve exact intermediate
    states of corridor convergence. These are explicit gloss domains, not
    route-search heuristics.
    """
    candidates = []
    seen = set()

    def retain(plan):
        if not plan.changed or plan_identity(plan) in seen:
            return
        seen.add(plan_identity(plan))
        candidates.append(plan)

    retain(primary_plan)
    has_track_terminals = bool(find_track_terminal_targets(
        model, set(eligible_keys)))
    has_pad_terminals = bool(find_pad_terminal_targets(
        model, set(eligible_keys)))
    policies = [
        # Interior translations and corner cuts form a complete,
        # corridor-preserving domain.  Keep both its optimum and its next
        # qualifying state independently of endpoint policy.
        (0, False, False, True),
        (1, False, False, True),
    ]
    # Electrical endpoint policies precede alternate schedules.  They are
    # distinct optimization domains, not guesses about which geometry KiCad
    # DRC might prefer.  Enumerate every applicable domain and let the shared
    # ranker/native authority decide.
    if has_track_terminals:
        policies.append((0, False, True, False))
    if has_pad_terminals:
        policies.append((0, True, False, False))
    if has_track_terminals or has_pad_terminals:
        policies.append((0, False, False, False))
    policies.extend(((1, True, True, False), (2, True, True, False)))
    if has_track_terminals:
        policies.extend(((1, False, True, False),
                         (2, False, True, False)))
    if has_pad_terminals:
        policies.extend(((1, True, False, False),
                         (2, True, False, False)))
    if has_track_terminals or has_pad_terminals:
        policies.extend(((1, False, False, False),
                         (2, False, False, False)))
    for (opening_solution_rank, allow_track_sliding,
         allow_pad_sliding, preserve_routed_corridor) in policies:
        if (planning_deadline is not None and
                time.monotonic() >= planning_deadline):
            break
        try:
            visited = [] if preserve_routed_corridor else None
            plan = generate_converged_plan(
                model, eligible_keys, max_passes=None,
                return_partial_on_limit=True,
                batch_group_convergence=False,
                group_max_passes=group_max_passes,
                min_gain=min_gain,
                clearance=clearance,
                collect_statistics=collect_statistics,
                parallel=False, deadline=planning_deadline,
                cancellation_grace_seconds=cancellation_grace_seconds,
                conservative_ladder=visited,
                opening_solution_rank=opening_solution_rank,
                use_taut_string=False,
                preserve_routed_corridor=preserve_routed_corridor,
                allow_track_terminal_sliding=allow_track_sliding,
                allow_pad_terminal_sliding=allow_pad_sliding)
        except ValueError:
            continue
        retain(plan)
        for visited_plan in visited or ():
            retain(visited_plan)
    return rank_candidate_plans(candidates)


def generate_single_connection_salvage_plans(
        model, eligible_keys, candidates, *, min_gain, clearance,
        group_max_passes, collect_statistics, planning_deadline,
        cancellation_grace_seconds, replan=True):
    """Build independently validatable units inside one connection.

    Candidate convergence states can contain several disconnected edit
    regions separated by unchanged copper.  Split those regions, then rerun
    each exact removal scope from the original model so endpoint sliding and
    subsequent passes reach that unit's own optimum before native DRC.
    """
    units = []
    seen = set()

    def retain(plan):
        identity = plan_identity(plan)
        if not plan.changed or identity in seen:
            return
        seen.add(identity)
        units.append(plan)

    for candidate in candidates:
        for component in split_plan_components(model, candidate):
            retain(component)

    if not replan:
        return rank_candidate_plans(units)

    scopes = sorted({frozenset(unit.remove_keys) for unit in units},
                    key=lambda scope: (-len(scope), tuple(sorted(scope))))
    for scope in scopes:
        if (planning_deadline is not None and
                time.monotonic() >= planning_deadline):
            break
        visited = []
        try:
            local = generate_converged_plan(
                model, scope, max_passes=None,
                return_partial_on_limit=True,
                batch_group_convergence=False,
                group_max_passes=group_max_passes,
                min_gain=min_gain, clearance=clearance,
                collect_statistics=collect_statistics,
                parallel=False, deadline=planning_deadline,
                conservative_ladder=visited,
                cancellation_grace_seconds=cancellation_grace_seconds)
        except ValueError:
            continue
        except RuntimeError:
            if (planning_deadline is not None and
                    time.monotonic() >= planning_deadline):
                break
            raise
        retain(local)
        for state in visited:
            retain(state)
    return rank_candidate_plans(units)


def generate_plan_continuations(
        model, eligible_keys, base_plan, *, min_gain, clearance,
        group_max_passes, collect_statistics, planning_deadline,
        cancellation_grace_seconds):
    """Return cumulative candidates continuing a native-approved partial plan."""
    current_model, current_eligible = _apply_to_model(
        model, set(eligible_keys), base_plan, base_plan.convergence_passes)
    visited = []
    followup = generate_converged_plan(
        current_model, current_eligible, max_passes=None,
        return_partial_on_limit=True, batch_group_convergence=False,
        group_max_passes=group_max_passes, min_gain=min_gain,
        clearance=clearance, collect_statistics=collect_statistics,
        parallel=False, deadline=planning_deadline,
        conservative_ladder=visited,
        cancellation_grace_seconds=cancellation_grace_seconds)
    if not followup.changed:
        return ()
    local_candidates = [followup]
    local_candidates.extend(state for state in visited if state.changed)
    local_candidates.extend(generate_single_connection_alternatives(
        current_model, current_eligible, followup,
        min_gain=min_gain, clearance=clearance,
        group_max_passes=group_max_passes,
        collect_statistics=collect_statistics,
        planning_deadline=planning_deadline,
        cancellation_grace_seconds=cancellation_grace_seconds))
    local_candidates.extend(generate_single_connection_salvage_plans(
        current_model, current_eligible, local_candidates,
        min_gain=min_gain, clearance=clearance,
        group_max_passes=group_max_passes,
        collect_statistics=collect_statistics,
        planning_deadline=planning_deadline,
        cancellation_grace_seconds=cancellation_grace_seconds,
        replan=True))
    canonical_identity = plan_identity(followup)

    cumulative = []
    for candidate in rank_candidate_plans(local_candidates):
        if (planning_deadline is not None and
                time.monotonic() >= planning_deadline):
            break
        try:
            next_model, next_eligible = _apply_to_model(
                current_model, current_eligible, candidate,
                base_plan.convergence_passes + candidate.convergence_passes)
            combined = _compose_refined_plan(
                model, set(eligible_keys), next_model, next_eligible,
                [base_plan, candidate], [], merge_collinear=True)
        except ValueError:
            continue
        combined.convergence_passes = (
            base_plan.convergence_passes + candidate.convergence_passes)
        # Restricted endpoint policies and split salvage units can reach a
        # fixed point only inside their own domain.  They remain resumable by
        # the complete rubber-band solver; only its canonical follow-up may
        # certify the whole connection.
        combined.fixed_point = (
            candidate.fixed_point and
            plan_identity(candidate) == canonical_identity)
        cumulative.append(combined)
    return rank_candidate_plans(cumulative)


def compose_compatible_connection_plans(model, eligible_keys, plans):
    """Preserve the best compatible local connections with batch isolation."""
    selected = []
    rejected = []

    def extend(batch):
        if not batch:
            return
        try:
            combine_plans(model, eligible_keys, selected + list(batch))
        except ValueError as error:
            rejected.append(str(error))
            if len(batch) == 1:
                return
            midpoint = len(batch) // 2
            extend(batch[:midpoint])
            extend(batch[midpoint:])
            return
        selected.extend(batch)

    extend(tuple(plans))
    if not selected:
        return None, (), rejected
    return (combine_plans(model, eligible_keys, selected),
            tuple(selected), rejected)


__all__ = (
    "combine_plans", "compose_compatible_connection_plans",
    "generate_connection_candidates",
    "generate_plan_continuations",
    "generate_single_connection_alternatives",
    "generate_single_connection_salvage_plans", "plan_identity",
    "plan_net_ids", "rank_candidate_plans", "split_plan_components")
