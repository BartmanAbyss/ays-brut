"""The timeline's shot table: read it from the harness source, flatten it into the key list
the release ships, and write it back. Shared by the build (flatten) and the dev server's
save (format), so the two can never disagree about the format.

In the source the table sits between two marker lines:

    // SHOTS:BEGIN ...
    const SHOTS = [
      { name: 'glass', dur: 12.75, ov: {}, note: '...', keys: [
        [0, 20, 0.3, ...],         // [t within the shot, angle, dist, ... env] - 13 columns
      ] },
    ];
    // SHOTS:END

Each shot owns its keys, from t = 0 to t = dur. Flattening offsets them by the shot's
start and drops a key that repeats the one before it exactly (same time, same values): a
shot whose first key continues the previous shot's last one needs no cut, and the release
ships what it shipped before shots existed.
"""
import math
import re

BEGIN = '// SHOTS:BEGIN'
END = '// SHOTS:END'
COLS = ['t', 'angle', 'dist', 'camY', 'tgtY', 'speed', 'ease', 'fade', 'lightEl', 'pour',
        'botTilt', 'tableY', 'envAmt']
NCOL = len(COLS)
# The sliders the timeline drives, and the key column each one reads out. Recording one of
# these shifts the shot's keys.
SLIDER_COL = {'angle': 1, 'dist': 2, 'camY': 3, 'tgtY': 4, 'speed': 5, 'lightEl': 8, 'botTilt': 10,
              'tableY': 11, 'envAmt': 12}
# The other sliders a shot may set for itself ("ov"): the looks, and how the bottle wanders
# while it pours (pourWander, wanderSpd - set per shot by the user). Everything else is
# global; the debug switches are not looks. A shot's start state depends on the values the
# shots before it set, which the editor's kept start states account for. Same list as the
# editor's PER_SHOT in the harness (a test checks they agree).
PER_SHOT = ['lightAz', 'expo', 'cgain', 'shutter', 'bkBreath', 'bkSpeed', 'bkLife',
            'pourWander', 'wanderSpd', 'pourRate', 'botShare', 'botStand']


class TimelineError(ValueError):
    pass


def r6(x):
    """Round to 1e-6 the way the harness does (Math.round(x * 1e6) / 1e6), so both
    languages produce the same key times bit for bit."""
    return math.floor(x * 1e6 + 0.5) / 1e6


# ── a parser for the JS literal subset the table is written in ──────────────────────
_TOK = re.compile(r"""\s+|//[^\n]*|/\*.*?\*/
    |(?P<str>'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")
    |(?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)
    |(?P<id>[A-Za-z_$][\w$]*)
    |(?P<p>[\[\]{},:])""", re.S | re.X)


