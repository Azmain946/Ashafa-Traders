# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Ashafa Traders Pharmacy ERP — a monolithic Django 6.0 web application (Python 3.12+) with server-rendered templates, Bootstrap 5, and jQuery. Uses SQLite by default (no external services required for dev).

### Running the app

```bash
python3 manage.py migrate
python3 manage.py seed_pharmacy   # creates admin/admin12345 user + demo data
python3 manage.py runserver 0.0.0.0:8000
```

### Testing

```bash
python3 manage.py test --verbosity=2
```

Tests use an in-memory SQLite database and require no external services.

### Key gotchas

- The `pip install` puts binaries in `~/.local/bin`; ensure `PATH` includes it (e.g. `export PATH="$HOME/.local/bin:$PATH"`) before running `django-admin` or other Django CLI tools.
- The project defaults to SQLite (`db.sqlite3`). Set `DATABASE_URL` env var only if you need PostgreSQL.
- `seed_pharmacy` is idempotent and creates the default admin user (`admin` / `admin12345`), store settings, sample products, customers, suppliers, and one seed invoice.
- Static assets (Bootstrap, jQuery, Bootstrap Icons) are vendored in `static/vendor/` — no `npm install` needed.
- No linter is configured in the repo. Standard Python linting with `ruff` or `flake8` can be used ad-hoc but is not required by CI.
