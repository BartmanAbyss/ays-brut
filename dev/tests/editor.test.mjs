// The timeline editor's model: pure functions, loaded straight out of the harness.
//   node --test dev/tests
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(HERE, '..', 'champagne.html'), 'utf8');

function block(begin, end) {
  const a = SRC.indexOf(begin), b = SRC.indexOf(end);
  assert.ok(a >= 0 && b > a, 'markers ' + begin + ' / ' + end + ' not found');
  return SRC.slice(SRC.indexOf('\n', a) + 1, b);
}
const ED = new Function(block('// EDITOR-MODEL:BEGIN', '// EDITOR-MODEL:END') + '\nreturn ED;')();
// the real shot table from the harness
const SHOTS = new Function(block('// SHOTS:BEGIN', '// SHOTS:END').replace(/^\s*\/\/.*$/mg, '') + '\nreturn SHOTS;')();

// a small timeline to test on: two shots, keys [t, 12 values]
const key = (t, angle, el = 45) => [t, angle, 0.3, 0.4, 0.4, 1, 1, el, 0, 0, 0, 1];
const mini = () => [
  { name: 'a', dur: 4, ov: {}, keys: [key(0, 10), key(2, 20), key(4, 30)] },
  { name: 'b', dur: 2, ov: {}, keys: [key(0, 30), key(2, 50)] },
  { name: 'c', dur: 3, ov: { expo: 2 }, keys: [key(0, 0), key(3, 90)] },
];

test('starts: each shot start, then the end', () => {
  assert.deepEqual(ED.starts(mini()), [0, 4, 6, 9]);
});

test('flatten: offsets keys by shot start, drops an exact repeat at a boundary', () => {
  const f = ED.flatten(mini());
  assert.deepEqual(f.map(k => k[0]), [0, 2, 4, 6, 6, 9]);   // a->b continues (one key), b->c cuts (two)
  assert.deepEqual(f[2], key(4, 30));
});

test('flatten: the real shot table lays out end to end, times going forward', () => {
  // the user saves into this table, so nothing about its contents is fixed
  const f = ED.flatten(SHOTS);
  const keys = SHOTS.reduce((n, s) => n + s.keys.length, 0);
  assert.ok(f.length <= keys && f.length >= SHOTS.length + 1);
  assert.equal(f[f.length - 1][0], ED.starts(SHOTS)[SHOTS.length]);
  for (let i = 1; i < f.length; i++) assert.ok(f[i][0] >= f[i - 1][0], 'times go forward');
});

test('flatten agrees with build/timeline.py bit for bit', () => {
  const py = execFileSync('python', ['-c',
    'import sys, json; sys.path.insert(0, sys.argv[1]); import timeline as T;' +
    'src = open(sys.argv[2], encoding="utf-8").read(); print(json.dumps(T.flatten(T.read_shots(src))))',
    path.join(HERE, '..', '..', 'build'), path.join(HERE, '..', 'champagne.html')]).toString();
  assert.deepEqual(ED.flatten(SHOTS), JSON.parse(py));
});

test('PER_SHOT and the column map agree with build/timeline.py', () => {
  const py = JSON.parse(execFileSync('python', ['-c',
    'import sys, json; sys.path.insert(0, sys.argv[1]); import timeline as T;' +
    'print(json.dumps([T.PER_SHOT, T.SLIDER_COL]))', path.join(HERE, '..', '..', 'build')]).toString());
  assert.deepEqual(ED.PER_SHOT, py[0]);
  assert.deepEqual(ED.COL, py[1]);
});

test('COLS agrees with build/timeline.py', () => {
  const py = JSON.parse(execFileSync('python', ['-c',
    'import sys, json; sys.path.insert(0, sys.argv[1]); import timeline as T; print(json.dumps(T.COLS))',
    path.join(HERE, '..', '..', 'build')]).toString());
  assert.deepEqual(ED.COLS, py);
});

test('keyChanges: the values that move between two keys, time left out', () => {
  const a = key(0, 10), b = key(2, 20, 50);
  assert.deepEqual(ED.keyChanges(a, b), [['angle', 10, 20], ['lightEl', 45, 50]]);
  assert.deepEqual(ED.keyChanges(a, a), []);
});

