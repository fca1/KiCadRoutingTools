# Smart Octo — specification for the next Track Gloss release

## Purpose

Smart Octo is a post-routing gloss engine. It does not search for a new route
and does not use A*. It shortens and cleans the copper already routed by KiCad,
first for one selected connection and then, by deterministic passes, for a
selection containing several nets.

The implementation must be derived from the geometric model below. A failing
board is evidence against a general invariant or one isolated implementation
stage; it must not lead to a catalogue of board-specific patterns, exceptions,
backoff ratios, or fallback planners.

## Geometric model

### The moving polyline

- The selected connection is represented by its centreline and its real copper
  width only.
- Its endpoints, fixed nodes, layer, net identity, connectivity and authorized
  topology are preserved.
- Every admissible interior segment translation is a continuous degree of
  freedom. The solver is not limited to a predefined set of candidate shapes.
- The polyline is contracted until it reaches a geometric fixed point against
  the forbidden obstacles.

### Smart Octo obstacles

Every primitive obstacle is represented by octolinear geometry. A neighbouring
track segment becomes an elongated irregular octagon. A round primitive is
circumscribed conservatively instead of being sampled as a curved succession
of short edges. A complex object may be decomposed into primitive octagons and
their exact geometric union.

For each moving-net/obstacle pair, two independently attributable envelopes are
constructed:

1. the obstacle copper dilated by the clearance imposed by the moving net;
2. the same obstacle copper dilated by the clearance imposed by the obstacle.

The forbidden obstacle is the geometric union (the Boolean OR) of these two
polygons. The clearances are never added together. If the two polygons are
nested, their union naturally reduces to the outer polygon. Both sources remain
recorded for diagnostics even when only one exterior boundary reaches the
solver.

The moving polyline retains its own real copper thickness. Collision therefore
means that this thick polyline intersects the consolidated forbidden polygon.
The solver itself does not need to understand netclasses or KiCad rule
priorities.

### KiCad rule authority

The envelope builder obtains, per layer and object where applicable:

- effective netclass and netclass clearance;
- evaluated own clearance and local overrides;
- minimum board clearance and copper-to-edge clearance;
- effective track, via and pad copper geometry;
- keepouts, board outline and enabled copper layers.

KiCad 10 `pcbnew` is the sole supported object API for this release. Pairwise
custom rules that cannot be queried exactly through the public Python bindings
remain covered by final native DRC validation. No compatibility fallback for
KiCad versions before 10.0 is permitted. IPC preparation is outside this
release and must not change its implementation.

## Contraction and reconstruction

The solver receives only a thick polyline, fixed or sliding terminals, and
forbidden octolinear polygons. It repeatedly:

1. removes slack from the complete connection;
2. creates exact contacts with obstacle sides or vertices;
3. translates admissible interior segments continuously;
4. repeats until no safe length improvement remains;
5. reconstructs the result with 0/45/90-degree copper;
6. removes redundant collinear segments.

Reconstruction must not follow a rounded obstacle with many short segments.
The polygonal obstacle is deliberately the routing support, so its finite clean
sides determine the possible contacts.

Every accepted state must preserve connectivity and clearance and must improve
the monotone objective: copper length first, then segment count when length is
equal within KiCad's coordinate quantum.

## Junctions and selection

- Selection authorizes modification; only selected/expanded copper may be
  rewritten.
- KiCad-native locks and protections remain stronger than selection.
- At a three-way T, two collinear segments form a fixed rail. The outside
  branch may slide continuously on that rail.
- When no incident pair is collinear, the junction is a fixed node.
- A junction with more than three segments is decomposed deterministically into
  all valid `(collinear rail, outside branch)` T interpretations.
- An unselected rail may support a selected sliding branch but is never
  rewritten.
- In a multi-selection conflict, the T topology determines the admissible
  movement; selection does not make the rail movable for that T operation.

## Single and multi-net operation

A single connection is the primary quality requirement. It must be processed
as a whole and reach the solver's fixed point when the total operation budget
permits. A second identical invocation on a completed result must be a no-op.

