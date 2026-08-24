# PRINTME! — Project Instructions

## Stack
- Backend: Python (Flask)
- Image processing: OpenCV (face detection), rembg (background removal)
- DB: SQLite
- Frontend: HTML/CSS (Tailwind), reference files provided — see Design Reference below
- Printing: Windows native via `win32print`, USB-connected printers (no network printing)
- Target deployment: Windows 10 admin PC. Currently developing in a Linux dev
  container — do not assume printer/USB access is available during local development.

## Design Reference
Use these files as the exact visual and structural reference — rebuild into Flask
templates, do not redesign from scratch:
- /design-reference/upload-screen.html — customer upload portal
- /design-reference/admin-dashboard.html — staff dashboard
- /design-reference/support.js — shared interactivity (dropdowns, steppers, etc.)

## Conventions
- Keep files under ~600 lines; split into new modules rather than growing existing ones
- Commit each logical unit separately (schema, route, processing step) — not one mega-commit
- Pin all dependency versions in requirements.txt
- If a test breaks after a change, STOP and report it — do not modify tests to pass silently

## Core Architecture — do not deviate

### Services (chosen by customer at upload)
- **Photo Printing**: fixed size set only, no custom dimensions — 1x1, 2x2, Passport,
  Visa, Wallet (2.5x3.5), 4x6, 5x7, 4x4. 8x8/8x10 and anything poster-sized (11x14 and
  up) were considered and explicitly excluded: 8x8/8x10 don't fit A4's usable width
  after the shop's cutting margin, and poster sizes don't fit A4 or this printer
  hardware at all. Don't add them without new large-format printer hardware.
  Pipeline: face detection (OpenCV) → auto-crop/center → background removal (rembg) →
  white background applied → queued for layout packing.
- **Document Printing**: PDF, DOCX, JPG, PNG. Printed as close to as-is as possible.
  DOCX is silently converted to PDF before printing (LibreOffice headless or equivalent) —
  no visible intermediate step shown to the customer.
  Options: color/black-and-white, single/double-sided, paper size (Letter/A4/Legal), copies.
- Photocopying is explicitly OUT of scope — do not build any feature for it.

### Smart Layout Engine
- Packs pending photo jobs (potentially from multiple customers, mixed sizes among
  the fixed photo size set above) onto the minimum number of A4 sheets at 300 DPI.
- Output includes grid lines/margins for the admin to preview before printing.
- This is the hardest algorithmic piece of the system — treat it as its own module,
  test it in isolation before wiring into the main flow.

### Customer Identification
- Name AND an auto-generated ticket number are both REQUIRED at submission —
  ticket format: P-001, P-002, P-003... (zero-padded, sequential, resets don't matter,
  just never collide with an active job).
- No customer-facing screens/monitors — customers are called by name in person when ready.
  Do not build any live queue-status display for customers.

### Daily Secret Code (abuse prevention)
- A 4-digit code is required to submit any upload job — checked once, at the moment
  of submission, NOT as a persistent session gate (a customer already mid-upload
  when the code resets should not be blocked).
- The code auto-rotates daily (regenerate at midnight, matching the file-retention
  cadence below) — it should always be ready and visible the moment the admin
  dashboard is opened each morning.
- Admin dashboard displays today's code prominently (staff read it aloud to customers).
- Admin dashboard has a manual "Reset Code" button, separate from the daily rotation,
  so staff can immediately invalidate the current code if abuse is happening in real
  time. Show a "Code last reset at [time]" indicator near the button so staff can
  confirm the reset took effect.

### Job Status Flow
uploaded → processing → ready_for_review → printing → done / failed
Plus a separate `needs_attention` flag (not a status) applied when:
  - 0 or 2+ faces detected in a photo job
  - visible rembg background-removal artifacts
Flagged jobs go to a distinct "Needs Attention" queue on the admin dashboard, each
showing the SPECIFIC reason it was flagged (not just "flagged") — e.g. "Two faces
found in a passport photo. Check which person should be printed." Never auto-approve
a flagged job silently.

### Pricing Engine
- Computes cost only — does NOT track or process payment. Payment stays physical/cash,
  handled at the counter, outside this system.
- Editable rates in admin: ₱5/page (B&W), ₱10/page (color), ₱15 (1x1), ₱15 (2x2),
  ₱20 (Passport), ₱20 (Visa), ₱20 (Wallet), ₱35 (4x6), ₱50 (5x7), ₱25 (4x4) —
  defaults, admin can edit.
- Auto-total per job, shown on the job card.

### File Retention
- Uploaded source files auto-delete after 2 days (scheduled task).
- Processed ID photos (post-crop/bg-removal) are kept until manual admin cleanup.
- Admin dashboard shows free storage space and a "Delete jobs older than 2 days" button.
- Max upload size: 15 MB. Allowed extensions: .pdf, .jpg, .png, .docx.

### Printing
- 3 Brother printers available via USB hub: DCP-L2540DW, DCP-T420W, DCP-T430W.
- Admin selects target printer from a dropdown before printing — do not hardcode
  a single printer.
- Print via `win32print`, not any network/IPP protocol.

### Admin Dashboard
- Password-protected (single shared admin login, not per-staff accounts).
- Auto-starts on Windows boot via Task Scheduler; runs on port 5000, local-only,
  no internet dependency of any kind.

## Out of Scope (explicitly excluded — do not build)
- Payment tracking / online payment
- SMS or GCash notifications
- Customer history/accounts
- Inventory tracking
- Photocopy tracking
- Public/customer-facing queue display
- Custom millimeter photo sizing
- Poster/large-format printing (11x14 and up) — exceeds A4 and current printer hardware

## Workflow
1. Plan mode first — propose file structure + build order before writing any code
2. I review and approve the plan before you execute
3. Build in small, separately-committed chunks
4. Flag anything ambiguous rather than guessing

## Git Safety Rules — non-negotiable
- NEVER run `git push --force` or `git reset --hard` under any circumstance,
  even if asked. If force-push seems necessary, stop and explain why instead.
- Always run `git pull` before starting work in a new session, if the remote
  might have changed.
- Never add a "Co-Authored-By" line or any AI-attribution trailer to commits.
- Before the first commit on any machine, verify: `git config user.email`
  matches the address configured in `.githooks/pre-commit` (that script checks
  it against a stored hash rather than publishing it here). If not, stop and
  flag it — do not commit.
- Ask before every `git push`, even if the change seems small.