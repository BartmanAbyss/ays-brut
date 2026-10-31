"""Where the bytes of intro.cmd go, measured through the real build.

Run:  python build/sizemap.py          (a few minutes: ~250 brotli runs, a dozen terser runs)

Two views, both on the shipped pipeline (prepare -> pack with the saved state -> brotli):

- REMOVAL: take a system out, rebuild, and the difference is what cutting it would save.
  Also with the packer's default state, as a check that the saved state is not flattering
  either side. Shader systems are removed as packer items (functions, consts); their call
  sites in other functions stay, so those numbers are slight underestimates. JS systems
  are cut from the stripped JS before terser, call sites included.
- SHARE: the shader in shipped order, item by item, each charged what brotli adds for it
  (a prefix at a time). Shares add up exactly to the shader's total, but depend on order:
  code that echoes something earlier comes cheap.

The JS has no share view; the part no removal accounts for is reported as its core.
The edits below anchor on the stripped JS (build/strip.js); when one stops matching, the
script stops and names it.
"""
import os, re, sys
import brotli

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import build as B   # noqa: E402
import pack         # noqa: E402

HEAD = 310   # the dropper header

# shader systems as packer items; Z0.. are the compute kernels (short_entries renames them in
# the order the JS lists them: see KERNELS)
KERNELS = 'simParticles waveUpdate clearFine scatterFine jfaCoarse resolveFine causticDecay photons causticBlur'
SHADER = {
    'photons + caustic map': 'causticDecay photons causticBlur causIdx causFetch causFetchF causticAt '
                             'CN CEXT CSCALE A_CAUST V_CAUSTF',
    'particle sim': 'simParticles',
    'spray grids (narrow band, far field)': 'clearFine scatterFine jfaCoarse resolveFine resolveCell fIdx '
                                            'cIdx c3 FHALF BAND QMAX INFQ FINE COARSE DOM_LO DOM_SZ FCELL '
                                            'CCELL sdBoxDom',
    'spray SDF in the render': 'sprayDist sdSeg fineAt',
    'waves + foam': 'waveUpdate sampleWave wIdx WMAX NWCELL WUNIT FUNIT',
    'glass volumes + overflow': 'glassUpdate',
    'bubbles': 'bubbleSDF',
    'bulk champagne SDF': 'bulkSDF liquidDist R_LIQ R_IN Y0 LMAX TS0 TS1 glassIdx glassOff',
    'coupe + tower': 'sdCoupe sdTower FOOT_R FLARE_H FLARE_R STEM_R GLASS_T RIM_R BOWL_D RIM_Y '
                     'BOWL_BOT SPH_R SPH_CY GH SP smin sdCyl',
    'bottle': 'BOT_H BODY_R NECK_R BOT_W rotX rotY bottleR sdBottleLocal sdBottle',
    'environment + bokeh': 'env bokeh',
    'render core (fs, march, normals, light path)': 'fs vs map mapN marchS planeT leg turn Turn mediumAt '
                                                    'iorOf sigmaOf reflColour tonemap tableShade lightDir '
                                                    'FAR SURF_EPS HIT_EPS',
    'plumbing (uniforms, buffers, hashes)': 'U Particle u parts fine fineF atom vecs A_GVOL A_WIMP '
                                            'V_GLASS V_WAVE pcg3d rnd3 PI VUNIT NG WN',
}


def cut(a, b, ins=''):
    return ('CUT', a, b, ins)


