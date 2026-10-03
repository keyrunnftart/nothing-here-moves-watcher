# milestone card for x: one image, mostly art .. a grid of mints under a slim header, mint link in the footer.
# 20/30 etc = the latest 4 mints (2x2); sold out / closed = every mint of the wave / edition.
# needs pillow (pip install pillow in the workflow). fonts = the teaser's syncopate + michroma.
import io, os, math, urllib.request
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
GREEN, GREY, BG = (63, 242, 160), (150, 150, 150), (0, 0, 0)
W, M, G = 1600, 40, 16          # width, margin, gutter
HEAD, FOOT = 128, 104
_fc = {}
def font(kind, size):
    k = (kind, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(os.path.join(HERE, 'fonts', {'title': 'syncopate-700.ttf', 'wide': 'michroma-400.ttf'}[kind]), size)
    return _fc[k]

def tracked(d, xy, s, f, fill, track=0, anchor='l'):
    """draw letter-spaced text; anchor l / r / c on x, y = vertical middle"""
    w = sum(d.textlength(ch, font=f) for ch in s) + track * (len(s) - 1)
    x, y = xy
    x = x - w if anchor == 'r' else x - w / 2 if anchor == 'c' else x
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill, anchor='lm')
        x += d.textlength(ch, font=f) + track

def fetch(url):
    return Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={'user-agent': 'Mozilla/5.0 nhm-cloud-watcher'}), timeout=30).read())).convert('RGB')

def card(tiles, headline, sub, footer, left='MINT.KEYRUNNFT.ART'):
    """tiles = [(token id, mode, image url | PIL image)]. returns jpeg bytes."""
    n = len(tiles)
    cols = 2 if n <= 4 else math.ceil(math.sqrt(n * 1.2))
    rows = math.ceil(n / cols)
    t = (W - 2 * M - (cols - 1) * G) // cols
    H = HEAD + rows * t + (rows - 1) * G + FOOT
    cv = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(cv)
    tracked(d, (M, HEAD / 2), 'NOTHING HERE MOVES', font('title', 30), (255, 255, 255), 6)
    tracked(d, (W - M, HEAD / 2 - 16), headline, font('title', 30), GREEN, 5, 'r')
    tracked(d, (W - M, HEAD / 2 + 22), sub, font('wide', 15), GREY, 4, 'r')
    small = n > 4
    for k, (i, mode, img) in enumerate(tiles):
        r, c = divmod(k, cols)
        short = (cols - (n - r * cols)) * (t + G) // 2 if r == rows - 1 else 0   # centre a partial last row
        x, y = M + c * (t + G) + short, HEAD + r * (t + G)
        im = img if isinstance(img, Image.Image) else fetch(img)
        cv.paste(im.resize((t, t), Image.LANCZOS), (x, y))
        lab = f'#{i}' if small else f'#{i}  ·  {mode.upper()}'
        f = font('wide', 13 if small else 17)
        lw = sum(d.textlength(ch, font=f) for ch in lab) + 3 * (len(lab) - 1)
        ph = 30 if small else 40
        d.rectangle((x, y + t - ph, x + lw + (16 if small else 28), y + t), fill=BG)
        tracked(d, (x + (8 if small else 14), y + t - ph / 2), lab, f, (235, 235, 235), 3)
    fy = H - FOOT / 2
    tracked(d, (M, fy), left, font('title', 24), GREEN, 6)
    tracked(d, (W - M, fy), footer, font('wide', 15), GREY, 4, 'r')
    out = io.BytesIO(); cv.save(out, 'JPEG', quality=92); return out.getvalue()
