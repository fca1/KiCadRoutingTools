"""Validated defaults and process-local session policy for Track Gloss."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("internal_config.json")


@dataclass(frozen=True)
class GlossPolicy:
    minimum_saved_length_mm: float


@dataclass(frozen=True)
class SafetyPolicy:
    use_kicad_native_drc: bool


@dataclass(frozen=True)
class TimingPolicy:
    interactive_total_time_budget_seconds: float
    cli_total_time_budget_seconds: float | None


@dataclass(frozen=True)
class InternalConfig:
    schema_version: int
    gloss: GlossPolicy
    timing: TimingPolicy
    safety: SafetyPolicy


def _positive_number(value, field, *, allow_zero=False):
    minimum_ok = value >= 0.0 if allow_zero else value > 0.0
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not minimum_ok):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError("{} must be a finite {} number".format(
            field, qualifier))
    return float(value)


def load_internal_config(path=CONFIG_PATH):
    """Load and strictly validate the packaged internal policy document."""
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "cannot load Track Gloss internal configuration: {}".format(error))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("unsupported Track Gloss configuration schema")
    try:
        gloss = document["gloss"]
        timing = document["timing"]
        safety = document["safety"]
        minimum = gloss["minimum_saved_length_mm"]
        use_native_drc = safety["use_kicad_native_drc"]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "missing Track Gloss internal configuration field: {}".format(error))
    if (isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or
            not math.isfinite(minimum) or minimum < 0.0):
        raise ValueError(
            "gloss.minimum_saved_length_mm must be a finite non-negative number")
    if not isinstance(use_native_drc, bool):
        raise ValueError("safety.use_kicad_native_drc must be a boolean")
    total_budget = _positive_number(
        timing.get("interactive_total_time_budget_seconds"),
        "timing.interactive_total_time_budget_seconds")
    cli_budget = timing.get("cli_total_time_budget_seconds")
    if cli_budget is not None:
        cli_budget = _positive_number(
            cli_budget, "timing.cli_total_time_budget_seconds")
    return InternalConfig(
        schema_version=1,
        gloss=GlossPolicy(float(minimum)),
        timing=TimingPolicy(
            total_budget,
            cli_budget),
        safety=SafetyPolicy(use_native_drc))


CONFIG = load_internal_config()
_SESSION_CONFIG = CONFIG


def get_session_config():
    """Return the policy currently used by both interactive ActionPlugins."""
    return _SESSION_CONFIG


def update_session_config(*, minimum_saved_length_mm,
                          interactive_total_time_budget_seconds,
                          use_kicad_native_drc):
    """Validate and install process-local values; never writes the JSON file."""
    global _SESSION_CONFIG
    minimum = _positive_number(
        minimum_saved_length_mm, "minimum saved length", allow_zero=True)
    total_budget = _positive_number(
        interactive_total_time_budget_seconds, "interactive total time budget")
    if not isinstance(use_kicad_native_drc, bool):
        raise ValueError("KiCad native DRC must be a boolean")
    current = _SESSION_CONFIG
    _SESSION_CONFIG = replace(
        current,
        gloss=replace(
            current.gloss, minimum_saved_length_mm=minimum),
        timing=replace(
            current.timing,
            interactive_total_time_budget_seconds=total_budget),
        safety=replace(
            current.safety,
            use_kicad_native_drc=use_kicad_native_drc))
    return _SESSION_CONFIG


def reset_session_config():
    """Restore packaged defaults, primarily for tests and plugin reloads."""
    global _SESSION_CONFIG
    _SESSION_CONFIG = CONFIG
    return _SESSION_CONFIG
