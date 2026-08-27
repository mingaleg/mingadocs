# mingadocs

A home-brewed system for managing paper documents: mail received by post,
electronic documents, and scans of official documents (passports, IDs, etc.).

It is a Django service. Documents are organised into an **archive** that is
addressed by **Archive Serial Numbers (ARNs)** printed as barcode stickers and
applied to physical pages, so that scanned documents can be matched back to
their archive location by OCR.

## Status

Early development. Implemented:

- **ARN label printing utility** — see [`arn-labels.md`](arn-labels.md).
- **Scan workflow** — scan labelled paper, detect the ARN barcode, group pages
  into document PDFs. See [`scan-workflow.md`](scan-workflow.md).

Future work: storage/retention, electronic-document intake, search, auth.

## Tech stack

- Python ≥ 3.14, managed with Poetry
- Django 6.x
- SQLite (development)
- `reportlab` for PDF generation
- `pycups` for sending print jobs to CUPS
- `django-solo` for singleton (global, permanent) settings
- `Pillow` + `zxing-cpp` for reading ARN barcodes off scans
- SANE's `scanimage` CLI (system package `sane-utils`) to drive the scanner

## Layout

```
src/mingadocs/
  manage.py
  config/            Django project (settings, urls, wsgi/asgi)
  arnlabels/         ARN label printing app
  scans/             Scan intake workflow app
media/               Uploaded scan images + generated document PDFs (gitignored)
docs/                Requirements and context (this directory)
```

Run the dev server:

```
poetry install
poetry run python src/mingadocs/manage.py migrate
poetry run python src/mingadocs/manage.py runserver
```

- Overview:        `/` — tiles for print / scan / documents / settings, plus
  recent volume and recent document activity
- Label utility:   `/labels/`
- Scan intake:     `/scans/`
- Documents:       `/scans/documents/`
- Settings:         `/scans/settings/` — unified page, `#labels` + `#scanner`
  sections (also in Django admin). `/labels/settings/` redirects here.

Without a scanner, set `MINGADOCS_FAKE_SCANNER=/path/to/image.png` and every
"Scan Page" returns that image.

Templates extend `arnlabels/base.html`; styling is one stylesheet at
`arnlabels/static/arnlabels/app.css` (light/dark aware, no build step).
