# Configuration

The plugin requires KiCad 10.0 or newer. No compatibility fallback for older
KiCad releases is present.

The session dialog exposes only settings meaningful to a user:

| Setting | Default | Meaning |
|---|---:|---|
| Native DRC | enabled | Compare one final composed candidate with the board-wide KiCad DRC baseline. Applies to single- and multi-net selections. |
| Minimum saved length | 0.2 mm | Minimum gain accepted for one transformation. The CLI exposes the same value as `--minimum-saved-length-mm`. |
| Total interactive budget | 20 s | Complete planning and validation deadline. The best complete incumbent is retained when planning stops. |

Settings are process-local and are not written to disk. Worker shutdown details
and internal scheduling between planning and DRC are intentionally not user
settings.

The CLI accepts one optional `--time-budget` for the same total-budget model.
Its packaged default is unlimited so automated callers choose the appropriate
limit explicitly (60 seconds for the SET21 comparison protocol).
