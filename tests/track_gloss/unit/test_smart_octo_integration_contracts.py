from pathlib import Path

from kicad_track_gloss.kicad.diagnostics import split_diagnostic_report


ROOT = Path(__file__).resolve().parents[3]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_plugin_has_one_planner_and_at_most_one_corrective_native_gate():
    action = source("kicad_track_gloss/action_plugin.py")
    assert "plan_selected_copper(" in action
    assert action.count("adapter.validate_plan(") == 2
    assert "while not native.allowed" not in action
    assert "native_salvage" not in action
    assert "candidate_ladder" not in action


def test_session_dialog_exposes_only_the_single_total_budget():
    dialog = source("kicad_track_gloss/kicad/settings_dialog.py")
    assert "Total interactive budget (s)" in dialog
    assert "Planning budget" not in dialog
    assert "cancellation grace" not in dialog.lower()


def test_busy_cursor_is_delayed_and_no_progress_dialog_remains():
    action = source("kicad_track_gloss/action_plugin.py")
    assert "BUSY_CURSOR_DELAY_SECONDS = 3.0" in action
    assert "wx.BeginBusyCursor()" in action
    assert "ProgressDialog" not in action


def test_smart_octo_overlay_is_separate_and_removable():
    action = source("kicad_track_gloss/action_plugin.py")
    overlay = source("kicad_track_gloss/kicad/smart_octo_overlay.py")
    assert "KiCadTrackGlossSmartOctoOverlayPlugin" in action
    assert "TrackGloss Smart Octo Overlay" in overlay
    assert "remove_overlay" in overlay
    assert "User_" in overlay


def test_diagnostic_summary_keeps_only_decision_information():
    summary, details, json_lines = split_diagnostic_report([
        "Plugin version: 2.1.0",
        "File: board.kicad_pcb",
        "Path: C:/boards/board.kicad_pcb",
        "Scope: 1 selected connection(s), 1 net(s): GND",
        "Outcome: no modification.",
        "Gain: 0.000000 mm.",
        "DRC: not required (no candidate).",
        "Primary reason: already at fixed point.",
        "Total time: 0.120 s.",
    ])
    assert summary == [
        "File: board.kicad_pcb",
        "Path: C:/boards/board.kicad_pcb",
        "Scope: 1 selected connection(s), 1 net(s): GND",
        "Outcome: no modification.",
        "Gain: 0.000000 mm.",
        "DRC: not required (no candidate).",
        "Primary reason: already at fixed point.",
        "Total time: 0.120 s.",
    ]
    assert details[0] == "Plugin version: 2.1.0"
    assert json_lines == [
        "No machine-readable result is available for this run."]
