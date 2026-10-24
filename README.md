# comparade26 — champagne tower

A realtime 3D fluid simulation of champagne filling a three-tier champagne tower, rendered
entirely by SDF raymarching. Target: an **8192-byte PC intro** for **ComParade 2026**
(Emmering/Munich, 6–8 Nov 2026), packaged the INCENDIUM way — WebGPU + a tiny PowerShell
dropper — not a native exe.

**Current state: dev harness only.** The renderer and simulation work and look right. None
of the size-coding exists yet: no minification, no packing, no music. See *Roadmap*.

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
serve it instead:

```bash
python -m http.server 8787 --bind 127.0.0.1
```

Requires a Chromium-based browser with WebGPU. Developed against an **RTX 4070**.

---

## What exists

### Geometry

**Coupe** — matched to the manufacturer's spec: 280 ml, 170 mm tall, 112 mm wide. The bowl
is a spherical cap, so capacity fixes the depth analytically:

```
V = π·h·(3R² + h²)/6    →   R = 56 mm, V = 280 ml  ⇒  h = 46.3 mm
```

Slender 5.2 mm stem, a solid glass knuckle under the bowl (smooth-min), and a thin foot:
a plate 2.2 mm at the rim rising to 4.4 mm at the centre, flat underneath, which the stem
flares into as one surface, a concave trumpet 15 mm tall widening to 11 mm (`FLARE_H`,
`FLARE_R`). The bowl's cavity is carved back out last, so nothing the fillets or the knuckle
do underneath can show up inside the bowl. The tower is 1+4+9 = 14 glasses by SDF domain folding, 0.51 m tall, 0.336 m wide.

**Magnum** — 345 mm tall, 116 mm body, 30 mm neck, 3 mm wall, deep punt, hollowed to a shell
with the bore opened through the neck. Its silhouette is a radius-vs-height function
(`bottleR`), not a union of primitives: a champagne shoulder is an S-curve that a cone can't
make and a wide smooth-min erases. Of 345 mm the body is ~140, shoulder ~175 (span), neck
~105. The mouth is pinned to the pour emitter, so the bottle inherits the pour's wander.

### Simulation — hybrid, not Navier–Stokes

Free-falling liquid has no pressure gradient, so it needs no solver. The split:

| Part | Method |
|---|---|
| Stream, splash, spill, droplets | ballistic particles (65 536), no neighbour search |
| Liquid at rest in each glass | volume ODE `dV/dt = inflow − overflow` + 2D wave field |
| Spill on the table | 384² height field with yield-threshold flow |
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
frame because the sub-step index reaches the shader through 16 uniform slots and reusing one
would make two substeps share an RNG stream — the bug that used to thin the pour. Past
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

`?det=1` (implied by `?still=1`) swaps the wall clock for a fixed one so that frame N is
always step N. That makes a run reproducible on any machine, which is what A/B comparisons
need — `?still=1&warm=300` lands on `t = 5.0000` exactly.

### The timeline

`?show=1` hands the camera and the simulation speed to a keyframe table, `SHOW`, driven by
the show clock. Keys are `[t, angle, dist, camY, tgtY, simSpeed, ease]`:

- **Two keys sharing a `t` are a cut.** The later one wins at that instant, so the change is
  immediate instead of a one-frame blend.
- **`ease`** applies to the segment starting at that key: 1 for smootherstep in and out, 0
  for linear, so a long drift can run through several keys without stalling at each one.
- **`simSpeed` is keyed too**, and the sim clock is the integral of it over show steps, so a
  timeline that varies speed stays machine-independent.

The camera is driven from the table directly and only *mirrored* into the sliders for
readout. Routing it through them would quantise it to the slider step, and `dist` steps by
0.01 — visible stepping on a push-in that covers 0.01 in eight seconds.

Scrubbing with `showT` moves the camera immediately, which is what blocking shots needs, and
the fluid catches up on release. **Backwards means rebuilding the fluid from zero**, because
the simulation has no inverse — you cannot un-pour it — so it reloads with `?showt=`. A seek
is representative, not bit-identical: a catch-up burst wraps the 16 sub-step slots, so spill
azimuths differ. Seek and live playback to t=12 both gave 9 glasses filled and an identical
top glass, with per-glass levels differing by the RNG.

