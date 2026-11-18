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
  page followed by its continuation pages. `GET /scans/documents/` lists them
  all (ARN, page count, date, source batch, PDF link), with a `?view=thumbnails`
  grid view — see below.

## Batch states

```
scanning ──stop──▶ review ──finalize──▶ finalized
```

- **scanning** — the console (`/scans/<id>/`). "Scan Page" acquires one page;
  "Stop" (modal confirm) moves the batch to *review*.
- **review** — `/scans/<id>/review/`. Fix detections, reorder (drag & drop),
  remove pages, resolve alerts, then "Finalize".
- **finalized** — PDFs created; raw scan images and `ScanPage` rows deleted.

Any non-finalized batch can be **discarded** from the console, the review page
or the batch list (`POST /scans/<id>/discard/`, `services.discard_batch`): the
`ScanBatch`, every `ScanPage` and all image/thumbnail files are hard-deleted.
There is no undo. A finalized batch cannot be discarded (its `Document`s stay).

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

`ocr.detect_arn` runs `zxingcpp.read_barcodes` (Code 128 only) once per
binarizer (`LocalAverage`, `FixedThreshold`, `GlobalHistogram`) over the whole
page **and** over a 2×3 grid of overlapping tiles, then unions the hits. Two
reasons: the default `LocalAverage` binarizer sometimes misses a crisp barcode
that a fixed threshold reads cleanly, and this build of zxing-cpp stops after
the first symbol it finds — on a page that also carries a Data Matrix the small
ARN Code 128 is otherwise never located in the full image.

Every region is scanned only after a 4× bicubic upscale, never at native
resolution: a label-sized Code 128 on a full-resolution flatbed scan often has
too few pixels per module for zxing-cpp to binarize reliably at native size —
it can come back empty, or (worse) silently misread a digit into a different
but still checksum-valid code. Smaller upscales (e.g. 2×) sit in the same
unreliable regime and were dropped after one produced exactly that kind of
misread on a real scan. See `make test-with-actual-docs` below for the
regression suite this was tuned against.

### Restart recovery

`ScansConfig.ready()` connects a one-shot `request_started` handler that calls
`jobs.recover_stale()`: pages left `scan_status=pending` or `ocr_status=running`
by a crash are marked failed. A half-scanned page is **never** auto re-scanned
(that could double-feed a sheet-fed scanner) — the user just scans again.

## Display labels

In the console and review grids a volume-start page shows its ARN
(`PREFIX 2026 00 042`); a continuation page shows `page N`, its 1-based position
within the document it continues (`views._arn_labels`, carried in the status
JSON as `arn_label`). Pages with no effective ARN fall back to the OCR note.

## Manual override

`/scans/<id>/pages/<pid>/` shows the scan image (click it for a full-width
overlay preview; close with the ✕, a click outside the image, or Esc) and lets
the user:

- **Set ARN** — four fields: the prefix (pre-filled, read-only), the year
  (pre-filled with the current year), the volume and the index. The volume is
  pre-filled when a strict majority of the batch's already-resolved
  volume-start pages share one volume. Posted as `arn_prefix` / `arn_year` /
  `arn_volume` / `arn_index`; the configured prefix always wins and the parts
  are validated by `Arn.volume_start` (year 4 digits, volume 0..99,
  index 0..999).
- **Mark as continuation** — the page becomes `PREFIX 000000000`.
- **Clear override** — fall back to the detected value.

Saving an ARN or marking a continuation returns to the batch review page;
clearing the override stays on the page.

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
   `Document(start_arn, page_count, pdf, batch)`. `Document.thumbnail` is a
   copy of the first page's own `ScanPage.thumbnail` file (already the right
   size — no re-render), left blank if that page never got one.
4. Delete every scan image + thumbnail file and all `ScanPage` rows.
5. `batch.status = finalized`.

## Document list — thumbnail view

`GET /scans/documents/?view=thumbnails` shows a 5×10 grid of `Document`
thumbnails (`views.THUMB_PAGE_SIZE = 50`), paginated with Django's
`Paginator`; `?view=list` (the default) is the original table. Each cell
links to the document's PDF; a document finalized before this field existed,
or whose first page had no thumbnail, renders as a `.thumb.placeholder` cell
with just its ARN.

Once every `<img>` on the current page has loaded (or failed), an inline
script fetches `GET /scans/documents/thumbnails/<page>/`
(`views.document_thumb_urls`, → `DocumentThumbUrls.urls`) for the *next*
page and warms the browser cache for those URLs with throwaway `Image()`
objects — so paging forward is instant once the current page is done
loading. It does nothing on the last page (no next page to prefetch) and
never blocks rendering of the current page.

### Regenerating thumbnails

The **Documents** section of `/settings/` (`siteconfig/settings.html`) has
two buttons, "Regenerate missing thumbnails" and "Regenerate all thumbnails",
posting to `POST /scans/documents/thumbnails/regenerate/`
(`scope=missing` / `scope=all`). Like scanning and OCR, this runs in its own
single-worker background pool (`jobs._THUMB_POOL`) so the request returns
immediately; an inline script on the settings page polls
`GET /scans/documents/thumbnails/regenerate/status/`
(`jobs.thumbnail_regen_status` → `ThumbnailRegenState`) every 1.5 s while a
pass is running and shows "processed / total (N failed)".

