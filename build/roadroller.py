"""Roadroller on the page's script: context mixing, served with brotli on top as before.

Blueberry's fork of Roadroller (build/vendor/node_modules/roadroller, see VENDORED.md)
packs the one <script> of the assembled page - our JS with the shader in it - into a
decoder plus packed text, which rebuilds the script and evals it. The page's markup (the
canvas, the lettering's overlay) stays as it is. Measured 31 Oct: intro.cmd 10 306 -> 9 514,
against 9 944 with stock Roadroller 2.1.0; it adds ~0.4 s before "click".

Every build packs with the settings in build/roadroller.json - fixed, so the same sources
give the same intro.cmd, and fast (no search). They are the result of a search, like
pack_state.json, and stay valid as the script changes, just less tuned. Re-run the search
after big changes, and before a release:

    python build/roadroller.py          # -O2 search (~40 s), saves build/roadroller.json

No fallbacks: a missing tool, a missing settings file or a failed pack stops the build.
"""
import io, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(ROOT, 'vendor', 'node_modules', 'roadroller', 'cli.mjs')
SETTINGS = os.path.join(ROOT, 'roadroller.json')


# -D, the "dirty" decoder: shorter, its variables global (Blueberry's fork searches their
# names). The CLI calls it unsafe for scripts with top-level code or single-letter names,
# and ours has both - but the decoder is done by the time our script is eval'd, and our
# top-level consts are scoped to that eval. -22 bytes; checked: decodes, plays, shows text.
DIRTY = ['-D']


class RoadrollerError(Exception):
    pass


def _run(script, args):
    """Roadroller on `script` with CLI `args`: (packed script, the CLI's stderr)."""
    if not os.path.exists(CLI):
        raise RoadrollerError('Roadroller is missing from build/vendor/node_modules/roadroller - '
                              'it is committed; check out the whole repository')
    src, out = os.path.join(ROOT, '_rr_in.js'), os.path.join(ROOT, '_rr_out.js')
    try:
        io.open(src, 'w', encoding='utf-8', newline='').write(script)
        try:
            r = subprocess.run(['node', CLI] + args + [src, '-o', out], capture_output=True, timeout=900)
        except FileNotFoundError:
            raise RoadrollerError('`node` is not on PATH - install Node.js (16 or newer)')
        err = r.stderr.decode(errors='replace') + r.stdout.decode(errors='replace')
        if r.returncode != 0 or not os.path.exists(out):
            raise RoadrollerError('Roadroller failed (exit %d):\n%s' % (r.returncode, err[-1500:]))
        packed = io.open(out, encoding='utf-8', newline='').read().rstrip('\n')
    finally:
        for f in (src, out):
            if os.path.exists(f):
                os.remove(f)
    # it goes inside <script>...</script> as is: it must not end the element early
    if '</script' in packed.lower():
        raise RoadrollerError('Roadroller output contains "</script" - it cannot be inlined')
    return packed, err


def split(page):
    """(markup up to and including <script>, the script) of the assembled page."""
    a = page.index('<script>') + len('<script>')
    if not page.endswith('</script>') or page.count('<script>') != 1:
        raise RoadrollerError('expected one <script> at the end of the page')
    return page[:a], page[a:-len('</script>')]


def roll(page):
    """The assembled page (bytes) with its script packed by Roadroller."""
    if not os.path.exists(SETTINGS):
        raise RoadrollerError('build/roadroller.json is missing - run python build/roadroller.py')
    args = json.load(io.open(SETTINGS, encoding='utf-8'))['args'].split() + DIRTY
    head, script = split(page.decode('utf-8'))
    packed, _ = _run(script, args)
    return (head + packed + '</script>').encode('utf-8')


def search(page):
    """-O2 search on the page's script; returns the CLI args that replicate the best."""
    _, script = split(page.decode('utf-8'))
    _, err = _run(script, ['-O2'] + DIRTY)
    m = re.search(r'use `([^`]+)` to replicate', err)
    if not m:
        raise RoadrollerError('the search did not report its settings:\n' + err[-1500:])
    return m.group(1), err


if __name__ == '__main__':
    sys.path.insert(0, ROOT)
    import brotli
    import build as B
    import pack
    wgsl, js, jmin, page = B.prepare()
    prog = pack.Program(wgsl, B._protected(wgsl, js), B.WGSL_KEEP)
    st = prog.adopt(pack.load_state())
    pb = pack.assemble(prog.render(st), jmin, st['parts'], page)
    print('searching (Roadroller -O2)...', flush=True)
    args, err = search(pb)
    est = re.search(r'to replicate: (\d+)', err)
    # what the build would ship with these settings
    json.dump({'args': args, 'searched': 'estimated %s' % (est.group(1) if est else '?')},
              io.open(SETTINGS, 'w', encoding='utf-8', newline='\n'), indent=1)
    packed = roll(pb)
    print('saved build/roadroller.json: %s' % args)
    print('intro.cmd with these settings: %d (brotli alone: %d)' % (
        218 + len(brotli.compress(packed, quality=11, lgwin=24)),
        218 + len(brotli.compress(pb, quality=11, lgwin=24))))
