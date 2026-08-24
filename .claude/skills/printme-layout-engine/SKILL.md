---
name: printme-layout-engine
description: Use when working on the Smart Layout Engine — bin-packing photo jobs onto A4 sheets, sizes, or the packer/render modules.
---

This is the hardest algorithmic piece of PRINTME! — treat changes here
carefully and always run tests/layout_engine/ before and after edits.

- Fixed size set only: 1x1, 2x2, Passport, Visa, Wallet, 4x6, 5x7, 4x4. No custom
  millimeter sizing, no 8x8/8x10 (don't fit A4's usable width), no poster sizes
  (don't fit A4 or the shop's printers) — all explicitly out of scope.
- Packs across potentially multiple customers' jobs onto the minimum number
  of A4 sheets at 300 DPI, with visible grid lines/margins in the output for
  admin preview before printing.
- Keep packer.py (the bin-packing logic), render.py (sheet image generation),
  and sizes.py (dimension constants) separated — don't merge these into one
  file even under time pressure.
