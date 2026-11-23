#!/usr/bin/env python3
"""Render a weekly exercise (or meal) plan PNG for 每日薄肌.

usage: python3 plan_card.py <out.png> [spec.json | -]

The spec is JSON built from this user's own plan (never reuse another person's data):
  {
    "title": "每周运动计划",
    "subtitle": ["3 次力量 + 2 次间歇", "第一阶段 · 草稿，可改"],
    "week": [{"day": "周一", "label": "腿", "kind": "legs"}, {"day": "周四", "label": "休息", "kind": "rest"}],
    "sessions": [
      {"day": "周一", "title": "腿日", "duration": "约 60 分钟", "kind": "legs",
       "rows": [{"name": "杠铃深蹲", "sets": "4 × 6-8", "tag": "前侧"}],
       "footer": "一句说明（可选）"}
    ],
    "rules_title": "怎么加量",
    "rules": ["每个动作做到次数上限、还留 2 次力气，下次加一点重量"],
    "footnote": "参考计划，不是医疗处方"
  }
Everything except "title" is optional. "kind" picks a color: legs, push, pull, cardio,
core, mobility, rest, meal, or any other word (falls back to a neutral color).
"""
import sys

from _common import font_loader, read_spec, require_pillow, wrap

USAGE = __doc__

COLORS = {
    "legs": (214, 90, 49), "push": (52, 110, 190), "pull": (45, 140, 100), "cardio": (128, 80, 170),
    "core": (90, 90, 100), "mobility": (40, 150, 160), "meal": (230, 140, 50), "rest": (150, 150, 150),
}
DEFAULT = (110, 120, 140)
BG, INK, SUB, WHITE = (246, 243, 236), (34, 34, 38), (110, 108, 104), (255, 255, 255)
W, M = 1200, 48
ROW_H, HEAD_H = 46, 76


def color(kind):
    return COLORS.get(str(kind or "").lower(), DEFAULT)


def main():
    spec = read_spec(sys.argv, USAGE)
    out = sys.argv[1]
    if not spec.get("title"):
        sys.exit("spec needs a title")
    require_pillow()
    from PIL import Image, ImageDraw

    F = font_loader()
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    subtitle = spec.get("subtitle") or []
    if isinstance(subtitle, str):
        subtitle = [subtitle]
    week = spec.get("week") or []
    sessions = spec.get("sessions") or []
    rules = spec.get("rules") or []
    footnote = spec.get("footnote") or ""

    def session_rows(session):
        rows = []
        for row in session.get("rows") or []:
            name_lines = wrap(probe, row.get("name", ""), F(27), 640 if row.get("sets") else 860)
            rows.append((name_lines, row.get("sets", ""), row.get("tag", "")))
        return rows

    prepared = [(s, session_rows(s), wrap(probe, s.get("footer", ""), F(23), W - 2 * M - 64)) for s in sessions]

    def session_height(rows, footer_lines):
        return HEAD_H + 16 + sum(max(1, len(r[0])) * ROW_H for r in rows) + 16 + 34 * len(footer_lines)

    rule_lines = [wrap(probe, r, F(24), W - 2 * M - 100) for r in rules]
    foot_lines = wrap(probe, footnote, F(20), W - 2 * M - 64)
    rules_h = (90 + sum(len(l) * 36 + 14 for l in rule_lines) + 34 * len(foot_lines) + 30) if (rules or footnote) else 0
    top = 150 + 48 * len(subtitle) + 30
    week_h = 230 if week else 0
    H = top + week_h + sum(session_height(r, f) + 24 for _, r, f in prepared) + rules_h + 40

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((M, 56), spec["title"], font=F(64), fill=INK)
    for i, line in enumerate(subtitle):
        d.text((M, 150 + i * 48), line, font=F(30 if i == 0 else 26), fill=INK if i == 0 else SUB)

    y = top
    if week:
        d.text((M, y), spec.get("week_title", "一周安排"), font=F(34), fill=INK)
        n = len(week)
        gap = 12
        cw = (W - 2 * M - gap * (n - 1)) // n
        for i, item in enumerate(week):
            x = M + i * (cw + gap)
            d.rounded_rectangle((x, y + 60, x + cw, y + 190), 16, fill=color(item.get("kind")))
            d.text((x + cw // 2, y + 85), item.get("day", ""), font=F(24), fill=WHITE, anchor="mm")
            label_lines = wrap(probe, item.get("label", ""), F(26), cw - 12)[:2]
            base = y + 140 if len(label_lines) == 1 else y + 125
            for j, line in enumerate(label_lines):
                d.text((x + cw // 2, base + j * 32), line, font=F(26), fill=WHITE, anchor="mm")
        y += week_h

    for session, rows, footer_lines in prepared:
        h = session_height(rows, footer_lines)
        c = color(session.get("kind"))
        d.rounded_rectangle((M, y, W - M, y + h), 22, fill=WHITE)
        d.rounded_rectangle((M, y, W - M, y + HEAD_H), 22, fill=c)
        d.rectangle((M, y + HEAD_H - 22, W - M, y + HEAD_H), fill=c)
        d.text((M + 28, y + HEAD_H // 2), session.get("day", ""), font=F(30), fill=WHITE, anchor="lm")
        d.text((M + 130, y + HEAD_H // 2), session.get("title", ""), font=F(32), fill=WHITE, anchor="lm")
        if session.get("duration"):
            d.text((W - M - 28, y + HEAD_H // 2), session["duration"], font=F(26), fill=WHITE, anchor="rm")
        ry = y + HEAD_H + 16
        for name_lines, sets, tag in rows:
            for k, line in enumerate(name_lines or [""]):
                d.text((M + 32, ry + ROW_H // 2 + k * ROW_H), line, font=F(27), fill=INK, anchor="lm")
            if sets:
                d.text((M + 700, ry + ROW_H // 2), sets, font=F(27), fill=INK, anchor="lm")
            if tag:
                tw = d.textlength(tag, font=F(21)) + 28
                tx = W - M - 28 - tw
                d.rounded_rectangle((tx, ry + 7, tx + tw, ry + ROW_H - 7), 12, fill=c)
                d.text((tx + tw / 2, ry + ROW_H // 2), tag, font=F(21), fill=WHITE, anchor="mm")
            ry += max(1, len(name_lines)) * ROW_H
        for k, line in enumerate(footer_lines):
            d.text((M + 32, ry + 18 + k * 34), line, font=F(23), fill=SUB, anchor="lm")
        y += h + 24

    if rules_h:
        d.rounded_rectangle((M, y, W - M, y + rules_h), 22, fill=(255, 244, 230))
        d.text((M + 32, y + 30), spec.get("rules_title", "要点"), font=F(34), fill=INK)
        ry = y + 90
        for lines in rule_lines:
            d.ellipse((M + 34, ry + 11, M + 46, ry + 23), fill=COLORS["legs"])
            for k, line in enumerate(lines):
                d.text((M + 64, ry + 17 + k * 36), line, font=F(24), fill=INK, anchor="lm")
            ry += len(lines) * 36 + 14
        for k, line in enumerate(foot_lines):
            d.text((M + 32, ry + 10 + k * 34), line, font=F(20), fill=SUB, anchor="lm")
        y += rules_h

    img = img.crop((0, 0, W, y + 40))
    img.save(out)
    print(out)


if __name__ == "__main__":
    main()
