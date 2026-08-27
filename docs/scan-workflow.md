# Scan workflow

Intake side of mingadocs: scan labelled paper, read the ARN barcode off each
page, group pages into documents, and produce archival PDFs.

Implemented in the `scans` Django app.

## Concepts

- **Scan batch** (`ScanBatch`) — one scanning session. Several may be in flight
  at once. State is on the server, so reloading a page never loses progress.
- **Scan page** (`ScanPage`) — one acquired image plus its scan/OCR status and
  detected / manually-set ARN.
- **Document** (`Document`) — a finalized multi-page PDF: a volume-start ARN
  page followed by its continuation pages.

## Batch states

```
scanning ──stop──▶ review ──finalize──▶ finalized
```

- **scanning** — the console (`/scans/<id>/`). "Scan Page" acquires one page;
  "Stop" (modal confirm) moves the batch to *review*.
- **review** — `/scans/<id>/review/`. Fix detections, reorder (drag & drop),
  remove pages, resolve alerts, then "Finalize".
- **finalized** — PDFs created; raw scan images and `ScanPage` rows deleted.

## Async scan / OCR model

In-process background threads (`scans/jobs.py`), no broker. Job state lives on
the `ScanPage` row.

- `_SCAN_POOL` — **1 worker** (the physical scanner is serial).
  `POST /scans/<id>/scan/` creates a `ScanPage` (`scan_status=pending`) and
  enqueues `_run_scan`, which shells out to `scanimage`, saves the image,
  builds a thumbnail, sets `scan_status=done`, then enqueues OCR.
- `_OCR_POOL` — 2 workers. `_run_ocr` decodes Code 128 barcodes with
  `zxing-cpp`; the decode itself runs in a throwaway thread with a deadline
  (`ScanSettings.ocr_timeout_seconds`) so a pathological image can't wedge the
  pool. Timeout / exception → `ocr_status` `timeout` / `failed`, page stays
  unassigned. Never raises to the user.
- The **Scan Page** button re-enables as soon as the scan finishes
  (`services.scan_in_progress` = any page with `scan_status=pending`), even
  while OCR for that page is still running.
- The console and review pages **poll** `GET /scans/<id>/status/` (JSON) every
  1.5–2.5 s. No websockets / SSE.

### ARN detection rule

Only Code 128 symbols whose text starts with the configured `PrintSettings`
prefix are considered. **Exactly one** match → that ARN. Zero or more than one
→ the page has no ARN assigned and must be resolved by hand.

### Restart recovery

`ScansConfig.ready()` connects a one-shot `request_started` handler that calls
`jobs.recover_stale()`: pages left `scan_status=pending` or `ocr_status=running`
by a crash are marked failed. A half-scanned page is **never** auto re-scanned
(that could double-feed a sheet-fed scanner) — the user just scans again.

## Manual override

`/scans/<id>/pages/<pid>/` shows the full image and lets the user:

- **Set ARN** — typed `PREFIX + 9 digits` (spaces ignored), validated by
  `Arn.parse`.
- **Mark as continuation** — the page becomes `PREFIX 000000000`.
- **Clear override** — fall back to the detected value.

Priority: manual continuation flag > manual ARN > detected ARN
(`ScanPage.effective_arn`).

## Alerts (block finalize)

`services.compute_alerts(batch)`; the batch is `finalizable` only when it has
pages and no alerts.

| Code                  | Meaning |
|-----------------------|---------|
| `unassigned`          | Page has no effective ARN (zero/multi detection, OCR failed or timed out). |
| `duplicate_in_batch`  | The same volume-start ARN is on more than one page. |
| `conflict_existing`   | A `Document` with that volume-start ARN already exists. |
| `orphan_continuation` | A continuation page with no volume-start page before it in batch order. |

## Finalize

`services.finalize_batch` (atomic):

1. Re-check `finalizable`.
2. Walk pages in `position` order: each volume-start ARN opens a new document
   group; continuation pages append to the current group.
3. Per group: build a PDF from the page images (`Pillow`, `save_all`), create a
   `Document(start_arn, page_count, pdf, batch)`.
4. Delete every scan image + thumbnail file and all `ScanPage` rows.
5. `batch.status = finalized`.

## Scanner backend

`scans/scanner.py` shells out to SANE's `scanimage`
(`--format=png`, optional `-d <device>` first, then `--resolution` / `--mode`).

- A device **must** be selectable: `sane_device` blank is only auto-resolved
  when exactly one device exists. Otherwise the scan errors and asks the user
  to pick one on the settings page — SANE's default device on a machine with a
  webcam is usually that webcam, not the scanner.
- `-d <device>` is passed **before** the device-specific options because
  `scanimage` only recognises `--resolution` / `--mode` once the backend is
  loaded. On failure the scan is retried with fewer options (drop `--mode`,
  then drop all), since a bad option *value* fails late with
  `sane_start: Invalid argument`. `mode` may be left blank.
- Output that looks like an HTML/XML error page (some network backends emit a
  device web page on stdout) is rejected, not saved as an image.
- `scanimage` comes from the system package `sane-utils`. Network MFPs: prefer
  the `escl:` (AirScan) device over `hpaio:` where both are listed.
- `list_devices()` parses `scanimage -L` for the settings page (best-effort).
- **Dev / tests without hardware:** set `MINGADOCS_FAKE_SCANNER` to an image
  path; `scan_page` returns that file's bytes.

## Settings

`ScanSettings` singleton (`/scans/settings/`, also Django admin):

| Field                 | Default | Purpose |
|-----------------------|---------|---------|
| `sane_device`         | (blank) | `scanimage -d` value; blank = SANE default |
| `resolution_dpi`      | 300     | `scanimage --resolution` |
| `mode`                | `Color` | `scanimage --mode` (blank = backend default) |
| `ocr_timeout_seconds` | 20      | Per-page barcode-decode deadline |

The ARN **prefix** is shared with label printing (`arnlabels.PrintSettings`).

## Module map

| Module               | Responsibility |
|----------------------|----------------|
| `scans/models.py`    | `ScanSettings`, `ScanBatch`, `ScanPage`, `Document` |
| `scans/scanner.py`   | `scanimage` subprocess + fake-scanner override |
| `scans/ocr.py`       | Code 128 → ARN detection (`zxing-cpp`) |
| `scans/jobs.py`      | Background scan/OCR workers, restart recovery |
| `scans/services.py`  | Batch lifecycle, alerts, finalization |
| `scans/views.py`     | Console, review, page detail, settings, JSON endpoints |
| `scans/forms.py`     | `ScanSettingsForm`, `PageArnForm` |
| `scans/templates/scans/` | 5 templates, extend `arnlabels/base.html` |

Shared CSS lives in `arnlabels/static/arnlabels/app.css` (`.thumb-grid`,
`.modal`, `.alert-list`, …).

## Open questions / future

- Authentication & access control (none yet).
- ADF batch scan (one `scanimage --batch` call → many pages).
- Multiple scanners.
- Optional OCR of typed text on the page, not just the barcode.
- Keeping `ScanPage` records (thumbnails) after finalize for provenance.
- Retention / lifecycle of `Document` PDFs.
- Multi-sheet volumes interplay (a document longer than one label sheet).
