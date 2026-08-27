#!/usr/bin/env python3
"""Extract label-sheet geometry from an Avery layout SVG/HTML dump.

The vendor's "final preview" markup positions each label cell with a
``#dpo8-final-preview-panel-canvas-0-<index>`` group carrying a
``matrix(1,0,0,1,tx,ty)`` transform, on a page sized in PostScript points
(1 pt = 1/72 in). This script reads those transforms and the page/label
rectangles and prints the geometry in millimetres.

Usage:
    python tools/extract_label_geometry.py path/to/layout.html

Note: the vendor "safe area" symbol (``#dpo8-final-preview-field-PF194``) is
referenced via <use> but its <defs> definition is usually NOT included in a
partial DOM dump - only the cell positions and the rounded-corner outline
(radius from the panel <path>, e.g. ``5.66929`` pt = 2 mm) are recoverable here.
"""
from __future__ import annotations

import re
import sys

PT_PER_MM = 72.0 / 25.4


def main(path: str) -> None:
    s = open(path).read()

    cells = sorted(
        (int(i), float(tx), float(ty))
        for i, tx, ty in re.findall(
            r'id="dpo8-final-preview-panel-canvas-0-(\d+)"\s+'
            r'transform="matrix\(1,0,0,1,([-\d.]+),([-\d.]+)\)"',
            s,
        )
    )
    if not cells:
        sys.exit("no cell transforms found")

    pm = re.search(
        r'dpo8-final-preview-page-0" width="([\d.]+)" height="([\d.]+)"', s
    )
    page_w, page_h = (float(v) for v in pm.groups())

    lm = re.search(
        r'default-background-0-0-drag-rect" x="0" y="0" '
        r'width="([\d.]+)" height="([\d.]+)"',
        s,
    )
    lab_w, lab_h = (float(v) for v in lm.groups())

    xs = sorted({round(c[1], 3) for c in cells})
    ys = sorted({round(c[2], 3) for c in cells})

    cr = re.search(r'"M([\d.]+) 0 L', s)
    corner_r = float(cr.group(1)) if cr else 0.0

    def mm(v: float) -> float:
        return v / PT_PER_MM

    print(f"cells:            {len(cells)}")
    print(f"page:             {mm(page_w):.3f} x {mm(page_h):.3f} mm")
    print(f"label:            {mm(lab_w):.3f} x {mm(lab_h):.3f} mm")
    print(f"grid:             {len(xs)} cols x {len(ys)} rows")
    print(f"index order:      {'row-major' if cells[1][2] == cells[0][2] else 'col-major'}")
    print(f"margin left/top:  {mm(xs[0]):.4f} / {mm(ys[0]):.4f} mm")
    print(f"margin right/bot: {mm(page_w - xs[-1] - lab_w):.4f} / "
          f"{mm(page_h - ys[-1] - lab_h):.4f} mm")
    print(f"column pitch:     {mm(xs[1] - xs[0]):.4f} mm  "
          f"(gap {mm(xs[1] - xs[0] - lab_w):.4f})")
    print(f"row pitch:        {mm(ys[1] - ys[0]):.4f} mm  "
          f"(gap {mm(ys[1] - ys[0] - lab_h):.4f})")
    print(f"corner radius:    {mm(corner_r):.4f} mm")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
