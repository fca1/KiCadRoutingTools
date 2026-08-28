# KiCad Track Gloss 1.4.0 — single-connection convergence test build

- Reads KiCad's evaluated via and pad clearances, and via padstack diameters,
  independently on every copper layer. No netclass or zero-clearance
  approximation replaces these native results.
- Treats corridor-preserving interior translations as a complete candidate
  domain beside ordinary octolinear reconstruction.
- Keeps every exact convergence state for native validation. A rejected final
  geometry can no longer erase a better earlier pass that KiCad accepts.
- Uses three DRC processes as a concurrency width, not a three-candidate
  quality cutoff, and continues through later candidates while time remains.
- Removes nested refinement, greedy/farthest scheduling, translation-free
  legacy fallback, netclass reseeding, scope-size canonicalization cutoffs, and
  junction-count cutoffs.
- Applies one native-DRC session policy consistently to single-connection and
  multi-net selections; the packaged default remains enabled.
- Keeps the pure engine independent of `pcbnew` and documents the adapter as
  the future whole-backend replacement point for IPC, without implementing or
  mixing IPC in this release.

Targeted `muzy_zynq4` validation on the six-segment `PSRAM_SI` connection
retains convergence pass 2 of 3 after native DRC, saves 5.940518 mm, introduces
no DRC finding, and completes in 8.375 s with the 60 s CLI budget. A second
gloss of its output applies nothing: the remaining geometric proposal is
rejected by native DRC for a new unconnected item, confirming a fixed point
under KiCad authority. The full non-regression campaign is intentionally
deferred.
