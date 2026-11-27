#!/usr/bin/env python3
"""Render every check-in card kind in every style with edge-case data and check the layout.

usage: python3 tests/check_cards.py [out_dir] [spec.json ...]

Without spec files it runs the built-in edge cases in styles A, B and C. Fails (exit 1) when two texts overlap, a text
touches a progress bar, a text leaves its tile or the card. Set BAOJI_FONT to try another font (e.g. Noto Sans CJK, as
on Linux). Each spec file carries "_kind" (meal, workout, daily, weekly) and may carry "style".
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "meiri-baoji", "scripts"))
import checkin_card as cc  # noqa: E402

cc.setup()
Image = cc.Image


def photo(tmp, color, size=(900, 700)):
    path = os.path.join(tmp, "p%d%d%d-%dx%d.jpg" % (color + size))
    if not os.path.exists(path):
        Image.new("RGB", size, color).save(path)
    return path


def cases(tmp):
    p = [photo(tmp, (180, 120, 80)), photo(tmp, (90, 140, 90), (700, 1200)), photo(tmp, (60, 90, 160), (1600, 600)),
         photo(tmp, (200, 180, 60)), photo(tmp, (120, 60, 120)), photo(tmp, (40, 40, 40))]
    long_text = "今天把所有该做的事情都做完了，而且还额外加练了一组核心，晚上又早早睡了，非常非常棒的一天"
    ex12 = [{"name": "保加利亚分腿蹲（单侧哑铃版本）%d" % i, "sets": "4 × 12（每侧）", "weight": "225 lb × 2"} for i in range(12)]
    yield "meal-normal", "meal", {"photo": p[0], "label": "晚饭 · 一人份", "dishes": "青椒炒肉 · 炒菠菜 · 米饭",
                                  "kcal": "650-850", "macros": {"protein": "35-50", "carb": "75-95", "fat": "25-35"},
                                  "targets": {"protein": 130, "carb": 210, "fat": 60}, "line": "菜很全"}
    yield "meal-long-6photos", "meal", {"photos": p, "label": "外卖 · 招牌双拼饭（加量版）配溏心蛋西兰花玉米粒冰美式大杯",
                                        "dishes": "【招牌】双拼饭·黑椒牛柳+照烧鸡腿肉（加量版）配溏心蛋、西兰花、玉米粒 + 冰美式（大杯 不加糖）",
                                        "kcal": "8000-12500 kJ", "macros": {"protein": "135-180", "carb": "约350", "fat": "1200"},
                                        "targets": {"protein": 90}, "line": long_text}
    yield "meal-portion-wide", "meal", {"label": "下午茶 · 轻松时刻", "dishes": "方形慕斯蛋糕、3小块", "kcal": "1200-1500",
                                        "macros": {"protein": "45-60", "carb": "150-180", "fat": "40-55"}}
    yield "meal-minimal", "meal", {"photo": p[1], "kcal": "300 大卡"}
    yield "meal-photo-only-3", "meal", {"photos": p[:3]}
    yield "workout-normal", "workout", {"sport": "strength", "label": "力量 · 腿日", "line": "深蹲又多了 5kg，\n腿在变强。",
                                        "minutes": 58, "score": 85,
                                        "stats": [{"name": "消耗", "value": "约 320–400", "sub": "千卡"}],
                                        "exercises": [["杠铃深蹲", "4×8 · 60kg"]], "more": 2}
    yield "workout-overflow", "workout", {"sport": "climb", "label": "攀岩 · 抱石馆（室内）四小时马拉松式训练日",
                                          "line": long_text, "minutes": 245, "score": 100, "photos": p[:2],
                                          "stats": [{"name": "消耗", "value": "约 3200–4100 kJ", "sub": "千卡"},
                                                    {"name": "训练量", "value": "12,345.5 kg", "sub": "+18% 比上次"},
                                                    {"name": "本周", "value": "6 / 5", "sub": "次"},
                                                    {"name": "心率", "value": "152", "sub": "bpm"}],
                                          "exercises": ex12}
    yield "workout-run-only", "workout", {"sport": "run", "minutes": 20}
    yield "daily-normal", "daily", {"date": "11月27日", "summary": "蛋白第一次吃够，\n腿也练完了。", "score": 82, "delta": "+6",
                                    "kcal": 1650, "kcal_goal": 1900,
                                    "macros": [{"name": "蛋白质", "value": 128, "target": 130},
                                               {"name": "碳水", "value": 190, "target": 210},
                                               {"name": "脂肪", "value": 58, "target": 60}],
                                    "workouts": [{"name": "腿日", "minutes": 58}], "tomorrow": "明天休息",
                                    "week": {"done": [True, True, None, True, None, None, None], "plan": 4}}
    yield "daily-overflow", "daily", {"date": "2026-11-27", "summary": long_text, "score": 100, "delta": "+100",
                                      "kcal": "11000 kJ", "kcal_goal": "1500 大卡", "photos": p,
                                      "macros": [{"name": "蛋白质", "value": 1350, "target": 130},
                                                 {"name": "碳水", "value": 2195.5, "target": 210},
                                                 {"name": "脂肪", "value": "152g", "target": "60 g"}],
                                      "workouts": [{"name": "晨跑（沿江大道往返一圈）", "minutes": 45},
                                                   {"name": "晚上练腿（新纪录）", "minutes": 93}],
                                      "tomorrow": long_text, "week": {"done": [True] * 7, "plan": 5}}
    yield "daily-kcal-only", "daily", {"kcal": 1650}
    yield "daily-workout-only", "daily", {"workouts": [{"name": "瑜伽", "minutes": 30}], "summary": "动了就好"}
    yield "weekly-normal", "weekly", {"range": "11.21–11.27", "plan": 4,
                                      "days": [{"trained": True, "score": 78}, {"trained": False, "score": 64}, None,
                                               {"trained": True, "score": 82}, None, None, {"trained": True, "score": 88}],
                                      "stats": [{"name": "蛋白吃够", "value": "4", "unit": "天"},
                                                {"name": "平均热量", "value": "1,720", "unit": "千卡"}],
                                      "best": "周日深蹲第一次到 70kg", "next": "工作日早饭都加个鸡蛋"}
    yield "weekly-overflow", "weekly", {"range": "2026年11月21日–2026年11月27日（第 48 周）", "plan": 7,
                                        "days": [{"trained": True, "kcal": 1800 + i * 300} for i in range(7)],
                                        "stats": [{"name": "平均每天吃到的蛋白质克数", "value": "123,456.7", "unit": "千卡"}] * 3,
                                        "best": long_text, "next": long_text}
    yield "weekly-two-days", "weekly", {"days": [{"trained": True}, None, None, {"trained": False}]}


def overlaps(a, b):
    return a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1


def inside(a, b):
    return a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="cards-")
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    runs = []
    for name, kind, spec in cases(tmp):
        runs += [("%s-%s" % (name, s), kind, dict(spec, style=s)) for s in "ABC"]
    for path in sys.argv[2:]:
        spec = json.load(open(path, encoding="utf-8"))
        runs.append((os.path.splitext(os.path.basename(path))[0], spec.pop("_kind"), spec))
    failed = 0
    for name, kind, spec in runs:
        del cc.LAYOUT[:]
        try:
            im = cc.render(kind, cc.clean(json.loads(json.dumps(spec))))
        except SystemExit as error:
            print("SKIP %-28s %s" % (name, error))
            continue
        im.save(os.path.join(out, name + ".png"))
        problems = cc.layout_problems()
        failed += bool(problems)
        print("%s %-28s %d texts" % ("FAIL" if problems else "ok  ", name, sum(1 for k, _, _ in cc.LAYOUT if k == "text")))
        for p in problems:
            print("     " + p)
    print("images in", out)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
