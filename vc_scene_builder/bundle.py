"""Write a .vcscene: a zip of scene.json, scene.ply, the sky and the sounds.

Every position and direction goes into the scan's own (PLY) space through
scan.matrix_world.inverted(), which is the space Splat Patch writes the PLY in.
"""

import importlib
import os
import shutil
import sys
import tempfile
import zipfile

import bpy
from mathutils import Matrix, Vector

from .props import KIT, START_NAME, metres_per_unit

FORMAT = "vintage-click-scene"
VERSION = 1


class BundleError(Exception):
    pass


def splat_patch():
    """Splat Patch's package (for ply_io and lod), if it is enabled; else None."""
    names = [k for k in bpy.context.preferences.addons.keys() if k.split(".")[-1] == "gs_patch"]
    if "gs_patch" in sys.modules:
        names.append("gs_patch")
    for name in names:
        try:
            pkg = importlib.import_module(name)
            importlib.import_module(name + ".ply_io")
            importlib.import_module(name + ".lod")
            return pkg
        except ImportError:
            continue
    return None


def _vec(v, nd=6):
    return [round(float(x), nd) + 0.0 for x in v]       # + 0.0: no "-0.0"


class Space:
    """World (Blender) to scan (PLY) coordinates."""

    def __init__(self, scan):
        self.inv = scan.matrix_world.inverted()
        self.rot = self.inv.to_3x3()

    def point(self, p):
        return self.inv @ Vector(p)

    def direction(self, d):
        v = self.rot @ Vector(d)
        return v.normalized() if v.length > 0 else v


def vc_lights(scene):
    return [o for o in scene.objects if o.type == 'LIGHT' and o.data.vc.is_vc]


BOUND_SHAPES = {'BOX': "box", 'SPHERE': "sphere", 'CYLINDER': "cylinder"}


def bounds(scene):
    """Objects tagged vc_bound = 'BOX' | 'SPHERE' | 'CYLINDER': the camera stays in their union."""
    return [o for o in scene.objects if o.get("vc_bound") in BOUND_SHAPES]


def bound_unit(obj):
    """How big the object's unit primitive is in its own space: an empty draws at its display
    size; the cylinder mesh is built at unit size."""
    return obj.empty_display_size if obj.type == 'EMPTY' else 1.0


FOG_SHAPES = BOUND_SHAPES


def fog_patches(scene):
    """Mesh primitives tagged vc_fog = 'BOX' | 'SPHERE' | 'CYLINDER', built at unit size."""
    return [o for o in scene.objects if o.get("vc_fog") in FOG_SHAPES]


def speakers(scene):
    return [o for o in scene.objects if o.type == 'SPEAKER']


def _number(x):
    return int(x) if float(x).is_integer() else float(x)


def _variation(amount, size_m, detail, seed):
    return {"amount": round(amount, 4), "sizeM": round(size_m, 4), "detail": int(detail), "seed": int(seed)}


class _Names:
    """Unique archive names within a folder (two 'wind.wav's become wind.wav, wind_2.wav)."""

    def __init__(self):
        self.by_source, self.used = {}, set()

    def name(self, folder, src):
        key = os.path.realpath(src)
        if key in self.by_source:
            return self.by_source[key]
        stem, ext = os.path.splitext(os.path.basename(src))
        cand, i = f"{folder}/{stem}{ext}", 2
        while cand in self.used:
            cand, i = f"{folder}/{stem}_{i}{ext}", i + 1
        self.used.add(cand)
        self.by_source[key] = cand
        return cand