JS = {
    'audio, all of it (synth, sound, audio clock)': [
        ('    if (true) {\n      nShow = Math.max', '    if (false) {\n      nShow = Math.max'),
        cut('  const SCORE = [', '  // frame-count driven', ins=
            "  onclick = () => { onclick = null; canvas.width = screen.width; canvas.height = "
            "screen.height; document.body.requestFullscreen(); requestAnimationFrame(frame); };\n"
            "  document.body.append('click');\n")],
    '  audio: pad synth (the score is empty)': [
        cut('  const SCORE = [', '  // The whole soundtrack'),
        cut('    const r3 = rng(5);', '    const lb = bus = gain(1, out);')],
    '  audio: drips + splashes': [
        cut('    const EV = [];', '    // ── the liquid: the bubble model ──'),
        cut('    for (const [t, drip, nr, pan] of EV) {', '    // the pour: a dense population')],
    '  audio: cork pop': [cut('    for (let i = 0, ph = 0, tp = 0, lo = 0, i0 = ', '    for (const b of bx) {')],
    '  audio: reverbs': [cut('    for (const [from, len, mix] of [[pb, ', '    const b = await o.startRendering();')],
    '  audio: pour glugs': [cut('    const glugP = t => {', '    // fizz: CO2 bubbles')],
    '  audio: fizz': [cut('    for (let t = 0; t < SHOW_END; t -= Math.log(1 - r2()) / 300)',
                          '    // The cork, before any picture')],
    'lettering (stroke font, SVG, fades)': [
        ('PAGE', ''),
        cut('  // [from, to] for each line', '  function evalShow(t) {'),
        ('    drawText(showT);\n', ''),
        ('    canvas.nextSibling.style.opacity = fade;   // the words go dark with the picture\n', '')],
    'timeline keys (SHOW rows)': [
        ('RE', r'const SHOW = \[\[.*?\]\];',
         'const SHOW = [[0,0,0.8,0.44,0.26,1,0,1,45,1,118,0,1],[96,0,0.8,0.44,0.26,1,0,1,45,1,118,0,1]];')],
    'shot table (SHOT_V)': [
        cut('  const SHOT_V = [', '  // ── lettering ──', ins='  let shotVals = t => [0,0.5,120,0.17,0];\n')],
    'bottle wander': [('RE', r'    const wob = tt => \[.*?\];\n', '    const wob = tt => [0, 0];\n')],
}


# JS regions for the share view: each runs from its anchor's line to the next region's. A
# few small spans inside them are named on their own (JS_SPANS: from the start anchor's
# line up to, not including, the end anchor's).
JS_REGIONS = [
    ('constants', 'const FINE = 320'),
    ('device, canvas context, shader module', '(async function main() {'),
    ('buffers + bind group', '  const bufs = ['),
    ('pipelines', '  const P = {};'),
    ('resize / letterbox', '  let lastVW = -1'),
    ('clock state', '  const SIM_DT = 1 / 60;'),
    ('uniforms (writeUniforms)', '  function writeUniforms(time) {'),
    ('frame: sim stepping on the clock', '  const WG = (n, s) =>'),
    ('frame: dispatches + render pass', '    const enc = device.createCommandEncoder();'),
    ('frame: submit, loop', '    device.queue.submit('),
    ('timeline keys (SHOW rows)', '  const SHOW = [['),
    ('shot table (SHOT_V)', '  const SHOT_V = ['),
    ('lettering', '  // [from, to] for each line'),
    ('timeline evaluation (evalShow)', '  function evalShow(t) {'),
    ('audio: context, buses', '  const SCORE = ['),
    ('audio: pad synth', '    const r3 = rng(5);'),
    ('audio: drip/splash timing', '    const lb = bus = gain(1, out);'),
    ('audio: bubble model (bub, pop)', '    const r2 = rnd;'),
    ('audio: drips + splashes', '    for (const [t, drip, nr, pan] of EV) {'),
    ('audio: pour glugs', '    const glugP = t => {'),
    ('audio: fizz', '    for (let t = 0; t < SHOW_END; t -= Math.log(1 - r2()) / 300)'),
    ('audio: cork pop', '    for (let i = 0, ph = 0, tp = 0, lo = 0, i0 = '),
    ('audio: mix, reverbs, offline render', '    for (const b of bx) {'),
    ('start screen, audio start', '  let ac, tA;'),
]
JS_SPANS = [
    ('bottle wander', '    const wob = tt =>', '    canvas.nextSibling.style.opacity = fade;'),
    ('lettering', '    canvas.nextSibling.style.opacity = fade;', '    const V = shotVals(showT);'),
    ('lettering', '    drawText(showT);', '    const enc = device.createCommandEncoder();'),
    ('frame: show clock, locked to the audio', '    let nShow;', '    for (let i = 0; i < nShow; i++) {'),
]


def _vlq(s):
    """Decode one source-map segment."""
    B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    out, val, shift = [], 0, 0
    for ch in s:
        d = B64.index(ch)
        val += (d & 31) << shift
        if d & 32:
            shift += 5
        else:
            out.append(-(val >> 1) if val & 1 else val >> 1)
            val, shift = 0, 0
    return out


