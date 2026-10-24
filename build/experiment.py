"""Measure WGSL renaming strategies by COMPRESSED size.

The literature is blunt about why this script exists: shrinking the source does not
guarantee a smaller compressed output, and Shader Minifier shipped a size regression from
a renaming heuristic precisely because nothing was measuring the compressed result. So
every strategy here is scored on brotli bytes of the real payload, not on source length.

Run: python build/experiment.py
"""
import io, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as B
import brotli

KEEP = B.WGSL_KEEP


def strip_comments(w):
    w = re.sub(r'/\*.*?\*/', '', w, flags=re.S)
    return re.sub(r'//[^\n]*', '', w)


def squeeze(w):
    w = re.sub(r'\s+', ' ', w)
    return re.sub(r'\s*([{}()\[\],;:+\-*/<>=&|!?%])\s*', r'\1', w).strip()


def make_pool(w, frequency_ordered):
    alpha = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    pool = ([c for c in alpha]
            + [a + d for a in alpha for d in '0123456789']
            + [a + d + e for a in alpha for d in '0123456789' for e in '0123456789'])
    pool = [p for p in pool if p not in KEEP]
    used = set(re.findall(r'\b\w+\b', w))
    pool = [p for p in pool if p not in used]
    if frequency_ordered:
        # "Not all letters are equal when it comes to compression." Prefer characters the
        # rest of the source already uses a lot, so the compressor's context model is
        # predicting symbols it has seen rather than fresh ones.
        freq = {}
        for ch in w:
            freq[ch] = freq.get(ch, 0) + 1
        # Length FIRST, frequency only as a tie-break. Ranking by average character
        # frequency alone put three-character names above two-character ones and renamed
        # locals from 2 chars to 3 - a net +325 characters before the compressor even ran.
        pool.sort(key=lambda n: (len(n), -sum(freq.get(c, 0) for c in n), n))
    return pool


def protected(w, js):
    e = set(re.findall(r'@(?:compute|vertex|fragment)[\s\S]{0,160}?\bfn\s+(\w+)', w))
    e |= set(re.findall(r"['\"]([A-Za-z_]\w*)['\"]", js))
    return e


def globals_of(w):
    n = (set(re.findall(r'\bfn\s+(\w+)', w))
         | set(re.findall(r'(?m)^const\s+(\w+)', w))
         | set(re.findall(r'\bstruct\s+(\w+)', w)))
    return {x for x in n if x not in KEEP and len(x) > 1}


def sub_ident(w, old, new):
    # never touch a member access: `p.pos` must not be rewritten by a rename of `pos`
    return re.sub(r'(?<![.\w])%s\b' % re.escape(old), new, w)


def rename_globals(w, js, freq):
    names = globals_of(w) - protected(w, js)
    pool = make_pool(w, freq)
    for n, short in zip(sorted(names, key=lambda x: (-len(x), x)), pool):
        w = sub_ident(w, n, short)
    return w


def functions(w):
    """Yield (start, end) spans of each function BODY, braces matched."""
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


def rename_locals(w, js, freq, reuse):
    """Rename each function's locals. With reuse=True every function draws from the SAME
    pool from the top, so `a`, `b`, `c` recur in function after function - which is the
    whole point: repetition compresses, brevity alone does not."""
    pool = make_pool(w, freq)
    out = []
    last = 0
    counter = [0]
    for start, bodyi, end in functions(w):
        head = w[start:bodyi]
        body = w[bodyi:end + 1]
        params = re.findall(r'(\w+)\s*:', head)
        decls = set(re.findall(r'\b(?:let|var)\s+(\w+)', body)) | set(params)
        decls = {d for d in decls if d not in KEEP and len(d) > 1}
        # any identifier the function mentions but does not declare is off limits: taking
        # its name for a local would shadow the global and silently change meaning
        referenced = set(re.findall(r'(?<![.\w])([A-Za-z_]\w*)', head + body))
        forbidden = (referenced - decls) | KEEP
        seg = head + body
        if reuse:
            avail = [p for p in pool if p not in forbidden]
        else:
            avail = [p for p in pool[counter[0]:] if p not in forbidden]
            counter[0] += len(decls)
        for d, short in zip(sorted(decls, key=lambda x: (-len(x), x)), avail):
            seg = sub_ident(seg, d, short)
        out.append(w[last:start])
        out.append(seg)
        last = end + 1
    out.append(w[last:])
    return ''.join(out)


def payload(wgsl, js):
    return ('<style>html,body{margin:0;height:100%;overflow:hidden;background:#000}'
            'canvas{display:block;width:100%;height:100%}</style>'
            '<canvas id=c></canvas><script type="text/wgsl" id="wgsl-main">' + wgsl
            + '</script><script type="module">' + js + '</script>').encode()


def main():
    src = B.read(B.SRC)
    wgsl = re.search(r'<script type="text/wgsl" id="wgsl-main">(.*?)</script>', src, re.S).group(1)
    js = re.search(r'<script type="module">(.*?)</script>', src, re.S).group(1)
    ui = B.spec_defaults(js)
    ui.update(B.UI_OVERRIDE)
    wgsl, js = B.cut_dev(wgsl), B.cut_dev(js)
    js = B.strip_js(js, ui)
    jmin, how = B.minify_js(js)
    print('js minified with %s: %d bytes\n' % (how, len(jmin.encode())))

    base = strip_comments(wgsl)
    variants = [
        ('comments+whitespace only', lambda w: w),
        ('+ globals renamed', lambda w: rename_globals(w, js, False)),
        ('+ globals, freq-ordered names', lambda w: rename_globals(w, js, True)),
        ('+ globals + locals, fresh names', lambda w: rename_locals(rename_globals(w, js, True), js, True, False)),
        ('+ globals + locals REUSED', lambda w: rename_locals(rename_globals(w, js, True), js, True, True)),
    ]
    rows = []
    for name, fn in variants:
        w = squeeze(fn(base))
        pb = payload(w, jmin)
        rows.append((name, len(w.encode()), len(pb), len(brotli.compress(pb, quality=11, lgwin=24))))
    best = min(r[3] for r in rows)
    print('%-34s %9s %9s %9s' % ('variant', 'wgsl', 'payload', 'BROTLI'))
    for name, wl, pl, bl in rows:
        print('%-34s %9d %9d %9d  %s' % (name, wl, pl, bl,
              'BEST' if bl == best else '+%d' % (bl - best)))
    io.open(os.path.join(B.ROOT, 'best.wgsl'), 'wb').write(
        squeeze(variants[[r[3] for r in rows].index(best)][1](base)).encode())
    print('\nbest variant written to build/best.wgsl for validation')


main()
