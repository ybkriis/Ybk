#!/usr/bin/env python3
"""Card-driven edit builder (ffmpeg + Pillow).

usage: build.py PROJECT OUT.mp4 [--preview] [--check] [--frames t1,t2,...]

Reads PROJECT/edit/edit.json (list of segments) and PROJECT/audio/vo.json (word times).
Each segment: {"at": "phrase from script/narration.md", "offset": 0.0, "card": {...}, "sfx": "hit|whoosh|tick"}
A segment runs from its anchor time to the next segment's anchor time.
Anchors are matched in order against the script, and the script is aligned to the transcript,
so every cut lands on a real spoken word time.
"""
import difflib, hashlib, json, math, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
W, H = 1920, 1080
P = {  # theme "NIGHTWATCH" (original)
    "bg": (10, 13, 20), "bg2": (18, 24, 36), "ink": (242, 239, 233), "dim": (120, 128, 145),
    "faint": (42, 49, 64), "amber": (255, 176, 46), "red": (255, 59, 74), "blue": (58, 160, 255),
    "green": (61, 220, 151), "pink": (255, 79, 163), "grey": (107, 114, 128),
}
STATUS = {"CONFIRMED": "green", "REPORTED": "amber", "RUMOUR": "pink", "UNCONFIRMED": "pink",
          "ONE SOURCE": "pink", "NO EVIDENCE": "pink", "SEEN": "blue"}


def font(name, size):
    path = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True).stdout
    return ImageFont.truetype(path, size)

_FC = {}
def F(kind, size):
    key = (kind, size)
    if key not in _FC:
        _FC[key] = font({"head": "Inter Display:style=Black", "bold": "Inter:style=Bold",
                         "mono": "JetBrains Mono:style=ExtraBold", "body": "Inter:style=Medium"}[kind], size)
    return _FC[key]

# ---------- alignment ----------
NUM = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
       "eight": "8", "nine": "9", "ten": "10", "sixth": "6th", "ninetynine": "99"}

def norm(tok):
    t = re.sub(r"[^a-z0-9]", "", tok.lower().replace("’", "'").replace("'", ""))
    return NUM.get(t, t)

def tokens(text):
    text = text.replace("-", " ").replace("…", " ")
    return [n for n in (norm(t) for t in text.split()) if n]