Several nets are processed sequentially because a modified net changes the
obstacles seen by its neighbours. Pass order alternates deterministically.
Strictly improving safe incumbents are retained until a common fixed point or
the single total deadline. Reaching the deadline returns the best complete safe
work already obtained; multi-net operation is never all-or-nothing merely
because the optimum was not reached.

## Native DRC

Internal geometric checks run during planning. Native KiCad DRC is not called
per candidate, connection, or pass. When enabled, one global before/after DRC
comparison validates the final composed plan.

If that comparison identifies an unmodelled violation with usable locations,
only implicated transformations may be removed, followed by at most one global
revalidation. There is no candidate portfolio, recursive salvage, or DRC
ladder. No live-board modification is applied without the required acceptance.

## Visual explanation

An optional diagnostic command renders the model on a dedicated KiCad
`User.*` information layer:

- initial copper centreline and real width;
- envelope produced by the moving-net clearance;
- envelope produced by the obstacle clearance;
- their consolidated union;
- fixed nodes, T rails and sliding terminals;
- contact points and final reconstructed polyline;
- rule source and numerical clearance associated with each envelope.

The overlay is explicitly requested, grouped, undoable and removable in one
operation. It never participates in routing, clearance or fabrication. Normal
gloss does not create diagnostic graphics.

The diagnostic result itself remains concise: board name and absolute path,
scope, outcome, gain, fixed-point state, elapsed total time, final DRC state,
and one concrete primary reason. Detailed geometry belongs in the optional
overlay and machine-readable output.

## Architecture

The production engine is divided into narrow one-way stages:

1. **KiCad snapshot and rule resolution** — authoritative input extraction;
2. **Smart Octo envelope builder** — two sourced polygons and their union;
3. **Topology** — chains, fixed nodes, rails and sliding T branches;
4. **Continuous contraction** — taut-polyline fixed-point solver;
5. **Octolinear reconstruction** — clean 0/45/90 copper;
6. **Internal validation** — connectivity, authorization and polygon safety;
7. **KiCad adapter** — one final DRC and one atomic Undo application;
8. **Diagnostic overlay** — visualization only, with no dependency back into
   the solver.

The geometry engine is API-neutral. Rule resolution does not leak into the
solver, and visualization does not influence planning.

## Validation campaign before a test release

The complete campaign is executed after the general implementation is stable,
not after every intermediate change.

### Geometric invariant tests

- Boolean union of the two clearance polygons, including nested envelopes;
- irregular elongated track octagons and circumscribed round obstacles;
- tangent contact accepted, strict penetration rejected;
- no sampled arc and no chain of short segments around a round obstacle;
- continuous interior-segment translation to the physical limiting contact;
- clean reconstruction at 0/45/90 degrees;
- monotone length/segment objective and exact connectivity;
- fixed nodes, T sliding, four-way T interpretations and selection authority;
- deadline returns the best complete incumbent;
- second invocation is a fixed-point no-op.

### Real single-net campaign

Test several deliberately chosen long and obstructed nets in each board rather
than waiting for a user to discover the next geometry:

- `magic_keys`: pad approaches, repeated bends and T connectivity;
- `picofx_pump`: long internal translations and zone/thermal interaction;
- `nanovoltmeter_marge`: dense neighbouring nets and clearance provenance;
- `muzy_zynq4`: trivial jog removal and complex-board DRC cost;
- `polykit_x_inputboard`: long translation opportunities.

For every chosen net, record before/after copper, segment count, fixed point,
second-pass result, internal safety, native DRC result and wall time. Visualize
the Smart Octo overlay for every incomplete or surprising outcome before any
code correction is considered.

### Multi-net campaign

After the single-net gate passes, test deterministic passes on the five
neighbouring `nanovoltmeter_marge` nets `AB_CTRL`, `AB_RST`, `AB_RX`, `AB_TX`
and `BEEP`, then four SET21 boards with a 60-second CLI total budget and native
DRC. Record retained gain, passes, fixed-point/deadline state, DRC calls and
total time.

### Release gate

A test release is produced only when failures can be explained by one of the
documented stages and the correction strengthens a general invariant. A
board-specific exception, pattern operator or fallback is a release blocker,
not an acceptable fix.
