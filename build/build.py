"""Build the release intro from the dev harness.

One source of truth: dev/champagne.html. This strips the harness, inlines the control
values the panel used to supply, minifies, and packs the result into a self-extracting
HTML that inflates itself with DecompressionStream.

Run:  python build/build.py
Out:  build/intro.html   (runnable)   and a size report on stdout.
"""
import io, math, os, re, struct, subprocess, sys, zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, '..', 'dev', 'champagne.html')
OUT = os.path.join(ROOT, 'intro.html')

# ── release values for everything the debug panel used to own ────────────────────
# cfg.* defaults, except where the release deliberately differs (show on, paused off).
CFG = {
    't': 'null', 'w': '0', 'h': '0', 'view': '0', 'still': 'false', 'selftest': 'false',
    'steps': '160', 'npart': '65536', 'spawnMod': '1600', 'pvol': '2e-8', 'warm': '400',
    'single': 'false', 'noliq': 'false', 'bub': 'true', 'expo': '1.45', 'wav': 'true',
    'pfield': 'true', 'bounces': '10', 'refl': '1.0', 'envg': 'false', 'fillQ': 'null',
    'nphoton': '65536', 'cgain': '0.05', 'paused': 'false', 'det': 'false',
    'show': 'true', 'showt': '0',
}
# ui.* comes from the panel's own SPEC defaults, so the two cannot drift. These two are
# the release's choices rather than the panel's.
UI_OVERRIDE = {'show': 'true', 'spin': 'false', 'view': '0'}


def read(path):
    return io.open(path, 'rb').read().decode('utf-8').replace('\r\n', '\n')


def spec_defaults(js):
    """Pull the panel's default values straight out of SPEC so they cannot drift."""
    m = re.search(r'const SPEC = \[(.*?)\n  \];', js, re.S)
    assert m, 'SPEC not found'
    out = {}
    for name, kind, rest in re.findall(r"\['(\w+)',\s*'(\w+)',\s*([^\]]+)\]", m.group(1)):
        val = rest.split(',')[0].strip()
        out[name] = 'true' if val == 'true' else 'false' if val == 'false' else val
    return out


def cut_dev(text):
    """Remove //#D{ ... //#D} regions."""
    out, depth = [], 0
    for line in text.split('\n'):
        t = line.strip()
        if t == '//#D{':
            depth += 1
            continue
        if t == '//#D}':
            depth -= 1
            assert depth >= 0, 'unbalanced //#D}'
            continue
        if depth == 0:
            out.append(line)
    assert depth == 0, 'unbalanced //#D{'
    return '\n'.join(out)


# Lines where harness and release code share a statement, so the filter below cannot
# just drop them. Order matters: these run first.
REWRITES = [
    ("    requiredFeatures: hasTS ? ['timestamp-query'] : [],", ''),
    ('    if (hasTS) desc.timestampWrites = ts(3);', ''),
    ('    frameNo++; simStep += simSteps; probe.frames = frameNo; probe.ok = true;',
     '    simStep += simSteps;'),
    ('    if (cfg.paused) { updateHud(); return; }', ''),
    ('    if (!cfg.still || frameNo < cfg.warm) requestAnimationFrame(frame); else updateHud();',
     '    requestAnimationFrame(frame);'),
    ("""    if (hasTS && !qbusy && qrd.mapState === 'unmapped') {
      enc.resolveQuerySet(qset, 0, LABELS.length * 2, qres, 0);
      enc.copyBufferToBuffer(qres, 0, qrd, 0, LABELS.length * 16);
    }""", ''),
    ("""  if (!navigator.gpu) { fail('init', 'navigator.gpu missing — WebGPU unavailable'); return; }""", ''),
    ("  if (!adapter) { fail('init', 'requestAdapter returned null'); return; }", ''),
    ("  device.addEventListener('uncapturederror', e => fail('gpu', e.error.message));", ''),
    ("  device.lost.then(i => { if (i.reason !== 'destroyed') fail('device-lost', i.message); });", ''),
    ("  device.pushErrorScope('validation');", ''),
    ("""  probe.features = [...adapter.features].filter(f =>
    ['timestamp-query', 'shader-f16', 'subgroups', 'float32-filterable'].includes(f));""", ''),
    ("})().catch(e => fail('main', e));", '})();'),
]

