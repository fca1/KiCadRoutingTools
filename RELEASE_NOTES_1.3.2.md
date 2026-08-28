# KiCad Track Gloss 1.3.2 — less-DRC test build

- Uses positions from new KiCad DRC findings to try non-implicated connection
  batches before blind subdivision.
- Falls back to the existing subdivision when KiCad provides no usable
  location.
- Canonicalizes segment direction in candidate identities.
- Does not revalidate an identical rejected candidate during one salvage run.
- Keeps the 1.3.1 certificates and leaves single-net geometry unchanged.

This intermediate build is validated only by the requested bounded
`muzy_zynq4` CLI run; the full non-regression suite remains deferred.
