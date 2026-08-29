# Track Gloss tests

Fast API-neutral tests:

```powershell
py -3.12 -m pytest tests/track_gloss/unit -q
```

Real-board acceptance uses the public CLI under KiCad 10's Python. The focused
fixtures are `magic_keys`, `picofx_pump`, `muzy_zynq4`, `polykit_x_inputboard`,
and the five interacting `nanovoltmeter_marge` nets documented in
`docs/real-spirit.md`. Use one total budget and keep native DRC enabled for the
final acceptance run, for example:

```powershell
D:\kicad\bin\python.exe tools\score_track_gloss.py board.kicad_pro --time-budget 60
```

The nanovoltmeter pass-order check selects `AB_CTRL`, `AB_RST`, `AB_RX`,
`AB_TX`, and `BEEP`, verifies monotone complete incumbents, reruns the accepted
board to a no-op/fixed point, and performs one final global DRC comparison.
