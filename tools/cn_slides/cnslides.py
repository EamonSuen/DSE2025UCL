#!/usr/bin/env python3
"""Page-by-page Chinese translation of slide PDFs (overlay method).

The method follows 01_Miller/ccp_chinese/slides_translation: the original PDF
page stays as a vector background (display math, figures, theme, numbers),
the English prose glyphs are removed, and Chinese text is typeset with
XeLaTeX at the original coordinates.  This script automates the region
finding that the reference did by hand.

    python3 -I tools/cn_slides/cnslides.py extract <deck>   # -> source.txt
    (write translation.txt:  <id> | <中文>)
    python3 -I tools/cn_slides/cnslides.py build <deck>     # -> PDF
    python3 -I tools/cn_slides/cnslides.py verify <deck>    # -> QA images

Translation file syntax, one region per line:
    k1a2b3c | 中文译文（行内公式用 $...$）
    k1a2b3c | =        keep the English text as it is
    k1a2b3c | -        remove the English text and put nothing
    k1a2b3c | 第一行 ⏎ 第二行   place each part at the original line positions
Lines starting with # are comments.  `@page N` lines are ignored (readability).
"""
import argparse
import collections
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

import fitz

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]
CONFIG = json.loads((TOOLS / 'decks.json').read_text(encoding='utf-8'))
AUTHOR = '孙翊铭'

FLAGS = (fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
         | fitz.TEXT_MEDIABOX_CLIP)
if hasattr(fitz, 'TEXT_ACCURATE_BBOXES'):
    FLAGS |= fitz.TEXT_ACCURATE_BBOXES

MATHFONT = re.compile(
    r'cmmi|cmsy|cmex|cmbsy|msam|msbm|math|eufm|eusm|eurm|euex|rsfs|stmary|'
    r'wasy|lasy|esint|bbm|dsrom|txmi|pxmi|txsy|pxsy|txex|pxex|lmmi|lmsy|lmex|'
    r'mnsymbol|bbold|mathabx|symbol|cmbrs|zxxrl', re.I)
ITALIC = re.compile(r'ital|obli|cmti|cmsl|ssi\d|ssi$|lcmssi|sfsi|sfso|-it$', re.I)
BOLD = re.compile(r'bold|bx|semibold|black|heavy|demi|lcmssb|sfsx|sfbx', re.I)
OPS = {'log', 'ln', 'exp', 'max', 'min', 'arg', 'argmax', 'argmin', 'lim',
       'sup', 'inf', 'det', 'tr', 'Pr', 'Var', 'Cov', 'plim', 'diag', 'sgn',
       'rank', 'dim', 'cos', 'sin', 'tan', 'mod', 'vec', 'cov', 'var', 'corr',
       'Corr', 'Prob', 'prob', 'liminf', 'limsup', 'supp', 'Pr(', 'Vec'}
LIG = {'\ufb01': 'fi', '\ufb02': 'fl', '\ufb00': 'ff', '\ufb03': 'ffi',
       '\ufb04': 'ffl', '\ufb05': 'st', '\ufb06': 'st'}
# T1-encoded fonts without a ToUnicode map report their slot numbers.  Slots
# 0x1c-0x1f count as whitespace in Python, so unmapped ligatures were dropped
# and stayed visible on the page.  Region ids keep using the original code
# (see idc()) so that existing translations stay attached.
T1_CODES = {'\x1b': '\ufb00', '\x1c': '\ufb01', '\x1d': '\ufb02', '\x1e': '\ufb03',
            '\x1f': '\ufb04', '\x10': '\u201c', '\x11': '\u201d', '\x15': '\u2013',
            '\x16': '\u2014'}


def idc(c):
    """The character as it entered region ids before T1 codes were mapped."""
    return c.get('idc', c['c'])


def id_string(chars):
    return ''.join(idc(c) for c in chars if not idc(c).isspace())
BULLETS = set('•◦▪▫■□●○◆◇▶►▸▹‣⁃∗✓✔➢➤★☆♦◮◭▷')
ACCENTS = {'ˆ': r'\hat', '^': r'\hat', '˜': r'\tilde', '~': r'\tilde',
           '¯': r'\bar', '˙': r'\dot', '¨': r'\ddot', 'ˇ': r'\check',
           '˘': r'\breve', '´': r'\acute', '`': r'\grave', '→': r'\vec',
           '⃗': r'\vec'}
GREEK = dict(zip('αβγδϵεζηθϑικλμνξπϖρϱσςτυϕφχψωΓΔΘΛΞΠΣΥΦΨΩ∆µ', [
    r'\alpha', r'\beta', r'\gamma', r'\delta', r'\epsilon', r'\varepsilon',
    r'\zeta', r'\eta', r'\theta', r'\vartheta', r'\iota', r'\kappa',
    r'\lambda', r'\mu', r'\nu', r'\xi', r'\pi', r'\varpi', r'\rho',
    r'\varrho', r'\sigma', r'\varsigma', r'\tau', r'\upsilon', r'\phi',
    r'\varphi', r'\chi', r'\psi', r'\omega', r'\Gamma', r'\Delta', r'\Theta',
    r'\Lambda', r'\Xi', r'\Pi', r'\Sigma', r'\Upsilon', r'\Phi', r'\Psi',
    r'\Omega', r'\Delta', r'\mu']))
SYM = {
    '∈': r'\in', '∉': r'\notin', '∋': r'\ni', '≤': r'\leq', '≥': r'\geq',
    '⩽': r'\leq', '⩾': r'\geq', '≠': r'\neq', '≡': r'\equiv',
    '≈': r'\approx', '∼': r'\sim', '≃': r'\simeq', '≅': r'\cong',
    '∝': r'\propto', '→': r'\to', '←': r'\leftarrow', '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow', '⇐': r'\Leftarrow', '⇔': r'\Leftrightarrow',
    '⟹': r'\Longrightarrow', '⟺': r'\Longleftrightarrow', '↦': r'\mapsto',
    '↑': r'\uparrow', '↓': r'\downarrow', '⇑': r'\Uparrow', '⇓': r'\Downarrow',
    '∞': r'\infty', '∑': r'\sum', '∏': r'\prod', '∫': r'\int', '∮': r'\oint',
    '∂': r'\partial', '∇': r'\nabla', '×': r'\times', '·': r'\cdot',
    '⋅': r'\cdot', '±': r'\pm', '∓': r'\mp', '−': '-', '–': '-',
    '∀': r'\forall', '∃': r'\exists', '∄': r'\nexists', '⊂': r'\subset',
    '⊆': r'\subseteq', '⊃': r'\supset', '⊇': r'\supseteq', '∪': r'\cup',
    '∩': r'\cap', '⋃': r'\bigcup', '⋂': r'\bigcap', '∅': r'\emptyset',
    '∖': r'\setminus', '′': "'", '″': "''", '∗': '*', '∘': r'\circ',
    '◦': r'\circ', '…': r'\ldots', '⋯': r'\cdots', '⋮': r'\vdots',
    '⋱': r'\ddots', 'ℝ': r'\mathbb{R}', 'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}', 'ℚ': r'\mathbb{Q}', 'ℂ': r'\mathbb{C}',
    'ℓ': r'\ell', '∣': r'\mid', '‖': r'\|', '⟨': r'\langle', '⟩': r'\rangle',
    '⊥': r'\perp', '≪': r'\ll', '≫': r'\gg', '∧': r'\wedge', '∨': r'\vee',
    '¬': r'\neg', '⊗': r'\otimes', '⊕': r'\oplus', '†': r'\dagger',
    '√': r'\surd', '⌈': r'\lceil', '⌉': r'\rceil', '⌊': r'\lfloor',
    '⌋': r'\rfloor', '{': r'\{', '}': r'\}', '%': r'\%', '#': r'\#',
    '&': r'\&', '_': r'\_', '≺': r'\prec', '≻': r'\succ', '⪯': r'\preceq',
    '⪰': r'\succeq', '⊤': r'\top', 'ı': r'\imath', 'ȷ': r'\jmath',
    '∆': r'\Delta', '⊙': r'\odot', '∠': r'\angle', '⊲': r'\lhd',
    '|': '|', '⋆': r'\star', '∪': r'\cup', '⊊': r'\subsetneq',
    '⩵': '==', '≜': r'\triangleq', '≔': ':=', '∎': r'\blacksquare'}


def deck_paths(deck):
    cfg = CONFIG[deck]
    src = REPO / cfg['src']
    out = REPO / cfg['out']
    work = out / 'src' / deck
    return cfg, src, out, work


# ----------------------------------------------------------------- extraction
def is_mathfont(font):
    return bool(MATHFONT.search(font))


