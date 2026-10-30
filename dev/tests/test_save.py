"""The shot table (build/timeline.py) and the editor's save (dev/serve.py).

    python -m unittest discover -s dev/tests -p "test_*.py"
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEV, '..', 'build'))
sys.path.insert(0, DEV)
import timeline as T  # noqa: E402
import serve  # noqa: E402

with io.open(os.path.join(DEV, "champagne.html"), encoding="utf-8", newline="") as _f:
    SRC = _f.read()


def key(t, angle=10.0, el=45.0):
    return [t, angle, 0.3, 0.4, 0.4, 1.0, 0.0, 1.0, el, 0.0, 0.0, 0.0, 1.0]


def mini():
    return [
        {'name': 'a', 'dur': 4.0, 'ov': {}, 'keys': [key(0), key(2, 20), key(4, 30)]},
        {'name': 'b', 'dur': 2.0, 'fade': 0.5, 'ov': {'expo': 2.0}, 'note': "it's b", 'keys': [key(0, 30), key(2, 50)]},
    ]


class Table(unittest.TestCase):
    def test_reads_the_harness(self):
        shots = T.read_shots(SRC)
        # the user saves into this table: check it reads and holds together, not its contents
        self.assertGreater(len(shots), 1)
        self.assertEqual(T.starts(shots)[-1], T.flatten(shots)[-1][0])
        T.validate(shots)

    def test_flatten_offsets_and_drops_exact_repeats(self):
        f = T.flatten(mini())
        self.assertEqual([k[0] for k in f], [0, 2, 4, 6])     # b's first key repeats a's last
        f2 = T.flatten([mini()[0], dict(mini()[1], keys=[key(0, 31), key(2, 50)])])
        self.assertEqual([k[0] for k in f2], [0, 2, 4, 4, 6])  # differs: a cut, two keys

    def test_format_parse_round_trip(self):
        for shots in (mini(), T.read_shots(SRC)):
            text = T.format_shots(shots)
            back = T.parse_literal(text.split('=', 1)[1].rsplit(';', 1)[0])
            self.assertEqual(back, shots)

    def test_write_then_read_keeps_the_source_around_it(self):
        out = T.write_shots(SRC, mini())
        self.assertEqual(T.read_shots(out), mini())
        a = SRC.index(T.BEGIN)
        self.assertEqual(out[:a], SRC[:a])
        self.assertEqual(out[out.index(T.END):], SRC[SRC.index(T.END):])
        self.assertIn('keep the format', out[a:out.index('const SHOTS')], 'the comment head is kept')

    def test_rewriting_the_harness_table_changes_nothing(self):
        self.assertEqual(T.write_shots(SRC, T.read_shots(SRC)), SRC)

    def test_validate_refuses_broken_tables(self):
        bad = []
        s = mini(); s[0]['dur'] = 0; bad.append(s)
        s = mini(); s[0]['keys'][1][0] = 5; bad.append(s)                 # out of order
        s = mini(); s[0]['keys'][-1][0] = 3.9; bad.append(s)              # does not end at dur
        s = mini(); s[0]['keys'][0][0] = 0.1; bad.append(s)               # does not start at 0
        s = mini(); s[0]['keys'][0].pop(); bad.append(s)                  # 12 columns
        s = mini(); s[0]['keys'] = s[0]['keys'][:1]; s[0]['keys'][0][0] = 0; bad.append(s)
        s = mini(); s[1]['ov'] = {'pourRate': 3.0}; bad.append(s)          # a global slider
        s = mini(); s[1]['ov'] = {'angle': 3.0}; bad.append(s)             # a timeline column
        s = mini(); s[1]['oops'] = 1; bad.append(s)
        s = mini(); s[1]['fade'] = -1.0; bad.append(s)
        s = mini(); s[1]['fade'] = True; bad.append(s)
        s = mini(); s[0]['keys'][1][3] = 'x'; bad.append(s)
        for b in bad:
            with self.assertRaises(T.TimelineError):
                T.validate(b)

    def test_release_flattens_and_warns_about_shot_values(self):
        # on the harness's own table with its shot values taken out: the user saves into
        # it, so its contents are not fixed
        shots = [{k: v for k, v in s.items() if k not in ('ov', 'fade')} for s in T.read_shots(SRC)]
        js, warn = T.emit_release(T.write_shots(SRC, shots))
        self.assertNotIn(T.FLAT_CALL, js)
        self.assertIn('const SHOW = ' + T.js_array(T.flatten(shots)) + ';', js)
        self.assertEqual(warn, [])
        js, warn = T.emit_release(T.write_shots(SRC, mini()))
        self.assertEqual(warn, ['b: expo, fade'])

    def test_numbers_are_written_shortest(self):
        self.assertEqual([T.num(x) for x in (20.0, 0.3, -25.0, 45.6, 1e-7)], ['20', '0.3', '-25', '45.6', '1e-07'])


class Save(unittest.TestCase):
    def payload(self, **globals_):
        shots = T.read_shots(SRC)
        shots[0] = dict(shots[0], dur=25.5, keys=[[k[0] * 2] + k[1:] for k in shots[0]['keys']])
        return {'shots': shots, 'globals': globals_}

    def test_writes_shots_and_defaults(self):
        out, changed = serve.apply_save(SRC, self.payload(expo=1.85, bubbles=False))
        self.assertEqual(changed, ['shots', 'bubbles', 'expo'])
        self.assertEqual(T.read_shots(out)[0]['dur'], 25.5)
        self.assertIn("['expo',     'range', 1.85,", out)
        self.assertIn("['bubbles',  'check', false]", out)
        # everything else in the file is as it was
        self.assertEqual(len(out.split('\n')) - len(SRC.split('\n')), 0)

    def test_saving_what_is_there_changes_nothing(self):
        out, changed = serve.apply_save(SRC, {'shots': T.read_shots(SRC), 'globals': {'expo': 1.45}})
        self.assertEqual(out, SRC)
        self.assertEqual(changed, [])

    def test_refuses_bad_input(self):
        bad = [
            {},
            {'shots': []},
            {'shots': T.read_shots(SRC), 'globals': {'nosuch': 1}},
            {'shots': T.read_shots(SRC), 'globals': {'expo': 'loud'}},
            {'shots': T.read_shots(SRC), 'globals': {'bubbles': 1}},
            {'shots': T.read_shots(SRC), 'globals': {'showT': 3}},
            {'shots': T.read_shots(SRC), 'globals': []},
        ]
        for b in bad:
            with self.assertRaises(serve.SaveError, msg=json.dumps(b)[:80]):
                serve.apply_save(SRC, b)

    def test_apply_cli_path(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'champagne.html')
            shutil.copy(os.path.join(DEV, 'champagne.html'), p)
            out, changed = serve.save_file(p, self.payload(expo=2.0))
            with io.open(p, encoding='utf-8', newline='') as f:
                self.assertEqual(f.read(), out)
            self.assertIn('expo', changed)
        finally:
            shutil.rmtree(d)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, 'champagne.html')
        shutil.copy(os.path.join(DEV, 'champagne.html'), cls.path)
        cls.srv = serve.make_server(0, directory=cls.dir, src_path=cls.path)
        cls.url = 'http://127.0.0.1:%d' % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.dir)

    def post(self, path, obj):
        req = urllib.request.Request(self.url + path, data=json.dumps(obj).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def disk(self):
        with io.open(self.path, encoding='utf-8', newline='') as f:
            return f.read()

    def test_a_serves_the_harness_uncached(self):
        with urllib.request.urlopen(self.url + '/champagne.html') as r:
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
            self.assertIn('SHOTS:BEGIN', r.read().decode())

    def test_b_dry_run_returns_the_text_and_writes_nothing(self):
        before = self.disk()
        shots = T.read_shots(before)
        shots[1]['dur'] = 17.0
        shots[1]['keys'] = [[k[0] * 2] + k[1:] for k in shots[1]['keys']]
        code, j = self.post('/__save?dry=1', {'shots': shots, 'globals': {'cgain': 0.07}})
        self.assertEqual(code, 200)
        self.assertEqual(j['changed'], ['shots', 'cgain'])
        self.assertEqual(T.read_shots(j['src'])[1]['dur'], 17.0)
        self.assertEqual(self.disk(), before)

    def test_c_save_writes_the_file(self):
        shots = T.read_shots(self.disk())
        shots[0]['ov'] = {'expo': 1.7}
        code, j = self.post('/__save', {'shots': shots, 'globals': {}})
        self.assertEqual((code, j['changed']), (200, ['shots']))
        self.assertEqual(T.read_shots(self.disk())[0]['ov'], {'expo': 1.7})

    def test_d_bad_input_is_a_400_and_writes_nothing(self):
        before = self.disk()
        code, j = self.post('/__save', {'shots': [{'name': 'x'}]})
        self.assertEqual(code, 400)
        self.assertFalse(j['ok'])
        self.assertIn('dur', j['error'])
        self.assertEqual(self.disk(), before)

    def test_e_only_save_takes_a_post(self):
        code, j = self.post('/elsewhere', {})
        self.assertEqual(code, 404)

    def test_f_binds_to_localhost_only(self):
        self.assertEqual(self.srv.server_address[0], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