def _tokens(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m:
            raise TimelineError('cannot read the shot table near: %r' % text[pos:pos + 40])
        pos = m.end()
        for kind in ('str', 'num', 'id', 'p'):
            if m.group(kind) is not None:
                out.append((kind, m.group(kind)))
                break
    return out


def _unquote(s):
    body = s[1:-1]
    return re.sub(r'\\(.)', r'\1', body)


def parse_literal(text):
    toks = _tokens(text)
    pos = 0

    def value():
        nonlocal pos
        if pos >= len(toks):
            raise TimelineError('shot table ends early')
        kind, v = toks[pos]
        pos += 1
        if kind == 'num':
            return float(v)
        if kind == 'str':
            return _unquote(v)
        if kind == 'id':
            if v in ('true', 'false'):
                return v == 'true'
            if v == 'null':
                return None
            raise TimelineError('unexpected name %r in the shot table' % v)
        if v == '[':
            out = []
            while True:
                if toks[pos] == ('p', ']'):
                    pos += 1
                    return out
                out.append(value())
                if toks[pos] == ('p', ','):
                    pos += 1
                elif toks[pos] != ('p', ']'):
                    raise TimelineError('expected , or ] in the shot table')
        if v == '{':
            out = {}
            while True:
                if toks[pos] == ('p', '}'):
                    pos += 1
                    return out
                kk, kv = toks[pos]
                if kk not in ('id', 'str'):
                    raise TimelineError('expected a key in the shot table, got %r' % kv)
                key = kv if kk == 'id' else _unquote(kv)
                pos += 1
                if toks[pos] != ('p', ':'):
                    raise TimelineError('expected : after %r' % key)
                pos += 1
                out[key] = value()
                if toks[pos] == ('p', ','):
                    pos += 1
                elif toks[pos] != ('p', '}'):
                    raise TimelineError('expected , or } in the shot table')
        raise TimelineError('unexpected %r in the shot table' % v)

    v = value()
    if pos != len(toks):
        raise TimelineError('trailing text after the shot table')
    return v


# ── the block in the source ─────────────────────────────────────────────────────────
def _block_span(src):
    """(start, end) of the text between the marker lines, markers excluded."""
    a = src.find(BEGIN)
    b = src.find(END)
    if a < 0 or b < 0 or b < a or src.count(BEGIN) != 1 or src.count(END) != 1:
        raise TimelineError('expected exactly one %s ... %s block' % (BEGIN, END))
    a = src.index('\n', a) + 1
    b = src.rindex('\n', 0, b) + 1
    return a, b


def _split_head(text):
    """Comment lines at the top of the block belong to the source, not the table."""
    lines = text.split('\n')
    n = 0
    while n < len(lines) and lines[n].strip().startswith('//'):
        n += 1
    return '\n'.join(lines[:n]) + ('\n' if n else ''), '\n'.join(lines[n:])


def read_shots(src):
    a, b = _block_span(src)
    m = re.match(r'\s*const SHOTS = (.*);\s*$', _split_head(src[a:b])[1], re.S)
    if not m:
        raise TimelineError('the shot block must hold just `const SHOTS = [...];`')
    shots = parse_literal(m.group(1))
    validate(shots)
    return shots


def validate(shots):
    if not isinstance(shots, list) or not shots:
        raise TimelineError('SHOTS must be a non-empty list')
    for i, s in enumerate(shots):
        where = 'shot %d' % (i + 1)
        if not isinstance(s, dict):
            raise TimelineError('%s is not an object' % where)
        for f in ('name', 'dur', 'keys'):
            if f not in s:
                raise TimelineError('%s has no %s' % (where, f))
        unknown = set(s) - {'name', 'dur', 'keys', 'ov', 'note', 'fade'}
        if unknown:
            raise TimelineError('%s has unknown fields %s' % (where, sorted(unknown)))
        where = 'shot %d (%s)' % (i + 1, s['name'])
        if not isinstance(s['name'], str) or not s['name']:
            raise TimelineError('%s: name must be text' % where)
        d = s['dur']
        if not isinstance(d, (int, float)) or not math.isfinite(d) or d <= 0:
            raise TimelineError('%s: dur must be a positive number' % where)
        if 'fade' in s and (isinstance(s['fade'], bool) or not isinstance(s['fade'], (int, float))
                            or not math.isfinite(s['fade']) or s['fade'] < 0):
            raise TimelineError('%s: fade is a number of seconds, 0 or more' % where)
        ov = s.get('ov', {})
        if not isinstance(ov, dict):
            raise TimelineError('%s: ov must be an object' % where)
        for k, v in ov.items():
            if k in SLIDER_COL:
                raise TimelineError('%s: %s is a timeline column - it lives in the keys, not ov' % (where, k))
            if k not in PER_SHOT:
                raise TimelineError('%s: %s is a global slider - a shot cannot set it' % (where, k))
            if not isinstance(v, (bool, int, float)):
                raise TimelineError('%s: ov.%s must be a number or true/false' % (where, k))
        keys = s['keys']
        if not isinstance(keys, list) or len(keys) < 2:
            raise TimelineError('%s needs at least two keys (its start and its end)' % where)
        prev = -1.0
        for j, k in enumerate(keys):
            if not isinstance(k, list) or len(k) != NCOL:
                raise TimelineError('%s key %d must have %d numbers' % (where, j, NCOL))
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in k):
                raise TimelineError('%s key %d holds something that is not a number' % (where, j))
            if k[0] < prev:
                raise TimelineError('%s key %d goes back in time' % (where, j))
            prev = k[0]
        if keys[0][0] != 0:
            raise TimelineError('%s must start with a key at t = 0' % where)
        if abs(keys[-1][0] - d) > 1e-6:
            raise TimelineError('%s must end with a key at t = dur (%g), not %g' % (where, d, keys[-1][0]))


def flatten(shots):
    out, t0 = [], 0.0
    for s in shots:
        for k in s['keys']:
            row = [r6(t0 + k[0])] + [float(x) for x in k[1:]]
            if out and out[-1] == row:
                continue
            out.append(row)
        t0 = r6(t0 + s['dur'])
    return out


def starts(shots):
    out, t = [], 0.0
    for s in shots:
        out.append(t)
        t = r6(t + s['dur'])
    out.append(t)
    return out


