"""One-shot localization of a native DRC rejection."""

from __future__ import annotations

from copy import deepcopy

from ..geometry import point_segment_distance
from ..model import segment_key
from ..validation import validate_result


def localized_drc_remainder(model, eligible_keys, plan, finding_points):
    """Drop every modified net nearest a new native DRC finding.

    KiCad zones are not part of the API-neutral obstacle snapshot.  When the
    one global native validation discovers such an interaction, its reported
    positions are the only available authority for attribution.  This function
    performs one deterministic localization; callers may validate the single
    remainder once, but must not iterate or search subsets.
    """
    if not plan.changed or not finding_points:
        return None
    by_key = {segment_key(segment): segment for segment in model.segments}
    primitives = []
    for key in plan.remove_keys:
        segment = by_key.get(key)
        if segment is not None:
            primitives.append((
                (segment.start_x, segment.start_y),
                (segment.end_x, segment.end_y), segment.net_id))
    primitives.extend((addition.start, addition.end, addition.net_id)
                      for addition in plan.additions)
    if not primitives:
        return None
    rejected_nets = set()
    for point in finding_points:
        _distance, net_id = min(
            (point_segment_distance(point, start, end), net_id)
            for start, end, net_id in primitives)
        rejected_nets.add(net_id)

    remainder = deepcopy(plan)
    remainder.remove_keys = [
        key for key in plan.remove_keys
        if key in by_key and by_key[key].net_id not in rejected_nets]
    remainder.additions = [
        addition for addition in plan.additions
        if addition.net_id not in rejected_nets]
    remainder.transformations = [
        item for item in plan.transformations
        if item.net_id not in rejected_nets]
    remainder.saved_mm = sum(
        item.saved_mm for item in remainder.transformations)
    remainder.chains_changed = len(remainder.transformations)
    if not remainder.changed or not remainder.remove_keys:
        return None
    retained_eligible = {
        key for key in eligible_keys
        if key in by_key and by_key[key].net_id not in rejected_nets}
    validate_result(
        model, retained_eligible, remainder, check_connectivity=True)
    return remainder


__all__ = ("localized_drc_remainder",)
