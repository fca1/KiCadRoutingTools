# Command-line interface

The CLI reads a board or project, defaults to scope `ALL`, and never overwrites
its input.

```powershell
D:\kicad\bin\python.exe tools\score_track_gloss.py board.kicad_pro --time-budget 60
D:\kicad\bin\python.exe tools\score_track_gloss.py board.kicad_pcb --scope "net:GND" --output glossed.kicad_pcb
```

Important options:

- `--scope ALL`, `--scope net:<exact-name>`, or `--scope segment:<uuid>`;
- `--time-budget SECONDS`: one total planning and DRC limit;
- `--minimum-saved-length-mm MM`: default 0.2 mm, same as the plugin;
- `--no-native-drc`: skip only the final native comparison;
- `--output`: save the accepted result to a different file.

The last stdout line is `SCORE=<post-gloss straight-track millimetres>`; lower
is better. `SCORE_JSON` contains the complete result.
