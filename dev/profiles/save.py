"""Receive one whole-show profile from record.js and store it for view.html.

    python dev/profiles/save.py 1080p-2026-11-02 [--gpu "RTX 4070"] [--refresh "60 Hz"]

Listens on 127.0.0.1:8799 for one POST, then writes dev/profiles/<name>.json (the viewer's
format: rows plus the shots' names and starts from the harness's timeline), <name>.csv
(the same rows, for a spreadsheet) and adds the file to index.json, which the viewer opens
newest-first. The shot of each row is derived from its show time - the probe's own `shot`
is the index of the timeline KEY, not of the shot.
"""
import argparse, csv, datetime, http.server, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'build'))
import build as B
import timeline as T


def receive():
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got['body'] = self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(('127.0.0.1', 8799), H)
    print('waiting for record.js on 127.0.0.1:8799 ...', flush=True)
    while 'body' not in got:
        srv.handle_request()
    return json.loads(got['body'])


def store(raw, name, gpu, refresh):
    c = {n: i for i, n in enumerate(raw['columns'])}
    shots = T.read_shots(io.open(B.SRC, encoding='utf-8').read())
    st = T.starts(shots)
    F = T.COLS.index('fade')
    SH = [{'name': s['name'], 'start': st[i], 'dur': s['dur'], 'black': all(k[F] == 0 for k in s['keys'])}
          for i, s in enumerate(shots)]
    cols = ['showT', 'shot', 'frameMs', 'sim', 'build', 'photon', 'render', 'total', 'simSteps', 'alive', 'topLevel']
    rows, prev = [], None
    for r in raw['rows']:
        t, step = r[c['showT']], r[c['step']]
        shot = max(i for i in range(len(SH)) if SH[i]['start'] <= t + 1e-9)
        rows.append([t, shot, r[c['frameMs']], r[c['sim']], r[c['build']], r[c['photon']], r[c['render']],
                     r[c['total']], (step - prev) if prev is not None else 0, r[c['alive']], r[c['topLevel']]])
        prev = step
    ad = raw.get('adapter') or {}
    doc = {'date': datetime.date.today().isoformat(), 'width': raw.get('width'), 'height': raw.get('height'),
           'gpu': gpu or '%s %s' % (ad.get('vendor', '?'), ad.get('architecture', '?')), 'refresh': refresh,
           'showEnd': st[-1], 'shots': SH, 'columns': cols, 'rows': rows,
           'note': 'GPU ms are per frame from timestamp queries, read back a frame or two late; frameMs is '
                   'the interval between rendered frames (vsync caps it at the refresh rate); simSteps is '
                   'sim progress that frame in full 1/60 s steps.'}
    json.dump(doc, open(os.path.join(HERE, name + '.json'), 'w'), separators=(',', ':'))
    with open(os.path.join(HERE, name + '.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(cols + ['shotName'])
        for r in rows:
            w.writerow(r + [SH[r[1]]['name']])
    idx = os.path.join(HERE, 'index.json')
    files = json.load(open(idx)) if os.path.exists(idx) else []
    if name + '.json' not in files:
        files.append(name + '.json')
    json.dump(files, open(idx, 'w'), indent=1)
    print('%d frames -> dev/profiles/%s.json, .csv' % (len(rows), name))
    print('view: http://localhost:8787/profiles/view.html?f=%s.json' % name)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('--gpu', default='')
    ap.add_argument('--refresh', default='60 Hz')
    ap.add_argument('--raw', help='a saved raw dump instead of waiting for record.js')
    a = ap.parse_args()
    store(json.load(open(a.raw)) if a.raw else receive(), a.name, a.gpu, a.refresh)
