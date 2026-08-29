"""KiCad 10 ActionPlugin entry points for the Real Spirit gloss engine."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
import traceback

import pcbnew
import wx

from .configuration import get_session_config
from .engine.model import segment_key
from .engine.real_spirit import (localized_drc_remainder,
                                 plan_selected_copper)
from .engine.statistics import summarize_plan
from .kicad import BoardAdapter
from .kicad.native_validation import start_native_baseline_warmup
from .kicad.report_dialog import (show_diagnostic_report as _show_diagnostic_report,
                                  show_report as _show_report,
                                  warning_bell as _warning_bell)
from .kicad.settings_dialog import show_session_settings
from .kicad.types import is_arc, is_straight_track, is_via
from .version import __version__


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = logging.getLogger("KiCadTrackGloss")
BUSY_CURSOR_DELAY_SECONDS = 3.0
BUSY_CURSOR_POLL_SECONDS = 0.05


class NoTrackSelection(ValueError):
    pass


def _show_session_settings():
    return show_session_settings()


def _busy_cursor_controller(operation_started,
                            delay_seconds=BUSY_CURSOR_DELAY_SECONDS):
    busy_started = False

    def wait_callback():
        nonlocal busy_started
        if (not busy_started and
                time.monotonic() - operation_started >= delay_seconds):
            try:
                wx.BeginBusyCursor()
                busy_started = True
            except Exception:
                LOG.exception("Could not display the Track Gloss busy cursor")
        try:
            if hasattr(wx, "YieldIfNeeded"):
                wx.YieldIfNeeded()
        except Exception:
            LOG.exception("Could not refresh the Track Gloss busy cursor")

    def close():
        if busy_started:
            try:
                wx.EndBusyCursor()
            except Exception:
                LOG.exception("Could not restore the Track Gloss cursor")
    return wait_callback, close


def _run_api_neutral(function, wait_callback):
    completed = threading.Event()
    outcome = {}

    def worker():
        try:
            outcome["result"] = function()
        except BaseException as error:
            outcome["error"] = error
            outcome["traceback"] = error.__traceback__
        finally:
            completed.set()

    threading.Thread(target=worker, name="KiCadTrackGlossPlanner",
                     daemon=True).start()
    while not completed.wait(BUSY_CURSOR_POLL_SECONDS):
        wait_callback()
    if "error" in outcome:
        raise outcome["error"].with_traceback(outcome["traceback"])
    return outcome["result"]


def _selection_counts(board):
    counts = {"segments": 0, "arcs": 0, "vias": 0, "other": 0}
    for item in board.GetTracks():
        if not item.IsSelected():
            continue
        if is_straight_track(pcbnew, item):
            counts["segments"] += 1
        elif is_arc(pcbnew, item):
            counts["arcs"] += 1
        elif is_via(pcbnew, item):
            counts["vias"] += 1
        else:
            counts["other"] += 1
    return counts


def _net_names(model, keys):
    keys = set(keys)
    return sorted({segment.net_name or "net {}".format(segment.net_id)
                   for segment in model.segments
                   if segment_key(segment) in keys})


def _board_identity(board):
    filename = str(board.GetFileName() or "")
    if not filename:
        return "Unsaved board", "(not saved)"
    path = Path(filename).resolve()
    return path.name, str(path)


class KiCadTrackGlossPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "KiCad Track Gloss"
        self.category = "Routing"
        self.description = "Gloss selected routed copper to a geometric fixed point"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon_24.png")
        dark = os.path.join(PLUGIN_DIR, "icon_24_dark.png")
        if os.path.exists(dark):
            self.dark_icon_file_name = dark

    def Run(self):
        try:
            changed = self._run([])
        except NoTrackSelection:
            try:
                _show_session_settings()
            except Exception:
                LOG.exception("Could not display Track Gloss session settings")
        except Exception:
            _warning_bell()
            LOG.exception("Track gloss failed; the board was left unchanged")
            _show_report("KiCad Track Gloss — Error", [
                "UNEXPECTED ERROR", "Plugin version: " + __version__,
                "The board was left unchanged.", "", traceback.format_exc()])
        else:
            if changed is False:
                _warning_bell()

    def _run(self, report, diagnostic=False):
        started = time.monotonic()
        wait_callback, close_cursor = _busy_cursor_controller(started)
        try:
            return self._run_operation(
                report, diagnostic, started, wait_callback)
        finally:
            close_cursor()

    def _run_operation(self, report, diagnostic, started, wait_callback):
        board = pcbnew.GetBoard()
        if board is None:
            report.append("Result: no active PCB board.")
            return False
        counts = _selection_counts(board)
        if counts["segments"] == 0:
            raise NoTrackSelection()

        config = get_session_config()
        total_budget = config.timing.interactive_total_time_budget_seconds
        operation_deadline = started + total_budget
        # Scheduling reserve only: it is not another user budget.  It keeps a
        # portion of the single total deadline available for the one final DRC.
        validation_reserve = min(8.0, total_budget * 0.40)
        planning_deadline = operation_deadline - validation_reserve
        adapter = BoardAdapter(pcbnew)
        snapshot = adapter.snapshot(board)
        baseline_warmup = (start_native_baseline_warmup(
            adapter, board, timeout_seconds=total_budget)
            if config.safety.use_kicad_native_drc else None)
        filename, filepath = _board_identity(board)
        nets = _net_names(snapshot.model, snapshot.eligible_keys)

        report.extend([
            "Plugin version: " + __version__,
            "KiCad version: " + str(pcbnew.Version()),
            "File: " + filename,
            "Path: " + filepath,
            "Scope: {} selected connection(s), {} net(s): {}".format(
                len(snapshot.connection_scopes), len(nets),
                ", ".join(nets) if nets else "none"),
            "Policy: minimum saving {:.3f} mm; total budget {:.1f} s; "
            "native DRC {}.".format(
                config.gloss.minimum_saved_length_mm, total_budget,
                "enabled" if config.safety.use_kicad_native_drc
                else "disabled"),
        ])

        plan = _run_api_neutral(
            lambda: plan_selected_copper(
                snapshot.model, snapshot.eligible_keys,
                min_gain=config.gloss.minimum_saved_length_mm,
                deadline=planning_deadline), wait_callback)
        if not plan.changed:
            if baseline_warmup is not None:
                baseline_warmup.cancel()
            report.extend([
                "Outcome: no modification.",
                "Gain: 0.000000 mm.",
                "Passes: {}; fixed point: {}.".format(
                    plan.convergence_passes,
                    "yes" if plan.fixed_point else "no"),
                "DRC: not required (no candidate).",
                "Primary reason: no shorter connected octolinear polyline "
                "passed the exact internal geometry checks.",
                "Total time: {:.3f} s.".format(time.monotonic() - started),
            ])
            return False

        remaining = operation_deadline - time.monotonic()
        if config.safety.use_kicad_native_drc and remaining <= 0.0:
            report.extend([
                "Outcome: no modification.",
                "Gain available: {:.6f} mm.".format(plan.saved_mm),
                "DRC: not run; total budget exhausted.",
                "Primary reason: the candidate could not be validated inside "
                "the total time budget.",
            ])
            return False
        if baseline_warmup is not None:
            baseline_warmup.wait(
                timeout_seconds=min(0.25, max(0.0, remaining)),
                wait_callback=wait_callback)
            remaining = operation_deadline - time.monotonic()
        native = adapter.validate_plan(
            board, plan,
            force_native=config.safety.use_kicad_native_drc,
            skip_native=not config.safety.use_kicad_native_drc,
            timeout_seconds=(remaining if
                             config.safety.use_kicad_native_drc else None),
            wait_callback=wait_callback)
        corrective_drc = False
        if (config.safety.use_kicad_native_drc and not native.allowed and
                native.finding_points):
            remainder = localized_drc_remainder(
                snapshot.model, snapshot.eligible_keys, plan,
                native.finding_points)
            remaining = operation_deadline - time.monotonic()
            if remainder is not None and remaining > 0.0:
                corrected_native = adapter.validate_plan(
                    board, remainder, force_native=True,
                    timeout_seconds=remaining, wait_callback=wait_callback)
                if corrected_native.allowed:
                    plan, native = remainder, corrected_native
                    corrective_drc = True
        if not native.allowed:
            increases = ", ".join(
                "{} +{}".format(key, value)
                for key, value in native.increases.items())
            reason = native.error or increases or "native validation rejected the plan"
            report.extend([
                "Outcome: no modification.",
                "Gain available: {:.6f} mm.".format(plan.saved_mm),
                "Passes: {}; fixed point: {}.".format(
                    plan.convergence_passes,
                    "yes" if plan.fixed_point else "no"),
                "DRC: rejected.",
                "Primary reason: " + reason + ".",
                "Total time: {:.3f} s.".format(time.monotonic() - started),
            ])
            return False

        adapter.apply(board, plan, rollback_on_error=True)
        board.SetModified()
        pcbnew.Refresh()
        report.extend([
            "Outcome: GLOSS APPLIED.",
            "Gain: {:.6f} mm.".format(plan.saved_mm),
            "Segments: {} removed, {} added.".format(
                len(plan.remove_keys), len(plan.additions)),
            "Passes: {}; fixed point: {}.".format(
                plan.convergence_passes,
                "yes" if plan.fixed_point else "no"),
            "DRC: {}.".format(
                "disabled by session policy" if
                native.validation_mode == "native_drc_disabled" else
                "validated globally after one localized correction; no "
                "category increase" if corrective_drc else
                "validated globally; no category increase"),
            "Total time: {:.3f} s.".format(time.monotonic() - started),
        ])
        if diagnostic:
            summary = summarize_plan(
                snapshot.model, snapshot.eligible_keys, plan)
            summary.update({
                "file_name": filename, "file_path": filepath,
                "validation_mode": native.validation_mode,
                "corrective_drc": corrective_drc,
                "total_seconds": time.monotonic() - started,
            })
            report.extend(["", "Machine-readable JSON:"])
            report.extend(json.dumps(
                summary, indent=2, sort_keys=True).splitlines())
        return True


class KiCadTrackGlossDiagnosticPlugin(KiCadTrackGlossPlugin):
    def defaults(self):
        self.name = "KiCad Track Gloss — Diagnostic"
        self.category = "Routing"
        self.description = "Run Track Gloss and display its concise diagnostic"
        self.show_toolbar_button = False
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon_24.png")

    def Run(self):
        report = ["KiCad Track Gloss diagnostic", ""]
        try:
            changed = self._run(report, diagnostic=True)
        except NoTrackSelection:
            _show_session_settings()
            return
        except Exception:
            _warning_bell()
            LOG.exception("Track gloss diagnostic run failed")
            report.extend(["", "UNEXPECTED ERROR", "The board was left unchanged.",
                           "", traceback.format_exc()])
        else:
            if changed is False:
                _warning_bell()
        _show_diagnostic_report("KiCad Track Gloss — Diagnostic", report)
