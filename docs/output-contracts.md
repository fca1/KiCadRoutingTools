# Diagnostic and CLI output

The diagnostic Result tab contains only:

- board file name and absolute path;
- selected scope and nets;
- outcome and copper gain;
- removed/added segment counts when applied;
- convergence passes and fixed-point state;
- final DRC state;
- total elapsed time;
- one primary reason for a no-op or rejection.

Details adds version and session policy. JSON is the machine-readable advanced
record and may contain lengths, percentages, transformations, and native DRC
mode. Human-facing field names are English.

The CLI emits the canonical document through `SCORE_JSON` and ends with
`SCORE=<float>`.
