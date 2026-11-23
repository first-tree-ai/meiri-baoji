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


# Fonts some systems return as a last-resort fallback; they have no Chinese glyphs.
REJECT_NAMES = ("dejavu", "bitstream", "liberation", "freesans", "freeserif")
# User-level font folders (fonts installed without root, e.g. on a Cloud Computer).
USER_FONT_DIRS = ["~/.local/share/fonts", "~/.fonts"]
PROBE_CHARS = "中文"


def covers_cjk(path):
    """True only if the font really has glyphs for 中 and 文 (fallback fonts render boxes instead)."""
    if any(name in os.path.basename(path).lower() for name in REJECT_NAMES):
        return False
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(path, fontNumber=0, lazy=True)
        cmap = font.getBestCmap() or {}
        return all(ord(ch) in cmap for ch in PROBE_CHARS)
    except ImportError:
        pass
    except Exception:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont

        font = ImageFont.truetype(path, 32)

        def render(ch):
            img = Image.new("L", (48, 48), 0)
            ImageDraw.Draw(img).text((4, 4), ch, font=font, fill=255)
            return img.tobytes()

        # A missing glyph renders as the font's .notdef box: the same image for different
        # characters, or the same image as a private-use codepoint no font defines.
        missing = render("\U0010FFFD")
        shapes = [render(ch) for ch in PROBE_CHARS]
        return all(any(shape) and shape != missing for shape in shapes) and shapes[0] != shapes[1]
    except Exception:
        return False


def _user_font_files():
    for folder in USER_FONT_DIRS:
        root = os.path.expanduser(folder)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if name.lower().endswith((".ttf", ".ttc", ".otf")):
                    yield os.path.join(dirpath, name)


def _fontconfig_files():
    """Fonts fontconfig says support Chinese (fc-list filters by coverage; fc-match would fall back)."""
    if not shutil.which("fc-list"):
        return []
    try:
        out = subprocess.run(["fc-list", ":lang=zh", "file"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({line.split(":")[0].strip() for line in out.splitlines() if line.strip()})


def find_cjk_font():
    override = os.environ.get("BAOJI_FONT")
    candidates = ([override] if override else []) + FONT_CANDIDATES + list(_user_font_files()) + _fontconfig_files()
    seen = set()
    for path in candidates:
        if not path or path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        if covers_cjk(path):
            return path
    sys.exit(
        "NO_CJK_FONT: no font with Chinese glyphs was found, so the image would show boxes. "
        "Reply in text instead. To enable images, install a Chinese font (e.g. Noto Sans SC or "
        "WenQuanYi Micro Hei) or set BAOJI_FONT to its path."
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
