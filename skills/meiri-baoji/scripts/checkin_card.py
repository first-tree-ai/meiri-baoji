#!/usr/bin/env python3
"""Render a 每日薄肌 check-in card PNG (1080×1440, 3:4).

AGENT: STOP — do not read further. Everything you need (fields, examples, rules) is in SKILL.md, section
「打卡卡片」. Write the JSON from there and run the command; the script checks its own layout.

usage: python3 checkin_card.py <kind> <out.png> [spec.json | -]

Fields for each kind and the rules are in SKILL.md, section 打卡卡片. After drawing, the script checks its own layout and
prints "OK <out.png>" (send it as is), "WARN: …" (fix the JSON once) or exits with "NOT_ENOUGH_DATA: …" (reply in text).
"""
import json
import math
import re
import os
import random
import sys

from _common import font_loader, require_pillow, wrap

USAGE = __doc__
KINDS = ("meal", "meal-split", "meal-polaroid", "workout", "workout-poster", "workout-list", "daily-nutrition",
         "daily-timeline", "daily-workout", "daily-highlight", "weekly", "weekly-bars")
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
SPORTS = ("strength", "run", "cycle", "swim", "yoga", "hiit")

W, H, R = 1080, 1440, 26
TEAL = (0, 211, 186)
THEMES = {
    "light": dict(bg=(248, 246, 242), tile=(255, 255, 255), inset=(244, 241, 236), ink=(28, 28, 32),
                  sub=(120, 116, 110), track=(232, 228, 222), line=(232, 228, 222), accent_text=(0, 150, 132)),
    "dark": dict(bg=(10, 10, 10), tile=(26, 26, 26), inset=(38, 38, 38), ink=(255, 255, 255),
                 sub=(150, 150, 150), track=(60, 60, 60), line=(44, 44, 44), accent_text=TEAL),
}

Image = ImageDraw = ImageFont = F = None
T = THEMES["light"]
# Text, bars and tiles drawn on the card, for the overlap check (tests/check_cards.py).
LAYOUT = []
# Where the top and the middle of a CJK line sit above its baseline, as a share of the font size. Fonts disagree
# about ascender height (Noto Sans CJK on Linux puts "top" ~0.26 em lower than macOS Heiti), so every system-font
# text is placed by its baseline with these fixed offsets and lands in the same spot on every machine.
TOP_TO_BASELINE, MIDDLE_TO_BASELINE = 0.86, 0.36


def draw(im):
    """ImageDraw that anchors system-font text on its baseline and records what it draws."""

    class Draw(ImageDraw.ImageDraw):
        def text(self, xy, text, fill=None, font=None, anchor=None, **kw):
            x, y = xy
            anchor = anchor or "la"
            if not str(getattr(font, "path", "")).endswith("xiaota-wordmark.ttf"):
                if anchor[1] == "a":
                    y, anchor = y + TOP_TO_BASELINE * font.size, anchor[0] + "s"
                elif anchor[1] == "m":
                    y, anchor = y + MIDDLE_TO_BASELINE * font.size, anchor[0] + "s"
            super().text((x, y), text, fill=fill, font=font, anchor=anchor, **kw)
            if text.strip():
                LAYOUT.append(("text", self.textbbox((x, y), text, font=font, anchor=anchor), text))

    return Draw(im)


def mark(kind, box):
    LAYOUT.append((kind, tuple(int(v) for v in box), ""))


def fit(d, text, size, width, min_size=None):
    """Shrink text down to min_size to fit width, then cut it with an ellipsis. Returns (text, size)."""
    text = str(text)
    min_size = min_size or size
    while size > min_size and d.textlength(text, font=F(size)) > width:
        size -= 2
    if d.textlength(text, font=F(size)) > width:
        while text and d.textlength(text + "…", font=F(size)) > width:
            text = text[:-1]
        text += "…"
    return text, size


# ---------- primitives ----------

def cover(img, w, h, focus=(0.5, 0.5)):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s + 1), int(img.height * s + 1)), Image.LANCZOS)
    x = min(max(int(img.width * focus[0] - w / 2), 0), img.width - w)
    y = min(max(int(img.height * focus[1] - h / 2), 0), img.height - h)
    return img.crop((x, y, x + w, y + h))


def round_mask(w, h, r):
    m = Image.new("L", (w * 3, h * 3), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), r * 3, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def grad(w, h, a0, a1, start=0.0):
    g = Image.new("L", (1, h))
    for y in range(h):
        t = max(0.0, (y / h - start) / (1 - start)) if y / h > start else 0.0
        g.putpixel((0, y), int(a0 + (a1 - a0) * t))
    return g.resize((w, h))


def open_photo(path):
    try:
        return Image.open(path).convert("RGB")
    except (OSError, ValueError):
        sys.exit("cannot open photo: %s" % path)


# Sports without their own placeholder borrow the closest one.
SPORT_ALIASES = {"walk": "run", "hike": "run", "步行": "run", "徒步": "run", "跑步": "run", "飞盘": "run", "frisbee": "run",
                 "ball": "run", "篮球": "run", "足球": "run", "羽毛球": "run", "网球": "run", "骑行": "cycle", "单车": "cycle",
                 "row": "cycle", "划船": "cycle", "游泳": "swim", "瑜伽": "yoga", "pilates": "yoga", "普拉提": "yoga",
                 "stretch": "yoga", "拉伸": "yoga", "跳绳": "hiit", "jump rope": "hiit", "crossfit": "hiit", "力量": "strength",
                 "攀岩": "strength", "climb": "strength"}


def placeholder(sport):
    sport = str(sport or "").strip().lower()
    sport = sport if sport in SPORTS else SPORT_ALIASES.get(sport, "strength")
    folder = os.path.join(ASSETS, "placeholders")
    names = sorted(n for n in os.listdir(folder) if n.startswith(sport + "-"))
    return open_photo(os.path.join(folder, random.choice(names)))


def thumb(im, photo, box, r=22):
    x0, y0, x1, y1 = box
    im.paste(cover(photo, x1 - x0, y1 - y0), (x0, y0), round_mask(x1 - x0, y1 - y0, r))


ICON_WORDS = [("moon", ("夜宵", "睡", "晚安")), ("drop", ("喝水", "水 ")), ("dumbbell", ("练", "跑", "训练", "健身", "骑", "游", "瑜伽", "步")),
              ("cup", ("早", "奶", "咖啡", "茶", "饮", "拿铁")), ("apple", ("加餐", "零食", "水果", "下午")),
              ("bowl", ("午", "晚", "餐", "饭", "面"))]


