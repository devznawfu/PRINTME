"""Dev-only visual demo of the Smart Layout Engine.

Packs a realistic mixed batch of photo jobs through the REAL packer,
then draws each resulting A4 sheet as a PNG with cutting grid lines -
what the admin will eventually preview before printing. Nothing here is
wired into the app; safe to delete or ignore.

Usage:
    venv/Scripts/python.exe scripts/preview_packing.py

Output: preview/sheet-01.png, sheet-02.png, ... (open them in Explorer)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from printme.layout_engine.packer import pack
from printme.layout_engine.render import render_sheet
from printme.layout_engine.types import PhotoItem


def make_demo_items():
    """A busy morning: three customers' worth of mixed-size orders."""
    orders = [
        ("P-001 Maria", [("Passport", 4), ("2x2", 2)]),
        ("P-002 Ben",   [("1x1", 8)]),
        ("P-003 Cy",    [("Visa", 6), ("1x1", 2), ("2x2", 1)]),
    ]
    items = []
    for ticket, sizes in orders:
        n = 0
        for size_name, qty in sizes:
            for _ in range(qty):
                n += 1
                items.append(PhotoItem(item_id=f"{ticket}-{n}", size_name=size_name))
    return items


COLORS = {
    "1x1": "#7cb5ec",
    "2x2": "#8fd694",
    "Passport": "#f2a65a",
    "Visa": "#d98cb3",
}


def draw_sheet(packed, sheet_render, out_path):
    img = Image.new(
        "RGB", (sheet_render.sheet_width, sheet_render.sheet_height), "white"
    )
    draw = ImageDraw.Draw(img)

    # Usable area box
    draw.rectangle(
        [
            sheet_render.usable_x,
            sheet_render.usable_y,
            sheet_render.usable_x + sheet_render.usable_width,
            sheet_render.usable_y + sheet_render.usable_height,
        ],
        outline="#bbbbbb",
        width=3,
    )

    # One rectangle per placed item (grid lines come from render.py)
    for line in sheet_render.grid_lines:
        draw.line([line.x1, line.y1, line.x2, line.y2], fill="#333333", width=4)

    # Label each placement from the packed geometry
    for placed in packed.items:
        fill = COLORS[placed.size_name]
        draw.rectangle(
            [placed.x + 2, placed.y + 2, placed.x + placed.width - 2,
             placed.y + placed.height - 2],
            fill=fill,
        )
        label = f"{placed.size_name}"
        if placed.rotated:
            label += " (rot)"
        # Small photos get short text; center whatever fits
        draw.text((placed.x + 10, placed.y + 10), label, fill="black")

    img.save(out_path)
    return out_path


def main():
    items = make_demo_items()
    print(f"Packing {len(items)} photos for 3 customers...")
    sheets = pack(items)
    print(f"-> {len(sheets)} A4 sheet(s) at 300 DPI")

    out_dir = Path(__file__).resolve().parent.parent / "preview"
    out_dir.mkdir(exist_ok=True)

    for sheet in sheets:
        path = draw_sheet(
            sheet,
            render_sheet(sheet),
            out_dir / f"sheet-{sheet.sheet_index + 1:02d}.png",
        )
        print(f"wrote {path.relative_to(out_dir.parent)} ({len(sheet.items)} photos)")

    print("\nOpen the preview/ folder to see the result.")


if __name__ == "__main__":
    main()
