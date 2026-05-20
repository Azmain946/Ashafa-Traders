# Ashafa Traders Pharmacy ERP

A monolithic Django pharmacy ERP web app for fast billing, batch-based stock control,
customer/supplier history, returns, antibiotic registers, reminders, and printable invoices.

## Stack

- Python 3.12+
- Django 6.0.x
- **PostgreSQL** (required for run and deploy; SQLite is only used by the test runner)
- Gunicorn + WhiteNoise for production (Railway)
- Django templates and ORM
- Bootstrap 5.3.8, Bootstrap Icons, vanilla JavaScript, and jQuery
- Pillow for product image processing and thumbnails

## Local setup (PostgreSQL)

1. Create a database, for example:

```bash
createdb pharmacy
```

2. Configure environment (copy `.env.example` to `.env` and edit):

```bash
cp .env.example .env
```

3. Install and run:

```bash
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_pharmacy
python3 manage.py runserver
```

Seed login:

- username: `admin`
- password: `admin12345`

## Deploy on Railway

### 1. Push to GitHub

Push this repository to GitHub (main or your feature branch).

### 2. Create Railway project

1. Go to [Railway](https://railway.com/) → **New Project** → **Deploy from GitHub repo**.
2. Select your repository.

### 3. Add PostgreSQL

1. In the project, click **+ New** → **Database** → **PostgreSQL**.
2. Railway sets **`DATABASE_URL`** on your web service automatically when you link the database (use **Variables** → **Reference** from the Postgres service).

### 4. Configure web service variables

On the **web** service (not only the database), set:

| Variable | Value |
|----------|--------|
| `DJANGO_SECRET_KEY` | Long random string (required) |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_ALLOWED_HOSTS` | Your public host, e.g. `your-app.up.railway.app,.up.railway.app` |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app.up.railway.app` |
| `DATABASE_URL` | Reference from Postgres plugin (automatic) |
| `DATABASE_SSL` | `1` (default on Railway) |

Railway also sets `PORT` and often `RAILWAY_PUBLIC_DOMAIN` (used for default `ALLOWED_HOSTS` / CSRF if you omit the variables above).

### 5. Build & deploy

Railway uses `railway.toml` / `Procfile`:

- **Release:** `python manage.py migrate --noinput`
- **Web:** `gunicorn config.wsgi` bound to `$PORT`
- Static files: `collectstatic` runs during Nixpacks build; WhiteNoise serves them

After the first successful deploy, open a **Railway shell** (or one-off command) and seed data once:

```bash
python manage.py seed_pharmacy
```

### 6. Custom domain (optional)

Add your domain in Railway → **Settings** → **Networking**, then extend:

- `DJANGO_ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS` (with `https://`)

## Environment variables

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Required in production |
| `DJANGO_DEBUG` | `1` local, `0` on Railway |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated origins with `https://` |
| `DATABASE_URL` | PostgreSQL URL from Railway (`postgresql://` or `postgres://`) |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | Used if `DATABASE_URL` is not set |
| `DATABASE_SSL` | `1` (default) for Railway SSL; `0` for local Postgres without SSL |
| `DJANGO_TIME_ZONE` | Default `Asia/Dhaka` |

## Tests

Tests use an in-memory SQLite database (no PostgreSQL required for CI):

```bash
python3 manage.py test pharmacy
```

## Main sections

- Home and global medicine search
- Fast order page with autocomplete, modal selection, AJAX cart updates, and checkout
- Product entry, product details, stock batch entry, batch pricing, and stock movement audit trail
- Dashboard with sales/profit/due/customer metrics and growth chart
- Customer directory and purchase history
- Supplier directory, due tracking, purchase records, and supplier memos
- Searchable invoice records and printable invoice details
- Return entry linked to original invoice
- Antibiotic register
- Low-stock and near-expiry reminders
- Settings for business details, printers (QZ Tray), passwords, and staff accounts

## Media layout

Uploaded files are stored under `media/` (products, receipts, invoices). On Railway the filesystem is ephemeral; for long-term media storage consider attaching a volume or external object storage in a future upgrade.
