# KiCad Track Gloss 1.4.1 — intra-connection DRC salvage test build

- Splits a single connection's converged plans into independently applicable
  edit regions separated by unchanged copper.
- Replans every region from the original board so endpoint sliding and local
  convergence retain their full gain.
- Reuses the existing three-process native DRC salvage to keep safe regions
  when another region of the same connection is rejected.
- Keeps the final accepted composition as one KiCad edit and one Undo step.

Targeted validation on the eight-segment `P1 UR` connection of the updated
`picofx_pump` board retains the safe lower translation and saves 4.573918 mm.
Native DRC remains unchanged (`starved_thermal` 9 -> 9). Total CLI time is
15.532 s with the plugin-equivalent 20 s budget. A second gloss applies no
additional safe modification; its remaining proposal is rejected for the
known `MX6.4` starved thermal. Six focused unit tests pass. The full
non-regression campaign is intentionally deferred.