test('keyList: every key with its show time, shot and index', () => {
  const l = ED.keyList(mini());
  assert.equal(l.length, 7);
  assert.deepEqual(l.map(e => e.t), [0, 2, 4, 4, 6, 6, 9]);
  assert.deepEqual(l[3], { t: 4, i: 1, j: 0, k: key(0, 30) });
});

test('shotAt: inside, on a boundary (the later shot), past the end', () => {
  const s = mini();
  assert.equal(ED.shotAt(s, 0), 0);
  assert.equal(ED.shotAt(s, 3.99), 0);
  assert.equal(ED.shotAt(s, 4), 1);
  assert.equal(ED.shotAt(s, 6), 2);
  assert.equal(ED.shotAt(s, 100), 2);
});

test('scale: stretches one shot and its keys, later shots move, input untouched', () => {
  const s = mini(), t = ED.scale(s, [0], 1.5);
  assert.equal(t[0].dur, 6);
  assert.deepEqual(t[0].keys.map(k => k[0]), [0, 3, 6]);
  assert.deepEqual(ED.starts(t), [0, 6, 8, 11]);
  assert.deepEqual(t[1], s[1]);
  assert.equal(s[0].dur, 4, 'the input is not modified');
});

test('scale: several shots at once, each by the factor', () => {
  const t = ED.scale(mini(), [0, 2], 0.5);
  assert.deepEqual(ED.starts(t), [0, 2, 4, 5.5]);
  assert.equal(t[2].keys[1][0], 1.5);
});

test('scale: the last key always lands exactly on the new length', () => {
  const t = ED.scale(mini(), [1], 1 / 3);
  assert.equal(t[1].keys[t[1].keys.length - 1][0], t[1].dur);
});

test('scale: refuses a factor that is not a positive number, never goes below 0.05 s', () => {
  assert.throws(() => ED.scale(mini(), [0], 0));
  assert.throws(() => ED.scale(mini(), [0], -1));
  assert.throws(() => ED.scale(mini(), [0], NaN));
  assert.equal(ED.scale(mini(), [0], 1e-6)[0].dur, 0.05);
});

test('setDur: sets one shot to a length in seconds', () => {
  const t = ED.setDur(mini(), 1, 5);
  assert.equal(t[1].dur, 5);
  assert.deepEqual(t[1].keys.map(k => k[0]), [0, 5]);
});

test('mapTime: the playhead keeps its place in a stretched shot and after it', () => {
  const a = mini(), b = ED.scale(a, [0], 2);
  assert.equal(ED.mapTime(a, b, 2), 4);       // half way through shot a
  assert.equal(ED.mapTime(a, b, 5), 9);       // half way through shot b, which moved by 4
  assert.equal(ED.mapTime(a, b, 0), 0);
});

test('shiftColumn: moves one column of one shot, every key, nothing else', () => {
  const s = mini(), t = ED.shiftColumn(s, 0, 1, 5);
  assert.deepEqual(t[0].keys.map(k => k[1]), [15, 25, 35]);
  assert.deepEqual(t[0].keys.map(k => k[7]), [45, 45, 45]);
  assert.deepEqual(t[1], s[1]);
});

test('scaleColumn: multiplies one column of one shot, every key, nothing else', () => {
  const s = mini();
  s[0].keys.forEach((k, j) => { k[5] = [0.25, 0.25, 1][j]; });
  const t = ED.scaleColumn(s, 0, 5, 2);
  assert.deepEqual(t[0].keys.map(k => k[5]), [0.5, 0.5, 2]);
  assert.deepEqual(t[0].keys.map(k => k[1]), [10, 20, 30]);
  assert.deepEqual(t[1], s[1]);
  assert.deepEqual(s[0].keys.map(k => k[5]), [0.25, 0.25, 1], 'the input is not modified');
});