`jobs.enqueue_thumbnail_regen` is a no-op (returns `False`, flashes "already
running") if a pass is already in flight — there's no queueing, just the one
worker. `jobs._regenerate_one_thumbnail` rebuilds a `Document`'s thumbnail
from its own `pdf` file: renders page 1 with `pypdfium2`, reuses the same
`_make_thumbnail_jpeg` helper `_run_scan` uses for `ScanPage.thumbnail`
(`THUMB_WIDTH = 320`, JPEG quality 80), replaces the old thumbnail file if
any. A per-document failure is logged and counted, not raised — one bad PDF
doesn't stop the pass. Progress (`running` / `processed` / `failed` /
`total`) is in-memory only, not persisted: a server restart mid-pass just
means running it again.

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

`ScanSettings` singleton — edited in the **Scanner** section of the unified
settings page, which lives in its own tiny app: `siteconfig` serves
`/settings/` (`#scanner` / `#labels` / `#documents` sections). It has no
models of its own — it just edits `arnlabels.PrintSettings` and
`scans.ScanSettings`, and (for `#documents`) reads `scans.Document` counts
and posts to the `scans:thumbnails-regenerate` endpoints above. Old links
(`/scans/settings/`, `/labels/settings/`) redirect there. Also in the Django
admin.

The CUPS printer list and the SANE device list are slow external probes, so
`siteconfig.probe` runs each **once per process** and caches the result (1 h
safety TTL). `SiteconfigConfig.ready()` **warms that cache on boot** in a daemon
thread (`siteconfig.probe.warm`), so the first `/settings/` visit is instant;
a cache miss still probes synchronously as a fallback, and the **Rescan
hardware** button forces a refresh. The boot probe is skipped for management
commands (`test`, `migrate`, …), for the `runserver` autoreload parent, and
when `MINGADOCS_SKIP_HARDWARE_PROBE` is set.

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
| `scans/enums.py`     | `BatchStatus` / `ScanStatus` / `OcrStatus` (TextChoices), `ArnSource`, `ArnMode`, `OcrOutcome`, `AlertLevel`, `AlertCode` |
| `scans/models.py`    | `ScanSettings`, `ScanBatch`, `ScanPage`, `Document` |
| `scans/schemas.py`   | Pydantic models for the JSON boundary (`BatchState`, `PageState`, `AlertState`, `ReorderRequest`, …) |
| `scans/scanner.py`   | `scanimage` subprocess + fake-scanner override |
| `scans/ocr.py`       | Code 128 → ARN detection (`zxing-cpp`); returns an `OcrResult` |
| `scans/jobs.py`      | Background scan/OCR workers, restart recovery |
| `scans/services.py`  | Batch lifecycle, alerts (`Alert` dataclass), finalization |
| `scans/views.py`     | Console, review, page detail, document list, JSON endpoints — every payload is a `scans/schemas.py` model |
| `scans/forms.py`     | `ScanSettingsForm`, `PageArnForm` (exposes `arn_mode()` / `arn_value()`) |
| `scans/templates/scans/` | 5 templates, extend `arnlabels/base.html` |
| `scans/test_actual_docs.py` | OCR regression suite against real scans in `media/documents/` — see below |
| `siteconfig/`        | The `/settings/` page (view + `probe.py` hardware cache); no models |

Shared CSS lives in `arnlabels/static/arnlabels/app.css` (`.thumb-grid`,
`.modal`, `.alert-list`, …).

## Real-document OCR regression suite

`scans/test_actual_docs.py` re-runs `ocr.detect_arn` over every page of every
PDF under `media/documents/**/*.pdf`: page 1 of each document must decode to
the ARN encoded in its own filename (`<prefix><body>.pdf`, the name
`services._pages_to_pdf` writes), every later page must decode to the
continuation marker (`PREFIX 000000000`).

That folder holds real scans and is gitignored (`media/`), so this is never
part of `make test` or CI — it only makes sense on a workstation that has the
documents. Run it with:

- `make test-with-actual-docs` — full run over every page; this is the
  authoritative check and rewrites `.test_actual_docs_failures.json` (under
  `MEDIA_ROOT`) with whatever still fails.
- `make test-with-actual-docs-failed` — re-tests only the `(doc, page)` pairs
  recorded in that file, for a fast inner loop while chasing a detection fix.
  Falls back to skipping with a clear message if nothing has been recorded
  yet (run the full target first).

Rendering a page back out of the finished PDF (rather than from the original
scan bytes) uses `pypdfium2`, a regular dependency.

## Open questions / future

- Authentication & access control (none yet).
- ADF batch scan (one `scanimage --batch` call → many pages).
- Multiple scanners.
- Optional OCR of typed text on the page, not just the barcode.
- Keeping `ScanPage` records (thumbnails) after finalize for provenance.
- Retention / lifecycle of `Document` PDFs.
- Multi-sheet volumes interplay (a document longer than one label sheet).
