# comparade26 — champagne tower

A realtime 3D fluid simulation of champagne filling a three-tier champagne tower, rendered
entirely by SDF raymarching. Target: an **8192-byte PC intro** for **ComParade 2026**
(Emmering/Munich, 6–8 Nov 2026), packaged the INCENDIUM way — WebGPU + a tiny PowerShell
dropper — not a native exe.

**Current state (25 Oct 2026):** the renderer, simulation, first-draft timeline and the
click-to-start screen work, and `build/intro.cmd` is **8 083 bytes, 109 under the 8 192
budget**. Missing: the song and its player (to be composed by hand), any text, and tier2
is still ~3 ms over the frame budget in its heaviest state. See *Roadmap*.

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
- Reflections trace a real ray only off the bulk champagne surface (`rtrace` 1), where
  near-grazing liquid would otherwise mirror the sky as an opaque disc. Glass and drops use
  the environment lookup (*The traced reflection*).

### Pass graph

```
sim        N steps per frame, N from the clock — everything that advances state:
           simParticles → puddleUpdate (its first 14 threads: the glass volumes) → waveUpdate ×3
build      once per frame — a rendering structure, needs only the final state:
           puddleCoarse (tallest film per block)
           clearFine (+ coarse clear) → scatterFine (+ far-field seeds) → jfaCoarse ×5
           → resolveFine (+ packs the far field for the render)
photon     causticDecay → photons → causticBlur
render     camera raymarch + post (one full-screen triangle)
```

Eleven compute entry points. Each dispatch passes its small index (sub-step, flood pass) as
the height of its grid, `num_workgroups.y - 1`, so no per-dispatch uniforms exist.

The split matters: the puddle, glass volumes and waves used to live in `build` and so
advanced once per *frame* while the particles advanced on the clock. See *Timing*.

### Grids

| Field | Size | Cell |
|---|---|---|
| Particle narrow band | 320³ | 1.94 mm |
| Coarse nearest-particle (JFA) | 32³ | 19.4 mm |
| Caustic map | 768², ±0.55 m | 1.43 mm |
| Table puddle | 384², ±0.55 m | 2.86 mm |
| Puddle blocks (tallest film, for the bound) | 48² | 22.9 mm |
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
  into 6 bindings (`parts`, `fine`, `fineF`, `atom`, `vecs`, `flts`) at fixed offsets;
  the dev build adds the profiler's counter bank as a 7th.
- **Workgroup size:** the default caps it at 256. 320³/256 would be 128 000 workgroups,
  over the 65 535 per-dimension cap, so `clearFine` and `resolveFine` handle two cells per
  thread.
- **Binding size:** 320³ × 4 B = 125 MiB per buffer, just under the 128 MiB default.

The dev harness requests `timestamp-query` when the adapter has it, for the per-pass times.

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

Done: geometry, hybrid sim, dielectrics, caustics, bubbles, mousse, puddle, bottle,
lighting, a first-draft timeline, the build and packer, the dropper, the click-to-start
screen with fullscreen and the audio clock. `intro.cmd` is 8 083 bytes.

Next:
1. **Music** — must be **human-composed**; the party bans prompt-based music. It goes in
   through `song(L, R, sr)`, and its player has to fit in what is left: 109 bytes today.
   How big it is decides whether features are cut (*Feature cuts, measured*).
2. **Text**, if any (credits, title), from the same budget.
3. **tier2** — ~22 ms against ~19 in its heaviest state (*Where it stands*). Options: cut
   there, don't hold on it while the spill is densest, or take `bounces` down on that shot.
4. **Render size** — the release renders at the screen's size. At the compo's 1920×1080
   that is the budget; on a larger monitor it is proportionally slower.
5. Timeline polish against the finished music.
6. Late, when every byte counts: design-constant rounding (~-40 to -90), Roadroller
   (-217, *Minifying* in CLAUDE.md), a final packer search.

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

One source of truth: `dev/champagne.html`. The build strips the harness, inlines the values
the debug panel used to supply, minifies, packs, and writes:

| file | what |
|---|---|
| `build/intro.cmd` | **the deliverable**: the dropper header plus the brotli payload |
| `build/intro.html` | a local test copy that inflates itself (base64 + deflate), ~50% bigger - not the entry |
| `build/min.wgsl`, `build/min.js` | what ships, as packed |
| `build/min.pretty.wgsl`, `build/min.pretty.js` | the same, re-indented to read |

It needs **Python 3 with `brotli`** (`pip install brotli`) and **Node.js 16+** on PATH.
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

**`intro.cmd` is 8 083 bytes (25 Oct 2026), 109 under 8 192**: the breakdown below
(7 967), plus the start screen and music hookup (+116). The song, its player and any text
still have to fit in those 109 bytes, or features get cut.

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

#### Feature cuts, measured

Each measured as the real edit - shader code, call sites, kernels and dispatches removed -
against the packer's default state, before the core pass above (the puddle's share is
~180 smaller now that its flood is gone). Bundles add up almost linearly.

| Option | saves | what it does to the look |
|---|---|---|
| puddle | 707 | 1.3% of pixels from above, <0.5% elsewhere: a few glints by the tower base |
| photon lighting -> analytic spot | 589 | the lit disc stays; the tower's shadow and the caustic glints go |
| waves + foam | 447 | every champagne surface becomes a flat mirror |
| bottle removed | 355 | the stream pours out of thin air |
| bokeh lights | 176 | the light discs behind the tower and their reflections go |
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

#### The size map (compressed bytes, shader side)

Marginal cost of removing each item, or each feature as a group (call sites left in, so
slight underestimates):

| feature | ~bytes | | function | ~bytes |
|---|---|---|---|---|
| puddle (sim, field, coarse grid, flood) | 620 | | `simParticles` | 750 |
| bottle geometry | 430 | | `fs` | 430 |
| caustics (photon pass, map) | 410+ | | `photons` | 270 |
| spray far field (seed, flood, pack) | 330 | | `scatterFine` | 240 |
| waves + foam | 320 | | `waveUpdate` | 220 |
| bokeh | 180 | | `sdCoupe` | 220 |
| reflection trace | 100 | | `liquidDist` | 180 |
| glass overflow | 100 | | `env` | 130 |
| bubbles | 90 | | | |

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

`intro.cmd` is one batch line that hands itself to PowerShell (310 bytes). PowerShell
reads its own file, starts an `HttpListener` on http://localhost:8044/, opens that URL in
the default browser and answers the one request with everything past a fixed offset, sent
as `text/html` with `Content-Encoding: br`. The payload sits in the file as **raw brotli
bytes** — no base64, no escaping. The offset is written into the header; the build finds
the value consistent with its own digit count, so the number cannot move what it points
at. Every golfing choice is commented in `build.py`.

Verified end to end: Chrome, Edge and Firefox decode it over plain http://localhost and
render with a clean console (*Browsers*).

One lever left on the table: the occupancy skip buys 0.9 ms and costs bytes — a fair trade
to reverse at the end if bytes are short.

---

## Credits / prior art

- **INCENDIUM** (Bercon + pestis, Revision 2025) — 4 kb WebGPU intro with a 3D fluid sim and
  compute-shader music. The packaging model and the byte budget come from it. MIT.
- **Roquefort** (Bercon) — 256³ WebGPU fluid. MIT.
- Shadertoy work by **wyatt** and **michael0884** informed the nearest-particle-as-SDF idea.
  Studied, not copied — Shadertoy defaults to CC BY-NC-SA.