def js_line_map(js, jmin, ren):
    """Terser again, with a source map: for each character of the minified JS, the line of
    the stripped JS it came from. js is the stripped JS BEFORE the kernels were renamed
    (build/strip.js): the build minifies first and renames after, and terser's output
    depends on the names. The same renames are applied here, carrying the map along.
    Checks the result is the shipped JS."""
    import json
    tmp, out = os.path.join(ROOT, '_sm_in.js'), os.path.join(ROOT, '_sm_out.js')
    try:
        open(tmp, 'wb').write(js.encode())
        B.run_tool('terser', [tmp, '--compress', '--mangle', '--module',
                              '--source-map', 'url=_sm_out.js.map', '-o', out])
        code = open(out, encoding='utf-8').read()
        smap = json.load(open(out + '.map', encoding='utf-8'))
    finally:
        for f in (tmp, out, out + '.map'):
            if os.path.exists(f):
                os.remove(f)
    code = re.sub(r'\n?//# sourceMappingURL=\S*\s*$', '', code)
    starts = [0]
    for ln in code.split('\n'):
        starts.append(starts[-1] + len(ln) + 1)
    owner = [None] * len(code)
    segs = []
    src_line = 0
    for gl, line in enumerate(smap['mappings'].split(';')):
        col = 0
        for seg in filter(None, line.split(',')):
            v = _vlq(seg)
            col += v[0]
            if len(v) >= 4:
                src_line += v[2]
                segs.append((starts[gl] + col, src_line))
    segs.sort()
    for (a, ln), nxt in zip(segs, segs[1:] + [(len(code), None)]):
        for i in range(a, min(nxt[0], len(code))):
            owner[i] = ln
    # the kernel renames, as short_entries does them; a new name takes the old one's line
    for old, new in ren.items():
        out_c, out_o, last = [], [], 0
        for m in re.finditer(r'\b%s\b' % old, code):
            out_c.append(code[last:m.start()]); out_o.extend(owner[last:m.start()])
            out_c.append(new); out_o.extend([owner[m.start()]] * len(new))
            last = m.end()
        out_c.append(code[last:]); out_o.extend(owner[last:])
        code, owner = ''.join(out_c), out_o
    assert code.strip() == jmin.strip(), 'sizemap: terser with a source map built different JS'
    return code, owner


def js_regions(js):
    """Source line -> region name."""
    lines = js.split('\n')
    def line_of(anchor):
        assert js.count(anchor) == 1, 'sizemap: JS anchor gone: %r' % anchor[:60]
        return js[:js.index(anchor)].count('\n')
    reg = ['page and glue'] * len(lines)
    marks = sorted((line_of(a), n) for n, a in JS_REGIONS)
    for (l0, n), nxt in zip(marks, marks[1:] + [(len(lines), None)]):
        for i in range(l0, nxt[0]):
            reg[i] = n
    for n, a, b in JS_SPANS:
        for i in range(line_of(a), line_of(b)):
            reg[i] = n
    return reg


def br(b):
    return len(brotli.compress(b, quality=11, lgwin=24))


def edit_js(js, edits):
    for e in edits:
        if e[0] == 'PAGE':
            continue
        if e[0] == 'CUT':
            _, a, b, ins = e
            assert js.count(a) == 1, 'sizemap: JS anchor gone: %r' % a[:60]
            i = js.index(a)
            js = js[:i] + ins + js[js.index(b, i):]
        elif e[0] == 'RE':
            js, n = re.subn(e[1], lambda m: e[2], js, count=1, flags=re.S)
            assert n == 1, 'sizemap: JS pattern gone: %r' % e[1][:60]
        else:
            assert js.count(e[0]) == 1, 'sizemap: JS anchor gone: %r' % e[0][:60]
            js = js.replace(e[0], e[1])
    return js


