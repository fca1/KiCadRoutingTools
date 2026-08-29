# Safety and native DRC

The engine receives KiCad 10's evaluated per-item clearance, copper layers,
exact pad geometry, keepouts, Edge.Cuts, locks, and native protection. It checks
every new segment against those API-neutral snapshots and verifies connectivity
before native validation.

When enabled, native DRC is called only for the final composed plan. A private
baseline board and candidate board are checked with the same project and rule
files; the plan is accepted only if no DRC category/fingerprint increases. The
baseline half may execute concurrently with geometric planning and is cached,
which reduces wall time without weakening the comparison.

No per-net, per-pass, or candidate-ladder DRC exists. Disabling native DRC
retains exact internal checks but removes the final KiCad authority check.
