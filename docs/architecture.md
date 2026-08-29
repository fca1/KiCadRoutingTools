# Real Spirit architecture

KiCad Track Gloss 2 uses one planner. It does not keep the historical candidate
portfolio, pattern operators, recursive fallbacks, per-candidate workers, DRC
salvage ladder, or A* routing.

## Boundaries

- `kicad_track_gloss/kicad/` is the KiCad 10 authority boundary: selection,
  locks, evaluated rules, exact pads, board snapshots, writes, Undo, and native
  DRC.
- `kicad_track_gloss/engine/real_spirit/` is API-neutral geometry: topology,
  inflated obstacles, contraction, contacts, 0/45/90 reconstruction, and
  deterministic fixed-point passes.
- `candidate_geometry.py`, `context.py`, `pads.py`, and `validation.py` contain
  shared exact geometry and connectivity primitives. They do not plan routes.

## Data flow

1. A selected straight segment authorizes its expanded connection.
2. Topology divides authorized copper at pads, vias, fixed nodes, and T rails.
3. Every chain is contracted as one polyline inside its existing routed
   homotopy. Interior segment translations are continuous degrees of freedom.
4. Round clearance contacts are represented for reconstruction by conservative
   octolinear polygons, never by sampled arcs.
5. Reconstruction keeps the existing copper as incumbent and replaces only
   spans proven shorter, connected, safe, and clean at 0/45/90 degrees.
6. Single-net work repeats to a true fixed point. Multi-net work applies nets
   sequentially, reverses deterministic order between passes, and retains the
   best complete incumbent when time expires.
7. The composed plan receives one final global native DRC comparison when that
   option is enabled, then is applied to the live board as one Undo operation.

## T junctions

A degree-three junction with one collinear pair is a T. The pair is a fixed
rail and the outside branch may slide on it. A degree-three junction without a
collinear pair is a fixed node. Higher-degree junctions enumerate every exact
collinear-pair/outside-branch interpretation. Unselected same-net copper may be
a rail but is never rewritten.

## Time contract

There is one user-visible total budget. It covers planning and final DRC. A
deadline never discards a complete improvement already found. Native baseline
DRC may run concurrently with API-neutral planning so final validation does not
repeat board-wide work.
