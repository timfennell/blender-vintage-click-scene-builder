"""Open a .vcscene in Blender: unpack it and rebuild its scene (scan, start, sky, lights,
sounds, bounds, fog) so it can be edited and saved again.

Files saved by this add-on carry a "blender" block (the scan's transform) and object
names, so they come back exactly. Others are stood upright from `up` and scaled from
`metresPerUnit`; which way the scan faces round the up axis is then arbitrary, as it is
to the game.
"""

import hashlib
import json
import os
import sys
import zipfile
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

from . import fog, ops
from .props import EV_ITEMS, GELS, HEADS, KIT, START_NAME, modifiers_for


class OpenError(Exception):
    pass


def cache_root():
    """A lasting home for unpacked bundles (a saved .blend refers to the files in it)."""
    try:
        return bpy.utils.extension_path_user(__package__, path="opened", create=True)
    except (ValueError, AttributeError):
        if sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Caches")
        elif os.name == "nt":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        root = os.path.join(base, "Vintage Click Scene Builder", "opened")
        os.makedirs(root, exist_ok=True)
        return root


def unpack(path):
    """Unpack to <cache>/<name>-<hash of path, size, mtime>/, reusing an earlier unpacking."""
    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:12]
    stem = bpy.path.clean_name(os.path.splitext(os.path.basename(path))[0])
    dest = os.path.join(cache_root(), f"{stem}-{key}")
    done = os.path.join(dest, ".unpacked")
    if not os.path.exists(done):
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                target = os.path.realpath(os.path.join(dest, info.filename))
                if not target.startswith(os.path.realpath(dest) + os.sep):
                    raise OpenError(f"Refusing a file outside the bundle: {info.filename}")
            z.extractall(dest)
        open(done, "w").close()
    return dest


def _matrix(flat):
    return Matrix([flat[r * 4:r * 4 + 4] for r in range(4)])


def _scan_matrix(j):
    b = j.get("blender") or {}
    if "scanMatrixWorld" in b:
        return _matrix(b["scanMatrixWorld"])
    # Stand it up: PLY `up` onto Blender +Z, and scale to metres.
    up = Vector(j.get("up", (0, -1, 0))).normalized()
    rot = up.rotation_difference(Vector((0, 0, 1))).to_matrix().to_4x4()
    return rot @ Matrix.Scale(float(j.get("metresPerUnit", 1.0)), 4)


def _ev_item(ev):
    best = min(EV_ITEMS, key=lambda it: abs(float(it[0]) - float(ev)))
    return best[0]


def _known(name, table, fallback, what, notes):
    if name in table:
        return name
    notes.append(f"Unknown {what} {name!r}: using {fallback!r}")
    return fallback


def _point_at(obj, world_dir):
    obj.rotation_euler = Vector(world_dir).to_track_quat('-Z', 'Y').to_euler()


def _link_only(obj, scene):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    scene.collection.objects.link(obj)


