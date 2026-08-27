# mingadocs

A home-brewed system for managing paper documents: mail received by post,
electronic documents, and scans of official documents (passports, IDs, etc.).

It is a Django service. Documents are organised into an **archive** that is
addressed by **Archive Serial Numbers (ARNs)** printed as barcode stickers and
applied to physical pages, so that scanned documents can be matched back to
their archive location by OCR.

## Status

Early development. The first deliverable is the **ARN label printing utility**
(see [`arn-labels.md`](arn-labels.md)). Everything else (document intake,
storage, OCR pipeline, retention) is future work.

## Tech stack

- Python ≥ 3.14, managed with Poetry
- Django 6.x
- SQLite (development)
- `reportlab` for PDF generation
- `pycups` for sending print jobs to CUPS
- `django-solo` for singleton (global, permanent) settings

## Layout

```
src/mingadocs/
  manage.py
  config/            Django project (settings, urls, wsgi/asgi)
  arnlabels/         ARN label printing app
docs/                Requirements and context (this directory)
```

Run the dev server:

```
poetry install
poetry run python src/mingadocs/manage.py migrate
poetry run python src/mingadocs/manage.py runserver
```

- Label utility:  `/labels/`
- Print settings:  `/labels/settings/` (also in Django admin)