The current shot list is a **first draft timed against the simulation's real pace**, which is
the part that needed measuring rather than guessing: the top glass fills in ~20 s and the
full tower in ~48 s. The macro shot therefore runs 9—18 s while the top glass is filling, and
the cut to tier 2 lands on the first overflow. Duration is 60 s.

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
- Reflections trace a real short ray when Fresnel is strong, rather than sampling the
  environment — otherwise near-grazing liquid mirrors the sky instead of its surroundings.

### Pass graph

```
sim        N steps per frame, N from the clock — everything that advances state:
           particles → puddle → glassUpdate → waveUpdate ×3
build      once per frame — a rendering structure, needs only the final state:
           puddleCoarse → puddleJFA ×5
           clearFine → clearCoarse → scatterFine → seedCoarse → jfaCoarse ×5 → resolveFine
photon     causticDecay → photons → causticBlur
render     camera raymarch + post
```

The split matters: `puddle`, `glassUpdate` and `waveUpdate` used to live in `build` and so
advanced once per *frame* while the particles advanced on the clock. See *Timing*.

### Grids

| Field | Size | Cell |
|---|---|---|
| Particle narrow band | 320³ | 1.94 mm |
| Coarse nearest-particle (JFA) | 32³ | 19.4 mm |
| Caustic map | 768², ±0.55 m | 1.43 mm |
| Table puddle | 384², ±0.55 m | 2.86 mm |
| Puddle blocks (JFA) | 48² | 22.9 mm |
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

RTX 4070, 1920×1080, every camera preset at fill 88, everything on. Median of ~20 samples
after warm-up, window on screen:

| Shot | sim | build | photon | render | **total** | fps |
|---|---|---|---|---|---|---|
| tower | 0.13 | 1.84 | 1.84 | 9.76 | **13.57** | 74 |
| bottl | 0.20 | 1.84 | 1.84 | 12.45 | **16.25** | 62 |
| macro | 0.13 | 1.84 | 1.84 | 13.43 | **17.24** | 58 |
| top | 0.13 | 1.84 | 1.84 | 15.66 | **19.46** | 52 |
| pour | 0.20 | 1.84 | 1.84 | 17.04 | **20.84** | 50 |
| **tier2** | 0.20 | 1.84 | 1.84 | **22.61** | **26.48** | 38 |

`tier2` is 25.5 after the occupancy skip described below; the rest are unchanged.

Everything but `render` is flat at **~3.8 ms** regardless of shot or resolution. `render`
swings 9.8–22.6 depending on how much glass and liquid the camera is looking through.

Against the 19 ms target: four of six shots pass, `pour` is 10% over and `tier2` is **40%
over**. It is a camera-dependent problem, not a uniform one, which matters for the timeline —
the cheapest shots are also the widest, and tier2 is the expensive one to linger on.

### What each lever actually buys

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

Where the rest is: the spray lookup minus the trilerp is still the biggest item, and the
10.7% of rays that run out of bounces (inside spray and glass, ending in constant haze
anyway) pay for ~30% of the marching.

### WebGPU limits that must be requested

Several defaults were within a few percent of biting:

