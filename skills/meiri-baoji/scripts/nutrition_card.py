#!/usr/bin/env python3
"""Render a meal nutrition card PNG for 每日薄肌.

usage: python3 nutrition_card.py <out.png> [spec.json | -]

The spec is JSON (from a file, or stdin when '-' or omitted):
  {"meal": "午餐", "kcal": "550-650", "protein": "30-40", "carb": "60-75",
   "fat": "18-25", "fiber": "6-9", "tip": "一句最值得做的具体建议", "note": "估算值"}
Values are strings so ranges stay ranges. Only "meal" and "kcal" are required; missing
nutrients show "—". The card never shows scores or good/bad labels.
"""
import sys

from _common import font_loader, read_spec, require_pillow, wrap

USAGE = __doc__


def main():
    spec = read_spec(sys.argv, USAGE)
    out = sys.argv[1]
    if not spec.get("meal") or not spec.get("kcal"):
        sys.exit("spec needs at least meal and kcal")
    require_pillow()
    from PIL import Image, ImageDraw

    F = font_loader()
    W = 900
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    tip_lines = wrap(probe, spec.get("tip", ""), F(32), W - 160)[:4] if spec.get("tip") else []
    H = 420 + (60 + 46 * len(tip_lines) if tip_lines else 0) + 70

    im = Image.new("RGB", (W, H), "#FFF8F0")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((30, 30, W - 30, H - 30), 36, fill="#FFFFFF", outline="#F2D9C0", width=3)
    d.rounded_rectangle((30, 30, W - 30, 150), 36, fill="#FF8A4C")
    d.rectangle((30, 100, W - 30, 150), fill="#FF8A4C")
    d.text((70, 62), "%s · 约 %s 千卡" % (spec["meal"], spec["kcal"]), font=F(44), fill="white")

    cells = [("蛋白质", "protein", "#E85D5D"), ("碳水", "carb", "#E0A526"), ("脂肪", "fat", "#4A9BD9"), ("纤维", "fiber", "#4CAF7A")]
    cw = (W - 140) // 4
    for i, (label, key, color) in enumerate(cells):
        x = 70 + i * cw
        value = str(spec.get(key) or "—")
        d.rounded_rectangle((x, 190, x + cw - 16, 340), 22, fill="#FAFAFA", outline=color, width=3)
        d.text((x + 20, 205), label, font=F(28), fill="#555555")
        size = 44
        while size > 26 and d.textlength(value + " g", font=F(size)) > cw - 56:
            size -= 2
        d.text((x + 20, 260), value, font=F(size), fill=color)
        if value != "—":
            d.text((x + 24 + d.textlength(value, font=F(size)), 260 + size - 26), "g", font=F(24), fill="#777777")

    y = 375
    d.line((70, y, W - 70, y), fill="#EADBCB", width=2)
    if tip_lines:
        d.text((70, y + 20), "建议", font=F(26), fill="#FF8A4C")
        for i, line in enumerate(tip_lines):
            d.text((70, y + 60 + i * 46), line, font=F(32), fill="#333333")
    d.text((70, H - 80), spec.get("note") or "估算值", font=F(22), fill="#AAAAAA")
    im.save(out)
    print(out)


if __name__ == "__main__":
    main()
