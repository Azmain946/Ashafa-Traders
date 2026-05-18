# Ashafa Traders Pharmacy ERP

A monolithic Django pharmacy ERP web app for fast billing, batch-based stock control,
customer/supplier history, returns, antibiotic registers, reminders, and printable invoices.

## Stack

- Python 3.12+
- Django 6.0.x
- SQLite for local development, PostgreSQL via `DATABASE_URL` for production
- Django templates and ORM
- Bootstrap 5.3.8, Bootstrap Icons, vanilla JavaScript, and jQuery
- Pillow for safe product image processing and thumbnails

## Local setup

```bash
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py seed_pharmacy
python3 manage.py runserver
```

Seed login:

- username: `admin`
- password: `admin12345`

## Environment variables

- `DJANGO_SECRET_KEY`: production secret key
- `DJANGO_DEBUG`: set to `0` in production
- `DJANGO_ALLOWED_HOSTS`: comma-separated host list
- `DATABASE_URL`: PostgreSQL URL, for example `postgresql://user:pass@host:5432/dbname`

## Main sections

- Home and global medicine search
- Fast order page with autocomplete, modal selection, AJAX cart updates, and checkout
- Product entry, product details, stock batch entry, batch pricing, and stock movement audit trail
- Dashboard with sales/profit/due/customer metrics and growth chart
- Customer directory and purchase history
- Supplier directory, due tracking, purchase records, and receipt/memo upload
- Searchable invoice records and printable invoice details
- Return entry linked to original invoice
- Antibiotic register
- Low-stock and near-expiry reminders
- Admin settings for profile, password, store details, invoice footer, and thresholds

## Media layout

Uploaded files are stored under:

- `media/products/`
- `media/products/thumbnails/`
- `media/receipts/`
- `media/invoices/`
- `media/avatars/`

Product uploads accept JPG, JPEG, PNG, and WebP. Images are converted to optimized WebP and
list thumbnails are generated automatically.
