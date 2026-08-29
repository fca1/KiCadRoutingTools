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

With no selected straight segment, either action opens session settings. Native
DRC applies equally to single- and multi-net selections.
