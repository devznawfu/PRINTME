# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Commands

```
# Setup (one-time)
python -m venv venv
venv/bin/pip install -r requirements.txt        # Windows: venv\Scripts\pip
set FLASK_APP=wsgi.py                           # Linux/dev container: export FLASK_APP=wsgi.py
venv/bin/python -m flask db upgrade             # apply DB schema

# Run the dev server
venv/bin/python run.py                          # http://127.0.0.1:5000/ (upload), /admin/login (staff, demo password "print")

# Tests
venv/bin/python -m pytest                       # full suite
venv/bin/python -m pytest tests/test_pricing.py            # one file
venv/bin/python -m pytest tests/test_pricing.py::test_name # one test
venv/bin/python -m pytest tests/layout_engine/              # layout engine only (test in isolation before wiring changes into the main flow)

# Rebuild Tailwind CSS after editing printme/static/src/input.css or template classes
scripts/build_css.sh          # Linux/dev container (needs tailwindcss-linux-x64 at repo root, not committed)
scripts\build_css.ps1         # Windows

# New DB migration after changing a model
venv/bin/python -m flask db migrate -m "description"
venv/bin/python -m flask db upgrade
```

Full setup/production-deployment steps (LibreOffice install, rembg model pre-cache, Windows Task Scheduler auto-start, firewall rules for customer phones) are in [README.md](README.md) — read it before touching deployment scripts in `scripts/`.

Config is environment-driven via `.env` (see `.env.example`); `config.py` selects `DevConfig`/`TestConfig`/`ProdConfig` from `FLASK_ENV`. The `printme-layout-engine` and `printme-printing` skills carry the detailed constraints for those two subsystems — check them before editing `layout_engine/` or `services/printing/`.

## Architecture

- **App factory** (`printme/__init__.py`): `create_app(config_name)` wires up SQLAlchemy, Flask-Migrate (against an absolute `migrations/` path — required because Task Scheduler launches `wsgi.py` from a different cwd than a dev terminal), registers all blueprints, starts the APScheduler background jobs, and seeds today's secret code + default pricing rates on boot (skipped silently if tables don't exist yet, i.e. before the first `flask db upgrade`).
- **Routes** (`printme/routes/`) are one blueprint per admin dashboard page (`admin_dashboard`, `admin_day`, `admin_history`, `admin_photo_sheets`, `admin_pricing`, `admin_review`, `admin_auth`) plus `upload` (customer-facing) and `api` (JSON endpoints, e.g. job cancellation). Routes stay thin — business logic lives in `services/`.
- **Services** (`printme/services/`) hold the actual pipeline logic:
  - `photo_pipeline.py` / `document_pipeline.py`: end-to-end processing for each job type (face detection → crop → background removal for photos; PDF/DOCX/image pass-through for documents), each owning its own `processing → ready_for_review/failed` transition.
  - `job_state.py`: the single source of truth for legal job-status transitions (`JobStatus` in `models/job.py`) — an illegal jump (e.g. `uploaded` straight to `done`) raises `IllegalTransition` rather than silently corrupting state. Route/service code should go through this rather than setting `job.status` directly.
  - `printing/`: printer backend abstraction (`base.py` interface, `win32_backend.py` for real Windows printing, `mock_backend.py` for dev-container/test use, `printer_registry.py` for the 3-printer dropdown) — see the `printme-printing` skill.
  - `photo_sheet.py` / `photo_sheet_renderer.py`: bridge between a job's photo items and the layout engine, and rendering the packed sheet previews shown on the admin Photo Sheets page.
  - `secret_code.py`: lazy rotation (a code is never stale even if the app wasn't running at midnight — `scheduler/` just makes rotation prompt on always-on machines) plus the manual reset path.
  - `retention.py`: the 2-day upload auto-delete sweep, run by both the scheduler and the admin's manual "Delete jobs older than 2 days" button.
- **`layout_engine/`** is a standalone, framework-agnostic package (`packer.py` bin-packing, `render.py` sheet image generation, `sizes.py` dimension constants, `types.py`) deliberately kept separate from `services/` — treat it as its own module per the `printme-layout-engine` skill.
- **Models** (`printme/models/`): `Job`/`JobStatus`/`PhotoItemRow` (job.py), `PhotoSheet`/`PhotoSheetItem`, `PricingRate`, `SecretCode`, `Availability`. Migrations live in `migrations/versions/` (Alembic via Flask-Migrate).
- **`scheduler/`**: APScheduler background jobs (midnight secret-code rotation, midnight retention sweep) — disabled in `TestConfig`/`DevConfig` (`SCHEDULER_ENABLED = False`), only active under `ProdConfig`.
- Static assets: Tailwind source in `printme/static/src/input.css`, compiled to `printme/static/css/output.css` (committed — this is what ships, since the target machine has no build step). `design-reference/*.html` are the visual/structural source of truth for templates — see Design Reference above.

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
  Options: color/black-and-white, copies. Always single-sided, always A4 — these
  were previously customer choices but were dropped as unnecessary complexity;
  every print job in practice is A4, single-sided.
- Photocopying is explicitly OUT of scope — do not build any feature for it.

### Smart Layout Engine
- Packs each ready-for-review, unflagged photo job's own requested prints (mixed
  sizes among the fixed photo size set above, all belonging to that one job) onto
  the minimum number of A4 sheets at 300 DPI.
- Never mixes different jobs onto the same physical sheet — a shop-owner decision,
  not a technical limitation: automatic cross-customer merging was tried and
  explicitly removed, since it added cutting/handout complexity the shop didn't
  want, even though it costs a little extra paper versus a fully general combined
  pack. Real orders are usually placed in the shop's own standard sets (e.g. 10x
  "1x1" + 10x "2x2"), which already pack tightly on their own. Every pending job's
  own sheet(s) still land in one batch and show up together on the admin's Photo
  Sheets page — only which sheet a print physically lands on is restricted, not
  what staff see in one place. Don't reintroduce cross-job merging without the
  shop owner asking for it again.
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
- Max upload size: 15 MB. Allowed extensions: .pdf, .jpg, .jfif, .png, .docx.
  (.jfif is the same JPEG format under a different extension.)

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