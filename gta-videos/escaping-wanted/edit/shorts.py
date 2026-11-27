#!/usr/bin/env python3
"""Cut vertical 9:16 Shorts / Reels / TikToks out of the long-form render.

usage: shorts.py [SOURCE.mp4] [--only N]

Each clip is defined by a start phrase and an end phrase from the narration. Both are
located in script/narration.md, whose words are aligned to audio/vo.json (ASR word timings),
so cuts land on real spoken word boundaries and captions use the script's spelling.
Layout (1080x1920): blurred backdrop, the 16:9 edit centred, a hook headline on top,
and word-by-word karaoke captions underneath (rendered with libass).
"""
import difflib, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "renders", "v1.mp4")
OUT = os.path.join(ROOT, "renders", "shorts")

CLIPS = [
    {"slug": "01-cops-changed", "title": "GTA 6 COPS\nAREN'T GTA 5 COPS",
     "start": "In GTA 5, you rob a store", "end": "extremely specific in what it knows"},
    {"slug": "02-witness", "title": "NO WITNESS,\nNO WANTED LEVEL",
     "start": "In GTA 5, the police are basically psychic", "end": "They describe who did it"},
    {"slug": "03-remember-your-shirt", "title": "GTA 6 COPS\nREMEMBER YOUR SHIRT",
     "start": "This is the heat system", "end": "The icons tell you who they're coming for"},
    {"slug": "04-star-colours", "title": "WHAT THE STAR\nCOLOURS MEAN",
     "start": "In GTA 5, stars meant one thing", "end": "the important word in that sentence is one"},
    {"slug": "05-escape-playbook", "title": "HOW TO LOSE\nTHE COPS IN GTA 6",
     "start": "Now GTA 6. The guides agree on a playbook", "end": "In GTA 6, you escape the description"},
    {"slug": "06-sixth-star", "title": "THE SIXTH STAR\nIS BACK",
     "start": "Six stars", "end": "They know exactly who you are"},
]

LEAD, TAIL = 0.15, 0.55          # seconds of breathing room around the spoken words
W, H, VY = 1080, 1920, 620        # canvas, top of the 16:9 window
VH = W * 9 // 16                  # 607


def disp(w):
    return w.strip("\"“”").upper()


NUM = {"five": "5", "six": "6", "seven": "7", "sixth": "6th", "ninety": "99"}


def norm(t):
    t = re.sub(r"[^a-z0-9]", "", t.lower().replace("’", "'").replace("'", ""))
    return NUM.get(t, t)


def script_words(vo):
    """Narration words (as written) with start/end times aligned from the ASR transcript."""
    raw = []
    for line in open(os.path.join(ROOT, "script", "narration.md")):
        if line.strip() and not line.startswith("#"):
            raw += line.replace("…", "… ").replace(" - ", " ").split()
    sw = [{"w": t} for t in raw]
    a = [norm(x["w"]) for x in sw]
    b = [norm(x["w"]) for x in vo]
    for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            sw[i + k]["s"], sw[i + k]["e"] = vo[j + k]["s"], vo[j + k]["e"]
    known = [i for i, x in enumerate(sw) if "s" in x]
    for i, x in enumerate(sw):  # interpolate words the ASR misheard
        if "s" not in x:
            p = max([k for k in known if k < i], default=None)
            q = min([k for k in known if k > i], default=None)
            lo = sw[p]["e"] if p is not None else 0.0
            hi = sw[q]["s"] if q is not None else lo + 0.4
            gap = [k for k in range((p if p is not None else -1) + 1, q if q is not None else len(sw))]
            step = (hi - lo) / len(gap)
            x["s"] = lo + step * gap.index(i)
            x["e"] = x["s"] + step
    return sw


def find(words, phrase, after=0):
    toks = [norm(t) for t in phrase.replace("-", " ").split() if norm(t)]
    seq = [norm(w["w"]) for w in words]
    for i in range(after, len(seq) - len(toks) + 1):
        if seq[i:i + len(toks)] == toks:
            return i, i + len(toks) - 1
    sys.exit(f"phrase not found in narration: {phrase!r}")


def ts(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t // 60 % 60):02d}:{t % 60:05.2f}"


def ass(clip, words, t0, dur):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Inter Display Black,92,&H00E9EFF2,&H00E9EFF2,&H00140D0A,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,60,60,250,1
Style: Cap,Inter Display Black,84,&H00E9EFF2,&H00E9EFF2,&H00140D0A,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,8,70,70,{VY + VH + 120},1
Style: Tag,Inter,40,&H00918078,&H00918078,&H00140D0A,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,2,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    title = clip["title"].replace("\n", "\\N")
    ev = [f"Dialogue: 0,{ts(0)},{ts(dur)},Title,,0,0,0,,{{\\fad(150,0)}}{title}",
          f"Dialogue: 0,{ts(0)},{ts(dur)},Tag,,0,0,0,,FULL BREAKDOWN ON THE CHANNEL"]
    # group words into short chunks; break on punctuation or every 3 words
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.,!?…:;\"]$", w["w"]):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + TAIL
        for k, w in enumerate(g):
            s = w["s"]
            e = g[k + 1]["s"] if k + 1 < len(g) else g_end
            txt = " ".join(
                (r"{\c&H2EB0FF&}" if j == k else "") + disp(x["w"]) + (r"{\c&HE9EFF2&}" if j == k else "")
                for j, x in enumerate(g))
            ev.append(f"Dialogue: 1,{ts(s - t0)},{ts(e - t0)},Cap,,0,0,0,,{txt}")
    return head + "\n".join(ev) + "\n"


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        only = int(args[args.index("--only") + 1]); del args[args.index("--only"):args.index("--only") + 2]
    src = args[0] if args else SRC
    words = script_words(json.load(open(os.path.join(ROOT, "audio", "vo.json")))["words"])
    os.makedirs(OUT, exist_ok=True)
    for n, clip in enumerate(CLIPS, 1):
        if only and n != only:
            continue
        a, _ = find(words, clip["start"])
        _, b = find(words, clip["end"], a)
        t0, t1 = max(0.0, words[a]["s"] - LEAD), words[b]["e"] + TAIL
        dur = t1 - t0
        sub = os.path.join(OUT, clip["slug"] + ".ass")
        open(sub, "w").write(ass(clip, words[a:b + 1], t0, dur))
        out = os.path.join(OUT, clip["slug"] + ".mp4")
        fc = (f"[0:v]split[a][b];"
              f"[a]scale=-2:{H},crop={W}:{H},gblur=sigma=40,eq=brightness=-0.28:saturation=0.8[bg];"
              f"[b]scale={W}:{VH}[fg];"
              f"[bg][fg]overlay=0:{VY},ass='{sub}',format=yuv420p[v];"
              f"[0:a]afade=t=in:d=0.08,afade=t=out:st={dur - 0.3:.2f}:d=0.3[a]")
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", src,
               "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True)
        print(f"{clip['slug']}: {t0:.2f}-{t1:.2f}s ({dur:.1f}s) -> {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
