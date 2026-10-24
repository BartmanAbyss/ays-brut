"""Token-level WGSL packer: renaming and ordering as a search, scored by brotli.

The shader is tokenised once into module-scope items (functions, structs, consts,
bindings). A *state* says what order the items go in and which candidate name each
identifier gets; render(state) turns that into WGSL in a couple of milliseconds. Every
move the search makes is semantics-preserving by construction:

  - module-scope declarations may appear in any order in WGSL (use before declaration is
    allowed at module scope), so items can be shuffled freely;
  - names are only ever permuted among identifiers of the same kind, and a function's
    locals never take a name that function also needs for something else.

Then search(): late-acceptance hill climbing, Pakettic's choice, over those moves, keeping
the state whose payload brotli-compresses smallest. The winning state is saved as JSON and
reused by every later build, keyed by source names, so it survives edits to the shader:
unknown items and names just fall back to their default position.

Usage: python build/pack.py [--rounds N] [--per-round N] [--workers N] [--seed N]
"""
import io, json, os, random, re, sys, time

import brotli

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, 'pack_state.json')

# Multi-character operators are single tokens. Without that `->` came out as `-` `>`, the
# danger rule below kept them apart, and every function signature read `)- >f32`.
TOK = re.compile(r'\s+|[A-Za-z_]\w*|0[xX][0-9a-fA-F]+[iu]?'
                 r'|\d+\.?\d*(?:[eE][+-]?\d+)?[fhiu]?|\.\d+(?:[eE][+-]?\d+)?[fh]?'
                 r'|->|&&|\|\||<=|>=|==|!=|\+\+|--|[-+*/%&|^]=|.', re.S)
# two characters that must not touch: joining would make a different token (a decrement,
# a comment, `>=` out of a template close and an assignment...)
# (`>>` is deliberately absent: two template closers may touch, and the old minifier relied on it)
DANGER = {'--', '++', '&&', '||', '//', '/*', '*/', '->', '<=', '>=', '==',
          '!=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^='}
SWIZZLE = re.compile(r'^[xyzwrgba]{1,4}$')


def _isword(t):
    return t[0].isalnum() or t[0] == '_'


def _names():
    """Candidate names, shortest first. Past the single letters every name carries a digit,
    so none can be a WGSL keyword or reserved word."""
    a = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return ([c for c in a] + [x + d for x in a for d in '0123456789']
            + [x + d + e for x in a for d in '0123456789' for e in '0123456789'])


