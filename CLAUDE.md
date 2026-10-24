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

**A debug toggle must isolate exactly one thing.** `parts=0` also disabled the puddle, which
sent a bisection at the wrong subsystem for several rounds. When a toggle's result is
surprising, check the toggle before believing it.

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

## Ground rules

- Performance budget is **16.6 ms** at **1920×1080** (confirmed) on the compo PC, an **RTX
  5070**. Dev is on a 4070, ~15–20% slower, so the number to hit here is **~19 ms**. Measured:
  tower 13.6, pour 20.8, tier2 26.5 — it is camera-dependent, and only the worst shots fail.
  Non-render passes are a flat ~3.8 ms. The one real win is skipping the particle-field sample
  where the band is empty (~8 ms, no visual change); `bounces` is ~1.1 ms each after that.
  Step count, reflections and photon count are **not** levers — measured, see the README.
- Size budget is **8192 bytes** for the whole entry, dropper included — confirmed by the
  organisers on 20 Oct 2026; it was 4096 until then, so anything that still says 4 kb is
  stale. The dropper is ~324 bytes, leaving ~7870 for the payload. The harness as it stands
  Brotlis to 17 438 bytes with comments stripped; the README roadmap has the breakdown and
  where the rest has to come from.
- Music must be composed by the user. The party bans prompt-based music, requires full
  disclosure of generative-AI use, and disqualifies entries that are mostly AI output. The
  NFO must carry the disclosure.
- Don't start the size-squeeze work until the look is frozen; it is the part that eats weeks.
