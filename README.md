# PRINTME!

LAN-hosted photo &amp; document printing shop system with automated photo processing. A customer-facing upload portal plus a staff admin dashboard for a walk-in print shop: photo prints (fixed sizes — 1×1, 2×2, Passport, Visa, Wallet, 4×6, 5×7, 4×4) go through automatic face detection, cropping, and background removal, then get packed onto the fewest A4 sheets by the built-in layout engine; documents (PDF/DOCX/JPG/PNG) print close to as-is. Runs entirely offline on a single Windows PC — see `CLAUDE.md` for the full spec.

> **Status:** in active development. Not yet deployed or tested at the actual shop — this has been built and tested in a Linux dev container so far, with real printer/USB behavior still unverified on the target Windows machine.

## Setup

1. **Create a virtual environment and install dependencies**
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```

2. **Apply the database schema**
   ```
   set FLASK_APP=wsgi.py
   venv\Scripts\python -m flask db upgrade
   ```

3. **Pre-cache the background-removal model** (one-time, needs internet — the app never reaches out again afterward)
   ```
   venv\Scripts\python -c "from printme.services.background_removal import _get_session; _get_session()"
   ```

4. **Build the CSS** (one-time, and again after editing `printme/static/src/input.css` or adding new template classes) — download the [Tailwind standalone CLI](https://github.com/tailwindlabs/tailwindcss/releases) as `tailwindcss.exe` in the repo root, then:
   ```
   powershell -File scripts\build_css.ps1
   ```

5. **Run it**
   ```
   venv\Scripts\python run.py
   ```
   Visit `http://127.0.0.1:5000/` for the customer upload portal, `http://127.0.0.1:5000/admin/login` for the staff dashboard (demo password: `print`, set `ADMIN_PASSWORD` for anything real).

## Admin PC setup (production, do this once)

For the actual shop PC — not the dev workflow above. After completing
steps 1-4 above (venv, dependencies, the background-removal model cache,
and the built CSS), run:

```
powershell -File scripts\install_startup_task.ps1
```

This registers a Scheduled Task that starts PRINTME! silently every time
this Windows account logs in, and adds a "PRINTME Dashboard" icon to the
Desktop that opens the admin dashboard like any other app — no terminal,
no `pip install`, no `flask db upgrade`, ever again. Every future update
to this repo just needs the new files copied in and the PC restarted (or
sign out/in) — `wsgi.py` runs the equivalent of `flask db upgrade` itself
on every launch, so the schema always catches up on its own.

Two things worth knowing:
- The task starts **at log on**, not before. If the counter PC should be
  ready before anyone touches it, configure Windows for auto-logon
  (Settings → Accounts → Sign-in options) — that's a Windows setting, not
  something the install script does for you (it would otherwise need this
  account's password stored in Task Scheduler).
- If the dashboard ever doesn't load, check `instance\printme.log` first —
  both a failed migration and a failed server start (e.g. the port
  already in use) are logged there, since there's no visible console to
  read them from otherwise.

## Tests

```
venv\Scripts\python -m pytest
```