test('columnChanged / resetColumn: against the saved table', () => {
  const saved = mini(), t = ED.shiftColumn(saved, 1, ED.COL.lightEl, -10);
  assert.equal(ED.columnChanged(t, saved, 1, ED.COL.lightEl), true);
  assert.equal(ED.columnChanged(t, saved, 1, 1), false);
  assert.equal(ED.columnChanged(t, saved, 0, ED.COL.lightEl), false);
  const r = ED.resetColumn(t, saved, 1, ED.COL.lightEl);
  assert.equal(ED.columnChanged(r, saved, 1, ED.COL.lightEl), false);
  assert.deepEqual(r, saved);
});

test('resetColumn keeps the times of a stretched shot', () => {
  const saved = mini();
  const t = ED.shiftColumn(ED.scale(saved, [0], 2), 0, 1, 7);
  const r = ED.resetColumn(t, saved, 0, 1);
  assert.deepEqual(r[0].keys.map(k => k[0]), [0, 4, 8]);
  assert.deepEqual(r[0].keys.map(k => k[1]), [10, 20, 30]);
});

test('setOverride / clearOverride / effective', () => {
  const g = { expo: 1.45, cgain: 0.05 };
  let s = ED.setOverride(mini(), 0, 'cgain', 0.1);
  assert.equal(ED.effective(s, 0, g, 'cgain'), 0.1);
  assert.equal(ED.effective(s, 1, g, 'cgain'), 0.05, 'other shots keep the global');
  assert.equal(ED.effective(s, 2, g, 'expo'), 2);
  s = ED.clearOverride(s, 0, 'cgain');
  assert.equal(ED.effective(s, 0, g, 'cgain'), 0.05);
  assert.deepEqual(s[0].ov, {});
});

test('fadeAt: none set -> null; in and out over the shot\'s fade, whatever its length', () => {
  const s = mini();
  assert.equal(ED.fadeAt(s, 1), null);
  const f = ED.setFade(s, 0, 1);
  assert.equal(ED.fadeAt(f, 0), 0);
  assert.equal(ED.fadeAt(f, 0.5), 0.5);
  assert.equal(ED.fadeAt(f, 2), 1);
  assert.equal(ED.fadeAt(f, 3.5), 0.5);
  assert.equal(ED.fadeAt(f, 4.5), null, 'the next shot has none');
  const g = ED.scale(f, [0], 2);
  assert.equal(ED.fadeAt(g, 1), 1, 'stretching the shot does not stretch the fade');
  assert.equal(ED.fadeAt(ED.setFade(s, 1, 5), 5), 0.2, 'longer than half the shot: a triangle');
  assert.equal(ED.fadeAt(ED.setFade(s, 0, 0), 0), 1, '0 is a hard cut');
});

test('setFade: sets, clears, refuses nonsense, leaves the input alone', () => {
  const s = mini();
  assert.equal(ED.setFade(s, 1, 0.75)[1].fade, 0.75);
  assert.equal('fade' in ED.setFade(ED.setFade(s, 1, 2), 1, null)[1], false);
  assert.throws(() => ED.setFade(s, 0, -1));
  assert.throws(() => ED.setFade(s, 0, NaN));
  ED.setFade(s, 0, 3);
  assert.equal('fade' in s[0], false);
  assert.equal(ED.shotChanged(ED.setFade(s, 0, 3), s, 0), true);
});

test('setOverride refuses a global-only slider', () => {
  assert.throws(() => ED.setOverride(mini(), 0, 'dropVol', 50), /global/);
  assert.throws(() => ED.setOverride(mini(), 0, 'angle', 50), /global/);
});

test('status: key / shot / global / none', () => {
  const saved = mini();
  const defaults = { expo: 1.45, cgain: 0.05, lightAz: -45 };
  const st = { shots: ED.shiftColumn(saved, 0, ED.COL.lightEl, 3), globals: { expo: 1.45, cgain: 0.07, lightAz: -45 }, touched: [] };
  assert.equal(ED.status(st, saved, defaults, 0, 'lightEl'), 'key');
  assert.equal(ED.status(st, saved, defaults, 1, 'lightEl'), '');
  assert.equal(ED.status(st, saved, defaults, 2, 'expo'), 'shot');
  assert.equal(ED.status(st, saved, defaults, 0, 'expo'), '');
  assert.equal(ED.status(st, saved, defaults, 0, 'cgain'), 'global');
  assert.equal(ED.status(st, saved, defaults, 0, 'lightAz'), '');
});

