"""Shared helpers for the 每日薄肌 image scripts: CJK font lookup and JSON input."""
import json
import os
import shutil
import subprocess
import sys

# Common CJK fonts on Linux (Cloud Computer), macOS and Windows; the first that exists wins.
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        sys.exit("Pillow is not installed. Install it with: python3 -m pip install --user pillow")


def find_cjk_font():
    override = os.environ.get("BAOJI_FONT")
    if override and os.path.exists(override):
        return override
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    if shutil.which("fc-match"):
        try:
            found = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=zh"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if found and os.path.exists(found):
                return found
        except (OSError, subprocess.SubprocessError):
            pass
    sys.exit(
        "No Chinese font found. Install one (e.g. fonts-noto-cjk or fonts-wqy-microhei), "
        "or set BAOJI_FONT to a .ttf/.ttc/.otf path."
    )


def font_loader():
    from PIL import ImageFont

    path = find_cjk_font()
    cache = {}

    def load(size):
        if size not in cache:
            cache[size] = ImageFont.truetype(path, size)
        return cache[size]

    return load


def read_spec(argv, usage):
    """Read the JSON spec from the file named in argv[2], or from stdin when it is '-' or absent."""
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        sys.exit(usage)
    source = argv[2] if len(argv) > 2 else "-"
    text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        sys.exit("Invalid JSON spec: %s" % error)


def wrap(draw, text, font, width):
    """Wrap text (CJK or Latin) to lines no wider than width pixels."""
    lines, current = [], ""
    for char in str(text):
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        if current and draw.textlength(current + char, font=font) > width:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    return lines
