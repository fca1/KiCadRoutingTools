# Safety and native KiCad DRC

Track Gloss uses two complementary safety layers. Fast internal checks reject
unsafe candidates during search. A native KiCad before/after DRC gate validates
the final composed plan when the policy requires it.

## Internal validation

The API-neutral engine checks new candidate copper against nearby indexed
geometry and then runs exact kernels. It covers foreign tracks, pads, vias,
keepouts, board edges, explicit mask graphics, immutable terminal
connectivity, net/layer/width preservation, and plan identity.

Copper layers come from KiCad semantic layer APIs, not display names or string
suffixes. Through-hole pads and through-vias therefore remain obstacles on all
applicable copper layers even if internal layers have custom names.

Every via padstack diameter and every evaluated via/pad clearance is captured
separately for each copper layer. Pad checks use actual rotated circle,
rectangle, oval, rounded-rectangle, and effective custom-pad copper. Edge checks use the chained Edge.Cuts outline,
including arcs and internal holes, rather than only the board bounding box.

These checks are intentionally conservative but cannot reproduce every KiCad
design-rule interaction. They reduce the candidate set; they do not replace
the native gate.

## Native validation sequence

For a plan requiring native validation, the adapter:

1. creates private same-project baseline and candidate snapshots;
2. applies the composed plan only to the candidate copy;
3. refills zones on both copies through `kicad-cli`;
4. runs KiCad DRC and parses the JSON reports;
5. compares category counts and stable finding identities;
6. accepts only a plan that introduces no prohibited regression;
7. deletes all temporary files before returning.

The current PCB is not saved or modified by this validation. Only an accepted
plan is later applied to the live board as one Undo transaction.

Most geometric DRC categories use normalized finding fingerprints. KiCad can
describe the same ratsnest gap through different tiny items after independent
zone refills, so `unconnected_items` is compared by count increase instead of
unstable item identity.

## Performance

Candidate planning for one connection is often measured in tens of
milliseconds. Starting helper processes, refilling zones, and running two
full-board DRC evaluations can dominate the operation and take seconds. On
Windows these processes are hidden so no console windows or taskbar entries
appear.

Baseline results may be reused only through an exact-content bounded cache
whose key includes board, project, design rules, KiCad executable, and relevant
validation inputs. An identical rejected candidate may also be cached. A
timeout, crashed helper, unreadable report, or stale cache key must fail closed.

The baseline and candidate preparation/DRC work is overlapped where safe. No
`pcbnew` object is serialized into a worker process.

## Fast path and session switch

A native DRC may be skipped automatically only for a provable containment case:
the board has no zones and every added segment lies wholly inside copper being
removed. Ordinary corner cutting, endpoint relocation, pad sliding, and T
sliding do not meet this proof.

The session setting is an explicit user safety/latency trade-off applying to
both a single connection and a multi-net selection. When disabled, the
internal checks remain active but the native before/after gate is skipped.
The packaged default is enabled.

## Candidate ladder and connection-local recovery

For one selected connection, the planner explores two complete domains:
octolinear reconstruction and corridor-preserving interior translation/corner
cutting. It also explores the applicable movable/fixed track and pad terminal
domains. Every exact state visited while converging is retained, so a native
rejection of the geometric fixed point cannot erase an earlier safe pass.
Three DRC processes are used concurrently, but three is a process width rather
than a candidate cutoff; later waves continue while time remains. Every
candidate passes the complete internal gate first.

KiCad recreates the identity and reported position of an unconnected item when
the touched tracks are rebuilt.  This category is therefore compared by its
before/after count; stable geometric violation categories retain exact JSON
comparison.  Diagnostics print both unconnected counts whenever relevant.

For a selection spanning several local connections, the engine also rebuilds
each connection through the same convergence path used when one segment is
selected. Their best compatible composition is ranked against the global plan
before DRC. If both leading candidates are rejected, local plans are validated
in an anytime portfolio: two independent probes first, then a complete-batch
candidate beside one incremental extension of the already safe base. Only the
last native-DRC-approved base can be applied when the deadline is reached.
