# Working notes for Claude Code

Read `README.md` first for what the project is. This file is about *how to work on it* —
the harness, and the traps already paid for.

## The loop

Everything lives in `dev/champagne.html`, one self-contained file. WGSL is in
`<script type="text/wgsl">` blocks read with `innerText` — never `fetch`, or `file://` breaks.

To see it yourself you need localhost; the browser pane turns `file://` into a static
snapshot and `data:` URLs have no `navigator.gpu`:

```bash
python dev/serve.py
```

(`http.server` on 127.0.0.1:8787 plus the timeline editor's save.) Then navigate to
`http://localhost:8787/champagne.html?...`, read `window.__probe()` for numbers and errors,
and screenshot for the look. The timeline editor is `?edit=1` (README, *The timeline
editor*); the user tunes the timeline there and SAVES INTO `dev/champagne.html` - so the
shot block and slider defaults can change under you between turns. Re-read before editing
them, and never assume your last version is the current one.

**Force a paint before reading the probe.** The pane pauses `requestAnimationFrame` when it
isn't painting, so a probe read without a preceding screenshot returns stale zeros. This has
produced false "it's broken" readings more than once.

**Pause the renderer when you finish a check** — `window.__pause()`. Otherwise it spins the
user's GPU in the background. The user has asked for this explicitly.

**Reproduce framing via URL params, not prose.** `angle, dist, camY, tgtY, lightAz, lightEl,
fill, view, w, h, steps, bounces, parts, bubbles, waves, refl, gridenv` all work.
A link beats a description when comparing before/after.

## Verifying

- `?selftest=1` — assertions, logs PASS/FAIL.
- The timeline editor has tests at three levels; run all three after touching it:
  `node --test "dev/tests/*.test.mjs"` (its logic), `python -m unittest discover -s dev/tests
  -p "test_*.py"` (shot table, save server), and `?edit=1&edtest=1&det=1` in the pane
  (`__probe().edtest`; the pane must be on screen, or no frames run).
- `?det=1` (implied by `?still=1`) makes frame N always step N, so a run is reproducible
  on any machine. Use it for any A/B: without it the two sides see different sim states.
- `?show=1&showt=<s>&pause=1` lands on an exact show frame for judging a shot. Without
  `pause=1` playback keeps running while you wait and you grade the wrong moment.
- A seek REPLAYS the timeline, 0.25 s of show per frame, so keyed pour/bottle/light apply
  when they should (a one-frame burst poured from t = 0 with the target's values - the
  uniforms are per frame). It is representative, not bit-identical: spill azimuths land
  elsewhere by the RNG; do not diff individual levels against a live run.
- **Pixel-exact A/B across a reload:** `?det=1&simSpeed=0&fill=88`, ff twice, wait 3 s,
  then `__saveRef(name)` before the change and `__diff(await __loadRef(name), await __grab())`
  after. With levels pinned the frame is bit-identical between loads; with spill running it
  is not (the overflow emitters race on a compare-and-swap). Noise floor: up to a few dozen
  table pixels by one level (the photon map's integer decay settles on neighbouring fixed
  points). Grab only after things settle (the table puddle, since cut, reached the shader
  through an async readback; a grab before it landed differed on 15% of pixels).
- Isolation views settle arguments far faster than reasoning: `liquid`, `glass`, `tir`,
  `bottle`, `medium`, `steps`, plus `gridEnv` for reflection/refraction direction.
- **The pane must be on screen.** A hidden browser pane runs the page as a background page
  at ~2 fps; the per-pass timestamps still measure real work, but the GPU downclocks between
  frames and inflates them. If `frameMs` is wildly larger than `gpuMs.total`, the reading is
  an upper bound, not a measurement. `show_pane` reports whether the session is open in a
  window at all — if it isn't, the user is away and a real profile has to wait.
- **A/B a code change on a frozen state:** load both versions with `det=1&simSpeed=0`, click
  `ff +20s` twice. The clock never moves on its own, so both land on exactly step 2400, and
  the page keeps rendering every frame with the GPU busy. Paused redraws are no substitute
  for timing: the GPU downclocks between them and inflates the numbers by ~40%.
- Perf numbers only from the real GPU **at 1920×1080**, which is what the budget is set at.
  The debug pane is ~1100×880, barely half the pixels, and the render pass scales with them,
  so a pane-sized number flatters the frame by about 2×. This already produced one wrong
  conclusion ("17.7 ms, slightly over" when it was nearer 31). Pass `w=1920&h=1080` and quote
  the per-pass split, not just the total.

## Traps already paid for

Each of these cost real time. They are the reason the code looks the way it does.

**A constant is not a distance.** `if (p.y > 0.03) return p.y - 0.03;` in an SDF looks like
a cheap bound; it is a horizontal plane spanning the scene that reaches zero wherever a ray
descends through 3 cm. Because air sat on both sides it was invisible — it just ate a bounce
from every grazing ray, and rays exhausting their budget at different distances banded into
concentric rings on the table. Bound regions in **every** axis, so the value only reaches
zero where the thing actually is.

**Clamping a sampled field smears its border to infinity.** The caustic map did this and
painted long streaks across the floor. Return zero outside, with a short fade.

**Coincident surfaces band.** Liquid meeting glass exactly let float noise pick the medium,
which showed as concentric rings. The liquid now overlaps 0.5 mm *into* the shell and
`mediumAt` resolves by priority. Same class of bug: filling a glass to exactly the rim made
the liquid plane coplanar with the glass's cut plane.

**Bounce-budget truncation is visible, and how you truncate decides how.** Dropping leftover
energy to black quantises into rings; sampling `env(d)` directionally shatters into
checkerboard shards, because after several refractions neighbouring pixels point in wildly
different directions. Resolving to a constant haze degrades gracefully.

**The shutter streak is per SIM STEP; the narrow band is rebuilt per FRAME.** Those are the
same thing only at 60 fps. Below it a particle moves `simSteps` steps between rendered
frames while its streak still spans one, so the gap reopens and the pour returns to the bead
chain the swept capsule exists to prevent — and fast drops pin to the length cap, which is
what "clamped" looks like. The shutter is now scaled by the steps the frame stands for
(bounded at 4, and never taken from a seek burst, which runs thousands in one frame). The
cap moved with it: `2.88 * u.shut` is exactly the old 24 mm at the default half-shutter and
one step. General form of the trap: anything sized in sim steps that is CONSUMED once per
frame is wrong as soon as the two rates diverge.

**Scaling a coordinate inside `length()` does the opposite of what it looks like.**
`length(p * vec3f(1, 0.62, 1)) - r` is an ellipsoid r/0.62 TALL, not 0.62 r tall. The
coupe's knuckle was meant to be squat and came out 12.9 mm high, rising ~17 mm into the
bowl as a dome in the champagne. Fixed by carving the cavity out after all the blends, which
guards against every fillet, not just this one. The foot had a related problem: a rounded
cylinder whose rounding pushed it to y = -1.3..7.7 mm, a 9 mm puck sunk into the table.
Measure a primitive's real extent, don't read it off its parameters.

**Don't smin two surfaces that already meet tangentially.** The stem's foot flare met the
stem tangentially, so near the junction the two ran within a couple of mm of each other -
and a polynomial smin of near-coincident surfaces inflates them by up to k/4, then stops
dead where one primitive ends: a collar ring round every stem. `min` removed the collar but
left a seam line, because the flare's flat top cap, though never on the surface, bent the
finite-difference normals of points just above it. The fix that has neither: make it one
surface (a profiled stem radius). Check junctions in `view=normals`, which shows a kink
plainly where refracting glass hides it.

**Measure with the scene in the state the intro is actually in.** `fill=88` pins the levels,
so there is almost no spill, and the pour shot measured 21 ms; with autofill and the tower
overflowing it is 34. Spray is where the cost is. For a reproducible spill state use
`det=1`, click `ff +20s`, and measure after step ~1300.

**A toggle that multiplies a result by zero still pays for computing it.** `refl=0` said
reflections were free, because it only scaled the traced reflection; the trace itself kept
running. The real switch was `rtrace`, and the trace turned out to be 41% of the render
pass: up to three extra marches per pixel, at two bounces, on every surface past ~53°.
Sweeping `bounces` from 1 upward is what exposed it - half the render pass was the FIRST
bounce. Now it traces only where air meets the bulk champagne surface (`rtrace` 1), the one
place it was ever needed; drops and glass use the environment.

**When a change is cheap, prove it is running.** The bulk-surface trace measured 0.2 ms,
indistinguishable from "never fires", and side-by-side frames looked identical because a
reflection that escapes returns `env(d)` either way. Painting the traced pixels magenta
answered it in one frame. Also: capping droplet interactions per ray made it SLOWER - rays
dying in the spray had been saving the tower traversal behind it.

**Anything racy in a distance field shows up as flicker.** The coarse far field kept one
particle per cell with a plain store - whichever thread wrote last - and jump-flooded in
place, threads reading cells others were writing. Both changed every frame, so the steps
rays took past the spray changed, and drops flickered with the simulation frozen. Now the
seed is the particle nearest the cell centre (atomicMin on a packed key) and the flood
ping-pongs between two regions. Test for determinism the way it was caught: freeze the sim
(`simSpeed=0`) and compare two frames.

**Fast and slightly wrong was beating correct by 10 ms.** Replacing that field with a
provably safe occupancy bound fixed the flicker but cost 10 ms on tier2, because a proven-
empty-neighbourhood bound only allows ~20 mm steps near spray while the nearest-seed
distance allows 100+. The kept fix removes only the nondeterminism; the field still uses
the old 0.85 safety factor on an estimate, now identically every frame.

**Measure the state the user measures.** A fast-forwarded state is lighter than natural
evolution - bursts do not reproduce it - and tier2 read 25 ms there against 29-34 in a
real run. For a heavy, reproducible state: `det=1`, run naturally to step 3120 (t = 52 s),
then set `simSpeed` 0. It takes about two minutes of wall time.

**An `atomicLoad` in the fragment shader is not a cached load.** The occupancy grid and the
far-field seeds live in an atomic buffer because the compute passes build them with
atomics, and the render read them there: two atomic loads and a dependent particle read
per spray lookup, 3.1 ms of tier2's 24.8. Anything the render reads per march step must be
in a plain buffer — `packCoarse` copies it out after the flood.

**Count before you guess, then rank by duplication.** `__profile()` gives exact per-frame
counts (steps per bounce, why rays end, evaluations per component); `__xc(bits)` makes a
component run twice with an unchanged picture and the time delta ranks it. Duplication
deltas are not additive — register pressure inflates them past the frame — so use them to
order suspects, then confirm with a real A/B. The atomic-load finding came from a
four-instruction lookup out-ranking the 8-fetch trilerp by 4×.

**"X takes 30% of the steps" does not mean capping X saves 30%.** The rays that ran out of
bounces took ~30% of all march steps, but most of that was in the early bounces every ray
shares; a cap only removes the late ones, and even `bounces` 6 saved 16%. Ask what the
change actually removes. Judge a look-changing cut with `__grab`/`__diff` on a frozen
frame, steps from `__profile` (exact), and time only from interleaved repeats — the GPU's
baseline drifted by 3 ms within one session here.

**An analytic shortcut must also bound the march.** The table was made a ray/plane test so
grazing rays would stop burning steps on it - but the march still ran first, to FAR, and
the plane only replaced its answer. Rays bound for the table marched on beneath it through
the puddle test: 13% of all steps, ~3 ms render and ~0.9 ms of photons. Anything resolved
analytically has to hand its distance to the march as a `tmax`. Stop on the last proven-
empty sphere reaching it (`tPrev + rPrev >= tmax`), never on `t` passing it, or an
over-relaxed step jumps a surface just in front.

**A global cap is a plane wherever its other axis is zero.** The puddle bound was
`max(dh, y - PMAXH)`: bounded horizontally, as the trap above demands, but over every wet
block `dh` is 0 and what remains is a plane 20 mm up, crossed in 0.8 mm steps. Bound by the
local maximum (puddleCoarse keeps it per block, over the neighbourhood the renderer reads),
and fall back to the global cap only where it is provably far. Keep the other axis's term in
the fallback too: dropping `dh` there capped every low step in the scene at one block.

**A particle smaller than a voxel vanishes.** The fine cell is 1.94 mm, so a drop only
registers if it lands near a cell centre. Keep `dropRad` above the cell half-diagonal
(~1.68 mm) or raise `FINE`. Symptom: a dense stream renders as four scattered drops.

**Emission must be sub-frame.** Every drop born on one frame starting at the same point makes
each frame's cohort fall as a clump; at spill speeds the clumps land ~17 mm apart and read as
bead chains. Offset each by a random fraction of the step, velocity *and* gravity included.

**Emitters need their own particles.** Spill drew from the shared pool and starved the
bottle to a trickle. The bottle owns a reserved slice.

**`atomicSub` on u32 underflows and invents volume.** Use compare-and-swap. The symptom was
a tower where every glass was full except the one being poured into.

**Thin shells tunnel.** The glass wall is 1.4 mm and a falling drop moves ~40 mm per step.
Never collide with "push out of negative SDF" — use a position constraint, which cannot
tunnel at any speed.

**`fract(sin(dot(...)))` degenerates at large indices.** At 262 144 photons the argument
reaches ~3×10⁷ and f32 `sin` has no precision left, so samples come out correlated. Use the
PCG hash (`rnd3`). It silently corrupted both photon emission and particle spawning.

**`smoothstep` has a curvature discontinuity.** Fine for blending, visible as a crease on a
shiny silhouette. Use smootherstep (`6t⁵−15t⁴+10t³`) for shapes. Also: only ~60% of a
smootherstep span reads as curvature, so a shoulder looks about two-thirds the span you set.

**A hard yield threshold terraces.** Thresholded diffusion settles into a staircase one
threshold high per step — concentric rings from a central source. Ramp it smoothly.

**Far clips must exceed the scene.** The table runs to the horizon; a 4 m clip silently
replaced distant table with environment.

**The canvas CSS stretches.** An explicit `w`/`h` whose aspect differs from the viewport was
being squashed, so shape judgements were made on distorted frames. It letterboxes now — and
the letterbox is recomputed whenever the viewport changes, not only at load. It used to skip
the resize listener whenever `w`/`h` were given, so a page opened while the pane was hidden
(viewport 0×0) scaled the canvas to `0px` and left it there: overlays visible, picture gone,
GPU still rendering 1920×1080 at full cost. If the HUD is there and the render isn't, this
is why.

**Check that ALL of the sim steps on the clock, not just the part you fixed.** The particles
were moved onto a clock; `puddle`, `glassUpdate` and `waveUpdate` stayed in the per-frame
build pass and went on advancing at the frame rate. It was invisible at 60 fps because frames
and steps matched one for one, and it only showed when a seek ran 3000 steps in one frame and
filled exactly one glass. The rule the dispatch order now follows: a pass that **advances
state** belongs in the per-step loop, a pass that **builds a structure for rendering** (the
narrow band, the JFA, the puddle's coarse bound) belongs per frame.

**Integrating a level over a shape whose area goes to zero overshoots.** The glass level
was `L += Q / A(L)`, and a spherical cap's area is ~0 at the bottom, so the first drops
of a step sent the level to the rim and the overflow, computed with that tiny area, lost
the excess. The top glass read full 0.3 s into the pour, and the error depended on the
step size - it only showed when slow motion made the steps smaller and the glass filled
differently. Keep the conserved quantity (volume) as the state and derive the rest.

**A position constraint must leave slack.** Putting a drop exactly ON the bowl's
interior sphere let float rounding flip the next substep's "was it inside?" test, and the
drop fell through the glass. Constrain to a radius inside, test against the full radius.

**Slow motion must shrink the step, not skip it.** Whole 1/60 s steps run less often show
the same frame several times (at 0.25, motion at 15 fps). A smaller step means everything
sized per step has to scale: waves, decay rates, emission cadence, the motion streak.

**One sim step per rendered frame makes the sim run at the refresh rate.** It reads as
correct because the step size is fixed, but the step *rate* is then the frame rate:
measured 1.160× at 66 fps and 0.624× at 39. Against music that error accumulates for the
whole run. The step index must come from a clock, and a deficit must be KEPT and worked off
rather than discarded — discarding it is exactly how the drift gets in. Corollary: a
deliberate burst (the ff button, 1200 steps) has to be allowed past the steady-state
catch-up cap, or it silently skips instead of simulating and the glasses never fill.

**A debug toggle must isolate exactly one thing.** `parts=0` also disabled the puddle, which
sent a bisection at the wrong subsystem for several rounds. When a toggle's result is
surprising, check the toggle before believing it.

**A toggle that removes geometry does not measure the cost of sampling it.** `parts=0` looked
like it proved the particle field cost 8 ms of render, and the conclusion written down was
that an occupancy skip would recover it for free. It recovered 0.9. Turning the field off
also deletes the spray, so rays stop marching around it and refracting through it and finish
in fewer bounces — most of that 8 ms is what the spray costs to draw. Before calling a number
overhead, ask what else the toggle changed; the honest test is a change that removes the work
while keeping the picture, which is what the skip finally was.

## Conventions

- WGSL and JS in one file; keep the dev scaffolding separable, since the build will strip it.
- Every tunable gets a slider **and** a URL param **and** a tooltip. The user drives this
  thing by hand and judges it by eye; a constant buried in a shader is a constant nobody
  can evaluate.
- Comment *why*, especially where a value encodes a trap above. Several of these bugs were
  reintroduced because the original reasoning wasn't written down.
- Prefer analytic intersection to marching where exact: the table is a plane and ray/plane
  removed both artifacts and cost.
- Anything inside `map()` runs ~100 steps × 2 M pixels. The question is never "is this
  cheap" but "can it be skipped" — hence the bounding sphere on the bottle, the conservative
  early-out on the wave fetch, and the coarse occupancy grids.

## Editing safely

**There is now a git repo — use it.** An index-based splice once deleted ~27 KB of shader
including every compute entry point; it was only recoverable because a browser tab still
held the old document in its back-cache. Commit before structural edits.

When patching with a script, anchor on unique strings and assert the match count. Replacing
between two `str.index` results will happily swallow everything in between.

**`open(path, 'w').write(f())` empties the file before `f()` reads it.** Python opens -
and truncates - first, then evaluates the argument. A generator that spliced its block into
`dev/champagne.html` that way read back an empty file, failed, and left the harness at 0
bytes; it came back only from git. Read, build the new text, check it, then write through a
temporary file and `os.replace`.

**Write regex-bearing patches as script FILES, not heredocs or `python -c`.** Twice a
`\b` or `\1` came through a shell layer as a literal backspace or \x01 byte: the pattern
silently matched nothing, and in one case a replacement wrote control bytes into the
build's own output. Afterwards, check the file for bytes below 0x20 other than newline/tab.

## Building

`python build/build.py` produces `build/intro.html`. Dev-only code sits between `//#D{` and
`//#D}`; everything else the build decides by rule (see the README). Three things it has
already cost, all of which look like success until you check:

**A renamed entry point is a WARNING, not an error.** The minifier renamed `vs` and `fs`
because `@vertex fn vs(` sits on one line and the guard pattern expected a newline. The
shader compiled clean, the pipelines came back invalid, and WebGPU said so at warning level
— so `read_console_messages` with `onlyErrors` showed nothing and the screen was simply
black. Entry points are now protected twice: by attribute, and by every quoted word in the
JS. When the build renders black, check the console WITHOUT the error filter first.

**The console buffer survives navigation.** After fixing it, the same invalid-pipeline
warnings were still listed — left over from the broken loads. Open a fresh tab before
believing a console check.

**Text-level folding must never see a comment.** `fold_branches` works on text. A WGSL
comment saying "every `if (PROF)` away" became `if (false)` after the profiler
substitution and was folded as code: everything up to the next matching brace vanished,
glass constants included. The module then failed to compile, which shows only as
"Invalid ComputePipeline" warnings and a black screen. Comments are now stripped before
any folding. To find a compile error in the release, compile `build/min.wgsl` yourself
and read `getCompilationInfo()` — the page only reports the invalid pipelines.

**The browser pane never goes fullscreen, and does not start on white.** The release made
the canvas fullscreen, which in Chrome hides everything outside it - the lettering's
overlay included - and every check in the pane passed. Text, overlays and anything else
the release puts outside the canvas need a look in the user's Chrome.

**Firefox draws an unpainted WebGPU canvas black; Chrome leaves it clear.** With the
full-screen canvas there from the start, Firefox's start screen was black: "click" (page
text under the canvas) gone, the white words (in the overlay above it) showing. The
release's canvas is now `hidden` until the click, as INCENDIUM's is small and inline until
its click: the start screen is then the browser's own page, in its own colours. Check the
start screen in Firefox too.

**A canvas is not a void element.** The page is `<canvas ...>` and then the script, with no
end tag - fine for a script, but markup put after it (the lettering's overlay) became the
canvas's fallback content: parsed, never drawn, and `canvas.nextSibling` null. `assemble`
closes the canvas when there is page markup.

**The page must open with a tag the sniffer knows.** The dropper sends no Content-Type, so
the browser sniffs; `<body>` passes, `<canvas>` does not and the page came up as plain
text. `assemble` puts `<body>` first - it looks removable and is not.

**A created pipeline is not a compiled one.** Chromium's `createComputePipeline` returns
at once and compiles lazily; on a cold shader cache the first submit waited 3-7 s, after the
click, with the music already running. Your own machine's cache hides it - test start-up
in a FRESH browser profile. The release awaits `create*PipelineAsync` before showing
"click".

**Never give a local the name of a parameter.** `waveUpdate` gained a parameter `nw` while
its body already had `var nw`: the harness compiled it, but the packer gave both one short
name and the release failed with "redeclaration" - while the build reported success. After
any shader change, load the RELEASE (`build/intro.cmd`'s payload) and check that it
compiles; a working harness proves nothing about the packed shader.

**Generated names must contain a digit.** A two-letter pool produced `as`, a WGSL reserved
word. Everything past the single letters now carries a digit.

Bisect a broken build by stage, not by reading: comments, then whitespace, then renaming,
each as its own payload. That found the renamer in three page loads.

## Packaging

**Brotli needs no decompressor — it needs a web server.** Stock Windows PowerShell is 5.1
on .NET Framework: `DeflateStream` yes, `BrotliStream` no, no `pwsh` 7. And the browser's
`DecompressionStream` does gzip, deflate and deflate-raw, never brotli. Both true, and both
beside the point: INCENDIUM's 324-byte bootstrapper **serves its own bytes over HTTP** from
the Windows built-in HTTP server, at an offset into itself, and the browser decodes
`Content-Encoding: br` natively. Their README says it plainly — brotli content can only be
served by a web server, not opened as a local file. So brotli is reachable without a native
exe; our dropper inflates deflate instead and pays ~1050 bytes for it.

**`New-Object ...DeflateStream($m,0)` throws on an ambiguous overload**, because 0 fits both
`CompressionMode` and `CompressionLevel`. Name the enum. Costs 33 bytes in the dropper.

A dropper that inflates is why the payload needs no encoding at all: base64 costs a third,
and the byte-string alternative still needs escaping. Let PowerShell do the inflating and
the bytes go in raw.

## Minifying

**Score every change on COMPRESSED bytes.** `python build/experiment.py` builds the real
payload under each strategy and reports brotli. Source size is not a proxy: renaming every
local to a fresh short name makes the file 361 bytes smaller and the brotli output 250
bytes *bigger*.

**A good name is one you reuse.** Locals drawing from the same pool in every function, so
`a`, `b`, `c` recur, beat per-function fresh names by 291 bytes at identical source size.
That is the entire mechanism: the compressor rewards repetition, not brevity.

**Order the name pool by LENGTH first.** Ranking by average character frequency put 3-char
names above 2-char ones and renamed locals from 2 characters to 3, costing 325 characters
before compression even ran.

**Sort before assigning, or the build is nondeterministic.** Set iteration order moved the
compressed result ~30 bytes a run, which is larger than most wins being measured. (It also
shows a search over assignments is worth real bytes - what Pakettic-style packers do.)

**A real parser beats the regex at analysis, and loses at naming.** wgslender tree-shakes
dead declarations and rewrites syntax, which the hand-rolled minifier cannot do. Used
for renaming as well it is 599 bytes smaller on disk and 733 bytes LARGER after brotli,
because it optimises raw size and hands every identifier its own name. The build takes
its analysis (`--no-mangle --no-whitespace`) and keeps our naming: 287 bytes better than
either alone. `--no-whitespace` is required - globals are found with a line-anchored
pattern that a one-line file defeats. Its validator also rejects our `atomicAdd` calls as
`@must_use` where Dawn accepts them, so `wgslender validate` reports errors on a shader
that compiles and runs. Re-check all 11 entry points (9 compute, `vs`, `fs`) survive tree-shaking after adding
a compute pass.

**wgslender tree-shakes; it does not constant-fold.** Inlining the release uniforms alone
made the brotli 13 bytes worse. The build's own `fold_branches` evaluates the literal
comparisons and deletes dead ifs; only then does tree-shaking find unreferenced helpers.
And keep the leading zero on literals: wgslender rejects `.5`, and the build stops on it.

**The build has no fallbacks, on purpose.** wgslender and terser are vendored in
`build/vendor/node_modules` (committed) and run with plain `node`; it used to be
`npx --yes`, which fetched whatever was newest, and a missing tool or a failing packer
fell back to a weaker path that built a bigger intro with only a log line to say so. The
user builds at the party on a laptop: the same sources must give the same `intro.cmd`, or
`BUILD FAILED`. Keep it that way - never add a silent fallback.

**`build/pack_state.json` is a build input, not a cache.** It is the search result, it is
committed, and every build applies it. It is keyed by source names, so it degrades
gracefully as the shader changes — but a big refactor leaves it mostly default, and the
search is worth re-running (`python build/pack.py`). Validate the shader in the browser
after any search: correctness is by construction, and construction has had bugs.

**Multi-character operators must be single tokens.** The packer's tokenizer first split
`->` into `-` `>`, then its own rule against fusing operators kept them apart, and every
signature came out `)- >f32`: black screen, WebGPU warnings only. Same failure shape as the
renamed entry points; same remedy - compile it, then look at it in a fresh tab.

**The search is brotli-bound.** 81% of an evaluation is brotli q11, 19% Python. It scales
with physical cores, not threads. Do not score with a lower quality to go faster: q9 is
790 bytes off and would optimise for the wrong compressor.

**Repetition is nearly free under brotli; only code that goes away saves bytes.** Merging
three near-identical trace loops (1.8 KB of source) saved ~35 bytes; an exact 203-char
duplicate cost 44. Estimate a dedup at a fifth of its raw size at most, and don't build
runtime string assembly to remove repeats - brotli already does it.

**Measure a shader edit with the packer's DEFAULT state on both sides.** The saved search
state is tuned to the shader it was searched on and flatters that version by ~100 bytes
against any edit, so `build.py` alone can show a real saving as a loss. The trace merge read
+23 shipped and -35 fair.

**The release JS is the harness JS, cut - so write the harness the way the release needs
it.** Setup longhand (15 bind-group entries spelled out, zero-fill uploads WebGPU already
does, a uniform write per dead field, URL parsing that survived as dead calls) was 842 + 251
bytes. Tables and generated layouts in the harness itself fixed it with one source of truth.

**GLSL-minifier syntax tricks don't pay in WGSL under brotli - measured.** On the shipped
payload: `vec3f(0.)` -> `vec3f()` 48 chars shorter, 0 bytes compressed; one-letter
`alias` for vec2f/3f/4f +18; splatting equal constructor arguments +18; dropping the dot
on integer float literals -16 at best (unchecked upper bound). Most of Shader Minifier's
other transforms have no WGSL form (braces are mandatory, no comma operator, no ternary
statements, no overloading). Don't spend time here.

**The build runs Roadroller - Blueberry's fork - on the page's script, brotli on top.**
Context mixing beats brotli alone: on 31 Oct, 10 306 -> 9 944 with stock 2.1.0 and
**-> 9 514 with askeksa/roadroller branch `intro-size`** (float predictions, a shared
table, mixer weight sets, identifier contexts, a smaller decoder; the fork the top 4k web
coders use, pouet topic 13094). Vendored at its commit in
`build/vendor/node_modules/roadroller` (VENDORED.md); `build/roadroller.py` packs with the
settings in `build/roadroller.json` - fixed, so builds are deterministic and take ~1 s -
and `python build/roadroller.py` re-runs the -O2 search (~40 s) and saves new ones. Its
output is printable ASCII spread thin on purpose, for a compressor after it: served raw it
is bigger, never serve it without brotli. It adds ~0.4 s of decoding before "click".
`pack_state.json` still pays under it (default packer state: 9 612), though its search
scores brotli alone - and a brotli gain mostly does not carry over: a fresh search took
brotli alone -45 and the shipped size only -10, then -34 more once Roadroller was
re-searched on the new script. So after a packer search, re-run `build/roadroller.py`
and keep the pair only if `intro.cmd` shrank. A packer bug now shows up as a
Roadroller-packed page that fails, so compile `build/min.wgsl` directly when the release
is black.

**Small wins on top, all measured on the shipped size (31 Oct, 9 514 -> 9 426 with the
searches):** Roadroller's `-D` decoder, -22 (its globals cannot clash with ours: the
decoder is done before our script is eval'd); terser `passes=2`, -16 (passes=3 the same,
the unsafe rewrites worse under Roadroller); brotli's window searched 10..24, -6
(INCENDIUM's slow mode does it too). Measure terser and packer changes through the whole
chain - brotli alone ranked `unsafe` second, Roadroller ranked it last.

**Never rename a member access.** The substitution uses a `(?<![.\w])` guard so a rename of
`pos` cannot touch `p.pos`.

## Ground rules

- Performance budget is **16.6 ms** at **1920×1080** (confirmed) on the compo PC, an **RTX
  5070**. Dev is on a 4070, ~15–20% slower, so the number to hit here is **~19 ms**. It is
  camera-dependent and only the worst shots fail. The worst measured is the heavy natural
  tier2 frame (step 3120): **~22.1 total, ~18.0 render** after the packed far field, the
  plane-bounded march and the local puddle bound (was 29.9). Non-render passes are ~4 ms. Step count, reflections and photon count are **not**
  levers, and neither was skipping empty particle blocks (0.9 ms, not the 8 that `parts=0`
  suggested), nor wasted trilerps (exact block reach cut them 36% for 0.4 ms), nor the rays
  that exhaust the bounce budget (every cap trades ~1% of steps for ~1% of changed pixels,
  on the rim glints), nor bounding the march by the scene's bounds (steps in empty sky are
  cheap), nor a tighter coupe bound (fewer exact evaluations, no fewer steps, slower).
  Inside the domain box the steps are now limited by geometry that is really there - bulk
  liquid, tower and spray about a third each (README, *What limits the steps*).
- Size budget is **8192 bytes** for the whole entry, dropper included — confirmed by the
  organisers on 20 Oct 2026; it was 4096 until then, so anything that still says 4 kb is
  stale. Our dropper header is 226 bytes. `intro.cmd` is **9 344** (31 Oct 2026), 1 152
  OVER, with the start screen, the sound engine and the lettering in but the score empty;
  to leave them room, what exists must reach
  ~5.8 KB. The lossless options are spent - the rest is features, cut or simplified. The
  README (*Where it lands today*) has the size map by feature and function.
- Music must be composed by the user. The party bans prompt-based music, requires full
  disclosure of generative-AI use, and disqualifies entries that are mostly AI output. The
  NFO must carry the disclosure.
- Don't start the size-squeeze work until the look is frozen; it is the part that eats weeks.
