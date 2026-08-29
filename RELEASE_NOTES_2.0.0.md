# KiCad Track Gloss 2.0.0 — Real Spirit test release

This release replaces the accumulated candidate heuristics with one geometric
post-route gloss engine. Selected copper is treated as a taut solid polyline,
contracted continuously against resolved-clearance obstacles, and rebuilt with
clean 0/45/90-degree segments.

- Interior segments can translate continuously instead of matching a pattern.
- Circular obstacles use one conservative octolinear polygon; curved borders
  never become a succession of short copper segments.
- T junctions distinguish fixed collinear rails from sliding outside branches.
- Single connections converge to a geometric fixed point; multi-net selections
  alternate deterministic passes and retain the best safe incumbent at the
  total deadline.
- Native DRC is one final global comparison, with at most one localized
  corrective comparison when KiCad exposes an unmodelled finding location.
- Settings expose one total budget. Diagnostics identify the board and report
  only the decision-relevant result.
- KiCad 10.0 or newer is required. Historical planner, fallback, salvage,
  progress-box, and compatibility code has been removed.

This is a testing build intended for focused unit testing in the plugin before
publication as a stable major release.
