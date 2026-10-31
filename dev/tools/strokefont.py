"""The intro's lettering: Josefin Sans SemiBold's capitals redrawn as strokes.

Josefin is geometric and monoline, so each capital is a pen path - a few lines, ellipse
arcs and curves - drawn with a pen as wide as the font's stem (116 of 1000 units), butt
ends, mitred corners. The browser renders it as an SVG path: no font, no glyph code.

    python dev/tools/strokefont.py    # writes dev/tools/strokefont.html (each glyph over
                                      # the real outline, to compare) and the TEXT block
                                      # in dev/champagne.html

The intro draws them with the browser's default miter limit (4), which mitres any corner
wider than ~29 degrees; the sharpest here is M's at 35. A new letter with a sharper corner
gets a flat tip, unless the overlay gets its stroke-miterlimit back.

The glyphs are defined below in font units, y up, baseline 0, cap height 728 - the
coordinates are read off the outlines in glyphs_ref.json (python dev/tools/glyphs.py).
Josefin Sans is under the SIL OFL (dev/fonts/OFL.txt); these are our own strokes after
its shapes, so they do not carry its Reserved Font Name.
"""
import io
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'champagne.html')
REF = os.path.join(HERE, 'glyphs_ref.json')

CAP = 728
PEN = 116            # the stem width
# The lettering as groups of lines, TEXT[0], TEXT[1], ...: each line centred, the group's
# lines stacked LEAD apart round the middle of the screen. The position is baked into the
# paths, so the intro places nothing; the harness says when each group shows (TEXT_CUES).
GROUPS = [['MAISON', 'ABYSSE', 'MILLESIME', '2026'],
          ['CHAMPAGNE', 'POUR', 'LES', 'MASSES']]
LINES = [t for g in GROUPS for t in g]
# tracking: extra space between letters, in font units - wide-set capitals read as luxury
TRACK = 150
# The output grid. At GRID 1 a path unit is 12 font units in a 1600 x 900 overlay, caps ~61
# of 900 - about 7% of the screen's height. GRID 3 draws the same size on a grid three
# times coarser (36 font units, ~3.6 px at 1080p): most coordinates become one digit, 33
# bytes less, and only the 2 needed help (FINE). Arcs survive it whole (radii()). The
# harness's overlay must use VIEWBOX and PEN_W; writing the block checks it does.
GRID = 3
Q = 12.0 * GRID
LEAD = round(110 / GRID)                       # line spacing, in path units
VIEWBOX = '%d %d %d %d' % (round(-800 / GRID), round(-450 / GRID), round(1600 / GRID), round(900 / GRID))
PEN_W = '%g' % round(PEN / Q, 2)               # the pen, in path units

# ── the glyphs ──────────────────────────────────────────────────────────────────────
# a glyph: (advance, [stroke, ...]); a stroke: list of nodes, optionally ending in 'z':
#   (x, y)                              - a point; the first starts the stroke
#   ('arc', cx, cy, rx, ry, a0, a1)     - along the ellipse from angle a0 to a1 (degrees,
#                                         counter-clockwise, y up); joined to what came before
#   ('q', cx, cy, x, y)                 - a quadratic curve to (x, y)
def arc(cx, cy, rx, ry, a0, a1):
    return ('arc', cx, cy, rx, ry, a0, a1)


G = {
    ' ': (320, []),
    'A': (699, [[(81, 0), (345, 615), (608, 0)], [(176, 221), (518, 221)]]),
    'B': (630, [[(158, 54), (158, 672), (324, 672), arc(324, 517, 155, 155, 90, -90),
                 (360, 362), arc(360, 208, 154, 154, 90, -90), (158, 54), 'z'],
                [(158, 362), (360, 362)]]),
    'C': (695, [[arc(427, 364, 314, 314, 55, 306)]]),
    'E': (658, [[(583, 672), (158, 672), (158, 56), (597, 56)], [(158, 366), (543, 366)]]),
    'F': (593, [[(542, 672), (158, 672), (158, 0)], [(158, 356), (500, 356)]]),
    'G': (756, [[arc(427, 364, 314, 314, 53, 308), (620, 310), (425, 310)]]),
    'H': (792, [[(158, 0), (158, 728)], [(633, 0), (633, 728)], [(158, 365), (633, 365)]]),
    'I': (317, [[(158, 0), (158, 728)]]),
    'L': (630, [[(158, 728), (158, 56), (575, 56)]]),
    'U': (741, [[(147, 728), (147, 262), arc(371, 262, 224, 214, 180, 360), (596, 728)]]),
    'M': (935, [[(158, 0), (158, 577), (467, 142), (777, 577), (777, 0)]]),
    'N': (844, [[(159, 0), (159, 618), (685, 105), (685, 728)]]),
    'O': (855, [[arc(427, 364, 314, 314, 0, 180), arc(427, 364, 314, 314, 180, 360), 'z']]),
    'P': (611, [[(158, 0), (158, 672), (331, 672), arc(331, 490, 182, 182, 90, -90), (158, 309)]]),
    'R': (670, [[(158, 0), (158, 672), (331, 672), arc(331, 490, 182, 182, 90, -90), (158, 309)],
                [(378, 309), (566, 0)]]),
    'S': (582, [[(504, 624), ('q', 420, 680, 300, 680), ('q', 138, 680, 138, 535),
                 ('q', 138, 430, 305, 360), ('q', 468, 290, 468, 200),
                 ('q', 468, 43, 286, 43), ('q', 160, 43, 68, 114)]]),
    'T': (583, [[(48, 672), (535, 672)], [(289, 672), (289, 0)]]),
    'Y': (704, [[(95, 728), (350, 290), (610, 728)], [(350, 290), (350, 0)]]),
    '0': (625, [[arc(312, 332, 217, 278, 0, 180), arc(312, 332, 217, 278, 180, 360), 'z']]),
    '2': (560, [[arc(268, 450, 171, 162, 231, -5), ('q', 416, 260, 150, 56), (514, 56)]]),
    '6': (551, [[arc(275, 212, 180, 167, 0, 180), arc(275, 212, 180, 167, 180, 360), 'z'],
                [(98, 250), ('q', 130, 470, 370, 628)]]),
}


