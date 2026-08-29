# KiCad Track Gloss 2.0 — Real Spirit

Requires KiCad 10.0 or newer.

The normal action glosses selected straight-track connections in place and is
silent on success. The diagnostic action runs the same engine and reports the
file name and absolute path, scope, outcome, gain, fixed-point state, total
time, final DRC state, and one concrete primary reason. Advanced numeric data
is available in its JSON tab.

Run either action without a selected straight segment to edit the three session
settings: native DRC, minimum saved length (default 0.2 mm), and total time
budget (default 20 s). No planning-budget or worker-grace setting exists.

The algorithm contracts the routed polyline against clearance obstacles,
represents round contacts with clean octolinear polygons, reconstructs 0/45/90
copper, and repeats to a fixed point. T branches slide on exact collinear rails;
non-collinear nodes remain fixed. Multi-net passes retain the best complete
incumbent when time expires.

The plugin never saves the board. A successful operation is one Undo step.
