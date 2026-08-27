# ARN Label Printing Utility

The first feature of mingadocs. A utility page that generates a sheet of
barcode stickers and sends it to a printer, so archive pages can be labelled
for OCR-based lookup.

## Archive Serial Number (ARN)

Every label carries one ARN, encoded as a **Code 128** barcode with the
human-readable value printed underneath it.

```
<prefix> <body>
```

- **prefix** — configurable, global, permanent (see [Settings](#settings)).
  Default `ARN`.
- A single **space** separates the prefix from the body in the human-readable
  line. The **barcode encodes prefix + body with no space.**
- **body** — always 9 digits, one of:

  | Kind          | Body format              | Meaning                              |
  |---------------|--------------------------|--------------------------------------|
  | Volume start  | `YYYY` `VV` `NNN`        | Start of a new document              |
  | Continuation  | `000000000` (9 zeros)    | Page continues the previous document |

  - `YYYY` — year, 4 digits
  - `VV`   — volume, 2 digits (`00`–`99`)
  - `NNN`  — document index within the volume, 3 digits (`000`–`999`)

Example human-readable values: `ARN 202600042`, `ARN 000000000`.

## Page types

The user picks the kind of sheet with a **tab** (Volume / Continuation); the
two submit buttons are **Send to printer** and **Download PDF**. Whichever
matches `print_directly_by_default` (and a configured printer) is shown first
and accent-styled; "Send to printer" is disabled when no printer is set.

### Volume page

Marks the start of new documents. One sheet contains **every** ARN for a given
`(year, volume)`, with the index running from `0` to a maximum:

```
<prefix> <year><volume>000
<prefix> <year><volume>001
...
<prefix> <year><volume>NNN     (NNN = max_index)
```

The user enters only **year** and **volume** (a tab picks the page type; there
is no index field — the index always runs `0` to sheet capacity, `188` for the
L4731REV, so every volume page fills the whole sheet).

Auto-population (both overridable before printing):

- **year** — current year.
- **volume** — `1 +` the highest volume previously allocated for that year, or
  `0` if none. Allocations are tracked in `VolumeAllocation`.

The form also shows the latest recorded volume for the entered year and when it
was created (updates as the year field changes).

On a successful print/download of a volume page, an allocation row
`(year, volume, max_index)` is recorded (`max_index` = sheet capacity − 1) so
the next suggestion advances.

### Continuation page

**Every** label on the sheet is the continuation ARN (`<prefix> 000000000`).
Used to label the 2nd..Nth physical page of a multi-page document.

## Label sheet layout

Initial (and currently only) supported stock:

**Avery Zweckform L4731REV-25** — A4, removable adhesive, 25 sheets.

Geometry extracted from Avery's own layout SVG (script:
`tools/extract_label_geometry.py`) — trust these over datasheet round numbers:

| Property             | Value      |
|----------------------|------------|
| Page size            | A4, 210 × 297 mm |
| Labels per sheet     | 189        |
| Grid                 | 7 columns × 27 rows |
| Label size           | 25.4 × 10 mm |
| Corner radius        | 2 mm (rounded) |
| Left / right margin  | 8.47 / 8.49 mm |
| Top / bottom margin  | 13.49 / 13.51 mm |
| Column pitch / gap   | 27.94 mm / 2.54 mm |
| Row pitch / gap      | 10.00 mm / ~0 mm |

Labels are filled **row-major**: left→right, top→bottom.

Each label renders inside a **safe area** (label edge inset by
`safe_inset`, default 1.5 mm, to clear the rounded corners and printer
registration drift): Code 128 barcode on top, human-readable ARN below.
The barcode is further inset by `pdf.BARCODE_QUIET_MM` (1.2 mm) on each side
and centred, leaving a white quiet zone so the outer bars are not clipped.

> The vendor's explicit safe-area symbol (`#dpo8-final-preview-field-PF194`)
> was **not** present in the saved SVG (only `<use>` references to it), so
> `safe_inset` is our own conservative value. If the real PF194 `<defs>`
> becomes available, replace it with the exact inset.

### Page size / media

The PDF is A4 (`LabelTemplate.media = "A4"`). The grid uses absolute positions,
so it only lands on the labels if the printer uses the **same** page size.

- CUPS jobs are submitted with `media=A4`, `fit-to-page=false`, `scaling=100`
  (`printing.submit_pdf`). A queue whose default is Letter would otherwise clip
  ~17.6 mm off the bottom — i.e. the entire last label row.
- For the **Download PDF** path, print it with "Actual size" / 100 %, media A4,
  never "Fit to printable area".

### Calibration

**Before the first production run**, print one sheet on the target printer and
check alignment against a real label sheet.

`LabelTemplate` has `offset_x` / `offset_y` (mm, positive = left / up) for a
whole-grid nudge to compensate for a printer's non-printable margins. The Avery
template currently ships `offset_y = 1.5` because lower rows were clipped at the
bottom. Re-tune against real output; if it varies by printer this should move
into `PrintSettings`.

### Barcode density

A 12-character Code 128 value (`ARN` + 9 digits) inside a 25.4 mm label leaves a
narrow bar width (~0.12–0.14 mm). That is below the comfortable minimum for many
office lasers and hand scanners. Verify a test sheet scans reliably on the
target hardware; if not, options are a shorter prefix, a laser at 1200 dpi, or a
larger label stock.

## Settings

Global and permanent, stored as a single `PrintSettings` row (django-solo).
Editable on `/labels/settings/` and in the Django admin.

| Field                       | Default | Purpose |
|-----------------------------|---------|---------|
| `arn_prefix`                | `ARN`   | Prefix for every ARN |
| `cups_printer`              | (blank) | CUPS queue name to print to |
| `print_directly_by_default` | `true`  | Print button submits to CUPS vs. returns a PDF download |

## Output / printing

- The server generates the PDF with `reportlab`.
- **Default:** submit the PDF straight to the configured CUPS queue via
  `pycups` (`arnlabels/printing.py`). No client-side print dialog.
- **Always available:** a "Download PDF" option that returns the same PDF as an
  `application/pdf` response instead of printing.
- If no `cups_printer` is configured, only download is offered.
- The settings page lists available CUPS queues (`printing.list_printers()`)
  to choose from.

## Module map

| Module                        | Responsibility |
|-------------------------------|----------------|
| `arnlabels/arn.py`            | ARN grammar, formatting, ARN-list generation per page type |
| `arnlabels/label_templates.py`| Physical sheet geometry |
| `arnlabels/pdf.py`            | reportlab rendering of a sheet |
| `arnlabels/printing.py`       | CUPS integration (list queues, submit job) |
| `arnlabels/services.py`       | Auto-population, sheet building, allocation recording |
| `arnlabels/forms.py`          | Settings form + label batch form |
| `arnlabels/views.py`          | `/` overview, `/labels/` utility, `/labels/settings/` |
| `arnlabels/static/arnlabels/app.css` | Shared stylesheet (light/dark) |
| `arnlabels/models.py`         | `PrintSettings` (singleton), `VolumeAllocation` |

## Status

Implemented and tested: ARN grammar, sheet geometry, PDF rendering, CUPS
submission, both views, form auto-population, volume allocation tracking
(`arnlabels/tests.py`). Pending: printer calibration on real hardware,
multi-sheet volumes, auth.

## Open questions / future

- Multi-sheet volumes when `max_index + 1 > 189`.
- Additional label stocks.
- Optional global mm offset for printer calibration.
- Reprint / history view of past batches.
- Authentication & access control (currently none).
