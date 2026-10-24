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

Slender 5.2 mm stem, a solid glass knuckle where bowl meets stem (smooth-min), thin rounded
foot. The tower is 1+4+9 = 14 glasses by SDF domain folding, 0.51 m tall, 0.336 m wide.

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
sim        particles (one fixed 1/60 s step per frame)
build      puddle → puddleCoarse → puddleJFA → glassUpdate → waveUpdate ×3
           clearFine → clearCoarse → scatterFine → seedCoarse → jfaCoarse ×5 → resolveFine
photon     causticDecay → photons → causticBlur
render     camera raymarch + post
```

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

Three of those are worth knowing because they are **not** levers. Step count does nothing —
the march is bounce-limited, not step-limited, so rays are terminating on hits long before
the cap and lowering it only risks artifacts. Reflections are free. Photons are nearly free,
so the caustics cost almost nothing to keep.

The two that matter:

1. **The particle field costs 8 ms of render — a third of the frame — with ~460 particles
   alive.** `build` is unchanged at 1.84 with `parts=0`, so this is not the grid build: it is
   the per-step cost of sampling the narrow band inside `map()`, paid on every step of every
   ray whether or not a particle is anywhere near. That is the one real optimisation, and it
   is a correctness-free win: a coarse occupancy test that skips the trilerp where the band
   is empty changes no pixel. Worth finding out first whether the cost is the 320³ fine
   trilerp or the 32³ JFA lookup.
2. **`bounces` is ~1.1 ms each.** Real quality is traded here, and 10 was chosen to fix the
   checkerboard breakup deep in the tower, so this is the reserve rather than the first move.

Doing (1) alone brings `tier2` to roughly 18.5 ms, which clears the target without touching
the look.

**Measure with the window on screen.** The same tier2 shot read 36–40 ms with the browser pane
hidden — roughly 3× inflated, because a background page runs at ~2 fps and the GPU
downclocks between frames. An earlier 17.7 ms figure was taken at the pane's own 1100×880 and
was never comparable to the budget at all.

### WebGPU limits that must be requested

Several defaults were within a few percent of biting:

- `maxStorageBuffersPerShaderStage: 16` and `maxStorageBuffersInFragmentStage: 16` — we bind 14.
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

Useful URL params beyond the above: `w`, `h` (explicit resolution, letterboxed), `t` (fixed
time), `still`, `warm`, `steps`, `npart`, `selftest`.

`gridEnv` replaces the environment with a lat-long UV test grid (green horizon, magenta
poles, orange dot at the key light) — it makes it obvious which direction a reflection or
refraction is sampling.

---

## Instrumentation

`window.__probe()` returns JSON: per-pass GPU times (`timestamp-query`), fps, adapter info,
shader compile and validation errors, glass levels in mm, particle counts and bottle-stream
extent, and puddle depth/wet-block/bound stats. `?selftest=1` runs assertions and logs
PASS/FAIL.

The renderer **pauses on demand** and still redraws one frame when a slider moves, so
exploring costs nothing.

---

## Roadmap

Done: geometry, hybrid sim, dielectrics, caustics, bubbles, mousse, puddle, bottle, lighting.

Next:
1. **Optimisation pass** — skip the particle-field sample where the narrow band is empty.
   That is ~8 ms on the worst shot and costs nothing visually; see *What each lever actually
   buys*. `bounces` is the reserve after that.
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

## Credits / prior art

- **INCENDIUM** (Bercon + pestis, Revision 2025) — 4 kb WebGPU intro with a 3D fluid sim and
  compute-shader music. The packaging model and the byte budget come from it. MIT.
- **Roquefort** (Bercon) — 256³ WebGPU fluid. MIT.
- Shadertoy work by **wyatt** and **michael0884** informed the nearest-particle-as-SDF idea.
  Studied, not copied — Shadertoy defaults to CC BY-NC-SA.
