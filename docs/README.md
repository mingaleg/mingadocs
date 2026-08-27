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
  siteconfig/        The unified /settings/ page (no models)
media/               Uploaded scan images + generated document PDFs (gitignored)
docs/                Requirements and context (this directory)
```

Run the dev server:

```
poetry install
poetry run python src/mingadocs/manage.py migrate
poetry run python src/mingadocs/manage.py runserver
```

- Overview:        `/` — current configuration plus live islands for scan
  batches in flight, recent documents and recent volume activity (each with a
  right-aligned "View all"); navigation lives in the top bar
- Label utility:   `/labels/`
- Scan intake:     `/scans/`
- Documents:       `/scans/documents/`
- Settings:         `/settings/` — unified page (`siteconfig` app), `#labels` +
  `#scanner` sections (also in Django admin). `/scans/settings/` and
  `/labels/settings/` redirect here. Printer / scanner lists are probed once
  per process and cached; "Rescan hardware" forces a refresh.

Without a scanner, set `MINGADOCS_FAKE_SCANNER=/path/to/image.png` and every
"Scan Page" returns that image.

Templates extend `arnlabels/base.html`; styling is one stylesheet at
`arnlabels/static/arnlabels/app.css` (light/dark aware, no build step).

## Static analysis

`make lint` runs three checkers; all are expected to pass with zero findings
(config lives in `pyproject.toml`):

| Tool     | `make` target | Scope |
|----------|---------------|-------|
| `mypy`   | `make mypy`   | `src/mingadocs` + `tools/`, with `django-stubs`; migrations excluded. Full annotations required (`disallow_untyped_defs`); tests are checked but not annotation-gated. |
| `pylint` | `make pylint` | Same source, `pylint-django` plugin. `broad-exception-caught` is disabled project-wide (deliberate degrade-gracefully handlers, each also tagged `# noqa: BLE001`). |
| `bandit` | `make bandit` | `src/mingadocs`. Reviewed subprocess / try-except sites carry inline `# nosec <ID>`. |

Third-party packages without type info (`cups`, `reportlab`, `solo`) are given
`ignore_missing_imports`; `zxing-cpp` ships its own stubs.