class Program:
    def __init__(self, wgsl, protected, keep):
        toks = [t for t in TOK.findall(wgsl)]
        # strip whitespace now; spacing is decided again at render time
        toks = [t for t in toks if not t.isspace()]
        self.keep = keep
        self.items = self._split(toks)
        self.keys = [self._key(it) for it in self.items]
        self._analyse(protected)

    # ── structure ────────────────────────────────────────────────────────────
    @staticmethod
    def _split(toks):
        items, cur, depth = [], [], 0
        for t in toks:
            cur.append(t)
            if t in '([{':
                depth += 1
            elif t in ')]}':
                depth -= 1
                if depth == 0 and t == '}':
                    items.append(cur); cur = []
            elif t == ';' and depth == 0:
                if len(cur) == 1 and items:          # stray `;` after a struct
                    items[-1].append(';')
                else:
                    items.append(cur)
                cur = []
        assert not cur, 'trailing tokens after the last declaration'
        return items

    @staticmethod
    def _key(it):
        s = ' '.join(it)
        m = re.search(r'\b(fn|struct|const|override|alias)\s+(\w+)', s) or \
            re.search(r'\b(var)\b(?:\s*<[^>]*>)?\s+(\w+)', s)
        return '%s:%s' % (m.group(1), m.group(2)) if m else 'item:' + s[:40]

    @staticmethod
    def _member(toks, i):
        return i > 0 and toks[i - 1] == '.'

    def _analyse(self, protected):
        glob = set()
        for k in self.keys:
            kind, name = k.split(':', 1)
            if kind in ('fn', 'struct', 'const', 'override', 'alias', 'var'):
                glob.add(name)
        self.globals = sorted(n for n in glob if n not in protected and n not in self.keep)

        # struct fields: renamed in their own namespace, never if they look like a swizzle
        fields = {}
        for it, k in zip(self.items, self.keys):
            if k.startswith('struct:'):
                for i in range(len(it) - 1):
                    if _isword(it[i]) and it[i + 1] == ':' and it[i] not in self.keep:
                        fields[it[i]] = 0
        for it in self.items:
            for i, t in enumerate(it):
                if t in fields and self._member(it, i):
                    fields[t] += 1
        self.fields = sorted((f for f in fields if not SWIZZLE.match(f)),
                             key=lambda f: (-fields[f], f))

        # locals of each function: parameters plus let/var/const in the body. A local that
        # shares its name with a global is left to the global mapping, which renames both
        # consistently and so keeps the shadowing exactly as written.
        self.locals = {}
        gset = set(self.globals) | set(protected)
        for idx, (it, k) in enumerate(zip(self.items, self.keys)):
            if not k.startswith('fn:'):
                continue
            decl = set()
            p0 = it.index('(')
            depth = 0
            for i in range(p0, len(it)):
                t = it[i]
                if t == '(':
                    depth += 1
                elif t == ')':
                    depth -= 1
                    if depth == 0:
                        break
                elif depth == 1 and _isword(t) and i + 1 < len(it) and it[i + 1] == ':':
                    decl.add(t)
            for i in range(len(it) - 1):
                if it[i] in ('let', 'var', 'const'):
                    j = i + 1
                    if it[j] == '<':
                        while it[j] != '>':
                            j += 1
                        j += 1
                    if _isword(it[j]):
                        decl.add(it[j])
            self.locals[idx] = {d for d in decl if d not in self.keep and d not in gset}
        self.all_locals = sorted({d for s in self.locals.values() for d in s})

        # every identifier that will NOT be renamed is off limits as a new name anywhere
        renamed = set(self.globals)
        frozen = set()
        for idx, it in enumerate(self.items):
            loc = self.locals.get(idx, set())
            for i, t in enumerate(it):
                if _isword(t) and not t[0].isdigit() and not self._member(it, i) \
                        and t not in renamed and t not in loc:
                    frozen.add(t)
        self.frozen = frozen | set(self.keep)
        pool = [n for n in _names() if n not in self.frozen]
        self.pool = pool
        self.fpool = [n for n in _names() if n not in self.keep and not SWIZZLE.match(n)]

    # ── state ────────────────────────────────────────────────────────────────
    def default_state(self):
        return {
            'items': list(self.keys),
            'globals': sorted(self.globals, key=lambda n: (-len(n), n)),
            'locals': sorted(self.all_locals, key=lambda n: (-len(n), n)),
            'fields': list(self.fields),
            'parts': ['style', 'canvas', 'wgsl', 'js'],
        }

    def adopt(self, saved):
        """Fit a saved state to the current program: keep the saved order for everything it
        knows, put anything new where the default would, drop what no longer exists."""
        d = self.default_state()
        out = {}
        for k in ('items', 'globals', 'locals', 'fields'):
            known = [x for x in saved.get(k, []) if x in set(d[k])]
            out[k] = known + [x for x in d[k] if x not in set(known)]
        p = saved.get('parts', d['parts'])
        out['parts'] = p if sorted(p) == sorted(d['parts']) else d['parts']
        return out

    # ── render ───────────────────────────────────────────────────────────────
    def render(self, st):
        gmap = dict(zip(st['globals'], self.pool))
        fmap = dict(zip(st['fields'], self.fpool))
        lrank = {n: i for i, n in enumerate(st['locals'])}
        order = [self.keys.index(k) for k in st['items']]
        out = []
        for idx in order:
            it = self.items[idx]
            loc = self.locals.get(idx)
            lmap = {}
            if loc:
                # names this function needs for things other than its own locals
                need = set()
                for i, t in enumerate(it):
                    if _isword(t) and not self._member(it, i) and t not in loc:
                        need.add(gmap.get(t, t))
                avail = (n for n in self.pool if n not in need)
                for d in sorted(loc, key=lambda n: lrank[n]):
                    lmap[d] = next(avail)
            in_struct = self.keys[idx].startswith('struct:')
            for i, t in enumerate(it):
                if self._member(it, i):
                    t = fmap.get(t, t)
                elif in_struct and i + 1 < len(it) and it[i + 1] == ':' and t in fmap:
                    t = fmap[t]
                elif t in lmap:
                    t = lmap[t]
                elif t in gmap:
                    t = gmap[t]
                if out and ((_isword(out[-1]) and _isword(t)) or (out[-1][-1] + t[0]) in DANGER):
                    out.append(' ')
                out.append(t)
        return ''.join(out)


def assemble(wgsl, js, parts):
    p = {
        'style': '<style>html,body{margin:0;height:100%;overflow:hidden;background:#000}'
                 'canvas{display:block;width:100%;height:100%}</style>',
        'canvas': '<canvas id=c></canvas>',
        'wgsl': '<script type="text/wgsl" id="wgsl-main">' + wgsl + '</script>',
        # a module script is deferred, so it may sit anywhere: the canvas and the shader
        # exist by the time it runs
        'js': '<script type="module">' + js + '</script>',
    }
    return ''.join(p[k] for k in parts).encode()


def score(prog, st, js):
    return len(brotli.compress(assemble(prog.render(st), js, st['parts']), quality=11, lgwin=24))


def _copy(st):
    return {k: list(v) for k, v in st.items()}


