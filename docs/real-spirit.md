# Real Spirit engine contract

`real_spirit` replaces the historical candidate planner. It is a post-route
gloss engine, not a router: it preserves the selected copper topology and the
routed corridor instead of searching the board for a new route.

## Geometry

- A track centreline of copper width `w` is handled as a solid polyline of
  width `w + 2c`, where `c` is its effective KiCad clearance.
- Foreign-object constraints use the larger applicable resolved clearance.
- Every circular clearance envelope is conservatively circumscribed by one
  clean octolinear polygon. The contracted path can contact its sides or
  vertices, but it never samples or follows the round boundary with a fan of
  short segments.
- The selected polyline is contracted continuously. Obstacles create exact
  contacts and support the contracted polyline; they are not merely reasons
  to discard a finite candidate.
- After contraction, copper is reconstructed with 0/45/90-degree segments,
  adding only the length required by those directions and the clearance
  constraints.
- No A*, global rerouting, sampled direction set, geometry pattern catalogue,
  arbitrary backoff ratio, or legacy-planner fallback is allowed.

## Selection and junctions

Selection is authorization, not an obligation to move copper. KiCad native
authority remains stronger than selection.

- At a three-segment junction, two collinear segments form a fixed rail. The
  endpoint of the third selected branch may slide continuously on that rail.
- If no two incident segments are collinear, the junction is a fixed node.
- A junction with more incident segments is decomposed deterministically into
  every possible `(collinear rail, outside branch)` T interpretation. For a
  four-way crossing made of two collinear pairs, this gives four possible T
  interpretations.
- A selected rail is still fixed for the T operation. Selection permits a
  modification; the junction rule defines its admissible motion.
- Unselected same-net copper may support a sliding endpoint but is never
  rewritten.

## One connection and multiple nets

- A single connection must reach its geometric fixed point in one solver
  invocation for a fixed environment.
- Multiple selected nets are optimized in deterministic passes because every
  moved net changes the obstacles seen by the others.
- Every accepted state strictly improves the objective and remains safe.
- Passes stop at a fixed point or at the single total operation deadline. The
  best safe incumbent is always retained.

## Native DRC and timing

The engine checks modelled copper clearance and connectivity itself. It never
runs native DRC per net, pass, or candidate. Native KiCad DRC is an optional
final authority for constraints unavailable through the Python object model.
The unchanged-board baseline is cached; the final composed plan is validated
once. Its background calculation is slightly delayed and cancelled when the
planner quickly establishes that there is no candidate, so an empty gloss
does not pay for an unnecessary global DRC.

The user configures one total time budget. Planning budgets and worker
cancellation grace periods are internal implementation details and are not
shown in settings or ordinary diagnostics.

## User-facing result

The ordinary result contains only:

- board filename and absolute path;
- selected scope;
- outcome and copper gain;
- pass count and fixed-point state;
- total elapsed time;
- final DRC state;
- one concrete primary reason when no modification is made.

Search counters, internal rejection lists, and detailed stage timings belong
in machine-readable JSON or an explicitly advanced technical log.

## Acceptance

Tests assert invariants rather than reproducing historical implementation
details: selection, native authority, topology, connectivity, resolved
clearance, monotone length, fixed-point idempotence, a single final DRC, and
the total time contract. Historical exact gains are comparison baselines, not
golden outputs.

The primary real-board cases are `magic_keys`, `picofx_pump`, `muzy_zynq4`,
and `nanovoltmeter_marge`. The five neighbouring `nanovoltmeter_marge` nets
`AB_CTRL`, `AB_RST`, `AB_RX`, `AB_TX`, and `BEEP` form the reference pass-order
case. `polykit_x_inputboard` and the wider SET21 corpus are final multi-net and
timing gates.
