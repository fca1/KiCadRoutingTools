# KiCad Track Gloss

KiCad Track Gloss 2.1 is a KiCad 10 ActionPlugin that contracts selected routed
copper as a taut polyline, then reconstructs a connected 0/45/90-degree track.
It is a post-route gloss, not a router: it preserves the existing connection's
topology and does not run A*.

Select one or more straight segments and run **KiCad Track Gloss**. Selection
authorizes modification of the expanded connection; KiCad locks and native
routing authority remain protected. Single connections run to a geometric
fixed point when time permits. Multi-net selections repeat deterministic passes
and retain the best complete result already found at the total deadline.

Native DRC is enabled by default for both single and multi-net work. The engine
checks clearance and connectivity first, then performs one final global KiCad
before/after comparison. The live board is modified only after acceptance and
is never saved automatically. One KiCad Undo reverts the operation.

Documentation:

- [Smart Octo specification](docs/smart-octo.md)
- [Architecture](docs/architecture.md)
- [Plugin usage](docs/plugin-usage.md)
- [CLI](docs/cli.md)
- [Configuration](docs/configuration.md)
- [Safety and DRC](docs/safety-and-drc.md)
- [Output contracts](docs/output-contracts.md)

Fast tests:

```powershell
py -3.12 -m pytest tests/track_gloss/unit -q
```

Build the PCM archive:

```powershell
py -3.12 kicad_track_gloss\package_pcm.py
```

The project is inspired by and reuses parts of DrAndyHaas's
KiCadRoutingTools under the retained MIT notices. The standalone adaptation is
maintained by Frantz and was developed with ChatGPT/Codex (OpenAI).