def align(script_toks, words):
    tw = [norm(w["w"]) for w in words]
    times = [None] * len(script_toks)
    sm = difflib.SequenceMatcher(None, script_toks, tw, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            times[a + k] = words[b + k]["s"]
    # interpolate gaps
    known = [i for i, t in enumerate(times) if t is not None]
    for i in range(len(times)):
        if times[i] is None:
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            if prev is None: times[i] = times[nxt]
            elif nxt is None: times[i] = times[prev] + 0.3 * (i - prev)
            else: times[i] = times[prev] + (times[nxt] - times[prev]) * (i - prev) / (nxt - prev)
    return times, sum(n for _, _, n in sm.get_matching_blocks()) / max(1, len(script_toks))

def resolve(edl, script_toks, times):
    cur, out = 0, []
    for i, seg in enumerate(edl):
        ph = tokens(seg["at"])
        found = None
        for j in range(cur, len(script_toks) - len(ph) + 1):
            if script_toks[j:j + len(ph)] == ph:
                found = j; break
        if found is None:
            raise SystemExit(f"segment {i}: anchor not found after token {cur}: {seg['at']!r}")
        cur = found + 1
        out.append(times[found] + seg.get("offset", 0.0) - (0.06 if i else 0))
    out[0] = 0.0
    return out

# ---------- drawing ----------
_BG = None
def background():
    global _BG
    if _BG is None:
        im = Image.new("RGB", (W, H), P["bg"])
        d = ImageDraw.Draw(im)
        for x in range(0, W, 80): d.line([(x, 0), (x, H)], fill=(14, 18, 27))
        for y in range(0, H, 80): d.line([(0, y), (W, y)], fill=(14, 18, 27))
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse([W * .15, -H * .3, W * .85, H * .9], fill=60)
        glow = glow.filter(ImageFilter.GaussianBlur(220))
        im = Image.composite(Image.new("RGB", (W, H), P["bg2"]), im, glow)
        vig = Image.new("L", (W, H), 0)
        ImageDraw.Draw(vig).ellipse([-W * .2, -H * .25, W * 1.2, H * 1.25], fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(160))
        im = Image.composite(im, Image.new("RGB", (W, H), (4, 5, 9)), vig)
        _BG = im
    return _BG.copy()

def tw(d, s, f):
    b = d.textbbox((0, 0), s, font=f); return b[2] - b[0], b[3] - b[1], b[1]

def ctext(d, cx, y, s, f, fill):
    w, h, off = tw(d, s, f); d.text((cx - w / 2, y - off), s, font=f, fill=fill); return w, h

def fit(d, lines, kind, maxw, start, minimum=40):
    size = start
    while size > minimum and max(tw(d, l, F(kind, size))[0] for l in lines) > maxw: size -= 4
    return size

def star_pts(cx, cy, r, rot=-90):
    pts = []
    for i in range(10):
        rr = r if i % 2 == 0 else r * 0.45
        a = math.radians(rot + i * 36)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts

def stars(d, cx, cy, n, of, state, r=70, gap=30):
    total = of * 2 * r + (of - 1) * gap
    x0 = cx - total / 2 + r
    col = {"white": P["ink"], "red": P["red"], "grey": P["grey"]}
    for i in range(of):
        pts = star_pts(x0 + i * (2 * r + gap), cy, r)
        if i >= n:
            d.polygon(pts, outline=P["faint"], width=5)
        elif state == "hollow":
            d.polygon(pts, outline=P["ink"], width=7)
        else:
            d.polygon(pts, fill=col.get(state, P["ink"]))

def pill(d, x, y, text, color, f=None, pad=(22, 12), fill=(16, 20, 30), anchor="l"):
    f = f or F("mono", 26)
    w, h, off = tw(d, text, f)
    bw = w + pad[0] * 2 + 28
    if anchor == "c": x -= bw / 2
    d.rounded_rectangle([x, y, x + bw, y + h + pad[1] * 2], radius=(h + pad[1] * 2) / 2, fill=fill, outline=P["faint"], width=2)
    d.ellipse([x + pad[0], y + pad[1] + h / 2 - 7, x + pad[0] + 14, y + pad[1] + h / 2 + 7], fill=color)
    d.text((x + pad[0] + 28, y + pad[1] - off), text, font=f, fill=P["ink"])
    return bw

def src_pill(d, src):
    if not src: return
    st = src.split(" · ")[0]
    pill(d, 70, H - 120, src, P[STATUS.get(st, "dim")])

def kicker(d, y, text, color="amber"):
    ctext(d, W / 2, y, text, F("mono", 40), P[color])

# ---------- card types ----------
def c_words(d, c):
    lines = c["lines"]
    size = c.get("size") or fit(d, lines, "head", 1640, 190 if len(lines) == 1 else 150)
    f = F("head", size)
    lh = size * 1.08
    total = lh * len(lines)
    y = H / 2 - total / 2 + (30 if c.get("kicker") else 0)
    if c.get("kicker"): kicker(d, y - 90, c["kicker"], c.get("kcolor", "amber"))
    for i, l in enumerate(lines):
        col = P[c["accent_color"] if "accent_color" in c else "red"] if i in c.get("accent", []) else P["ink"]
        if i in c.get("dimlines", []): col = P["dim"]
        w, h = ctext(d, W / 2, y + i * lh, l, f, col)
        if i in c.get("strike", []):
            yy = y + i * lh + h / 2
            d.line([(W / 2 - w / 2 - 20, yy), (W / 2 + w / 2 + 20, yy)], fill=P["red"], width=14)

def c_stars(d, c):
    of = c.get("of", 6); n = c.get("n", of)
    r = 80 if of <= 5 else 72
    if c.get("game"): kicker(d, 300, c["game"])
    state = c.get("state", "white")
    if state == "flash": state = "white" if c.get("_frame", 0) == 0 else "grey"
    stars(d, W / 2, 470, n, of, state, r=r)
    if c.get("label"):
        f = F("bold", fit(d, [c["label"]], "bold", 1600, 64))
        ctext(d, W / 2, 640, c["label"], f, P[c.get("lcolor", "ink")])
    if c.get("sub"): ctext(d, W / 2, 740, c["sub"], F("mono", 34), P["dim"])

ICON_ORDER = ["CLOTHING", "VEHICLE", "APPEARANCE", "WEAPON", "PAIR", "CCTV"]
def c_hud(d, c):
    if c.get("game"): kicker(d, 210, c["game"])
    stars(d, W / 2, 360, c.get("n", 2), 6, c.get("state", "white"), r=58, gap=24)
    icons = c.get("icons", {})
    show = [k for k in ICON_ORDER if k in icons] if not c.get("all") else ICON_ORDER
    bw, bh, gap = 250, 110, 26
    total = len(show) * bw + (len(show) - 1) * gap
    x = W / 2 - total / 2
    for k in show:
        st = icons.get(k, "off")
        box = [x, 500, x + bw, 500 + bh]
        if st == "on":
            d.rounded_rectangle(box, radius=18, fill=P["red"])
            col = P["ink"]
        elif st == "hl":
            d.rounded_rectangle(box, radius=18, fill=P["red"], outline=P["amber"], width=8)
            col = P["ink"]
        elif st == "gone":
            d.rounded_rectangle(box, radius=18, outline=P["faint"], width=4)
            col = P["faint"]
        else:
            d.rounded_rectangle(box, radius=18, outline=P["faint"], width=4)
            col = P["dim"]
        f = F("mono", 34 if len(k) < 9 else 30)
        ctext(d, x + bw / 2, 500 + bh / 2 - 14, k, f, col)
        if st == "gone":
            d.line([(x + 20, 500 + bh / 2), (x + bw - 20, 500 + bh / 2)], fill=P["amber"], width=8)
        x += bw + gap
    if c.get("label"):
        f = F("bold", fit(d, [c["label"]], "bold", 1600, 64))
        ctext(d, W / 2, 700, c["label"], f, P[c.get("lcolor", "ink")])
    ctext(d, W / 2, 860, "ILLUSTRATION · NOT THE IN-GAME HUD", F("mono", 24), P["dim"])

def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tw(d, t, f)[0] > maxw and cur: lines.append(cur); cur = w
        else: cur = t
    lines.append(cur); return lines

def c_quote(d, c):
    text = "“" + c["text"] + "”"
    size = 96
    while True:
        f = F("head", size); lines = wrap(d, text, f, 1500)
        if len(lines) * size * 1.15 < 520 or size < 50: break
        size -= 6
    lh = size * 1.15
    y = H / 2 - len(lines) * lh / 2 - 60
    hl = (c.get("hl") or "").lower()
    for i, l in enumerate(lines):
        ws = l.split(" "); sp = tw(d, "a a", f)[0] - tw(d, "aa", f)[0]
        total = sum(tw(d, w, f)[0] for w in ws) + sp * (len(ws) - 1); x = W / 2 - total / 2
        for w in ws:
            col = P["amber"] if hl and re.sub(r"[^a-z]", "", w.lower()) == hl else P["ink"]
            d.text((x, y + i * lh - tw(d, "Ag", f)[2]), w, font=f, fill=col)
            x += tw(d, w, f)[0] + sp
    # attribution
    ctext(d, W / 2, y + len(lines) * lh + 50, c["who"], F("mono", 32), P["dim"])

def c_chapter(d, c):
    ctext(d, W / 2, 300, f"{c['num']:02d}", F("mono", 120), P["amber"])
    f = F("head", fit(d, [c["name"]], "head", 1600, 200))
    ctext(d, W / 2, 470, c["name"], f, P["ink"])
    strip(d, 790, c["num"])

NAMES = ["WITNESS", "DESCRIPTION", "CAMERA", "STARS", "HEAT", "ESCAPE", "SIXTH STAR"]
def strip(d, y, cur):
    n = 7; gap = 230; x0 = W / 2 - gap * 3
    for i in range(n):
        x = x0 + i * gap
        if i < n - 1: d.line([(x + 22, y), (x + gap - 22, y)], fill=P["amber"] if i + 1 < cur else P["faint"], width=5)
        on = i + 1 <= cur
        d.ellipse([x - 18, y - 18, x + 18, y + 18], fill=P["amber"] if on else P["bg"], outline=P["amber"] if on else P["faint"], width=5)
        ctext(d, x, y + 44, NAMES[i], F("mono", 22), P["ink"] if i + 1 == cur else P["dim"])

def c_map(d, c):
    kicker(d, 220, c.get("title", "SEVEN SYSTEMS · EACH ONE FEEDS THE NEXT"))
    n = 7; gap = 250; x0 = W / 2 - gap * 3; y = 520
    lit = set(c.get("lit", [])); hl = set(c.get("hl", []))
    for i in range(n):
        x = x0 + i * gap
        if i < n - 1:
            col = P["amber"] if c.get("flow") or (i + 1 in lit and i + 2 in lit) else P["faint"]
            d.line([(x + 60, y), (x + gap - 70, y)], fill=col, width=6)
            d.polygon([(x + gap - 70, y - 14), (x + gap - 50, y), (x + gap - 70, y + 14)], fill=col)
        k = i + 1
        if k == 7 and c.get("lock"):
            d.ellipse([x - 55, y - 55, x + 55, y + 55], outline=P["red"], width=6)
            ctext(d, x, y - 30, "?", F("head", 70), P["red"])
        else:
            fill = P["red"] if (k == 7 and c.get("final")) else (P["amber"] if k in hl else (P["bg2"] if k not in lit else (70, 56, 30)))
            d.ellipse([x - 55, y - 55, x + 55, y + 55], fill=fill, outline=P["amber"] if (k in lit or k in hl) else P["faint"], width=6)
            ctext(d, x, y - 28, str(k), F("head", 56), P["bg"] if k in hl or (k == 7 and c.get("final")) else P["ink"])
        ctext(d, x, y + 90, NAMES[i], F("mono", 24), P["ink"] if (k in hl or k in lit) else P["dim"])
    if c.get("label"):
        ctext(d, W / 2, 760, c["label"], F("bold", fit(d, [c["label"]], "bold", 1600, 60)), P["ink"])

def c_vs(d, c):
    d.line([(W / 2, 200), (W / 2, 880)], fill=P["faint"], width=4)
    for side, cx in (("left", W / 4), ("right", 3 * W / 4)):
        s = c.get(side, {}); on = c.get("hl") in (side, "both", None)
        ctext(d, cx, 260, s.get("game", ""), F("mono", 48), P["amber"] if on else P["faint"])
        if s.get("text"):
            f = F("head", 96)
            lines = wrap(d, s["text"], f, 760)
            sz = 96
            while len(lines) > 3 and sz > 50:
                sz -= 8; f = F("head", sz); lines = wrap(d, s["text"], f, 760)
            y = 540 - len(lines) * sz * 1.1 / 2
            for i, l in enumerate(lines):
                ctext(d, cx, y + i * sz * 1.1, l, f, P["ink"] if on else P["faint"])

def c_columns(d, c):
    cols = [("CONFIRMED", "green", "Rockstar said it"), ("REPORTED", "amber", "Guides and previews agree"), ("RUMOUR", "pink", "Sources disagree")]
    for i, (name, col, sub) in enumerate(cols):
        cx = W / 2 + (i - 1) * 560
        on = c.get("hl") in (None, name)
        d.rounded_rectangle([cx - 240, 300, cx + 240, 760], radius=28, outline=P[col] if on else P["faint"], width=6, fill=(16, 20, 30))
        ctext(d, cx, 470, name, F("mono", 54), P[col] if on else P["faint"])
        ctext(d, cx, 580, sub, F("body", 34), P["ink"] if on else P["faint"])

def c_metric(d, c):
    ctext(d, W / 2, 230, c["value"], F("head", 400), P["amber"])
    ctext(d, W / 2, 740, c["label"], F("mono", 44), P["ink"])

def c_tag(d, c):
    st = c["status"]; col = P[STATUS.get(st, "pink")]
    f = F("mono", 64); w, h, _ = tw(d, st, f)
    x0, y0 = W / 2 - w / 2 - 50, 300
    d.rounded_rectangle([x0, y0, x0 + w + 100, y0 + h + 60], radius=14, outline=col, width=8)
    ctext(d, W / 2, y0 + 30, st, f, col)
    f2 = F("head", 84); lines = wrap(d, c["text"], f2, 1600)
    for i, l in enumerate(lines): ctext(d, W / 2, 520 + i * 96, l, f2, P["ink"])
    if c.get("sub"): ctext(d, W / 2, 540 + len(lines) * 96 + 30, c["sub"], F("mono", 34), P["dim"])

def c_list(d, c):
    if c.get("kicker"): kicker(d, 230, c["kicker"])
    ctext(d, W / 2, 330, c["num"], F("mono", 150), P["amber"])
    f = F("head", fit(d, [c["title"]], "head", 1600, 170))
    ctext(d, W / 2, 540, c["title"], f, P["ink"])
    if c.get("sub"): ctext(d, W / 2, 760, c["sub"], F("mono", 40), P["dim"])

def c_radar(d, c):
    cx, cy, R = W / 2, 500, 330
    mode = c.get("mode", "cones")
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); o = ImageDraw.Draw(lay)
    o.rectangle([0, 0, W, H], fill=(14, 24, 30, 255))
    for k in range(-4, 5):
        o.line([(cx - R * 1.2, cy + k * R * .28), (cx + R * 1.2, cy + k * R * .28 + 30)], fill=(32, 46, 54, 255), width=12)
        o.line([(cx + k * R * .3, cy - R * 1.2), (cx + k * R * .3 - 40, cy + R * 1.2)], fill=(32, 46, 54, 255), width=12)
    cl = Image.new("RGBA", (W, H), (0, 0, 0, 0)); o = ImageDraw.Draw(cl)
    if mode == "cones":
        for (px, py, ang, col) in [(-210, -60, 10, P["blue"]), (150, -200, 100, P["blue"]), (200, 130, 200, P["red"])]:
            x, y = cx + px, cy + py
            o.pieslice([x - 170, y - 170, x + 170, y + 170], ang - 25, ang + 25, fill=col + (110,))
            o.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col + (255,))
    elif mode == "zone":
        o.ellipse([cx - 300, cy - 260, cx + 270, cy + 290], fill=P["red"] + (90,))
        o.ellipse([cx - 170, cy - 130, cx + 140, cy + 160], fill=P["red"] + (80,))
    lay = Image.alpha_composite(lay, cl)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    base = d.base.convert("RGBA"); base.paste(lay, (0, 0), mask)
    d.base.paste(base.convert("RGB"))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=P["dim"], width=6)
    if c.get("player", True):
        px, py = (cx - 200, cy + 170) if mode == "cones" else (cx + 30, cy + 20)
        d.polygon([(px, py - 26), (px + 19, py + 19), (px, py + 9), (px - 19, py + 19)], fill=P["ink"])
    if c.get("game"): kicker(d, 100, c["game"])
    if c.get("label"):
        ctext(d, W / 2, 890, c["label"], F("bold", fit(d, [c["label"]], "bold", 1600, 56)), P["ink"])
    ctext(d, W / 2, 970, "ILLUSTRATION · NOT GAME FOOTAGE", F("mono", 24), P["dim"])

