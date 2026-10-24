"""Build the release intro from the dev harness.

One source of truth: dev/champagne.html. This strips the harness, inlines the control
values the panel used to supply, minifies, and packs the result into a self-extracting
HTML that inflates itself with DecompressionStream.

Run:  python build/build.py
Out:  build/intro.html   (runnable)   and a size report on stdout.
"""
import io, os, re, subprocess, sys, zlib

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


def main():
    src = read(SRC)
    wgsl = re.search(r'<script type="text/wgsl" id="wgsl-main">(.*?)</script>', src, re.S).group(1)
    js = re.search(r'<script type="module">(.*?)</script>', src, re.S).group(1)
    ui = spec_defaults(js)
    ui.update(UI_OVERRIDE)

    print('source           wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))
    wgsl, js = cut_dev(wgsl), cut_dev(js)
    print('harness stripped wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))
    js = strip_js(js, ui)
    print('dev code removed wgsl %7d   js %7d' % (len(wgsl.encode()), len(js.encode())))

    io.open(os.path.join(ROOT, 'strip.js'), 'wb').write(js.encode())
    wmin = minify_wgsl(wgsl, js)
    jmin, how = minify_js(js)
    print('minified (%-8s) wgsl %7d   js %7d' % (how, len(wmin.encode()), len(jmin.encode())))

    # keep the intermediates: a broken shader is unreadable from the packed page
    io.open(os.path.join(ROOT, 'min.wgsl'), 'wb').write(wmin.encode())
    io.open(os.path.join(ROOT, 'min.js'), 'wb').write(jmin.encode())

    # document.write replaces the loader's own body, so the payload carries its own style.
    # Without it the canvas keeps the 300x150 default and resize() reads that as the size.
    payload = ('<style>html,body{margin:0;height:100%;overflow:hidden;background:#000}'
               'canvas{display:block;width:100%;height:100%}</style>'
               '<canvas id=c></canvas><script type="text/wgsl" id="wgsl-main">' + wmin
               + '</script><script type="module">' + jmin + '</script>')
    pb = payload.encode()

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
