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
from mathutils import Vector

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


def speakers(scene):
    return [o for o in scene.objects if o.type == 'SPEAKER']


def _number(x):
    return int(x) if float(x).is_integer() else float(x)


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
                       "patternFocus": round(s.pattern_focus, 4), "flare": bool(s.flare)})
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