def c_camera(d, c):
    cx, cy = W / 2, 330
    d.rounded_rectangle([cx - 170, cy - 70, cx + 150, cy + 70], radius=20, fill=P["ink"])
    d.polygon([(cx + 150, cy - 40), (cx + 240, cy - 75), (cx + 240, cy + 75), (cx + 150, cy + 40)], fill=P["ink"])
    d.ellipse([cx - 140, cy - 30, cx - 100, cy + 10], fill=P["red"])
    d.rectangle([cx - 30, cy + 70, cx + 10, cy + 150], fill=P["ink"])
    d.rectangle([cx - 110, cy + 150, cx + 90, cy + 170], fill=P["ink"])
    lines = c.get("lines", [])
    if lines:
        f = F("head", fit(d, lines, "head", 1600, 130))
        for i, l in enumerate(lines): ctext(d, W / 2, 600 + i * 140, l, f, P["red"] if i in c.get("accent", []) else P["ink"])

TL = [("GTA III", "2001", 6), ("VICE CITY", "2002", 6), ("SAN ANDREAS", "2004", 6), ("GTA IV", "2008", 6), ("GTA V", "2013", 5), ("GTA VI", "2026", 6)]
def c_timeline(d, c):
    kicker(d, 170, "MAXIMUM WANTED LEVEL")
    hl = c.get("hl")
    for i, (g, y, n) in enumerate(TL):
        row = 290 + i * 110
        on = hl is None or hl == g
        d.text((330, row - 10), g, font=F("head", 60), fill=P["ink"] if on else P["faint"])
        d.text((800, row), y, font=F("mono", 44), fill=P["dim"] if on else P["faint"])
        for k in range(6):
            pts = star_pts(1100 + k * 85, row + 30, 34)
            if k < n: d.polygon(pts, fill=(P["red"] if (g == "GTA V" and on) else P["ink"]) if on else P["faint"])
            else: d.polygon(pts, outline=P["red"] if on else P["faint"], width=4)

