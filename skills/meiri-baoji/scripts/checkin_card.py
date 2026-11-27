#!/usr/bin/env python3
"""Render a 每日薄肌 check-in card PNG (1080×1440, 3:4).

AGENT: STOP — do not read further. Everything you need (kinds, styles, fields, rules) is in SKILL.md, section
「打卡卡片」. Write the JSON from there and run the command; the script checks its own layout.

usage: python3 checkin_card.py <kind> <out.png> [spec.json | -]

kind is meal, workout, daily or weekly; "style" in the JSON is A (poster), B (magazine) or C (dashboard). After drawing,
the script checks its own layout and prints "OK <out.png>" (send it as is), "WARN: …" (fix the JSON once) or exits with
"NOT_ENOUGH_DATA: …" (reply in text).
"""
import datetime
import json
import math
import os
import re
import sys

from _common import NO_LINE_START, font_loader, require_pillow

USAGE = __doc__
KINDS = ("meal", "workout", "daily", "weekly")
# Older kind names still work, so an Agent that remembers them gets the closest new card.
KIND_ALIASES = {"meal-split": "meal", "meal-polaroid": "meal", "workout-poster": "workout", "workout-list": "workout",
                "daily-nutrition": "daily", "daily-timeline": "daily", "daily-workout": "daily",
                "daily-highlight": "daily", "weekly-bars": "weekly"}
STYLES = {"a": "A", "poster": "A", "海报": "A", "b": "B", "magazine": "B", "杂志": "B", "c": "C", "dashboard": "C",
          "面板": "C"}
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")

W, H = 1080, 1440
TEAL = (0, 211, 186)
INK = (18, 24, 26)
DEEP = (0, 92, 82)          # secondary text on the teal field
CREAM = (247, 244, 238)
RULE = (214, 207, 196)
WHITE = (255, 255, 255)
GREY = (170, 170, 170)
DARK = (10, 10, 10)
TILE = (30, 32, 34)
TRACK = (60, 62, 64)
AMBER = (255, 176, 32)
CORAL = (255, 102, 92)
BAR_COLORS = (TEAL, AMBER, CORAL)
MIN_PX = 38                 # nothing on a card is smaller than this (about 14 pt on a phone)

Image = ImageDraw = ImageFont = ImageFilter = F = None
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


def phone_fonts(load):
    def font(size):
        return load(max(int(size), MIN_PX))

    return font


def tw(d, text, size):
    return d.textlength(text, font=F(size))