def hidden_test(page):
    """Return f(char) -> True when an opaque fill painted later covers it."""
    try:
        trace = page.get_texttrace()
        paths = page.get_drawings()
    except Exception:
        return lambda c: False
    seq = {}
    invisible = set()
    for sp in trace:
        for ch in sp['chars']:
            key = (round(ch[2][0], 1), round(ch[2][1], 1))
            seq[key] = sp['seqno']
            if sp.get('type') == 3 or sp.get('opacity', 1) == 0:
                invisible.add(key)
    covers = []
    for d in paths:
        if d.get('fill') is None or (d.get('fill_opacity') or 1) < 0.99 or 'seqno' not in d:
            continue
        r = d['rect']
        if r.width < 4 or r.height < 4:
            continue
        covers.append((d['seqno'], r))

    # Candidates: glyphs under an opaque fill painted later.  The geometry
    # alone over-reports (soft-masked shadows, clipped figure backgrounds), so
    # each candidate is confirmed by removing it and re-rendering: a glyph
    # whose removal changes no pixel is really hidden.
    cand = {}
    for sp in trace:
        if sp.get('type') == 3 or sp.get('opacity', 1) == 0:
            continue
        for ch in sp['chars']:
            bb = fitz.Rect(ch[3])
            x = (bb.x0 + bb.x1) / 2
            y = ch[2][1] - 0.3 * sp['size']
            if any(sqd > sp['seqno'] and r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1
                   for sqd, r in covers):
                cand[(round(ch[2][0], 1), round(ch[2][1], 1))] = bb
    covered = set()
    if cand:
        Z = 3
        before = page.get_pixmap(matrix=fitz.Matrix(Z, Z), alpha=False)
        tmp = fitz.open()
        tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        tp = tmp[0]
        for bb in cand.values():
            cx, cy = (bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2
            tp.add_redact_annot(fitz.Rect(cx - .3, cy - .3, cx + .3, cy + .3),
                                fill=None, cross_out=False)
        tp.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0,
                            text=fitz.PDF_REDACT_TEXT_REMOVE)
        after = tp.get_pixmap(matrix=fitz.Matrix(Z, Z), alpha=False)
        for key, bb in cand.items():
            changed = 0
            for px in range(max(int(bb.x0 * Z), 0), min(int(bb.x1 * Z) + 1, before.width)):
                for py in range(max(int(bb.y0 * Z), 0), min(int(bb.y1 * Z) + 1, before.height)):
                    a, b = before.pixel(px, py), after.pixel(px, py)
                    if max(abs(u - v) for u, v in zip(a, b)) > 24:
                        changed += 1
            if changed < 3:
                covered.add(key)

    def hidden(c):
        key = (round(c['ox'], 1), round(c['oy'], 1))
        return key in invisible or key in covered
    return hidden


def page_chars(page):
    """Characters with font information; rotated text is kept separately."""
    raw = page.get_text('rawdict', flags=FLAGS)
    # MuPDF's redaction decides with the font-box glyph rectangles, so keep
    # those as well (the accurate boxes are used for geometry).
    plain = page.get_text('rawdict', flags=FLAGS & ~getattr(fitz, 'TEXT_ACCURATE_BBOXES', 0))
    fontbox = {}
    for b in plain['blocks']:
        if b['type'] != 0:
            continue
        for ln in b['lines']:
            for sp in ln['spans']:
                for c in sp['chars']:
                    fontbox[(round(c['origin'][0], 2), round(c['origin'][1], 2), c['c'])] = list(c['bbox'])
    hidden = hidden_test(page)
    chars, rot = [], []
    for b in raw['blocks']:
        if b['type'] != 0:
            continue
        for ln in b['lines']:
            dx, dy = ln['dir']
            for s in ln['spans']:
                font = s['font'].split('+')[-1]
                fl = s['flags']
                ital = bool(fl & 2) or bool(ITALIC.search(font))
                bold = bool(fl & 16) or bool(BOLD.search(font))
                for c in s['chars']:
                    ch = c['c']
                    rb = fontbox.get((round(c['origin'][0], 2), round(c['origin'][1], 2), ch), list(c['bbox']))
                    rec = dict(c=ch, bbox=list(c['bbox']), rbox=rb, ox=c['origin'][0],
                               oy=c['origin'][1], size=s['size'], font=font,
                               color=s['color'], ital=ital, bold=bold,
                               math=is_mathfont(font))
                    if ch in T1_CODES:
                        rec['c'], rec['idc'] = T1_CODES[ch], ch
                    if hidden(rec):
                        continue
                    if abs(dy) > 0.5 or abs(dx) < 0.5:
                        rec['dir'] = (dx, dy)
                        rot.append(rec)
                    else:
                        chars.append(rec)
    return chars, rot


def union_find(n):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)
    return find, union


def vint(c):
    s = c['size']
    return c['oy'] - 0.70 * s, c['oy'] + 0.20 * s


EXFONT = re.compile(r'cmex|lmex|pxex|txex|euex|mathex|extension', re.I)


