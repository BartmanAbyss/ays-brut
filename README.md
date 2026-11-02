# comparade26 — champagne tower

A realtime 3D fluid simulation of champagne filling a three-tier champagne tower, rendered
entirely by SDF raymarching. Target: an **8192-byte PC intro** for **ComParade 2026**
(Emmering/Munich, 6–8 Nov 2026), packaged the INCENDIUM way — WebGPU + a tiny PowerShell
dropper — not a native exe.

**Current state (25 Oct 2026):** the renderer, simulation, first-draft timeline, the
click-to-start screen and the sound engine (PADsynth pad, reverbs, liquid sounds, cork
pop) work. `build/intro.cmd` is **9 379 bytes, 1 187 OVER the 8 192 budget**, so features have
to be cut or simplified. Missing: the score (the chords, to be written by hand), any text, and
tier2 is still ~3 ms over the frame budget in its heaviest state. See *Roadmap*.

---

## Running it

The harness is a single self-contained file. Open it directly:

```bash
start "" "dev/champagne.html"
```

WGSL lives in `<script type="text/wgsl">` blocks read via `innerText`, **not** `fetch`,
precisely so `file://` works — a `file://` page has an opaque origin and cannot fetch its
own siblings.

To drive it from a tool that can't open local files (the Claude browser pane, for example),
or to use the timeline editor's save, serve it instead:

```bash
python dev/serve.py
```

That is `python -m http.server` on 127.0.0.1:8787 plus the editor's save (below).

Requires a browser with WebGPU: Chrome, Edge and Firefox all run both the harness and the
release (*Browsers*, below). Developed against an **RTX 4070**.

The release is `build/intro.cmd` (see *Build*). Double-click it: it serves itself on
http://localhost:8044/ and opens the default browser; click the page to start.

---

## What exists

### Geometry

**Coupe** — matched to the manufacturer's spec: 280 ml, 170 mm tall, 112 mm wide. The bowl
is a spherical cap, so capacity fixes the depth analytically:

```
V = π·h·(3R² + h²)/6    →   R = 56 mm, V = 280 ml  ⇒  h = 46.3 mm
```

Slender 5.2 mm stem and a thin foot, a plate 2.2 mm thick with a rounded rim, flat
underneath. Since 2 Nov it is three primitives and two smooth-min fillets: the stem into
the bowl (`stemK`, 12 mm) and into the foot (`footK`, 18 mm, which gives the flare), then
cut flat at the table. It replaced a stem profiled as a concave trumpet into the foot and a
solid ellipsoid knuckle under the bowl: -105 bytes, render no slower, the neck under the
bowl shorter than the knuckle was. The bowl's cavity is carved back out last, and is also
the bowl's inner face, so nothing the fillets do underneath can show up inside the bowl.
The tower is 1+4+9 = 14 glasses by SDF domain folding, 0.51 m tall, 0.336 m wide.

**Magnum** — 345 mm tall, 116 mm body, 30 mm neck, a flat base, **solid glass** since 31 Oct
(it was a 3 mm shell with the bore opened through the neck, and a punt for shot 2): photons
cross two surfaces instead of four, so its shadow carries a green caustic within their 4 legs,
and dark solid glass reads as a full bottle. Its silhouette is a radius-vs-height function
(`bottleR`), not a union of primitives: a champagne shoulder is an S-curve that a cone can't
make and a wide smooth-min erases. Of 345 mm the body is ~140, shoulder ~175 (span), neck
~105. The mouth is pinned to the pour emitter, so the bottle inherits the pour's wander.

### Simulation — hybrid, not Navier–Stokes

Free-falling liquid has no pressure gradient, so it needs no solver. The split:

| Part | Method |
|---|---|
| Stream, splash, spill, droplets | ballistic particles (32 768), no neighbour search |
| Liquid at rest in each glass | volume per glass (`dV/dt = inflow − overflow`), level its exact inverse + 2D wave field |
| Spill on the table | ends where it lands (a 384² height-field puddle was cut for size) |
| Mousse | foam deposited by impact into the per-glass grid, decaying |

This gives a razor-sharp meniscus (the thing particle fluids get wrong) and costs a fraction
of a real solver. Glasses spill 4 mm below the rim — at exactly the rim the liquid plane is
coplanar with the glass's cut plane and the coincidence renders as an opaque disc.

Spill leaves the rim **where the wave crest is highest** (best of 4 sampled azimuths), so a
glass overflows in a few wandering rivulets rather than an even curtain.

### Timing — one clock

Everything is a function of a single master clock: the sim advances in whole 1/60 s steps
whose index is derived from it, and the camera reads it directly. Nothing is a function of
the frame.

This matters because the intro has to hold sync with music for its whole length. Stepping
once per rendered frame ties the simulation's rate to whatever the renderer happens to
manage — measured on the previous build, **1.160× at 66 fps and 0.624× at 39 fps**. The slow
case alone would end a three-minute intro more than a minute behind the music.

| | sim seconds per wall second |
|---|---|
| one step per frame, 66 fps | 1.160 |
| one step per frame, 39 fps | 0.624 |
| master clock, 78 fps | 0.9996 |
| master clock, 39 fps | 0.9954 |

A frame that runs long leaves a deficit, and the deficit is **kept** and worked off over the
following frames, so a hitch costs nothing in the end. Catch-up is capped at 16 steps per
frame because the sub-step index wraps at 16 (it reaches the shader as the dispatch's grid
height), and reusing one would make two substeps share an RNG stream — the bug that used
to thin the pour. Past
`LAG_STEPS` (0.5 s) behind, the missed steps are given up rather than chased: in a demo,
staying with the music beats fluid continuity. Those events are counted in `probe.resyncs`
so the cost is visible rather than silent.

**All** of the simulation steps on this clock, not just the particles. The per-glass volume
ODE, the wave field and the table puddle sat in the per-frame build pass until the timeline
exposed it: a seek running 3000 steps in one frame filled exactly one glass, because the
bulk had advanced one frame's worth. At 60 fps it hid perfectly, since frames and steps
matched one for one.

Measured with everything in, at 1920×1080 on the heaviest shot:

| | |
|---|---|
| frame rate | 50.2 fps |
| show clock vs wall | 0.9979 |
| sim clock vs wall | 0.9979 |
| drift | one step, bounded |
| resyncs | 0 |

In the release (and the harness with `?gate=1`) the show clock is the **audio** clock:
the music's `currentTime` decides how many steps have happened, so the picture follows the
music rather than the wall. See *Start screen and music hookup*.

`?det=1` (implied by `?still=1`) swaps the wall clock for a fixed one so that frame N is
always step N. That makes a run reproducible on any machine, which is what A/B comparisons
need — `?still=1&warm=300` lands on `t = 5.0000` exactly.

### The timeline

`?show=1` hands the camera and the simulation speed to the timeline, driven by the show
clock. It is a list of **shots** (`SHOTS`, between `// SHOTS:BEGIN` and `// SHOTS:END`),
each with a name, a length, its own keys from t = 0 to t = its length, and optionally a
fade length (`fade`) and its own values for a few look sliders (`ov`). `flattenShots()` lays
them end to end into `SHOW`, the key list the show reads; a shot whose first key repeats the
previous shot's last one runs on from it without a cut. The build does the same flattening
in Python (`build/timeline.py`), so the release ships the same key list. The values a shot
sets for itself that the release carries - `shutter`, `pourRate` -
go into `SHOT_V`, `[from, shutter, pourRate]` with a row wherever they
change (in a shot that is black throughout, the look-only ones carry over from the shot
before: a row fewer each). The release picks the current row each frame; three of them are
live uniforms there. Any other per-shot value, and a shot's `fade` length, is still
harness-only, and the build warns when it leaves one out. The wander (`pourWander` 35,
`wanderSpd` 9) is global: the shots' values were close, and a global one also stops the
bottle jumping at a cut.
Keys are `[t, angle, dist, camY, tgtY, simSpeed, ease, fade, light, pour, tilt, table, env]`:

- **`fade`**: 0 black .. 1 full; every shot fades in and out.
- **`light`**: the key light's elevation in degrees; below 0 it is under the table, which
  then gets no light at all (the table is lit only by the photon map).
- **`pour`**: the share of the bottle's flow, 0 = not pouring; ramp it for a natural start.
- **`tilt`**: the bottle in degrees; 0 takes it out of the scene, ~118 pours.
- **`table`**: the table's height. Raised to a tier's base it hides the tiers below - rays
  stop at the plane, so they are never even marched: 0.341 shows the top glass alone on
  the table, 0.171 two tiers, 0 the whole tower. A millimetre above the tier below, whose
  rims are exactly at the next base and otherwise cut through the table as rings. Drops
  reaching the raised table end there, so hidden tiers get no spill (it would pour visibly
  into the table); tier 3 starts filling when the table drops. Photons that would start
  under the table are discarded - with the light low they lit the hidden tiers, which
  showed through as rings. Change it only in the black.
- **`env`**: the environment's brightness, 0..1 - the sky, the fill lights, the softbox
  and bokeh seen in the glass, the bounce-budget haze and the table's ambient. 0 leaves only
  what the key light lights through the photon map. All of it scales, key lobes included:
  with the light still under the table they showed in the glass, which then looked lit
  while the table was dark. Shot 1 brings it up with the light (0 → 0.1 at 2 s → 1 at 7.5).
- In the black between shots `simSpeed` runs at 8, so the tower fills while nobody watches.

- **Two keys sharing a `t` are a cut.** The later one wins at that instant, so the change is
  immediate instead of a one-frame blend.
- **`ease`** applies to the segment starting at that key: 1 for smootherstep in and out, 0
  for linear, so a long drift can run through several keys without stalling at each one.
- **`simSpeed` is keyed too**, and the sim clock is the integral of it over show steps, so a
  timeline that varies speed stays machine-independent.
- **Slow motion is real.** Below speed 1 each sim step covers *less* time (`u.dt`), one step
  per show step, so the liquid moves every frame. It used to run whole 1/60 s steps less
  often - at 0.25 the same frame showed four times, motion at 15 fps. Everything sized per
  step scales with the step: the waves (in velocity form, so the step can change), the
  mousse decay, the bottle's emission (its cadence counts sim time, not steps) and the
  motion streak, which shortens the way a high-speed camera's exposure does. At speed 1 and
  above nothing changed: whole steps, more of them when faster. Checked with `det=1`: the
  same sim time at 0.25 and at 1 fills the glasses to within a few percent (top glass 29.6
  vs 30.4 mm at 3.3 s, tier 2 starting to fill at the same moment).
- **The glass level used to jump.** The level was integrated as L += Q / A(L), and a
  spherical cap's area is nearly 0 at the bottom: the first drops in a step pushed the level
  to the rim, and almost none of the excess went on as overflow. The top glass read full
  0.3 s into the pour with 12 of its 280 mL, and how badly depended on the step - slow
  motion filled differently. The volume is now the state and the level its exact inverse
  (a cubic, solved in closed form). The top glass now takes ~6 s to fill at the default
  pour, which also means the first-draft timeline below and the measured drip rates in
  *Sound* were timed against the wrong fill and have to be redone (the sound once the
  timeline settles).
- **Drops resting on the bowl fell through it.** The bowl constraint put a drop's centre
  exactly on the interior sphere, and float rounding then made about half of those test as
  outside the next substep - unconstrained, so in an empty glass the stream ran straight
  through the bottom for the first ~1/4 s (hidden before by the level jump, which absorbed
  drops at the rim). The centre is now kept a drop radius inside, and in a nearly empty
  glass a drop reaching the bottom is absorbed.
- **The bottle glugs.** Air pushing in through the neck interrupts a real pour a few times a
  second. The emission cadence offers twice the drops and keeps a share p that pulses on sim
  time - 0.5 on average (the `pourRate` you set), swinging by `glug` (0.7) at about
  `glugHz` (3.5), the frequency wandering. At `glug` 1 the drops in flight swing between
  ~170 and ~1 130 against 520-690 steady; the fill rate is unchanged. The pour's bubble
  sound pulses with the same function. `pourWander` is now 20 mm.

The camera is driven from the table directly and only *mirrored* into the sliders for
readout. Routing it through them would quantise it to the slider step, and `dist` steps by
0.01 — visible stepping on a push-in that covers 0.01 in eight seconds.

Scrubbing with `showT` moves the camera immediately, which is what blocking shots needs, and
the fluid catches up on release. **Backwards means rebuilding the fluid from zero**, because
the simulation has no inverse — you cannot un-pour it — so it reloads with `?showt=`. **A seek
replays the timeline** a quarter second of show time per frame (full steps, as many as
needed): the pour, bottle and light reach the shader once per frame, and a seek that ran
the whole sim in one frame poured from t = 0 with the target's values. A seek to 50 s takes
a few seconds. It is representative, not bit-identical: spill azimuths differ by the RNG.

