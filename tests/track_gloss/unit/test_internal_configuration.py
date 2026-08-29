import json
import pytest

from kicad_track_gloss.configuration import (
    CONFIG, get_session_config, load_internal_config, reset_session_config,
    update_session_config)
from kicad_track_gloss.kicad.native_validation import validate_native_plan


def test_current_internal_policy_preserves_release_behavior():
    assert CONFIG.schema_version == 1
    assert CONFIG.gloss.minimum_saved_length_mm == pytest.approx(0.2)
    assert CONFIG.timing.interactive_total_time_budget_seconds == 20.0
    assert CONFIG.timing.cli_total_time_budget_seconds is None
    assert CONFIG.safety.use_kicad_native_drc is True


def test_internal_policy_rejects_wrong_types(tmp_path):
    document = {
        "schema_version": 1,
        "gloss": {"minimum_saved_length_mm": 0.01},
        "timing": {
            "interactive_total_time_budget_seconds": 10.0,
            "cli_total_time_budget_seconds": None,
        },
        "safety": {"use_kicad_native_drc": "yes"},
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a boolean"):
        load_internal_config(path)


def test_session_policy_can_explicitly_skip_native_drc():
    result = validate_native_plan(None, None, None, skip_native=True)
    assert result.allowed
    assert result.validation_mode == "native_drc_disabled"


def test_native_drc_policy_rejects_conflicting_modes():
    with pytest.raises(ValueError, match="both forced and skipped"):
        validate_native_plan(
            None, None, None, force_native=True, skip_native=True)


def test_session_policy_changes_are_validated_and_not_persisted():
    try:
        changed = update_session_config(
            minimum_saved_length_mm=0.025,
            interactive_total_time_budget_seconds=20.0,
            use_kicad_native_drc=False)
        assert get_session_config() is changed
        assert changed.gloss.minimum_saved_length_mm == pytest.approx(0.025)
        assert changed.timing.interactive_total_time_budget_seconds == 20.0
        assert not changed.safety.use_kicad_native_drc
        assert CONFIG.gloss.minimum_saved_length_mm == pytest.approx(0.2)
        with pytest.raises(ValueError, match="positive"):
            update_session_config(
                minimum_saved_length_mm=0.01,
                interactive_total_time_budget_seconds=0.0,
                use_kicad_native_drc=True)
    finally:
        reset_session_config()