# Any remaining line mentioning one of these is harness-only.
DEV_RE = re.compile(
    r'\bprobe\b|\bfail\(|\bhudEl\b|\berrEl\b|\bsetUI\(|\buiEl\b|\bhasTS\b'
    r'|\bqrd\b|\bqres\b|\bqset\b|\bqbusy\b|\bLABELS\b'
    r'|readTimestamps|readLevels|readParts|readPuddle|updateHud|runSelftest'
    r'|\bglassRd\b|\bpudRd\b|\bpartRd\b|\bgbusy\b|\bpbusy\b|\bpudbusy\b|\bPSAMP\b'
    r'|window\.__|getCompilationInfo|\bverr\b')


def strip_js(js, ui):
    for a, b in REWRITES:
        assert js.count(a) == 1, ('rewrite anchor missing', a[:60])
        js = js.replace(a, b)
    # the compilation-info loop spans lines; drop it wholesale
    js = re.sub(r'\n *for \(const m of \(await module\.getCompilationInfo\(\)\)\.messages\) \{.*?\n *\}',
                '', js, flags=re.S)
    js = '\n'.join(l for l in js.split('\n') if not DEV_RE.search(l))
    js = js.replace('beginComputePass({ timestampWrites: ts(0) })', 'beginComputePass()')
    js = re.sub(r'beginComputePass\(\{ timestampWrites: ts\(\d\) \}\)', 'beginComputePass()', js)
    # inline the control values, then the objects that held them are dead
    js = re.sub(r'\bcfg\.(\w+)\b', lambda m: CFG.get(m.group(1), 'cfg.' + m.group(1)), js)
    js = re.sub(r'\bui\.(\w+)\b', lambda m: ui.get(m.group(1), 'ui.' + m.group(1)), js)
    left = sorted(set(re.findall(r'\b(?:cfg|ui)\.\w+', js)))
    assert not left, 'un-inlined control values: %s' % left
    return js


# ── minification ────────────────────────────────────────────────────────────────
WGSL_KEEP = set("""fn let var const struct return if else for while loop break continue switch
case default discard true false override alias bitcast array atomic ptr sampler texture
vec2f vec3f vec4f vec2i vec3i vec4i vec2u vec3u vec4u f32 i32 u32 bool mat2x2f mat3x3f
mat4x4f vec2 vec3 vec4 abs acos asin atan atan2 ceil clamp cos cosh cross degrees
determinant distance dot exp exp2 faceForward floor fma fract frexp inverseSqrt length log
log2 max min mix modf normalize pow radians reflect refract round sign sin sinh smoothstep
sqrt step tan tanh transpose trunc all any select arrayLength atomicLoad atomicStore
atomicAdd atomicSub atomicMax atomicMin atomicAnd atomicOr atomicXor atomicExchange
atomicCompareExchangeWeak textureSample textureLoad textureStore workgroupBarrier
storageBarrier dpdx dpdy fwidth read write read_write uniform storage function private
workgroup compute vertex fragment builtin location group binding workgroup_size
global_invocation_id local_invocation_id workgroup_id num_workgroups position
vertex_index instance_index front_facing frag_depth sample_index sample_mask""".split())


def f32_literal(v):
    """Shortest WGSL literal that rounds to the same f32 the JS would have written."""
    t = struct.unpack('f', struct.pack('f', v))[0]
    for prec in range(1, 10):
        lit = '%.*g' % (prec, t)
        if struct.unpack('f', struct.pack('f', float(lit)))[0] == t:
            break
    if not any(c in lit for c in '.e'):
        lit += '.'                     # keep it a float: `91.` not the abstract int `91`
    # no `.5`: valid WGSL, but wgslender's parser rejects a leading dot and the build
    # silently loses its tree-shaking pass
    return '(%s)' % lit if lit.startswith('-') else lit


def release_uniforms(ui):
    """Uniform slots the release never varies, with the values writeUniforms would put
    there. Mirrors the JS expressions one for one; anything per-frame (camera, time, frame,
    emitter, shutter) is deliberately absent and stays a real uniform."""
    f = lambda k: float(ui[k])
    on = lambda k: 1.0 if ui[k] == 'true' else 0.0
    rad = math.pi / 180
    npart = float(CFG['npart'])
    return {
        'view': 0.0, 'fov': 1.6, 'maxSteps': float(CFG['steps']), 'dt': 1 / 60,
        'spawnMod': float(max(1, round((npart / 6) / f('pourRate')))),
        'nPart': npart, 'pvol': f('dropVol') * 1e-9, 'nPhoton': float(CFG['nphoton']),
        'cgain': f('cgain'), 'single': 0.0, 'noliq': 0.0, 'bub': on('bubbles'),
        'expo': f('expo'), 'wav': on('waves'), 'pfield': on('drops'), 'bounces': f('bounces'),
        'refl': on('reflect'), 'fillOv': -1.0 if ui['autofill'] == 'true' else f('fill') / 100,
        'envg': on('gridEnv'), 'rtrace': f('rtrace'),
        'ltAz': f('lightAz') * rad, 'ltEl': f('lightEl') * rad,
        'prad': f('dropRad') * 0.001, 'foamG': f('foam'),
        'botTilt': f('botTilt') * rad, 'botAz': f('botAz') * rad,
        'botOn': on('bottle'), 'pudOn': on('puddle'),
    }


