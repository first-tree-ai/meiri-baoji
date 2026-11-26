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
KINDS = ("meal", "workout", "daily-nutrition", "daily-timeline", "daily-workout")
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


TILE_H = 140


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
        d.text((x + 22, y + 18), fit(d, name, 22, inner)[0], font=F(22), fill=T["sub"])
        size = 36
        while size > 26 and d.textlength(value, font=F(size)) + 6 + d.textlength(rest, font=F(22)) > inner:
            size -= 2
        if d.textlength(value, font=F(size)) + 6 + d.textlength(rest, font=F(22)) > inner:
            rest = "g" if rest else rest
        value, size = fit(d, value, size, inner - (d.textlength(rest, font=F(22)) + 6 if rest else 0), 22)
        base = y + 86
        d.text((x + 22, base), value, font=F(size), fill=T["ink"], anchor="ls")
        if rest:
            d.text((x + 22 + d.textlength(value, font=F(size)) + 6, base), rest, font=F(22), fill=T["sub"], anchor="ls")
        if frac is not None:
            by, bx1 = y + h - 34, x + cw - 22
            d.rounded_rectangle((x + 22, by, bx1, by + 12), 6, fill=T["track"])
            d.rounded_rectangle((x + 22, by, x + 22 + max(12, int((bx1 - x - 22) * max(0, min(frac, 1)))), by + 12),
                                6, fill=TEAL)
            mark("bar", (x + 22, by, bx1, by + 12))


def macro_items(macros):
    """[{"name", "value", "target"}] → nutrient tile tuples; target is optional."""
    items = []
    for m in macros or []:
        value, tgt = number(m.get("value")), number(m.get("target"))
        if value is None or not m.get("name"):
            continue
        items.append((m["name"], "%g" % value, "/ %g g" % tgt if tgt else "g", value / tgt if tgt else None))
    return items[:3]


def score_ring(d, cx, cy, score, label, r=82, on_photo=False):
    if on_photo:
        d.ellipse((cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12), fill=(0, 0, 0))
    ring(d, cx, cy, r, 14, score / 100, TEAL, (70, 70, 70) if on_photo else T["track"])
    ink = (255, 255, 255) if on_photo else T["ink"]
    score, size = fit(d, score, 60, 2 * r - 44, 36)
    d.text((cx, cy - 10), score, font=F(size), fill=ink, anchor="mm")
    d.text((cx, cy + 34), fit(d, label, 20, 2 * r - 40)[0], font=F(20), fill=(190, 190, 190) if on_photo else T["sub"], anchor="mm")


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
    extras = spec.get("extras") or []
    body = 30 + (TILE_H + 30 if items else 0) + (EXTRAS_H if extras else 0) + (130 if line else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(open_photo(spec["photo"]), hero_h, False), (0, 0))
    d = draw(im)
    header(im, d, spec.get("label") or "这一餐", on_photo=True)
    if spec.get("dishes"):
        for i, ln in enumerate(lines_of(d, spec["dishes"], F(40), W - 96, 2)[::-1]):
            d.text((48, hero_h - 210 - i * 56), ln, font=F(40), fill=(255, 255, 255))
    big, size = fit(d, "约 " + bare(spec["kcal"], "千卡").lstrip("约 ").replace("-", "–"), 112, W - 96 - 16 - d.textlength("千卡", font=F(38)), 64)
    d.text((48, hero_h - 50), big, font=F(size), fill=(255, 255, 255), anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, hero_h - 50), "千卡", font=F(38), fill=(255, 255, 255),
           anchor="ls")
    y = hero_h + 30
    if items:
        nutrient_tiles(d, 48, W - 48, y, items)
        y += TILE_H + 30
    if extras:
        y = extras_row(d, y, extras) + 24
    if line:
        bg = tuple(int(c * 0.14 + b * 0.86) for c, b in zip(TEAL, T["tile"]))
        d.rounded_rectangle((48, y, W - 48, y + 100), R, fill=bg)
        d.rounded_rectangle((48, y, 58, y + 100), 5, fill=TEAL)
        line, size = fit(d, line, 30, W - 160, 26)
        d.text((84, y + 50), line, font=F(size), fill=T["ink"], anchor="lm")
    return im


