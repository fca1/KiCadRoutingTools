"""One-shot KiCad-native DRC gate for a composed Track Gloss plan."""

from __future__ import annotations

from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

if __package__:
    from .drc_report import (drc_increases as _drc_increases,
                             json_report_evidence as _json_report_evidence,
                             json_report_summary as _json_report_summary)
else:
    # The candidate-board helper deliberately executes this file directly in
    # KiCad's Python process.  Direct scripts have no package parent, but their
    # own directory is importable.  Keep that supported entry point explicit.
    from drc_report import (drc_increases as _drc_increases,
                            json_report_evidence as _json_report_evidence,
                            json_report_summary as _json_report_summary)


@dataclass
class NativeDrcResult:
    allowed: bool
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    increases: dict = field(default_factory=dict)
    error: str = ""
    timings_ms: dict = field(default_factory=dict)
    baseline_cached: bool = False
    validation_mode: str = "native_parallel"
    finding_points: tuple = ()


_CACHE_LIMIT = 8
_baseline_cache = OrderedDict()
_validation_cache = OrderedDict()
_baseline_warmups = {}
_cache_lock = threading.Lock()


class NativeBaselineWarmup:
    """Background baseline DRC whose cache is consumed by final validation."""

    def __init__(self, adapter, board, timeout_seconds, delay_seconds=0.25):
        self._completed = threading.Event()
        self._cancelled = threading.Event()
        self._error = None
        self._temporary = tempfile.TemporaryDirectory(
            prefix="kicad-track-gloss-baseline-")
        root = Path(self._temporary.name)
        self._board_path = root / "baseline.kicad_pcb"
        if not adapter.pcbnew.SaveBoard(str(self._board_path), board):
            self._temporary.cleanup()
            raise RuntimeError("KiCad could not snapshot the current board")
        _copy_project_files(board, self._board_path)
        self._key = _state_digest(adapter, self._board_path)
        if _cache_get(_baseline_cache, self._key) is not None:
            self._temporary.cleanup()
            self._completed.set()
            return
        with _cache_lock:
            _baseline_warmups[self._key] = self

        def worker():
            try:
                if self._cancelled.wait(max(0.0, float(delay_seconds))):
                    return
                counts, fingerprints, _evidence = _run_drc(
                    adapter, self._board_path, root / "baseline.rpt",
                    timeout_seconds=timeout_seconds)
                _cache_put(_baseline_cache, self._key,
                           (Counter(counts), Counter(fingerprints)))
            except Exception as error:
                self._error = error
            finally:
                with _cache_lock:
                    if _baseline_warmups.get(self._key) is self:
                        _baseline_warmups.pop(self._key, None)
                self._temporary.cleanup()
                self._completed.set()

        threading.Thread(
            target=worker, name="TrackGlossBaselineDRC", daemon=True).start()

    def cancel(self):
        """Suppress a delayed DRC when planning produced no candidate."""
        self._cancelled.set()

    def wait(self, timeout_seconds=None, wait_callback=None):
        deadline = (None if timeout_seconds is None else
                    time.monotonic() + max(0.0, timeout_seconds))
        while not self._completed.wait(0.05):
            if wait_callback is not None:
                wait_callback()
            if deadline is not None and time.monotonic() >= deadline:
                return False
        return self._error is None


def start_native_baseline_warmup(adapter, board, timeout_seconds=None,
                                 delay_seconds=0.25):
    """Start the immutable baseline half of the final DRC comparison."""
    return NativeBaselineWarmup(
        adapter, board, timeout_seconds, delay_seconds=delay_seconds)


def _cache_get(cache, key):
    with _cache_lock:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value


def _cache_put(cache, key, value):
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _CACHE_LIMIT:
            cache.popitem(last=False)


def _state_digest(adapter, board_path):
    """Hash the exact snapshot, local rules and KiCad CLI executable state."""
    digest = hashlib.sha256()
    for path in (board_path, board_path.with_suffix(".kicad_pro"),
                 board_path.with_suffix(".kicad_dru")):
        digest.update(path.suffix.encode("ascii"))
        if path.is_file():
            digest.update(path.read_bytes())
    cli = _kicad_cli(adapter)
    stat = cli.stat()
    digest.update(str(cli.resolve()).encode("utf-8", errors="replace"))
    digest.update("{}:{}".format(stat.st_size, stat.st_mtime_ns).encode("ascii"))
    return digest.digest()


