#!/usr/bin/env python3
"""Render a 每日薄肌 check-in card PNG (1080×1440, 3:4).

usage: python3 checkin_card.py <kind> <out.png> [spec.json | -]

kind is one of meal, workout, daily-nutrition, daily-timeline, daily-workout. The spec is JSON
(from a file, or stdin when '-' or omitted). Leave out anything you do not know: a missing field
hides its block, it never shows as 0 or "—". Energy is always 千卡. Lines written by you
(line, summary, tomorrow) must be short, specific to today, and must not repeat a number already
on the card. Use "\\n" to break a line yourself.

meal (light):
  {"photo": "meal.jpg", "label": "晚饭 · 一人份", "dishes": "青椒炒肉 · 炒菠菜 · 米饭",
   "kcal": "650–850", "macros": {"protein": "35–50", "carb": "75–95", "fat": "25–35"},
   "targets": {"protein": 130, "carb": 210, "fat": 60}, "line": "菜很全；炒饭吃半碗就刚好"}
  photo is required (no photo → reply in text). targets are the user's daily grams; with them
  each nutrient tile gets a short bar for this meal's share of the day.

workout (dark):
  {"photo": "gym.jpg", "sport": "strength", "label": "力量 · 腿日", "line": "深蹲又多了 5kg，\\n腿在变强。",
   "minutes": 58, "score": 85, "score_label": "运动分",
   "stats": [{"name": "消耗", "value": "约 320–400", "sub": "千卡"}, {"name": "训练量", "value": "6.9 吨", "sub": "+8% 比上次"}],
   "exercises": [["杠铃深蹲", "4×8 · 60kg"]], "more": 2}
  Without photo the built-in placeholder for sport is used: strength, run, cycle, swim, yoga, hiit.

daily-nutrition (light, calorie gauge):
  {"summary": "蛋白第一次吃够，\\n腿也练完了。", "activity": "腿日 58 分钟 · 睡 7h10m",
   "score": 82, "delta": "+6", "kcal": 1650, "kcal_goal": 1900,
   "macros": [{"name": "蛋白质", "value": 128, "target": 130}, {"name": "碳水", "value": 190, "target": 210},
              {"name": "脂肪", "value": 58, "target": 60}],
   "meals": [{"photo": "a.jpg", "name": "早餐", "time": "08:10", "kcal": "150–170"}],
   "tomorrow": "明天休息，拉伸 10 分钟就好"}

daily-timeline (light, the day as a time axis):
  {"summary": ..., "score": 82, "delta": "+6", "kcal": 1650, "kcal_goal": 1900, "macros": [...],
   "events": [{"time": "08:10", "title": "早餐 · 燕麦奶", "sub": "约 150–170 千卡", "photo": "a.jpg"},
              {"time": "19:10", "title": "腿日 · 58 分钟", "sub": "深蹲 +5kg", "highlight": true}],
   "tomorrow": ...}   (at most 7 events)

daily-workout (dark, training first):
  {"photo": "gym.jpg", "sport": "strength", "label": "腿日 · 19:10", "summary": "深蹲终于加上去了，\\n腿在发抖但很稳。",
   "score": 86, "stats": [{"name": "时长", "value": "58", "unit": "分钟"}, {"name": "消耗", "value": "约 360", "unit": "千卡"}],
   "exercises": [{"name": "深蹲", "sets": "5 × 5", "weight": "80 kg", "delta": "+5 kg"}],
   "week": {"done": [true, true, null, null, null, null, null], "plan": 4, "today": 1},
   "diet": {"kcal": 1650, "kcal_goal": 1900, "macros": [...]},
   "tomorrow": ...}
  Leave out "diet" when there is no diet data that day; the block disappears.
"""
import json
import math
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


def placeholder(sport):
    sport = sport if sport in SPORTS else "strength"
    folder = os.path.join(ASSETS, "placeholders")
    names = sorted(n for n in os.listdir(folder) if n.startswith(sport + "-"))
    return open_photo(os.path.join(folder, random.choice(names)))