def open_bundle(context, path):
    """Rebuild a .vcscene in a new Blender scene; returns (scene, notes)."""
    if not os.path.isfile(path):
        raise OpenError(f"No such file: {path}")
    root = unpack(path)
    jpath = os.path.join(root, "scene.json")
    if not os.path.isfile(jpath):
        raise OpenError("Not a Vintage Click scene: no scene.json inside")
    j = json.load(open(jpath))
    if j.get("format") != "vintage-click-scene":
        raise OpenError("Not a Vintage Click scene (scene.json has another format)")
    notes = []
    if int(j.get("version", 1)) > 1:
        notes.append(f"Saved by a newer builder (format version {j['version']}): some settings may be left out")

    def file_in(arc):
        p = os.path.join(root, arc) if arc else ""
        if p and not os.path.isfile(p):
            notes.append(f"Missing from the bundle: {arc}")
        return p

    name = j.get("name") or os.path.splitext(os.path.basename(path))[0]
    scene = bpy.data.scenes.new(name)
    b = j.get("blender") or {}
    scene.unit_settings.scale_length = float(b.get("unitScale", 1.0))
    ctx = SimpleNamespace(scene=scene, collection=scene.collection, view_layer=scene.view_layers[0],
                          active_object=None)

    # The scan.
    ply = file_in(j.get("splats", "scene.ply"))
    before = set(bpy.data.objects)
    bpy.ops.wm.ply_import(filepath=ply)
    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        raise OpenError("The scan (scene.ply) could not be read")
    scan = new[0]
    _link_only(scan, scene)
    scan.name = b.get("scanName", name + " scan")
    M = _scan_matrix(j)
    scan.matrix_world = M
    R = M.to_3x3()

    def pos(p):
        return M @ Vector(p)

    def direction(d):
        return (R @ Vector(d)).normalized()

    vc = scene.vc
    vc.scan = scan
    vc.source_ply = ply
    vc.opened_from = root
    vc.scene_name = name
    vc.kind = 'PLACE' if j.get("place", True) else 'OBJECT'
    if "ev" in j:
        vc.ev = _ev_item(j["ev"])
    houses = [h["name"] for h in KIT["houseLevels"]]
    if j.get("houseLights"):
        vc.house_lights = _known(j["houseLights"], houses, houses[0], "house lights", notes)

    st = j.get("start")
    if st:
        cam = ops.place_start(ctx, Matrix.Identity(4))
        cam.location = pos(st["position"])
        _point_at(cam, direction(st["forward"]))
        cam.data.sensor_width = 36.0
        cam.data.lens = float(st.get("focalMM", 35))
        scene.camera = cam

    sky = j.get("sky")
    if sky:
        vc.sky_yaw = float(sky.get("yawDegrees", 0))
        vc.sky_stops = float(sky.get("stops", 0))
        vc.sky_path = file_in(sky.get("file"))       # last: it builds the World nodes

    for l in j.get("lights", []):
        head = _known(l.get("head"), HEADS, KIT["heads"][0]["name"], "head", notes)
        obj = ops.add_light(ctx, head, location=pos(l["position"]))
        if l.get("name"):
            obj.name = obj.data.name = l["name"]
        _point_at(obj, direction(l["aim"]))
        s = obj.data.vc
        s.spot = float(l.get("spot", 0.5))
        s.dimmer_stops = float(l.get("dimmerStops", 0))
        s.gel = _known(l.get("gel", "No gel"), GELS, KIT["gels"][0]["name"], "gel", notes)
        fits = modifiers_for(HEADS[head]["kind"])
        mod = l.get("modifier", "Nothing")
        if mod not in fits:
            notes.append(f"{obj.name}: modifier {mod!r} doesn't fit a {head}; left off")
            mod = "Nothing"
        s.modifier = mod
        s.pattern_focus = float(l.get("patternFocus", 0.25))
        s.flare = bool(l.get("flare", True))
        s.fog_scatter = float(l.get("fogScatter", 1.0))

    scale = scene.unit_settings.scale_length
    for snd in j.get("sounds", []):
        obj = ops.add_speaker(ctx, file_in(snd.get("file")), location=pos(snd["position"]))
        if snd.get("name"):
            obj.name = snd["name"]
        obj.data.volume = float(snd.get("volume", 1))
        obj.data.distance_reference = float(snd.get("fullWithinM", 1)) / scale
        obj.data.distance_max = float(snd.get("silentBeyondM", 40)) / scale

    for a in j.get("ambience", []):
        item = vc.ambience.add()
        item.file = file_in(a.get("file"))
        item.volume = float(a.get("volume", 0.5))

    shapes = {"box": 'BOX', "sphere": 'SPHERE', "cylinder": 'CYLINDER'}
    for bd in j.get("bounds", []):
        shape = shapes.get(bd.get("shape"))
        if shape is None:
            notes.append(f"Unknown bound shape {bd.get('shape')!r}: left out")
            continue
        obj = ops.add_bound(ctx, shape)
        if bd.get("name"):
            obj.name = bd["name"]
        if obj.type == 'EMPTY':
            obj.empty_display_size = 1.0
        obj.matrix_world = M @ _matrix(bd["matrix"])

    fg = j.get("fog")
    if fg:
        vc.fog_visibility = float(fg.get("visibilityM", 300))
        vc.fog_colour = fg.get("colour", (1, 1, 1))
        vc.fog_falloff = float(fg.get("heightFalloffM", 0))
        vc.fog_base = pos(fg["base"]).z if "base" in fg else 0.0
        vc.fog_anisotropy = float(fg.get("anisotropy", 0.6))
        v = fg.get("variation") or {}
        vc.fog_variation = float(v.get("amount", 0))
        vc.fog_variation_size = float(v.get("sizeM", 20))
        vc.fog_variation_detail = int(v.get("detail", 3))
        vc.fog_variation_seed = int(v.get("seed", 0))
        vc.fog = True                                   # last: it builds the preview

    for fv in j.get("fogVolumes", []):
        shape = shapes.get(fv.get("shape"))
        if shape is None:
            notes.append(f"Unknown fog patch shape {fv.get('shape')!r}: left out")
            continue
        obj = ops.add_fog_patch(ctx, shape)
        if fv.get("name"):
            obj.name = fv["name"]
        obj.matrix_world = M @ _matrix(fv["matrix"])
        f = obj.vc_fog
        f.colour = fv.get("colour", (1, 1, 1))
        f.softness = float(fv.get("softness", 0.4))
        f.height_falloff = float(fv.get("heightFalloffM", 0))
        f.anisotropy = float(fv.get("anisotropy", 0.6))
        v = fv.get("variation") or {}
        f.variation = float(v.get("amount", 0))
        f.variation_size = float(v.get("sizeM", 1))
        f.variation_detail = int(v.get("detail", 3))
        f.variation_seed = int(v.get("seed", 0))
        scene.view_layers[0].update()
        f.visibility = float(fv.get("visibilityM", 5))   # last: rebuilds with the final transform

    scene.view_layers[0].update()
    fog.update_ambient(scene)
    return scene, notes
