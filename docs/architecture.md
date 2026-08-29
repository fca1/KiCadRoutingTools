# Smart Octo architecture

KiCad Track Gloss 2.1 has one post-route planner. It contains no geometry
pattern catalogue, fallback planner, candidate portfolio, A* search, or per-net
native DRC.

## Boundaries

- `kicad_track_gloss/kicad/` owns the KiCad 10 boundary: selection, locks,
  evaluated rules, snapshots, writes, optional overlay and final native DRC.
- `kicad_track_gloss/engine/smart_octo/` owns API-neutral clearance provenance,
  octolinear envelopes, topology, continuous contraction, reconstruction,
  safety and deterministic passes.
- Shared `context.py`, `pads.py`, `geometry.py` and `validation.py` provide
  spatial indexing and geometry/connectivity primitives; they do not plan.

## Data flow

1. Selection authorizes complete connected copper scopes.
2. KiCad supplies real copper geometry and evaluated per-object/layer rules.
3. Smart Octo resolves moving and obstacle clearance sources and retains their
   maximum; it constructs only one effective forbidden polygon.
4. The selected polyline retains only its real copper width and contracts
   continuously against those polygons.
5. Topology provides fixed nodes, pad terminals and sliding T rails.
6. Reconstruction emits only connected 0/45/90 copper and removes redundant
   collinear segments.
7. Single connections repeat to a fixed point; multi-net work alternates
   deterministic order and retains every complete safe incumbent.
8. One optional global native DRC comparison validates the composed plan before
   atomic application to the live board.

## Explainability

`smart_octo/diagnostic.py` produces API-neutral sourced and effective polygons.
`kicad/smart_octo_overlay.py` renders them as one locked, removable group on an
unused `User.*` information layer. The overlay has no dependency back into the
planner and never affects safety decisions.

## Time contract

One user-visible total budget covers planning and validation. Native baseline
DRC may overlap planning. The internal reserve is scheduling, not a second
budget. A deadline retains the best fully composed safe state already found.