def thumb(im, photo, box, r=22):
    x0, y0, x1, y1 = box
    im.paste(cover(photo, x1 - x0, y1 - y0), (x0, y0), round_mask(x1 - x0, y1 - y0, r))


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
    return wrap(d, text, font, width)[:limit]


# ---------- brand and shared blocks ----------

def tag(d, x, y, text):
    w = d.textlength(text, font=F(28)) + 56
    d.rounded_rectangle((x, y, x + w, y + 60), 30, outline=TEAL, width=3)
    d.text((x + w / 2, y + 30), text, font=F(28), fill=TEAL, anchor="mm")


def brand_chip(im, x_right, y, shadow=False):
    """Solid white capsule: @ mark on white, 小塔 in the teal wordmark, 薄肌搭子 in dark grey."""
    wordmark = ImageFont.truetype(os.path.join(ASSETS, "xiaota-wordmark.ttf"), 34)
    d = ImageDraw.Draw(im)
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
    d.text((80, y + 32), lines_of(d, text, F(32), W - 140, 1)[0], font=F(32), fill=T["ink"], anchor="lm")


def nutrient_tiles(d, x0, x1, y, items, h=130, fill=None):
    """Three short tiles: name, number (+ / target or unit), one short thick bar when a fraction is known."""
    gap = 16
    cw = (x1 - x0 - (len(items) - 1) * gap) // len(items)
    for i, (name, value, rest, frac) in enumerate(items):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle((x, y, x + cw, y + h), 22, fill=fill or T["tile"])
        d.text((x + 22, y + 20), name, font=F(22), fill=T["sub"])
        size = 36
        while size > 24 and d.textlength(value, font=F(size)) + 6 + d.textlength(rest, font=F(22)) > cw - 44:
            size -= 2
        d.text((x + 22, y + 52 + (36 - size)), value, font=F(size), fill=T["ink"])
        d.text((x + 22 + d.textlength(value, font=F(size)) + 6, y + 64), rest, font=F(22), fill=T["sub"])
        if frac is not None:
            by, bx1 = y + h - 30, x + cw - 22
            d.rounded_rectangle((x + 22, by, bx1, by + 14), 7, fill=T["track"])
            d.rounded_rectangle((x + 22, by, x + 22 + max(14, int((bx1 - x - 22) * min(frac, 1))), by + 14), 7,
                                fill=TEAL)


def macro_items(macros):
    """[{"name", "value", "target"}] → nutrient tile tuples; target is optional."""
    items = []
    for m in macros or []:
        if m.get("value") is None:
            continue
        tgt = m.get("target")
        items.append((m["name"], str(m["value"]), "/ %s g" % tgt if tgt else "g",
                      m["value"] / tgt if tgt else None))
    return items[:3]


def score_ring(d, cx, cy, score, label, r=82, on_photo=False):
    if on_photo:
        d.ellipse((cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12), fill=(0, 0, 0))
    ring(d, cx, cy, r, 14, score / 100, TEAL, (70, 70, 70) if on_photo else T["track"])
    ink = (255, 255, 255) if on_photo else T["ink"]
    d.text((cx, cy - 10), str(score), font=F(60), fill=ink, anchor="mm")
    d.text((cx, cy + 34), label, font=F(20), fill=(190, 190, 190) if on_photo else T["sub"], anchor="mm")


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


# ---------- cards ----------