def fold_uniforms(w, ui):
    """Replace u.<constant> with its literal so the branches behind debug toggles become
    `if (0. > .5)` and dead. Tree-shaking cannot remove those on its own: behind a uniform
    they are live code as far as any analysis of the shader can tell."""
    vals = release_uniforms(ui)
    n = [0]

    def rep(m):
        if m.group(1) in vals:
            n[0] += 1
            return f32_literal(vals[m.group(1)])
        return m.group(0)
    w = re.sub(r'(?<![.\w])u\.(\w+)\b', rep, w)
    return w, n[0]


_NUM = r'(?:\(-?\d[\d.]*(?:e[+-]?\d+)?\)|-?\d[\d.]*(?:e[+-]?\d+)?)'
_CMP = re.compile(r'(?<=[(&|])(\s*)(' + _NUM + r')\s*(<=|>=|==|!=|<|>)\s*(' + _NUM +
                  r')(?=\s*(?:\)|&&|\|\|))')
_OPS = {'<': lambda a, b: a < b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b,
        '>=': lambda a, b: a >= b, '==': lambda a, b: a == b, '!=': lambda a, b: a != b}


def _match(w, i, open_, close):
    """Index just past the bracket that closes the one at w[i]."""
    depth = 0
    while True:
        if w[i] == open_:
            depth += 1
        elif w[i] == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def _cond(c):
    """(True|False|None, simplified text) for an if-condition. Only top-level && chains
    are simplified; anything with || is left alone rather than reasoned about."""
    t = c.strip()
    if t in ('true', 'false'):
        return t == 'true', t
    if '||' in t:
        return None, c
    parts = [x.strip() for x in t.split('&&')]
    if any(x == 'false' for x in parts):
        return False, 'false'
    parts = [x for x in parts if x != 'true']
    if not parts:
        return True, 'true'
    return None, ' && '.join(parts)


def fold_branches(w):
    """Delete code behind conditions the folded uniforms have made constant.

    After fold_uniforms the debug toggles read `if (0. > 0.5) { ... }`. wgslender does not
    evaluate those - it only removes declarations nothing references - so this does: it
    evaluates literal comparisons, simplifies && chains, drops dead if-bodies (keeping the
    else arm), and unwraps always-true ones. Helpers that were only reachable through a
    dead branch then become unreferenced, which tree-shaking CAN remove.
    """
    w = _CMP.sub(lambda m: m.group(1) + ('true' if _OPS[m.group(3)](
        float(m.group(2).strip('()')), float(m.group(4).strip('()'))) else 'false'), w)
    ifre = re.compile(r'\bif\s*\(')
    n = 0
    # One fold per pass, then rescan from the top, so ifs nested inside other ifs (or
    # exposed by an earlier fold) are reached. There are only ~a dozen; cost is nothing.
    while True:
        changed = False
        for m in ifre.finditer(w):
            if re.search(r'\belse\s*$', w[:m.start()]):
                continue                       # part of an else-if chain: leave it
            ce = _match(w, m.end() - 1, '(', ')')
            cond = w[m.end():ce - 1]
            val, text = _cond(cond)
            if val is None and text == cond:
                continue
            bs = w.index('{', ce)
            be = _match(w, bs, '{', '}')
            if val is None:                    # condition simplified, branch stays
                w = w[:m.start()] + 'if (' + text + ') ' + w[bs:]
                changed = True
                break
            end, else_arm = be, ''
            k = re.match(r'\s*else\b', w[be:])
            if k:
                j = be + k.end()
                if re.match(r'\s*if\b', w[j:]):
                    c2 = w.index('(', j)
                    e2 = _match(w, w.index('{', _match(w, c2, '(', ')')), '{', '}')
                    while True:
                        k2 = re.match(r'\s*else\b', w[e2:])
                        if not k2:
                            break
                        e2 = _match(w, w.index('{', e2 + k2.end()), '{', '}')
                    else_arm, end = w[j:e2].strip(), e2
                else:
                    b2 = w.index('{', j)
                    end = _match(w, b2, '{', '}')
                    else_arm = w[b2:end]
            keep = w[bs:be] if val else else_arm
            w = w[:m.start()] + keep + w[end:]
            n += 1
            changed = True
            break
        if not changed:
            return w, n


