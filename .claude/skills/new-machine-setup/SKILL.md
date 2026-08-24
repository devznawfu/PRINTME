---
name: new-machine-setup
description: Use when starting work on PRINTME! from a new or unfamiliar machine, or when environment/dependency errors suggest the dev container isn't active.
---

Before writing any code on a machine you haven't used for this project before:

1. Confirm you're inside the devcontainer, not the bare host machine.
   Check: `python --version` should show 3.11.x and `pip list` should show
   opencv-python and rembg already installed. If not, you're not in the
   container — stop and reopen in container first.
2. Confirm git identity: `git config user.email` must be
   impasjohnfranz@gmail.com. If wrong, fix it before touching any files.
3. Run `git pull origin main` before making any changes.
4. Confirm the pre-commit hook is active: `git config core.hooksPath` should
   output `.githooks`. If empty, run:
   `git config core.hooksPath .githooks && chmod +x .githooks/pre-commit`