**The shot plan, first draft (26 Oct 2026)**, 64.25 s (shot 1 since stretched 1.5x):

| show s | shot | sim |
|---|---|---|
| 0 - 12.75 | 1. the top glass alone on the table (0.341); fades in dark, the light rises from 25° below the table to 45.6°, its shadow sweeping in, the environment coming up with it | empty, no pour, no bottle |
| 12.75 - 21.25 | 2. an orbit round it | |
| 21.25 - 23.75 | 3. black; the cork pops at `popT` 22.05 | the bottle appears, tilted in |
| 23.75 - 35.75 | 4. the pour in slow motion (0.25 throughout): the bottle tips in, the flow starts at 24.25 s, the top glass fills | top glass a little under 3/4 full |
| 35.75 - 37.25 | black: the table drops to tier 2 (0.171), sim at 8x | top glass overflows, tier 2 fills |
| 37.25 - 47.75 | 5. an orbit of the two tiers (sim 1.5x) | tier 2 nearly full |
| 47.75 - 49.25 | black, sim at 8x | |
| 49.25 - 60.25 | 6. tier 2 in slow motion (0.25), spilling onto the table | tier 2 full and spilling |
| 60.25 - 61.75 | black: the table drops to the floor, sim at 8x | tier 3 starts to fill |
| 61.75 - 64.25 | 7. to be decided; for now the whole tower, wide | tier 3 about half full |

The sound has not been re-timed to it yet (the drip rates still follow the old measurement).

#### The timeline editor (`?edit=1`)

`python dev/serve.py`, then http://localhost:8787/champagne.html?edit=1. No sound is rendered
in the editor at all, and the show is on.

- **Above the strip**: the timeline's speed as an orange curve (log scale, lines at 0.25,
  1 and 8) and its fade in grey, across the whole show; under them a diamond for every key -
  filled when the move from it is eased, yellow-edged at a cut. Hover a diamond for the key's
  values and what moves on the way to the next key; click it to jump there.
- **The strip** at the bottom: every shot end to end, each as wide as it is long. Click in
  one to select it and play from the point clicked; ctrl- or shift-click to add to the
  selection. **`.`** steps one frame (and pauses if playing); **`h`** hides every overlay
  (HUD, panels, timeline, buttons; errors stay) and brings them back. `*`
  marks a shot that differs from what was last saved; hover for its times, fade and values.
- **len** sets the selected shot's length in seconds; **scale** / **-10%** / **+10%** stretch
  every selected shot, keys and all. The shots after it move; the playhead stays on the same
  moment of the shot. **fade** sets the selected shot's fade in and out, in seconds (the same
  at both ends, whatever its length; 0 cuts hard; empty: its keys' fade, as before).
- **loop** plays the selection over and over. The simulation's state at a shot's first frame
  is kept on the GPU (~20 MB a shot, up to 12 - the whole show), so each pass, and each jump back to a
  shot, starts there at once instead of replaying the show from 0. It is replayed only when
  something it depends on has changed: an earlier shot, or a global that changes the
  simulation (`ED.SIM`).
  Playback and replays stop on every shot's first frame, so every start passed is kept -
  a frame that took two steps used to skip one, and a loop of that shot replayed from 0.
  When a replay from 0 is unavoidable, the strip says so.
- **rec**: slider moves go into the shot under the playhead. The timeline's own sliders
  (angle, dist, camY, tgtY, lightEl, botTilt, tableY, envAmt) shift all of that shot's keys
  by the move, so a camera move keeps its shape; `speed` multiplies them instead (0.25 -> 0.5
  doubles every key of the shot, a ramp keeps its shape); the look sliders a shot may set for itself
  (lightAz, expo, cgain, shutter, bkLife) and the bottle's wander
  (pourWander, wanderSpd) and flow (pourRate) - `ED.PER_SHOT` - become the shot's
  own values. Everything else is global, rec or not: anything that changes the simulation
  would make a shot's start depend on the shots before it, and the debug switches are not
  looks. With rec off, the timeline still drives its own sliders.
- **Marks**: a slider's label is blue when its keys in this shot differ from the saved ones,
  red when the shot sets its own value, yellow when its global value is not the default
  (`?param=` values count). The ↺ at the end of a marked row puts it back.
- **undo / redo**: every change, sliders included - buttons, ctrl+z, ctrl+y or ctrl+shift+z.
- **Typing a value**: the number beside any slider is a field - click it, type, Enter (or
  click away) applies, Esc cancels. It goes through the slider, so it snaps to the slider's
  step and range and is recorded, undone and marked like a drag.
- **save** writes the shots and every global you changed (not those that only came from the
  URL) into `dev/champagne.html`: the shot block, and each slider's default in `SPEC`. Commit
  it like any edit. Under a server without the save (`python -m http.server`) it downloads
  `timeline.json` instead; `python dev/serve.py --apply timeline.json` writes that in.
  The server re-reads `build/timeline.py` on every save, so a rule change there (a slider
  made per-shot) needs no restart; a change to `dev/serve.py` itself does.

**speed** is the timeline's simulation speed: during the show the slider reads it out,
without the show it is the speed. `simSpeed` - a dev multiplier on top of it, 0 to freeze the
sim for A/B checks - is out of the panel: a URL parameter only, its row shown when the URL
sets it to anything but 1.

Going back in time no longer reloads the page anywhere in the harness: it rewinds in place,
as the rewind button does (with `?gate=1` it still reloads, the show running on the audio
clock).

Tests:

```bash
node --test "dev/tests/*.test.mjs"
python -m unittest discover -s dev/tests -p "test_*.py"
```

The first runs the editor's logic (pure functions, loaded straight out of the harness) and
checks its flattening against `build/timeline.py` bit for bit; the second the shot table's
reading and writing and the save server, on a copy of the file. The UI itself is tested in
the page: `?edit=1&edtest=1&det=1` clicks, drags, loops and saves (a dry run - the file is
never written) and leaves `EDTEST PASS` in the console and `__probe().edtest`; the pane has
to be on screen.

### Lettering