def main():
    wgsl, js, jmin, page = B.prepare()
    saved = pack.load_state()
    # the source names of the renamed kernels, from the JS's own pipeline list
    zs = re.search(r"for \(const n of \(('[^)]*)\)\.split", js).group(1)
    zs = re.findall(r'Z\d+', zs)
    ren = dict(zip(KERNELS.split(), zs))
    prot = B._protected(wgsl, js)
    prog = pack.Program(wgsl, prot, B.WGSL_KEEP)
    name = {k: k.split(':', 1)[1] for k in prog.keys}

    def render(keep, state):
        items = [' '.join(it) for it, k in zip(prog.items, prog.keys) if keep(k)]
        p = pack.Program('\n'.join(items), prot, B.WGSL_KEEP)
        return p.render(p.adopt(saved) if state == 'saved' else p.default_state())

    def size(w, j, pg=page):
        return HEAD + br(pack.assemble(w, j, page=pg))

    full = {s: render(lambda k: True, s) for s in ('saved', 'default')}
    base = {s: size(full[s], jmin) for s in full}
    shader_total = base['saved'] - size('', jmin)
    js_total = base['saved'] - HEAD - shader_total
    print('intro.cmd %d (packer default state: %d) = dropper %d + shader %d + JS and page %d'
          % (base['saved'], base['default'], HEAD, shader_total, js_total))

    # SHARE: prefix by prefix in the shipped order
    st = prog.adopt(saved)
    sysof = {}
    for s, names in SHADER.items():
        for n in names.split():
            sysof[ren.get(n, n)] = s
    share, item_share, prev = {}, {}, size('', jmin)
    for n in range(1, len(st['items']) + 1):
        part = prog.render(dict(st, items=st['items'][:n]))
        cur = size(part, jmin)
        k = st['items'][n - 1]
        s = sysof.get(name[k], 'other')
        share[s] = share.get(s, 0) + cur - prev
        item_share[k] = cur - prev
        prev = cur

    print('\nSHADER %d   %-46s %6s %6s %8s' % (shader_total, '', 'share', 'cut', 'cut/def'))
    for s, names in sorted(SHADER.items(), key=lambda x: -share.get(x[0], 0)):
        gone = {ren.get(n, n) for n in names.split()}
        cut_ = {t: base[t] - size(render(lambda k: name[k] not in gone, t), jmin) for t in base}
        print('       %-46s %6d %6d %8d' % (s, share.get(s, 0), cut_['saved'], cut_['default']))
    if 'other' in share:
        print('       %-46s %6d' % ('(items in no system)', share['other']))
    for s in ('render core (fs, march, normals, light path)', 'plumbing (uniforms, buffers, hashes)'):
        print('\n  %s, per item (share):' % s)
        back = {v: k for k, v in ren.items()}
        rows = sorted(((v, name[k]) for k, v in item_share.items() if sysof.get(name[k]) == s), reverse=True)
        print('   ' + ', '.join('%s %d' % (back.get(n, n), v) for v, n in rows))

    # SHARE for the JS: the minified JS charged region by region (terser's source map says
    # which source line each character came from), a prefix at a time
    pre = B.read(os.path.join(ROOT, 'strip.js'))   # prepare() wrote it: the JS before renaming
    code, owner = js_line_map(pre, jmin, ren)
    reg = js_regions(pre)
    ps = pack.assemble(full['saved'], jmin, page=page).decode()
    v = pack._shader_var[jmin]
    li = jmin.index(pack.SHADER_LOOKUP) + len(pack.SHADER_LOOKUP)
    st0 = ps.index('<script>') + len('<script>')
    def off(i):   # end of jmin char i in the payload (the shader lookup became a short name)
        return st0 + i + 1 + (len(v) - len(pack.SHADER_LOOKUP) if i >= li else 0)
    names = [reg[o] if o is not None else 'page and glue' for o in owner]
    # the page: the canvas tag, then the lettering's overlay, then the script
    cv = ps.index('>') + 1
    jshare = {'page and glue': br(ps[:cv].encode())}
    jshare['lettering'] = br(ps[:st0].encode()) - jshare['page and glue']
    prev, i = br(ps[:st0].encode()), 0
    while i < len(names):
        j = i
        while j < len(names) and names[j] == names[i]:
            j += 1
        cur = br(ps[:off(j - 1)].encode())
        jshare[names[i]] = jshare.get(names[i], 0) + cur - prev
        prev, i = cur, j
    jshare['page and glue'] += js_total - sum(jshare.values())
    print('\nJS AND PAGE %d, share by region (exact sum, in shipped order):' % js_total)
    for n, c in sorted(jshare.items(), key=lambda x: -x[1]):
        print('       %-46s %6d' % (n, c))

    print('\nJS AND PAGE %d   %-38s %6s %8s' % (js_total, '', 'cut', 'cut/def'))
    top = 0
    for s, edits in JS.items():
        jm, _ = B.minify_js(edit_js(js, edits))
        pg = '' if ('PAGE', '') in edits else page
        c = {t: base[t] - size(full[t], jm, pg) for t in base}
        if not s.startswith(' '):
            top += c['saved']
        print('       %-46s %6d %8d' % (s, c['saved'], c['default']))
    print('       %-46s %6d' % ('core (setup, frame loop, clock, uniforms, page)', js_total - top))


if __name__ == '__main__':
    main()