def meal(spec):
    global T
    T = THEMES["light"]
    if not spec.get("photo") or not spec.get("kcal"):
        sys.exit("meal needs photo and kcal")
    m, tg = spec.get("macros") or {}, spec.get("targets") or {}
    items = []
    for key, name in (("protein", "蛋白质"), ("carb", "碳水"), ("fat", "脂肪")):
        if m.get(key):
            lo_hi = [float(p) for p in str(m[key]).replace("–", "-").split("-") if p.strip()]
            frac = (sum(lo_hi) / len(lo_hi)) / tg[key] if tg.get(key) and lo_hi else None
            items.append((name, str(m[key]).replace("-", "–"), "g", frac))
    line = spec.get("line")
    body = 30 + (160 if items else 0) + (130 if line else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(open_photo(spec["photo"]), hero_h, False), (0, 0))
    d = ImageDraw.Draw(im)
    header(im, d, spec.get("label") or "这一餐", on_photo=True)
    if spec.get("dishes"):
        for i, ln in enumerate(lines_of(d, spec["dishes"], F(40), W - 96, 2)[::-1]):
            d.text((48, hero_h - 210 - i * 56), ln, font=F(40), fill=(255, 255, 255))
    big = "约 " + str(spec["kcal"]).replace("-", "–")
    d.text((48, hero_h - 150), big, font=F(112), fill=(255, 255, 255))
    d.text((48 + d.textlength(big, font=F(112)) + 16, hero_h - 66), "千卡", font=F(38), fill=(255, 255, 255))
    y = hero_h + 30
    if items:
        nutrient_tiles(d, 48, W - 48, y, items)
        y += 160
    if line:
        bg = tuple(int(c * 0.14 + b * 0.86) for c, b in zip(TEAL, T["tile"]))
        d.rounded_rectangle((48, y, W - 48, y + 100), R, fill=bg)
        d.rounded_rectangle((48, y, 58, y + 100), 5, fill=TEAL)
        d.text((84, y + 50), lines_of(d, line, F(30), W - 170, 1)[0], font=F(30), fill=T["ink"], anchor="lm")
    return im


def workout(spec):
    global T
    T = THEMES["dark"]
    if not spec.get("minutes"):
        sys.exit("workout needs minutes")
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    stats = (spec.get("stats") or [])[:3]
    rows = (spec.get("exercises") or [])[:5]
    more = spec.get("more") or 0
    body = 30 + (210 if stats else 0) + ((len(rows) * 56 + (40 if more else 0) + 70) if rows else 0)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    d = ImageDraw.Draw(im)
    header(im, d, spec.get("label") or "运动", on_photo=True)
    if spec.get("line"):
        lines = summary_lines(d, spec["line"], 54, W - 96)
        ty = hero_h - 290 - (len(lines) - 1) * 66
        for i, ln in enumerate(lines):
            d.text((48, ty + i * 66), ln, font=F(54), fill=(255, 255, 255) if i < len(lines) - 1 else TEAL)
    big = str(spec["minutes"])
    d.text((48, hero_h - 150), big, font=F(112), fill=TEAL)
    d.text((48 + d.textlength(big, font=F(112)) + 16, hero_h - 66), "分钟", font=F(38), fill=(255, 255, 255))
    if spec.get("score") is not None:
        score_ring(d, W - 130, hero_h - 92, spec["score"], spec.get("score_label") or "运动分", r=68, on_photo=True)
    y = hero_h + 30
    if stats:
        cw = (W - 96 - (len(stats) - 1) * 16) // len(stats)
        for i, s in enumerate(stats):
            x = 48 + i * (cw + 16)
            d.rounded_rectangle((x, y, x + cw, y + 180), R, fill=T["tile"])
            d.text((x + 26, y + 30), s["name"], font=F(24), fill=T["sub"])
            size = 40
            while size > 26 and d.textlength(str(s["value"]), font=F(size)) > cw - 48:
                size -= 2
            d.text((x + 26, y + 80), str(s["value"]), font=F(size), fill=T["ink"])
            if s.get("sub"):
                d.text((x + 26, y + 138), s["sub"], font=F(22), fill=TEAL if s["sub"].startswith("+") else T["sub"])
        y += 210
    if rows:
        h = len(rows) * 56 + (40 if more else 0) + 40
        d.rounded_rectangle((48, y, W - 48, y + h), R, fill=T["tile"])
        ry = y + 22
        for name, val in rows:
            d.text((80, ry), name, font=F(30), fill=T["ink"])
            d.text((W - 80, ry), val, font=F(30), fill=TEAL, anchor="ra")
            ry += 56
        if more:
            d.text((80, ry), "+ %d 个动作" % more, font=F(22), fill=T["sub"])
    return im


