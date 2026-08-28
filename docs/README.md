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
- `pydantic` v2 for the typed data that crosses boundaries (form input, JSON
  request/response payloads, cached values)

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

`make lint` runs four checkers; all are expected to pass with zero findings
(config lives in `pyproject.toml`):

| Tool     | `make` target | Scope |
|----------|---------------|-------|
| `ruff`   | `make ruff`   | `src/mingadocs` + `tools/` + `stubs/`; migrations excluded. Rule set: pyflakes/pycodestyle, isort, pyupgrade, bugbear, blind-except, comprehensions, flake8-{django,datetimez,executable,logging,pie,return,simplify}, ruff-specific. Security lint is left to bandit. `RUF012` is ignored in Django declarative modules; stubs may keep the upstream camelCase names. |
| `mypy`   | `make mypy`   | `src/mingadocs` + `tools/`, with `django-stubs` and `pydantic.mypy`; migrations excluded. Strict: `disallow_untyped_defs`, `disallow_untyped_calls`, `disallow_any_explicit`, `disallow_any_generics`, `disallow_subclassing_any`, `warn_return_any`. Tests are checked but exempt from the annotation / no-`Any` rules. |
| `pylint` | `make pylint` | Same source, `pylint-django` plugin. `broad-exception-caught` is disabled project-wide (deliberate degrade-gracefully handlers, each also tagged `# noqa: BLE001`). |
| `bandit` | `make bandit` | `src/mingadocs`. Reviewed subprocess / try-except sites carry inline `# nosec <ID>`. |

### Typing conventions

- **No `Any` in first-party logic.** External data (`form.cleaned_data`, JSON
  request bodies, `cache.get`) is turned into a pydantic model at the boundary
  and only the model is used afterwards.
- **Enums for every closed vocabulary** — see `scans/enums.py` and
  `arnlabels/enums.py` (batch/scan/OCR status, ARN source, alert level/code,
  page type, …). DB-backed ones are `models.TextChoices`; the rest `StrEnum`.
- **Dataclasses for internal value objects** (`Arn`, `LabelTemplate`, `Alert`,
  `OcrResult`, `Sheet`); **pydantic models** for anything parsed or serialised
  (`scans/schemas.py`, `LabelBatchInput`, `VolumeDefaults`).
- Local stubs for untyped C extensions live in `stubs/` (`cups`, `reportlab`);
  `mypy_path` includes it. `zxing-cpp` and `django-solo` ship their own types.
- `django-stubs` types `ModelForm` / `ModelAdmin` / `QuerySet` etc. as generic;
  `config/settings.py` calls `django_stubs_ext.monkeypatch()` so the
  `Foo[Model]` annotations are also valid at runtime.