def tree_shake(w):
    """Hand the shader to wgslender for dead-code elimination and syntax-level rewrites,
    but NOT for renaming or whitespace.

    Its own renaming optimises RAW size: distinct short names everywhere. Measured on this
    payload that is 599 bytes smaller on disk and 733 bytes LARGER after brotli, because
    distinct names destroy the repetition the compressor feeds on. So we take its analysis
    and keep our own naming. --no-whitespace matters too: our renamer finds globals with a
    line-anchored pattern, which a one-line file would defeat.

    Optional: if wgslender is not installed the build still works, 287 bytes heavier.
    """
    tmp_in = os.path.join(ROOT, '_shake_in.wgsl')
    tmp_out = os.path.join(ROOT, '_shake_out.wgsl')
    try:
        io.open(tmp_in, 'wb').write(w.encode())
        r = subprocess.run('npx --yes wgslender --no-mangle --no-whitespace "%s" -o "%s"'
                           % (tmp_in, tmp_out), capture_output=True, timeout=300, shell=True)
        if r.returncode == 0 and os.path.exists(tmp_out):
            out = io.open(tmp_out, encoding='utf-8').read()
            if len(out) > 1000:
                return out, True
        print('  wgslender failed: %s' % r.stderr.decode()[:200])
    except Exception as e:
        print('  wgslender unavailable (%s)' % e)
    finally:
        for f in (tmp_in, tmp_out):
            if os.path.exists(f):
                os.remove(f)
    return w, False


def _pool(w):
    """Candidate names, shortest first. Everything past the single letters carries a digit
    so it cannot collide with a WGSL keyword or reserved word (`as` got generated once).
    Length is the primary key: ranking by average character frequency alone put 3-char
    names above 2-char ones and renamed locals from 2 characters to 3."""
    alpha = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    pool = ([c for c in alpha]
            + [a + d for a in alpha for d in '0123456789']
            + [a + d + e for a in alpha for d in '0123456789' for e in '0123456789'])
    pool = [n for n in pool if n not in WGSL_KEEP]
    used = set(re.findall(r'\b\w+\b', w))
    freq = {}
    for ch in w:
        freq[ch] = freq.get(ch, 0) + 1
    pool = [n for n in pool if n not in used]
    pool.sort(key=lambda n: (len(n), -sum(freq.get(c, 0) for c in n), n))
    return pool


def _sub(w, old, new):
    # never rewrite a member access: a rename of `pos` must not touch `p.pos`
    return re.sub(r'(?<![.\w])%s\b' % re.escape(old), new, w)


def _protected(w, js):
    """Anything the host addresses by name. Two deliberately overlapping sources: any fn
    carrying an entry-point attribute, matched across newlines because `@vertex fn vs(`
    sits on ONE line and a newline-requiring pattern missed it (renamed entry point ->
    invalid pipeline -> a WebGPU *warning*, not an error, and a black screen); and every
    quoted word in the JS, which covers entryPoint: 'x' however it is spelled."""
    e = set(re.findall(r"@(?:compute|vertex|fragment)[\s\S]{0,160}?\bfn\s+(\w+)", w))
    e |= set(re.findall(r"['\"]([A-Za-z_]\w*)['\"]", js))
    return e