def c_end(d, c):
    kicker(d, 250, "YOUR TURN")
    f = F("head", 150)
    ctext(d, W / 2, 360, "HOW ARE YOU", f, P["ink"])
    ctext(d, W / 2, 530, "ESCAPING?", f, P["amber"])
    ctext(d, W / 2, 760, c.get("sub", "CHANGE CLOTHES · SWAP CARS · SPLIT UP · OR JUST OUTRUN THEM"), F("mono", 38), P["dim"])
    ctext(d, W / 2, 850, "TELL ME IN THE COMMENTS", F("mono", 38), P["ink"])

CARDS = {k[2:]: v for k, v in globals().items() if k.startswith("c_")}

def render_card(card, path, frame=0):
    im = background(); d = ImageDraw.Draw(im); d.base = im
    c = dict(card); c["_frame"] = frame
    CARDS[c["type"]](d, c)
    src_pill(d, c.get("src"))
    im.save(path)

# ---------- audio ----------
SFX = {
    "hit": "aevalsrc='0.95*sin(2*PI*(38+60*exp(-t*9))*t)*exp(-t*3.2)+0.35*(random(0)*2-1)*exp(-t*30)':d=1.4:s=48000",
    "whoosh": "aevalsrc='(random(0)*2-1)*pow(sin(PI*t/0.55),2)*0.6':d=0.55:s=48000,lowpass=f=2400,highpass=f=300",
    "tick": "aevalsrc='0.7*sin(2*PI*1800*t)*exp(-t*60)':d=0.12:s=48000",
}
SFX_GAIN = {"hit": 0.45, "whoosh": 0.30, "tick": 0.25}

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: sys.stderr.write(r.stderr[-3000:]); raise SystemExit("ffmpeg failed")