def txt(d, xy, text, size, fill, anchor="la", bold=False):
    """Text; bold thickens it with a same-colour stroke (no bold CJK font ships on every machine)."""
    kw = {"stroke_width": max(1, size // 36), "stroke_fill": fill} if bold else {}
    d.text(xy, text, font=F(size), fill=fill, anchor=anchor, **kw)
    return tw(d, text, size)


def fit(d, text, size, width, min_size=None):
    """Shrink to min_size (default: no shrinking), then cut with "…"."""
    text = str(text)
    min_size = min_size or size
    while size > min_size and tw(d, text, size) > width:
        size -= 2
    if tw(d, text, size) > width:
        while text and tw(d, text + "…", size) > width:
            text = text[:-1]
        text += "…"
    return text, size


def wrap(d, text, font, width):
    """Wrap CJK text; numbers and Latin words (70kg, 4×8) never break across lines."""
    lines, cur = [], ""
    for tok in re.findall(r"[0-9A-Za-z.,%+×/:~–-]+|\n|.", str(text)):
        if tok == "\n":
            lines.append(cur)
            cur = ""
        elif cur and tok[0] not in NO_LINE_START and d.textlength(cur + tok, font=font) > width:
            lines.append(cur)
            cur = tok
        else:
            cur += tok
    if cur:
        lines.append(cur)
    return lines


def lines_of(d, text, size, width, limit):
    """At most limit lines; a cut-off text ends in "…" instead of stopping mid-sentence."""
    font = F(size)
    lines = wrap(d, text, font, width - size)  # room for a comma hanging at the line end
    # No one- or two-character widow on the last line: carry two characters down with it.
    if (len(lines) >= 2 and len(lines[-1]) <= 2 and len(lines[-2]) > 4 and "\n" not in str(text)[-4:]
            and not re.search(r"[0-9A-Za-z]", lines[-2][-3:])):
        lines[-2], lines[-1] = lines[-2][:-2], lines[-2][-2:] + lines[-1]
    if len(lines) <= limit:
        return lines
    last = lines[limit - 1]
    while last and d.textlength(last + "…", font=font) > width:
        last = last[:-1]
    return lines[:limit - 1] + [last.rstrip("，、,;；") + "…"]


def brand_chip(im, x_right, y):
    """Solid white capsule: @ mark on white, 小塔 in the teal wordmark, 薄肌搭子 in dark grey."""
    wordmark = ImageFont.truetype(os.path.join(ASSETS, "xiaota-wordmark.ttf"), 34)
    d = draw(im)
    h = 60
    w = int(16 + 40 + 10 + d.textlength("小塔", font=wordmark) + 12 + tw(d, "薄肌搭子", MIN_PX) + 24)
    x = x_right - w
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=WHITE)
    logo = Image.open(os.path.join(ASSETS, "xiaota-mark.png")).convert("RGBA").resize((40, 40), Image.LANCZOS)
    im.paste(logo, (x + 16, y + 10), logo)
    tx = x + 66
    d.text((tx, y + h // 2), "小塔", font=wordmark, fill=TEAL, anchor="lm")
    d.text((tx + d.textlength("小塔", font=wordmark) + 12, y + h // 2), "薄肌搭子", font=F(MIN_PX), fill=(70, 70, 75),
           anchor="lm")
    return x


def ring(d, cx, cy, r, w, frac, color, track):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=track, width=w)
    if frac > 0:
        d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * min(frac, 1), fill=color, width=w)


def bar(d, x0, x1, y, frac, color, h=24, track=TRACK):
    d.rounded_rectangle((x0, y, x1, y + h), h // 2, fill=track)
    if frac and frac > 0:
        d.rounded_rectangle((x0, y, x0 + max(h, (x1 - x0) * min(frac, 1)), y + h), h // 2, fill=color)
    mark("bar", (x0, y, x1, y + h))


# ---------- photos: smart crop and collage ----------

def open_photo(path):
    try:
        img = Image.open(path)
        img.load()
        from PIL import ImageOps

        return ImageOps.exif_transpose(img).convert("RGB")
    except (OSError, ValueError, TypeError):
        return None


def look(img):
    """Where the subject is (food, faces) and how sharp the photo is, from a 48×48 thumbnail: colourful, detailed
    and skin-toned pixels weigh more, with a pull towards the centre."""
    s = img.resize((48, 48))
    sat = s.convert("HSV").getchannel(1).load()
    edge = s.convert("L").filter(ImageFilter.FIND_EDGES).load()
    rgb = s.load()
    tot = sx = sy = sharp = 0.0
    for y in range(1, 47):
        for x in range(1, 47):
            r, g, b = rgb[x, y]
            skin = 0.8 if r > 95 and g > 40 and b > 20 and r > g and r > b and r - g > 15 else 0.0
            wgt = (sat[x, y] / 255 * 0.6 + edge[x, y] / 255 + skin) * math.exp(
                -((x / 47 - .5) ** 2 + (y / 47 - .5) ** 2) / 0.12) + 1e-3
            tot += wgt
            sx += wgt * x / 47
            sy += wgt * y / 47
            sharp += edge[x, y]
    clamp = lambda v: min(max(v, 0.3), 0.7)  # noqa: E731
    return (clamp(sx / tot), clamp(sy / tot)), sharp


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


def load_photos(spec):
    paths = spec.get("photos") or []
    if isinstance(paths, str):
        paths = [paths]
    if spec.get("photo"):
        paths = [spec["photo"]] + [p for p in paths if p != spec["photo"]]
    out = []
    for p in paths:
        p = p.get("path") if isinstance(p, dict) else p
        img = open_photo(p) if p else None
        if img is not None:
            focus, sharp = look(img)
            out.append((img, focus, sharp))
    return out


# Default images (assets/placeholders/<group>-<n>.jpg) when the user sent no photo: by sport or meal, else a
# neutral background. Which one rotates by date, so the same card type looks different from day to day.
SPORT_GROUPS = {"strength": "strength", "力量": "strength", "攀岩": "strength", "climb": "strength", "run": "run",
                "跑步": "run", "飞盘": "run", "frisbee": "run", "ball": "run", "篮球": "run", "足球": "run",
                "羽毛球": "run", "网球": "run", "cycle": "cycle", "骑行": "cycle", "单车": "cycle", "row": "cycle",
                "划船": "cycle", "swim": "swim", "游泳": "swim", "yoga": "yoga", "瑜伽": "yoga", "pilates": "yoga",
                "普拉提": "yoga", "stretch": "yoga", "拉伸": "yoga", "hiit": "hiit", "跳绳": "hiit", "jump rope": "hiit",
                "crossfit": "hiit", "walk": "walk", "步行": "walk", "散步": "walk", "hike": "walk", "徒步": "walk",
                "爬山": "walk"}
MEAL_GROUPS = (("breakfast", ("早",)), ("lunch", ("午",)), ("dinner", ("晚", "夜宵")),
               ("snack", ("加餐", "零食", "水果", "下午茶", "奶茶", "饮")))


def default_photos(kind, spec):
    folder = os.path.join(ASSETS, "placeholders")
    if not os.path.isdir(folder):
        return []
    if kind == "workout":
        sport = str(spec.get("sport") or spec.get("label") or "").strip().lower()
        group = SPORT_GROUPS.get(sport) or next((g for k, g in SPORT_GROUPS.items() if k in sport), "strength")
        groups = [group]
    elif kind == "meal":
        text = "%s %s" % (spec.get("label") or "", spec.get("dishes") or "")
        groups = [g for g, words in MEAL_GROUPS if any(w in text for w in words)][:1] or [g for g, _ in MEAL_GROUPS]
    else:
        groups = ["bg"]
    names = sorted(n for n in os.listdir(folder) for g in groups if n.startswith(g + "-") and n.endswith(".jpg"))
    if not names:
        return []
    day = datetime.date.today().toordinal() + KINDS.index(kind) * 3
    img = open_photo(os.path.join(folder, names[day % len(names)]))
    return [(img,) + look(img)] if img is not None else []


def tile_boxes(box, n, gap):
    """1 fills the box; 2 side by side (or stacked in a wide-short… tall box); 3 = one big + two; 4 = 2×2."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if n == 1:
        return [box]
    if n == 2:
        if w >= h * 0.9:
            m = x0 + (w - gap) // 2
            return [(x0, y0, m, y1), (m + gap, y0, x1, y1)]
        m = y0 + (h - gap) // 2
        return [(x0, y0, x1, m), (x0, m + gap, x1, y1)]
    if n == 3:
        if w >= h:
            m = x0 + int((w - gap) * 0.58)
            c = y0 + (h - gap) // 2
            return [(x0, y0, m, y1), (m + gap, y0, x1, c), (m + gap, c + gap, x1, y1)]
        m = y0 + int((h - gap) * 0.58)
        c = x0 + (w - gap) // 2
        return [(x0, y0, x1, m), (x0, m + gap, c, y1), (c + gap, m + gap, x1, y1)]
    mx, my = x0 + (w - gap) // 2, y0 + (h - gap) // 2
    return [(x0, y0, mx, my), (mx + gap, y0, x1, my), (x0, my + gap, mx, y1), (mx + gap, my + gap, x1, y1)]


def collage(im, box, photos, r=0, gap=10):
    """Lay out 1–4 photos in the box; 5+ keeps the first and the three sharpest others, the last tile says +N."""
    extra = 0
    if len(photos) > 4:
        rest = sorted(range(1, len(photos)), key=lambda i: -photos[i][2])[:3]
        keep = [0] + sorted(rest)
        extra = len(photos) - 4
        photos = [photos[i] for i in keep]
    boxes = tile_boxes(tuple(int(v) for v in box), len(photos), gap)
    for (img, focus, _), (a, b, c, e) in zip(photos, boxes):
        w, h = c - a, e - b
        piece = cover(img, w, h, focus)
        im.paste(piece, (a, b), round_mask(w, h, r) if r else None)
    if extra:
        a, b, c, e = boxes[-1]
        shade = (round_mask(c - a, e - b, r) if r else Image.new("L", (c - a, e - b), 255)).point(lambda v: v * 150 // 255)
        im.paste(Image.new("RGB", (c - a, e - b), (0, 0, 0)), (a, b), shade)
        txt(draw(im), ((a + c) / 2, (b + e) / 2), "+%d" % extra, 96, WHITE, "mm", bold=True)


def shade_top(im, h=230, alpha=170):
    g = Image.new("L", (1, h))
    for y in range(h):
        g.putpixel((0, y), int(alpha * (1 - y / h)))
    im.paste(Image.new("RGB", (W, h), (0, 0, 0)), (0, 0), g.resize((W, h)))


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
    if isinstance(value, str) and key not in ("photo", "photos", "path", "style"):
        return unitize(value)
    return value


def number(value):
    """A number from 1650, "1650", "约 1650 千卡" or "650-850" (the middle of a range)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    found = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))[:2]]
    return sum(found) / len(found) if found else None


def shown(value, unit=""):
    """How a value reads on the card: 1650 → "1,650", "约 650-850 千卡" → "650–850" (unit shown separately)."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "{:,}".format(int(value)) if value >= 1000 and value == int(value) else "%g" % value
    s = str(value).strip()
    for u in filter(None, (unit, "千卡", "kcal")):
        if s.endswith(u):
            s = s[: -len(u)].rstrip()
    s = re.sub(r"^约\s*", "", s)
    s = re.sub(r"(\d)\s*[-~～]\s*(\d)", r"\1–\2", s)
    return s


def g_text(value):
    s = shown(value, "g")
    return s + "g" if s and s[-1].isdigit() else s


# ---------- what goes on the card (one "story" per kind, drawn by any style) ----------
#
# kicker  top-left line            mast   (big word, small line, bold line) for the magazine masthead
# hero    (label, value, unit, pill) the main number     ring   score 0–100 (dashboard)
# head    the one sentence          sub    second line under it (poster)
# facts   [(value, label, unit)] ≤3        bars   [(name, value, frac)] macros with a goal (dashboard)
# rows    [(key, text)] list         more   hidden rows count          foot   ("明天", text)
# week    {"done": [7], "values": [7], "plan"}                         photos [(img, focus, sharpness)]

MACROS = (("protein", "蛋白质"), ("carb", "碳水"), ("fat", "脂肪"))
SPORT_NAMES = {"strength": "力量", "run": "跑步", "cycle": "骑行", "swim": "游泳", "yoga": "瑜伽", "hiit": "HIIT"}
WEEKDAYS = "一二三四五六日"


def need(cond, msg):
    if not cond:
        sys.exit("NOT_ENOUGH_DATA: " + msg + "; reply in text instead")


def story_meal(spec):
    photos = load_photos(spec)
    need(photos or spec.get("kcal") or spec.get("dishes"), "meal needs a photo, kcal or dishes")
    kcal = shown(spec.get("kcal"), "千卡")
    m, tg = spec.get("macros") or {}, spec.get("targets") or {}
    if isinstance(m, list):  # [{"name","value","target"}] also works
        m = {k: x.get("value") for x in m for k, n in MACROS if x.get("name") in (n, k, n[:2])}
    facts, bars = [], []
    for key, name in MACROS:
        if m.get(key) not in (None, ""):
            facts.append((g_text(m[key]), name, ""))
            goal = number(tg.get(key))
            bars.append((name, g_text(m[key]), number(m[key]) / goal if goal and number(m[key]) else None))
    label = (spec.get("label") or "").strip()
    word = label.split("·")[0].strip() if label else ""
    dishes = [x.strip() for x in re.split(r"[·、，,+＋/]", spec.get("dishes") or "") if x.strip()]
    head = spec.get("line") or ""
    return dict(kicker=label or "这一餐", mast=(word if 0 < len(word) <= 3 else "这一餐",
                                               label[len(word):].strip(" ·") if word else "", "饮食打卡"),
                hero=("这一餐约", kcal, "千卡", None) if kcal else None, head=head,
                sub=" · ".join(dishes) if dishes and head else "", facts=facts, bars=bars,
                rows=[(x, "") for x in dishes] if dishes else [], photos=photos,
                head_b=head or " · ".join(dishes))


def story_workout(spec):
    minutes = number(spec.get("minutes"))
    need(minutes, "workout needs minutes")
    sport = str(spec.get("sport") or "").strip()
    name = spec.get("label") or SPORT_NAMES.get(sport.lower(), sport) or "训练"
    stats = [x for x in spec.get("stats") or [] if isinstance(x, dict)
             and x.get("name") not in ("时长", "用时", "训练时长")]
    facts = []
    for x in stats[:3]:
        unit = x.get("unit") or x.get("sub") or ""
        unit = "" if str(unit).startswith("+") else unit
        facts.append((shown(x.get("value"), unit), x.get("name", ""), unit))
    rows = []
    for row in spec.get("exercises") or []:
        if isinstance(row, (list, tuple)):
            key, val = (list(row) + ["", ""])[:2]
        elif isinstance(row, dict):
            key = row.get("name", "")
            val = " · ".join(str(row[k]) for k in ("sets", "weight") if row.get(k))
        else:
            key, val = str(row), ""
        rows.append((str(key), str(val)))
    score = number(spec.get("score"))
    return dict(kicker=name, mast=(shown(minutes), "分钟", name), hero=("今天练了", shown(minutes), "分钟", None),
                ring=(score, spec.get("score_label") or "运动分") if score is not None else None,
                head=spec.get("line") or "", facts=facts,
                facts_ab=facts[:2] + ([(shown(score), "运动分", "")] if score is not None else facts[2:3]),
                rows=rows, more=int(number(spec.get("more")) or 0), photos=load_photos(spec),
                list=[(k, v) for k, v in rows])


def date_parts(spec):
    raw = str(spec.get("date") or "")
    m = re.search(r"(?:\d{4}\s*[年./-]\s*)?(\d{1,2})\s*[月./-]\s*(\d{1,2})", raw)
    today = datetime.date.today()
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        try:
            wd = WEEKDAYS[datetime.date(today.year, mon, day).weekday()]
        except ValueError:
            wd = ""
    else:
        mon, day, wd = today.month, today.day, WEEKDAYS[today.weekday()]
    return mon, day, wd


def story_daily(spec):
    mon, day, wd = date_parts(spec)
    kcal, goal = number(spec.get("kcal")), number(spec.get("kcal_goal"))
    macros = []
    raw = spec.get("macros") or []
    if isinstance(raw, dict):
        raw = [{"name": n, "value": raw.get(k)} for k, n in MACROS if raw.get(k) is not None]
    for x in raw:
        v = number(x.get("value")) if isinstance(x, dict) else None
        if v is not None and x.get("name"):
            t = number(x.get("target"))
            macros.append((x["name"], g_text(x["value"]), v / t if t else None))
    works = spec.get("workouts") or ([spec["workout"]] if isinstance(spec.get("workout"), dict) else [])
    works = [(w.get("name") or SPORT_NAMES.get(str(w.get("sport")), w.get("sport")) or "训练", number(w.get("minutes")))
             for w in works if isinstance(w, dict)]
    if not works and spec.get("activity"):
        works = [(str(spec["activity"]), None)]
    score = number(spec.get("score"))
    need(kcal or works or macros, "daily needs kcal, macros or workouts")
    protein = next((v for n, v, _ in macros if "蛋白" in n), None)
    work_txt = "、".join("%s %s 分钟" % (n, shown(mi)) if mi else n for n, mi in works)
    total_min = sum(mi or 0 for _, mi in works)
    if score is not None:
        hero = ("今日薄肌分", shown(score), "", spec.get("delta"))
    elif kcal:
        hero = ("今天吃了", shown(kcal), "千卡", None)
    else:
        hero = ("今天练了", shown(total_min), "分钟", None) if total_min else None
    facts = []
    if kcal and hero and hero[2] != "千卡":
        facts.append((shown(kcal), "热量", "千卡"))
    if protein:
        facts.append((protein, "蛋白质", ""))
    if total_min and not (hero and hero[2] == "分钟"):
        facts.append((shown(total_min), works[0][0] if len(works) == 1 else "运动", "分钟"))
    elif works and not total_min:
        facts.append((works[0][0], "运动", ""))
    rows = []
    if kcal or protein:
        rows.append(("吃", " · ".join(filter(None, ["%s 千卡" % shown(kcal) if kcal else "",
                                                    "蛋白 %s" % protein if protein else ""]))))
    if works:
        rows.append(("练", work_txt))
    if score is not None:
        rows.append(("分", "薄肌分 %s" % shown(score) + ("（比昨天 %s）" % spec["delta"] if spec.get("delta") else "")))
    wk = spec.get("week") if isinstance(spec.get("week"), dict) else None
    return dict(kicker="%d月%d日 周%s" % (mon, day, wd), mast=("%d" % day, "%d月 · 周%s" % (mon, wd), "今日复盘"),
                hero=hero, ring=(score, "薄肌分" + (" " + spec["delta"] if spec.get("delta") else ""))
                if score is not None else None,
                kcal=(shown(kcal), goal and kcal / goal, "目标 " + shown(goal) if goal else "") if kcal else None,
                head=spec.get("summary") or "", facts=facts[:3], bars=macros[:3], rows=rows,
                list=[(n, "%s 分钟" % shown(mi) if mi else "") for n, mi in works],
                foot=("明天", re.sub(r"^明天[：:\s]*", "", spec["tomorrow"])) if spec.get("tomorrow") else None,
                week=dict(done=wk.get("done"), plan=wk.get("plan")) if wk else None, photos=load_photos(spec),
                tag="今日复盘")


def story_weekly(spec):
    days = list(spec.get("days") or [])[:7]
    days += [None] * (7 - len(days))
    recorded = [x for x in days if isinstance(x, dict)]
    need(len(recorded) >= 2 or spec.get("stats"), "weekly needs at least 2 recorded days")
    trained = sum(1 for x in recorded if x.get("trained"))
    plan = number(spec.get("plan"))
    vals = [number(x.get("score")) if isinstance(x, dict) else None for x in days]
    unit = "分"
    if sum(v is not None for v in vals) < 2:
        vals = [number(x.get("kcal")) if isinstance(x, dict) else None for x in days]
        unit = "千卡"
    facts = []
    for x in (spec.get("stats") or [])[:3]:
        if isinstance(x, dict):
            facts.append((shown(x.get("value"), x.get("unit") or ""), x.get("name", ""), x.get("unit") or ""))
    rng = str(spec.get("range") or "").strip()
    rows = [("练", "%d 天" % trained + (" / 计划 %d 天" % plan if plan else ""))]
    rows += [(lab, ("%s %s" % (v, u)).strip()) for v, lab, u in facts]
    return dict(kicker=("%s · " % rng if rng else "") + "本周复盘", mast=("%d" % trained, "天在练",
                                                                         rng or "本周复盘"),
                hero=("这周练了", "%d" % trained, "天", "计划 %d" % plan if plan else None), head=spec.get("best") or "",
                facts=facts, rows=rows, foot=("下周", re.sub(r"^下周[：:\s]*", "", spec["next"])) if spec.get("next") else None,
                week=dict(done=[bool(x.get("trained")) if isinstance(x, dict) else None for x in days], plan=plan,
                          values=vals if sum(v is not None for v in vals) >= 2 else None, unit=unit),
                photos=load_photos(spec), tag="本周复盘")


STORIES = {"meal": story_meal, "workout": story_workout, "daily": story_daily, "weekly": story_weekly}


# ---------- shared pieces ----------

def week_dots(d, x0, x1, cy, done, on, off, ink_on, ink_off, r=40):
    done = list(done or [])[:7] + [None] * 7
    step = (x1 - x0) / 7
    for i, ch in enumerate(WEEKDAYS):
        cx = x0 + (i + 0.5) * step
        if done[i]:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=on)
            txt(d, (cx, cy), ch, MIN_PX, ink_on, "mm")
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=off, width=4)
            txt(d, (cx, cy), ch, MIN_PX, ink_off, "mm")


def week_bars(d, box, values, done, fill, rest, label_ink):
    """Seven columns, height by the day's score (or kcal); trained days in the accent colour."""
    x0, y0, x1, y1 = box
    top = max([v for v in values if v] or [1])
    step = (x1 - x0) / 7
    base = y1 - 64
    for i, ch in enumerate(WEEKDAYS):
        cx = x0 + (i + 0.5) * step
        v = values[i]
        if v:
            h = max(24, (base - y0) * v / top)
            d.rounded_rectangle((cx - step * 0.3, base - h, cx + step * 0.3, base), 14,
                                fill=fill if (done or [None] * 7)[i] else rest)
        else:
            d.rounded_rectangle((cx - step * 0.3, base - 14, cx + step * 0.3, base), 7, fill=rest)
        txt(d, (cx, y1 - 22), ch, MIN_PX, label_ink, "mm")


def value_unit(d, x, base, v, unit, size, width, ink, unit_ink, min_size=46):
    """A big value with its unit in small type after it; the value shrinks first, then the unit goes."""
    uw = tw(d, unit, 40) + 10 if unit else 0
    v, vs = fit(d, v, size, width - uw, min_size)
    if unit and (tw(d, v, vs) + uw > width or v.endswith("…")):
        unit, uw = "", 0
        v, vs = fit(d, v, size, width, min_size)
    w = txt(d, (x, base), v, vs, ink, "ls", bold=True)
    if unit:
        txt(d, (x + w + 10, base), unit, 40, unit_ink, "ls")


def pill(d, x, base, text, size, fill, ink):
    w = tw(d, text, size) + size
    d.rounded_rectangle((x, base - size * 1.55, x + w, base - size * 0.1), size, fill=fill)
    txt(d, (x + w / 2, base - size * 0.82), text, size, ink, "mm", bold=True)
    return w


# ---------- style A: poster on a solid teal field ----------

A_BG = (22, 24, 26)
A_PANEL = (40, 43, 46)


def fade(im, y0, y1, alpha):
    """Darken the photo from y0 (clear) to y1 (alpha), solid below, so white type stays readable."""
    g = Image.new("L", (1, H), 0)
    for y in range(H):
        g.putpixel((0, y), 0 if y < y0 else int(alpha * min(1, (y - y0) / max(1, y1 - y0))))
    im.paste(Image.new("RGB", (W, H), A_BG), (0, 0), g.resize((W, H)))


def style_a(st):
    """Big-type poster: the photo fills the card (darkened at the bottom) or a near-black page; teal only for accents."""
    im = Image.new("RGB", (W, H), A_BG)
    if st.get("backdrop"):
        img, focus, _ = st["backdrop"][0]
        im.paste(cover(img, W, H, focus), (0, 0))
        im.paste(Image.new("RGB", (W, H), A_BG), (0, 0), Image.new("L", (W, H), 175))
    d = draw(im)
    photos = st.get("photos")
    facts = st.get("facts_ab") or st.get("facts") or []
    facts = [f for f in facts if f[0]][:3]
    foot = st.get("foot")
    if not facts and not foot and not st.get("photos") and st.get("kicker"):
        facts = [(st["kicker"], "", "")]
    # dark panel at the bottom: facts, then the foot line
    panel_h = (190 if len(facts) > 1 else 170 if facts else 0) + (110 if foot else 0)
    panel_h = panel_h + 60 if panel_h else 0
    panel_top = H - 32 - panel_h if panel_h else H - 40
    hero = st.get("hero")
    big = hero[1] if hero else ""
    label = hero[0] if hero else ""
    unit, pill_text = (hero[2], hero[3]) if hero else ("", None)
    head = st.get("head") or ""
    sub = st.get("sub") or ""
    week = st.get("week")

    def mid_height(bs, hs, nlines):
        return ((60 if label else 0) + (bs * 0.75 if big else 0) + (60 if big else 0) + nlines * (hs + 22)
                + (64 if sub else 0) + (130 if week else 0))

    hs = 76
    hl = lines_of(d, head, hs, W - 128, 3) if head else []
    top = 150
    if photos:
        bs = 300 if len(big) <= 3 else 220
        need_h = mid_height(bs, hs, len(hl))
        top = max(int(H * 0.4), panel_top - 40 - need_h)
        # one photo fills the card; several photos stop where the text starts, so no tile (or "+N") sits under it
        collage(im, (0, 0, W, H if len(photos) == 1 else top + 20), photos, gap=8)
        shade_top(im)
        if hero or head or sub or week or panel_h:
            fade(im, top - 260, top + 60, 236)
    else:
        bs = 460 if len(big) <= 2 else 380 if len(big) <= 3 else 300
    kick_ink = WHITE
    # the hero shrinks to fit the width; spare height goes to a bigger headline
    room = W - 120 - (tw(d, unit, 64) + 30 if unit else 0) - (tw(d, pill_text, 64) + 100 if pill_text else 0)
    while big and bs > 120 and tw(d, big, bs) + bs // 18 > room:
        bs -= 10
    avail = panel_top - 40 - top
    while hl and hs < 100 and mid_height(bs, hs + 8, len(lines_of(d, head, hs + 8, W - 128, 3))) < avail * 0.8:
        hs += 8
        hl = lines_of(d, head, hs, W - 128, 3)
    while mid_height(bs, hs, len(hl)) > avail and (bs > 140 or hs > 56):
        if bs > 140:
            bs -= 20
        else:
            hs -= 4
            hl = lines_of(d, head, hs, W - 128, 3)
    if mid_height(bs, hs, len(hl)) > avail:
        week = None
    if mid_height(bs, hs, len(hl)) > avail:
        sub = ""
    txt(d, (64, 86), fit(d, st.get("kicker", ""), 40, W - 520)[0], 40, kick_ink, "lm", bold=bool(photos))
    brand_chip(im, W - 56, 56)
    spare = max(0, avail - mid_height(bs, hs, len(hl)))
    y = top + (spare if photos else spare / 2)  # on a photo the text sits low, over the darkened part
    if label:
        txt(d, (64, y + 24), label, 48, TEAL, "lm")
        y += 60
    if big:
        base = y + 20 - d.textbbox((0, 0), big, font=F(bs), anchor="ls")[1]  # digit tops differ per font
        w = txt(d, (52, base), big, bs, WHITE, "ls", bold=True)
        x = 52 + w + 28
        if unit:
            x += txt(d, (x, base - 8), unit, 64, WHITE, "ls", bold=True) + 24
        if pill_text:
            pill(d, x, base - 8, pill_text, 64 if not photos else 52, TEAL, INK)
        y = base + 60
    for line in hl:
        txt(d, (64, y + hs * 0.5), line, hs, WHITE, "lm", bold=True)
        y += hs + 22
    if sub:
        txt(d, (64, y + 30), fit(d, sub, 44, W - 128)[0], 44, GREY, "lm")
        y += 64
    if week:
        week_dots(d, 40, W - 40, y + 70, week.get("done"), TEAL, (110, 112, 114), INK, GREY, r=42)
    if not panel_h:
        return im
    d.rounded_rectangle((32, panel_top, W - 32, H - 32), 44, fill=A_PANEL)
    mark("box", (32, panel_top, W - 32, H - 32))
    ty = panel_top + 40
    if len(facts) == 1:
        v, lab, u = facts[0]
        lab = (u + lab) if u and lab else (u or lab)
        v, vs = fit(d, v, 140, W - 220 - tw(d, lab, 56), 60)
        w = txt(d, (88, ty + 116), v, vs, WHITE, "ls", bold=True)
        if lab:
            txt(d, (88 + w + 24, ty + 116), fit(d, lab, 56, W - 200 - w)[0], 56, TEAL, "ls")
        ty += 170
    elif facts:
        cw = (W - 64 - 48) / len(facts)
        for i, (v, lab, u) in enumerate(facts):
            x = 56 + 24 + i * cw
            if i:
                d.line((x - 12, ty + 10, x - 12, ty + 170), fill=(60, 66, 68), width=3)
            value_unit(d, x + 16, ty + 96, v, u, 96, cw - 40, WHITE, GREY)
            txt(d, (x + 16, ty + 160), fit(d, lab, 44, cw - 40)[0], 44, TEAL, "ls")
        ty += 190
    if foot:
        if facts:
            d.line((80, ty, W - 80, ty), fill=(60, 66, 68), width=3)
        t = "%s · %s" % foot
        txt(d, (88, ty + 56), fit(d, t, 46, W - 176)[0], 46, (232, 232, 232), "lm")
    return im


# ---------- style B: magazine page on cream ----------

def style_b(st):
    im = Image.new("RGB", (W, H), CREAM)
    d = draw(im)
    big, s1, s2 = st["mast"]
    brand_chip(im, W - 56, 56)
    photos = st.get("photos")
    head = st.get("head_b", st.get("head")) or ""
    rows = st.get("rows") or []
    facts = [] if st.get("kind") in ("daily", "weekly") else [f for f in st.get("facts_ab") or st.get("facts") or []
                                                            if f[0]][:3]
    if st.get("kind") == "meal" and st.get("hero"):
        facts = [(st["hero"][1], "热量", "千卡")] + facts[:2]
    foot = st.get("foot")
    week = st.get("week")
    more = st.get("more", 0)
    bottom = H - 150 if foot else H - 56
    y0 = 380
    # fixed parts first, then hand the spare height to the photos, the rows, the quote, in that order
    qs = 72

    def quote_h(size):
        return len(lines_of(d, head, size, W - 230, 3)) * int(size * 1.32) + 24 if head else 0

    max_rows = 6
    rows_shown = rows[:max_rows]
    hidden = len(rows) - len(rows_shown) + more
    rh = 92
    fh = 190 if facts else 0
    wh = 150 if week else 0
    ph = 260 if photos else 0

    def total():
        return (quote_h(qs) + (ph + 40 if ph else 0) + (fh + 20 if fh else 0) + (wh if wh else 0)
                + len(rows_shown) * rh + (rh if hidden else 0) + (8 if rows_shown else 0))

    if total() > bottom - y0 and photos:
        wh = 0  # with photos, the rows matter more than the week strip
    while total() > bottom - y0 and len(rows_shown) > 1:
        rows_shown = rows_shown[:-1]
        hidden += 1
    spare = bottom - y0 - total()
    if photos:
        add = min(spare, 760 - ph)
        ph += add
        spare -= add
    while spare > 0 and head and qs < 96:
        before = quote_h(qs)
        qs += 8
        spare -= quote_h(qs) - before
    if spare < 0 and qs > 72:
        qs -= 8
        spare = bottom - y0 - total()
    # little data and no photo: the masthead becomes a cover (huge number, title under it)
    bs, cover = 260, False
    while bs > 120 and tw(d, big, bs) > 560:
        bs -= 10
    if not photos and spare > 300:
        cover = True
        lines = len(rows_shown) + (1 if hidden else 0) + (2 if head else 0)
        grow = min(int(spare * (0.85 if not lines else 0.6 if lines <= 2 else 0.4)), 480 if lines <= 2 else 160)
        bs = 260 + grow
        while bs > 200 and tw(d, big, bs) > W - 112:
            bs -= 10
        mast_h = int(bs * 0.75) + 70 + (70 if s1 else 0) + 90
        spare -= max(0, mast_h - 230)
        y0 += max(0, mast_h - 230)
    alone = cover and not (head or fh or wh or rows_shown or hidden)
    if alone:  # nothing under the cover: centre it
        y0 += max(0, spare) // 2
        spare = 0
    if cover:
        top = 150 - d.textbbox((0, 0), big, font=F(bs), anchor="ls")[1] + (y0 - 380 - max(0, int(bs * 0.75) + 70 + (70 if s1 else 0) + 90 - 230) if alone else 0)
        txt(d, (48, top), big, bs, TEAL, "ls", bold=True)
        ty = top + 70
        if s1:
            txt(d, (56, ty), fit(d, s1, 52, W - 112)[0], 52, INK, "ls")
            ty += 70
        txt(d, (56, ty), fit(d, s2, 64, W - 112)[0], 64, INK, "ls", bold=True)
        d.rectangle((56, ty + 40, W - 56, ty + 46), fill=INK)
    else:
        txt(d, (56, 300), big, bs, TEAL, "ls", bold=True)
        x = 56 + tw(d, big, bs) + 34
        if s1:
            txt(d, (x, 206), fit(d, s1, 48, W - 60 - x)[0], 48, INK, "ls")
        txt(d, (x, 278), fit(d, s2, 60, W - 60 - x)[0], 60, INK, "ls", bold=True)
        d.rectangle((56, 334, W - 56, 340), fill=INK)
    n_rows = len(rows_shown) + (1 if hidden else 0)
    if spare > 0 and n_rows:
        add = min(spare // n_rows, 110)
        rh += add
        spare -= add * n_rows
    gaps = sum(1 for p in (head, ph, fh, wh, n_rows) if p)
    pad = max(0, spare) / max(1, gaps + 1)
    y = y0 + pad
    if head:
        ImageDraw.Draw(im).text((156, y + qs * 1.9), "“", font=F(200), fill=TEAL, anchor="rs",
                                stroke_width=5, stroke_fill=TEAL)
        for line in lines_of(d, head, qs, W - 230, 3):
            txt(d, (170, y + qs * 0.95), line, qs, INK, "ls", bold=True)
            y += int(qs * 1.32)
        y += 24 + pad
    if ph:
        collage(im, (56, y, W - 56, y + ph), photos, r=10, gap=12)
        y += ph + 40 + pad
    if fh:
        d.line((56, y, W - 56, y), fill=RULE, width=3)
        cw = (W - 112) / len(facts)
        for i, (v, lab, u) in enumerate(facts):
            x = 56 + i * cw
            if i:
                d.line((x, y + 30, x, y + fh - 30), fill=RULE, width=3)
            value_unit(d, x + (24 if i else 0), y + 104, v, u, 76, cw - 48, TEAL, INK)
            txt(d, (x + (24 if i else 0), y + 160), fit(d, lab, 40, cw - 48)[0], 40, INK, "ls")
        y += fh
        d.line((56, y, W - 56, y), fill=RULE, width=3)
        y += 20 + pad
    if wh:
        week_dots(d, 56, W - 56, y + wh / 2, week.get("done"), TEAL, RULE, INK, (120, 116, 110), r=44)
        y += wh + pad
    big_rows = rh >= 150
    for i, (k, v) in enumerate(rows_shown):
        d.line((56, y, W - 56, y), fill=RULE, width=3)
        cy = y + rh / 2
        txt(d, (56, cy), "%02d" % (i + 1), 44, TEAL, "lm", bold=True)
        size = 60 if big_rows else 48
        if v:
            kw = txt(d, (150, cy), fit(d, k, size, 300)[0], size, INK, "lm", bold=True)
            vt, vs = fit(d, v, 60 if big_rows else 44, W - 56 - (150 + kw + 32), MIN_PX)
            txt(d, (150 + kw + 32, cy), vt, vs, TEAL if big_rows else INK, "lm", bold=big_rows)
        else:
            txt(d, (150, cy), fit(d, k, size, W - 220)[0], size, INK, "lm", bold=True)
        y += rh
    if hidden:
        d.line((56, y, W - 56, y), fill=RULE, width=3)
        txt(d, (150, y + rh / 2), "还有 %d 项" % hidden, 44, (120, 116, 110), "lm")
        y += rh
    if rows_shown:
        d.line((56, y, W - 56, y), fill=RULE, width=3)
    if foot:
        d.rectangle((0, H - 150, W, H), fill=INK)
        t = "%s → %s" % foot
        txt(d, (56, H - 75), fit(d, t, 48, W - 112)[0], 48, WHITE, "lm")
    return im


# ---------- style C: dashboard of dark tiles ----------

def tile(d, box, fill=TILE):
    d.rounded_rectangle(box, 36, fill=fill)
    mark("box", box)


def style_c(st):
    im = Image.new("RGB", (W, H), DARK)
    d = draw(im)
    txt(d, (44, 86), fit(d, st.get("kicker", ""), 48, W - 520)[0], 48, WHITE, "lm", bold=True)
    brand_chip(im, W - 44, 56)
    G, x0, x1, top, bottom = 22, 40, W - 40, 150, H - 40
    kind = st.get("kind")
    hero, ring_ = st.get("hero"), st.get("ring")
    if kind == "daily" and st.get("kcal"):
        hero = ("今日热量", st["kcal"][0], "千卡", None)
    bars = st.get("bars") or []
    facts = [] if bars else [f for f in st.get("facts") or [] if f[0]][:3]
    if kind == "daily" or (kind == "meal" and bars):
        facts = []
    lst = st.get("list") or []
    week = st.get("week")
    note = [x for x in (st.get("head"), "%s · %s" % st["foot"] if st.get("foot") else "") if x]
    parts = []  # (line, size, bold) for the teal note tile
    for i, t in enumerate(note):
        first = i == 0 and bool(st.get("head"))
        size = (64 if len(note) == 1 else 52) if first else 44
        parts += [(ln, size, first) for ln in lines_of(d, t, size, x1 - x0 - 88, 2 if first else 1)]
    note_h = sum(p[1] + 26 for p in parts) + 50
    photos = st.get("photos")
    rows = []  # (name, base height, minimum)
    if photos:
        rows.append(("photo", 440, 300))
    if hero or ring_:
        rows.append(("hero", 340, 280))
    if bars:
        rows.append(("bars", 240, 220))
    if facts:
        rows.append(("facts", 220, 200))
    if lst:
        rows.append(("list", 90 * min(len(lst), 4) + 70, 90 * min(len(lst), 2) + 70))
    if week:
        rows.append(("week", 230, 200))
    if note:
        rows.append(("note", note_h + 40, note_h))
    drop = ["list", "facts", "week", "bars"]
    while sum(r[2] for r in rows) + G * (len(rows) - 1) > bottom - top and drop:
        name = drop.pop(0)
        rows = [r for r in rows if r[0] != name]
    avail = bottom - top - G * (len(rows) - 1)
    base = sum(r[1] for r in rows)
    heights = [max(r[2], r[1] * avail / base) for r in rows]
    over = sum(heights) - avail
    if over > 0:  # take it from the most elastic rows
        for i in sorted(range(len(rows)), key=lambda i: -(heights[i] - rows[i][2])):
            cut = min(over, heights[i] - rows[i][2])
            heights[i] -= cut
            over -= cut
    y = top
    for (name, _, _), h in zip(rows, heights):
        h = int(h)
        b = (x0, y, x1, y + h)
        if name == "photo":
            collage(im, b, photos, r=36, gap=12)
        elif name == "hero":
            split = x1 if not ring_ else x0 + (x1 - x0) * (0.6 if hero else 0)
            if hero:
                tile(d, (x0, y, split - (G / 2 if ring_ else 0), y + h))
                hx1 = split - (G / 2 if ring_ else 0)
                frac = st["kcal"][1] if kind == "daily" and st.get("kcal") else None
                goal = st["kcal"][2] if kind == "daily" and st.get("kcal") else ""
                txt(d, (x0 + 40, y + 64), hero[0], 44, GREY, "lm")
                tall = h > 480 and not ring_  # little data: one big tile, so the number gets big
                room = h - 110 - (150 if frac is not None else 40) - (110 if tall else 0)
                bs = min(420 if tall else 240 if not ring_ else 150, int(room / 0.8))
                unit_w = tw(d, hero[2], 56) + 20 if hero[2] else 0
                v, bs = fit(d, hero[1], bs, hx1 - x0 - 80 - unit_w, 70)
                by = (y + 110 + (room + bs * 0.75) / 2) if frac is not None or not tall else y + (h + bs * 0.72) / 2
                if not tall and frac is None:
                    by = y + (h + 70 + bs * 0.72) / 2
                w = txt(d, (x0 + 36, by), v, bs, WHITE, "ls", bold=True)
                if hero[2]:
                    txt(d, (x0 + 36 + w + 16, by), hero[2], 48, GREY, "ls")
                if frac is not None:
                    bar(d, x0 + 40, hx1 - 40, y + h - 112, frac, TEAL, 30)
                    txt(d, (x0 + 40, y + h - 48), goal, 40, (150, 150, 150), "lm")
                elif tall and st.get("kicker") and kind != "daily":
                    txt(d, (x0 + 40, y + h - 70), fit(d, st["kicker"], 64, hx1 - x0 - 80)[0], 64, TEAL, "lm", bold=True)
            if ring_:
                rx0 = split + (G / 2 if hero else 0)
                tile(d, (rx0, y, x1, y + h))
                cx = (rx0 + x1) / 2
                r = min((x1 - rx0) / 2 - 50, (h - 110) / 2)
                cy = y + 30 + r + 10
                ring(d, cx, cy, r, 34, ring_[0] / 100, TEAL, TRACK)
                sc, ss = fit(d, shown(ring_[0]), int(r * 0.75), r * 1.25, 60)
                txt(d, (cx, cy), sc, ss, WHITE, "mm", bold=True)
                txt(d, (cx, y + h - 44), fit(d, ring_[1], 40, x1 - rx0 - 40)[0], 40, TEAL, "mm")
        elif name in ("bars", "facts"):
            items = bars if name == "bars" else facts
            cw = (x1 - x0 - G * (len(items) - 1)) / len(items)
            for i, it in enumerate(items):
                tx0 = x0 + i * (cw + G)
                tile(d, (tx0, y, tx0 + cw, y + h))
                if name == "bars":
                    n, v, frac = it
                    txt(d, (tx0 + 30, y + 56), fit(d, n, 40, cw - 60)[0], 40, GREY, "lm")
                    v, vs = fit(d, v, 76, cw - 60, 46)
                    txt(d, (tx0 + 28, y + 56 + (h - 56) * 0.55), v, vs, WHITE, "ls", bold=True)
                    if frac is not None:
                        bar(d, tx0 + 30, tx0 + cw - 30, y + h - 52, frac, BAR_COLORS[i % 3], 24)
                else:
                    v, lab, u = it
                    value_unit(d, tx0 + 28, y + h / 2 + 14, v, u, 80, cw - 56, WHITE if i else TEAL, GREY)
                    txt(d, (tx0 + 30, y + h / 2 + 70), fit(d, lab, 40, cw - 60)[0], 40, GREY, "ls")
        elif name == "list":
            tile(d, b)
            n = max(1, min(len(lst), int((h - 40) // 84)))
            hidden = len(lst) - n + st.get("more", 0)
            slots = n + (1 if hidden else 0)
            step = (h - 40) / slots
            big_list = step > 120
            for i, (k, v) in enumerate(lst[:n]):
                cy = y + 20 + step * (i + 0.5)
                if i:
                    d.line((x0 + 36, cy - step / 2, x1 - 36, cy - step / 2), fill=(52, 54, 56), width=2)
                if big_list and kind == "daily":
                    cx = x0 + 80
                    d.rounded_rectangle((cx - 44, cy - 14, cx - 28, cy + 14), 5, fill=TEAL)
                    d.rounded_rectangle((cx + 28, cy - 14, cx + 44, cy + 14), 5, fill=TEAL)
                    d.rectangle((cx - 28, cy - 5, cx + 28, cy + 5), fill=TEAL)
                kx = x0 + (150 if big_list and kind == "daily" else 40)
                vs0 = 96 if big_list else 44
                vw = 0
                if v:
                    vt, vs = fit(d, v, vs0, (x1 - x0) * 0.5, MIN_PX)
                    txt(d, (x1 - 40, cy), vt, vs, TEAL, "rm", bold=True)
                    vw = tw(d, vt, vs)
                ks = 60 if big_list else 46
                txt(d, (kx, cy), fit(d, k, ks, x1 - 80 - kx - vw)[0], ks, WHITE, "lm", bold=True)
            if hidden:
                txt(d, (x0 + 40, y + 20 + step * (n + 0.5)), "+%d 项" % hidden, 40, GREY, "lm")
        elif name == "week":
            tile(d, b)
            done = week.get("done")
            cnt = sum(1 for t in (done or []) if t)
            txt(d, (x0 + 40, y + 56), "本周训练", 40, GREY, "lm")
            txt(d, (x1 - 40, y + 56), "%d / %s 天" % (cnt, shown(week["plan"])) if week.get("plan") else "%d 天" % cnt,
                40, TEAL, "rm", bold=True)
            if week.get("values"):
                week_bars(d, (x0 + 30, y + 100, x1 - 30, y + h - 14), week["values"], done, TEAL, TRACK, GREY)
            else:
                week_dots(d, x0 + 20, x1 - 20, y + 100 + (h - 100) / 2, done, TEAL, TRACK, DARK, GREY,
                          r=min(48, int((h - 120) / 2)))
        else:  # note: the sentence (and tomorrow / next week) on a teal tile
            tile(d, b)
            d.rounded_rectangle((x0, y + 24, x0 + 10, y + h - 24), 5, fill=TEAL)
            lh = [p[1] + 26 for p in parts]
            ly = y + (h - sum(lh)) / 2
            for (t, size, bold), step in zip(parts, lh):
                txt(d, (x0 + 44, ly + step / 2), t, size, WHITE if bold else (200, 200, 200), "lm", bold=bold)
                ly += step
        y += h + G
    return im


STYLE_FN = {"A": style_a, "B": style_b, "C": style_c}


def render(kind, spec):
    kind = KIND_ALIASES.get(kind, kind)
    st = STORIES[kind](spec)
    st["kind"] = kind
    style = STYLES.get(str(spec.get("style") or "A").strip().lower(), "A")
    if not st.get("photos"):
        if kind in ("meal", "workout"):
            st["photos"] = default_photos(kind, spec)
        elif style == "A":  # daily / weekly: a quiet backdrop behind the big type, not a photo slot
            st["backdrop"] = default_photos(kind, spec)
    return STYLE_FN[style](st)


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


def setup():
    global Image, ImageDraw, ImageFont, ImageFilter, F
    require_pillow()
    from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: F811

    F = phone_fonts(font_loader())


def main():
    if len(sys.argv) < 3 or KIND_ALIASES.get(sys.argv[1], sys.argv[1]) not in KINDS:
        sys.exit(USAGE)
    kind, out = sys.argv[1], sys.argv[2]
    source = sys.argv[3] if len(sys.argv) > 3 else "-"
    text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as error:
        sys.exit("Invalid JSON spec: %s" % error)
    setup()
    del LAYOUT[:]
    render(kind, clean(spec)).save(out, optimize=True)
    problems = layout_problems()
    print("WARN: " + "; ".join(problems[:5]) if problems else "OK " + out)


if __name__ == "__main__":
    main()