def icon_kind(text, default="bowl"):
    text = str(text or "")
    for kind, words in ICON_WORDS:
        if any(w in text for w in words):
            return kind
    return default


def icon(im, cx, cy, size, kind, color=TEAL):
    """A simple line icon (bowl, cup, apple, moon, drop, dumbbell), drawn at 4x for smooth edges."""
    s = 4
    n = size * s
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    c = color + (255,)
    w = max(2, n // 14)
    if kind == "bowl":
        g.pieslice((n * .1, n * .2, n * .9, n * .9), 0, 180, fill=c)
        g.rectangle((n * .1, n * .52, n * .9, n * .57), fill=c)
        g.line((n * .55, n * .08, n * .78, n * .5), fill=c, width=w)
        g.line((n * .68, n * .05, n * .86, n * .48), fill=c, width=w)
    elif kind == "cup":
        g.rounded_rectangle((n * .15, n * .3, n * .68, n * .88), n // 10, fill=c)
        g.arc((n * .55, n * .4, n * .9, n * .72), -90, 90, fill=c, width=w)
        for x in (.3, .5):
            g.arc((n * x - n * .06, n * .04, n * x + n * .06, n * .24), 90, 270, fill=c, width=w // 2 + 1)
    elif kind == "apple":
        g.ellipse((n * .14, n * .26, n * .86, n * .92), fill=c)
        g.line((n * .5, n * .3, n * .52, n * .1), fill=c, width=w)
        g.ellipse((n * .54, n * .06, n * .78, n * .2), fill=c)
    elif kind == "moon":
        g.ellipse((n * .12, n * .12, n * .88, n * .88), fill=c)
        g.ellipse((n * .36, n * .02, n * 1.02, n * .7), fill=(0, 0, 0, 0))  # bite out a crescent
    elif kind == "drop":
        g.ellipse((n * .22, n * .38, n * .78, n * .94), fill=c)
        g.polygon([(n * .5, n * .04), (n * .24, n * .58), (n * .76, n * .58)], fill=c)
    else:  # dumbbell
        g.rounded_rectangle((n * .08, n * .3, n * .24, n * .7), n // 20, fill=c)
        g.rounded_rectangle((n * .76, n * .3, n * .92, n * .7), n // 20, fill=c)
        g.rectangle((n * .24, n * .45, n * .76, n * .55), fill=c)
    layer = layer.resize((size, size), Image.LANCZOS)
    im.paste(layer, (int(cx - size / 2), int(cy - size / 2)), layer)


def soft_teal():
    return tuple(int(c * 0.12 + b * 0.88) for c, b in zip(TEAL, (255, 255, 255)))


def meal_placeholder(im, d, box, name, desc, r=20):
    """No photo: light teal tile with a meal icon and the dish (or meal name), so it sits well next to photos."""
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, r, fill=soft_teal())
    w = x1 - x0
    text = desc or name or ""
    if w >= 300:  # wide tile: icon left, text right
        icon(im, x0 + 60, (y0 + y1) // 2, 52, icon_kind(name or desc))
        d.text((x0 + 104, (y0 + y1) // 2), fit(d, text, 26, w - 128, 20)[0], font=F(26), fill=T["accent_text"],
               anchor="lm")
    else:
        icon(im, (x0 + x1) // 2, y0 + 50, 56, icon_kind(name or desc))
        if text:
            t, size = fit(d, text, 22, w - 20, 18)
            d.text(((x0 + x1) // 2, y0 + 104), t, font=F(size), fill=T["accent_text"], anchor="mm")


def ring(d, cx, cy, r, w, frac, color, track):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=track, width=w)
    if frac > 0:
        d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * min(frac, 1), fill=color, width=w)


def gauge(im, cx, cy, r, width, frac, sweep=240):
    """Large open arc with round caps, drawn at 3x for smooth edges."""
    s = 3
    size = (r + width) * 2 * s
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    c, rr, ww = size // 2, r * s, width * s
    start = 90 + (360 - sweep) / 2

    def seg(a0, a1, color):
        g.arc((c - rr, c - rr, c + rr, c + rr), a0, a1, fill=color, width=ww)
        for a in (a0, a1):
            px = c + (rr - ww / 2) * math.cos(math.radians(a))
            py = c + (rr - ww / 2) * math.sin(math.radians(a))
            g.ellipse((px - ww / 2, py - ww / 2, px + ww / 2, py + ww / 2), fill=color)

    seg(start, start + sweep, T["track"] + (255,))
    if frac > 0:
        seg(start, start + sweep * min(frac, 1), TEAL + (255,))
    layer = layer.resize((size // s, size // s), Image.LANCZOS)
    im.paste(layer, (cx - size // s // 2, cy - size // s // 2), layer)


def lines_of(d, text, font, width, limit):
    """At most limit lines; a cut-off text ends in "…" instead of stopping mid-sentence."""
    lines = wrap(d, text, font, width)
    # No one- or two-character widow on the last line: carry two characters down with it.
    if len(lines) >= 2 and len(lines[-1]) <= 2 and len(lines[-2]) > 4 and "\n" not in str(text)[-4:]:
        lines[-2], lines[-1] = lines[-2][:-2], lines[-2][-2:] + lines[-1]
    if len(lines) <= limit:
        return lines
    last = lines[limit - 1]
    while last and d.textlength(last + "…", font=font) > width:
        last = last[:-1]
    return lines[:limit - 1] + [last.rstrip("，、,;；") + "…"]


# ---------- brand and shared blocks ----------

def tag(d, x, y, text):
    text, _ = fit(d, text, 28, 420)
    w = d.textlength(text, font=F(28)) + 56
    d.rounded_rectangle((x, y, x + w, y + 60), 30, outline=TEAL, width=3)
    d.text((x + w / 2, y + 30), text, font=F(28), fill=TEAL, anchor="mm")


def brand_chip(im, x_right, y, shadow=False):
    """Solid white capsule: @ mark on white, 小塔 in the teal wordmark, 薄肌搭子 in dark grey."""
    wordmark = ImageFont.truetype(os.path.join(ASSETS, "xiaota-wordmark.ttf"), 34)
    d = draw(im)
    h = 60
    w = int(16 + 40 + 10 + d.textlength("小塔", font=wordmark) + 12 + d.textlength("薄肌搭子", font=F(26)) + 24)
    x = x_right - w
    if shadow:
        sh = Image.new("L", (w + 40, h + 40), 0)
        ImageDraw.Draw(sh).rounded_rectangle((20, 22, w + 20, h + 22), h // 2, fill=40)
        from PIL import ImageFilter

        sh = sh.filter(ImageFilter.GaussianBlur(8))
        im.paste(Image.new("RGB", sh.size, (0, 0, 0)), (x - 20, y - 20), sh)
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=(255, 255, 255))
    logo = Image.open(os.path.join(ASSETS, "xiaota-mark.png")).convert("RGBA").resize((40, 40), Image.LANCZOS)
    im.paste(logo, (x + 16, y + 10), logo)
    tx = x + 66
    d.text((tx, y + h // 2), "小塔", font=wordmark, fill=TEAL, anchor="lm")
    d.text((tx + d.textlength("小塔", font=wordmark) + 12, y + h // 2), "薄肌搭子", font=F(26), fill=(70, 70, 75),
           anchor="lm")


def header(im, d, title, on_photo=False):
    tag(d, 48, 48, title)
    brand_chip(im, W - 48, 48, shadow=not on_photo and T is THEMES["light"])


def tomorrow(d, text, y=H - 118):
    if not text:
        return
    d.rounded_rectangle((48, y, 56, y + 64), 4, fill=TEAL)
    text, size = fit(d, text, 32, W - 128, 26)
    d.text((80, y + 32), text, font=F(size), fill=T["ink"], anchor="lm")


TILE_H = 190


def nutrient_tiles(d, x0, x1, y, items, h=TILE_H, fill=None):
    """Three short tiles, each in three rows: name / number (+ "/ target g") / one short thick bar.
    The bar is capped at 100%; the number shrinks (then the target is dropped) so it never leaves the tile."""
    gap = 16
    cw = (x1 - x0 - (len(items) - 1) * gap) // len(items)
    for i, (name, value, rest, frac) in enumerate(items):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle((x, y, x + cw, y + h), 22, fill=fill or T["tile"])
        mark("box", (x, y, x + cw, y + h))
        inner = cw - 44
        d.text((x + 22, y + 20), fit(d, name, 22, inner)[0], font=F(22), fill=T["sub"])
        size = 36
        while size > 26 and d.textlength(value, font=F(size)) + 6 + d.textlength(rest, font=F(22)) > inner:
            size -= 2
        if d.textlength(value, font=F(size)) + 6 + d.textlength(rest, font=F(22)) > inner:
            rest = "g" if rest else rest
        value, size = fit(d, value, size, inner - (d.textlength(rest, font=F(22)) + 6 if rest else 0), 22)
        base = y + 122
        d.text((x + 22, base), value, font=F(size), fill=T["ink"], anchor="ls")
        if rest:
            d.text((x + 22 + d.textlength(value, font=F(size)) + 6, base), rest, font=F(22), fill=T["sub"], anchor="ls")
        if frac is not None:
            by, bx1 = y + h - 38, x + cw - 22
            d.rounded_rectangle((x + 22, by, bx1, by + 14), 7, fill=T["track"])
            d.rounded_rectangle((x + 22, by, x + 22 + max(14, int((bx1 - x - 22) * max(0, min(frac, 1)))), by + 14),
                                7, fill=TEAL)
            mark("bar", (x + 22, by, bx1, by + 14))


def macro_items(macros):
    """[{"name", "value", "target"}] → nutrient tile tuples; target is optional."""
    items = []
    for m in macros or []:
        value, tgt = number(m.get("value")), number(m.get("target"))
        if value is None or not m.get("name"):
            continue
        items.append((m["name"], "%g" % value, "/ %g g" % tgt if tgt else "g", value / tgt if tgt else None))
    return items[:3]


def score_ring(d, cx, cy, score, label, r=100, on_photo=False):
    if on_photo:
        d.ellipse((cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12), fill=(0, 0, 0))
    ring(d, cx, cy, r, 14, score / 100, TEAL, (70, 70, 70) if on_photo else T["track"])
    ink = (255, 255, 255) if on_photo else T["ink"]
    score, size = fit(d, score, 60, 2 * r - 44, 36)
    d.text((cx, cy - 16), score, font=F(size), fill=ink, anchor="mm")
    d.text((cx, cy + 44), fit(d, label, 20, 2 * r - 40)[0], font=F(20), fill=(190, 190, 190) if on_photo else T["sub"], anchor="mm")


def photo_hero(photo, h, mono, focus=(0.5, 0.5)):
    im = cover(photo, W, h, focus)
    if mono:
        im = Image.blend(im.convert("L").convert("RGB"), Image.new("RGB", (W, h), (0, 0, 0)), 0.45)
    im.paste(Image.new("RGB", (W, h), (0, 0, 0)), (0, 0), grad(W, h, 0, 235 if mono else 200, 0.4))
    top = Image.new("L", (1, 220))
    for y in range(220):
        top.putpixel((0, y), int(170 * (1 - y / 220)))
    im.paste(Image.new("RGB", (W, 220), (0, 0, 0)), (0, 0), top.resize((W, 220)))
    return im


def summary_lines(d, text, size, width, limit=2):
    return lines_of(d, text or "", F(size), width, limit)


# ---------- data clean-up ----------

UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*[-–~～]\s*(\d+(?:\.\d+)?))?\s*"
                     r"(kcal|Kcal|KCAL|大卡|卡路里|千卡|kJ|KJ|kj|千焦|lbs|lb|磅|miles|mile|mi|英里|km|KM|公里|公斤)(?![A-Za-z])")


def _conv(n, unit):
    if unit in ("kJ", "KJ", "kj", "千焦"):
        return "%d" % round(float(n) / 4.184), "千卡"
    if unit in ("lbs", "lb", "磅"):
        return ("%.1f" % (float(n) * 0.4536)).rstrip("0").rstrip("."), "kg"
    if unit in ("miles", "mile", "mi", "英里"):
        return ("%.1f" % (float(n) * 1.609)).rstrip("0").rstrip("."), "公里"
    if unit in ("km", "KM", "公里"):
        return n, "公里"
    if unit == "公斤":
        return n, "kg"
    return n, "千卡"


def unitize(text):
    """Energy → 千卡, weight → kg, distance → 公里, inside any text the Agent passed."""

    def sub(m):
        a, unit = _conv(m.group(1), m.group(3))
        if m.group(2):
            b, _ = _conv(m.group(2), m.group(3))
            return "%s–%s %s" % (a, b, unit)
        return "%s %s" % (a, unit)

    return UNIT_RE.sub(sub, text)


def clean(value, key=""):
    if isinstance(value, dict):
        return {k: clean(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v, key) for v in value]
    if isinstance(value, str) and key != "photo":
        return unitize(value)
    return value


def number(value):
    """A number from 1650, "1650", "约 1650 千卡" or "6900 kJ" (already turned into 千卡 by clean)."""
    if isinstance(value, (int, float)):
        return value
    m = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(m.group()) if m else None


def bare(value, unit):
    """Drop a unit the value already ends with, so the card never shows "千卡 千卡"."""
    value = str(value if value is not None else "").strip()
    if unit and value.endswith(unit):
        value = value[: -len(unit)].rstrip()
    return value


def extra_text(e):
    if isinstance(e, str):
        return e
    return " ".join(str(v) for v in (e.get("name"), e.get("value"), e.get("unit")) if v not in (None, ""))


def extras_row(d, y, extras, x0=48, x1=W - 48):
    """One "其他" strip for data the card has no slot for (心率, 配速, 体重, 补剂…); shows what fits, then +N."""
    h = 84
    d.rounded_rectangle((x0, y, x1, y + h), 22, fill=T["tile"])
    mark("box", (x0, y, x1, y + h))
    d.text((x0 + 28, y + h // 2), "其他", font=F(24), fill=T["sub"], anchor="lm")
    x, right = x0 + 28 + d.textlength("其他", font=F(24)) + 28, x1 - 28
    items = [extra_text(e) for e in extras if extra_text(e)]
    for i, text in enumerate(items):
        rest = len(items) - i - 1
        more = "+%d" % rest if rest else ""
        reserve = d.textlength(" " + more, font=F(24)) + 24 if more else 0
        w = d.textlength(text, font=F(26))
        if x + w > right - reserve:
            if i == 0:
                text = fit(d, text, 26, right - x - reserve)[0]
                w = d.textlength(text, font=F(26))
            else:
                d.text((x, y + h // 2), "+%d" % (len(items) - i), font=F(24), fill=T["sub"], anchor="lm")
                break
        d.text((x, y + h // 2), text, font=F(26), fill=T["ink"], anchor="lm")
        x += w + 36
    return y + h


EXTRAS_H = 84 + 24


# ---------- cards ----------

# Layout rules for every card (phone readable): one hero (photo or the main number) plus at most three blocks,
# clear gaps between blocks, line height ≥ 1.3 × the font, and less content rather than smaller text.
# Sizes below are logical: they pass through PHONE_MIN (24 → 38 px, 30 → 44 px, 36 → 48 px, 44 → 54 px, 52 → 60 px).
GAP = 40


def meal(spec):
    global T
    T = THEMES["light"]
    if not spec.get("photo") or not spec.get("kcal"):
        sys.exit("NOT_ENOUGH_DATA: meal needs photo and kcal; reply in text instead")
    m, tg = spec.get("macros") or {}, spec.get("targets") or {}
    items = []
    for key, name in (("protein", "蛋白质"), ("carb", "碳水"), ("fat", "脂肪")):
        if m.get(key):
            try:
                lo_hi = [float(p) for p in str(m[key]).replace("–", "-").split("-") if p.strip()]
            except ValueError:
                lo_hi = []
            frac = (sum(lo_hi) / len(lo_hi)) / tg[key] if tg.get(key) and lo_hi else None
            items.append((name, str(m[key]).replace("-", "–"), "g", frac))
    line = spec.get("line")
    body = GAP + (TILE_H + GAP if items else 0) + (120 + GAP if line else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(open_photo(spec["photo"]), hero_h, False), (0, 0))
    d = draw(im)
    header(im, d, spec.get("label") or "这一餐", on_photo=True)
    if spec.get("dishes"):
        d.text((48, hero_h - 196), lines_of(d, spec["dishes"], F(40), W - 96, 1)[0], font=F(40), fill=(255, 255, 255))
    big, size = fit(d, "约 " + bare(spec["kcal"], "千卡").lstrip("约 ").replace("-", "–"), 112,
                    W - 96 - 16 - d.textlength("千卡", font=F(30)), 64)
    d.text((48, hero_h - 50), big, font=F(size), fill=(255, 255, 255), anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, hero_h - 50), "千卡", font=F(30), fill=(255, 255, 255),
           anchor="ls")
    y = hero_h + GAP
    if items:
        nutrient_tiles(d, 48, W - 48, y, items)
        y += TILE_H + GAP
    if line:
        bg = tuple(int(c * 0.14 + b * 0.86) for c, b in zip(TEAL, T["tile"]))
        d.rounded_rectangle((48, y, W - 48, y + 120), R, fill=bg)
        d.rounded_rectangle((48, y, 58, y + 120), 5, fill=TEAL)
        line, size = fit(d, line, 30, W - 160, 24)
        d.text((84, y + 60), line, font=F(size), fill=T["ink"], anchor="lm")
    return im


def stat_tiles(d, y, stats, h=170):
    """Up to three tiles: a name and a big value with its unit on the same line (no sub-captions)."""
    cw = (W - 96 - (len(stats) - 1) * 20) // len(stats)
    for i, s in enumerate(stats):
        x = 48 + i * (cw + 20)
        d.rounded_rectangle((x, y, x + cw, y + h), R, fill=T["tile"])
        mark("box", (x, y, x + cw, y + h))
        d.text((x + 26, y + 26), fit(d, s.get("name", ""), 24, cw - 52)[0], font=F(24), fill=T["sub"])
        unit = s.get("unit") or s.get("sub") or ""
        unit = "" if unit.startswith("+") else fit(d, unit, 24, (cw - 52) // 2)[0]
        value, size = fit(d, bare(s.get("value", ""), unit).lstrip("约 "), 52, cw - 52 - (10 + d.textlength(unit, font=F(24)) if unit else 0), 30)
        d.text((x + 26, y + h - 30), value, font=F(size), fill=T["ink"], anchor="ls")
        if unit:
            d.text((x + 36 + d.textlength(value, font=F(size)), y + h - 32), unit, font=F(24), fill=T["sub"], anchor="ls")
    return y + h


def exercise_rows(d, y, rows, total, title=None):
    """At most three exercises, then "+N 个动作"; each row is name on the left, sets and weight on the right."""
    shown = rows[:3]
    more = total - len(shown)
    head = 84 if title else 30
    h = head + len(shown) * 72 + (64 if more else 0) + 20
    d.rounded_rectangle((48, y, W - 48, y + h), R, fill=T["tile"])
    if title:
        d.text((84, y + 26), title, font=F(30), fill=T["ink"])
    for i, (name, val) in enumerate(shown):
        ry = y + head + i * 72 + 36
        if i:
            d.line((84, ry - 36, W - 84, ry - 36), fill=T["line"], width=2)
        val, vsize = fit(d, val, 30, 440, 24)
        d.text((W - 84, ry), val, font=F(vsize), fill=TEAL, anchor="rm")
        d.text((84, ry), fit(d, name, 30, W - 200 - d.textlength(val, font=F(vsize)))[0], font=F(30), fill=T["ink"],
               anchor="lm")
    if more:
        d.text((84, y + head + len(shown) * 72 + 30), "+ %d 个动作" % more, font=F(24), fill=T["sub"], anchor="lm")
    return y + h


def as_rows(items):
    out = []
    for row in items:
        if isinstance(row, (list, tuple)):
            name, val = (list(row) + ["", ""])[:2]
        else:
            name = row.get("name", "")
            val = " · ".join(str(row[k]) for k in ("sets", "weight") if row.get(k))
            if row.get("delta"):
                val = "%s  %s" % (row["delta"], val) if val else row["delta"]
        out.append((name, val))
    return out


def workout(spec):
    global T
    T = THEMES["dark"]
    if not spec.get("minutes"):
        sys.exit("NOT_ENOUGH_DATA: workout needs minutes; reply in text instead")
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    # The big number already shows the minutes, so a 时长 tile would only repeat it.
    stats = [x for x in spec.get("stats") or [] if x.get("name") not in ("时长", "用时", "训练时长")][:3]
    rows = as_rows(spec.get("exercises") or [])
    total = len(rows) + (spec.get("more") or 0)
    ex_h = (30 + min(3, len(rows)) * 72 + (64 if total > min(3, len(rows)) else 0) + 20) if rows else 0
    body = GAP + (170 + GAP if stats else 0) + (ex_h + GAP if rows else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    d = draw(im)
    header(im, d, spec.get("label") or "运动", on_photo=True)
    if spec.get("line"):
        lines = summary_lines(d, spec["line"], 52, W - 96)
        ty = hero_h - 250 - (len(lines) - 1) * 80
        for i, ln in enumerate(lines):
            d.text((48, ty + i * 80), ln, font=F(52), fill=(255, 255, 255) if i < len(lines) - 1 else TEAL)
    big, size = fit(d, str(spec["minutes"]), 112, 520, 64)
    d.text((48, hero_h - 50), big, font=F(size), fill=TEAL, anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, hero_h - 50), "分钟", font=F(30), fill=(255, 255, 255),
           anchor="ls")
    if spec.get("score") is not None:
        score_ring(d, W - 150, hero_h - 118, spec["score"], spec.get("score_label") or "运动分", r=96, on_photo=True)
    y = hero_h + GAP
    if stats:
        y = stat_tiles(d, y, stats) + GAP
    if rows:
        exercise_rows(d, y, rows, total)
    return im


def daily_nutrition(spec):
    """Calories and macros for the day. Meals are not repeated here: each meal already had its own card."""
    global T
    T = THEMES["light"]
    spec["kcal"], spec["kcal_goal"] = number(spec.get("kcal")), number(spec.get("kcal_goal"))
    if not spec.get("kcal"):
        sys.exit("NOT_ENOUGH_DATA: daily-nutrition needs kcal; reply in text instead")
    kcal_v = int(spec["kcal"])
    goal = int(spec["kcal_goal"]) if spec["kcal_goal"] else None
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "每日总结")
    has_score = spec.get("score") is not None
    items = macro_items(spec.get("macros"))
    lines = summary_lines(d, spec.get("summary"), 44, W - 96 - (250 if has_score else 0))
    head_h = max(len(lines) * 72, 230 if has_score else 0)
    card_h = (620 if items else 470) if goal else 260 + (TILE_H + 40 if items else 0)
    bottom = H - 150 if spec.get("tomorrow") else H - 48
    y0 = 150 + max(0, (bottom - 150 - head_h - GAP - card_h) // 2)
    for i, ln in enumerate(lines):
        d.text((48, y0 + (head_h - len(lines) * 72) // 2 + i * 72), ln, font=F(44), fill=T["ink"])
    if has_score:
        score_ring(d, W - 150, y0 + head_h // 2, spec["score"], "薄肌分")
    top = y0 + head_h + GAP
    bot = top + card_h
    d.rounded_rectangle((48, top, W - 48, bot), R, fill=T["tile"])
    d.text((84, top + 30), "热量", font=F(30), fill=T["ink"])
    if goal:
        gcx, gcy = W // 2, top + 290
        gauge(im, gcx, gcy, 190, 44, kcal_v / goal)
        kcal, size = fit(d, kcal_v, 96, 300, 60)
        d.text((gcx, gcy - 24), kcal, font=F(size), fill=T["ink"], anchor="mm")
        d.text((gcx, gcy + 52), fit(d, "目标 %s 千卡" % goal, 24, 280)[0], font=F(24), fill=T["sub"], anchor="mm")
    else:
        kcal, size = fit(d, "约 %d" % kcal_v, 96, 600, 60)
        d.text((84, top + 200), kcal, font=F(size), fill=T["ink"], anchor="ls")
        d.text((84 + d.textlength(kcal, font=F(size)) + 14, top + 200), "千卡", font=F(30), fill=T["sub"], anchor="ls")
    if items:
        nutrient_tiles(d, 84, W - 84, bot - TILE_H - 36, items, fill=T["inset"])
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_timeline(spec):
    """The day in at most five rows (title only), then the day's macros."""
    global T
    T = THEMES["light"]
    if len(spec.get("events") or []) < 2:
        sys.exit("NOT_ENOUGH_DATA: daily-timeline needs at least 2 events; use another card or reply in text")
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "每日总结")
    tx0 = 48
    if spec.get("score") is not None:
        score_ring(d, 152, 270, spec["score"], "薄肌分", r=104)
        tx0 = 296
    lines = summary_lines(d, spec.get("summary"), 44, W - 48 - tx0)
    for i, ln in enumerate(lines):
        d.text((tx0, 270 - len(lines) * 36 + i * 72), ln, font=F(44), fill=T["ink"])
    items = macro_items(spec.get("macros"))
    events = spec.get("events") or []
    if len(events) > 5:
        events = events[:4] + [{"time": "", "title": "还有 %d 项" % (len(events) - 4)}]
    y0 = 430
    y_end = (H - 150 - TILE_H - GAP) if items else H - 150
    step = min(124, (y_end - y0) // len(events))
    x_axis, disc = 176, 84
    d.line((x_axis, y0 + disc // 2, x_axis, y0 + step * (len(events) - 1) + disc // 2), fill=T["line"], width=4)
    for i, e in enumerate(events):
        yy = y0 + i * step
        cy = yy + disc // 2
        hl = bool(e.get("highlight"))
        if e.get("time"):
            tm, size = fit(d, e["time"], 24, 104, 20)
            d.text((48, cy), tm, font=F(size), fill=T["sub"], anchor="lm")
        d.ellipse((x_axis - 12, cy - 12, x_axis + 12, cy + 12), fill=TEAL if hl else T["ink"])
        tx = 216
        if e.get("photo"):
            thumb(im, open_photo(e["photo"]), (tx, yy, tx + disc, yy + disc), disc // 2)
        elif e.get("time"):
            d.ellipse((tx, yy, tx + disc, yy + disc), fill=soft_teal())
            icon(im, tx + disc // 2, cy, int(disc * 0.5), "dumbbell" if hl else icon_kind(e.get("title"), "bowl"))
        tx += disc + 28
        title, size = fit(d, e.get("title", ""), 30, W - 48 - tx, 24)
        d.text((tx, cy), title, font=F(size), fill=T["accent_text"] if hl else T["ink"], anchor="lm")
    if items:
        nutrient_tiles(d, 48, W - 48, H - 150 - TILE_H - 10, items)
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_workout(spec):
    """Training first: the day's line and score on the photo, then the day's stats and the week. The exercise list
    is not repeated here: it is on the workout card."""
    global T
    T = THEMES["dark"]
    if not (spec.get("stats") or spec.get("exercises")):
        sys.exit("NOT_ENOUGH_DATA: daily-workout needs stats or exercises; reply in text instead")
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    stats = spec.get("stats") or []
    if spec.get("exercises"):  # the list header already says "N 个动作"
        stats = [x for x in stats if x.get("name") not in ("动作", "动作数")]
    stats = stats[:3]
    if not stats and spec.get("exercises"):
        stats = [{"name": "动作", "value": str(len(spec["exercises"])), "unit": "个"}]
    week = spec.get("week")
    body = GAP + (170 + GAP if stats else 0) + (150 + GAP if week else 0) + (130 if spec.get("tomorrow") else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    im.paste(Image.new("RGB", (W, 140), T["bg"]), (0, hero_h - 140), grad(W, 140, 0, 255))
    d = draw(im)
    header(im, d, "每日总结", on_photo=True)
    lines = summary_lines(d, spec.get("summary"), 44, W - 96 - 230)
    for i, ln in enumerate(lines):
        d.text((48, hero_h - 60 - (len(lines) - 1 - i) * 72), ln, font=F(44), fill=T["ink"], anchor="ls")
    if spec.get("label"):
        d.text((48, hero_h - 60 - len(lines) * 72), spec["label"], font=F(24), fill=TEAL, anchor="ls")
    if spec.get("score") is not None:
        score_ring(d, W - 150, hero_h - 130, spec["score"], spec.get("score_label") or "运动分")
    y = hero_h + GAP
    if stats:
        y = stat_tiles(d, y, stats) + GAP
    if week:
        done = list(week.get("done") or [])[:7] + [None] * 7
        count = sum(1 for t in done[:7] if t)
        plan = week.get("plan")
        d.text((48, y + 20), "本周训练", font=F(30), fill=T["ink"], anchor="lm")
        d.text((W - 48, y + 20), "%d / %s 次" % (count, plan) if plan else "%d 次" % count, font=F(30), fill=TEAL,
               anchor="rm")
        step = (W - 96) / 7
        cy = y + 104
        for i, ch in enumerate("一二三四五六日"):
            cx, r = 48 + (i + 0.5) * step, 34
            if done[i]:
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TEAL)
                d.text((cx, cy), ch, font=F(24), fill=(10, 10, 10), anchor="mm")
            else:
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=T["track"], width=3)
                d.text((cx, cy), ch, font=F(24), fill=T["sub"], anchor="mm")
            if i == week.get("today"):
                d.ellipse((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), outline=T["ink"], width=3)
    tomorrow(d, spec.get("tomorrow"))
    return im


def meal_split(spec):
    """Meal, split layout: the photo fills the top, the number and macros sit on a calm panel below."""
    global T
    T = THEMES["light"]
    if not spec.get("photo") or not spec.get("kcal"):
        sys.exit("NOT_ENOUGH_DATA: meal-split needs photo and kcal; reply in text instead")
    tg, m = spec.get("targets") or {}, spec.get("macros") or {}
    items = []
    for key, name in (("protein", "蛋白质"), ("carb", "碳水"), ("fat", "脂肪")):
        if m.get(key):
            try:
                lo_hi = [float(x) for x in str(m[key]).replace("–", "-").split("-") if x.strip()]
            except ValueError:
                lo_hi = []
            items.append((name, str(m[key]).replace("-", "–"), "g",
                          (sum(lo_hi) / len(lo_hi)) / tg[key] if tg.get(key) and lo_hi else None))
    photo_h = 700 if items else 860
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(cover(open_photo(spec["photo"]), W, photo_h), (0, 0))
    top = Image.new("L", (1, 200))
    for yy in range(200):
        top.putpixel((0, yy), int(150 * (1 - yy / 200)))
    im.paste(Image.new("RGB", (W, 200), (0, 0, 0)), (0, 0), top.resize((W, 200)))
    d = draw(im)
    header(im, d, spec.get("label") or "这一餐", on_photo=True)
    y = photo_h + GAP
    if spec.get("dishes"):
        d.text((48, y), lines_of(d, spec["dishes"], F(30), W - 96, 1)[0], font=F(30), fill=T["sub"])
        y += 70
    big, size = fit(d, "约 " + bare(spec["kcal"], "千卡").lstrip("约 ").replace("-", "–"), 104,
                    W - 96 - 16 - d.textlength("千卡", font=F(30)), 64)
    d.text((48, y + 100), big, font=F(size), fill=T["ink"], anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, y + 100), "千卡", font=F(30), fill=T["sub"], anchor="ls")
    y += 100 + GAP
    if items:
        nutrient_tiles(d, 48, W - 48, y, items)
        y += TILE_H + GAP
    if spec.get("line") and y + 64 < H - 40:
        tomorrow(d, spec["line"], y=max(y, H - 118))
    return im


def meal_polaroid(spec):
    """Meal, framed photo on a light page with one big number. Good when the macros are unknown."""
    global T
    T = THEMES["light"]
    if not spec.get("photo") or not spec.get("kcal"):
        sys.exit("NOT_ENOUGH_DATA: meal-polaroid needs photo and kcal; reply in text instead")
    im = Image.new("RGB", (W, H), tuple(int(c * 0.08 + b * 0.92) for c, b in zip(TEAL, THEMES["light"]["bg"])))
    d = draw(im)
    header(im, d, spec.get("label") or "这一餐")
    x0, y0, x1, y1 = 110, 160, W - 110, 900
    d.rounded_rectangle((x0 - 24, y0 - 24, x1 + 24, y1 + 110), 28, fill=(255, 255, 255))
    thumb(im, open_photo(spec["photo"]), (x0, y0, x1, y1), 18)
    if spec.get("dishes"):
        d.text((W // 2, y1 + 55), lines_of(d, spec["dishes"], F(30), x1 - x0, 1)[0], font=F(30), fill=T["sub"],
               anchor="mm")
    big, size = fit(d, "约 " + bare(spec["kcal"], "千卡").lstrip("约 ").replace("-", "–"), 112, W - 200, 64)
    by = 1150
    full = d.textlength(big, font=F(size)) + 16 + d.textlength("千卡", font=F(30))
    bx = (W - full) // 2
    d.text((bx, by), big, font=F(size), fill=T["ink"], anchor="ls")
    d.text((bx + d.textlength(big, font=F(size)) + 16, by), "千卡", font=F(30), fill=T["sub"], anchor="ls")
    tomorrow(d, spec.get("line"))
    return im


def workout_poster(spec):
    """Workout, no photo needed: one huge number for the minutes, up to three stats, one line."""
    global T
    T = THEMES["dark"]
    if not spec.get("minutes"):
        sys.exit("NOT_ENOUGH_DATA: workout-poster needs minutes; reply in text instead")
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    d.ellipse((W - 520, -260, W + 260, 520), fill=(14, 40, 37))
    header(im, d, spec.get("label") or "运动", on_photo=True)
    lines = summary_lines(d, spec.get("line"), 44, W - 96)
    for i, ln in enumerate(lines):
        d.text((48, 190 + i * 72), ln, font=F(44), fill=(255, 255, 255) if i < len(lines) - 1 else TEAL)
    stats = [x for x in spec.get("stats") or [] if x.get("name") not in ("时长", "用时", "训练时长")][:3]
    base = 760 if stats or spec.get("score") is not None else 900  # nothing below: sit lower on the page
    big, size = fit(d, str(spec["minutes"]), 340, W - 300, 160)
    d.text((48, base), big, font=F(size), fill=TEAL, anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 20, base), "分钟", font=F(44), fill=(255, 255, 255), anchor="ls")
    y = 860
    if stats:
        y = stat_tiles(d, y, stats) + GAP
    if spec.get("score") is not None:
        score_ring(d, W - 160, 1240, spec["score"], spec.get("score_label") or "运动分")
    return im


def workout_list(spec):
    """Workout, exercise-first: up to five lifts in large rows, then the minutes. For strength days."""
    global T
    T = THEMES["dark"]
    rows = as_rows(spec.get("exercises") or [])
    if not rows or not spec.get("minutes"):
        sys.exit("NOT_ENOUGH_DATA: workout-list needs minutes and exercises; use workout or workout-poster")
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, spec.get("label") or "运动", on_photo=True)
    if spec.get("line"):
        d.text((48, 200), lines_of(d, spec["line"].replace("\n", ""), F(44), W - 96, 1)[0], font=F(44), fill=TEAL)
    shown, more = rows[:5], len(rows) + (spec.get("more") or 0) - min(5, len(rows))
    y = 300
    for i, (name, val) in enumerate(shown):
        cy = y + i * 128 + 64
        d.rounded_rectangle((48, cy - 56, W - 48, cy + 56), R, fill=T["tile"])
        d.text((84, cy), "%d" % (i + 1), font=F(30), fill=TEAL, anchor="lm")
        val, vsize = fit(d, val, 30, 420, 24)
        d.text((W - 84, cy), val, font=F(vsize), fill=T["sub"], anchor="rm")
        d.text((150, cy), fit(d, name, 36, W - 260 - d.textlength(val, font=F(vsize)))[0], font=F(36), fill=T["ink"],
               anchor="lm")
    y += len(shown) * 128
    if more > 0:
        d.text((84, y + 30), "+ %d 个动作" % more, font=F(24), fill=T["sub"], anchor="lm")
    big, size = fit(d, str(spec["minutes"]), 120, 400, 72)
    d.text((48, H - 60), big, font=F(size), fill=TEAL, anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, H - 60), "分钟", font=F(30), fill=(255, 255, 255), anchor="ls")
    if spec.get("score") is not None:
        score_ring(d, W - 150, H - 140, spec["score"], spec.get("score_label") or "运动分")
    return im


def daily_highlight(spec):
    """Daily summary for a light day: today's best moment in big type, the score, one thing for tomorrow."""
    global T
    T = THEMES["light"]
    if not spec.get("best") and not spec.get("summary"):
        sys.exit("NOT_ENOUGH_DATA: daily-highlight needs best (or summary); reply in text instead")
    im = Image.new("RGB", (W, H), tuple(int(c * 0.10 + b * 0.90) for c, b in zip(TEAL, THEMES["light"]["bg"])))
    d = draw(im)
    header(im, d, "每日总结")
    d.text((48, 260), "今天最棒的一刻", font=F(30), fill=T["accent_text"])
    lines = lines_of(d, spec.get("best") or spec.get("summary"), F(64), W - 96, 4)
    for i, ln in enumerate(lines):
        d.text((48, 340 + i * 90), ln, font=F(64), fill=T["ink"])
    y = 340 + len(lines) * 90 + 60
    if spec.get("score") is not None:
        score_ring(d, 160, y + 120, spec["score"], "薄肌分", r=110)
    facts = [f for f in (spec.get("facts") or [])[:2] if f]
    for i, f in enumerate(facts):
        d.text((330, y + 80 + i * 80), fit(d, str(f), 36, W - 380)[0], font=F(36), fill=T["ink"], anchor="lm")
    if spec.get("tomorrow"):
        tomorrow(d, "明天：" + spec["tomorrow"].lstrip("明天：:"))
    return im


def week_dots(d, y, done, today=None, plan=None):
    done = list(done or [])[:7] + [None] * 7
    count = sum(1 for t in done[:7] if t)
    d.text((48, y + 20), "本周训练", font=F(30), fill=T["ink"], anchor="lm")
    d.text((W - 48, y + 20), "%d / %s 次" % (count, plan) if plan else "%d 次" % count, font=F(30), fill=TEAL,
           anchor="rm")
    step = (W - 96) / 7
    cy = y + 104
    for i, ch in enumerate("一二三四五六日"):
        cx, r = 48 + (i + 0.5) * step, 34
        if done[i]:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TEAL)
            d.text((cx, cy), ch, font=F(24), fill=(10, 10, 10), anchor="mm")
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=T["track"], width=3)
            d.text((cx, cy), ch, font=F(24), fill=T["sub"], anchor="mm")
        if i == today:
            d.ellipse((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), outline=T["ink"], width=3)
    return cy + 50


def weekly(spec):
    """Week summary (dark): training days as the hero, up to three week totals, the best moment, next week's one thing."""
    global T
    T = THEMES["dark"]
    days = spec.get("days") or []
    if not days and not spec.get("stats"):
        sys.exit("NOT_ENOUGH_DATA: weekly needs days or stats; reply in text instead")
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "本周总结", on_photo=True)
    if spec.get("range"):
        d.text((48, 170), spec["range"], font=F(24), fill=T["sub"], anchor="lm")
    trained = sum(1 for x in days if x.get("trained"))
    d.text((48, 420), str(trained), font=F(240), fill=TEAL, anchor="ls")
    d.text((48 + d.textlength(str(trained), font=F(240)) + 20, 420), "天在练", font=F(44), fill=(255, 255, 255),
           anchor="ls")
    y = week_dots(d, 470, [x.get("trained") for x in days], plan=spec.get("plan")) + GAP
    stats = (spec.get("stats") or [])[:3]
    if stats:
        y = stat_tiles(d, y, stats) + GAP
    if spec.get("best"):
        d.text((48, y + 10), "本周最棒", font=F(24), fill=TEAL)
        for i, ln in enumerate(lines_of(d, spec["best"], F(44), W - 96, 2)):
            d.text((48, y + 70 + i * 72), ln, font=F(44), fill=T["ink"])
    if spec.get("next"):
        tomorrow(d, "下周：" + spec["next"].lstrip("下周：:"))
    return im


def weekly_bars(spec):
    """Week summary (light): one bar per day (score, or calories when there is no score), the best moment, next week."""
    global T
    T = THEMES["light"]
    days = spec.get("days") or []
    vals = [number(x.get("score")) if x.get("score") is not None else number(x.get("kcal")) for x in days][:7]
    if sum(1 for v in vals if v) < 2:
        sys.exit("NOT_ENOUGH_DATA: weekly-bars needs scores or calories on at least 2 days; use weekly")
    by_score = any(x.get("score") is not None for x in days)
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "本周总结")
    if spec.get("range"):
        d.text((48, 170), spec["range"], font=F(24), fill=T["sub"], anchor="lm")
    d.rounded_rectangle((48, 230, W - 48, 760), R, fill=T["tile"])
    d.text((84, 270), "每天的薄肌分" if by_score else "每天的热量（千卡）", font=F(30), fill=T["ink"], anchor="lm")
    top_v = max(v for v in vals if v)
    step = (W - 168) / 7
    for i, ch in enumerate("一二三四五六日"):
        v = vals[i] if i < len(vals) else None
        cx = 84 + (i + 0.5) * step
        base = 690
        if v:
            h = int(320 * v / top_v)
            d.rounded_rectangle((cx - 36, base - h, cx + 36, base), 14, fill=TEAL if v == top_v else (150, 225, 215))
            d.text((cx, base - h - 12), "%d" % v if by_score else "%.1fk" % (v / 1000), font=F(24), fill=T["ink"],
                   anchor="ms")
        else:
            d.rounded_rectangle((cx - 36, base - 8, cx + 36, base), 4, fill=T["track"])
        d.text((cx, base + 46), ch, font=F(24), fill=T["sub"], anchor="ms")
    y = 760 + GAP
    stats = (spec.get("stats") or [])[:3]
    if stats:
        y = stat_tiles(d, y, stats) + GAP
    if spec.get("best"):
        d.text((48, y + 10), "本周最棒", font=F(24), fill=T["accent_text"])
        for i, ln in enumerate(lines_of(d, spec["best"], F(44), W - 96, 2)):
            d.text((48, y + 70 + i * 72), ln, font=F(44), fill=T["ink"])
    if spec.get("next"):
        tomorrow(d, "下周：" + spec["next"].lstrip("下周：:"))
    return im


# Cards are read on a phone at about a third of their 1080 px width, so small text is raised to stay legible
# (a 1080 px card opened full-screen is ~390 pt wide: 38 px ≈ 14 pt, the smallest text we allow). Larger sizes keep their hierarchy.
PHONE_MIN = {20: 38, 22: 38, 24: 38, 26: 40, 28: 44, 30: 44, 32: 46, 36: 48, 38: 48, 40: 52, 42: 52, 44: 54, 52: 60, 54: 60, 60: 68, 64: 72}


def phone_fonts(load):
    def F(size):
        return load(PHONE_MIN.get(size, max(size, 38)))

    return F


RENDER = {"meal": meal, "meal-split": meal_split, "meal-polaroid": meal_polaroid, "workout": workout,
          "workout-poster": workout_poster, "workout-list": workout_list, "daily-nutrition": daily_nutrition,
          "daily-timeline": daily_timeline, "daily-workout": daily_workout, "daily-highlight": daily_highlight,
          "weekly": weekly, "weekly-bars": weekly_bars}


def layout_problems():
    """Texts that overlap each other or a bar, or leave their tile or the card (the agent never has to look)."""
    def hit(a, b):
        return a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1

    def inside(a, b):
        return a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1

    texts = [(b, t) for k, b, t in LAYOUT if k == "text"]
    bars = [b for k, b, _ in LAYOUT if k == "bar"]
    boxes = [b for k, b, _ in LAYOUT if k == "box"]
    out = []
    for i, (a, ta) in enumerate(texts):
        if not inside(a, (0, 0, W, H)):
            out.append("%s 超出卡片" % ta)
        out += ["%s 和 %s 重叠" % (ta, tb) for b, tb in texts[i + 1:] if hit(a, b)]
        out += ["%s 压到进度条" % ta for b in bars if hit(a, b)]
        cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
        out += ["%s 超出小格" % ta for b in boxes if b[0] <= cx <= b[2] and b[1] <= cy <= b[3] and not inside(a, b)]
    return out


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in KINDS:
        sys.exit(USAGE)
    kind, out = sys.argv[1], sys.argv[2]
    source = sys.argv[3] if len(sys.argv) > 3 else "-"
    text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as error:
        sys.exit("Invalid JSON spec: %s" % error)
    require_pillow()
    global Image, ImageDraw, ImageFont, F
    from PIL import Image, ImageDraw, ImageFont  # noqa: F811

    F = phone_fonts(font_loader())
    render = RENDER[kind]
    del LAYOUT[:]
    render(clean(spec)).save(out, optimize=True)
    problems = layout_problems()
    print("WARN: " + "; ".join(problems[:5]) if problems else "OK " + out)


if __name__ == "__main__":
    main()