def _copy_summary(summary):
    counts, fingerprints = summary
    return Counter(counts), Counter(fingerprints)


def _unpack_drc(value):
    """Accept both native evidence triples and legacy test doubles."""
    if len(value) == 3:
        return value
    counts, fingerprints = value
    return counts, fingerprints, {}


def _wait_for_future(future, remaining, wait_callback=None):
    """Wait for a subprocess result while allowing the KiCad UI to advance."""
    if wait_callback is None:
        return future.result(timeout=remaining())
    while True:
        wait_callback()
        available = remaining()
        poll_seconds = (0.05 if available is None else
                        min(0.05, available))
        try:
            return future.result(timeout=poll_seconds)
        except FutureTimeoutError:
            # A completed worker may itself have raised TimeoutError. Do not
            # confuse that failure with the short UI polling timeout.
            if future.done():
                return future.result()


def _hidden_process_kwargs():
    """Keep helper and kicad-cli processes out of the Windows taskbar."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _has_zones(board):
    return bool(list(board.Zones()))


def _point_line_distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    squared = dx * dx + dy * dy
    if squared <= 1e-18:
        return ((point[0] - a[0]) ** 2 + (point[1] - a[1]) ** 2) ** 0.5
    cross = abs((point[0] - a[0]) * dy - (point[1] - a[1]) * dx)
    return cross / squared ** 0.5


def _item_endpoints(item):
    if hasattr(item, "start"):
        return item.start, item.end
    return ((item.start_x, item.start_y),
            (item.end_x, item.end_y))


def _item_is_covered_by_copper(item, covering, tolerance):
    """Prove that ``item`` is wholly covered by compatible collinear copper."""
    a, b = _item_endpoints(item)
    dx, dy = b[0] - a[0], b[1] - a[1]
    squared = dx * dx + dy * dy
    if squared <= 1e-18:
        return False
    intervals = []
    for segment in covering:
        if (segment.net_id != item.net_id or
                segment.layer != item.layer or
                abs(segment.width - item.width) > tolerance):
            continue
        start, end = _item_endpoints(segment)
        if (_point_line_distance(start, a, b) > tolerance or
                _point_line_distance(end, a, b) > tolerance):
            continue
        first = ((start[0] - a[0]) * dx + (start[1] - a[1]) * dy) / squared
        second = ((end[0] - a[0]) * dx + (end[1] - a[1]) * dy) / squared
        low, high = sorted((first, second))
        low, high = max(0.0, low), min(1.0, high)
        if high >= low - 1e-9:
            intervals.append((low, high))
    covered = 0.0
    for low, high in sorted(intervals):
        if low > covered + 1e-7:
            return False
        covered = max(covered, high)
        if covered >= 1.0 - 1e-7:
            return True
    return False


def _addition_is_existing_copper(addition, removed, tolerance):
    """Backward-compatible name for the strict-removal geometric proof."""
    return _item_is_covered_by_copper(addition, removed, tolerance)


def _removed_segments(adapter, board, plan):
    wanted = set(plan.remove_keys)
    removed = []
    try:
        tracks = board.GetTracks()
    except Exception:
        return None
    for item in tracks:
        if _item_uuid(item) not in wanted:
            continue
        try:
            removed.append(adapter.segment_from_item(item))
        except Exception:
            return None
    return removed if len(removed) == len(wanted) else None


def _is_exact_copper_equivalent_plan(adapter, board, plan):
    """Prove bidirectional copper coverage, including on zoned boards."""
    if not plan.remove_keys or not plan.additions:
        return False
    removed = _removed_segments(adapter, board, plan)
    if removed is None:
        return False
    tolerance = 1.0 / adapter._iu_per_mm()
    return (
        all(_item_is_covered_by_copper(addition, removed, tolerance)
            for addition in plan.additions) and
        all(_item_is_covered_by_copper(segment, plan.additions, tolerance)
            for segment in removed))


def _is_strict_removal_only_plan(adapter, board, plan):
    """Return true only when the plan cannot add copper to new geometry.

    With no copper zones and after the engine's exact connectivity/clearance
    checks, deleting copper cannot introduce a new collision. This deliberately
    excludes normal corner cutting, endpoint sliding and every zoned board.
    """
    if _has_zones(board) or not plan.remove_keys or not plan.additions:
        return False
    removed = _removed_segments(adapter, board, plan)
    if removed is None:
        return False
    tolerance = 1.0 / adapter._iu_per_mm()
    return all(_addition_is_existing_copper(addition, removed, tolerance)
               for addition in plan.additions)


def certify_native_plan(adapter, board, plan):
    """Return a proof mode when native DRC cannot add safety information."""
    if _is_exact_copper_equivalent_plan(adapter, board, plan):
        return "geometric_equivalence_fast_path"
    if _is_strict_removal_only_plan(adapter, board, plan):
        return "geometric_removal_fast_path"
    return None


def _copy_project_files(source_board, target_board):
    source = Path(str(source_board.GetFileName()))
    for suffix in (".kicad_pro", ".kicad_dru"):
        candidate = source.with_suffix(suffix)
        if candidate.is_file():
            shutil.copy2(candidate, target_board.with_suffix(suffix))


def _kicad_cli(adapter):
    suffix = ".exe" if os.name == "nt" else ""
    candidates = []
    module_path = getattr(adapter.pcbnew, "__file__", "")
    if module_path:
        module = Path(module_path).resolve()
        candidates.extend(parent / ("kicad-cli" + suffix)
                          for parent in list(module.parents)[:5])
    resolved = shutil.which("kicad-cli")
    if resolved:
        candidates.append(Path(resolved))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("kicad-cli was not found beside pcbnew or on PATH")


def _kicad_python(adapter):
    suffix = ".exe" if os.name == "nt" else ""
    module_path = getattr(adapter.pcbnew, "__file__", "")
    candidates = []
    if module_path:
        module = Path(module_path).resolve()
        for directory in list(module.parents)[:5]:
            candidates.extend((directory / ("python" + suffix),
                               directory / ("python3" + suffix)))
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.is_file() and candidate.name.lower() not in (
                "kicad.exe", "pcbnew.exe"):
            return candidate
    raise RuntimeError("KiCad's Python interpreter was not found")


def _write_plan(path, plan):
    if any(str(key).startswith("geom:") for key in plan.remove_keys):
        raise RuntimeError("native DRC requires KiCad UUID track identities")
    path.write_text(json.dumps({
        "remove_keys": list(plan.remove_keys),
        "additions": [{
            "start": list(item.start), "end": list(item.end),
            "width": item.width, "layer": item.layer,
            "net_id": item.net_id,
        } for item in plan.additions],
    }), encoding="utf-8")


def _apply_plan_process(adapter, baseline_path, candidate_path, plan_path,
                        timeout_seconds=None):
    timeout = (180.0 if timeout_seconds is None else
               max(0.1, min(180.0, float(timeout_seconds))))
    process = subprocess.run([
        str(_kicad_python(adapter)), str(Path(__file__).resolve()),
        "--apply-plan", str(baseline_path), str(candidate_path),
        str(plan_path),
    ], capture_output=True, text=True, timeout=timeout,
        **_hidden_process_kwargs())
    if process.returncode != 0 or not candidate_path.is_file():
        detail = (process.stderr or process.stdout).strip()[:500]
        raise RuntimeError(
            "candidate snapshot failed (exit {}): {}".format(
                process.returncode, detail))


def _run_drc(adapter, board_path, report_path, timeout_seconds=None):
    timeout = (300.0 if timeout_seconds is None else
               max(0.1, min(300.0, float(timeout_seconds))))
    command = [
        str(_kicad_cli(adapter)), "pcb", "drc", "--format", "json",
        "--severity-all", "--units", "mm", "--refill-zones",
        # Without this flag KiCad suppresses repeated findings per track.  DRC
        # providers run concurrently, so the retained representative can vary
        # between two identical board snapshots and look like a regression.
        # Complete track findings make geometric fingerprints deterministic;
        # unconnected-items remain intentionally compared by count.
        "--all-track-errors",
        "--output", str(report_path), str(board_path),
    ]
    process = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        **_hidden_process_kwargs())
    returncode, stdout, stderr = (
        process.returncode, process.stdout, process.stderr)
    if returncode != 0 or not report_path.is_file():
        detail = (stderr or stdout).strip()[:500]
        raise RuntimeError(
            "native DRC failed (exit {}): {}".format(
                returncode, detail))
    text = report_path.read_text(encoding="utf-8", errors="replace")
    counts, fingerprints = _json_report_summary(text)
    return counts, fingerprints, _json_report_evidence(text)


def validate_native_plan(adapter, board, plan, *, force_native=False,
                         skip_native=False, timeout_seconds=None,
                         wait_callback=None):
    """Run the one final native comparison for a composed gloss plan."""
    started = time.monotonic()
    deadline = (None if timeout_seconds is None else
                started + max(0.0, float(timeout_seconds)))

    def remaining():
        if deadline is None:
            return None
        value = deadline - time.monotonic()
        if value <= 0.0:
            raise TimeoutError("KiCad DRC time budget reached")
        return value
    if force_native and skip_native:
        raise ValueError("native DRC cannot be both forced and skipped")
    if skip_native:
        elapsed = (time.monotonic() - started) * 1000.0
        return NativeDrcResult(
            True, timings_ms={"total": elapsed},
            validation_mode="native_drc_disabled")
    certificate = (None if force_native else
                   certify_native_plan(adapter, board, plan))
    if certificate is not None:
        return NativeDrcResult(
            True, timings_ms={
                "total": (time.monotonic() - started) * 1000.0},
            validation_mode=certificate)

    try:
        with tempfile.TemporaryDirectory(prefix="kicad-track-gloss-drc-") as name:
            root = Path(name)
            baseline_path = root / "baseline.kicad_pcb"
            stage = time.monotonic()
            if not adapter.pcbnew.SaveBoard(str(baseline_path), board):
                raise RuntimeError("KiCad could not snapshot the current board")
            _copy_project_files(board, baseline_path)
            remaining()
            snapshot_ms = (time.monotonic() - stage) * 1000.0
            baseline_key = _state_digest(adapter, baseline_path)
            candidate_path = root / "candidate.kicad_pcb"
            plan_path = root / "plan.json"
            _copy_project_files(board, candidate_path)
            _write_plan(plan_path, plan)
            plan_key = hashlib.sha256(plan_path.read_bytes()).digest()
            cached = _cache_get(_validation_cache, (baseline_key, plan_key))
            if cached is not None:
                elapsed = (time.monotonic() - started) * 1000.0
                return NativeDrcResult(
                    allowed=cached.allowed,
                    before=dict(cached.before), after=dict(cached.after),
                    increases=dict(cached.increases), error=cached.error,
                    finding_points=tuple(cached.finding_points),
                    timings_ms={"snapshot": snapshot_ms,
                                "cache_lookup": elapsed, "total": elapsed},
                    baseline_cached=True,
                    validation_mode="native_validation_cache")
            cached_before = _cache_get(_baseline_cache, baseline_key)
            if cached_before is None:
                with _cache_lock:
                    warmup = _baseline_warmups.get(baseline_key)
                if warmup is not None:
                    warmup.wait(
                        timeout_seconds=remaining(),
                        wait_callback=wait_callback)
                    cached_before = _cache_get(
                        _baseline_cache, baseline_key)
            baseline_cached = cached_before is not None

            def timed_drc(path, report):
                drc_started = time.monotonic()
                value = _run_drc(
                    adapter, path, report, timeout_seconds=remaining())
                return value, (time.monotonic() - drc_started) * 1000.0

            apply_started = time.monotonic()
            _apply_plan_process(
                adapter, baseline_path, candidate_path, plan_path,
                timeout_seconds=remaining())
            candidate_snapshot_ms = (
                time.monotonic() - apply_started) * 1000.0

            # Only the immutable baseline and the single composed candidate
            # may run in parallel. No speculative plan portfolio exists.
            with ThreadPoolExecutor(max_workers=(1 if baseline_cached else 2),
                                    thread_name_prefix="track-gloss-drc") as pool:
                before_future = None
                if not baseline_cached:
                    before_future = pool.submit(
                        timed_drc, baseline_path, root / "before.rpt")
                after_future = pool.submit(
                    timed_drc, candidate_path, root / "after.rpt")
                if baseline_cached:
                    before, before_fingerprints = _copy_summary(cached_before)
                    before_ms = 0.0
                else:
                    before_value, before_ms = _wait_for_future(
                        before_future, remaining, wait_callback)
                    before, before_fingerprints, _before_evidence = \
                        _unpack_drc(before_value)
                    _cache_put(_baseline_cache, baseline_key,
                               (Counter(before), Counter(before_fingerprints)))
                after_value, after_ms = _wait_for_future(
                    after_future, remaining, wait_callback)
            after, after_fingerprints, after_evidence = _unpack_drc(after_value)
            increases = _drc_increases(
                before, after, before_fingerprints, after_fingerprints)
            points = []
            for identity in after_fingerprints - before_fingerprints:
                if identity[0] != "unconnected_items":
                    points.extend(after_evidence.get(identity, ()))
            if increases.get("unconnected_items"):
                for identity, positions in after_evidence.items():
                    if identity[0] == "unconnected_items":
                        points.extend(positions)
            result = NativeDrcResult(
                allowed=not increases,
                before=dict(before), after=dict(after),
                increases=dict(increases),
                finding_points=tuple(sorted(set(points))),
                timings_ms={
                    "snapshot": snapshot_ms,
                    "candidate_snapshot": candidate_snapshot_ms,
                    "before_drc": before_ms,
                    "after_drc": after_ms,
                    "total": (time.monotonic() - started) * 1000.0,
                },
                baseline_cached=baseline_cached,
                validation_mode="native_parallel")
            _cache_put(_validation_cache, (baseline_key, plan_key), result)
            return result
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        failure = NativeDrcResult(
            False, error="KiCad DRC time budget reached: {}".format(error),
            timings_ms={"total": (time.monotonic() - started) * 1000.0},
            validation_mode="native_timeout")
    except Exception as error:
        failure = NativeDrcResult(
            False, error=str(error),
            timings_ms={"total": (time.monotonic() - started) * 1000.0})
    return failure


def _item_uuid(item):
    return item.m_Uuid.AsString()


def _headless_apply(baseline_path, candidate_path, plan_path):
    import wx
    wx.Log.SetActiveTarget(wx.LogStderr())
    import pcbnew

    def from_mm(value):
        return int(round(float(value) * float(pcbnew.PCB_IU_PER_MM)))

    def is_straight_track(item):
        return int(item.Type()) == int(pcbnew.PCB_TRACE_T)

    board = pcbnew.LoadBoard(str(baseline_path))
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    tracks = {
        _item_uuid(item): item for item in board.GetTracks()
        if is_straight_track(item)
    }
    missing = [key for key in plan["remove_keys"] if key not in tracks]
    if missing:
        raise RuntimeError("candidate snapshot is missing planned tracks")
    for key in plan["remove_keys"]:
        board.RemoveNative(tracks[key])
    for addition in plan["additions"]:
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(
            from_mm(addition["start"][0]), from_mm(addition["start"][1])))
        track.SetEnd(pcbnew.VECTOR2I(
            from_mm(addition["end"][0]), from_mm(addition["end"][1])))
        track.SetWidth(from_mm(addition["width"]))
        track.SetLayer(int(addition["layer"]))
        track.SetNetCode(int(addition["net_id"]))
        board.Add(track)
    if not pcbnew.SaveBoard(str(candidate_path), board):
        raise RuntimeError("KiCad could not save the candidate snapshot")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--apply-plan":
        _headless_apply(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit("expected --apply-plan BASELINE CANDIDATE PLAN")
