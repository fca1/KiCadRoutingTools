# KiCad Track Gloss 1.3.3 — dominant simplification test build

- Always accepts a candidate that reduces the segment count without increasing
  copper length, independently of the minimum length-saving threshold.
- Keeps the configured minimum saving for transformations which do not reduce
  segment count.
- Removes the former optional `allow_equal_length_simpler` engine mode: this
  dominance rule is now an unconditional gloss invariant.
- Retains only the KiCad coordinate quantum as numerical comparison tolerance.

This test build is checked on the `Net-(J13-UTILITY)` connection from
`muzy_zynq4`. The full non-regression suite is intentionally deferred.
