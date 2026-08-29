# Plugin usage

1. In KiCad 10 PCB Editor, select one or more straight track segments.
2. Run **KiCad Track Gloss**.
3. Inspect the copper and use Undo if desired.

One selected segment expands to its connected authorized copper. Multiple nets
are processed in deterministic passes because one net's improvement can free
space for another. If the total deadline is reached, the best complete plan
already found is validated and returned; unfinished work is discarded.

Run **KiCad Track Gloss — Diagnostic** when an explanation is needed. Its
Result tab is intentionally short. The Details tab adds version and policy
context. JSON contains the technical counters.

Run **KiCad Track Gloss — Toggle Smart Octo obstacles** to visualize the
clearance model for the current selection. The action uses an unused `User.*`
layer named `TrackGloss Obstacles` and creates one locked group:

- 0.05 mm outlines: clearance sourced from the moving net;
- 0.08 mm outlines: clearance sourced from the obstacle;
- 0.15 mm outlines: the single effective envelope built from their maximum.

Run the same action again to remove the whole group. These non-copper graphics
are informational, never affect DRC, and are not created by normal gloss.

With no selected straight segment, either action opens session settings. Native
DRC applies equally to single- and multi-net selections.