# ── geometry → path ─────────────────────────────────────────────────────────────────
def arc_pts(cx, cy, rx, ry, a0, a1):
    p = lambda a: (cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
    return p(a0), p(a1)


def stroke_segments(st):
    """[('M'|'L'|'Q'|'A', ...)] in font units, y up; arcs split to at most 180 degrees"""
    out, cur = [], None
    for n in st:
        if n == 'z':
            out.append(('Z',))
            continue
        if isinstance(n, tuple) and n and n[0] == 'arc':
            _, cx, cy, rx, ry, a0, a1 = n
            # Half-turns are one arc: a 180-degree arc between opposite points is still one
            # well-defined curve (the sweep flag picks the side), and an O drawn as two arcs
            # instead of four is ~30 characters shorter. Only past 180 must it split, since
            # every arc here is written with the large-arc flag 0.
            parts = max(1, int(math.ceil(abs(a1 - a0) / 180.0 - 1e-9)))
            for k in range(parts):
                b0 = a0 + (a1 - a0) * k / parts
                b1 = a0 + (a1 - a0) * (k + 1) / parts
                s, e = arc_pts(cx, cy, rx, ry, b0, b1)
                if cur is None:
                    out.append(('M',) + s)
                elif math.dist(cur, s) > 0.5:
                    out.append(('L',) + s)
                # y up: counter-clockwise (a1 > a0) is the positive sweep
                out.append(('A', rx, ry, 1 if b1 > b0 else 0) + e + (abs(b1 - b0),))
                cur = e
        elif isinstance(n, tuple) and n and n[0] == 'q':
            _, qx, qy, x, y = n
            out.append(('Q', qx, qy, x, y))
            cur = (x, y)
        else:
            out.append(('M' if cur is None else 'L',) + n)
            cur = n
    return out


# Glyphs whose own coordinates keep half grid steps: the 2's hook is a short arc and a
# curve, which a coarse grid bends out of shape; anything drawn as straight lines and
# half-turns survives whole steps.
FINE = {'2': 2}


def num(v):
    s = '%g' % round(v, 2)
    return s.replace('0.', '.') if s.startswith(('0.', '-0.')) else s


def dec(v):
    """A radius to one decimal, as short as it writes: 6.5, 7, .8"""
    s = '%g' % round(v, 1)
    return s[1:] if s.startswith('0.') else s


def radii(rx, ry, span, q):
    """An arc's radii as written. A half-turn runs between opposite points of its ellipse,
    and SVG scales radii too small to reach both endpoints up until they just do, keeping
    their ratio - so a half-turn needs only the ratio, written smaller than any real radius
    here: `1 1` for a circle. That is shorter, and exact on any grid, where radii rounded on
    their own made a coarse grid's O pointed. Other arcs (C, G, 2) keep their size, to a
    tenth: whole steps measured 12 bytes worse."""
    if abs(span - 180) < 1e-6:
        return '1 1' if rx == ry else '%s 1' % dec(rx / ry)
    return '%s %s' % (dec(rx / q), dec(ry / q))


def path_for(text, q=Q, oy=0):
    """One relative SVG path for a line, centred on x = 0 with the caps centred on y = oy.
    Coordinates are rounded as ABSOLUTE positions and then differenced, so rounding
    never drifts along a line."""
    width = sum(G[c][0] for c in text) + TRACK * (len(text) - 1)
    x0 = -width / 2
    d, last = [], (0, 0)
    # to output units, y down. Each glyph's origin snaps to the grid FIRST and its own
    # coordinates round on their own, so every copy of a letter is the same string - which
    # brotli then stores once. Rounding the sum instead made each copy differ by a unit
    # here and there, and the three lines cost ~700 bytes instead of ~350.
    ox, f = 0, 1
    T = lambda x, y: (ox + round(x / q * f) / f, round(-(y - CAP / 2) / q * f) / f + oy)
    for c in text:
        adv, strokes = G[c]
        ox, f = round(x0 / q), FINE.get(c, 1)
        for st in strokes:
            start = None
            for seg in stroke_segments(st):
                op = seg[0]
                if op == 'Z':
                    d.append('z')
                    last = start
                    continue
                if op == 'A':
                    _, rx, ry, sweep, ex, ey, span = seg
                    e = T(ex, ey)
                    # y flips, so the sweep flips
                    d.append('a%s 0 0 %d %s %s' % (radii(rx, ry, span, q), 1 - sweep,
                                                    num(e[0] - last[0]), num(e[1] - last[1])))
                    last = e
                elif op == 'Q':
                    _, qx, qy, ex, ey = seg
                    c1, e = T(qx, qy), T(ex, ey)
                    d.append('q%s %s %s %s' % (num(c1[0] - last[0]), num(c1[1] - last[1]),
                                              num(e[0] - last[0]), num(e[1] - last[1])))
                    last = e
                else:
                    p = T(seg[1], seg[2])
                    dx, dy = p[0] - last[0], p[1] - last[1]
                    if op == 'M':
                        d.append('m%s %s' % (num(dx), num(dy)))
                        start = p
                    elif dx == 0:
                        d.append('v%s' % num(dy))
                    elif dy == 0:
                        d.append('h%s' % num(dx))
                    else:
                        d.append('l%s %s' % (num(dx), num(dy)))
                    last = p
        x0 += adv + TRACK
    s = ''.join(d)
    s = re.sub(r' -', '-', s)       # SVG needs no space before a minus
    return s


# ── the comparison page ─────────────────────────────────────────────────────────────
def compare_page(ref):
    cells = []
    for c in sorted(G):
        if c == ' ':
            continue
        adv = G[c][0]
        refd = ref['glyphs'][c]['d']
        mine = path_for(c, q=1.0)
        cells.append(
            '<figure><svg viewBox="%d %d %d %d"><g transform="translate(%g 0)">'
            '<path d="%s" transform="matrix(1 0 0 -1 %g %g)" fill="#c33" opacity=".55"/></g>'
            '<path d="%s" fill="none" stroke="#fff" stroke-width="%d" stroke-miterlimit="9" opacity=".75"/>'
            '</svg><figcaption>%s</figcaption></figure>'
            % (-adv / 2 - 40, -CAP / 2 - 80, adv + 80, CAP + 160, 0, refd, -adv / 2, CAP / 2, mine, PEN, c))
    lines = ''.join(
        '<svg class="line" viewBox="-800 -100 1600 200"><path d="%s" fill="none" stroke="#fff" '
        'stroke-width="%g" stroke-miterlimit="9"/></svg>' % (path_for(t), PEN / Q) for t in LINES)
    return ('<!doctype html><meta charset="utf-8"><title>Stroke font</title><style>'
            'body{background:#111;color:#aaa;font:12px monospace;margin:16px}'
            'figure{display:inline-block;margin:6px;text-align:center}'
            'figure svg{height:220px;background:#1c1c22}'
            '.line{display:block;width:100%;max-width:1400px;background:#000;margin:8px 0}'
            '</style><p>red: Josefin Sans SemiBold, white: the strokes</p>' + ''.join(cells) +
            '<p>the three lines as the intro draws them</p>' + lines)


def group_paths():
    return [[path_for(t, oy=round((k - (len(g) - 1) / 2) * LEAD)) for k, t in enumerate(g)]
            for g in GROUPS]


def with_block(src, groups):
    """src with the TEXT block replaced. Pure: the caller reads and writes - this once
    emptied the harness, because `open(SRC, 'w').write(f())` truncates the file BEFORE
    f() reads it, and f() then failed on the empty text."""
    a, b = src.index('// TEXT:BEGIN'), src.index('// TEXT:END')
    a = src.index('\n', a) + 1
    b = src.rindex('\n', 0, b) + 1
    body = ('  const TEXT = [\n' + ''.join('    [\n' + ''.join("      '%s',\n" % p for p in g) + '    ],\n'
                                       for g in groups) + '  ];\n')
    return src[:a] + body + src[b:]


if __name__ == '__main__':
    ref = json.load(io.open(REF, encoding='utf-8'))
    io.open(os.path.join(HERE, 'strokefont.html'), 'w', encoding='utf-8').write(compare_page(ref))
    groups = group_paths()
    for t, p in zip(LINES, [p for g in groups for p in g]):
        print('%-26s %4d chars' % (t, len(p)))
    with io.open(SRC, encoding='utf-8', newline='') as f:
        src = f.read()
    for attr in ('viewBox="%s"' % VIEWBOX, 'stroke-width="%s"' % PEN_W):
        assert attr in src, 'the overlay in dev/champagne.html must have %s for GRID %d' % (attr, GRID)
    if '// TEXT:BEGIN' in src and '// TEXT:END' in src:
        out = with_block(src, groups)
        assert len(out) > len(src) // 2, 'refusing to write: the result lost half the file'
        tmp = SRC + '.writing'
        with io.open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
        os.replace(tmp, SRC)          # all or nothing
        print('wrote the TEXT block into dev/champagne.html')
    else:
        print('no TEXT block in dev/champagne.html yet - nothing written there')