def main():
    a = sys.argv[1:]
    proj, out = a[0], a[1]
    preview, check = "--preview" in a, "--check" in a
    edl = json.load(open(os.path.join(proj, "edit/edit.json")))["segments"]
    vo = json.load(open(os.path.join(proj, "audio/vo.json")))
    narr = open(os.path.join(proj, "script/narration.md")).read().split("\n", 2)[2]
    narr = re.sub(r"^## .*$", "", narr, flags=re.M)
    st = tokens(narr)
    times, ratio = align(st, vo["words"])
    starts = resolve(edl, st, times)
    end = vo["duration"] + 2.5
    bounds = starts + [end]
    durs = [bounds[i + 1] - bounds[i] for i in range(len(edl))]
    print(f"alignment match {ratio:.1%}; {len(edl)} segments; video {end:.1f}s; "
          f"median shot {sorted(durs)[len(durs)//2]:.2f}s; min {min(durs):.2f}s; max {max(durs):.2f}s")
    bad = [(i, round(x, 2)) for i, x in enumerate(durs) if x < 0.5]
    if bad: print("WARNING very short segments:", bad)
    for i, s in enumerate(edl):
        if s["card"]["type"] not in CARDS: raise SystemExit(f"segment {i}: unknown card type")
    json.dump([{"i": i, "t": round(t, 3), "dur": round(dd, 3), "at": s["at"]} for i, (t, dd, s) in enumerate(zip(starts, durs, edl))],
              open(os.path.join(proj, "edit/timeline.json"), "w"), indent=1)
    if check: return
    ow, oh = (960, 540) if preview else (1920, 1080)
    cache = os.path.join(proj, "edit/cache"); os.makedirs(cache, exist_ok=True)
    cardsdir = os.path.join(proj, "cards/out"); os.makedirs(cardsdir, exist_ok=True)
    fb = [round(b * FPS) for b in bounds]
    parts = []
    for i, s in enumerate(edl):
        n = fb[i + 1] - fb[i]
        key = hashlib.md5(json.dumps([s["card"], n, ow, 3]).encode()).hexdigest()[:12]
        seg = os.path.join(cache, f"s{i:03d}_{key}.mp4")
        parts.append(seg)
        if os.path.exists(seg): continue
        png = os.path.join(cardsdir, f"card{i:03d}.png")
        render_card(s["card"], png)
        push = s.get("push", 0.035)
        zp = (f"scale={ow*2}:{oh*2},zoompan=z='1+{push}*on/{max(n,1)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={n}:s={ow}x{oh}:fps={FPS}")
        if s["card"].get("state") == "flash":
            png2 = os.path.join(cardsdir, f"card{i:03d}b.png"); render_card(s["card"], png2, frame=1)
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", png, "-i", png2, "-filter_complex",
                 f"[0]{zp}[a];[1]{zp}[b];[a][b]overlay=enable='gte(mod(t,0.7),0.35)',format=yuv420p",
                 "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), seg])
        else:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", png, "-vf", zp + ",format=yuv420p",
                 "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), seg])
        print(f"  rendered {i+1}/{len(edl)}", end="\r", flush=True)
    lst = os.path.join(cache, "concat.txt")
    with open(lst, "w") as L:
        for p in parts: L.write(f"file '{os.path.abspath(p)}'\n")
    video = os.path.join(cache, "video_preview.mp4" if preview else "video.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video])
    # audio mix
    sfxdir = os.path.join(proj, "sfx"); os.makedirs(sfxdir, exist_ok=True)
    for k, expr in SFX.items():
        f = os.path.join(sfxdir, f"{k}.wav")
        if not os.path.exists(f): run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", expr, f])
    inputs = ["-i", video, "-i", os.path.join(proj, "audio/vo.wav")]
    filt, labels = [], ["[1:a]"]
    idx = 2
    for i, s in enumerate(edl):
        if not s.get("sfx"): continue
        inputs += ["-i", os.path.join(sfxdir, s["sfx"] + ".wav")]
        ms = max(0, int(starts[i] * 1000) - (20 if s["sfx"] == "hit" else 120 if s["sfx"] == "whoosh" else 0))
        filt.append(f"[{idx}:a]volume={SFX_GAIN[s['sfx']]},adelay={ms}|{ms}[x{idx}]")
        labels.append(f"[x{idx}]"); idx += 1
    filt.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,apad=whole_dur={end},alimiter=limit=0.89[aout]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{end}", out])
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