def workout(spec):
    global T
    T = THEMES["dark"]
    if not spec.get("minutes"):
        sys.exit("NOT_ENOUGH_DATA: workout needs minutes; reply in text instead")
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    # The big number already shows the minutes, so a 时长 tile would only repeat it.
    stats = [x for x in spec.get("stats") or [] if x.get("name") not in ("时长", "用时", "训练时长")]
    extras = [extra_text(dict(x, value="%s%s" % (x.get("value", ""), x.get("sub", "")))) for x in stats[3:]] \
        + list(spec.get("extras") or [])
    stats = stats[:3]
    rows = spec.get("exercises") or []
    more = (spec.get("more") or 0) + max(0, len(rows) - 5)
    rows = rows[:5]
    body = 30 + (210 if stats else 0) + (EXTRAS_H if extras else 0) \
        + ((len(rows) * 56 + (40 if more else 0) + 70) if rows else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    d = draw(im)
    header(im, d, spec.get("label") or "运动", on_photo=True)
    if spec.get("line"):
        lines = summary_lines(d, spec["line"], 54, W - 96)
        ty = hero_h - 290 - (len(lines) - 1) * 66
        for i, ln in enumerate(lines):
            d.text((48, ty + i * 66), ln, font=F(54), fill=(255, 255, 255) if i < len(lines) - 1 else TEAL)
    big, size = fit(d, str(spec["minutes"]), 112, 560, 64)
    d.text((48, hero_h - 54), big, font=F(size), fill=TEAL, anchor="ls")
    d.text((48 + d.textlength(big, font=F(size)) + 16, hero_h - 54), "分钟", font=F(38), fill=(255, 255, 255),
           anchor="ls")
    if spec.get("score") is not None:
        score_ring(d, W - 130, hero_h - 92, spec["score"], spec.get("score_label") or "运动分", r=68, on_photo=True)
    y = hero_h + 30
    if stats:
        cw = (W - 96 - (len(stats) - 1) * 16) // len(stats)
        for i, s in enumerate(stats):
            x = 48 + i * (cw + 16)
            d.rounded_rectangle((x, y, x + cw, y + 180), R, fill=T["tile"])
            mark("box", (x, y, x + cw, y + 180))
            d.text((x + 26, y + 30), fit(d, s.get("name", ""), 24, cw - 52)[0], font=F(24), fill=T["sub"])
            value, size = fit(d, bare(s.get("value", ""), s.get("sub")), 40, cw - 52, 24)
            d.text((x + 26, y + 80), value, font=F(size), fill=T["ink"])
            if s.get("sub"):
                sub = fit(d, s["sub"], 22, cw - 52)[0]
                d.text((x + 26, y + 138), sub, font=F(22), fill=TEAL if sub.startswith("+") else T["sub"])
        y += 210
    if extras:
        y = extras_row(d, y, extras) + 24
    if rows:
        h = len(rows) * 56 + (40 if more else 0) + 40
        d.rounded_rectangle((48, y, W - 48, y + h), R, fill=T["tile"])
        ry = y + 22
        for row in rows:
            name, val = (list(row) + ["", ""])[:2] if isinstance(row, (list, tuple)) else (row.get("name", ""), " · ".join(
                str(row[k]) for k in ("sets", "weight") if row.get(k)))
            val, vsize = fit(d, val, 30, 520, 24)
            name = fit(d, name, 30, W - 160 - d.textlength(val, font=F(vsize)) - 32)[0]
            d.text((80, ry), name, font=F(30), fill=T["ink"])
            d.text((W - 80, ry), val, font=F(vsize), fill=TEAL, anchor="ra")
            ry += 56
        if more:
            d.text((80, ry), "+ %d 个动作" % more, font=F(22), fill=T["sub"])
    return im


def daily_nutrition(spec):
    global T
    T = THEMES["light"]
    spec["kcal"], spec["kcal_goal"] = number(spec.get("kcal")), number(spec.get("kcal_goal"))
    if not spec.get("kcal"):
        sys.exit("NOT_ENOUGH_DATA: daily-nutrition needs kcal; reply in text instead")
    spec["kcal"] = int(spec["kcal"])
    spec["kcal_goal"] = int(spec["kcal_goal"]) if spec["kcal_goal"] else None
    activity = " · ".join(x for x in [spec.get("activity")] + [extra_text(e) for e in spec.get("extras") or []] if x)
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "每日总结")
    has_score = spec.get("score") is not None
    items = macro_items(spec.get("macros"))
    goal = spec.get("kcal_goal")
    meals = spec.get("meals") or []
    # Lay the blocks out first so a day with little data sits in the middle of the card, not at the top.
    n_lines = len(summary_lines(d, spec.get("summary"), 44, W - 96 - (220 if has_score else 0)))
    head_h = 230 if (has_score or activity) else (n_lines * 60 + 50 if n_lines else 0)
    card_h = (590 if items else 450) if goal else 230 + (TILE_H + 32 if items else 0)
    meals_h = (28 + 308) if meals else 0
    bottom = H - 150 if spec.get("tomorrow") else H - 48
    y0 = 140 + max(0, (bottom - 140 - head_h - card_h - meals_h) // 2)
    for i, ln in enumerate(summary_lines(d, spec.get("summary"), 44, W - 96 - (220 if has_score else 0))):
        d.text((48, y0 + 10 + i * 60), ln, font=F(44), fill=T["ink"])
    if activity:
        d.text((48, y0 + 142), fit(d, activity, 24, W - 340)[0], font=F(24), fill=T["sub"])
    if has_score:
        cx, cy = W - 140, y0 + 80
        score_ring(d, cx, cy, spec["score"], "薄肌分")
        if spec.get("delta"):
            d.text((cx, cy + 118), "比昨天 %s" % spec["delta"], font=F(24), fill=T["accent_text"], anchor="mm")
    top = y0 + head_h
    bot = top + card_h  # the gauge needs a goal; without one the card shows just the number
    d.rounded_rectangle((48, top, W - 48, bot), R, fill=T["tile"])
    d.text((84, top + 30), "热量", font=F(28), fill=T["ink"])
    d.text((W - 84, top + 34), "今天", font=F(24), fill=T["sub"], anchor="ra")
    if goal:
        gcx, gcy = W // 2, top + 290
        gauge(im, gcx, gcy, 205, 48, spec["kcal"] / goal)
        kcal, size = fit(d, spec["kcal"], 92, 300, 48)
        d.text((gcx, gcy - 24), kcal, font=F(size), fill=T["ink"], anchor="mm")
        d.text((gcx, gcy + 42), fit(d, "目标 %s 千卡" % goal, 26, 300)[0], font=F(26), fill=T["sub"], anchor="mm")
    else:
        kcal, size = fit(d, "约 %d" % spec["kcal"], 92, 600, 48)
        d.text((84, top + 190), kcal, font=F(size), fill=T["ink"], anchor="ls")
        d.text((84 + d.textlength(kcal, font=F(size)) + 14, top + 190), "千卡", font=F(32), fill=T["sub"], anchor="ls")
    if items:
        nutrient_tiles(d, 80, W - 80, bot - TILE_H - 32, items, fill=T["inset"])
    if meals:
        top2, bot2 = bot + 28, bot + 336
        d.rounded_rectangle((48, top2, W - 48, bot2), R, fill=T["tile"])
        d.text((84, top2 + 28), "今日餐食", font=F(28), fill=T["ink"])
        d.text((W - 84, top2 + 32), "%d 餐" % len(meals), font=F(24), fill=T["sub"], anchor="ra")
        # Up to 4 slots that always fill the row: 2 meals → halves, 3 → thirds; more than 4 → 3 meals + "+N".
        shown = meals[:4] if len(meals) <= 4 else meals[:3]
        slots = len(shown) + (1 if len(meals) > 4 else 0)
        gap = 16
        cw = (W - 168 - (slots - 1) * gap) // slots
        y = top2 + 84
        for i, m in enumerate(shown):
            x = 84 + i * (cw + gap)
            if m.get("photo"):
                thumb(im, open_photo(m["photo"]), (x, y, x + cw, y + 130), 20)
            else:
                meal_placeholder(im, d, (x, y, x + cw, y + 130), m.get("name"), m.get("desc"))
            label = " ".join(str(v) for v in (m.get("name"), m.get("time")) if v)
            d.text((x, y + 142), fit(d, label, 22, cw)[0], font=F(22), fill=T["ink"])
            if m.get("kcal"):
                k, size = fit(d, "约 %s 千卡" % bare(m["kcal"], "千卡").lstrip("约 "), 20, cw, 16)
                d.text((x, y + 172), k, font=F(size), fill=T["sub"])
        if len(meals) > 4:
            x = 84 + 3 * (cw + gap)
            d.rounded_rectangle((x, y, x + cw, y + 130), 20, fill=soft_teal())
            d.text((x + cw // 2, y + 65), "+%d" % (len(meals) - 3), font=F(44), fill=T["accent_text"], anchor="mm")
            d.text((x, y + 142), "还有 %d 餐" % (len(meals) - 3), font=F(22), fill=T["ink"])
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_timeline(spec):
    global T
    T = THEMES["light"]
    if len(spec.get("events") or []) < 2:
        sys.exit("NOT_ENOUGH_DATA: daily-timeline needs at least 2 events; use another card or reply in text")
    im = Image.new("RGB", (W, H), T["bg"])
    d = draw(im)
    header(im, d, "每日总结")
    tx0 = 48
    if spec.get("score") is not None:
        ring(d, 140, 250, 86, 14, spec["score"] / 100, TEAL, T["track"])
        d.text((140, 240), str(spec["score"]), font=F(64), fill=T["ink"], anchor="mm")
        d.text((140, 284), "薄肌分", font=F(20), fill=T["sub"], anchor="mm")
        tx0 = 270
    for i, ln in enumerate(summary_lines(d, spec.get("summary"), 42, W - 48 - tx0)):
        d.text((tx0, 190 + i * 58), ln, font=F(42), fill=T["ink"])
    facts = []
    if spec.get("delta"):
        facts.append("比昨天 %s" % spec["delta"])
    kcal, goal = number(spec.get("kcal")), number(spec.get("kcal_goal"))
    if kcal:
        facts.append("约 %d / %d 千卡" % (kcal, goal) if goal else "约 %d 千卡" % kcal)
    facts += [extra_text(e) for e in spec.get("extras") or [] if extra_text(e)]
    if facts:
        d.text((tx0 + 2, 314), fit(d, " · ".join(facts), 26, W - 50 - tx0)[0], font=F(26), fill=T["accent_text"])
    items = macro_items(spec.get("macros"))
    events = spec.get("events") or []
    if len(events) > 7:
        events = events[:6] + [{"time": "", "title": "+%d 项" % (len(events) - 6), "sub": "、".join(
            e.get("title", "") for e in events[6:])}]
    y0, y_end = 420, (1136 if items else H - 150) - 40
    if events:
        step = min(130, (y_end - y0) // len(events))
        x_axis = 170
        d.line((x_axis, y0 + 20, x_axis, y0 + step * (len(events) - 1) + 20), fill=T["line"], width=4)
        for i, e in enumerate(events):
            yy = y0 + i * step
            hl = bool(e.get("highlight"))
            tm, size = fit(d, e.get("time", ""), 26, 100, 18)
            d.text((48, yy + 4), tm, font=F(size), fill=T["sub"])
            d.ellipse((x_axis - 12, yy + 8, x_axis + 12, yy + 32), fill=TEAL if hl else T["ink"])
            tx = 210
            disc = min(88, step - 8)
            if e.get("photo"):
                thumb(im, open_photo(e["photo"]), (tx, yy - 10, tx + disc, yy - 10 + disc), disc // 2)
            elif e.get("time") or e.get("sub"):
                d.ellipse((tx, yy - 10, tx + disc, yy - 10 + disc), fill=soft_teal())
                kind = "dumbbell" if hl else icon_kind(e.get("title"), "bowl")
                icon(im, tx + disc // 2, yy - 10 + disc // 2, int(disc * 0.5), kind)
            tx += disc + 24
            d.text((tx, yy - 4), fit(d, e.get("title", ""), 32, W - 48 - tx)[0], font=F(32),
                   fill=T["accent_text"] if hl else T["ink"])
            if e.get("sub"):
                d.text((tx, yy + 42), lines_of(d, e["sub"], F(22), W - 48 - tx, 1)[0], font=F(22), fill=T["sub"])
    if items:
        nutrient_tiles(d, 48, W - 48, 1136, items)
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_workout(spec):
    global T
    T = THEMES["dark"]
    if not (spec.get("stats") or spec.get("exercises")):
        sys.exit("NOT_ENOUGH_DATA: daily-workout needs stats or exercises; reply in text instead")
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    stats = spec.get("stats") or []
    if spec.get("exercises"):  # the list header already says "N 个动作"
        stats = [x for x in stats if x.get("name") not in ("动作", "动作数")]
    extras = [extra_text(dict(x, value="%s%s" % (x.get("value", ""), x.get("unit", "")))) for x in stats[3:]] \
        + list(spec.get("extras") or [])
    stats = stats[:3]
    exercises = spec.get("exercises") or []
    shown = exercises[:5] if len(exercises) <= 5 else exercises[:4] + [{"name": "+%d 个动作" % (len(exercises) - 4)}]
    week = spec.get("week")
    diet = spec.get("diet") or None
    diet_items = macro_items(diet.get("macros")) if diet else []
    fixed = (174 if stats else 0) + (EXTRAS_H if extras else 0) + (150 if week else 0) \
        + (52 + TILE_H + 22 if diet and diet_items else 0) + (150 if spec.get("tomorrow") else 40)
    while shown and H - fixed - (92 + len(shown) * 60 + 40) < 380 and len(shown) > 2:
        shown = shown[:len(shown) - 2] + [{"name": "+%d 个动作" % (len(exercises) - len(shown) + 2)}]
    ex_h = 92 + len(shown) * 60 + 16 if shown else 0
    hero_h = H - fixed - (ex_h + 24 if shown else 0)
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    im.paste(Image.new("RGB", (W, 140), T["bg"]), (0, hero_h - 140), grad(W, 140, 0, 255))
    d = draw(im)
    header(im, d, "每日总结", on_photo=True)
    lines = summary_lines(d, spec.get("summary"), 52, W - 96 - 200)
    for i, ln in enumerate(lines):
        d.text((48, hero_h - 92 - (len(lines) - 1 - i) * 68), ln, font=F(52), fill=T["ink"])
    if spec.get("label"):
        d.text((48, hero_h - 142 - (len(lines) - 1) * 68), spec["label"], font=F(28), fill=TEAL)
    if spec.get("score") is not None:
        score_ring(d, W - 140, hero_h - 130, spec["score"], spec.get("score_label") or "运动分")
    y = hero_h + 10
    if stats:
        cw = (W - 96 - (len(stats) - 1) * 16) // len(stats)
        for i, s in enumerate(stats):
            x = 48 + i * (cw + 16)
            d.rounded_rectangle((x, y, x + cw, y + 150), 22, fill=T["tile"])
            mark("box", (x, y, x + cw, y + 150))
            d.text((x + 24, y + 22), fit(d, s.get("name", ""), 22, cw - 48)[0], font=F(22), fill=T["sub"])
            unit = fit(d, s.get("unit", ""), 22, (cw - 48) // 3)[0]
            value, size = fit(d, bare(s.get("value", ""), s.get("unit")), 52, cw - 48 - 8 - d.textlength(unit, font=F(22)), 28)
            d.text((x + 24, y + 120), value, font=F(size), fill=T["ink"], anchor="ls")
            d.text((x + 32 + d.textlength(value, font=F(size)), y + 118), unit, font=F(22), fill=T["sub"], anchor="ls")
        y += 174
    if extras:
        y = extras_row(d, y, extras) + 24
    if shown:
        d.rounded_rectangle((48, y, W - 48, y + ex_h), R, fill=T["tile"])
        d.text((84, y + 28), "今天练了", font=F(28), fill=T["ink"])
        d.text((W - 84, y + 32), "%d 个动作" % len(exercises), font=F(24), fill=T["sub"], anchor="ra")
        for i, e in enumerate(shown):
            ry = y + 92 + i * 60
            if i:
                d.line((84, ry - 8, W - 84, ry - 8), fill=T["line"], width=2)
            weight = fit(d, e.get("weight", ""), 26, 260)[0]
            wx = W - 84 - d.textlength(weight, font=F(26))
            delta = fit(d, e.get("delta", ""), 22, 120)[0] if e.get("delta") else ""
            if delta:
                wx -= 16 + d.textlength(delta, font=F(22))
            sets = fit(d, e.get("sets", ""), 26, max(40, wx - 20 - 560), 20)
            d.text((84, ry + 22), fit(d, e.get("name", ""), 28, 560 - 84 - 20)[0], font=F(28), fill=T["ink"], anchor="lm")
            d.text((560, ry + 22), sets[0], font=F(sets[1]), fill=T["sub"], anchor="lm")
            d.text((W - 84, ry + 22), weight, font=F(26), fill=T["ink"], anchor="rm")
            if delta:
                d.text((W - 84 - d.textlength(weight, font=F(26)) - 16, ry + 22), delta, font=F(22), fill=TEAL,
                       anchor="rm")
        y += ex_h + 24
    if week:
        done = list(week.get("done") or [])[:7] + [None] * 7
        d.text((48, y), "本周训练", font=F(28), fill=T["ink"])
        count = sum(1 for t in done[:7] if t)
        plan = week.get("plan")
        d.text((W - 48, y + 4), "%d / %s 次" % (count, plan) if plan else "%d 次" % count, font=F(24), fill=TEAL,
               anchor="ra")
        step = (W - 96) / 7
        cy = y + 92
        for i, ch in enumerate("一二三四五六日"):
            cx, r = 48 + (i + 0.5) * step, 30
            if done[i]:
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TEAL)
                d.text((cx, cy), ch, font=F(24), fill=(10, 10, 10), anchor="mm")
            else:
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=T["track"], width=3)
                d.text((cx, cy), ch, font=F(24), fill=T["sub"], anchor="mm")
            if i == week.get("today"):
                d.ellipse((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), outline=T["ink"], width=3)
        y = cy + 46 + 28
    if diet and diet_items:
        d.text((48, y), "饮食", font=F(28), fill=T["ink"])
        dk, dg = number(diet.get("kcal")), number(diet.get("kcal_goal"))
        if dk:
            k = "约 %d / %d 千卡" % (dk, dg) if dg else "约 %d 千卡" % dk
            d.text((W - 48, y + 4), k, font=F(24), fill=T["sub"], anchor="ra")
        nutrient_tiles(d, 48, W - 48, y + 52, diet_items)
    tomorrow(d, spec.get("tomorrow"))
    return im


# Cards are read on a phone at about a third of their 1080 px width, so small text is raised to stay legible
# (28 px on the card ≈ 10 pt on screen). Larger sizes keep their hierarchy.
PHONE_MIN = {20: 28, 22: 28, 24: 30, 26: 30, 28: 32, 30: 34, 32: 34}


def phone_fonts(load):
    def F(size):
        return load(PHONE_MIN.get(size, max(size, 28)))

    return F


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
    render = {"meal": meal, "workout": workout, "daily-nutrition": daily_nutrition,
              "daily-timeline": daily_timeline, "daily-workout": daily_workout}[kind]
    del LAYOUT[:]
    render(clean(spec)).save(out, optimize=True)
    problems = layout_problems()
    print("WARN: " + "; ".join(problems[:5]) if problems else "OK " + out)


if __name__ == "__main__":
    main()