# ── writing ─────────────────────────────────────────────────────────────────────────
def num(v):
    """Shortest text that reads back as the same double, integers without a point."""
    v = float(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _str(s):
    return "'" + s.replace('\\', '\\\\').replace("'", "\\'") + "'"


def format_shots(shots, indent='  '):
    """The block's text, columns aligned so a hand edit is easy to read."""
    validate(shots)
    rows = [[num(x) for x in k] for s in shots for k in s['keys']]
    width = [max(len(r[c]) for r in rows) for c in range(NCOL)]
    i1, i2, i3 = indent * 2, indent * 3, indent * 4
    out = [indent + 'const SHOTS = [']
    for s in shots:
        ov = s.get('ov') or {}
        ovt = '{' + ', '.join('%s: %s' % (k, 'true' if v is True else 'false' if v is False else num(v))
                              for k, v in sorted(ov.items())) + '}'
        fade = ' fade: %s,' % num(s['fade']) if 'fade' in s else ''
        head = '%s{ name: %s, dur: %s,%s ov: %s,' % (i1, _str(s['name']), num(s['dur']), fade, ovt)
        out.append(head)
        if s.get('note'):
            out.append('%snote: %s,' % (i2, _str(s['note'])))
        out.append(i2 + 'keys: [')
        for k in s['keys']:
            cells = [num(x).rjust(width[c]) for c, x in enumerate(k)]
            out.append('%s[%s],' % (i3, ', '.join(cells)))
        out.append(i2 + '] },')
    out.append(indent + '];')
    return '\n'.join(out) + '\n'


def write_shots(src, shots):
    a, b = _block_span(src)
    return src[:a] + _split_head(src[a:b])[0] + format_shots(shots) + src[b:]


# ── the release ─────────────────────────────────────────────────────────────────────
FLAT_CALL = 'flattenShots(SHOTS)'


def js_array(flat):
    return '[' + ','.join('[' + ','.join(num(x) for x in k) + ']' for k in flat) + ']'


# the per-shot values the release carries, in SHOT_V's order after the start time
SHOT_KEYS = ['shutter', 'pourRate', 'botShare', 'botStand']


def shot_table(shots, defaults):
    """[from, shutter, pourRate, botShare, botStand] per shot - its own value, else the
    global default - with a row only where something changes."""
    def val(k, v):
        if isinstance(v, str):
            v = v == 'true' if v in ('true', 'false') else float(v)
        return (1.0 if v else 0.0) if isinstance(v, bool) else float(v)
    out = []
    for s, t in zip(shots, starts(shots)):
        ov = s.get('ov') or {}
        row = [t] + [val(k, ov.get(k, defaults[k])) for k in SHOT_KEYS]
        # A shot that is black throughout shows nothing, so the values that only change the
        # look (LOOK_KEYS) carry over from the shot before: a row fewer for each black.
        # The ones the simulation runs on still apply - the tower fills in the black.
        if out and all(k[7] == 0 for k in s['keys']):
            for k in LOOK_KEYS:
                j = 1 + SHOT_KEYS.index(k)
                row[j] = out[-1][j]
        if not out or out[-1][1:] != row[1:]:
            out.append(row)
    return out


LOOK_KEYS = ['shutter', 'botStand']


def emit_release(js, defaults=None):
    """Replace the harness's runtime flattening with the flat literal. Returns the JS and
    a list of warnings: per-shot slider values (ov) are harness-only for now - the release
    folds those sliders to one value each, so it ships without them, and says so."""
    shots = read_shots(js)
    # per-shot values the release cannot carry yet: everything but SHOT_KEYS, and fade
    warn = []
    for s in shots:
        left = sorted(k for k in (s.get('ov') or {}) if k not in SHOT_KEYS) + (['fade'] if 'fade' in s else [])
        if left:
            warn.append('%s: %s' % (s['name'], ', '.join(left)))
    if js.count(FLAT_CALL) != 1:
        raise TimelineError('expected exactly one %s in the harness' % FLAT_CALL)
    js = js.replace(FLAT_CALL, js_array(flatten(shots)))
    if TEXT_CALL in js:
        js = js.replace(TEXT_CALL, js_array(text_cues(js, shots)))
    if TABLE_CALL in js:
        if defaults is None:
            raise TimelineError('the shot table needs the sliders\' defaults')
        js = js.replace(TABLE_CALL, js_array(shot_table(shots, defaults)))
    return js, warn


TABLE_CALL = 'shotTable(SHOTS)'


TEXT_CALL = 'textCues(SHOTS)'


def text_block(js):
    """The harness's TEXT block: the overlay's opening tag and the paths, in groups."""
    m = re.search(r"const TEXT_SVG = '([^'\n]*)';\s*const TEXT = (\[.*?\n  \]);", js, re.S)
    if not m:
        raise TimelineError('the TEXT block (TEXT_SVG, TEXT) not found in the harness')
    return m.group(1), parse_literal(m.group(2))


def _cued(js, shots):
    """(shot index, cue, group's paths) for each cue whose shot exists, in cue order."""
    m = re.search(r'const TEXT_CUES = (\[.*?\n  \]);', js, re.S)
    if not m:
        raise TimelineError('TEXT_CUES not found in the harness')
    groups = text_block(js)[1]
    names = [s['name'] for s in shots]
    return [(names.index(c[0]), c, groups[int(c[3])]) for c in parse_literal(m.group(1))
            if c[0] in names]


def text_cues(js, shots):
    """The lettering's cues - [shot name, from, to, group], seconds from the shot's start -
    as the release needs them: [from, to] for each line, in show seconds, a line a second
    after the one above. Mirrors the harness's textCues(): `to` stops at the shot's end, a
    cue for a missing shot drops."""
    st = starts(shots)
    return [[r6(st[i] + c[1] + k), r6(min(st[i] + c[2], st[i + 1]))]
            for i, c, g in _cued(js, shots) for k in range(len(g))]


def text_overlay(js, shots):
    """The overlay as the release's page has it, after the canvas: the cued lines' paths in
    the order text_cues() times them, every one unseen until the first frame sets it."""
    svg = text_block(js)[0]
    return svg + ''.join('<path opacity=0 d="%s"/>' % d for _, _, g in _cued(js, shots) for d in g) + "</svg>"
