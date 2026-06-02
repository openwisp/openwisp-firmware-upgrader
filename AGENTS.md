# AGENTS.md

## Project Overview

`openwisp-firmware-upgrader` is the OpenWISP Django app for firmware image management and device firmware upgrades.

Core code lives in `openwisp_firmware_upgrader/`:

- `base/` contains abstract models and core firmware/upgrade behavior.
- `upgraders/`, `tasks.py`, `signals.py`, `hardware.py`, and `private_storage/` handle upgrade execution, metadata, background jobs, and protected files.
- `api/`, `filters.py`, `admin.py`, `websockets.py`, `templates/`, and `static/` provide API, admin/UI, and realtime behavior.
- Tests live in `openwisp_firmware_upgrader/tests/` and `tests/`.

## Source of Truth

- Use `docs/developer/installation.rst` and `docs/developer/index.rst` for local setup, services, and baseline test commands.
- Use `.github/workflows/ci.yml` for CI-tested dependencies, QA/test commands, env vars, and supported Python/Django versions.
- Use GitHub issue/PR templates when asked to open issues or PRs.

If instructions conflict, repository config and CI workflows win first, official docs next, and this file is supplemental.

## Development Notes

- Keep changes focused. Avoid unrelated refactors and formatting churn.
- Preserve public APIs, migrations, swappable models, upgrade state transitions, private storage behavior, and integration points unless explicitly required.
- Mark user-facing strings for translation with Django i18n helpers in Django code.
- Avoid unnecessary blank lines inside function and method bodies.
- Update docs when behavior, settings, public APIs, setup steps, or supported versions change.

## Testing and QA

- Add or update tests for every behavior change.
- For bug fixes, write the regression test first, run it against the unfixed code, confirm it fails for the expected reason, then implement the fix.
- Use targeted tests while iterating, then run the documented full test command before considering the change complete.
- Run `openwisp-qa-format` after editing when available.
- Run `./run-qa-checks` when present. Treat failures as blocking unless confirmed unrelated and reported.
- Prefer in-process tests so coverage tools can measure changed code.

## Django Notes

- Preserve tenant isolation and object-level permissions for firmware images, builds, categories, devices, and upgrade operations.
- Be careful with upload validation, firmware metadata, upgrade scheduling, retry behavior, Celery tasks, signals, websocket updates, serializers, and admin actions.
- When changing APIs, include tests for permissions, validation, filtering, pagination, and tenant boundaries.

## Security Notes

- Watch for cross-tenant data leaks, permission bypasses, unsafe file paths, unsafe downloads, insecure firmware handling, and secrets.
- Preserve validation around firmware images, checksums, metadata, private storage paths, upgrade commands, and URLs.
- Write comments and docstrings only when they explain why code is shaped a certain way. Put comments before the relevant code block instead of scattering them inside it.

## Troubleshooting

- If setup, QA, or tests fail, check docs first, then compare with CI. If commands diverge, follow CI.
