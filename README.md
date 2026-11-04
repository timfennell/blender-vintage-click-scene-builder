# Vintage Click Scene Builder

A Blender 5.3 extension that composes a Vintage Click scene around a Gaussian splat scan and
saves it as one self-contained `.vcscene` file the game opens.

## The sidebar (N panel › Vintage Click)

- **Scene**: the scan (blank = the active splat object, or the scene's only one; it is pinned
  the first time you add a start, light or sound), the metres per PLY unit (the scan's world
  scale × the scene's unit scale; scale the scan until the Measure tool reads true), place or
  object, and the light the scan was captured in (EV). **Open…** (also File › Import)
  brings a `.vcscene` back into a new scene to edit; **Save .vcscene…** (also File › Export)
  writes it. An opened bundle is unpacked to a lasting cache folder (a saved .blend refers to
  it) and any other files in it, such as a licence, are saved again with it. Bundles from
  this add-on reopen exactly; others are stood up from `up` and scaled from `metresPerUnit`.
- **Start**: *Set Start From View* creates or moves the camera **VC Start** to the viewport
  view. Its lens (on a 36 mm-wide sensor) is the start focal length. Look through it as any
  camera.
- **Sky**: an `.hdr`/`.exr`, a yaw and a brightness in stops, mirrored into the World so the
  viewport matches.
- **House Lights**: the game's ambient levels (day … dark).
- **Lights**: *Add VC Light* adds a head from the kit at the 3D cursor (a spot light; an area
  light for the softlight). Aim it as any light (it shines down its −Z). Its head,
  spot/flood, dimmer, gel, modifier (only those that fit the head: gobos for the ellipsoidal,
  doors, flags and cookies for the others), pattern focus and flare are saved by name; the
  Blender light previews the beam angle, tungsten × gel colour and the energy.
- **Fog**: ambient fog through the whole scene (visibility in metres, colour, a height
  fall-off that halves it about every so many metres above a base height, full below it).
  *Add Fog Patch* (box, sphere, cylinder) adds a unit mesh: a flattened box over a pond
  makes mist. Each patch has visibility, colour, edge softness and its own height fall-off
  (from its lowest point). Both can vary in 3D (*Variation*: amount, size in metres,
  detail, seed) and have an *Anisotropy* (forward scattering: beams glow as you look into
  them). VC lights shine through the fog and objects cast shadows into it; each light's
  *Beam in Fog* sets how strongly. Blender previews all this with volume materials (the
  ambient fog in a box round the scan) and turns on EEVEE's volumetric shadows; Cycles
  shows it too. Light modifiers (doors, cookies, gobos) aren't previewed in Blender yet.
- **Bounds**: *Add Bound Box / Sphere / Cylinder* add a movement bound (an empty drawn as a
  cube or sphere; a wireframe unit cylinder along its local Z). Move, rotate and scale them
  freely, unevenly too. The camera may go anywhere inside their union; no bounds, no limit.
- **Sounds**: *Add Sound Emitter* adds a Speaker (looping in the game) with volume,
  *Full Within* and *Silent Beyond* distances. **Ambience** holds beds that play everywhere.

Splat Patch (gs_patch) writes `scene.ply` when it is enabled (erased splats left out, a work
area synced first). Without it, set **Source PLY** and the file is copied in as it is.

## The `.vcscene` file

A zip: `scene.json`, `scene.ply` (stored), `sky/…`, `sounds/…`. All positions and
directions are in the PLY's own coordinates (`scan.matrix_world.inverted()`); `up` is
Blender's +Z in those coordinates. Distances for sounds are in metres. Each bound is
`{"shape": "box"|"sphere"|"cylinder", "matrix": [16, row-major]}`, mapping the unit
primitive (box |x|,|y|,|z| ≤ 1; sphere r ≤ 1; cylinder x²+y² ≤ 1, |z| ≤ 1) into PLY space. `fog.base` is world (0, 0, base height) in PLY space; `fogVolumes` use the
same unit shapes and matrices as bounds. See the format
section of the plan for every key.

## kit.json

The heads, gels, modifiers, house levels, scene-light choices and the tungsten colour,
exported by the game: `VintageClick --export-kit kit.json`. Re-export it whenever the
game's kit changes; the add-on stores everything by name.

## Example

`examples/timberjack_fog.py` builds *Timberjack in the Mist*: a forest clearing at dusk
with haze, ground mist, three lamps (a branch cookie, a leaf gobo, a cab work light), a
bound round the clearing, wind in the trees and the machine idling (synthesized
placeholder loops from `examples/make_sounds.py`).

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python examples/timberjack_fog.py -- SCAN.ply OUT_DIR
```

## Test

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python tests/build_scene.py -- "/path/to/scene.ply"
```

It loads Splat Patch from `~/Documents/gs_patch`, builds a full scene around each scan,
saves it, unzips it and checks `scene.json` (positions round-trip through `matrix_world`,
`up`, `metresPerUnit`, names, packed files), plus the source-copy fallback.

## Install

```bash
/Applications/Blender.app/Contents/MacOS/Blender --command extension build --source-dir vc_scene_builder
```

then Edit › Preferences › Get Extensions › Install from Disk.

License: GPL-3.0-or-later.
