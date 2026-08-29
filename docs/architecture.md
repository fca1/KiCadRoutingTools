# Architecture

KiCad Track Gloss separates pure optimization from KiCad integration so the
same algorithm serves the ActionPlugin, diagnostic action, CLI, and tests.

## Main flow

```text
selected KiCad objects
        |
        v
selection expansion and BoardModel snapshot
        |
        v
API-neutral fixed-point candidate planning
        |
        v
composed plan and internal validation
        |
        v
private KiCad native DRC gate
        |
        v
single live-board Undo transaction
```

The normal and diagnostic actions differ only in reporting. CLI scope `ALL`
uses the same engine and convergence function as a complete plugin selection;
only interactive/offline budgets differ.

Two performance contracts are intentionally distinct. A one-net gloss follows
the lowest-latency path available while retaining its configured safety gate.
A multi-net gloss is an anytime optimization: it uses the configured maximum
budget to improve quality, keeps the best native-DRC-approved subset reached
so far, and returns that subset when time expires. Fast no-op completion is not
a valid substitute for already discovered safe work.

## Engine packages

- `engine/model.py`: immutable board records and edit plans.
- `engine/geometry.py`: dependency-free geometry kernels.
- `engine/context.py`: reusable spatial indexes, identities, rule envelopes,
  pad rotations, and Edge.Cuts queries.
- `engine/candidate_geometry.py`: exact local identity, clearance, pad,
  keepout, mask, and edge validation.
- `engine/local_operators.py`: corridor-preserving corner chamfers and
  continuous obstacle-contact moves used by the string contraction.
- `engine/taut_string.py`: complete fixed-endpoint rubber-band contraction;
  every safe shortening is reapplied until no support point can move or
  disappear.
- `engine/terminals.py`: sliding same-net T termination analysis.
- `engine/pads.py`: pad copper containment and bounded contact candidates.
- `engine/planner.py`: chain discovery, taut octolinear contraction,
  deterministic scheduling, and fixed-point convergence.
- `engine/workflow.py`: shared plugin/CLI convergence continuation and
  multi-connection composition.
- `engine/parallel.py`: deterministic worker orchestration with sequential
  fallback.
- `engine/validation.py`: immutable pre-apply invariants and connectivity.
- `engine/statistics.py`: transformation classification and aggregate metrics.

The engine imports neither `pcbnew` nor wx. Worker payloads consist only of
serializable model records and configuration values.

## KiCad adapter

- `kicad/reader.py`: converts the board and selection to the pure model.
- `kicad/selection.py`: native connectivity expansion.
- `kicad/authority.py`: strict KiCad 10 locked/group/generator/differential-
  pair edit authority, without geometric intent heuristics.
- `kicad/rules.py`: semantic layers, rule values, keepouts, board boundaries,
  pads, vias, and masks.
- `kicad/writer.py`: identity-checked live application and rollback.
- `kicad/native_validation.py`: temporary snapshots, refill, hidden helpers,
  DRC orchestration, caching, and timeout handling.
- `kicad/drc_report.py`: pure KiCad JSON report normalization and comparison.
- `kicad/diagnostics.py`: shared human and machine metrics.
- `kicad/settings_dialog.py` and `kicad/report_dialog.py`: session settings and
  diagnostic UI.
- `kicad/adapter.py`: narrow public facade used by actions and CLI.

`action_plugin.py` owns the one-click lifecycle and delayed busy cursor but
does not contain optimization geometry. `configuration.py` validates packaged
defaults and maintains process-local session overrides. `version.py` is the
single source of version truth for UI and packaging.

## Determinism and batching

Selected seeds are expanded independently, deduplicated, and grouped by net,
layer, and compatible geometry. Candidate ranking uses saved length, segment
reduction, and a stable geometry signature. Independent parallel results are
sorted before composition. Selection order, net order, file object order, and
worker completion order must not affect the result.

Every proper branch is derived from the same electrical incidence; there is
no track-count cutoff deciding whether a branch deserves gloss. The
planner uses one weighted interval scheduler, follows newly opened
simplifications through one outer convergence loop, and composes changed
passes against the original model so the live board receives one atomic edit
plan. The former nested refinement loop and greedy/farthest schedulers have
been removed.

Every selected seed expansion is also retained as a distinct local-connection
scope. Multi-connection planning rebuilds these scopes through the exact same
path used by a one-segment selection, composes every mutually compatible local
optimum, and ranks that composition alongside the global converged plan. A
larger selection therefore cannot silently replace a better local result with
a lower-quality plan.

Within one connection, the canonical planner pulls the complete routed path
taut. Existing vertices preserve the routed homotopy while every safe
octolinear chord is considered; support runs then slide continuously to their
last safe obstacle contact. The globally shortest safe contraction is applied
and the same rule repeats to a quantized geometric fixed point. This is a
post-route contraction, not a new route search.

One selected connection produces one canonical taut-string plan. The former
matrix of ranked schedules, corridor-only replanning, endpoint-policy variants,
and intra-connection salvage has been removed. When native DRC is enabled,
KiCad accepts or rejects that canonical plan; disabling native DRC avoids all
candidate-portfolio work. Multi-connection selections still retain independent
connection plans so the external anytime contract can return approved work
instead of a global no-op.

When KiCad rejects the taut geometry but approves a less aggressive state
with the same topology, the engine interpolates exact octolinear backoff
states. Native DRC selects the closest safe state, implementing the second
half of the physical model: add only the length required by KiCad authority.
A fixed point reached in a restricted fallback domain is never reported as
the fixed point of the complete connection.

## KiCad API boundary

KiCad 10 does not expose the internal C++ `PNS::OPTIMIZER` through public SWIG
or IPC plugin APIs. Track Gloss therefore obtains board objects, evaluated rule
data, connectivity, semantic layers, and mutations from `pcbnew`, while its
candidate generator remains Python and API-neutral. The narrow boundary makes
it possible to substitute an official optimizer API later without rewriting
selection, reporting, CLI, or packaging.

The adapter is intentionally the sole owner of SWIG objects. KiCad 10 IPC can
cover a future live-editor adapter but cannot run this project's headless CLI;
headless IPC starts with KiCad 11. A future IPC implementation must therefore
replace the adapter as a whole instead of introducing feature-by-feature
fallbacks inside the engine.

## Provenance

The standalone plugin is inspired by and reuses part of DrAndyHaas's
KiCadRoutingTools code, algorithms, and implementation patterns. The original
MIT notices are retained. Standalone integration and subsequent modifications
were produced with ChatGPT/Codex at the project owner's direction, and the
project is maintained by Frantz. See `kicad_track_gloss/NOTICE` for the formal
notice.