test('shotChanged: length, keys or overrides differ from the saved table', () => {
  const saved = mini();
  assert.equal(ED.shotChanged(saved, saved, 0), false);
  assert.equal(ED.shotChanged(ED.scale(saved, [0], 2), saved, 0), true);
  assert.equal(ED.shotChanged(ED.setOverride(saved, 1, 'expo', 1), saved, 1), true);
  assert.equal(ED.shotChanged(ED.setOverride(saved, 1, 'expo', 1), saved, 0), false);
});

test('signature: earlier shots and sim globals matter; the shot itself and looks do not', () => {
  const s = mini(), g = { pourRate: 120, expo: 1.45 };
  const base = ED.signature(s, 1, g);
  assert.equal(ED.signature(ED.scale(s, [1], 2), 1, g), base, 'the shot itself');
  assert.equal(ED.signature(s, 1, { ...g, expo: 3 }), base, 'a look');
  assert.notEqual(ED.signature(ED.scale(s, [0], 2), 1, g), base, 'an earlier shot');
  assert.notEqual(ED.signature(s, 1, { ...g, pourRate: 60 }), base, 'a sim global');
});

test('clampSteps: never steps over a shot start, lands on it exactly', () => {
  const S = [0, 765, 1275, 1425];
  assert.equal(ED.clampSteps(S, 763, 3), 2, 'stops on 765');
  assert.equal(ED.clampSteps(S, 764, 1), 1);
  assert.equal(ED.clampSteps(S, 765, 3), 3, 'already on it: free to go on');
  assert.equal(ED.clampSteps(S, 100, 15), 15, 'no start in reach');
  assert.equal(ED.clampSteps(S, 1270, 15), 5, 'a replay stops on 1275');
  assert.equal(ED.clampSteps(S, 763, 2), 2, 'landing exactly on it needs no clamp');
});

test('loopSpan: one shot, or first to last of a selection', () => {
  assert.deepEqual(ED.loopSpan(mini(), [1]), [4, 6]);
  assert.deepEqual(ED.loopSpan(mini(), [2, 0]), [0, 9]);
});

test('history: undo, redo, a new change drops the redo branch', () => {
  const h = ED.history();
  let cur = { v: 1 };
  assert.equal(h.undo(cur), null);
  h.push(cur); cur = { v: 2 };
  h.push(cur); cur = { v: 3 };
  cur = h.undo(cur); assert.deepEqual(cur, { v: 2 });
  cur = h.undo(cur); assert.deepEqual(cur, { v: 1 });
  assert.equal(h.canUndo, false);
  cur = h.redo(cur); assert.deepEqual(cur, { v: 2 });
  h.push(cur); cur = { v: 9 };
  assert.equal(h.canRedo, false, 'a new change after undo drops the redo branch');
  cur = h.undo(cur); assert.deepEqual(cur, { v: 2 });
});

test('history: states are copies, later mutation does not leak in', () => {
  const h = ED.history();
  const st = { a: [1] };
  h.push(st);
  st.a.push(2);
  assert.deepEqual(h.undo({}), { a: [1] });
});

test('history: bounded', () => {
  const h = ED.history(3);
  for (let i = 0; i < 10; i++) h.push({ i });
  let n = 0, cur = {};
  while ((cur = h.undo(cur))) n++;
  assert.equal(n, 3);
});

test('savePayload: shots, and only touched globals that are not the default', () => {
  const st = { shots: mini(), globals: { expo: 2, cgain: 0.05, fill: 60 }, touched: ['expo', 'cgain'] };
  const p = ED.savePayload(st, { expo: 1.45, cgain: 0.05, fill: 80 });
  assert.deepEqual(p.globals, { expo: 2 });                 // fill came from the URL: not saved
  assert.deepEqual(p.shots, st.shots);
  p.shots[0].dur = 99;
  assert.equal(st.shots[0].dur, 4, 'a copy');
});