def lahc(prog, st, js, iters, seed, history=400):
    """Late-acceptance hill climbing: accept a candidate if it is no worse than the current
    state OR than the state `history` steps ago. It wanders across plateaus a plain hill
    climber gets stuck on, with no temperature schedule to tune. Returns the best state
    seen and the state it ended on."""
    rng = random.Random(seed)
    cur = _copy(st)
    cs = score(prog, cur, js)
    best, bs = _copy(cur), cs
    hist = [cs] * history
    for it in range(iters):
        cand = _copy(cur)
        r = rng.random()
        if r < 0.40:
            L = cand['items']
            i, j = rng.randrange(len(L)), rng.randrange(len(L))
            L.insert(j, L.pop(i))
        else:
            L = (cand['globals'] if r < 0.60 else cand['locals'] if r < 0.85
                 else cand['fields'] if r < 0.97 else cand['parts'])
            if len(L) > 1:
                i, j = rng.randrange(len(L)), rng.randrange(len(L))
                L[i], L[j] = L[j], L[i]
        sc = score(prog, cand, js)
        v = it % history
        if sc <= cs or sc <= hist[v]:
            cur, cs = cand, sc
            if sc < bs:
                best, bs = _copy(cand), sc
        hist[v] = cs
    return best, bs, cur, cs


# ── one process per core ───────────────────────────────────────────────────────
# Evaluation is a brotli q11 compress (~20 ms) and nothing else, so it parallelises as
# independent chains. Island model: every worker runs its own chain for a round; between
# rounds the worse half of the islands are re-seeded from the global best while the
# better half carry on from where they were, which keeps both diversity and pressure.
_W = {}


def _init(wgsl, protected, keep, js):
    _W['prog'] = Program(wgsl, set(protected), set(keep))
    _W['js'] = js


def _round(args):
    st, iters, seed = args
    return lahc(_W['prog'], st, _W['js'], iters, seed)


def search(wgsl, protected, keep, js, start, rounds, per_round, workers, seed, log=print):
    import multiprocessing as mp
    prog = Program(wgsl, set(protected), set(keep))
    gbest, gs = _copy(start), score(prog, start, js)
    states = [_copy(start) for _ in range(workers)]
    t0 = time.time()
    with mp.get_context('spawn').Pool(workers, initializer=_init,
                                      initargs=(wgsl, sorted(protected), sorted(keep), js)) as pool:
        for r in range(rounds):
            res = pool.map(_round, [(states[i], per_round, seed * 1000003 + r * 1009 + i)
                                    for i in range(workers)])
            for b, bsc, _, _ in res:
                if bsc < gs:
                    gbest, gs = _copy(b), bsc
            order = sorted(range(workers), key=lambda i: res[i][3])
            for rank, i in enumerate(order):
                states[i] = _copy(res[i][2]) if rank < workers // 2 else _copy(gbest)
            ends = sorted(x[3] for x in res)
            done = (r + 1) * per_round * workers
            log('  round %3d  best %6d  islands %d..%d  %7d evals  %5.0f/s' % (
                r + 1, gs, ends[0], ends[-1], done, done / (time.time() - t0)))
    return gbest, gs


def load_state():
    if os.path.exists(STATE):
        return json.load(io.open(STATE, encoding='utf-8'))
    return {}


def save_state(st, s, src=None):
    st = dict(st, score=s, src=src)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(json.dumps(st, indent=1))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='search WGSL order and naming by brotli size')
    ap.add_argument('--rounds', type=int, default=30)
    ap.add_argument('--per-round', type=int, default=400, help='iterations per island per round')
    ap.add_argument('--workers', type=int, default=os.cpu_count())
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()

    sys.path.insert(0, ROOT)
    import build as B
    wgsl, js, jmin = B.prepare()
    protected = B._protected(wgsl, js)
    prog = Program(wgsl, protected, B.WGSL_KEEP)
    st = prog.adopt(load_state())
    print('items %d  globals %d  locals %d  fields %d   %d workers x %d rounds x %d' % (
        len(prog.items), len(prog.globals), len(prog.all_locals), len(prog.fields),
        a.workers, a.rounds, a.per_round))
    print('default state %d   starting state %d' % (
        score(prog, prog.default_state(), jmin), score(prog, st, jmin)))
    best, bs = search(wgsl, protected, B.WGSL_KEEP, jmin, st, a.rounds, a.per_round,
                      a.workers, a.seed)
    # A stored score only means something for the input it was searched on: after a shader
    # or JS change it is a different problem, and comparing against the old score would
    # discard a valid search whenever the payload grew.
    import hashlib
    src = hashlib.sha1((wgsl + jmin).encode()).hexdigest()[:16]
    old = load_state()
    prev = old.get('score') if old.get('src') == src else None
    if prev is None or bs < prev:
        save_state(best, bs, src)
        print('saved: %d (was %s for this input)' % (bs, prev))
    else:
        print('kept existing state %d; this run reached %d' % (prev, bs))
