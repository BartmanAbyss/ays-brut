"""Josefin Sans SemiBold (600), cut from the variable font in dev/fonts: the outlines and
advance widths of the glyphs the intro's text uses, as SVG paths - the reference the
intro's stroke font is drawn against.

    python dev/tools/glyphs.py            # writes dev/tools/glyphs_ref.json
"""
import io
import json
import os
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, '..', 'fonts', 'JosefinSans[wght].ttf')
CHARS = 'ABCEFGHILMNOPRSTUY026'

f = instancer.instantiateVariableFont(TTFont(FONT), {'wght': 600})
cmap = f.getBestCmap()
gs = f.getGlyphSet()
out = {'upem': f['head'].unitsPerEm, 'capHeight': f['OS/2'].sCapHeight, 'glyphs': {}}
for ch in CHARS + ' ':
    name = cmap[ord(ch)]
    g = gs[name]
    pen = SVGPathPen(gs)
    g.draw(pen)
    bp = BoundsPen(gs)
    g.draw(bp)
    out['glyphs'][ch] = {'adv': g.width, 'bounds': bp.bounds, 'd': pen.getCommands()}

# the stem: the H's left vertical, from its outline's x extremes at mid height
io.open(os.path.join(HERE, 'glyphs_ref.json'), 'w', encoding='utf-8').write(json.dumps(out, indent=1))
for ch in CHARS + ' ':
    g = out['glyphs'][ch]
    print(ch, 'adv', g['adv'], 'bounds', g['bounds'])
