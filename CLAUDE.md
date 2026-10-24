# Working notes for Claude Code

Read `README.md` first for what the project is. This file is about *how to work on it* —
the harness, and the traps already paid for.

## The loop

Everything lives in `dev/champagne.html`, one self-contained file. WGSL is in
`<script type="text/wgsl">` blocks read with `innerText` — never `fetch`, or `file://` breaks.

To see it yourself you need localhost; the browser pane turns `file://` into a static
snapshot and `data:` URLs have no `navigator.gpu`:

```bash
python -m http.server 8787 --bind 127.0.0.1
```

Then navigate to `http://localhost:8787/champagne.html?...`, read `window.__probe()` for
numbers and errors, and screenshot for the look.

**Force a paint before reading the probe.** The pane pauses `requestAnimationFrame` when it
isn't painting, so a probe read without a preceding screenshot returns stale zeros. This has
produced false "it's broken" readings more than once.

**Pause the renderer when you finish a check** — `window.__pause()`. Otherwise it spins the
user's GPU in the background. The user has asked for this explicitly.

**Reproduce framing via URL params, not prose.** `angle, dist, camY, tgtY, lightAz, lightEl,
fill, view, w, h, steps, bounces, parts, puddle, bubbles, waves, refl, gridenv` all work.
A link beats a description when comparing before/after.

## Verifying

- `?selftest=1` — assertions, logs PASS/FAIL.
- `?det=1` (implied by `?still=1`) makes frame N always step N, so a run is reproducible
  on any machine. Use it for any A/B: without it the two sides see different sim states.
- `?show=1&showt=<s>&pause=1` lands on an exact show frame for judging a shot. Without
  `pause=1` playback keeps running while you wait and you grade the wrong moment.
- A seek is representative, not bit-identical: the catch-up burst wraps the 16 sub-step
  slots, so the RNG stream differs and spill azimuths land elsewhere. Glass counts and the
  overall state match; do not diff individual levels against a live run.
- Isolation views settle arguments far faster than reasoning: `liquid`, `glass`, `tir`,
  `puddle`, `bottle`, `medium`, `steps`, plus `gridEnv` for reflection/refraction direction.
- **The pane must be on screen.** A hidden browser pane runs the page as a background page
  at ~2 fps; the per-pass timestamps still measure real work, but the GPU downclocks between
  frames and inflates them. If `frameMs` is wildly larger than `gpuMs.total`, the reading is
  an upper bound, not a measurement. `show_pane` reports whether the session is open in a
  window at all — if it isn't, the user is away and a real profile has to wait.
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
that compiles and runs. Re-check all 17 entry points survive tree-shaking after adding a
compute pass.

**wgslender tree-shakes; it does not constant-fold.** Inlining the release uniforms alone
made the brotli 13 bytes worse. The build's own `fold_branches` evaluates the literal
comparisons and deletes dead ifs; only then does tree-shaking find unreferenced helpers.
And keep the leading zero on literals: wgslender rejects `.5`, and its failure makes the
build fall back to the unshaken shader without stopping - watch for the `tree-shaken`
line in the build output.

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

**Never rename a member access.** The substitution uses a `(?<![.\w])` guard so a rename of
`pos` cannot touch `p.pos`.

## Ground rules

- Performance budget is **16.6 ms** at **1920×1080** (confirmed) on the compo PC, an **RTX
  5070**. Dev is on a 4070, ~15–20% slower, so the number to hit here is **~19 ms**. Measured:
  tower 13.6, pour 20.8, tier2 26.5 — it is camera-dependent, and only the worst shots fail.
  Non-render passes are a flat ~3.8 ms. The one real win is skipping the particle-field sample
  where the band is empty (~8 ms, no visual change); `bounces` is ~1.1 ms each after that.
  Step count, reflections and photon count are **not** levers — measured, see the README.
  Neither was the particle-field sample: skipping it exactly is worth 0.9 ms, not the 8 ms
  that `parts=0` suggested. `bounces` (~1.1 ms each) is the only real one found so far.
- Size budget is **8192 bytes** for the whole entry, dropper included — confirmed by the
  organisers on 20 Oct 2026; it was 4096 until then, so anything that still says 4 kb is
  stale. The dropper is ~324 bytes, leaving ~7870 for the payload. The harness as it stands
  Brotlis to 17 438 bytes with comments stripped; the README roadmap has the breakdown and
  where the rest has to come from.
- Music must be composed by the user. The party bans prompt-based music, requires full
  disclosure of generative-AI use, and disqualifies entries that are mostly AI output. The
  NFO must carry the disclosure.
- Don't start the size-squeeze work until the look is frozen; it is the part that eats weeks.