def daily_nutrition(spec):
    global T
    T = THEMES["light"]
    if not spec.get("kcal"):
        sys.exit("daily-nutrition needs kcal")
    im = Image.new("RGB", (W, H), T["bg"])
    d = ImageDraw.Draw(im)
    header(im, d, "每日总结")
    has_score = spec.get("score") is not None
    for i, ln in enumerate(summary_lines(d, spec.get("summary"), 44, W - 96 - (220 if has_score else 0))):
        d.text((48, 150 + i * 60), ln, font=F(44), fill=T["ink"])
    if spec.get("activity"):
        d.text((48, 282), lines_of(d, spec["activity"], F(24), W - 340, 1)[0], font=F(24), fill=T["sub"])
    if has_score:
        cx, cy = W - 140, 220
        score_ring(d, cx, cy, spec["score"], "薄肌分")
        if spec.get("delta"):
            d.text((cx, cy + 118), "比昨天 %s" % spec["delta"], font=F(24), fill=T["accent_text"], anchor="mm")
    items = macro_items(spec.get("macros"))
    top, bot = 370, 960 if items else 820
    d.rounded_rectangle((48, top, W - 48, bot), R, fill=T["tile"])
    d.text((84, top + 30), "热量", font=F(28), fill=T["ink"])
    d.text((W - 84, top + 34), "今天", font=F(24), fill=T["sub"], anchor="ra")
    gcx, gcy = W // 2, top + 290
    goal = spec.get("kcal_goal")
    gauge(im, gcx, gcy, 205, 48, spec["kcal"] / goal if goal else 0)
    d.text((gcx, gcy - 24), str(spec["kcal"]), font=F(92), fill=T["ink"], anchor="mm")
    d.text((gcx, gcy + 42), "目标 %s 千卡" % goal if goal else "千卡", font=F(26), fill=T["sub"], anchor="mm")
    if items:
        nutrient_tiles(d, 80, W - 80, bot - 162, items, fill=T["inset"])
    meals = spec.get("meals") or []
    if meals:
        top2, bot2 = bot + 28, bot + 336
        d.rounded_rectangle((48, top2, W - 48, bot2), R, fill=T["tile"])
        d.text((84, top2 + 28), "今日餐食", font=F(28), fill=T["ink"])
        d.text((W - 84, top2 + 32), "%d 餐" % len(meals), font=F(24), fill=T["sub"], anchor="ra")
        shown = meals[:4]
        gap = 16
        cw = (W - 168 - 3 * gap) // 4
        for i, m in enumerate(shown):
            x, y = 84 + i * (cw + gap), top2 + 84
            if m.get("photo"):
                thumb(im, open_photo(m["photo"]), (x, y, x + cw, y + 130), 20)
            else:
                d.rounded_rectangle((x, y, x + cw, y + 130), 20, fill=T["inset"])
                d.text((x + cw // 2, y + 65), m.get("name", ""), font=F(30), fill=T["sub"], anchor="mm")
            d.text((x, y + 142), " ".join(v for v in (m.get("name"), m.get("time")) if v), font=F(22), fill=T["ink"])
            if m.get("kcal"):
                d.text((x, y + 172), "约 %s 千卡" % m["kcal"], font=F(20), fill=T["sub"])
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_timeline(spec):
    global T
    T = THEMES["light"]
    im = Image.new("RGB", (W, H), T["bg"])
    d = ImageDraw.Draw(im)
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
    if spec.get("kcal"):
        facts.append("约 %s / %s 千卡" % (spec["kcal"], spec["kcal_goal"]) if spec.get("kcal_goal")
                     else "约 %s 千卡" % spec["kcal"])
    if facts:
        d.text((tx0 + 2, 314), " · ".join(facts), font=F(26), fill=T["accent_text"])
    items = macro_items(spec.get("macros"))
    events = (spec.get("events") or [])[:7]
    y0, y_end = 420, (1146 if items else H - 150) - 40
    if events:
        step = min(130, (y_end - y0) // len(events))
        x_axis = 170
        d.line((x_axis, y0 + 20, x_axis, y0 + step * (len(events) - 1) + 20), fill=T["line"], width=4)
        for i, e in enumerate(events):
            yy = y0 + i * step
            hl = bool(e.get("highlight"))
            d.text((48, yy + 4), e.get("time", ""), font=F(26), fill=T["sub"])
            d.ellipse((x_axis - 12, yy + 8, x_axis + 12, yy + 32), fill=TEAL if hl else T["ink"])
            tx = 210
            if e.get("photo"):
                thumb(im, open_photo(e["photo"]), (tx, yy - 10, tx + 88, yy + 78), 44)
                tx += 112
            d.text((tx, yy - 4), e.get("title", ""), font=F(32), fill=T["accent_text"] if hl else T["ink"])
            if e.get("sub"):
                d.text((tx, yy + 42), lines_of(d, e["sub"], F(22), W - 48 - tx, 1)[0], font=F(22), fill=T["sub"])
    if items:
        nutrient_tiles(d, 48, W - 48, 1146, items)
    tomorrow(d, spec.get("tomorrow"))
    return im


def daily_workout(spec):
    global T
    T = THEMES["dark"]
    photo = open_photo(spec["photo"]) if spec.get("photo") else placeholder(spec.get("sport"))
    stats = (spec.get("stats") or [])[:3]
    exercises = spec.get("exercises") or []
    shown = exercises[:5]
    week = spec.get("week")
    diet = spec.get("diet") or None
    diet_items = macro_items(diet.get("macros")) if diet else []
    ex_h = 92 + len(shown) * 60 + 16 if shown else 0
    body = (174 if stats else 0) + (ex_h + 24 if shown else 0) + (150 if week else 0) \
        + (196 if diet and diet_items else 0) + (150 if spec.get("tomorrow") else 40)
    hero_h = H - body
    im = Image.new("RGB", (W, H), T["bg"])
    im.paste(photo_hero(photo, hero_h, True), (0, 0))
    im.paste(Image.new("RGB", (W, 140), T["bg"]), (0, hero_h - 140), grad(W, 140, 0, 255))
    d = ImageDraw.Draw(im)
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
            d.text((x + 24, y + 22), s["name"], font=F(22), fill=T["sub"])
            value, unit = str(s["value"]), s.get("unit", "")
            size = 52
            while size > 30 and d.textlength(value, font=F(size)) + 8 + d.textlength(unit, font=F(22)) > cw - 40:
                size -= 2
            d.text((x + 24, y + 120), value, font=F(size), fill=T["ink"], anchor="ls")
            d.text((x + 32 + d.textlength(value, font=F(size)), y + 118), unit, font=F(22), fill=T["sub"], anchor="ls")
        y += 174
    if shown:
        d.rounded_rectangle((48, y, W - 48, y + ex_h), R, fill=T["tile"])
        d.text((84, y + 28), "今天练了", font=F(28), fill=T["ink"])
        d.text((W - 84, y + 32), "%d 个动作" % len(exercises), font=F(24), fill=T["sub"], anchor="ra")
        for i, e in enumerate(shown):
            ry = y + 92 + i * 60
            if i:
                d.line((84, ry - 8, W - 84, ry - 8), fill=T["line"], width=2)
            d.text((84, ry + 22), e.get("name", ""), font=F(28), fill=T["ink"], anchor="lm")
            d.text((560, ry + 22), e.get("sets", ""), font=F(26), fill=T["sub"], anchor="lm")
            d.text((W - 84, ry + 22), e.get("weight", ""), font=F(26), fill=T["ink"], anchor="rm")
            if e.get("delta"):
                pw = d.textlength(e.get("weight", ""), font=F(26))
                d.text((W - 84 - pw - 16, ry + 22), e["delta"], font=F(22), fill=TEAL, anchor="rm")
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
        if diet.get("kcal"):
            k = "约 %s / %s 千卡" % (diet["kcal"], diet["kcal_goal"]) if diet.get("kcal_goal") else "约 %s 千卡" % diet["kcal"]
            d.text((W - 48, y + 4), k, font=F(24), fill=T["sub"], anchor="ra")
        nutrient_tiles(d, 48, W - 48, y + 52, diet_items, h=124)
    tomorrow(d, spec.get("tomorrow"))
    return im


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

    F = font_loader()
    render = {"meal": meal, "workout": workout, "daily-nutrition": daily_nutrition,
              "daily-timeline": daily_timeline, "daily-workout": daily_workout}[kind]
    render(spec).save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
