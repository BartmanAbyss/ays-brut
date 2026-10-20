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

RTX 4070, tower shot at 1100×880, everything on:

| Pass | ms |
|---|---|
| sim | 0.85 |
| build | 2.29 |
| photons + blur | 2.88 |
| render | 11.67 |
| **total** | **17.7** |

**Budget is 16.6 ms for 60 Hz, so this is currently over.** Levers, in order: photon count,
the `bounces` default (10), half-resolution refracted paths, and the 320³ build.

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
1. **Optimisation pass** — get back under 16.6 ms.
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