def _finish_line(g):
    g.sort(key=lambda c: (c['bbox'][0], c['oy']))
    sizes = sorted(c['size'] for c in g)
    med = sizes[len(sizes) // 2]
    textsz = collections.Counter(round(c['size'], 2) for c in g
                                 if not c['math'] and c['c'].isalpha())
    if textsz:
        top = max(textsz.values())
        main = max(sz for sz, k in textsz.items() if k >= 0.5 * top)
        main = max(c['size'] for c in g if abs(c['size'] - main) < 0.01)
    else:
        main = max(s for s in sizes if s <= 1.3 * med + 0.01)
    pool = [c['oy'] for c in g if c['size'] >= 0.88 * main and not c.get('ex')] or [c['oy'] for c in g]
    base = statistics.median(pool)
    return dict(chars=g, size=main, base=base,
                x0=min(c['bbox'][0] for c in g), x1=max(c['bbox'][2] for c in g),
                top=base - 0.75 * main, bottom=base + 0.24 * main)


def build_lines(chars):
    """Cluster glyphs into visual lines.

    Pass 1 joins glyphs of similar size on a common baseline; pass 2 attaches
    small clusters (sub/superscripts, inline fractions) and big delimiters to
    the line they belong to.
    """
    items = [c for c in chars if not c['c'].isspace()]
    for c in items:
        c['ex'] = bool(EXFONT.search(c['font']))
    norm = [c for c in items if not c['ex']]
    n = len(norm)
    find, union = union_find(n)
    order = sorted(range(n), key=lambda i: norm[i]['bbox'][0])
    for a, i in enumerate(order):
        ci = norm[i]
        ti, bi = vint(ci)
        xi1 = max(ci['bbox'][2], ci['bbox'][0])
        for j in order[a + 1:]:
            cj = norm[j]
            if cj['bbox'][0] - xi1 > 1.25 * max(ci['size'], cj['size']):
                break
            ratio = min(ci['size'], cj['size']) / max(ci['size'], cj['size'])
            if ratio <= 0.86:
                continue
            tj, bj = vint(cj)
            if min(bi, bj) - max(ti, tj) >= 0.5 * min(bi - ti, bj - tj):
                union(i, j)
    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(norm[i])
    clusters = [_finish_line(g) for g in groups.values()]
    # big delimiters: stack multi-piece glyphs, then attach by vertical centre
    exg = sorted([c for c in items if c['ex']], key=lambda c: (c['bbox'][0], c['bbox'][1]))
    comps = []
    for c in exg:
        for comp in comps:
            r = comp['box']
            w = min(r[2], c['bbox'][2]) - max(r[0], c['bbox'][0])
            if w >= 0.5 * min(r[2] - r[0], c['bbox'][2] - c['bbox'][0]) and \
                    c['bbox'][1] - r[3] <= 1.0 and r[1] - c['bbox'][3] <= 1.0:
                comp['chars'].append(c)
                comp['box'] = [min(r[0], c['bbox'][0]), min(r[1], c['bbox'][1]),
                               max(r[2], c['bbox'][2]), max(r[3], c['bbox'][3])]
                break
        else:
            comps.append(dict(chars=[c], box=list(c['bbox'])))
    for comp in comps:
        r = comp['box']
        cy = (r[1] + r[3]) / 2
        best, bestd = None, None
        for l in clusters:
            if r[0] > l['x1'] + 0.6 * l['size'] or r[2] < l['x0'] - 0.6 * l['size']:
                continue
            d = abs(cy - (l['base'] - 0.25 * l['size']))
            if d <= 0.7 * l['size'] and (best is None or d < bestd):
                best, bestd = l, d
        if best is None:
            clusters.append(dict(chars=list(comp['chars']), size=comp['chars'][0]['size'],
                              base=comp['chars'][0]['oy'], x0=r[0], x1=r[2], top=r[1], bottom=r[3]))
        else:
            best['chars'].extend(comp['chars'])
            best['chars'].sort(key=lambda q: (q['bbox'][0], q['oy']))
            best['x0'] = min(best['x0'], r[0])
            best['x1'] = max(best['x1'], r[2])
    # pass 2: attach small clusters to a bigger neighbour
    clusters.sort(key=lambda l: l['size'])
    alive = [True] * len(clusters)
    for a, A in [(a, A) for _ in range(3) for a, A in enumerate(clusters)]:
        if not alive[a]:
            continue
        A = clusters[a]
        words = re.findall(r'[A-Za-z]{3,}', ''.join(c['c'] for c in A['chars']))
        if len(A['chars']) > 14 or len(words) >= 2:
            continue
        best, bestd = None, None
        for b, B in enumerate(clusters):
            if b == a or not alive[b] or A['size'] > 0.86 * B['size'] or A['size'] < 0.4 * B['size']:
                continue
            if A['x0'] > B['x1'] + 0.4 * B['size'] or A['x1'] < B['x0'] - 0.4 * B['size']:
                continue
            rel = (A['base'] - B['base']) / B['size']
            if not (-0.65 <= rel <= 0.45):
                continue
            # horizontal adjacency to some glyph of B
            dmin = min(max(0.0, max(ca['bbox'][0] - cb['bbox'][2], cb['bbox'][0] - ca['bbox'][2]))
                       for ca in A['chars'] for cb in B['chars'])
            if dmin > 0.45 * B['size']:
                continue
            if best is None or abs(rel) < bestd:
                best, bestd = b, abs(rel)
        if best is not None:
            B = clusters[best]
            merged = _finish_line(B['chars'] + A['chars'])
            merged['size'], merged['base'] = B['size'], B['base']
            merged['top'], merged['bottom'] = B['top'], B['bottom']
            clusters[best] = merged
            alive[a] = False
    lines = [l for l, ok in zip(clusters, alive) if ok]
    # pass 3: join clusters on a common baseline separated by a normal gap
    changed = True
    while changed:
        changed = False
        lines.sort(key=lambda l: l['x0'])
        for a in range(len(lines)):
            A = lines[a]
            if A is None:
                continue
            for b in range(a + 1, len(lines)):
                B = lines[b]
                if B is None:
                    continue
                S = max(A['size'], B['size'])
                if B['x0'] - A['x1'] > 1.25 * S:
                    continue
                if min(A['size'], B['size']) < 0.86 * S or abs(A['base'] - B['base']) > 0.15 * S:
                    continue
                if B['x0'] < A['x1'] - 0.5 * S and B['x1'] > A['x0'] + 0.5 * S and abs(A['base'] - B['base']) > 0.05 * S:
                    continue
                big = A if A['size'] >= B['size'] else B
                m = _finish_line(A['chars'] + B['chars'])
                m['size'], m['base'], m['top'], m['bottom'] = big['size'], big['base'], big['top'], big['bottom']
                lines[a] = A = m
                lines[b] = None
                changed = True
        lines = [l for l in lines if l is not None]
    # delimiters may bridge two pieces of one line: join again on baseline
    lines.sort(key=lambda l: l['x0'])
    out = []
    for l in lines:
        for o in out:
            S = max(o['size'], l['size'])
            if abs(o['base'] - l['base']) <= 0.05 * S and min(o['size'], l['size']) >= 0.86 * S \
                    and l['x0'] - o['x1'] <= 1.25 * S and l['x0'] >= o['x0']:
                o['chars'].extend(l['chars'])
                o['chars'].sort(key=lambda q: (q['bbox'][0], q['oy']))
                o['x1'] = max(o['x1'], l['x1'])
                break
        else:
            out.append(l)
    lines = out
    lines.sort(key=lambda l: (round(l['base'], 0), l['x0']))
    return lines


def tokens_of(line):
    """Split a line into tokens at spaces/gaps; classify each token."""
    S = line['size']
    toks, cur, prev = [], [], None
    for c in line['chars']:
        if prev is not None and c['bbox'][0] - prev['bbox'][2] > 0.17 * S:
            toks.append(cur)
            cur = []
        cur.append(c)
        if prev is None or c['bbox'][2] > prev['bbox'][2]:
            prev = c
    if cur:
        toks.append(cur)
    out = []
    for t in toks:
        for c in t:
            c['script'] = c['size'] < 0.86 * S
        txt = ''.join(LIG.get(c['c'], c['c']) for c in t)
        core = txt.strip('.,;:!?()[]"\'`’‘“”-–—/')
        letters = sum(ch.isalpha() for ch in txt)
        if any(c['script'] for c in t) or any(c['math'] for c in t):
            kind = 'math'
        elif letters >= 2 and core.replace('-', '').replace('’', '').replace("'", '').replace('.', '').replace('/', '').replace('&', '').isalnum():
            if core in OPS and not t[0]['ital']:
                kind = 'math'
            elif all(c['ital'] for c in t if c['c'].isalpha()) and letters == 2:
                kind = 'ital2'
            else:
                kind = 'word'
        elif letters == 1 and len(core) == 1 and core.isalpha():
            lc = [c for c in t if c['c'].isalpha()][0]
            kind = 'math' if lc['ital'] else 'single'
        elif re.search(r'[A-Za-z][,()=+\[\]]|[,()=+\[\]][A-Za-z]', core) and \
                all(c['ital'] for c in t if c['c'].isalpha()) and letters <= 4:
            kind = 'math'
        elif letters == 0 and txt.strip() and all(not c['c'].isalpha() for c in t):
            kind = 'num'
        elif letters >= 2:
            kind = 'word'
        else:
            kind = 'math'
        out.append(dict(chars=t, text=txt, kind=kind,
                        x0=min(c['bbox'][0] for c in t),
                        x1=max(c['bbox'][2] for c in t)))
    # resolve context-dependent kinds
    OPEN_R = re.compile(r'[=+\-−<>≤≥∈(\[{,|/×·∼≡≈]$')
    CLOSE_L = re.compile(r'^[=+\-−<>≤≥∈)\]},|/×·∼≡≈]')
    i = 0
    while i < len(out):
        if out[i]['kind'] not in ('num', 'single', 'ital2'):
            i += 1
            continue
        j = i
        while j < len(out) and out[j]['kind'] in ('num', 'single', 'ital2'):
            j += 1
        left = out[i - 1] if i > 0 else None
        right = out[j] if j < len(out) else None
        lk = left['kind'] if left else None
        rk = right['kind'] if right else None
        run = ''.join(t['text'] for t in out[i:j]).strip()
        if run and lk == 'math' and run[0] in '=+-−<>≤≥∈)]}|/×·∼≡≈,\'′':
            for t in out[i:j]:
                if t['kind'] == 'num':
                    t['kind'] = 'math'
        if run and rk == 'math' and run[-1] in '=+-−<>≤≥∈([{|/×·∼≡≈':
            for t in out[i:j]:
                if t['kind'] == 'num':
                    t['kind'] = 'math'
        for t in out[i:j]:
            if t['kind'] == 'ital2':
                t['kind'] = 'word' if ((lk == 'word' and left['chars'][0]['ital']) or
                                       (rk == 'word' and right['chars'][0]['ital'])) else 'math'
            elif t['kind'] == 'single':
                t['kind'] = 'word' if 'word' in (lk, rk) else 'math'
            else:
                if lk == 'math' and rk in ('math', None):
                    t['kind'] = 'math'
                elif lk is None and rk == 'math':
                    t['kind'] = 'math'
                elif lk == 'math' and OPEN_R.search(left['text']):
                    t['kind'] = 'math'
                elif rk == 'math' and CLOSE_L.search(right['text']):
                    t['kind'] = 'math'
                else:
                    t['kind'] = 'word'
        i = j
    # a leading superscript number is a list label, not mathematics
    return out


def char_latex(c):
    ch = LIG.get(c['c'], c['c'])
    if c.get('ex'):
        if ch in '([{⟨|':
            return r'\left' + ('\\' + ch if ch in '{' else ch)
        if ch in ')]}⟩':
            return r'\right' + ('\\' + ch if ch in '}' else ch)
        if ch in GREEK or ch in SYM or ch in '∑∏∫':
            return SYM.get(ch, GREEK.get(ch, ch))
        return '⟦?⟧'
    if ch == '\ufffd':
        return '⟦?⟧'
    f = c['font'].lower()
    if 'msbm' in f or 'bbm' in f or 'dsrom' in f:
        return r'\mathbb{%s}' % ch if ch.isalpha() else ch
    if ('cmsy' in f or 'lmsy' in f or 'mathsymbol' in f) and ch.isalpha() and ch.isupper():
        return r'\mathcal{%s}' % ch
    if 'eufm' in f and ch.isalpha():
        return r'\mathfrak{%s}' % ch
    if ch in GREEK:
        return GREEK[ch]
    if ch in SYM:
        return SYM[ch]
    if not c['math'] and ch.isalpha() and not c['ital'] and not c['script']:
        return r'\mathrm{%s}' % ch
    return ch


def join_latex(pieces):
    s = ''
    for piece in pieces:
        if s and re.search(r'\\[a-zA-Z]+$', s) and re.match(r'[a-zA-Z0-9]', piece):
            s += ' '
        s += piece
    return s


def math_latex(chars, base, S):
    """Rough LaTeX for a run of math glyphs (to be checked by the translator)."""
    chars = sorted(chars, key=lambda c: (c['bbox'][0], c['oy']))
    accents, body = [], []
    for c in chars:
        if c['c'] in ACCENTS and c['c'] != '→':
            w = max(0.1, c['bbox'][2] - c['bbox'][0])
            over = any(d is not c and d['c'] not in ACCENTS and
                       min(c['bbox'][2], d['bbox'][2]) - max(c['bbox'][0], d['bbox'][0]) >= 0.6 * w
                       for d in chars)
            if over or c['oy'] < base - 0.35 * S:
                accents.append(c)
                continue
        body.append(c)
    acc_of = {}
    for a in accents:
        cx = (a['bbox'][0] + a['bbox'][2]) / 2
        best = None
        for k, c in enumerate(body):
            if c['bbox'][0] - 0.5 <= cx <= c['bbox'][2] + 0.5 and abs(c['size'] - a['size']) < 0.2 * a['size']:
                best = k
                break
        if best is not None:
            acc_of[best] = ACCENTS[a['c']]
    out = []
    k = 0
    while k < len(body):
        c = body[k]
        rel = (c['oy'] - base) / S
        if c['script'] or c['size'] < 0.86 * S:
            grp = []
            while k < len(body) and (body[k]['script'] or body[k]['size'] < 0.86 * S):
                grp.append(body[k])
                k += 1
            subs = [d for d in grp if (d['oy'] - base) / S > 0.04]
            sups = [d for d in grp if (d['oy'] - base) / S <= 0.04]
            for kind, part in (('sup', [d for d in sups if d['c'] in '′″']), ('sub', subs),
                               ('sup', [d for d in sups if d['c'] not in '′″'])):
                if not part:
                    continue
                inner = join_latex([char_latex(d) for d in part])
                if kind == 'sup' and inner in ("'", "''"):
                    out.append(inner)
                else:
                    out.append(('_' if kind == 'sub' else '^') + ('{%s}' % inner if len(inner) > 1 else inner))
            continue
        lx = char_latex(c)
        if k in acc_of:
            lx = '%s{%s}' % (acc_of[k], lx)
        out.append(lx)
        k += 1
    s = ''
    for piece in out:
        if s and re.search(r'\\[a-zA-Z]+$', s) and re.match(r'[a-zA-Z]', piece):
            s += ' '
        s += piece
    s = re.sub(r'\.\s*\.\s*\.', r'\\ldots ', s)
    s = re.sub(r'(?:\\mathrm\{[A-Za-z]\})+', lambda m: r'\mathrm{%s}' % ''.join(re.findall(r'\{(.)\}', m.group(0))), s)
    s = re.sub(r'\\mathrm\{(ln|log|exp|max|min|lim|sup|inf|det|Pr|arg|cos|sin)\}', r'\\\1 ', s)
    s = s.replace('\u0338', r'\not')
    s = re.sub(r'\\ldots (?=[,)\]}]|$)', r'\\ldots', s)
    s = re.sub(r'\}_\{', '}_{', s)
    return s


def tex_escape_text(s):
    s = ''.join(LIG.get(ch, ch) for ch in s)
    rep = {'\\': r'\textbackslash{}', '%': r'\%', '&': r'\&', '#': r'\#',
           '$': r'\$', '_': r'\_', '{': r'\{', '}': r'\}',
           '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(rep.get(ch, ch) for ch in s)


def tok_style(t):
    letters = [c for c in t['chars'] if c['c'].isalpha()] or t['chars']
    bold = sum(c['bold'] for c in letters) > len(letters) / 2
    color = collections.Counter(c['color'] for c in t['chars']).most_common(1)[0][0]
    return bold, color


def line_text(line, toks, dom=None):
    """English text of a line with rough inline LaTeX.

    Words whose colour differs from the region's main colour are wrapped in
    ⟪...⟫, bold words in a non-bold region in **...**.
    """
    parts, mathbuf = [], []

    def flush():
        if mathbuf:
            chars = [c for t in mathbuf for c in t['chars']]
            parts.append(('m', math_latex(chars, line['base'], line['size']), None))
            mathbuf.clear()
    for t in toks:
        if t['kind'] == 'math':
            mathbuf.append(t)
        else:
            flush()
            parts.append(('w', tex_escape_text(t['text']), tok_style(t)))
    flush()
    s = ''
    open_mark = ''
    for kind, txt, st in parts:
        if kind == 'm':
            trail = ''
            m = re.match(r'^(.*?)([,.;:]+)$', txt)
            if m and m.group(1):
                txt, trail = m.group(1), m.group(2)
            piece = '$%s$%s' % (txt, trail)
            mark = open_mark
        else:
            piece = txt
            mark = ''
            if dom is not None:
                bold, color = st
                if color != dom['color']:
                    mark = '⟪'
                elif bold and not dom['bold']:
                    mark = '**'
        if mark != open_mark:
            if open_mark:
                s += '⟫' if open_mark == '⟪' else '**'
            s += (' ' if s else '') + mark
            open_mark = mark
            s += piece
        else:
            s += (' ' if s else '') + piece
    if open_mark:
        s += '⟫' if open_mark == '⟪' else '**'
    return s


def marker_of(line, toks, images, drawings):
    """Detect a list marker immediately left of (or starting) the line."""
    S = line['size']
    if toks:
        t0 = toks[0]
        txt = t0['text'].strip()
        gap_ok = len(toks) > 1 and toks[1]['x0'] - t0['x1'] > 0.25 * S
        if txt and all(ch in BULLETS or ch in '–-—' for ch in txt) and len(txt) <= 2 and gap_ok:
            return 'glyph', t0
        if gap_ok and re.fullmatch(r'\(?([0-9]{1,2}|[a-hA-H]|[ivxIVX]{1,4})[.)]', txt):
            return 'label', t0
        if len(toks) > 1 and txt.isdigit() and all(c['size'] < 0.86 * S for c in t0['chars']):
            return 'label', t0
    x0, top, bottom = line['x0'], line['top'], line['bottom']
    for r in images + drawings:
        w, h = r[2] - r[0], r[3] - r[1]
        if w <= 9 and h <= 9 and r[2] <= x0 + 1 and r[2] >= x0 - 22:
            cy = (r[1] + r[3]) / 2
            if top - 1 <= cy <= bottom + 1:
                return 'shape', None
    return None, None


def small_shapes(page):
    rects = []
    for info in page.get_image_info():
        r = info['bbox']
        rects.append(list(r))
    drawings = []
    try:
        for d in page.get_drawings():
            r = d['rect']
            drawings.append(dict(rect=[r.x0, r.y0, r.x1, r.y1],
                                 fill=d.get('fill'), color=d.get('color'),
                                 width=d.get('width') or 0))
    except Exception:
        pass
    return rects, drawings


def region_id(text):
    norm = re.sub(r'\s+', ' ', text).strip()
    return 'k' + hashlib.sha1(norm.encode('utf-8')).hexdigest()[:6]


def extract_page(page, pno):
    chars, rot = page_chars(page)
    images, drawings = small_shapes(page)
    lines = build_lines(chars)
    rules = [d for d in drawings
             if (d['rect'][3] - d['rect'][1]) <= 1.2 and (d['rect'][2] - d['rect'][0]) >= 2]
    small = [d['rect'] for d in drawings
             if (d['rect'][2] - d['rect'][0]) <= 9 and (d['rect'][3] - d['rect'][1]) <= 9
             and d['fill'] is not None]
    allex = [c for l in lines for c in l['chars'] if c.get('ex')]
    for ln in lines:
        # a big brace/bracket opening the line (cases environments) stays in
        # the background: it is structure, not text
        S = ln['size']
        lead = []
        for c in ln['chars']:
            if c.get('ex'):
                lead.append(c)
                continue
            break
        if lead:
            # a wide accent sits over the next glyph; a brace stands before it
            rest0 = [c for c in ln['chars'] if not any(c is q for q in lead)]
            if rest0:
                nxt = min(rest0, key=lambda c: c['bbox'][0])
                w = max(0.1, nxt['bbox'][2] - nxt['bbox'][0])
                ov = min(max(c['bbox'][2] for c in lead), nxt['bbox'][2]) - max(min(c['bbox'][0] for c in lead), nxt['bbox'][0])
                if ov > 0.4 * w:
                    lead = []
        if lead:
            span = max(c['bbox'][3] for c in lead) - min(c['bbox'][1] for c in lead)
            stacked = False
            for g in lead:
                for h in allex:
                    if any(h is q for q in ln['chars']):
                        continue
                    w = min(g['bbox'][2] - g['bbox'][0], h['bbox'][2] - h['bbox'][0])
                    ox = min(g['bbox'][2], h['bbox'][2]) - max(g['bbox'][0], h['bbox'][0])
                    gap = max(h['bbox'][1] - g['bbox'][3], g['bbox'][1] - h['bbox'][3])
                    if w > 0 and ox >= 0.3 * w and gap < 0.8 * S:
                        stacked = True
            rest = [c for c in ln['chars'] if not any(c is q for q in lead)]
            if rest and not stacked:
                nx0 = min(c['bbox'][0] for c in rest)
                if True:
                    for other in lines:
                        if other is ln:
                            continue
                        if 0.5 * S < abs(other['base'] - ln['base']) < 2.4 * S and abs(other['x0'] - nx0) < 1.5:
                            stacked = True
                            break
            if span <= 1.5 * S and not stacked:
                lead = []
        if lead and len(lead) < len(ln['chars']):
            ln['chars'] = [c for c in ln['chars'] if not any(c is q for q in lead)]
            ln['x0'] = min(c['bbox'][0] for c in ln['chars'])
        ln['toks'] = tokens_of(ln)
    # complex lines: other (math) lines overlap vertically inside the x-range
    for i, ln in enumerate(lines):
        S = ln['size']
        cx = any(((c['bbox'][3] - c['bbox'][1]) > 2.6 * S and not c.get('ex')) or c['size'] > 1.6 * S
                 for c in ln['chars'])
        for j, other in enumerate(lines):
            if i == j or cx:
                continue
            if other['x1'] < ln['x0'] - 2 or other['x0'] > ln['x1'] + 2:
                continue
            ot, ob = other['top'] + 0.1 * other['size'], other['bottom'] - 0.05 * other['size']
            if min(ln['bottom'], ob) - max(ln['top'], ot) > 0.02 * S:
                cx = True
        ln['complex'] = cx
        ln['prose_letters'] = sum(sum(ch.isalpha() for ch in t['text'])
                                  for t in ln['toks'] if t['kind'] == 'word')
        ln['rules'] = []
        tc = dominant_color_rgb(ln)
        mathx = [(c['bbox'][0], c['bbox'][2]) for t in ln['toks'] if t['kind'] == 'math' for c in t['chars']]
        for d in rules:
            r = d['rect']
            if not (r[0] >= ln['x0'] - 1 and r[2] <= ln['x1'] + 1
                    and ln['top'] - 1 <= (r[1] + r[3]) / 2 <= ln['bottom'] + 1):
                continue
            col = d['fill'] if d['fill'] is not None else d['color']
            if col is None or max(abs(a - b) for a, b in zip(col, tc)) > 0.12:
                continue
            w = r[2] - r[0]
            cover = sum(max(0.0, min(r[2], b) - max(r[0], a)) for a, b in mathx)
            if cover < 0.6 * w:
                continue
            ln['rules'].append(r)
    regions = []
    paras = []
    for ln in lines:
        if ln['prose_letters'] == 0:
            continue
        if ln['complex'] or ln['prose_letters'] < 3:
            # word-level labels inside display math
            run = []
            runs = []
            for t in ln['toks']:
                if t['kind'] == 'word':
                    run.append(t)
                else:
                    if run:
                        runs.append(run)
                    run = []
            if run:
                runs.append(run)
            ctx = line_text(ln, ln['toks'])
            for run in runs:
                chars = [c for t in run for c in t['chars']]
                txt = ' '.join(tex_escape_text(t['text']) for t in run)
                regions.append(dict(
                    kind='word', page=pno, en=txt, ctx=ctx, raw=id_string(chars),
                    x0=run[0]['x0'], x1=run[-1]['x1'], top=ln['top'],
                    bottom=ln['bottom'], base=ln['base'], size=ln['size'],
                    pitch=1.25 * ln['size'], nlines=1,
                    color=collections.Counter(c['color'] for c in chars).most_common(1)[0][0],
                    alt=collections.Counter(c['color'] for c in chars).most_common(1)[0][0],
                    bold=sum(c['bold'] for c in chars) > len(chars) / 2, indent=0,
                    targets=[c['rbox'] for c in chars], inks=[c['bbox'] for c in chars], rules=[],
                    next_x=min([t['x0'] for t in ln['toks'] if t['x0'] > run[-1]['x1'] + 0.1] + [1e9]),
                    lines=[dict(x0=run[0]['x0'], x1=run[-1]['x1'], base=ln['base'],
                                top=ln['top'], bottom=ln['bottom'])]))
            continue
        kind, mtok = marker_of(ln, ln['toks'], images, small)
        ln['mx0'] = None
        if kind in ('glyph', 'label'):
            ln['toks'] = ln['toks'][1:]
            ln['mx0'] = mtok['x0']
            ln['x0'] = ln['toks'][0]['x0']
        ln['marker'] = kind
        paras.append(ln)
    return lines, regions, paras, rot, images, drawings


def group_paragraphs(paras, pitch_of, right_of):
    """Merge consecutive prose lines that continue the same paragraph."""
    paras = sorted(paras, key=lambda l: (l['base'], l['x0']))
    used = set()
    groups = []
    for i, ln in enumerate(paras):
        if i in used:
            continue
        grp = [ln]
        used.add(i)
        cur = ln
        while True:
            nxt = None
            for j in range(i + 1, len(paras)):
                if j in used:
                    continue
                c = paras[j]
                dy = c['base'] - cur['base']
                if dy <= 0.3 * cur['size']:
                    continue
                if dy > 2.2 * cur['size']:
                    break
                if abs(c['x0'] - cur['x0']) > 2.5 and not (
                        grp[0].get('mx0') is not None and abs(c['x0'] - grp[0]['mx0']) <= 2.5):
                    continue
                nxt = j
                break
            if nxt is None:
                break
            c = paras[nxt]
            S = cur['size']
            dy = c['base'] - cur['base']
            mode = pitch_of(S)
            ok = (abs(c['size'] - S) <= 0.1 * S and c['marker'] is None
                  and abs(dy - mode) <= max(1.2, 0.09 * S))
            # Light text sits on a dark bar (block title); never continue it
            # with dark text, which is on a different background.
            if ok and (luminance(cur) > 0.8) != (luminance(c) > 0.8):
                ok = False
            if ok:
                toks = c['toks']
                k = 0
                if toks[0]['kind'] == 'math':
                    while k + 1 < len(toks) and toks[k + 1]['kind'] == 'math':
                        k += 1
                fw = toks[k]['x1'] - toks[0]['x0']
                limit = right_of(cur)
                ok = cur['x1'] + 0.33 * S + fw > limit - 1.5
            if not ok:
                break
            grp.append(c)
            used.add(nxt)
            cur = c
        groups.append(grp)
    return groups


def dominant_color_rgb(line):
    cols = collections.Counter(c['color'] for c in line['chars'])
    c = cols.most_common(1)[0][0] if cols else 0
    return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255


def dominant(line, key):
    chars = [c for t in line['toks'] for c in t['chars']]
    if not chars:
        return None
    return collections.Counter(c[key] for c in chars).most_common(1)[0][0]


def luminance(line):
    c = dominant(line, 'color') or 0
    r, g, b = ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255
    return 0.299 * r + 0.587 * g + 0.114 * b


def region_style(chars):
    letters = [c for c in chars if c['c'].isalpha()] or chars
    color = collections.Counter(c['color'] for c in chars).most_common(1)[0][0]
    alt = collections.Counter(c['color'] for c in chars if c['color'] != color)
    altc = alt.most_common(1)[0][0] if alt else color
    alt_letters = [c for c in chars if c['color'] == altc and c['c'].isalpha()]
    alt_bold = sum(c['bold'] for c in alt_letters) > 0.6 * len(alt_letters) if alt_letters else False
    return dict(color=color, alt=altc, alt_bold=alt_bold,
                bold=sum(c['bold'] for c in letters) > 0.6 * len(letters),
                ital=sum(c['ital'] for c in letters) > 0.8 * len(letters))


def para_region(grp, pno):
    S = grp[0]['size']
    chars = [c for l in grp for t in l['toks'] for c in t['chars']]
    st = region_style(chars)
    texts = [line_text(l, l['toks'], st) for l in grp]
    en = ''
    for t in texts:
        if en.endswith('-') and t[:1].islower():
            en = en[:-1] + t
        else:
            en += (' ' if en else '') + t
    pitch = (grp[-1]['base'] - grp[0]['base']) / (len(grp) - 1) if len(grp) > 1 else 1.25 * S
    x0 = min(l['x0'] for l in grp)
    ink_bottom = max(c['bbox'][3] for c in chars if not c['c'].isspace())
    return dict(
        kind='para', page=pno, en=en, x0=x0, raw=id_string(chars),
        x1=max(l['x1'] for l in grp), top=min(l['top'] for l in grp),
        bottom=max(l['bottom'] for l in grp), base=grp[0]['base'], size=S,
        pitch=pitch, nlines=len(grp), indent=grp[0]['x0'] - x0, ink_bottom=ink_bottom,
        color=st['color'], alt=st['alt'], alt_bold=st['alt_bold'], bold=st['bold'], ital=st['ital'],
        targets=[c['rbox'] for c in chars], inks=[c['bbox'] for c in chars],
        rules=[r for l in grp for r in l['rules']],
        marker=grp[0].get('marker'),
        lines=[dict(x0=l['x0'], x1=l['x1'], base=l['base'], top=l['top'],
                    bottom=l['bottom'], en=t) for l, t in zip(grp, texts)])


def mark_centred(regs, drawings, W):
    """Single-line regions centred on the page or inside a filled box."""
    boxes = [d['rect'] for d in drawings if d.get('fill') is not None]

    def centre_of(r):
        mid = (r['x0'] + r['x1']) / 2
        tol = 1.5 + 0.012 * (r['x1'] - r['x0'])
        cands = [(0, W)]
        for b in boxes:
            if b[0] <= r['x0'] + 0.5 and b[2] >= r['x1'] - 0.5 and b[1] <= r['top'] + 2 and b[3] >= r['bottom'] - 2:
                cands.append((b[0], b[2]))
        for a, b in sorted(cands, key=lambda ab: ab[1] - ab[0]):
            if abs(mid - (a + b) / 2) < tol and r['x0'] - a > 6:
                return [a, b]
        return None
    paras = [r for r in regs if r['kind'] == 'para']
    cand = {id(r): centre_of(r) for r in paras}
    for r in paras:
        if r.get('marker') or cand[id(r)] is None:
            continue
        if r['nlines'] > 1 and any(abs((l['x0'] + l['x1']) / 2 - (r['lines'][0]['x0'] + r['lines'][0]['x1']) / 2) > 2 for l in r['lines']):
            continue
        # left-aligned text that only happens to sit in the middle
        if any(q is not r and abs(q['x0'] - r['x0']) < 1.0 and cand[id(q)] is None for q in paras):
            continue
        r['centred'] = True
        r['cbox'] = cand[id(r)]


def rot_regions(rot, pno):
    """Rotated labels (axis titles).  One region per PyMuPDF line."""
    groups = collections.defaultdict(list)
    for c in rot:
        key = (tuple(round(v, 2) for v in c['dir']), round(c['ox'] if abs(c['dir'][1]) > 0.5 else c['oy'], 0))
        groups[key].append(c)
    out = []
    for key, g in groups.items():
        dx, dy = key[0]
        if dy < 0:
            g.sort(key=lambda c: -c['oy'])
        else:
            g.sort(key=lambda c: c['oy'])
        txt = ''.join(LIG.get(c['c'], c['c']) for c in g).strip()
        raw = ''.join(LIG.get(idc(c), idc(c)) for c in g).strip()
        if sum(ch.isalpha() for ch in txt) < 3:
            continue
        x0 = min(c['bbox'][0] for c in g); x1 = max(c['bbox'][2] for c in g)
        y0 = min(c['bbox'][1] for c in g); y1 = max(c['bbox'][3] for c in g)
        out.append(dict(kind='rot', page=pno, en=tex_escape_text(txt), raw=raw, x0=x0, x1=x1,
                        top=y0, bottom=y1, base=y1, size=g[0]['size'],
                        angle=90 if dy < 0 else -90, nlines=1, pitch=g[0]['size'],
                        color=collections.Counter(c['color'] for c in g).most_common(1)[0][0],
                        bold=sum(c['bold'] for c in g) > len(g) / 2,
                        targets=[c['rbox'] for c in g], inks=[c['bbox'] for c in g], rules=[], lines=[]))
    return out


def cmd_extract(deck):
    cfg, src, out, work = deck_paths(deck)
    work.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(src)
    pages = []
    all_paras = []
    for pno in range(len(doc)):
        page = doc[pno]
        lines, words, paras, rot, images, drawings = extract_page(page, pno + 1)
        pages.append(dict(lines=lines, words=words, paras=paras, rot=rot,
                          images=images, drawings=drawings))
        all_paras.extend(paras)
    # deck-level statistics: typical line pitch per size, right text margin
    diffs = collections.defaultdict(list)
    for pg in pages:
        ps = sorted(pg['paras'], key=lambda l: (l['x0'], l['base']))
        for a, b in zip(ps, ps[1:]):
            if abs(a['x0'] - b['x0']) <= 2.5 and abs(a['size'] - b['size']) < 0.2:
                d = b['base'] - a['base']
                if 0.9 * a['size'] < d < 1.8 * a['size']:
                    diffs[round(a['size'], 1)].append(round(d, 1))
    pitch_mode = {s: collections.Counter(v).most_common(1)[0][0] for s, v in diffs.items()}

    def pitch_of(S):
        best = None
        for s, v in pitch_mode.items():
            if abs(s - S) < 0.25 and (best is None or len(diffs[s]) > len(diffs[best])):
                best = s
        return pitch_mode[best] if best is not None else 1.22 * S
    W = doc[0].rect.width
    xs = sorted(l['x1'] for l in all_paras)
    right_margin = xs[int(0.995 * (len(xs) - 1))] if xs else W - 10
    right_margin = min(max(right_margin, 0.8 * W), W - 2)

    legacy = CONFIG[deck].get('legacy_wrap', False)

    def right_of_factory(pg):
        def right_of(line):
            lim = right_margin
            if not legacy:
                same = [l['x1'] for l in pg['paras'] if abs(l['x0'] - line['x0']) < 3
                        and abs(l['size'] - line['size']) < 0.3]
                if same:
                    lim = min(lim, max(same) + 1.0)
            for other in pg['lines']:
                if other is line or other['x0'] <= line['x1'] + 0.5:
                    continue
                if other['bottom'] < line['top'] or other['top'] > line['bottom']:
                    continue
                lim = min(lim, other['x0'] - 3)
            for r in pg['images']:
                if r[0] > line['x1'] + 0.5 and not (r[3] < line['top'] or r[1] > line['bottom']):
                    lim = min(lim, r[0] - 3)
            return lim
        return right_of
    regions = []
    for pno, pg in enumerate(pages, start=1):
        groups = group_paragraphs(pg['paras'], pitch_of, right_of_factory(pg))
        regs = [para_region(g, pno) for g in groups] + pg['words'] + rot_regions(pg['rot'], pno)
        mark_centred(regs, pg['drawings'], W)
        for r in regs:
            r['old_id'] = region_id(r['en'])
            r['id'] = region_id(r['raw'])
        regs.sort(key=lambda r: (r['top'], r['x0']))
        regions.extend(regs)
    meta = dict(deck=deck, src=str(src.relative_to(REPO)), pages=len(doc),
                width=doc[0].rect.width, height=doc[0].rect.height,
                right_margin=right_margin, pitch_mode={str(k): v for k, v in pitch_mode.items()})
    # obstacles per page, used at build time
    obst = []
    for pno, pg in enumerate(pages, start=1):
        o = dict(page=pno, chars=[], images=pg['images'], drawings=[])
        for ln in pg['lines']:
            for c in ln['chars']:
                o['chars'].append([round(v, 2) for v in c['bbox']] + [round(c['oy'], 2), round(c['size'], 2)]
                                  + [round(v, 2) for v in c['rbox']])
        for c in pg['rot']:
            o['chars'].append([round(v, 2) for v in c['bbox']] + [round(c['oy'], 2), round(c['size'], 2)]
                              + [round(v, 2) for v in c['rbox']])
        for d in pg['drawings']:
            o['drawings'].append([round(v, 2) for v in d['rect']])
        obst.append(o)
    (work / 'regions.json').write_text(json.dumps(dict(meta=meta, regions=regions), ensure_ascii=False))
    (work / 'obstacles.json').write_text(json.dumps(obst))
    write_source(work, meta, regions)
    print(f'{deck}: {len(doc)} pages, {len(regions)} regions, '
          f'{len(set(r["id"] for r in regions))} unique texts, right margin {right_margin:.1f}')


def write_source(work, meta, regions):
    deck = meta['deck']
    mem, own = load_memory(deck)
    seen = {}
    out = [f'# {meta["src"]}  ({meta["pages"]} pages)',
           '# id | English (inline math is a rough reconstruction; check it)', '']
    for r in regions:
        if r['id'] in seen:
            continue
        seen[r['id']] = r['page']
    cur = None
    done = set()
    for r in regions:
        if r['id'] in done:
            continue
        done.add(r['id'])
        if r['page'] != cur:
            cur = r['page']
            out.append(f'@page {cur}')
        tag = ''
        if r['kind'] == 'word':
            tag = '  «' + r['ctx'] + '»'
        elif r['kind'] == 'rot':
            tag = '  «rotated»'
        nl = ''
        if r['kind'] == 'para' and r['nlines'] > 1:
            nl = f' [{r["nlines"]}L]'
        if r['id'] in mem and r['id'] not in own:
            out.append(f'#= {r["id"]} | {r["en"]}  ⇒ {mem[r["id"]]}')
            continue
        out.append(f'{r["id"]}{nl} | {r["en"]}{tag}')
    (work / 'source.txt').write_text('\n'.join(out) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------- build
def read_translation(path):
    tr = {}
    if not path.exists():
        return tr
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith('@page'):
            continue
        m = re.match(r'^(k[0-9a-f]{6})(?:\s*\[\d+L\])?\s*\|\s?(.*)$', line)
        if not m:
            raise SystemExit(f'bad translation line: {raw}')
        tr[m.group(1)] = m.group(2).strip()
    return tr


def load_memory(deck):
    """Translations of identical texts from every deck (own deck wins)."""
    mem = {}
    for other in CONFIG:
        if other == deck:
            continue
        f = deck_paths(other)[3] / 'translation.txt'
        if f.exists():
            for k, v in read_translation(f).items():
                mem.setdefault(k, v)
    own = read_translation(deck_paths(deck)[3] / 'translation.txt')
    mem.update(own)
    return mem, own


def hexcolor(c):
    return '%06X' % (c & 0xFFFFFF)


def inside(r, x, y):
    return r[0] - 0.01 <= x <= r[2] + 0.01 and r[1] - 0.01 <= y <= r[3] + 0.01


def redact_points(targets, others):
    """A tiny rectangle inside each target glyph that avoids other glyphs."""
    pts = []
    for t in targets:
        x0, y0, x1, y1 = t
        if x1 - x0 < 0.05 or y1 - y0 < 0.05:
            continue
        cands = [((x0 + x1) / 2, (y0 + y1) / 2)]
        for fx in (0.5, 0.3, 0.7, 0.2, 0.8):
            for fy in (0.5, 0.35, 0.65, 0.2, 0.8):
                cands.append((x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)))
        best = cands[0]
        for (x, y) in cands:
            if not any(inside(o, x, y) for o in others):
                best = (x, y)
                break
        pts.append(fitz.Rect(best[0] - 0.02, best[1] - 0.02, best[0] + 0.02, best[1] + 0.02))
        # MuPDF tests the glyph's tight outline, and short glyphs (old-style
        # figures, small caps) do not reach the middle of the font box.  A
        # second point in the x-height band just above the baseline catches them.
        lx, ly = (x0 + x1) / 2, y0 + 0.75 * (y1 - y0)
        if abs(ly - best[1]) > 0.3 and not any(inside(o, lx, ly) for o in others):
            pts.append(fitz.Rect(lx - 0.02, ly - 0.02, lx + 0.02, ly + 0.02))
    return pts


def cmd_build(deck, compile_tex=True):
    cfg, src, out, work = deck_paths(deck)
    data = json.loads((work / 'regions.json').read_text())
    meta, regions = data['meta'], data['regions']
    obst = {o['page']: o for o in json.loads((work / 'obstacles.json').read_text())}
    tr, own = load_memory(deck)
    missing = sorted({r['id'] for r in regions if r['id'] not in tr})
    if missing:
        (work / 'missing.txt').write_text('\n'.join(
            f'{r["id"]} | {r["en"]}' for r in {x['id']: x for x in regions if x['id'] in missing}.values()) + '\n')
        raise SystemExit(f'{deck}: {len(missing)} regions without translation (see missing.txt)')
    doc = fitz.open(src)
    W, H = meta['width'], meta['height']
    active = [r for r in regions if tr[r['id']] != '=']
    # ---- availability (width to the right, depth below the first baseline)
    by_page = collections.defaultdict(list)
    for r in regions:
        by_page[r['page']].append(r)
    for pno, regs in by_page.items():
        o = obst[pno]
        mine = {tuple(round(v, 2) for v in t) for r in regs if tr[r['id']] != '=' for t in r['targets']}
        free_chars = [c for c in o['chars'] if tuple(c[6:10]) not in mine]
        boxes = []
        for c in free_chars:
            x0, y0, x1, y1, oy, s = c[:6]
            boxes.append([x0, min(y0, oy - 0.7 * s), x1, max(y1, oy + 0.15 * s)])
        for r in regs:
            if tr[r['id']] not in ('=', '-', ''):
                pass
        rect_obst = [list(i) for i in o['images']]
        for r in regs:
            if r['kind'] == 'rot':
                continue
            S = r['size']
            fam_drawings = []
            for d in o['drawings']:
                # containers (backgrounds, blocks) do not limit the text
                if d[0] <= r['x0'] + 0.5 and d[2] >= r['x1'] - 0.5 and d[1] <= r['top'] + 0.5 and d[3] >= r['bottom'] - 0.5:
                    continue
                # rules inside this region are removed with it
                if any(abs(d[0] - q[0]) < 0.3 and abs(d[1] - q[1]) < 0.3 for q in r['rules']):
                    continue
                if (d[2] - d[0]) > 0.9 * W and (d[3] - d[1]) > 0.6 * H:
                    continue
                fam_drawings.append(d)
            others = boxes + rect_obst + fam_drawings
            # regions on the page that stay (or will hold Chinese text)
            for q in regs:
                if q is r or tr[q['id']] in ('-', ''):
                    continue
                if tr[q['id']] == '=':
                    continue  # their glyphs are already in boxes
                others.append([q['x0'], q['top'], q['x1'], q['bottom']])
            # right limit
            if r['kind'] == 'word':
                right = min(r.get('next_x', 1e9) - 1.0, W - 2)
            else:
                right = max(meta['right_margin'], r['x1'])
                if r['x1'] > right - 1:
                    right = min(W - 2, r['x1'] + 2)
            ytop, ybot = r['top'], r['bottom']
            for b in others:
                if b[3] < ytop + 0.5 or b[1] > ybot - 0.5:
                    continue
                if b[0] >= r['x1'] - 0.5:
                    right = min(right, b[0] - 2.0)
            r['right'] = max(right, r['x1'])
            # left limit (centred text)
            left = 2.0
            for b in others:
                if b[3] < ytop + 0.5 or b[1] > ybot - 0.5:
                    continue
                if b[2] <= r['x0'] + 0.5:
                    left = max(left, b[2] + 2.0)
            r['left'] = min(left, r['x0'])
            # bottom limit
            bottom = H - 1.0
            xa, xb = r['x0'], r['right']
            for b in others:
                if b[2] < xa + 0.5 or b[0] > xb - 0.5:
                    continue
                if b[1] >= r['bottom'] - 0.3 * S:
                    bottom = min(bottom, b[1])
            r['floor'] = bottom
    # ---- background: remove the English glyphs of translated regions
    layout = fitz.open(src)
    for pno in range(1, len(doc) + 1):
        regs = [r for r in by_page.get(pno, []) if tr[r['id']] != '=']
        if not regs:
            continue
        page = layout[pno - 1]
        o = obst[pno]
        target_set = {tuple(round(v, 2) for v in t) for r in regs for t in r['targets']}
        others = [c[6:10] for c in o['chars'] if tuple(c[6:10]) not in target_set]
        for r in regs:
            for rect in redact_points(r['targets'], others):
                page.add_redact_annot(rect, fill=None, cross_out=False)
            for q in r['rules']:
                page.add_redact_annot(fitz.Rect(q[0] - 0.4, q[1] - 0.4, q[2] + 0.4, q[3] + 0.4),
                                      fill=None, cross_out=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
    layout.set_metadata(dict(title='Background layout for ' + cfg['name'], author=AUTHOR,
                             creator=AUTHOR, producer=AUTHOR, subject='', keywords=''))
    layout.del_xml_metadata()
    layout.save(work / 'layout.pdf', garbage=0, deflate=True)
    # ---- TeX
    tex = [preamble(cfg, meta)]
    for pno in range(1, len(doc) + 1):
        tex.append(f'% page {pno}\n\\begin{{frame}}[plain]\n\\begin{{tikzpicture}}[remember picture,overlay]\n'
                   f'\\node[anchor=north west,inner sep=0pt,outer sep=0pt] at (current page.north west)'
                   f'{{\\includegraphics[page={pno},width=\\paperwidth,height=\\paperheight]{{layout.pdf}}}};\n')
        for r in by_page.get(pno, []):
            zh = tr[r['id']]
            if zh in ('=', '-', ''):
                continue
            tex.append(region_tex(r, zh))
        tex.append('\\end{tikzpicture}\n\\end{frame}\n')
    tex.append('\\end{document}\n')
    texname = cfg['name'] + '.tex'
    (work / texname).write_text(''.join(tex), encoding='utf-8')
    (work / 'regions_built.json').write_text(json.dumps(
        [dict(id=r['id'], page=r['page'], kind=r['kind'], box=[r['x0'], r['top'], r['x1'], r['bottom']],
              right=r.get('right'), floor=r.get('floor'), zh=tr[r['id']]) for r in regions],
        ensure_ascii=False))
    if compile_tex:
        compile_deck(deck)


def fmt_num(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')


TEXTSYM = {'∆': r'$\Delta$', '✗': r'$\times$', '✘': r'$\times$', '✓': r'$\checkmark$',
           '✔': r'$\checkmark$', '⇒': r'$\Rightarrow$', '→': r'$\to$', '≈': r'$\approx$',
           '≤': r'$\leq$', '≥': r'$\geq$', '•': r'\textbullet{}', '♠': r'$\spadesuit$',
           '∞': r'$\infty$', '±': r'$\pm$', '×': r'$\times$'}


def fix_text_symbols(zh):
    parts = zh.split('$')
    for k in range(0, len(parts), 2):
        parts[k] = ''.join(TEXTSYM.get(ch, ch) for ch in parts[k])
    return '$'.join(parts)


def region_tex(r, zh):
    S = r['size']
    zh = fix_text_symbols(zh)
    zh = zh.replace('⟪', r'\hl{').replace('⟫', '}')
    zh = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', zh)
    col = hexcolor(r['color'])
    style = (r'\bfseries' if r.get('bold') else '')
    if r['kind'] == 'rot':
        cx = (r['x0'] + r['x1']) / 2
        cy = (r['top'] + r['bottom']) / 2
        length = r['bottom'] - r['top']
        s = 0.9 * S
        return (f'\\CNR{{{fmt_num(cx)}}}{{{fmt_num(cy)}}}{{{fmt_num(length + 2)}}}{{{fmt_num(s)}}}'
                f'{{{r["angle"]}}}{{\\color[HTML]{{{col}}}{style}}}{{{zh}}}\n')
    parts = [p.strip() for p in zh.split('⏎')]
    if len(parts) > 1 and len(parts) == len(r['lines']):
        out = ''
        for ln, part in zip(r['lines'], parts):
            sub = dict(r)
            # each line starts at its own x0, so the first-line indent is already in it
            sub.update(x0=ln['x0'], x1=ln['x1'], top=ln['top'], bottom=ln['bottom'],
                       base=ln['base'], nlines=1, floor=ln['bottom'] + 0.3 * S + 1, indent=0)
            out += region_tex(sub, part)
        return out
    zh = zh.replace('⏎', r'\\')
    factor = 0.9 if S >= 13 else 0.87
    s = factor * S
    lead = r['pitch'] if r['nlines'] > 1 else 1.25 * S
    # how many lines are allowed: the original count plus one if there is room
    floor = r.get('floor', r['bottom'] + 0.3 * S)
    dmax = max(r['bottom'] - r['base'] + 0.05 * S + (r['nlines'] - 1) * 0, floor - r['base'] - 0.18 * S)
    dmax = min(dmax, (r['nlines']) * lead + 0.25 * S)
    dmax = max(dmax, (r['nlines'] - 1) * lead + 0.3 * S)
    if r.get('ink_bottom'):
        dmax = max(dmax, r['ink_bottom'] - r['base'] + 0.6)
    centred = False
    x0, w = r['x0'], r.get('right', r['x1'] + 2) - r['x0']
    if r['kind'] == 'para' and r['nlines'] == 1:
        mid = (r['x0'] + r['x1']) / 2
        left, right = r.get('left', 0), r.get('right', r['x1'])
        # centred titles: symmetric around the original centre
        if r.get('centred'):
            centred = True
    if r.get('centred'):
        mid = (r['x0'] + r['x1']) / 2
        half = min(mid - r.get('left', r['x0']), r.get('right', r['x1']) - mid)
        x0, w = mid - half, 2 * half
    align = r'\centering' if centred else r'\raggedright'
    hlfont = ''
    if r.get('bold') and not r.get('alt_bold', r.get('bold')):
        hlfont = r'\mdseries'
    elif not r.get('bold') and r.get('alt_bold'):
        hlfont = r'\bfseries'
    if r.get('indent', 0) > 1 and not centred:
        zh = r'\hspace*{%sbp}' % fmt_num(r['indent']) + zh
    minsize = 0.62 * s if r['kind'] == 'word' else 0.7 * s
    return (f'\\CN{{{fmt_num(x0)}}}{{{fmt_num(r["base"])}}}{{{fmt_num(w)}}}{{{fmt_num(dmax)}}}'
            f'{{{fmt_num(s)}}}{{{fmt_num(lead)}}}{{{fmt_num(minsize)}}}'
            f'{{\\color[HTML]{{{col}}}{style}{align}\\def\\hlcolor{{{hexcolor(r.get("alt", r["color"]))}}}'
            f'\\def\\hlfont{{{hlfont}}}}}{{{zh}}}\n')


def preamble(cfg, meta):
    W, H = meta['width'], meta['height']
    fam = cfg.get('family', 'sf')
    if fam == 'rm':
        cjk = r'''\setCJKmainfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf]
\setCJKsansfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf]
\usefonttheme{serif}'''
        family = r'\rmfamily'
    else:
        cjk = r'''\setCJKmainfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]
\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]'''
        family = r'\sffamily'
    mathfont = r'\usefonttheme{professionalfonts}' if cfg.get('math') == 'serif' else ''
    return rf'''% 逐页中文翻译（叠加法）：原稿每页作为矢量背景，英文文字移除后在原坐标排版中文。
% 由 tools/cn_slides/cnslides.py 生成；译文见同目录 translation.txt。
% 编译：latexmk -xelatex -interaction=nonstopmode -outdir=build {cfg["name"]}.tex
\documentclass[10pt]{{beamer}}
\geometry{{papersize={{{W:.3f}bp,{H:.3f}bp}}}}
\usepackage[UTF8,fontset=fandol]{{ctex}}
\usepackage{{amsmath,amssymb,graphicx,tikz}}
{mathfont}
{cjk}
\setbeamertemplate{{navigation symbols}}{{}}
\setbeamertemplate{{headline}}{{}}
\setbeamertemplate{{footline}}{{}}
\setbeamersize{{text margin left=0pt,text margin right=0pt}}
\hypersetup{{pdftitle={{{cfg["title"]}}},pdfauthor={{{AUTHOR}}},pdfcreator={{{AUTHOR}}},pdfproducer={{{AUTHOR}}},pdfsubject={{}},pdfkeywords={{}}}}
\makeatletter
\newsavebox\cn@box
\newdimen\cn@sz \newdimen\cn@ld
\def\hlfont{{}}
\def\hl#1{{\textcolor[HTML]{{\hlcolor}}{{\hlfont #1}}}}
% \CN{{x}}{{baseline y}}{{width}}{{max depth}}{{size}}{{leading}}{{min size}}{{format}}{{text}}  (bp, from top left)
\newcommand\CN[9]{{%
  \node[anchor=base west,inner sep=0pt,outer sep=0pt] at ([xshift=#1bp,yshift=-#2bp]current page.north west) {{%
    \cn@sz=#5bp\relax \cn@ld=#6bp\relax
    \def\cn@w{{#3bp}}\def\cn@fmt{{#8}}\def\cn@txt{{#9}}%
    \cn@make\cn@fit{{#4bp}}{{#7bp}}\usebox\cn@box}};}}
\def\cn@make{{\sbox\cn@box{{\parbox[t]{{\cn@w}}{{\normalfont{family}\fontsize{{\cn@sz}}{{\cn@ld}}\selectfont
  \setlength\parindent{{0pt}}\setlength\parskip{{0pt}}\leavevmode\cn@fmt\cn@txt}}}}}}
\def\cn@fit#1#2{{%
  \let\cn@next\relax
  \ifdim\dp\cn@box>#1\relax
    \ifdim\cn@sz>#2\relax
      \cn@sz=0.96\cn@sz \cn@ld=0.96\cn@ld \cn@make
      \def\cn@next{{\cn@fit{{#1}}{{#2}}}}%
    \else
      \typeout{{CN-OVERFLOW page=\thepage\space depth=\the\dp\cn@box\space limit=#1}}%
    \fi
  \fi
  \cn@next}}
% \CNR{{cx}}{{cy}}{{max length}}{{size}}{{angle}}{{format}}{{text}}  rotated labels
\newcommand\CNR[7]{{%
  \node[anchor=center,inner sep=0pt,outer sep=0pt,rotate=#5] at ([xshift=#1bp,yshift=-#2bp]current page.north west) {{%
    \cn@sz=#4bp\relax
    \def\cn@r{{\sbox\cn@box{{\normalfont{family}\fontsize{{\cn@sz}}{{\cn@sz}}\selectfont#6#7}}}}\cn@r
    \loop\ifdim\wd\cn@box>#3bp\relax \cn@sz=0.95\cn@sz \cn@r \repeat
    \usebox\cn@box}};}}
\makeatother
\begin{{document}}
'''


def compile_deck(deck):
    cfg, src, out, work = deck_paths(deck)
    texname = cfg['name'] + '.tex'
    (work / '.latexmkrc').write_text("$xdvipdfmx = 'xdvipdfmx -E -d 5 -o %D %O %S';\n")
    res = subprocess.run(['latexmk', '-xelatex', '-interaction=nonstopmode', '-halt-on-error',
                          '-outdir=build', texname], cwd=work, capture_output=True, text=True)
    log = (work / 'build' / (cfg['name'] + '.log'))
    logtxt = log.read_text(errors='replace') if log.exists() else ''
    if res.returncode != 0:
        tail = '\n'.join(logtxt.splitlines()[-40:])
        raise SystemExit(f'{deck}: XeLaTeX failed\n{tail}')
    over = re.findall(r'CN-OVERFLOW page=(\d+)', logtxt)
    miss = re.findall(r'Missing character: There is no (\S+)', logtxt)
    overfull = len(re.findall(r'^Overfull', logtxt, re.M))
    finalize(deck)
    print(f'{deck}: compiled; overflow regions on pages {sorted(set(map(int, over)))}; '
          f'missing glyphs {sorted(set(miss))}; overfull boxes {overfull}')


def finalize(deck):
    cfg, src, out, work = deck_paths(deck)
    built = fitz.open(work / 'build' / (cfg['name'] + '.pdf'))
    orig = fitz.open(src)
    assert len(built) == len(orig), (len(built), len(orig))
    for p, q in zip(built, orig):
        p.set_mediabox(q.rect)
    built.set_metadata(dict(title=cfg['title'], author=AUTHOR, creator=AUTHOR,
                            producer=AUTHOR, subject='', keywords=''))
    built.del_xml_metadata()
    built.save(out / (cfg['name'] + '.pdf'), garbage=4, deflate=True)


# --------------------------------------------------------------------- verify
def cmd_verify(deck, sheets=True):
    import numpy as np
    cfg, src, out, work = deck_paths(deck)
    data = json.loads((work / 'regions.json').read_text())
    regions = data['regions']
    tr, own = load_memory(deck)
    source = fitz.open(src)
    background = fitz.open(work / 'layout.pdf')
    final = fitz.open(out / (cfg['name'] + '.pdf'))
    assert len(final) == len(source)
    report = dict(pages=len(final))
    bad = []
    for n in range(len(source)):
        a = source[n].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        b = background[n].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        a1 = np.frombuffer(a.samples, np.uint8).reshape(a.height, a.width, 3).astype(int)
        b1 = np.frombuffer(b.samples, np.uint8).reshape(b.height, b.width, 3).astype(int)
        mask = np.zeros((a.height, a.width), dtype=bool)
        for r in regions:
            if r['page'] != n + 1 or tr.get(r['id']) == '=':
                continue
            boxes = [t for t in r['targets']] + r.get('inks', []) + r['rules']
            for x0, y0, x1, y1 in boxes:
                mask[max(0, int(y0 * 2) - 3):min(a.height, int(y1 * 2) + 4),
                     max(0, int(x0 * 2) - 3):min(a.width, int(x1 * 2) + 4)] = True
        outside = (np.max(np.abs(a1 - b1), axis=2) > 40) & ~mask
        k = int(outside.sum())
        if k > 6:
            bad.append((n + 1, k))
    report['pages_with_changes_outside_regions'] = bad
    meta = final.metadata
    report['metadata'] = {k: meta.get(k) for k in ('title', 'author', 'creator', 'producer')}
    assert all(AUTHOR == meta.get(k) for k in ('author', 'creator', 'producer'))
    if sheets:
        qa = work / 'qa'
        qa.mkdir(exist_ok=True)
        W, H = source[0].rect.width, source[0].rect.height
        scale = 520 / W
        per = 4
        for start in range(0, len(source), per):
            sheet = fitz.open()
            canvas = sheet.new_page(width=2 * 520 + 30, height=per * (H * scale + 22) + 10)
            canvas.draw_rect(canvas.rect, fill=(.85, .85, .85), color=None)
            for row, n in enumerate(range(start, min(start + per, len(source)))):
                y = 10 + row * (H * scale + 22)
                for col, d in enumerate([source, final]):
                    x = 10 + col * (520 + 10)
                    canvas.show_pdf_page(fitz.Rect(x, y + 14, x + 520, y + 14 + H * scale), d, n)
                    canvas.insert_text((x + 2, y + 10), f'{n + 1}/{len(source)} ' + ('EN' if col == 0 else 'CN'), fontsize=9)
            canvas.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False).save(qa / f'qa-{start + 1:03}.jpg', jpg_quality=88)
    (work / 'verify.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False))


def cmd_migrate(deck, old_regions):
    """Carry translations over to new region ids after an extractor change."""
    cfg, src, out, work = deck_paths(deck)
    new = json.loads((work / 'regions.json').read_text())['regions']
    old = json.loads(Path(old_regions).read_text())['regions']
    tr = read_translation(work / 'translation.txt')
    newids = {r['id'] for r in new}
    mapping = {}
    for r in new:
        if r['id'] in tr:
            continue
        best, score = None, 0.0
        for q in old:
            if q['page'] != r['page'] or q['id'] not in tr:
                continue
            ix = max(0, min(r['x1'], q['x1']) - max(r['x0'], q['x0']))
            iy = max(0, min(r['bottom'], q['bottom']) - max(r['top'], q['top']))
            inter = ix * iy
            union = (r['x1'] - r['x0']) * (r['bottom'] - r['top']) + (q['x1'] - q['x0']) * (q['bottom'] - q['top']) - inter
            sc = inter / union if union > 0 else 0
            if sc > score:
                best, score = q, sc
        if best is not None and score > 0.5:
            mapping[r['id']] = best['id']
    lines = (work / 'translation.txt').read_text(encoding='utf-8').splitlines()
    add = [f'{nid} | {tr[oid]}' for nid, oid in mapping.items()]
    (work / 'translation.txt').write_text('\n'.join(lines + (['# migrated'] + add if add else [])) + '\n', encoding='utf-8')
    print(f'{deck}: migrated {len(mapping)} translations')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['extract', 'build', 'verify', 'tex', 'migrate'])
    ap.add_argument('deck')
    ap.add_argument('--no-sheets', action='store_true')
    ap.add_argument('--old')
    a = ap.parse_args()
    if a.cmd == 'migrate':
        cmd_migrate(a.deck, a.old)
    elif a.cmd == 'extract':
        cmd_extract(a.deck)
    elif a.cmd == 'build':
        cmd_build(a.deck)
    elif a.cmd == 'tex':
        cmd_build(a.deck, compile_tex=False)
    elif a.cmd == 'verify':
        cmd_verify(a.deck, sheets=not a.no_sheets)


if __name__ == '__main__':
    main()
