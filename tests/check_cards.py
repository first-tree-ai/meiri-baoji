#!/usr/bin/env python3
"""Render every check-in card kind with edge-case data and check the layout.

usage: python3 tests/check_cards.py [out_dir] [spec.json ...]

Without spec files it runs the built-in edge cases. Fails (exit 1) when two texts overlap, a text touches a progress
bar, a text leaves its tile or the card. Set BAOJI_FONT to try another font (e.g. Noto Sans CJK, as on Linux).
Each spec file may carry "_kind" (meal, workout, daily-nutrition, daily-timeline, daily-workout).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "meiri-baoji", "scripts"))
import checkin_card as cc  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

cc.Image, cc.ImageDraw, cc.ImageFont = Image, ImageDraw, ImageFont
cc.F = cc.font_loader()
RENDER = {"meal": cc.meal, "workout": cc.workout, "daily-nutrition": cc.daily_nutrition,
          "daily-timeline": cc.daily_timeline, "daily-workout": cc.daily_workout}


def photo(tmp, color):
    path = os.path.join(tmp, "p%d%d%d.jpg" % color)
    if not os.path.exists(path):
        Image.new("RGB", (900, 700), color).save(path)
    return path


def cases(tmp):
    p1, p2 = photo(tmp, (180, 120, 80)), photo(tmp, (90, 140, 90))
    macros = [{"name": "蛋白质", "value": 128, "target": 130}, {"name": "碳水", "value": 190, "target": 210},
              {"name": "脂肪", "value": 58, "target": 60}]
    over = [{"name": "蛋白质", "value": 1350, "target": 130}, {"name": "碳水", "value": 2195.5, "target": 210},
            {"name": "脂肪", "value": "152g", "target": "60 g"}]
    half = [{"name": "蛋白质", "value": 128}, {"name": "碳水", "value": None, "target": 210}, {"name": "脂肪", "value": 9}]
    meals8 = [{"photo": p1 if i % 2 else None, "name": "第%d餐" % (i + 1), "time": "%02d:00" % (7 + i * 2),
               "kcal": "300-450"} for i in range(8)]
    ex12 = [{"name": "保加利亚分腿蹲（单侧哑铃版本）%d" % i, "sets": "4 × 12（每侧）", "weight": "225 lb × 2",
             "delta": "+10 磅"} for i in range(12)]
    long_text = "今天把所有该做的事情都做完了，而且还额外加练了一组核心，晚上又早早睡了，非常非常棒的一天"
    week = {"done": [True, True, None, True, None, True, True], "plan": 5, "today": 6}
    extras = [{"name": "心率", "value": "152", "unit": "bpm"}, {"name": "配速", "value": "5:36", "unit": "/公里"},
              {"name": "距离", "value": "3.1 mi"}, {"name": "体重", "value": "176 lb"}, "体脂 18%", "肌酸 5g",
              {"name": "步频", "value": 178}]
    yield "meal-normal", "meal", {"photo": p1, "label": "晚饭 · 一人份", "dishes": "青椒炒肉 · 炒菠菜 · 米饭",
                                  "kcal": "650-850", "macros": {"protein": "35-50", "carb": "75-95", "fat": "25-35"},
                                  "targets": {"protein": 130, "carb": 210, "fat": 60}, "line": "菜很全"}
    yield "meal-long", "meal", {"photo": p1, "label": "外卖 · 招牌双拼饭（加量版）配溏心蛋西兰花玉米粒冰美式大杯",
                                "dishes": "【招牌】双拼饭·黑椒牛柳+照烧鸡腿肉（加量版）配溏心蛋、西兰花、玉米粒 + 冰美式（大杯 不加糖）+ 香辣小龙虾拌面",
                                "kcal": "8000-12500 kJ", "macros": {"protein": "135-180", "carb": "约350", "fat": "1200"},
                                "targets": {"protein": 90}, "extras": extras, "line": long_text}
    yield "meal-minimal", "meal", {"photo": p1, "kcal": "300 大卡"}
    yield "workout-normal", "workout", {"sport": "strength", "label": "力量 · 腿日", "line": "深蹲又多了 5kg，\n腿在变强。",
                                        "minutes": 58, "score": 85,
                                        "stats": [{"name": "消耗", "value": "约 320–400", "sub": "千卡"}],
                                        "exercises": [["杠铃深蹲", "4×8 · 60kg"]], "more": 2}
    yield "workout-overflow", "workout", {"sport": "climb", "label": "攀岩 · 抱石馆（室内）四小时马拉松式训练日",
                                          "line": long_text, "minutes": 245, "score": 100,
                                          "stats": [{"name": "消耗", "value": "约 3200–4100 kJ", "sub": "千卡"},
                                                    {"name": "训练量", "value": "12,345.5 kg", "sub": "+18% 比上次（上周四）"},
                                                    {"name": "本周", "value": "6 / 5", "sub": "次"},
                                                    {"name": "心率", "value": "152", "sub": "bpm"}],
                                          "exercises": [[e["name"], e["sets"] + " · " + e["weight"]] for e in ex12],
                                          "extras": extras}
    yield "workout-run-only", "workout", {"sport": "run", "minutes": 20}
    yield "nutrition-normal", "daily-nutrition", {"summary": "蛋白第一次吃够，\n腿也练完了。", "activity": "腿日 58 分钟",
                                                  "score": 82, "delta": "+6", "kcal": 1650, "kcal_goal": 1900,
                                                  "macros": macros, "meals": meals8[:4], "tomorrow": "明天休息"}
    yield "nutrition-over", "daily-nutrition", {"summary": long_text, "activity": long_text, "score": 100,
                                                "delta": "+100", "kcal": "11000 kJ", "kcal_goal": "1500 大卡",
                                                "macros": over, "meals": meals8, "extras": extras, "tomorrow": long_text}
    yield "nutrition-half", "daily-nutrition", {"kcal": 1650, "macros": half}
    yield "timeline-normal", "daily-timeline", {"summary": "蛋白第一次吃够。", "score": 82, "delta": "+6", "kcal": 1650,
                                                "kcal_goal": 1900, "macros": macros,
                                                "events": [{"time": "08:10", "title": "早餐", "sub": "约 150 千卡", "photo": p2},
                                                           {"time": "19:10", "title": "腿日", "highlight": True}],
                                                "tomorrow": "明天休息"}
    yield "timeline-overflow", "daily-timeline", {"summary": long_text, "score": 9, "delta": "-30", "kcal": 4800,
                                                  "kcal_goal": 1900, "macros": over, "extras": extras,
                                                  "events": [{"time": "%02d:%02d" % (6 + i, i * 5), "title": long_text[:20 + i],
                                                              "sub": long_text, "photo": p1 if i % 2 else None,
                                                              "highlight": i == 3} for i in range(12)],
                                                  "tomorrow": long_text}
    yield "timeline-empty", "daily-timeline", {}
    yield "workout-day-normal", "daily-workout", {"sport": "strength", "label": "腿日 · 19:10", "summary": "深蹲加上去了，\n腿很稳。",
                                                  "score": 86, "stats": [{"name": "时长", "value": "58", "unit": "分钟"}],
                                                  "exercises": ex12[:2], "week": week,
                                                  "diet": {"kcal": 1650, "kcal_goal": 1900, "macros": macros},
                                                  "tomorrow": "明天休息"}
    yield "workout-day-overflow", "daily-workout", {"sport": "hiit", "label": "两次训练 · 晨跑 + 晚上练腿（新纪录）",
                                                    "summary": long_text, "score": 100,
                                                    "stats": [{"name": "时长", "value": "93", "unit": "分钟"},
                                                              {"name": "消耗", "value": "约 2900 kJ", "unit": ""},
                                                              {"name": "训练量", "value": "12,345", "unit": "kg"},
                                                              {"name": "距离", "value": "3.1 mi", "unit": ""}],
                                                    "exercises": ex12, "week": week, "extras": extras,
                                                    "diet": {"kcal": "12000 kJ", "kcal_goal": 1500, "macros": over},
                                                    "tomorrow": long_text}
    yield "workout-day-empty", "daily-workout", {}


def overlaps(a, b):
    return a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1


def inside(a, b):
    return a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1


def check(layout):
    texts = [(b, t) for k, b, t in layout if k == "text"]
    bars = [b for k, b, _ in layout if k == "bar"]
    boxes = [b for k, b, _ in layout if k == "box"]
    problems = []
    for i, (a, ta) in enumerate(texts):
        if not inside(a, (0, 0, cc.W, cc.H)):
            problems.append("off card: %r %s" % (ta, a))
        for b, tb in texts[i + 1:]:
            if overlaps(a, b):
                problems.append("text overlap: %r %s × %r %s" % (ta, a, tb, b))
        for b in bars:
            if overlaps(a, b):
                problems.append("text on bar: %r %s × bar %s" % (ta, a, b))
        cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
        for b in boxes:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3] and not inside(a, b):
                problems.append("leaves tile: %r %s ⊄ %s" % (ta, a, b))
    return problems


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="cards-")
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    runs = list(cases(tmp))
    for path in sys.argv[2:]:
        spec = json.load(open(path, encoding="utf-8"))
        runs.append((os.path.splitext(os.path.basename(path))[0], spec.pop("_kind"), spec))
    failed = 0
    for name, kind, spec in runs:
        del cc.LAYOUT[:]
        try:
            im = RENDER[kind](cc.clean(json.loads(json.dumps(spec))))
        except SystemExit as error:
            print("SKIP %-24s %s" % (name, error))
            continue
        im.save(os.path.join(out, name + ".png"))
        problems = check(cc.LAYOUT)
        failed += bool(problems)
        print("%s %-24s %d texts" % ("FAIL" if problems else "ok  ", name, sum(1 for k, _, _ in cc.LAYOUT if k == "text")))
        for p in problems:
            print("     " + p)
    print("images in", out)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
