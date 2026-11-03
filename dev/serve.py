"""The harness's dev server: serves dev/ like `python -m http.server`, plus the timeline
editor's save.

    python dev/serve.py                        # http://localhost:8787/champagne.html?edit=1
    python dev/serve.py --port 8788
    python dev/serve.py --apply timeline.json  # write a downloaded save in, no server

POST /__save takes {shots, globals} from the editor and rewrites dev/champagne.html: the
shot table between its markers (build/timeline.py formats it) and the default of each
slider in `globals` (its row in SPEC). /__save?dry=1 returns the new text instead of
writing it - the editor's tests use that. Only ever binds to 127.0.0.1.
"""
import argparse
import functools
import http.server
import importlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'build'))
import timeline  # noqa: E402

SRC = os.path.join(HERE, 'champagne.html')
BUILD = os.path.join(HERE, '..', 'build')   # exported videos are served from here
# sliders that are not settings: the show toggle and its clock
NOT_SAVED = {'show', 'showT'}


class SaveError(ValueError):
    pass


def spec_rows(src):
    """{name: (kind, start, end)} with start/end the span of each row's default value."""
    m = re.search(r'const SPEC = \[(.*?)\n  \];', src, re.S)
    if not m:
        raise SaveError('SPEC not found in the harness')
    out = {}
    for r in re.finditer(r"\['(\w+)',\s*'(range|check)',\s*([^,\]]+)", m.group(1)):
        a = m.start(1) + r.start(3)
        out[r.group(1)] = (r.group(2), a, a + len(r.group(3)))
    return out


def set_default(src, name, value, rows=None):
    rows = rows or spec_rows(src)
    if name not in rows or name in NOT_SAVED:
        raise SaveError('no slider called %r' % name)
    kind, a, b = rows[name]
    if kind == 'check':
        if not isinstance(value, bool):
            raise SaveError('%s is a checkbox: true or false, not %r' % (name, value))
        txt = 'true' if value else 'false'
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SaveError('%s is a slider: a number, not %r' % (name, value))
        txt = timeline.num(value)
    old = src[a:b]
    # keep the column alignment the table is written with
    pad = len(old) - len(old.rstrip())
    return src[:a] + txt + ' ' * pad + src[b:] if pad else src[:a] + txt + src[b:]


def apply_save(src, payload):
    """The new source text, and a list of what changed."""
    if not isinstance(payload, dict) or 'shots' not in payload:
        raise SaveError('expected {shots, globals}')
    globals_ = payload.get('globals', {})
    if not isinstance(globals_, dict):
        raise SaveError('globals must be an object')
    try:
        timeline.validate(payload['shots'])
        before = timeline.read_shots(src)
        out = timeline.write_shots(src, payload['shots'])
    except timeline.TimelineError as e:
        raise SaveError(str(e))
    changed = []
    if before != payload['shots']:
        changed.append('shots')
    for name in sorted(globals_):
        rows = spec_rows(out)
        old = out[rows[name][1]:rows[name][2]].strip() if name in rows else None
        out = set_default(out, name, globals_[name], rows)
        if old != out[spec_rows(out)[name][1]:spec_rows(out)[name][2]].strip():
            changed.append(name)
    return out, changed


def write_atomic(path, text):
    tmp = path + '.saving'
    with io.open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, path)


def save_file(path, payload, dry=False):
    # the server runs for hours while build/timeline.py changes under it (a slider becomes
    # per-shot, a field is added): read the rules fresh on every save, or a server started
    # before the change refuses the very saves the change allows
    importlib.reload(timeline)
    with io.open(path, encoding='utf-8', newline='') as f:
        src = f.read()
    out, changed = apply_save(src, payload)
    if not dry and out != src:
        write_atomic(path, out)
    return out, changed


class Handler(http.server.SimpleHTTPRequestHandler):
    src_path = SRC

    def end_headers(self):
        # the harness is edited and saved under the browser: never serve a stale copy
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path, _, query = self.path.partition('?')
        if path != '/__save':
            self._json(404, {'ok': False, 'error': 'only /__save takes a POST'})
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(n).decode('utf-8'))
            dry = 'dry=1' in query.split('&')
            out, changed = save_file(self.src_path, payload, dry)
        except (SaveError, ValueError) as e:
            self._json(400, {'ok': False, 'error': str(e)})
            return
        self._json(200, {'ok': True, 'changed': changed, **({'src': out} if dry else {})})

    def do_GET(self):
        # /build/<name>.mp4: the exported videos, for the music sketchpad (dev/music.html).
        # With byte ranges - a <video> cannot seek a file served without them.
        path = self.path.partition('?')[0]
        m = re.fullmatch(r'/build/([\w.-]+\.mp4)', path)
        if not m:
            return super().do_GET()
        f = os.path.join(BUILD, m.group(1))
        if not os.path.isfile(f):
            self.send_error(404, 'no build/%s - export it with dev/export.py' % m.group(1))
            return
        size = os.path.getsize(f)
        a, b, code = 0, size - 1, 200
        r = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
        if r and (r.group(1) or r.group(2)):
            if r.group(1):
                a = int(r.group(1))
                b = min(int(r.group(2)), size - 1) if r.group(2) else size - 1
            else:
                a = max(0, size - int(r.group(2)))
            if a > b:
                self.send_response(416)
                self.send_header('Content-Range', 'bytes */%d' % size)
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(b - a + 1))
        if code == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (a, b, size))
        self.end_headers()
        with open(f, 'rb') as fh:
            fh.seek(a)
            left = b - a + 1
            try:
                while left > 0:
                    chunk = fh.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass   # the player cancels ranges it no longer needs

    def log_message(self, fmt, *args):
        if self.command == 'POST':
            super().log_message(fmt, *args)


def make_server(port, directory=HERE, src_path=SRC):
    handler = functools.partial(type('H', (Handler,), {'src_path': src_path}), directory=directory)
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--apply', metavar='JSON', help='write a downloaded timeline.json into the harness and exit')
    a = ap.parse_args()
    if a.apply:
        with io.open(a.apply, encoding='utf-8') as f:
            payload = json.load(f)
        _, changed = save_file(SRC, payload)
        print('wrote dev/champagne.html: ' + (', '.join(changed) or 'nothing had changed'))
        return
    srv = make_server(a.port)
    print('serving dev/ on http://localhost:%d/champagne.html?edit=1  (ctrl+c stops)' % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
