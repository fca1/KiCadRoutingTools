"""Pure parsing and comparison of KiCad JSON DRC reports."""

from __future__ import annotations

from collections import Counter
import json


def _freeze(value):
    """Return an order-independent but otherwise exact JSON identity."""
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item))
                            for key, item in value.items()))
    if isinstance(value, list):
        frozen = [_freeze(item) for item in value]
        return tuple(sorted(frozen, key=repr))
    return value


def json_report_summary(text):
    document = json.loads(text)
    records = list(document.get("violations", ())) + list(
        document.get("unconnected_items", ()))
    counts = Counter()
    fingerprints = Counter()
    for record in records:
        kind = record.get("type", "unknown")
        counts[kind] += 1
        fingerprints[(kind, _freeze(record))] += 1
    return counts, fingerprints


def json_report_evidence(text):
    """Map exact finding identities to the positions reported by KiCad."""
    document = json.loads(text)
    records = list(document.get("violations", ())) + list(
        document.get("unconnected_items", ()))
    evidence = {}
    for record in records:
        kind = record.get("type", "unknown")
        points = []
        for item in record.get("items", ()):
            position = item.get("pos") or item.get("position") or {}
            try:
                points.append((float(position["x"]), float(position["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        evidence[(kind, _freeze(record))] = tuple(points)
    return evidence


def drc_increases(before, after, before_fingerprints, after_fingerprints):
    """Return new findings without treating ratsnest relocation as a fault.

    KiCad recreates the JSON identity and position of ``unconnected_items``
    when touched tracks are rebuilt.  Their stable native signal is the
    category count; all geometric DRC records retain exact comparison.
    """
    new_records = after_fingerprints - before_fingerprints
    increases = Counter()
    for (kind, _record), count in new_records.items():
        if kind != "unconnected_items":
            increases[kind] += count
    unconnected_delta = (after.get("unconnected_items", 0) -
                         before.get("unconnected_items", 0))
    if unconnected_delta > 0:
        increases["unconnected_items"] = unconnected_delta
    return increases


__all__ = ("drc_increases", "json_report_evidence", "json_report_summary")
