# KiCad Track Gloss 2.1 — Smart Octo

Requires KiCad 10.0 or newer.

The normal action glosses selected straight-track connections in place and is
silent on success. The diagnostic action runs the same engine and reports the
file name and absolute path, scope, outcome, gain, fixed-point state, total
time, final DRC state, and one concrete primary reason. Advanced numeric data
is available in its JSON tab.

Run either action without a selected straight segment to edit the three session
settings: native DRC, minimum saved length (default 0.2 mm), and total time
budget (default 20 s). No planning-budget or worker-grace setting exists.

The moving polyline retains only its real copper width. Each obstacle becomes
one conservative octolinear polygon built with the maximum of the moving-net
clearance, obstacle clearance and KiCad floors. Complete connections contract
and reconstruct as 0/45/90 copper to a fixed point. T branches slide on exact
collinear rails; non-collinear nodes remain fixed. Multi-net passes retain the
best complete incumbent when time expires.

The separate **Toggle Smart Octo obstacles** action creates or removes a locked
diagnostic group on an unused `User.*` layer. Thin outlines show the two source
clearances and the thicker outline shows the single effective polygon. These
graphics are informational and never participate in routing or DRC.

The plugin never saves the board. A successful operation is one Undo step.