def _func_spans(w):
    """(decl start, body open brace, body close brace) for each function, braces matched."""
    for m in re.finditer(r'\bfn\s+\w+\s*\([^)]*\)[^{]*\{', w):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(w):
            if w[j] == '{':
                depth += 1
            elif w[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.start(), i, j


def minify_wgsl(w, js=''):
    w = re.sub(r'/\*.*?\*/', '', w, flags=re.S)
    w = re.sub(r'//[^\n]*', '', w)

    # globals
    names = (set(re.findall(r'\bfn\s+(\w+)', w))
             | set(re.findall(r'(?m)^const\s+(\w+)', w))
             | set(re.findall(r'\bstruct\s+(\w+)', w)))
    names = {n for n in names if n not in WGSL_KEEP and len(n) > 1} - _protected(w, js)
    for n, short in zip(sorted(names, key=lambda x: (-len(x), x)), _pool(w)):
        w = _sub(w, n, short)

    # Locals, drawing from the SAME pool in every function so the same few names recur.
    # Measured on this payload: reusing names and giving every function fresh ones produce
    # an IDENTICAL source size and differ by 291 bytes after brotli. Brevity is not the
    # lever; repetition is. Fresh names are even worse than not renaming locals at all.
    pool = _pool(w)
    out, last = [], 0
    for a, bi, b in _func_spans(w):
        head, body = w[a:bi], w[bi:b + 1]
        decls = set(re.findall(r'\b(?:let|var)\s+(\w+)', body)) | set(re.findall(r'(\w+)\s*:', head))
        decls = {d for d in decls if d not in WGSL_KEEP and len(d) > 1}
        # an identifier the function mentions but does not declare is off limits: taking
        # its name for a local would shadow the global and silently change meaning
        referenced = set(re.findall(r'(?<![.\w])([A-Za-z_]\w*)', head + body))
        avail = [n for n in pool if n not in (referenced - decls) | WGSL_KEEP]
        seg = head + body
        for d, short in zip(sorted(decls, key=lambda x: (-len(x), x)), avail):
            seg = _sub(seg, d, short)
        out.append(w[last:a])
        out.append(seg)
        last = b + 1
    out.append(w[last:])
    w = ''.join(out)

    w = re.sub(r'\s+', ' ', w)
    w = re.sub(r'\s*([{}()\[\],;:+\-*/<>=&|!?%])\s*', r'\1', w)
    return w.strip()


def minify_js(js):
    tmp = os.path.join(ROOT, '_min.js')
    try:
        io.open(tmp, 'wb').write(js.encode())
        # terser reads a FILE here: piping source through stdin fails on Windows.
        r = subprocess.run('npx --yes terser "%s" --compress --mangle --module' % tmp,
                           capture_output=True, timeout=300, shell=True)
        if r.returncode == 0 and len(r.stdout) > 200:
            return r.stdout.decode(), 'terser'
        print('  terser failed: %s' % r.stderr.decode()[:300])
    except Exception as e:
        print('  terser unavailable (%s)' % e)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    js = re.sub(r'(?m)^\s*//[^\n]*$', '', js)
    js = re.sub(r'\s*//(?:[^\n\'"`]*)$', '', js, flags=re.M)
    js = '\n'.join(l.strip() for l in js.split('\n') if l.strip())
    return js, 'fallback'


def prepare(verbose=False):
    """Everything up to the point where names and order get decided: harness stripped,
    controls inlined, uniforms and branches folded, dead code shaken, comments gone, JS
    minified. Shared by the build and by pack.py's search so both see the same shader."""
    say = print if verbose else (lambda *a: None)
    src = read(SRC)
    wgsl = re.search(r'<script type="text/wgsl" id="wgsl-main">(.*?)</script>', src, re.S).group(1)
    js = re.search(r'<script type="module">(.*?)</script>', src, re.S).group(1)
    ui = spec_defaults(js)
    ui.update(UI_OVERRIDE)

    say('source           wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))
    wgsl, js = cut_dev(wgsl), cut_dev(js)
    say('harness stripped wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))
    js = strip_js(js, ui)
    say('dev code removed wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))
    io.open(os.path.join(ROOT, 'strip.js'), 'wb').write(js.encode())

    wgsl, folded = fold_uniforms(wgsl, ui)
    say('uniforms folded  %d references to release constants' % folded)
    wgsl, branches = fold_branches(wgsl)
    say('branches folded  %d if-statements resolved at build time' % branches)
    wgsl, shaken = tree_shake(wgsl)
    if shaken:
        say('tree-shaken      wgsl %7d   (wgslender: dead code + syntax)' % len(wgsl.encode()))
    wgsl = re.sub(r'/\*.*?\*/', '', wgsl, flags=re.S)
    wgsl = re.sub(r'//[^\n]*', '', wgsl)
    jmin, how = minify_js(js)
    say('js minified with %s' % how)
    return wgsl, js, jmin


def main():
    sys.path.insert(0, ROOT)      # -I keeps the script's own directory off sys.path
    import pack
    wgsl, js, jmin = prepare(verbose=True)
    try:
        prog = pack.Program(wgsl, _protected(wgsl, js), WGSL_KEEP)
        saved = pack.load_state()
        st = prog.adopt(saved)
        wmin = prog.render(st)
        parts = st['parts']
        print('packed with %s state (%d items, %d globals, %d locals, %d fields)' % (
            'searched' if saved else 'default', len(prog.items), len(prog.globals),
            len(prog.all_locals), len(prog.fields)))
    except Exception as e:
        # the regex minifier is the fallback, not the path: say so loudly if it is taken
        print('  PACKER FAILED (%s) - falling back to the regex minifier' % e)
        wmin, parts = minify_wgsl(wgsl, js), ['style', 'canvas', 'wgsl', 'js']
    print('minified         wgsl %7d   js %7d' % (len(wmin.encode()), len(jmin.encode())))

    # keep the intermediates: a broken shader is unreadable from the packed page
    io.open(os.path.join(ROOT, 'min.wgsl'), 'wb').write(wmin.encode())
    io.open(os.path.join(ROOT, 'min.js'), 'wb').write(jmin.encode())

    pb = pack.assemble(wmin, jmin, parts)
    payload = pb.decode()
    raw_deflate = zlib.compress(pb, 9)[2:-4]          # raw deflate stream
    try:
        import brotli
        br = brotli.compress(pb, quality=11, lgwin=24)
    except ImportError:
        br = None

    b64 = __import__('base64').b64encode(raw_deflate).decode()
    loader = ('<body style=margin:0;overflow:hidden><script>'
              'fetch("data:application/octet-stream;base64,' + b64 + '")'
              '.then(r=>r.blob()).then(b=>b.stream()'
              '.pipeThrough(new DecompressionStream("deflate-raw")))'
              '.then(s=>new Response(s).text()).then(t=>{document.write(t);document.close()})'
              '</script>')
    io.open(OUT, 'wb').write(loader.encode())

    # ── the real deliverable: a self-extracting .cmd ────────────────────────────
    # It does NOT decompress. Stock Windows PowerShell is 5.1 on .NET Framework, which
    # has no BrotliStream, and the browser's DecompressionStream has no brotli either -
    # so inflating here would force deflate and cost ~1 kB. Instead the dropper SERVES
    # its own bytes over the Windows built-in HTTP server with Content-Encoding: br, and
    # the browser decodes brotli natively. This is INCENDIUM's trick. HttpListener binds
    # localhost without elevation (checked).
    PORT = 8044
    head = ('@set "f=%~f0"&powershell -nop -ep bypass -c '
            '"$b=[IO.File]::ReadAllBytes($env:f);$l=New-Object Net.HttpListener;'
            "$l.Prefixes.Add('http://localhost:%d/');$l.Start();"
            'start http://localhost:%d;'
            "$c=$l.GetContext();$r=$c.Response;$r.ContentType='text/html';"
            "$r.Headers.Add('Content-Encoding','br');"
            '$r.OutputStream.Write($b,@@@@@,$b.Length-@@@@@);$r.Close();$l.Stop()"&exit/b\r\n')
    head = head.replace('%d', str(PORT))   # not %-formatting: the header contains %~f0
    # the offset is written into the header itself, so it is padded to a fixed width to
    # stop the digit count from moving what it points at
    off = len(head.encode('ascii'))
    head = head.replace('@@@@@', str(off).rjust(5, '0'))
    assert len(head.encode('ascii')) == off, 'header length moved'
    assert br, 'brotli module required for the dropper'
    cmd = head.encode('ascii') + br
    io.open(os.path.join(ROOT, 'intro.cmd'), 'wb').write(cmd)

    print()
    print('dropper header         %8d' % off)
    print('   (serves brotli over HTTP; no inflate on the host)')
    print('intro.cmd (DELIVERABLE)%8d' % len(cmd))
    print('payload (uncompressed) %8d' % len(pb))
    print('deflate-raw            %8d' % len(raw_deflate))
    if br:
        print('brotli q11             %8d' % len(br))
    print('intro.html (runnable)  %8d' % len(loader.encode()))
    print()
    budget = 8192
    drop = 324
    print('budget %d, dropper ~%d, payload allowance %d' % (budget, drop, budget - drop))
    if br:
        print('brotli + dropper       %8d   %s' % (len(br) + drop,
              'UNDER' if len(br) + drop <= budget else 'OVER by %d' % (len(br) + drop - budget)))
    print('self-extracting html   %8d   %s' % (len(loader.encode()),
          'UNDER' if len(loader.encode()) <= budget else 'OVER by %d' % (len(loader.encode()) - budget)))
    print('intro.cmd              %8d   %s' % (len(cmd),
          'UNDER' if len(cmd) <= budget else 'OVER by %d' % (len(cmd) - budget)))


if __name__ == '__main__':
    main()
