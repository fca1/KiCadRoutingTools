# Smart Octo validation — 2.1.0

This campaign validates the rewritten Smart Octo engine against real KiCad 10
boards. The figures below are produced by the CLI with native KiCad DRC enabled.
They are measurements, not golden expectations: board evolution may change them.

## Single-net checks

| Board | Net | Budget | Saved | Planning | Total | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `magic_keys` | `Net-(A1-D8)` | 20 s | 6.730 mm | 15.594 s | 17.469 s | DRC passed; fixed point |
| `picofx_pump` | `P1 CN LED` | 20 s | 7.141 mm | 15.781 s | 18.547 s | DRC passed; budget stop |
| `picofx_pump` | `P1 UR` | 20 s | 7.669 mm | 15.797 s | 18.547 s | DRC passed; budget stop |
| `nanovoltmeter_marge` | `AB_CTRL` | 20 s | 0.266 mm | 3.484 s | 19.656 s | DRC passed; fixed point |
| `muzy_zynq4` | `PSRAM_SI` | 20 s | 1.521 mm | 8.703 s | 13.250 s | DRC passed; fixed point |
| `polykit_x_inputboard` | `CV4_IN` | 20 s | 3.086 mm | 1.969 s | 5.813 s | DRC passed; fixed point |

A second invocation on the optimized `magic_keys` result saved nothing and
reported a fixed point. This verifies convergence rather than relying only on
the first-run gain.

## Multi-net order and passes

The five interacting `nanovoltmeter_marge` nets `AB_CTRL`, `AB_RST`, `AB_RX`,
`AB_TX`, and `BEEP` were processed together with a 60 s budget. The result saved
1.754 mm and three segments in 53.672 s, with one final native DRC validation.
The result was safe but stopped on the budget before a fixed point.

## Four-board SET21 sample

| Board | Budget | Saved | Segments saved | Total | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| `magic_keys` | 60 s | 55.465 mm | -9 | 46.766 s | DRC passed |
| `picofx_pump` | 60 s | 33.327 mm | 18 | 50.125 s | DRC passed after corrective validation |
| `polykit_x_inputboard` | 60 s | 97.518 mm | 77 | 47.047 s | DRC passed |
| `muzy_zynq4` | 60 s | 5.176 mm | 5 | 49.157 s | DRC passed |

The negative segment count on `magic_keys` is deliberate: copper length is the
primary objective, and an octolinear reconstruction may use more segments while
remaining shorter and cleaner.

## Structural checks

- 47 focused unit and integration tests pass.
- Python compilation and static undefined-name checks pass.
- The optional overlay was created and removed inside KiCad 10 on `magic_keys`.
- The distributable contains no `real_spirit` package or legacy
  `candidate_geometry.py` module.