MAISON / ABYSSE / MILLESIME / 2026 stacked over the standing bottle in shot 2, a line a
second from 1 s in; CHAMPAGNE / POUR / LES / MASSES the same over the tower in shot 8,
from 10 s in. Josefin Sans SemiBold
capitals, which no PC at the party will have installed and which cannot ship inside 8 KB.
Josefin is geometric and monoline, so each capital is redrawn as a pen path: a few lines,
ellipse arcs and curves, drawn with a pen as wide as the font's stem (116 of 1000 units),
butt ends, mitred corners, and set wide (150 units between letters) for a luxury feel.
Each line is one SVG path over the picture, already in its place in a 1600 x 900 box (0 0
the centre; caps ~7% of the screen's height): `TEXT` is groups of lines, and the tool
stacks each group's lines 110 apart round the middle. The browser draws them, so there is
no font, no glyph code and no layout code.

`TEXT_CUES` times the groups: `[shot, from, to, group]`, seconds from the shot's start, so
the words stay with their shot when shots are stretched or moved (`to` past the shot's end
means to its end). The group's first line shows at `from`, each next one a second later;
each fades in and out over 1 s, and with the picture's own fades. The build resolves the
cues to show times for the release, as it flattens the shots; the editor re-resolves them
whenever the shots change. `?text=1` holds every word.

`python dev/tools/strokefont.py` holds the glyphs (in the font's units, read off its
outlines), the groups and their layout, writes them into the harness's `TEXT` block, and writes
`dev/tools/strokefont.html`, every glyph over the real outline to compare.
`python dev/tools/glyphs.py` cuts the 600 weight out of the variable font in `dev/fonts`
(from Google Fonts' repository, with its OFL) and dumps the reference outlines. A new
letter needs its strokes added there.

Cost: ~730 bytes (measured 30 Oct, before the changes below), ~450 of it the paths. Each
letter's origin snaps to the grid before its own coordinates round, so every copy of a
letter is the same string and brotli stores it once. Measured 31 Oct, intro.cmd:
- MILLESIME added in the old per-word layout: 10 464 -> 10 480.
- Groups with the positions baked into the paths, one cue per group: 10 470.
- Half-turn arcs as one arc each (an O is two arcs, not four): 10 440.
- The overlay's style is the canvas's own string (`position:fixed;inset:0;width:100%;
  height:100%`), which brotli stores once: 10 408. `pointer-events:none` is harness-only
  (its panels sit under the overlay). In the release a click on the overlay still bubbles
  up to the window's start handler.
- The fades lean on CSS clamping opacity to 0..1: a word's opacity is just
  `min(t - from - k, to - t)`, and the picture's fade is the overlay's own opacity: 10 406.
- No `stroke-miterlimit`: the default limit of 4 already mitres every corner these letters
  have (the sharpest, M's top corners at 35 degrees, need 3.3): 10 398. A new letter
  with a corner under ~29 degrees would get a flat tip; then it comes back.
- Fullscreen goes on the body, not the canvas: fullscreen shows only that element and its
  contents, and the overlay beside the canvas vanished in Chrome (10 400). The browser pane
  never goes fullscreen, so check text in the release in a real browser.
- A 3x coarser grid at the same size on screen (`GRID` in the tool): most coordinates one
  digit. Half-turn arcs keep only their radius ratio (`a1 1` for a circle) - SVG scales radii
  too small for their endpoints up to fit, so they stay exact on any grid, where rounded radii
  made an O pointed; the 2 keeps half steps (`FINE`). 1.5x saved 5, 2x 9, 3x 33, 4x and 6x
  more but bent the 2: 10 367.
- The overlay is in the release's PAGE, after the canvas, written by the build
  (`timeline.text_overlay`); the JS keeps one [from, to] per line: 10 313. The canvas needs
  its end tag there, or the overlay is the canvas's fallback content and never drawn.
- `t` for curves whose control point is the previous one mirrored exactly: 10 299.
  Allowing it within a grid step saved 7 more, but the S looked worse.
- Dropping `opacity=0` (10 292) relied on a white page behind the words. Firefox draws an
  unpainted WebGPU canvas black, so its start screen showed the words and hid "click".
  Now the canvas is `hidden` until the click and the words keep `opacity=0`: **10 306**.
  Other browser intros do the same in other ways: INCENDIUM opens on plain "Click" text
  above a small inline canvas that only turns full-screen in the click handler; elusive
  (bypass, Deadline 2023) puts a native `<button>CLICK` on the page with the canvas
  zero-wide inside it until fullscreen.
- Re-checked: a glyph table laid out at runtime is still worse, 10 573 against 10 470.
  Brotli already stores each repeated letter once, so the table only adds layout code.

### Sound

`song()` renders the whole soundtrack once, before "click" appears, with an
`OfflineAudioContext`; the show clock is then the audio clock (*Timing*). Seeded, so it
sounds the same every run. Three parts:

- **The pad** plays `SCORE`: chords as `[start s, length s, MIDI notes...]`. **The score is
  written by hand** - the party bans generated music - and is empty in the repository;
  `?testpad=1` adds one plain held chord in the harness (dev-only lines, never shipped) to
  judge the timbre by. The pad is PADsynth-lite (*The pad*, below): each note plays one
  looped table of smeared harmonics twice, panned apart, through a lowpass (`padCut`),
  with `padAtk`/`padRel` swells and the notes of a chord up to `padStagger` apart.
- **The liquid**: the bubble model (*The bubble model*, below) - drips, splash clouds, the
  pour and the fizz, written sample by sample (as audio nodes, ~1300 drips took 9.5 s to
  render; as plain loops, milliseconds). Every track follows the timeline. The bubbles of
  each are a Poisson process whose rate is per SIM second, so a show second holds `speed`
  of them and slow motion thins them out with the picture. Re-done for the shot plan on
  31 Oct from a run of the show on the audio clock (glass levels, and particles alive in
  the spill pool): nothing is poured before the bottle tips in (the pour column, 24.9 s),
  so shots 1-2 have only the pad and the cork; the top glass reaches its spill level at
  ~35 s (spray ~1600 drops), tier 2 at ~52 s (~3500), and shot 8, with its own
  `pourRate` (250 since 2 Nov, *Shot 8's pour and the frame budget*), sends twice the
  stream and ~6 200 drops. The drips and splashes follow that spray as 1.5 s ramps (x1, x2,
  x4), the pour the pour column (x2 in shot 8), the fizz one share per tier on the table once the pour has begun. Loudness follows
  the camera's distance (1 on the macro shot, quieter on the wide ones) and the fade, so
  the liquid drops out in the blacks, where the sim runs at 8x. +45 bytes with the
  packer's default state on both sides (+43 shipped). Re-measure the ramp times when the
  shots change what the tower does when.
- **The reverbs**: convolution, each impulse two channels of noise decaying to -60 dB.
  The pad goes into a hall (`verbLen` 4 s, `verbMix`), the liquid into a short room
  (`fxVerbLen` 0.6 s, `fxVerbMix` 0.25): one 4 s hall for everything made the drips sound
  like a cave. +21 bytes for the second one.

The level is a fixed `master` gain (0.9), not normalised: the harness shows the mix's peak
in the audio column's header, red with "CLIPS" past 1 - then turn `master` down. (It was
normalised to a 0.9 peak; scanning and scaling the 6 M rendered samples cost 25 bytes.)
Render time: ~3 s.

**To hear it**, press *hear audio* in the harness panel: it reloads with `?gate=1&show=1`
and the audio sliders in the URL; click the page. Add `&testpad=1` for the test chord.
The harness then plays the soundtrack as four **stems** - pad, stream, drips, splashes -
through a live hall, and the `trk*` boxes switch each track (and the reverb) on and off
while the show runs. Letting go of an audio slider re-renders just the stems it touches
(the pad takes ~2 s, the rest a fraction of that) and swaps them in at the playback
position; the peak shown is then re-measured. With everything on it is the release mix:
the stems times `master` sum to it within 3e-7. The release itself renders one mix and
ships none of this (drips and splashes having a buffer each cost 18 bytes).

The start box says what is happening: "rendering audio..." (about 10 s in the harness,
which renders the mix and two stems; the other six stems are the mix render's own sample
buffers), then "click here to start: show + sound". Only that box starts the show, so the
panel stays usable meanwhile; the harness does not go fullscreen (`&fs=1` does, as the
release does). The track boxes come along in the URL on "hear audio".

#### The bubble model (the liquid, decided by A/B)

The first drips sounded synthetic, and for a reason the literature names. K. van den Doel,
"Physically based models for liquid sounds" (ACM TAP 2005), finds that liquid sound is
bubbles ringing: a bubble of radius r rings at the Minnaert frequency 3/r Hz (r in m),
damped by d = 0.043 f + 0.0014 f^1.5 - so small bubbles are short high ticks and only big
ones ring - and one near the surface rises in pitch, f(t) = f0 (1 + xi d t), with xi ~0.1
for a falling drop. The first drips rose 2-4x over 50 ms and rang 15-65 ms whatever their
pitch: the paper's "blowing through a straw". Real liquid is a population: sizes from rates
1/r^gamma (0-3 streams, above ~5 rain), loudness D r^alpha with D = rnd^beta (most bubbles
deep and faint, beta ~10), the rise only on the loud near-surface ones, and the smallest
bubbles (~0.2 mm) essential - without them it turns into a nozzle. It was built as four
tracks next to the first liquid (a stream hiss, chirping sines, high-passed noise bursts),
compared by ear, and replaced it. All four use one bubble function:

| track | what it is | sliders |
|---|---|---|
| `drips` | per drip, one bubble from the population and 0-2 smaller ones as it breaks up | `dripGain` |
| `splashes` | per splash, a cloud of `splashN` bubbles over `splashLen`, densest at the impact | `splashGain`, `splashN`, `splashLen` |
| `pour` | the stream as `pourBub` bubbles per second (up to ~1000/s is dripping to an intimate stream) | `pourGain`, `pourBub` |
| `fizz` | CO2 bubbles bursting at the surface: 0.15-0.5 mm, every one heard, pitch rising as the cavity collapses (Poujol et al., "Sound of effervescence", Phys. Rev. Fluids 2021) | `fizzGain`, `fizzRate`, `fizzXi` |

Shared: `bRmin`, `bRmax`, `bGamma`, `bXi`, `bRiseCut`, `bBeta`, `bAlpha`. Toggles: `trkDrips`,
`trkSplash`, `trkPour`, `trkFizz`. Dropping the first liquid saved 262 bytes and halved
the render (3.2 -> 1.9 s for a full mix); the drip and splash times kept their process,
though not their exact moments (the first liquid's noise drew from the same random
sequence).

Two corrections after the first listen. **Loudness is relative to the largest bubble**
(`(r / rmax)^alpha`): with r in mm, one rare 7 mm bubble near the surface peaked at 2.2, and
since the mix is normalised to its peak, that one drip turned the whole soundtrack down
2.5x. And **a drip's own bubble is evenly loud**: the paper's depth skew (`D = rnd^beta`,
beta 10) is for crowds of bubbles - on the one bubble a falling drop makes it left nearly
every drip inaudible, peak 42x the RMS. Secondary bubbles, splash clouds and the pour keep
it. Defaults re-levelled to the old tracks, raw on the macro shot (RMS / peak): `splash2`
0.016 / 0.40 against splashes 0.015 / 0.24, `pour2` 0.026 / 0.31 against the stream's
0.007, `drip2` about 0.02 / 0.5 against drips 0.051 / 0.39 - bubble drips are short ticks,
and matching the old RMS would have put their peaks over everything. `fizz` 0.009, pad 0.063.

#### The cork pop

The show opens on the bottle being opened, with no picture for it, so the sound alone has
to say what it is. Track `pop`, at `popT` (0.5 s), in three parts:

- **the crack**: a millisecond of broadband noise as the gas jet leaves the neck - at about
  twice the speed of sound (Liger-Belair et al., *Science Advances* 2019, high-speed
  imaging of uncorking);
- **the plop**: the open neck ringing as a Helmholtz resonator (`popF`, a few hundred Hz),
  gliding there from `popGlide` x popF in ~25 ms as the cork clears it - below 1 rises,
  the "plopp" - for `popDecay`, over a thump of the gas expanding that falls like a kick
  drum from twice `popThumpF` (60 Hz) to it, for `popThumpLen` (`popThump`, 1.2: "the pop
  needs more bass");
- **the rush**: high-passed noise fading over `hissLen` as the rest of the gas leaves
  (`hissGain`).

No study quantifies the pop's own sound, so these are physics-shaped starting points to
tune by ear. Peak 0.985 (raw) with the deeper thump: the pop is the loudest moment, so it
is what clips first if `master` or the pop go up. +90 bytes, +18 for the kick-like
thump.

#### Audio size pass: 9 476 -> 9 394

| change | bytes | sound |
|---|---|---|
| one random-generator factory for the three sequences; one exact 2 pi (`TAU`) | | same sequences |
| the bubble-size formula without its gamma = 1 special case (folded away in the release) | | same |
| no unused pitch-rise parameter on the bubble population | | same |
| pad playback rate as 2^((m - 57) / 12) | | same |
| *together* | **-57** | levels within 0.2% |
| a fixed `master` gain instead of normalising the rendered mix | **-25** | the same at 0.9 |

The exact 2 pi also fixed a bug: the PADsynth table used 6.2832, so over one 2.7 s loop the
top partials drifted up to 0.2 rad and the seam clicked every loop. The first liquid
tracks were left alone in this pass; removing them afterwards saved 262.

#### The pad: PADsynth (decided by A/B)

The first pad - five detuned sawtooth voices per note - sounded synthetic for the usual
reasons: the same even detune on every note, so every note beats alike; every voice
starting at once; nothing moving but one filter LFO. Two answers were built as tracks and
compared by ear; **the PADsynth pad won and is the only pad now** (the saw pad and its
upgrade are gone; this records what was tried):

- **The saw pad, upgraded** - each with its own slider, 0 = off:
  - `padRand`: a random detune per voice on top of the even spread, so no two notes beat
    the same way (string machines tuned every oscillator differently, after the human
    players they imitated);
  - `padDrift`: every voice drifts on a slow sine of its own rate (0.05-0.25 Hz), a few
    cents - inaudible alone, mixed it makes the voices phase like analog voice cards
    (practitioners' advice: tiny depth, very slow, different per voice);
  - `padStagger` (both pads): the notes of a chord start up to 0.15 s apart;
  - `padEns`: the Solina String Ensemble's chorus - three short delays swept by a slow
    (~0.6 Hz) and a fast (~6 Hz) LFO, panned left, centre, right.
- **`pad2`, PADsynth-lite.** Nasca Octavian Paul's PADsynth (ZynAddSubFX) treats each
  harmonic as a band of frequencies with random phases and renders one long table that
  loops - "the phases are random, and this is the key". Lite: no FFT; 24 harmonics, each
  a band of 12 sines `padBw` cents wide (scaling up the harmonics by `padBwScale`), every
  sine a whole number of cycles per 2.7 s loop, summed with a rotating phasor. Each note
  plays the table twice, from different points of the loop, panned apart.

Bytes, measured by building each variant: the upgrade +136; PADsynth *instead of* the saw
pad +111 - so the one that sounded better was also the cheaper. Shipped: 9 476, the
predicted figure, 278 less than with both. The pad's level matches the old one (RMS 0.067
against 0.063). Rendering the pad costs ~0.8 s; the upgraded saw pad cost 2.2 s, mostly in
its modulated delays. The pad has its own random sequence, so editing the score never
reshuffles the drips.

The harness also has **rewind** (top bar): back to t = 0 without reloading. The simulation
lives in buffers that start zeroed plus a few clocks, so clearing both is exactly a fresh
load; with sound on the stems restart with it and nothing is rendered again. With sound
on, **pause** suspends the audio too: the show runs on the audio clock, so both stop on
the same sample and resume together.

### Rendering

Nearest-particle narrow-band distance field → sphere trace. Particles deposit a **swept
capsule**, not a sphere: over one shutter interval a falling drop traces a streak, and
recording it as a point makes a pour read as a string of frozen beads.

- **Nested dielectrics** by medium priority (`mediumAt` → air / glass / champagne / table /
  bottle glass), not by authoring separate interface surfaces. The liquid deliberately
  **overlaps 0.5 mm into the glass shell**; coincident surfaces let float noise decide which
  medium wins, which bands into rings.
- Beer–Lambert gold with a cheap single-scatter term so depth glows instead of going black.
- **Photon-splat caustics**: rays from the key light refracted through glass and champagne,
  atomically splatted into a 768² table map, blurred, with temporal decay. These carry the
  *direct* light too, so shadows come free — and `cgain = 0` leaves the table ambient-only.
- Bubbles are carved out of the liquid SDF as real geometry, so light refracts through each.
- Reflections are the environment lookup. A traced reflection off the bulk champagne
  surface and the bottle was dropped on 2 Nov (*The traced reflection*).

### Pass graph

```
sim        N steps per frame, N from the clock — everything that advances state:
           simParticles → waveUpdate ×3 (the first one's first 14 threads: the glass volumes)
build      once per frame — a rendering structure, needs only the final state:
           scatterFine (+ far-field seeds) → jfaCoarse ×5
           → resolveFine (+ packs the far field for the render, clears the band, blocks
             and seeds for the next frame, fades the photon map)
photon     photons → causticBlur
render     camera raymarch + post (one full-screen triangle)
```

Seven compute entry points. Each dispatch passes its small index (sub-step, flood pass, the
wave dispatch that also updates the glasses) as the height of its grid,
`num_workgroups.y - 1`, so no per-dispatch uniforms exist.

The split matters: the puddle, glass volumes and waves used to live in `build` and so
advanced once per *frame* while the particles advanced on the clock. See *Timing*.

### Grids

| Field | Size | Cell |
|---|---|---|
| Particle narrow band | 320³ | 1.94 mm |
| Coarse nearest-particle (JFA) | 32³ | 19.4 mm |
| Caustic map | 768², ±0.55 m | 1.43 mm |
| Per-glass wave + foam | 32² × 14 | — |

Domain: `(-0.31, -0.015, -0.31)`, 0.62 m cube.

---

## Performance

### Target hardware

The compo PC, confirmed 24 Oct 2026:

| | |
|---|---|
| GPU | ASUS GeForce RTX 5070 Prime OC White |
| CPU | AMD Ryzen 7 7800X3D |
| RAM | Kingston FURY 16 GB DDR5-6000 |
| Board / disk | ASRock B650 Steel Legend WIFI, Samsung 990 Pro 1 TB |

Development is on an **RTX 4070**. Against it the 5070 brings +4% shaders, +1% clock, +6%
FP32 and +33% memory bandwidth (GDDR7), plus a larger L2; reviews put it ~20% ahead at 1080p
raster. This frame is mostly ALU with incoherent gathers out of a 125 MiB grid, so call it
**15–20%** — an estimate from specifications, not a benchmark of this workload.

That fixes the number to aim at: 16.6 ms on the 5070 is about **19 ms on the 4070**.

CPU and disk don't matter here — one draw call, everything GPU-side.

The compo runs at **1920×1080**, confirmed with the organisers.

### Where it stands

RTX 4070, 1920×1080, everything on, at the **heavy natural state**: `det=1`, run to step
3120 (t = 52 s, tower overflowing), `simSpeed` 0, then each camera preset in turn. Median
of 18 samples, measured 24 Oct 2026 after the profiler work (packed far field, exact block
reach, plane-bounded march, local puddle bound). Frozen, so `sim` is 0. Running, the sim
adds **0.52 ms per step**: one per frame at 60 fps, two when a frame runs long.

| Shot | build | photon | render | **total frozen** | **+ sim** | vs 19 ms |
|---|---|---|---|---|---|---|
| tower | 2.10 | 1.64 | 7.60 | **11.3** | 11.9 | passes, 7 ms spare |
| bottl | 2.16 | 1.64 | 8.45 | **12.2** | 12.7 | passes |
| top | 2.10 | 1.64 | 11.01 | **14.8** | 15.3 | passes |
| macro | 2.10 | 1.64 | 11.93 | **15.7** | 16.2 | passes |
| pour | 2.10 | 1.64 | 14.75 | **18.6** | 19.1 | on the line |
| **tier2** | 2.16 | 1.64 | **18.28** | **22.0** | **22.5** | **~3.5 over** |

Everything but `render` is a flat ~4.3 ms (build 2.1, photons 1.6, sim 0.5). It was 3.8;
build grew with the deterministic far field, and photons shrank when they stopped at the
table. `render` swings 7.6–18.3 with how much glass, liquid and spray the camera looks
through.

Five of six shots are at or under 19 ms. `tier2` is the one left, and it is
state-dependent: 160 steps later, with more spray in view, the same camera read 20.3 ms
render. The earlier table (fill 88, a much lighter state, before this work) had tier2 at
26.5, pour 20.8, top 19.5. Those numbers are not comparable to these, and the gain on
tier2 in the heavy state is 29.9 → 22.0.

On the compo machine's RTX 5070 (~15–20% faster) the 16.6 ms budget corresponds to the
19 ms here, so the same standings hold. The timeline can stay on every shot except tier2
in heavy spray. To make tier2 fit: cut ~3.5 ms there, avoid holding on it while the spill
is at its densest, or take the `bounces` trade on that shot only (about 1.1 ms per bounce,
visible on the rim glints).

### Profiling a whole run

The table above freezes one state. A whole run shows the show as it plays: every frame of
the timeline, with the sim running and the spill as it really develops. On 31 Oct, RTX 4070,
1920×1080, 60 Hz, the audio clock (`dev/profiles/1080p-2026-10-31.json`, 5 488 frames):

| shot | GPU median | p95 | frames over 19 ms |
|---|---|---|---|
| 1 glass, 2 orbit, 3 pop, 5 tiers | 6–11 | 7–12 | 0 |
| 4 pour | 10.6 | 18.3 | 12 of 888 (the end, full and overflowing) |
| 6 tier 2 | **19.7** | 20.6 | **427 of 564** |
| 7 tower | 13.0 | 13.6 | 0 |
| 8 | **19.1** | **24.1** | **611 of 1061**, rising to ~25 ms at the end |
| the 8x blacks | 16–20 | 18–27 | the sim pass: 8 steps a frame |

Render is the bulk in every heavy stretch; the sim matters only in the blacks, and nobody
sees those frames. Shots 6 and 8 are the ones over the target here; 8 holds the whole tower
overflowing for 20 s, and its cost keeps climbing with the spray.

To record one: `python dev/serve.py`, then `python dev/profiles/save.py <name> --gpu "..."`
(it waits for the data), open
`http://localhost:8787/champagne.html?gate=1&show=1&master=0&w=1920&h=1080`, paste
`dev/profiles/record.js` into its console and keep the page on screen for the ~100 s the
show runs. It clicks start, records a row per frame (show time, frame interval, the four
passes' GPU ms, sim steps, live drops, the top glass's level), pauses the renderer at the
end and sends the rows; `save.py` writes `<name>.json` and `<name>.csv`. Look at it in
`http://localhost:8787/profiles/view.html`: the passes stacked over show time, shots
marked, the frame interval, both budget lines, a hover readout and a per-shot table. The
GPU times come from timestamp queries, one frame at a time - at 60 Hz a light frame leaves
the GPU idle and it clocks down, so the light shots read a little high; the heavy ones are
real.

### Shot 8's pour and the frame budget

On 2 Nov, shot 8 (25 s by then) was measured over whole deterministic runs (`det=1`) at
the release's 1600×900, GPU ms per frame, for its own `pourRate`:

| `pourRate` | median, first 12 s | median, last 12 s | worst p95 (2.5 s window) |
|---|---|---|---|
| 5000 (was) | 19.3–20.6 | 24–26 | 26.7 |
| 2000 | 19.2–20.6 | 24–26 | 26.7 |
| 1000 | 19.1–20.5 | 24–26 | 28.7 |
| 500 | 19.0–19.9 | 19.5–21.8 | 23.9 |
| **250** (now) | 18.5–19.1 | 18.5–19.1 | 19.7 |

Above ~1900 drops a step the bottle's slice (then `botShare` 0.5 of 65 536, a drop holding
its particle ~17 steps) was the limit, so 5000 never applied; 1000 halved the stream and cost
the same. The jump at ~88 s is the bottom tier overflowing onto the table near the camera:
render 11 -> 16 ms, photons 6 -> 7.6. At 250 enough volume never arrives for that, and the
spray is ~6 200 drops instead of ~21 000. 250 is also about the floor of this lever: the
shot costs ~18.5 ms with little spray (render ~10.3, photons ~6, build ~2), so it sits on
the 19 ms line, not under it.

With the pour fixed, the counts settled the pool (2 Nov). A natural `det=1` run peaks at
~1 900 drops in the stream and ~6 800 in the spill, so 65 536 particles were four times
what any shot uses: the pool is 32 768 and `botShare` one global 0.17 (~5 570 for the
bottle, a stream of up to ~330 drops a step). Run again at that size, every glass
reached the same level within a millimetre at the same second, and the spill and
stream peaks matched. -6 bytes for the shot table's column; half the particle buffer.

### Exporting a video

```bash
python dev/export.py
```

writes `build/intro.mp4`: the whole intro rendered at 3840×2160, scaled to 1920×1080,
60 fps, H.264 at 20 Mbit/s (30 peak) with the soundtrack in AAC. It never skips a frame or
a simulation step, whatever the machine: `?det=1` gives every frame exactly one show step,
which is what the release takes at a steady 60 fps, and in `?export=1` the page starts the
next frame only once this one is read back and handed over, instead of on
`requestAnimationFrame`. A slow GPU only makes it take longer.

It serves `dev/` on 127.0.0.1:8796 and opens the harness in the default browser (any WebGPU
browser; `--no-open` prints the URL instead). The page renders the soundtrack first
(`song()`, as a 16-bit WAV to `/audio`), then for each frame draws the 4K canvas down to
1080p in a 2D canvas (smoothing 'high': at exactly 2:1 an even box filter), composites the
lettering - it is an SVG overlay in the DOM, not in the canvas - from the overlay's own
state, and sends the raw RGBA over a WebSocket on port 8797; the script pipes it into
ffmpeg. The audio starts one frame in, since the page's frame k already shows show step
k+1. RGB goes to YUV with the BT.709 matrix and is tagged so - swscale's default is BT.601,
which every HD player would decode with the wrong colours.

Options: `--seconds 30` stops at that show time (a test; the default is the end plus a
second of reverb), `-o`, `--render 3840x2160`, `--size 1920x1080`, `--bitrate 20M`,
`--maxrate`, `--bufsize`, `--preset slow`. The rate is fixed at 60: the simulation steps at
60 Hz, and any other rate would not be the intro. Needs ffmpeg on PATH and
`pip install websockets`. Keep the browser window visible: nothing depends on frame
timing, but a hidden tab may be throttled to a crawl. ffmpeg's warnings go to
`build/intro.ffmpeg.log`.

The frames go over a WebSocket because a `fetch()` POST of 8 MB took the browser
150-500 ms to upload (curl: 4 ms), which made the upload, not the render, the export's
speed: 2.3 frames/s, against 13 with the socket on the light first shot.

### What each lever actually buys

> Historical: measured before the profiler work, at fill 88, so the absolute numbers are
> superseded by *Where it stands* above. What it shows about which knobs matter still holds.

Measured on `tier2` at fill 88, the worst shot. Baseline render 22.61, total 26.48:

| Change | render | total | saves |
|---|---|---|---|
| `bounces` 10 –> 8 | 20.45 | 24.25 | 2.2 |
| `bounces` 10 –> 6 | 17.76 | 21.56 | 4.9 |
| `bounces` 10 –> 4 | 14.68 | 18.61 | **7.9** |
| `parts=0` (no particle field) | 15.01 | 18.48 | **8.0** |
| `bubbles=0` | 21.23 | 25.03 | 1.5 |
| `nphoton` 65536 –> 16384 | 22.68 | 26.02 | 0.5 |
| `steps` 160 –> 120 | 22.54 | 26.35 | 0.1 |
| `refl=0` | 22.68 | 26.48 | 0.0 |

Four of those are worth knowing because they are **not** levers. Step count does nothing —
the march is bounce-limited, not step-limited, so rays terminate on hits long before the cap
and lowering it only risks artifacts. Reflections are free. Photons are nearly free, so the
caustics cost almost nothing to keep.

**`parts=0` is not a lever either, and reading it as one was a mistake.** It does not merely
stop sampling the particle field: it removes the particle *geometry*, so rays no longer march
around the stream or refract through droplets, and they finish in fewer bounces. That 8 ms is
what the spray costs to draw, not overhead waiting to be optimised away.

The test that settled it: a coarse occupancy grid (below) now skips the eight narrow-band
fetches wherever the band is provably empty, leaving the geometry untouched. If the 8 ms had
been fetch cost, that would have recovered most of it. Measured:

| Shot | before | after | saved |
|---|---|---|---|
| tier2 | 26.41 | 25.49 | 0.92 |
| pour | 20.84 | 20.77 | 0.07 |
| tower | 13.57 | 13.76 | –0.19 (noise) |

So the eight scattered reads were already close to free — they are coherent for coherent
rays, and most of the 125 MiB buffer holds the same clamped BAND value, which caches well.
The skip is kept because it is exact and helps the one shot that fails, but it is marginal
and a fair candidate to drop during the size squeeze.

**That leaves `bounces` as the only real lever**, at ~1.1 ms each, and it trades the quality
it was raised to 10 to protect (checkerboard breakup deep in the tower). `tier2` at 25.5 ms
needs ~6 ms, which is most of the way back to the artifacts. The better answers are probably
not in the renderer: a throughput early-out already exists at `tp < 0.02` and could be raised,
and the timeline does not have to hold on `tier2`, which is the only shot far over.

**Measure with the window on screen.** The same tier2 shot read 36–40 ms with the browser pane
hidden — roughly 3× inflated, because a background page runs at ~2 fps and the GPU
downclocks between frames. An earlier 17.7 ms figure was taken at the pane's own 1100×880 and
was never comparable to the budget at all.

### The traced reflection

> Dropped on 2 Nov 2026, with its `rtrace` control: -87 bytes shipped (-125 with the packer's
> default state) and render time. By then it traced only off the bulk champagne and the
> bottle, and switching it off changed 0.05-0.8% of a shot's pixels by more than 4 levels -
> the bottle's edges (shot 2, the most), the far rim of the champagne surface at grazing,
> drops landing on it. The history below is why it existed.

Measured in the spill state (autofill, tower overflowing), 1920×1080, RTX 4070:

| shot | glass + drops traced (before) | bulk liquid only (`rtrace` 1) |
|---|---|---|
| pour | 34.1 | **22.7** |
| tier2 | 39.1 | **28.6** |
| tower | 23.8 | **18.2** |

The traced reflection was 41% of the render pass. It exists for one artefact — the
champagne's free surface mirroring the sky as an opaque disc near grazing — and now runs
only there. Droplets and glass use the environment lookup; the visible difference is a
slightly more silvery spill curtain. `rtrace` 2 restores the old behaviour for comparison.

### Anatomy of the heavy tier2 frame

`det=1`, run naturally to step 3120, `simSpeed` 0; 1920×1080, RTX 4070. Before the packed
far field below: render 24.8, total 29.9 (build 2.1, photons 3.0). Counted with
`__profile()` over all 2 073 600 pixels, and identical frame to frame:

| per pixel | |
|---|---|
| marches (bounces taken) | 3.07 |
| march steps | 39.4 |
| `map()` evaluations | 53.1 (17% of them for normals: 2.3 normals × 4) |

| per `map()` / spray lookup | |
|---|---|
| coupe evaluations | 3.1, of which 22% get past the bounding cylinder |
| spray lookups in an occupied block (trilerp) | 64% — and 68% of those land outside the band anyway |
| wave fetch / bubble lattice | 0.36 / 0.10 |
| bottle profile | ~0 (the bounding sphere works) |

| how rays end | |
|---|---|
| table | 58.1% |
| environment | 29.5% |
| too dim to matter | 1.7% |
| **out of bounces (10)** | **10.7%** — and they take about 30% of all march steps |

66% of pixels finish at bounce 0. March steps by bounce: 46% the primary ray, 4% bounce 1,
29% bounces 2–4, 21% bounces 5–9. The traced reflection is 4.4% of pixels and 3.3% of
steps; over-relaxation fallbacks are 3.8% of steps. Neither is a lever.

**What each component costs**, measured by making `map()` evaluate it a second time at a
point the compiler cannot prove equal (`__xc(bits)`; the picture does not change). These
are a ranking, not a budget: duplicating also raises register pressure, so the deltas add
up to more than the frame.

| evaluated twice | render +ms |
|---|---|
| whole spray/liquid lookup (`liquidDist`) | 26.1 |
| tower (three coupes) | 11.7 |
| bulk liquid (wave fetch, bubbles) | 7.1 |
| spray trilerp | 3.9 |
| *before the fix:* far-field seed lookup | 16.0 |
| *before the fix:* the occupancy `atomicLoad` alone | 7.2 |
| *before the fix:* the seed particle read alone | 5.4 |

The last three are why the far field was repacked. `occ` is `array<atomic<u32>>` because
the compute passes build it, and `liquidDist` read it with two `atomicLoad`s per call plus a
dependent read of the seed particle — ~114 M calls a frame. In a fragment shader an atomic
load is not a cached load. `packCoarse` now copies occupancy, seed validity and the seed's
position into the (previously unused) `coarse` vec4 buffer after the flood, so the render
does one plain load. Every profiler counter matched exactly before and after, so the image
is bit-identical. Render 24.8 → **21.8** on this frame, 21.95 → 18.6 on the step-2400 A/B
frame; +62 bytes compressed.

**The wasted trilerps were not worth much.** Blocks were marked with a whole extra block
of dilation on every side, up to 3×3×3 blocks (58 mm) around a band ~3 cells deep. Marking
exactly the blocks whose trilerps can reach a touched cell (one fine cell past each face)
cut trilerps 70.9 M → 45.2 M with every other counter identical, and bought **0.4 ms**
(render 22.1 → 21.7, same frozen frame, alternated twice). The remaining half of them are
wasted too, but at that rate skipping all of them is worth ~0.35 ms more, not a finer grid
and its buffer. The duplication test (+3.9 ms) overstated them: a repeated fetch of the
same eight cells is cache-hot, the first one is not, yet it is still cheap next to
everything else in the lookup.

**The rays that run out of bounces are not a cheap lever either.** They are not lost in
the spray: per ray they entered 0.7 spray drops, 1.0 glass walls and 0.5 bulk surfaces
from air, plus 1.85 total internal reflections; the rest of the ten bounces are glass ↔
liquid inside the coupes, where one filled coupe costs four (air → glass → liquid → glass →
air). They still carry energy at the end, 45% of them above half throughput. And although
they take ~30% of all march steps, most of those steps are in the early bounces every ray
shares; any cap only removes the late ones. Measured on the same frozen frame, steps saved
against pixels changed by more than 4/255:

| variant | steps saved | pixels changed (>4 / >16) |
|---|---|---|
| total-internal-reflection cap 3 | 2.5% | 1.9% / 0.7% |
| total-internal-reflection cap 2 | 6.7% | 4.9% / 2.2% (≈1.5 ms) |
| throughput cut 0.10 → haze | 1.0% | 0.6% / 0.1% |
| throughput cut 0.20 → haze | 2.2% | 2.2% / 0.3% |
| a spray-drop cap (ignore spray after 2) | 0% | — |
| `bounces` 8 | 6.6% | 6.7% / 2.9% |
| `bounces` 6 | 15.8% | 13.4% / 7.1% |

Roughly one percent of steps per percent of changed pixels, whichever way it is cut, and the
changes land on the rim glints and the golden ring where the liquid meets the glass — the
glass's character. None was adopted; `bounces` remains the knob for that trade.

**The primary ray, and the march that ran on under the table.** The primary ray is 45% of
all march steps, 18.3 per pixel: 42% of primary rays end on the table (17 steps each), 24%
in the environment (13), 34% at an object (23); 59% of them take 8–16 steps and almost none
reach the 160-step cap. By where along the ray the steps fall: 80% inside the domain box,
12% outside it, and **8% past the table plane**. The table is intersected analytically
after the march, so a march headed for it never knew to stop. It sphere-traced on beneath
the table to the 14 m far clip, and whatever it found there was discarded.

`marchS` now takes the plane distance and stops once the last proven-empty sphere reaches
it. That is exact (every ray exit identical, no pixel off by more than 1/255) and it
applies to every bounce, the reflection trace and the photon pass. It cut march steps 13%,
render ~22.5 → **19.6**, and photons 2.75 → **1.84** (steps under the table were dear:
right below the plane, every one paid the puddle test). Bounding the march by the scene's
convex bounds as well (domain box, puddle slab, bottle sphere) removed 6.5% more steps and
**no** time — out in empty sky every SDF early-outs, so those steps were cheap — and was
dropped.

**What limits the steps inside the domain box.** For each march step in air inside the
box, the profiler records which component gave the minimum and so set the step:

| limiter | share of steps | mean step |
|---|---|---|
| bulk liquid | 30.0% | 17.5 mm |
| tower | 29.3% | 13.3 mm (a third from the coupe's bounding cylinder) |
| spray | 26.7% | 19.9 mm (half narrow band, half far-field estimate) |
| puddle | 7.8% | **8.2 mm** |
| bottle | 6.3% | 61.8 mm |

27% of those steps are under 1 mm, the usual cost of approaching surfaces. A further 20 M
steps are inside a medium. Bulk, tower and spray are limited by geometry that is really
there. The puddle was not: its bound used the global depth cap, a slab 20 mm deep over every
wet block, which rays crossed in 0.8 mm steps over a film usually a millimetre thick.
`puddleCoarse` now stores the tallest rendered film within one block of each block
(including the smoothing skirt), and `puddleSDF` bounds by that locally and by the global
cap a block away. Puddle-limited steps fell 5.1 M → 1.4 M at three times the length; all
steps −5%, **render 19.15 → 18.02**.

Two candidates that failed. **Stacked cylinders for the coupe** (bowl, stem, foot instead of
one rim-wide cylinder over the full height) were a valid bound and cut exact coupe
evaluations 19%, but saved no steps and were **0.9 ms slower**: three bounds on every coupe
call cost more than they save. A first version of the puddle bound dropped the horizontal
distance term from the "beyond a block" case and *added* 26% steps. That was caught by the
step count before anything was timed.

**Drops scatter under any change to the march path.** A bound that is perfectly valid still
changes which point on a 2 mm drop a ray lands on, and refraction through it amplifies that
into different pixels. The stacked cylinders changed 6.5% of pixels, all on drops, with
the glass untouched. The puddle bound changed 0.04%, specks on the low drops. A pixel diff
judges such changes only together with *where* the pixels are (`__diff` shows that).

Heavy tier2 now: **render ~18.0, total ~22.1** (was 24.8 / 29.9 when this profile started).
Still ~3 ms over the 19 ms target.

### WebGPU limits: none requested

The release asks for no features and no limits, so it runs on any WebGPU device at the
defaults. That took three changes, since several defaults were close to biting:

- **Storage buffers:** the default is 8 per stage. The storage is merged by element type
  into 5 bindings (`parts`, `fine`, `fineF`, `atom`, `vecs`) at fixed offsets; the dev
  build adds the profiler's counter bank as a 6th. (A sixth, `flts`, held the puddle.)
- **Workgroup size:** the default caps it at 256. 320³/256 would be 128 000 workgroups,
  over the 65 535 per-dimension cap, so `resolveFine` handles two cells per
  thread.
- **Binding size:** 320³ × 4 B = 125 MiB per buffer, just under the 128 MiB default.

The dev harness requests `timestamp-query` when the adapter has it, for the per-pass times.

---

## Controls

Panel, top right. Every control has a tooltip; every one is also a URL parameter.

**View** — `beauty · steps · normals · medium · liquid · glass · tir · bottle`.
The isolation views are the debugging workhorses: `liquid`/`glass` show one field alone,
`tir` reddens total internal reflection,
`bottle` shows the magnum alone, flat-lit, for shape comparison.

**Camera presets** — `tower · pour · macro · tier2 · top · bottl`.

**Sliders/toggles** — `spin, angle, dist, camY, tgtY, lightAz, lightEl, gridEnv,
drops, bubbles, waves, reflect, autofill, fill, pourRate, dropVol, dropRad, foam,
bottle, botTilt, pourWander, wanderSpd, shutter, bounces, simSpeed, expo, cgain`.

**Buttons** — `ff +20s` (jump the sim forward), `restart`, `pause` (also spacebar).

**Timeline** — `show` runs it, `showT` scrubs it. `?show=1` and `?showt=<seconds>` do the same
from a URL, and `&pause=1` with them lands on an exact frame for judging a shot.

Useful URL params beyond the above: `w`, `h` (explicit resolution, letterboxed), `t` (fixed
time), `still`, `warm`, `det`, `steps`, `npart`, `nphoton`, `parts`, `selftest`, and `gate`
(the release's start screen and audio clock) with `tick` (a click every half second, to
check sync).

`gridEnv` replaces the environment with a lat-long UV test grid (green horizon, magenta
poles, orange dot at the key light) — it makes it obvious which direction a reflection or
refraction is sampling.

---

## Instrumentation

`window.__probe()` returns JSON: per-pass GPU times (`timestamp-query`), fps, adapter info,
shader compile and validation errors, glass levels in mm, particle counts and bottle-stream
extent, and the clock's `step`, `drift` and `resyncs`.
Drift should stay under one step (16.7 ms); the HUD shows it live. `?selftest=1` runs assertions and logs
PASS/FAIL.

The renderer **pauses on demand** and still redraws one frame when a slider moves, so
exploring costs nothing.

`await window.__profile()` renders one frame with a second render pipeline compiled with
`PROF` on (a WGSL `override`, so the normal pipeline carries no counter cost) and returns 48
counters summed over the frame: map, spray and coupe evaluations, march steps, normals,
reflection traces, rays ending per bounce and per reason, march steps per bounce. The index
map is in the comment above `__profile`. `await window.__xc(bits)` renders with one
component evaluated twice to rank what it costs (`__xc(0)` restores);
`__variant({...})` takes arbitrary pipeline constants, and `{ PROF: 1, ... }` profiles a
variant. `const a = await __grab()` reads the frame on screen; `__diff(a, b)` reports the
share of pixels that changed by more than 4, 16 and 48 levels and overlays |a − b| × 8 on
the canvas (`__diff()` clears it) — on a frozen frame, two grabs of the same state differ
by exactly 0, so this is how a look-changing optimisation gets judged.
`await __saveRef(name)` / `await __loadRef(name)` keep a grab in IndexedDB, so a before/after
comparison survives the reload between them. `__pause()` / `__resume()` stop and restart the
loop - pause after every check, or it keeps the GPU busy. All of it is dev-only and absent
from the release.

---

## Roadmap

Done: geometry, hybrid sim, dielectrics, caustics, bubbles, mousse, bottle,
lighting, a first-draft timeline, the build and packer, the dropper, the click-to-start
screen with fullscreen and the audio clock, the sound engine and the cork pop.
`intro.cmd` is 9 379 bytes.

Next:
1. **Size** — 1 187 bytes over, before the score and any text. The puddle is cut (-362);
   next candidates in *Feature cuts, measured*, and a packer search on the new shader.
   Features have to be cut or simplified (*Feature cuts, measured*), or the sound made
   smaller.
2. **The score** — must be **human-composed**; the party bans prompt-based music. Chords
   go into `SCORE` (*Sound*); each chord costs a few bytes.
3. **Text**, if any (credits, title), from the same budget.
4. **tier2** — ~22 ms against ~19 in its heaviest state (*Where it stands*). Options: cut
   there, don't hold on it while the spill is densest, or take `bounces` down on that shot.
5. **Render size** — the release renders at the screen's size. At the compo's 1920×1080
   that is the budget; on a larger monitor it is proportionally slower.
6. Timeline polish against the finished music.
7. Late, when every byte counts: design-constant rounding (~-40 to -90), a final packer
   search, a fresh Roadroller search (`python build/roadroller.py`). Roadroller itself is
   in the build since 31 Oct (-792).

Not planned for now: bloom, fluid inside the bottle (it is an empty shell).

Open questions for the organisers: whether a browser/WebGPU entry is allowed, and the
submission deadline.

Party rules: tools must be disclosed, generative-AI use must be **fully** disclosed, and
entries that are mostly AI material with little human input are disqualified. Realtime/Wild
also bans "purely generated effects or shaders". The NFO must carry this.

---

## Build

```bash
python build/build.py
```

### Setting up a machine

Three things, installed once. On Windows, from a terminal (winget ships with Windows 10
and 11):

```bash
winget install -e --id Git.Git
winget install -e --id Python.Python.3.13
winget install -e --id OpenJS.NodeJS.LTS
```

Open a **new** terminal so PATH picks them up, then:

```bash
python -m pip install brotli
git clone https://github.com/BartmanAbyss/comparade26.git
cd comparade26
python build/build.py
```

If `python` is not found or opens the Microsoft Store, use the launcher instead: `py -m pip
install brotli` and `py build/build.py`. On macOS or Linux it is the same with `python3`;
only the dropper itself is Windows-only.

The output ends with `intro.cmd  <bytes>  UNDER`, and for a given commit that number is the
same on every machine. If something is missing, the build stops with `BUILD FAILED` and
names it. Nothing else gets installed - no npm packages, no network requests during a
build - so once these three are on the laptop it builds offline at the party.

Optional extras: a WebGPU browser (Chrome, Edge or Firefox) to run the harness or the
release, and `python build/pack.py` for the packer search (it uses every core; *The packer
search*).

### What the build does

One source of truth: `dev/champagne.html`. The build strips the harness, inlines the values
the debug panel used to supply, minifies, packs, and writes:

| file | what |
|---|---|
| `build/intro.cmd` | **the deliverable**: the dropper header plus the brotli payload - the page, its script packed by Roadroller (`build/roadroller.py`, settings in `build/roadroller.json`) |
| `build/intro.html` | a local test copy that inflates itself (base64 + deflate), ~50% bigger - not the entry |
| `build/min.wgsl`, `build/min.js` | what ships, as packed |
| `build/min.pretty.wgsl`, `build/min.pretty.js` | the same, re-indented to read |
| `build/min.pretty.html` | the whole page as it ships - canvas, the lettering's overlay, a path per line - with the readable JS and shader inlined |

It needs **Python 3 with `brotli`** and **Node.js 16+** on PATH (*Setting up a machine*).
That is all: wgslender 1.5.1 and terser 5.51.2 are vendored in `build/vendor/node_modules`
(committed, 5.5 MB, plain JS and WebAssembly, so the same files on every OS) and run with
`node` from there - no npm, no npx, no network. A fresh clone builds the same `intro.cmd`,
byte for byte, or the build stops with `BUILD FAILED` and the reason. There are no
fallbacks: a missing Node, a missing tool, or a tool or the packer failing ends the build
rather than quietly producing a bigger intro. To change a tool version, see the
description in `build/vendor/package.json`.

Dev-only code is bracketed with `//#D{` / `//#D}` in both the WGSL and the JS. Everything
else goes by rule, so the harness cannot quietly end up in the release:

- Lines mentioning `probe`, `fail(`, `setUI(`, `hasTS`, the readbacks or the query-set
  plumbing are dropped. A handful of lines mix harness and release work in one statement
  and are rewritten explicitly instead.
- `cfg.*` and `ui.*` are replaced with literals — `ui.*` read straight out of the panel's
  own `SPEC` table, so the release cannot drift from the defaults you tuned by hand. The
  build asserts that none survive.
- WGSL identifiers are renamed by the packer (below), except entry points and anything
  quoted in the JS; compute entry points get short names (`Z0`...) in both languages.

### What minification is actually worth

Measured with `python build/experiment.py`, which scores each strategy on brotli bytes of
the real payload. This is not optional rigour: shrinking the source does not guarantee a
smaller compressed result, and Shader Minifier once shipped a size regression from a
renaming heuristic precisely because nothing measured the compressed output.

| WGSL strategy | raw | brotli |
|---|---|---|
| comments + whitespace only | 25 368 | 10 581 |
| + globals renamed | 23 690 | 10 212 |
| + globals, frequency-ordered names | 23 690 | 10 216 |
| + globals + locals, **fresh** names | 23 329 | 10 462 |
| + globals + locals, **names reused** | 23 329 | 10 171 |
| wgslender, its own renaming | 22 985 | 10 926 |
| wgslender + `--mangle-external-bindings` | 22 730 | 10 904 |
| **wgslender tree-shake + our naming** | **22 190** | **9 884** |

The last two rows are the whole lesson. **Identical source size, 291 bytes apart after
brotli** — the only difference is whether the same few names recur from function to
function. Brevity is not the lever; repetition is. Giving every function fresh names is
worse than not renaming locals at all (10 462 against 10 212) while being 361 bytes smaller
on disk: a smaller file that compresses worse.

Two of my own bugs showed up in the same measurement and are worth remembering. Ranking
candidate names by average character frequency put three-character names above
two-character ones, so locals were renamed *from* 2 characters *to* 3. And set iteration
order made name assignment nondeterministic, moving the result about 30 bytes between runs
— which incidentally says a search over assignments has real bytes in it, exactly what
INCENDIUM's Pakettic-derived packer does.

Frequency-ordering as a tie-break is worth nothing here (+4 bytes, noise).

### Why the build uses wgslender for analysis but not for names

[wgslender](https://github.com/HugoDaniel/wgslender) is a real WGSL toolchain on a real
parser, and it beats our regex at everything structural: it tree-shakes dead declarations
and rewrites syntax, which our minifier cannot do at all. Used as intended it is also
**599 bytes smaller on disk and 733 bytes larger after brotli** than ours, for the same
reason fresh local names lost above — it optimises raw size, so it gives every identifier
its own short name and the repetition goes away.

So the build takes its analysis and keeps our naming: `--no-mangle --no-whitespace`, then
our renamer. Worth **287 bytes** over either alone. `--no-whitespace` is not optional:
globals are found with a line-anchored pattern, which a one-line file defeats.

The pre-pass is required (vendored, see *Build*); it used to be optional, which meant a
machine without Node built an intro 287 bytes heavier without saying so. Two notes for
anyone repeating this: wgslender's validator rejects our `atomicAdd` calls as `@must_use`
where Dawn accepts them, so `validate` reports errors on a shader that compiles and runs;
and all 17 entry points survive its tree-shaking, which is worth re-checking whenever a
compute pass is added.

[washi](https://github.com/datatrash/washi) was the other candidate and is not usable here:
no prebuilt releases, cargo required, and its own README recommends wgslender instead.

### Folding what the release never varies

When this was written, 29 of the 47 uniform slots were constants in the release (the struct
has since been cut to its 9 live fields, the rest dev-only): the debug toggles, `view`,
bounce and step counts, light angles, bottle pose. The build inlines them (39 references)
as the shortest literal that rounds to the same f32 the JS would have written, then
evaluates the comparisons that leaves behind — `if (0. > 0.5)` and friends — and deletes
the dead branches. 8 if-statements resolve at build time. Helpers reachable only through a
dead branch (the UV grid environment, for one) are then unreferenced, which is what
wgslender's tree-shaker can actually remove.

That order matters: **wgslender does not evaluate constant conditions.** It removes
declarations nothing references, and behind a uniform the debug paths are referenced.
Fed the folded shader without the branch folder it shrank 66 bytes and the brotli got 13
bytes *worse*. With the folder: **9 698**, 186 better.

One parser incompatibility cost a confusing round: `.5` is a valid WGSL literal, but
wgslender rejects a leading dot and fails; back then the build fell back silently to an
unshaken shader, now it stops. Literals keep their leading zero.

### The packer search

`build/pack.py` replaces the regex renamer. It tokenises the shader once into its 137
module-scope declarations and treats packing as a search over two kinds of move, both
semantics-preserving by construction:

- **order** — module-scope declarations may appear in any order in WGSL, so items shuffle
  freely (the page around them is now fixed: a canvas, one script, the shader a template
  string at its end);
- **names** — which candidate name goes to which of 119 globals, 162 locals and 52 struct
  fields. Fields live in their own namespace (`p.pos` vs a local `pos` never collide), and
  a local may take the name of any global its function does not touch, which is the
  shadowing trick Shader Minifier uses.

Scored by brotli q11 of the whole payload, because a cheaper proxy is no proxy: q9 is 790
bytes off. Late-acceptance hill climbing, as in Pakettic, one chain per core as an island
model — each round the worse half of the islands restart from the global best.

| | brotli |
|---|---|
| regex renamer (previous build) | 9 698 |
| packer, default state | 9 479 |
| **packer, searched** (32 islands × 40 rounds × 300) | **9 184** |

The default state already gains 219 bytes, from field renaming and shadowing alone. The
search adds 295 more. It converged: by the end every island sat within 2 bytes of the
others, and the last 15 rounds bought about 30, so more of the same is not where the next
bytes are.

The result lives in `build/pack_state.json`, keyed by **source** names, and every build
reuses it without searching. It survives edits: anything it knows keeps its place, anything
new falls in where the default would put it. Re-run the search after big shader changes:

```bash
python build/pack.py --rounds 40 --per-round 300
```

It only saves when it beats the stored score for the same input. The figures above are
from its first run; the latest, 120 rounds, is in *Non-feature pass*.

**What limits it.** One evaluation is 21 ms: brotli 17.1 ms (81%), rendering the candidate
in Python 3.9 ms (19%). So it is brotli-bound, and the Python could at best buy back a
fifth. Across cores it reaches 730 evaluations/s against 48/s on one core — 15× on a
16-core, 32-thread Ryzen 9 9950X. It scales with physical cores and SMT adds nothing:
brotli q11's optimal parsing saturates a core on its own. Faster search means fewer or
smarter evaluations, not faster ones.

### Where it lands today (no music, first draft timeline)

**`intro.cmd` is 8 273 bytes (2 Nov 2026), 81 OVER 8 192**, lettering in, score
empty; the last changes: the liquid's sound re-done for the shot plan (+43, *Sound*), shot 8 5 s longer (+11), its pour down to 250 for the frame budget (+9), clearFine and causticDecay folded into resolveFine (-52), exact shader simplifications (-57), a simpler coupe (-105), the traced reflection dropped (-87), the bottle without heel bevel and neck taper (-43), one smoothed normal for all liquid (-56), the bottle held from 180 degrees (-32), its helpers inlined (-29), more single-call functions inlined (-51), `botShare` global, the pool halved and the integer consts untyped (-6), two uniforms gone (-15): the standing bottle is switched by the raised table (only shot 2 raises it past 0.4), and the shader takes the pour rate and works out the emission cadence itself; 62 exact rewrites across the shader (-160, see CLAUDE.md *Minifying*); a fresh packer search on them (-19; the Roadroller search found nothing better than its old settings); fs ending in one expression and the particle writes merged into one (-4 after another packer search); the bottle's wander computed in the shader, five uniforms fewer (-10); the mousse made from the wave impulse and drops absorbed at the bowl wall instead of sliding down it (-56, no visible difference).
Before them, all lossless: the dropper golfed 310 -> 218 (9 426 -> 9 336, see
*The dropper*); the release's uniforms as a nameless `array<vec4f,6>` plus fresh packer and
Roadroller searches (-> 9 319); sloppy literals in the WGSL (-> 9 213): 520 places where
an abstract literal takes its type from context - `x * 2` for `x * 2.0`, `n * 4` for
`n * 4u` - each found by the compiler, checked against integer division by a scan and
against the picture by a pixel-exact A/B (CLAUDE.md has the rules); the timeline read as a function of the column, `showAt(t)(1)` for `evalShow(t).angle`, so the release carries no field names (-> 9 141); the key table trimmed - the `ease` column gone (two keys used it), camera values to a degree and a centimetre, black shots copying the camera either side (-> 9 080); the release frame loop without its leftovers (-> 9 053) and a simpler sim clock - steps straight from the audio clock each frame, capped at 16, nothing owed (-> 9 022); the camera rise at the end of 4 pour taken out, a key fewer (-> 9 016). Then the table, 9 032 -> 9 042: it mirrors the room (`env`, Schlick Fresnel for lacquer), glossy rather than sharp - the reflection's bokeh discs drawn at twice the radius - for +0.5 ms render on the tower shot; paid for by trimming the bokeh (one hash per disc, elevation as `rd.y`, no breathing). Then the bottle: solid glass, and marches no longer stop on the surface they just left (CLAUDE.md) - its shadow now carries a green caustic line, it reads as a full bottle, -17 bytes with the packer's default state on both sides (+21 shipped until the packer was searched again: -> 9 020), +0.8 ms in shot 8; then a flat base - the punt, carved from solid glass, showed as a bubble - and its puntSoft slider gone (-> 8 992). Tried and dropped on
the way: float constants packed into vectors (+35 shipped, -25 fair - the packer already
names repeated literals), local floats packed into a `vec3f` (-2), the page markup moved
inside the Roadroller-packed script (-4), mgnauck's wgslminify (does nothing ours does not).

Before that, 9 379 (26 Oct): shot 1 stretched 1.5x
(+10, the shifted key times). Before that 9 369: stratified photon emission
(+56 shipped, +78 with the packer's default state on both sides). The lit table's grain is
photon noise: 65 536 photons a frame put ~5 in each blurred (5x5 texel) cell, and the
236/256 fade averages ~25 frames. `strat` picks the emitter pattern - 0 random, 1 R2
low-discrepancy shifted per frame (`stratJit` breaks the faint diagonal stripes plain R2
beats into the texel grid), 2 a jittered grid, one random photon per cell (default; fewest
bytes, no stripes). Same photon count, same paths, same cost (photon pass 1.47 vs 1.48 ms at
1920x1080, tower at step 2400). Grain on the lit table in the shot-1 framing, mean
|5x5 box - 25x25 box| / mean, 5 grabs: light at 45.6° random 1.32% -> grid 0.95% (41x41: 2.01
-> 1.22); light at 20° 1.70 -> 1.36, because the photons then land ~6 texels apart along the
light, wider than the blur, and stratification only helps where the kernel spans several
cells. The stronger lever at low light is the fade: 248/256 instead of 236 took the grid to
1.04 (not adopted - it lags a moving light or caustic 2.5x longer). 4x the photons measured
2.0 -> 0.45 but costs time. Before that 9 313: the bokeh animates (+49) -
each disc breathed at its own rate (`bkBreath`, `bkSpeed`; dropped on 31 Oct for 17 bytes, with
`bkLife` cut from 9 s to 4 so the room stays lively), and every `bkLife` seconds,
phase-shifted per cell, a cell fades its disc out and rolls a new one, or none, so the lights
drift around the room. It runs on the show clock, so it keeps real time through slow motion,
and costs nothing measurable: the environment is only sampled where rays leave the scene.
`bkLife` 0 gives the old static discs. Before that 9 264: the environment's
brightness as a timeline column (+56). Before that 9 208: the table height as a
timeline column, with the photons and drops following it (+81). Before that 9 127: the new
timeline - four more
columns and 28 keys, light, pour and bottle tilt as live uniforms (+183). Before that
8 944: the glugs and the bowl fix
(+79), pourWander 20 (+23, a constant). Before that 8 842: real slow motion, the exact
glass volume and a fade slot in the uniforms (+92). Before that 8 750, after cutting the bottle's
punt (-12) and the table puddle (-362, measured with the old search state; 0.4 ms faster on heavy tier2). Before
that: **9 132**, the breakdown below (7 967),
plus the start screen and music hookup (+116), plus the sound (+1 049 all told, the score
still empty): the PADsynth pad, two reverbs, the bubble-model liquid with fizz, the cork
pop and the fixed master gain - after it was built with a saw pad and a first liquid next
to the final ones for A/B, and those were removed (-278, -262), and an audio size pass
(-82).

The breakdown, 24 Oct 2026, after the lossless pass, the core simplifications and the
non-feature pass below, and a 120-round packer search on the result:

| Stage | WGSL | JS |
|---|---|---|
| source | 68 147 | 48 975 |
| harness stripped | 59 980 | 19 452 |
| dev code removed | 59 980 | 16 520 |
| tree-shaken | 35 444 | |
| minified | 19 948 | 4 207 |

| Packed | bytes |
|---|---|
| payload, uncompressed | 24 379 |
| brotli q11 (searched state) | 7 657 |
| dropper header | 310 |
| **`intro.cmd`, the deliverable** | **7 967** |

That was 225 to spare before the click-to-start screen, which took 116 of them.

#### Start screen and music hookup: 7 967 -> 8 083

The release opens on the word "click", unstyled (black on white, top left: centred
white-on-black cost 55 bytes), which appears only once everything is loaded
(device, pipelines, the song rendered). A click goes fullscreen on the canvas, sizes it once
from `screen.width/height` (no resize handling in the release), resumes the audio, schedules
playback 0.1 s ahead and starts the render loop. From then the show clock is the AUDIO
clock: as many whole sim steps as the music has played, so the picture follows the music.

The music hookup is `song(L, R, sr)` in the harness: it fills the stereo buffers once,
before the click, so a slow player costs load time and never a hitch. It is empty - silence
of the show's length - until the user's player goes in; the party bans generated music.
In the harness the same path runs with `?gate=1`; `?tick=1` adds a click every half second
to check sync. Measured: show time advances 1.00 s per second of audio, drift one step.
If fullscreen is refused, the 16:9 canvas is stretched to the window.

#### Browsers (24 Oct 2026)

The release was run in Chrome 152 (the app pane), Edge 156 and Firefox 157, served byte for
byte as the dropper serves it. All three decode `Content-Encoding: br` over plain
http://localhost (Firefox included), compile the shader with no messages and render the same
picture; a frozen dev-harness frame matched in Firefox and Chrome. Speed is the same: at
2560x1440 Edge and Firefox were within ~10% of each other over the first 45 s of the show
(~65-80 fps on the opening, 24-27 on the heaviest stretch, t = 28-36 s), Firefox ahead as
often as behind.

Two things it showed:
- **The release renders at the SCREEN's size** (`screen.width/height`). On a 1440p monitor
  that is 1.78x the pixels the 1080p budget is set for, so it looks slow on any browser.
- **Chromium compiles pipelines lazily** - fixed, +5 bytes. "click" appeared ~0.5 s after
  load, but on a cold shader cache (a fresh profile, as on the compo machine) the first
  frame then waited 3-7 s while the audio clock already ran, so the picture started that far
  into the show. Firefox compiles inside `createComputePipeline` and had no stall. The
  pipelines are now made with the awaited `create*PipelineAsync`, which resolve only once
  compiled: cold, both browsers show "click" at ~3 s and the first frame follows within
  6 ms of the click.

#### Non-feature pass: 8 333 -> 7 967

| Change | bytes | picture |
|---|---|---|
| per-dispatch index passed as the grid HEIGHT (`num_workgroups.y - 1`): the uniform slot buffer, its bind group and dynamic offsets gone | -104 (default state) | exact |
| page wrapper: canvas styled inline, one classic script, the shader a template string at its end | -53 | exact |
| dropper golfed 371 -> 310 (see the comment in `build.py`) | -61 | - |
| no `requiredLimits`: 14 storage bindings -> 6 by element type, the big passes 256-wide | -92 (default state) | exact |
| camera angle `/57.3` | -6 | 0.007% |
| packer search, 120 rounds (40 -> 120 found 22 more) | - | - |

The release now asks for no features and no limits: it runs on any WebGPU device.

Measured and not worth it: radians in the timeline (-2), exact fraction literals (0),
`vec3f()` for zero vectors (0), one-letter type aliases (+18). Long float literals are few
(16 of 544): rounding them to 4 digits is -16. Rounding DESIGN values hard (colours,
angles, gains) is worth an estimated -40 to -90; blanket rounding is not usable - it hits
grid sizes, the glass count, refractive indices and pi/2.

#### Core simplifications: 8 696 -> 8 333

Default packer state 8 651 -> 8 343 (-308), shipped -363 after re-searching:

| Change | bytes | picture |
|---|---|---|
| f32 literals without exponent cruft (`10.` not `1e+01`), peephole for folding leftovers | -27 | exact |
| dev-only bookkeeping in `fs` (step / TIR counts, first-hit normal) fenced | -40 | exact |
| one wave fetch for height and foam; IOR/absorption tables; `marchS` returns a vec3; vec4 blurred photon texels; one-loop puddle blocks; small dead stores | -49 | exact |
| the puddle's distance flood retired: a block whose neighbourhood is dry is at least a block from wet table, which is all the bound needs | -183 | thin outline shifts at glass edges, frame indistinguishable |
| glass levels updated by the first threads of the puddle step | -10 | exact |

What is left is the core itself: the particle sim (~720), `fs` (~520), the scatter, the
coupe, the spray lookup. The remaining exact wins are tens of bytes each - the same
lesson as the trace loops: brotli already shares what repeats, so only work that goes away
pays.

#### Table light without photons: tried 30 Oct, reverted

Commits 7de3f51 and d62f890, reverted. Both measured with the photon code really deleted,
packer default state on both sides:
- **Analytic fake** (each bowl a lens-shaped blob, the bottle a capsule): -262 bytes,
  ~-0.9 ms, but it looked nothing like the photons.
- **Shadow rays into the same table map** (the photons' path run backwards, one ray per
  texel): the real shadow shapes, no grain, no caustic glints; -269 bytes, ~-0.45 ms.
  Traced per pixel instead of per texel it cost +6.5 ms of render.

The ceiling is low because the photons are cheap: they reuse the render's `leg` / `turn`,
so only the emitter, the fade, the splat and the blur are theirs, and any replacement needs
its own kernel and keeps the map and its lookup.

#### Feature cuts, measured

Each measured as the real edit - shader code, call sites, kernels and dispatches removed -
against the packer's default state, before the core pass above (the puddle's share is
~180 smaller now that its flood is gone). Bundles add up almost linearly.

| Option | saves | what it does to the look |
|---|---|---|
| puddle - **cut 25 Oct: -362 on the shipped build** | 707 | 1.3% of pixels from above, <0.5% elsewhere: a few glints by the tower base |
| photon lighting -> analytic spot | 589 | the lit disc stays; the tower's shadow and the caustic glints go |
| waves + foam | 447 | every champagne surface becomes a flat mirror |
| bottle removed | 355 | the stream pours out of thin air |
| bokeh lights | ~225 | the light discs behind the tower and their reflections go (176 static, +49 animated) |
| bottle, plain profile | 168 | no lip, punt, neck taper or heel bevel; hard to see at pouring distance |
| foam only | 134 | subtle: the cream texture calms |
| bubbles | 80 | not visible at tier2 distance |
| traced reflection | 13 | now shares the main trace code - not worth it |

Bundles: puddle + bokeh + bubbles ~960; + waves/foam + plain bottle 1 573; + spot 2 158.

The packer search (`python build/pack.py --rounds 40 --per-round 300`, ~8 minutes on 32
threads) took this shader from 8 637 to 8 325: worth re-running after any big edit, and
the last thing to do before a release.

#### The lossless pass: 10 181 -> 9 008 (8 696 after re-searching)

Every step verified on the same frame before and after (pinned-level step 2400, three
cameras), measured, committed separately:

| Step | bytes | picture |
|---|---|---|
| JS written for the release: buffer table, generated layouts and bind group, pipelines from a name list, dispatches as tables; no zero-fill uploads (WebGPU zero-initialises); URL parsing dev-only | **-842** | same |
| uniform struct: the 9 live fields first (64 bytes); the 32 folded controls behind dev markers, neither declared nor written by the release | -251 | same |
| compute entry points renamed `Z0`... by the build (they shipped twice, once per language) | -86 | same |
| three trace loops -> one `leg` + `turn` | ~-35 | pixel-exact |
| three small kernels merged into their neighbours | -27 | pixel-exact |

JS went from 2 942 to 1 867 bytes compressed on its own; the shader is 6 744 of the 8 637.

#### What repetition costs under brotli

Less than it looks. The three trace loops were 1.8 KB of near-identical source, and
merging them saved ~35 bytes; an exact 203-character duplicate costs 44. Brotli already
replaces repeats with back-references, so neither deduplicating by hand nor assembling
repeated chunks at runtime buys much - only code that genuinely goes away does. Judge such
changes with the packer's DEFAULT state on both sides: the saved search state is tuned to
the shader it was searched on and flatters it by ~100 bytes against any edit.

#### The size map (2 Nov, `python build/sizemap.py`)

Measured through the real build, so it can be re-run after any change. It measures the
pipeline up to brotli and leaves Roadroller out, so its total is ~770 above the shipped
`intro.cmd` (9 055): **brotli alone 9 820 = dropper 218 + shader 5 961 + JS and page 3 641**
(10 165 with the packer's default state). The proportions still say where the bytes are;
what a cut saves under Roadroller differs.

- **share**: in shipped order, item by item, each charged what brotli adds for it. Adds up
  exactly to the total, but order matters: code that echoes something earlier comes cheap.
- **cut**: remove the system, rebuild, and the difference is what cutting it would save.
  Shader cuts leave call sites in other functions, so they slightly undercount.
- **cut/def**: the same with the packer's default state, a check that the saved state is
  not flattering either side.

Run to run, the noise is about ±40 bytes.

| shader system | share | cut | cut/def |
|---|---|---|---|
| render core (`fs`, march, normals, `leg`/`turn`, `reflColour`, `tableShade`, tonemap) | 1 593 | 1 219 | 1 477 |
| spray grids (narrow band, JFA far field) | 874 | 658 | 761 |
| particle sim (`simParticles`) | 768 | 638 | 696 |
| photons + caustic map | 514 | 448 | 539 |
| coupe + tower | 408 | 279 | 393 |
| plumbing (uniforms, buffers, hashes) | 309 | 76 | 137 |
| environment + bokeh | 296 | 246 | 302 |
| waves + foam | 285 | 207 | 242 |
| bottle | 262 | 217 | 284 |
| bulk champagne SDF | 261 | 123 | 157 |
| spray SDF in the render (`sprayDist`) | 227 | 142 | 181 |
| bubbles | 97 | 47 | 58 |
| glass volumes + overflow | 51 | 86 | 53 |

**Render core per function (share):** `fs` 406, `reflColour` 174, `mapN` 173, `marchS` 152,
`turn` 127, `tableShade` 115, `leg` 90, `lightDir` 67, `vs` 66, `sigmaOf` 59, `map` 56,
`tonemap` 38, `planeT` 38, the rest under 25. **Plumbing:** `pcg3d` 56, buffer declarations
~140, `Particle` 36, `PI` 36, `rnd3` 35, the rest ~0 (the uniforms have no struct since
`nameless_uniforms`).

| JS system | cut | cut/def |
|---|---|---|
| audio, all of it (synth, liquid sound, audio clock) | 1 250 | 1 207 |
| - pad synth (plays nothing: the score is empty) | 304 | 296 |
| - drips + splashes | 113 | 62 |
| - cork pop | 67 | 118 |
| - pour glugs | 54 | 16 |
| - reverbs | 47 | 75 |
| - fizz | 22 | 21 |
| lettering (stroke font, SVG, fades) | 557 | 557 |
| timeline keys (`SHOW` rows) | 268 | 273 |
| shot table (`SHOT_V`) | 2 | 32 |
| bottle wander | 8 | 3 |
| core: WebGPU setup, frame loop and clock, uniforms, start, page (the rest) | 1 556 | |

The audio's parts add up to ~610 of its 1 250. The rest is what they share: the bubble
model, the liquid's timeline helpers, buses, the offline render and the clock that
follows the audio.

**JS share by region.** Terser's source map ties each minified character to its source line;
charged a prefix at a time like the shader, the shares add up exactly to 3 641.

| JS region | share | | JS region | share |
|---|---|---|---|---|
| lettering | 617 | | audio: pad synth | 288 |
| timeline keys (`SHOW` rows) | 316 | | audio: bubble model (`bub`, `pop`) | 198 |
| frame: dispatches + render pass | 270 | | audio: liquid on the timeline (ramps, loudness, `each`) | 145 |
| uniforms (`writeUniforms`) | 232 | | audio: mix, reverbs, offline render | 136 |
| buffers + bind group | 156 | | audio: context, buses | 118 |
| device, canvas context, shader module | 152 | | audio: cork pop | 118 |
| start screen, audio start | 123 | | audio: drips + splashes | 108 |
| pipelines | 99 | | audio: pour glugs | 68 |
| shot table (`SHOT_V`) | 96 | | audio: fizz | 28 |
| frame: sim stepping on the clock | 88 | | bottle wander | 35 |
| timeline evaluation (`showAt`) | 78 | | constants | 30 |
| clock state | 45 | | page and glue | 24 |
| frame: show clock, locked to the audio | 39 | | frame: submit, loop | 34 |

Since 30 Oct (10 507 brotli alone, dropper 310): the dropper -92, the shader -242 (sloppy
literals, nameless uniforms, the solid flat-based bottle, the leaner bokeh), the JS and
page -353 (`showAt` instead of named fields, the trimmed keys, the simpler clock, the frame
loop's leftovers pinned) - and Roadroller on top of all of it.

### Brotli, by serving rather than decompressing

Nothing on a stock Windows box can inflate brotli for us: PowerShell 5.1 runs on .NET
Framework, which has `DeflateStream` but **no `BrotliStream`**, `pwsh` 7 is not a safe
assumption, and the browser's `DecompressionStream` does gzip, deflate and deflate-raw but
**never brotli**. All measured.

None of it matters, because the dropper does not decompress — it **serves**. This is
INCENDIUM's trick: the bootstrapper hands its own bytes to the Windows built-in HTTP server
at an offset into itself, and the browser decodes `Content-Encoding: br` natively. Their
README says outright that brotli content can only be served over HTTP, never opened as a
local file. `HttpListener` binds `localhost` without elevation, which was checked before
building on it.

Worth 1 050 bytes over the deflate version, for a header that came out *smaller*.

### The dropper

`intro.cmd` is one batch line that hands itself to PowerShell (218 bytes). PowerShell
starts an `HttpListener` on http://localhost:8044/, opens that URL in the default browser
and answers the one request with its own file past a fixed offset, sent with
`Content-Encoding: br` and no Content-Type: the page opens with `<body>`, so the browser
sniffs it as HTML. The payload sits in the file as **raw brotli bytes** — no base64, no
escaping. The offset is written into the header; the build finds the value consistent
with its own digit count, so the number cannot move what it points at. Every golfing
choice is commented in `build.py`.

Golfed again on 31 Oct, 310 -> 218 (intro.cmd 9 426 -> 9 336): no `-c` (a bare trailing
argument is the command), `[Net.HttpListener]@{}` for `::new()`, assignments inside their
first use, `Close(bytes, 1)` for Write + Close with the body a slice of `gc -li ... -en 3`
(out-of-range indices are dropped, so `[N..1e5]` runs to the end), no Content-Type for
`<body>` in the page (+2 after brotli), and LF without CR. Ruled out: a port under ~5000
(binding localhost there needs admin). Not tried: raw `TcpListener` with the HTTP header
in the file - its short constructor binds every interface (a firewall prompt), the
loopback one costs most of what it saves, and it has to cope with the browser's extra
connections itself. Then dropped, trade-offs accepted for the compo machine: `-nop` (a user profile could print or slow the start), `@` (cmd echoes the line), `/b` on exit (it closes a console it was run from): 8 bytes.

Verified end to end: Chrome, Edge and Firefox decode it over plain http://localhost and
render with a clean console (*Browsers*).

One lever left on the table: the occupancy skip buys 0.9 ms and costs bytes — a fair trade
to reverse at the end if bytes are short.

---

## Credits and references

Everything the intro uses that came from someone else, for the NFO. Ideas and algorithms
were implemented from their descriptions; no third-party code ships in the intro. The
build tools in `build/vendor` are third-party code and keep their licences (below).

### Prior art and packaging

- **INCENDIUM** (Bercon + pestis, Revision 2025) - 4 kb WebGPU intro with a 3D fluid sim and
  compute-shader music. The packaging model, the byte budget and the dropper's trick -
  PowerShell serving its own bytes as `Content-Encoding: br` - come from it. MIT.
- **Roquefort** (Bercon) - 256³ WebGPU fluid. MIT.
- Shadertoy work by **wyatt** and **michael0884** informed the nearest-particle-as-SDF idea.
  Studied, not copied - Shadertoy defaults to CC BY-NC-SA.
- **Pakettic** (Veikko Sariola / pestis, MIT) - the model for `build/pack.py`: packing as a
  search over orderings and names, scored by compressed size, with late-acceptance hill
  climbing. Reimplemented, not copied.
- **Shader Minifier** (Laurent Le Brun / Ctrl-Alt-Test, Apache-2.0) - the trick of letting a
  local take the name of a global its function never touches. Idea only.

### Rendering

- **Sphere tracing** - J. C. Hart, "Sphere tracing: a geometric method for the antialiased
  ray tracing of implicit surfaces", *The Visual Computer* 12(10), 1996.
- **Over-relaxed sphere tracing** - B. Keinert, H. Schäfer, J. Korndörfer, U. Ganse,
  M. Stamminger, "Enhanced Sphere Tracing", STAG 2014 (Eurographics Italian Chapter),
  doi:10.2312/stag.20141233.
- **Distance-field modelling** - Inigo Quilez's articles: SDF primitives (capped cylinder,
  capsule) and the polynomial smooth minimum used for the glass's joins
  (iquilezles.org/articles/distfunctions, /smin).
- **Nested dielectrics by priority** (glass, champagne and bottle glass meeting without
  coincident surfaces) - C. M. Schmidt, B. Budge, "Simple Nested Dielectrics in Ray Traced
  Images", *Journal of Graphics Tools* 7(2):1-8, 2002.
- **Fresnel term** - C. Schlick, "An Inexpensive BRDF Model for Physically-based
  Rendering", *Computer Graphics Forum* 13(3), 1994 (Schlick's approximation).
- **Absorption** - the Beer-Lambert law.
- **Caustics by tracing photons from the light** - after H. W. Jensen, "Global
  Illumination using Photon Maps", Eurographics Rendering Workshop 1996; here splatted
  into a table texture.
- **Jump flooding** (the spray's far field) - G. Rong, T.-S. Tan, "Jump Flooding in GPU
  with Applications to Voronoi Diagram and Distance Transform", I3D 2006.
- **Hash** - `pcg3d` from M. Jarzynski, M. Olano, "Hash Functions for GPU Rendering",
  *Journal of Computer Graphics Techniques* 9(3):21-38, 2020.
- **Tonemapping** - K. Narkowicz's fit of the ACES filmic curve, "ACES Filmic Tone Mapping
  Curve" (blog, 2016).
- **Smootherstep** (shapes and camera easing) - the quintic fade from K. Perlin, "Improving
  Noise", SIGGRAPH 2002.

### Simulation

- **Collision as a position constraint** (no tunnelling through the 1.4 mm glass at any
  speed) - in the spirit of M. Müller, B. Heidelberger, M. Hennix, J. Ratcliff, "Position
  Based Dynamics", *J. Visual Communication and Image Representation* 18(2), 2007.
- The per-glass surface waves are the discrete 2D wave equation. Textbook, no single
  source.

### Sound

- **Bubble acoustics** - M. Minnaert, "On musical air-bubbles and the sounds of running
  water", *Philosophical Magazine* 16(104):235-248, 1933 (the resonance 3/r).
- **The liquid's bubble model** (damping, pitch rise, size and depth distributions) -
  K. van den Doel, "Physically Based Models for Liquid Sounds", *ACM Transactions on
  Applied Perception* 2(4), 2005; first at ICAD 2004.
- **Fizz** (bubbles bursting at the surface, pitch rising as the cavity collapses) -
  M. Poujol, R. Wunenburger, F. Ollivier, A. Antkowiak, J. Pierre, "Sound of
  effervescence", *Physical Review Fluids* 6, 013604, 2021.
- **The cork pop** - shaped after G. Liger-Belair, D. Cordier, R. Georges, "Under-expanded
  supersonic CO2 freezing jets during champagne cork popping", *Science Advances* 5(9),
  2019, doi:10.1126/sciadv.aav5528; and the Helmholtz resonance of the open neck.
- **The pad** - PADsynth, by Nasca Octavian Paul (ZynAddSubFX): harmonics as bands of
  frequencies with random phases in one looped table. A lite version without the FFT.
- **Random numbers** - S. K. Park, K. W. Miller, "Random Number Generators: Good Ones Are
  Hard to Find", *Communications of the ACM* 31(10), 1988 (the minimal standard, 16807).
- Champagne acoustics background (not implemented directly): K. Spratt, K. Lee,
  P. Wilson, "Champagne acoustics", *Physics Today* 2018.

### Build tools

- **wgslender** (Hugo Daniel, CC0-1.0) - WGSL tree-shaking. Vendored.
- **terser** (BSD-2-Clause) - JS minification, with its dependencies acorn, commander,
  source-map-support, buffer-from, @jridgewell/* (MIT) and source-map (BSD-3-Clause).
  Vendored; licences in `build/vendor/node_modules`.
- **Brotli** (Google, MIT) - via Python's `brotli` package.
- **Late-acceptance hill climbing** (the packer search) - E. K. Burke, Y. Bykov, "The Late
  Acceptance Hill-Climbing Heuristic", *European Journal of Operational Research* 258(1),
  2017 (Bykov's 2008 report first).
- **Roadroller** (Kang Seonghoon, MIT), in Aske Simon Christensen's (Blueberry's)
  `intro-size` fork, https://github.com/askeksa/roadroller - packs the page's script.
  Vendored at its commit in `build/vendor/node_modules/roadroller`; its decoder, which
  ships, is public domain.

### Lettering

- **Josefin Sans** by Santiago Orozco, SIL Open Font License 1.1
  (https://github.com/ThomasJockin/JosefinSansFont-master; `dev/fonts/OFL.txt`). The
  intro's capitals are our own pen strokes after its SemiBold shapes; no font file ships,
  and the strokes do not use its Reserved Font Name.

### Disclosure

The party requires full disclosure of generative-AI use and bans prompt-based music. The
NFO has to say that much of the code - renderer, simulation, sound engine and build - was
written with an AI coding assistant (Claude, by Anthropic) under the author's direction,
and that the music (the score) is composed by the author. The wording is the author's.
