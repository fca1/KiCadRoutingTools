"""Deterministic fixed-point planner for the Real Spirit gloss engine."""

from __future__ import annotations

import time

from ..candidate_geometry import retain_identity_replacements
from ..context import PlannerContext
from ..geometry import length
from ..model import BoardModel, GlossResult, Segment, Transformation, segment_key
from ..validation import validate_result
from .contraction import contract_polyline
from .contacts import contact_descent_targets, insert_contact_points
from .copper import map_path_to_copper, path_is_safe, path_length
from .reconstruction import reconstruct_octolinear
from .topology import extract_chains


class PlanningDeadlineExceeded(RuntimeError):
    pass


def _check(deadline, cancel_check):
    if cancel_check is not None and cancel_check():
        raise RuntimeError("Track Gloss was cancelled by the user")
    if deadline is not None and time.monotonic() >= deadline:
        raise PlanningDeadlineExceeded("Total operation budget reached")


def _plan_once(model, eligible, *, min_gain, deadline, cancel_check,
               reverse=False):
    context = PlannerContext(model)
    baseline_cover = frozenset(context.segment_by_key)
    result = GlossResult(fixed_point=True)

    def check():
        _check(deadline, cancel_check)

    chains = list(extract_chains(model, eligible))
    if reverse:
        chains.reverse()
    for chain in chains:
        check()
        result.chains_considered += 1

        def safe(path):
            return path_is_safe(
                model, path, chain.segments, context=context,
                immutable_cover_keys=baseline_cover,
                check_deadline=check)

        initial_path = insert_contact_points(
            model, chain.points, chain.segments[0], frozenset(chain.keys),
            context, check_deadline=check)
        contracted, _states = contract_polyline(
            initial_path, chain.start, chain.end, is_safe=safe,
            coordinate_quantum=model.coordinate_quantum_mm,
            check_deadline=check,
            contact_targets=lambda path: contact_descent_targets(
                model, path, chain.segments[0], frozenset(chain.keys),
                context, check_deadline=check))
        rebuilt = reconstruct_octolinear(
            contracted, is_safe=safe,
            coordinate_quantum=model.coordinate_quantum_mm,
            check_deadline=check, baseline=chain.points,
            edge_is_safe=(safe if len({
                (round(segment.width, 6), round(segment.clearance, 6))
                for segment in chain.segments}) == 1 else None))
        if rebuilt is None:
            continue
        before, after = path_length(chain.points), path_length(rebuilt)
        gain = before - after
        additions = map_path_to_copper(
            rebuilt, chain.segments, chain.layer, chain.net_id)
        simplifies = len(additions) < len(chain.segments)
        if (gain < min_gain - model.coordinate_quantum_mm and
                not (simplifies and gain >= -model.coordinate_quantum_mm)):
            continue
        if (abs(gain) <= model.coordinate_quantum_mm and
                len(additions) >= len(chain.segments)):
            continue
        result.remove_keys.extend(chain.keys)
        result.additions.extend(additions)
        result.chains_changed += 1
        net_name = next((segment.net_name for segment in chain.segments
                         if segment.net_name), "")
        result.transformations.append(Transformation(
            "taut_polyline", "continuous_contraction", chain.net_id,
            net_name, chain.layer, chain.segments[0].width,
            before, after, len(chain.segments), len(additions)))
    retain_identity_replacements(model, result)
    result.saved_mm = sum(item.saved_mm for item in result.transformations)
    if result.changed:
        try:
            validate_result(
                model, set(eligible), result, check_connectivity=True)
        except ValueError as error:
            rejected = GlossResult(fixed_point=True)
            rejected.warnings.append(str(error))
            return rejected
    return result


def _apply_to_model(model, editable, plan, generation):
    removed = set(plan.remove_keys)
    source_by_net = {}
    retained = []
    next_editable = set(editable) - removed
    for segment in model.segments:
        if segment_key(segment) in removed:
            source_by_net.setdefault(segment.net_id, segment)
        else:
            retained.append(segment)
    for index, addition in enumerate(plan.additions):
        source = source_by_net.get(addition.net_id)
        key = "real-spirit:{}:{}".format(generation, index)
        segment = Segment(
            addition.start[0], addition.start[1],
            addition.end[0], addition.end[1], addition.width,
            addition.layer, addition.net_id, key,
            net_name="" if source is None else source.net_name,
            clearance=addition.clearance)
        retained.append(segment)
        next_editable.add(key)
    return (BoardModel(
        retained, model.obstacles, model.keepouts, model.net_clearances,
        model.minimum_clearance, model.copper_edge_clearance,
        model.board_bounds, model.pad_regions, model.board_outline,
        model.coordinate_quantum_mm), next_editable)


def _final_plan(original, working, original_eligible, editable,
                transformations, passes, fixed_point, chains_considered):
    result = GlossResult(
        remove_keys=list(original_eligible),
        transformations=list(transformations),
        convergence_passes=passes, fixed_point=fixed_point,
        chains_considered=chains_considered)
    for segment in working.segments:
        if segment_key(segment) not in editable:
            continue
        result.additions.extend(map_path_to_copper(
            ((segment.start_x, segment.start_y),
             (segment.end_x, segment.end_y)),
            (segment,), segment.layer, segment.net_id))
    retain_identity_replacements(original, result)
    result.saved_mm = max(0.0, sum(
        length((segment.start_x, segment.start_y),
               (segment.end_x, segment.end_y))
        for segment in original.segments
        if segment_key(segment) in original_eligible) - sum(
            length((segment.start_x, segment.start_y),
                   (segment.end_x, segment.end_y))
            for segment in working.segments
            if segment_key(segment) in editable))
    result.chains_changed = len(transformations)
    if result.changed:
        validate_result(original, set(original_eligible), result,
                        check_connectivity=True)
    return result


def plan_selected_copper(model, eligible_segment_keys, *, min_gain=0.0,
                         deadline=None, cancel_check=None):
    """Gloss all authorized copper, retaining the best complete incumbent."""
    original_eligible = frozenset(str(key) for key in eligible_segment_keys)
    working, editable = model, set(original_eligible)
    transformations = []
    passes = 0
    attempts = 0
    chains_considered = 0
    fixed_point = False
    generation = 0
    try:
        while True:
            _check(deadline, cancel_check)
            changed = False
            net_ids = sorted({segment.net_id for segment in working.segments
                              if segment_key(segment) in editable})
            if attempts % 2:
                net_ids.reverse()
            for net_id in net_ids:
                _check(deadline, cancel_check)
                local = {segment_key(segment) for segment in working.segments
                         if (segment_key(segment) in editable and
                             segment.net_id == net_id)}
                chains = list(extract_chains(working, local))
                if attempts % 2:
                    chains.reverse()
                for chain in chains:
                    plan = _plan_once(
                        working, set(chain.keys), min_gain=min_gain,
                        deadline=deadline, cancel_check=cancel_check)
                    chains_considered += plan.chains_considered
                    if not plan.changed:
                        continue
                    generation += 1
                    working, editable = _apply_to_model(
                        working, editable, plan, generation)
                    transformations.extend(plan.transformations)
                    changed = True
                    passes = attempts + 1
            if not changed:
                fixed_point = True
                break
            attempts += 1
    except PlanningDeadlineExceeded:
        fixed_point = False

    return _final_plan(
        model, working, original_eligible, editable, transformations,
        passes, fixed_point, chains_considered)


__all__ = ("PlanningDeadlineExceeded", "plan_selected_copper")