- `maxStorageBuffersPerShaderStage: 16` and `maxStorageBuffersInFragmentStage: 16` — we bind
  15 in dev (the profiler's counter banks are the 15th), 14 in the release.
- `maxComputeWorkgroupSizeX: 512`, `maxComputeInvocationsPerWorkgroup: 512` — 320³/256 would
  be 65 536 workgroups, one over the per-dimension cap, so the clear/resolve passes are
  512-wide.
- 320³ × 4 B = 125 MiB per buffer, just under the 128 MiB default binding size.

---

## Controls

Panel, top right. Every control has a tooltip; every one is also a URL parameter.

**View** — `beauty · steps · normals · medium · liquid · glass · tir · bottle · puddle`.
The isolation views are the debugging workhorses: `liquid`/`glass` show one field alone,
`tir` reddens total internal reflection, `puddle` shows the height field with contours,
`bottle` shows the magnum alone, flat-lit, for shape comparison.

**Camera presets** — `tower · pour · macro · tier2 · top · bottl`.

**Sliders/toggles** — `spin, angle, dist, camY, tgtY, lightAz, lightEl, gridEnv, rtrace,
drops, bubbles, waves, puddle, reflect, autofill, fill, pourRate, dropVol, dropRad, foam,
bottle, botTilt, botAz, pourWander, wanderSpd, shutter, bounces, simSpeed, expo, cgain`.

**Buttons** — `ff +20s` (jump the sim forward), `restart`, `pause` (also spacebar).

**Timeline** — `show` runs it, `showT` scrubs it. `?show=1` and `?showt=<seconds>` do the same
from a URL, and `&pause=1` with them lands on an exact frame for judging a shot.

Useful URL params beyond the above: `w`, `h` (explicit resolution, letterboxed), `t` (fixed
time), `still`, `warm`, `det`, `steps`, `npart`, `nphoton`, `selftest`.

`gridEnv` replaces the environment with a lat-long UV test grid (green horizon, magenta
poles, orange dot at the key light) — it makes it obvious which direction a reflection or
refraction is sampling.

---

## Instrumentation

`window.__probe()` returns JSON: per-pass GPU times (`timestamp-query`), fps, adapter info,
shader compile and validation errors, glass levels in mm, particle counts and bottle-stream
extent, puddle depth/wet-block/bound stats, and the clock's `step`, `drift` and `resyncs`.
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
variant. All of it is dev-only and absent from the release.

---

## Roadmap

Done: geometry, hybrid sim, dielectrics, caustics, bubbles, mousse, puddle, bottle, lighting.

Next:
1. **Optimisation pass** — still open. The occupancy skip is in and bought 0.9 ms on the
   worst shot, not the 8 predicted; see *What each lever actually buys* for why. `tier2` is
   25.5 ms against ~19. Untried: raising the `tp < 0.02` throughput cutoff, and keeping the
   timeline off the shots that fail.
2. Bloom.
3. Fluid inside the bottle (it is an empty shell today).
4. Camera and timeline.
5. Music — must be **human-composed**; the party bans prompt-based music.
6. The 8192-byte squeeze: template long names to one letter, Brotli, then a search over
   statement orderings scored by compressed size (INCENDIUM's packer, derived from Pakettic,
   is MIT). A ~324-byte dropper leaves ~7870 bytes of payload.

   Measured baseline — today's harness with comments and indentation stripped, Brotli q11:

   | | raw | brotli |
   |---|---|---|
   | WGSL | 34.2 KB | 8 820 |
   | JS | 29.6 KB | 8 726 |
   | **both** | **63.8 KB** | **17 438** |

   Stripping alone is a 3.7:1 ratio and lands ~2.2x over budget. The rest has to come from
   deleting the debug harness — most of that JS, and a good share of the WGSL, is panel,
   probe, selftest and nine isolation views — and from minification proper, where the
   identifiers being long and descriptive works in our favour, since renaming feeds the
   compressor as well as shrinking the source. INCENDIUM reached ~10:1 end-to-end on a
   comparable 38.9 KB (24 KB WGSL + 10 KB JS + 4.9 KB of note data in ~3770 bytes), and
   NuSan's *Drifting Shore* fit ~22.6 KB in 4096, so the ~5:1 that 8 KB asks for has room.

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

One source of truth: `dev/champagne.html`. The build strips the harness, inlines the values
the debug panel used to supply, minifies, and packs the result into `build/intro.html`, a
self-extracting page that inflates itself with `DecompressionStream`. It needs Python with
`brotli`, and Node for `terser`.

Dev-only code is bracketed with `//#D{` / `//#D}` in both the WGSL and the JS. Everything
else goes by rule, so the harness cannot quietly end up in the release:

- Lines mentioning `probe`, `fail(`, `setUI(`, `hasTS`, the readbacks or the query-set
  plumbing are dropped. A handful of lines mix harness and release work in one statement
  and are rewritten explicitly instead.
- `cfg.*` and `ui.*` are replaced with literals — `ui.*` read straight out of the panel's
  own `SPEC` table, so the release cannot drift from the defaults you tuned by hand. The
  build asserts that none survive.
- WGSL identifiers are renamed, except entry points and anything quoted in the JS.

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

The pre-pass is optional — the build runs without Node, 287 bytes heavier. Two notes for
anyone repeating this: wgslender's validator rejects our `atomicAdd` calls as `@must_use`
where Dawn accepts them, so `validate` reports errors on a shader that compiles and runs;
and all 17 entry points survive its tree-shaking, which is worth re-checking whenever a
compute pass is added.

[washi](https://github.com/datatrash/washi) was the other candidate and is not usable here:
no prebuilt releases, cargo required, and its own README recommends wgslender instead.

### Folding what the release never varies

29 of the 47 uniform slots are constants in the release: the debug toggles, `view`,
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
wgslender rejects a leading dot, fails, and the build falls back silently to an unshaken
shader. Literals keep their leading zero.

### The packer search

`build/pack.py` replaces the regex renamer. It tokenises the shader once into its 137
module-scope declarations and treats packing as a search over two kinds of move, both
semantics-preserving by construction:

- **order** — module-scope declarations may appear in any order in WGSL, so items shuffle
  freely; so do the four parts of the page (a module script is deferred, so it can sit
  ahead of the shader and canvas it reads);
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

It only saves when it beats the stored score.

**What limits it.** One evaluation is 21 ms: brotli 17.1 ms (81%), rendering the candidate
in Python 3.9 ms (19%). So it is brotli-bound, and the Python could at best buy back a
fifth. Across cores it reaches 730 evaluations/s against 48/s on one core — 15× on a
16-core, 32-thread Ryzen 9 9950X. It scales with physical cores and SMT adds nothing:
brotli q11's optimal parsing saturates a core on its own. Faster search means fewer or
smarter evaluations, not faster ones.

### Where it lands today (no music, first draft timeline)

| Stage | WGSL | JS |
|---|---|---|
| source | 51 136 | 43 520 |
| harness stripped | 47 351 | 24 259 |
| dev code removed | 47 351 | 20 924 |
| minified | 23 674 | 8 853 |

| Packed | bytes |
|---|---|
| payload, uncompressed | 32 452 |
| brotli q11 | 10 171 |
| dropper header | 371 |
| **`intro.cmd`, the deliverable** | **10 542** |
| `intro.html` (base64, test convenience only) | 15 484 |

**10 542 against 8192 — over by 2 350**, about 29%, before a byte of music.

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

`intro.cmd` is a batch line that hands itself to PowerShell, which reads its own file,
inflates everything past a fixed offset and opens the result. Because the dropper inflates,
the payload sits in the file as **raw bytes** — no base64, no string escaping, no encoding
overhead at all. The offset is written into the header and padded to a fixed width, so the
digit count cannot move what it points at.

Verified end to end: running `intro.cmd` writes a file byte-identical to the build's payload
and the extracted page renders with no errors. It inflates rather than serves, so it is a
deflate dropper; see above for why serving would be better. `intro.html` still comes out for quick
browser testing, but it carries base64 and reads about 30% too big; the deliverable is the
`.cmd`.

The remaining levers, largest first:

1. **WGSL local names.** Only globals are renamed today. Locals are most of the identifiers.
2. **Dead branches.** `view`, `gridEnv`, `noliq` and the feature toggles are uniforms the
   release never varies; a constant-folding pass would delete whole code paths.
3. **The packer.** INCENDIUM's search over statement orderings, scored by compressed size.
4. The occupancy skip, which buys 0.9 ms and costs bytes — a fair trade to reverse at the end.

---

## Credits / prior art

- **INCENDIUM** (Bercon + pestis, Revision 2025) — 4 kb WebGPU intro with a 3D fluid sim and
  compute-shader music. The packaging model and the byte budget come from it. MIT.
- **Roquefort** (Bercon) — 256³ WebGPU fluid. MIT.
- Shadertoy work by **wyatt** and **michael0884** informed the nearest-particle-as-SDF idea.
  Studied, not copied — Shadertoy defaults to CC BY-NC-SA.