def describe(context, scan):
    """scene.json as a dict, and the files to pack: [(archive name, source path)].
    Also returns problems (missing files) as a list of strings."""
    scene = context.scene
    vc = scene.vc
    sp = Space(scan)
    names = _Names()
    files, problems = [], []
    scale = scene.unit_settings.scale_length

    def add_file(folder, path, what):
        src = bpy.path.abspath(path) if path else ""
        if not src or not os.path.isfile(src):
            problems.append(f"{what}: file not found ({path or 'none set'})")
            return None
        arc = names.name(folder, src)
        if (arc, src) not in files:
            files.append((arc, src))
        return arc

    up = sp.direction((0, 0, 1))
    j = {"format": FORMAT, "version": VERSION,
         "name": vc.scene_name or scene.name,
         "splats": "scene.ply",
         "metresPerUnit": round(metres_per_unit(scene, scan), 9),
         "place": vc.kind == 'PLACE',
         "ev": _number(float(vc.ev)),
         "up": _vec(up)}

    cam = scene.objects.get(START_NAME)
    if cam is not None and cam.type == 'CAMERA':
        mw = cam.matrix_world
        fwd = mw.to_3x3() @ Vector((0, 0, -1))
        lens = cam.data.lens * 36.0 / cam.data.sensor_width     # as on 35 mm film
        j["start"] = {"position": _vec(sp.point(mw.translation)), "forward": _vec(sp.direction(fwd)),
                      "focalMM": round(lens, 3)}

    if vc.sky_path:
        arc = add_file("sky", vc.sky_path, "Sky")
        if arc:
            j["sky"] = {"file": arc, "yawDegrees": round(vc.sky_yaw, 4), "stops": round(vc.sky_stops, 4)}

    j["houseLights"] = vc.house_lights

    lights = []
    for o in sorted(vc_lights(scene), key=lambda o: o.name):
        s = o.data.vc
        mw = o.matrix_world
        aim = mw.to_3x3() @ Vector((0, 0, -1))
        lights.append({"head": s.head, "position": _vec(sp.point(mw.translation)),
                       "aim": _vec(sp.direction(aim)), "spot": round(s.spot, 4),
                       "dimmerStops": round(s.dimmer_stops, 4), "gel": s.gel, "modifier": s.modifier,
                       "patternFocus": round(s.pattern_focus, 4), "flare": bool(s.flare),
                       "fogScatter": round(s.fog_scatter, 4)})
    j["lights"] = lights

    sounds = []
    for o in sorted(speakers(scene), key=lambda o: o.name):
        snd = o.data.sound
        if snd is None:
            problems.append(f"Speaker {o.name}: no sound file")
            continue
        arc = add_file("sounds", snd.filepath, f"Speaker {o.name}")
        if not arc:
            continue
        sounds.append({"file": arc, "position": _vec(sp.point(o.matrix_world.translation)),
                       "volume": round(o.data.volume, 4),
                       "fullWithinM": round(o.data.distance_reference * scale, 4),
                       "silentBeyondM": round(o.data.distance_max * scale, 4)})
    j["sounds"] = sounds

    amb = []
    for i, a in enumerate(vc.ambience):
        arc = add_file("sounds", a.file, f"Ambience {i + 1}")
        if arc:
            amb.append({"file": arc, "volume": round(a.volume, 4)})
    j["ambience"] = amb

    # The unit primitive (box |x|,|y|,|z| <= 1; sphere r <= 1; cylinder x²+y² <= 1, |z| <= 1)
    # into PLY space, row-major.
    out = []
    for o in sorted(bounds(scene), key=lambda o: o.name):
        m = sp.inv @ o.matrix_world @ Matrix.Scale(bound_unit(o), 4)
        out.append({"shape": BOUND_SHAPES[o["vc_bound"]],
                    "matrix": [round(m[r][c], 7) + 0.0 for r in range(4) for c in range(4)]})
    j["bounds"] = out

    vc = scene.vc
    if vc.fog:
        j["fog"] = {"visibilityM": round(vc.fog_visibility, 4), "colour": _vec(vc.fog_colour, 4),
                    "heightFalloffM": round(vc.fog_falloff, 4),
                    "base": _vec(sp.point((0, 0, vc.fog_base))),
                    "anisotropy": round(vc.fog_anisotropy, 4),
                    "variation": _variation(vc.fog_variation, vc.fog_variation_size,
                                            vc.fog_variation_detail, vc.fog_variation_seed)}
    vols = []
    for o in sorted(fog_patches(scene), key=lambda o: o.name):
        m = sp.inv @ o.matrix_world
        f = o.vc_fog
        vols.append({"shape": FOG_SHAPES[o["vc_fog"]],
                     "matrix": [round(m[r][c], 7) + 0.0 for r in range(4) for c in range(4)],
                     "visibilityM": round(f.visibility, 4), "colour": _vec(f.colour, 4),
                     "softness": round(f.softness, 4), "heightFalloffM": round(f.height_falloff, 4),
                     "anisotropy": round(f.anisotropy, 4),
                     "variation": _variation(f.variation, f.variation_size, f.variation_detail,
                                             f.variation_seed)})
    j["fogVolumes"] = vols
    return j, files, problems


def write_ply(context, scan, path):
    """scene.ply: Splat Patch's writer when it is enabled (erased splats left out, a work
    area synced first), else a copy of the scan's source .ply. Returns how it was made."""
    gsp = splat_patch()
    if gsp is not None:
        gsp.lod.sync(scan)
        gsp.ply_io.write_pointcloud_ply(path, gsp.lod.full_data(scan))
        return "Splat Patch"
    src = bpy.path.abspath(context.scene.vc.source_ply)
    if not src or not os.path.isfile(src):
        raise BundleError("Splat Patch isn't enabled to write the splats, and no Source PLY is set")
    shutil.copyfile(src, path)
    return "source copy"


def save(context, scan, filepath):
    """Write the bundle. Returns (scene.json dict, problems). Raises BundleError."""
    import json
    if scan is None:
        raise BundleError("No scan: choose the splat object in Scene > Scan")
    j, files, problems = describe(context, scan)
    tmpdir = tempfile.mkdtemp(prefix="vcscene_")
    try:
        ply = os.path.join(tmpdir, "scene.ply")
        write_ply(context, scan, ply)
        part = filepath + ".part"
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("scene.json", json.dumps(j, indent=2))
            z.write(ply, "scene.ply", compress_type=zipfile.ZIP_STORED)
            for arc, src in files:
                z.write(src, arc, compress_type=zipfile.ZIP_STORED if arc.startswith("sounds/")
                        else zipfile.ZIP_DEFLATED)
        os.replace(part, filepath)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return j, problems
