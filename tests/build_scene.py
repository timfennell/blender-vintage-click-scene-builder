"""Headless check of the scene builder. Run:
    Blender --background --factory-startup --python tests/build_scene.py [-- <scan.ply> ...]
For each scan: load it, rotate and scale it, add a start camera, a sky, two VC lights (one
with a gobo), a speaker and an ambience bed, save a .vcscene, unzip it and check scene.json
(positions round-trip through matrix_world; up and metresPerUnit right). Also saves once
without Splat Patch (the source-copy fallback). Exits 1 on any failure."""
import json
import math
import os
import struct
import sys
import tempfile
import wave
import zipfile

import bpy
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
GS_PATCH = os.path.expanduser("~/Documents/gs_patch")
if os.path.isdir(GS_PATCH):
    sys.path.insert(0, GS_PATCH)
    import gs_patch
    gs_patch.register()
import vc_scene_builder
vc_scene_builder.register()
from vc_scene_builder import bundle, ops, props

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SCANS = argv or ["/Users/timothyfennell/Downloads/Big Bee/scene.ply"]
D = tempfile.mkdtemp(prefix="vcs_test_") + "/"
FAILS = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}", flush=True)
    if not ok:
        FAILS.append(label)


def close(a, b, tol=1e-4):
    return (Vector(a) - Vector(b)).length <= tol * max(1.0, Vector(b).length)


def make_wav(path, hz):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / 22050)))
                               for i in range(22050)))


def make_hdr(path):
    img = bpy.data.images.new("sky_src", 64, 32, float_buffer=True)
    img.pixels = [0.5, 0.6, 0.9, 1.0] * (64 * 32)
    img.filepath_raw = path
    img.file_format = 'HDR'
    img.save()
    bpy.data.images.remove(img)


make_wav(D + "stream.wav", 440)
make_wav(D + "wind.wav", 220)
os.makedirs(D + "other", exist_ok=True)
make_wav(D + "other/wind.wav", 110)            # same name, different file
make_hdr(D + "forest.hdr")


def ply_count(data):
    head = data[:data.index(b"end_header")].decode()
    return int(next(l.split()[2] for l in head.splitlines() if l.startswith("element vertex")))


def build_and_check(scan_path, tag):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    ctx = bpy.context
    scene = ctx.scene
    scene.unit_settings.scale_length = 1.0
    scene.vc.scan = None
    bpy.ops.wm.ply_import(filepath=scan_path)
    scan = ctx.selected_objects[0]
    check(f"[{tag}] imported scan counts as splats", props.is_splat(scan))
    n_points = len(scan.data.points)
    # Rotate and scale: COLMAP's -Y up to Blender's Z up, a turn, and to real size.
    scan.rotation_euler = Euler((math.radians(-90), math.radians(15), math.radians(30)))
    scan.scale = (0.25, 0.25, 0.25)
    scan.location = (1.0, -2.0, 0.5)
    ctx.view_layer.update()
    ctx.view_layer.objects.active = scan
    check(f"[{tag}] scan defaults to the active splat object", props.scan_of(ctx) == scan and scene.vc.scan is None)
    vc = scene.vc
    vc.scene_name = "Test " + tag
    vc.kind = 'PLACE'
    vc.ev = "11"
    vc.house_lights = "dusk"

    cam_mw = Matrix.Translation((3, -4, 1.6)) @ Euler((math.radians(85), 0, math.radians(35))).to_matrix().to_4x4()
    cam = ops.place_start(ctx, cam_mw)
    cam.data.lens = 50
    check(f"[{tag}] the scan is pinned once things are added", scene.vc.scan == scan)
    cam2 = ops.place_start(ctx, cam_mw)
    check(f"[{tag}] Set Start moves the one VC Start camera", cam2 == cam and
          sum(1 for o in scene.objects if o.type == 'CAMERA') == 1)

    vc.sky_path = D + "forest.hdr"
    vc.sky_yaw = 90
    vc.sky_stops = -1
    nt = scene.world.node_tree
    env = nt.nodes.get("VC Sky")
    bg = next(n for n in nt.nodes if n.type == 'BACKGROUND')
    check(f"[{tag}] sky mirrored into the World", env is not None and env.image is not None and
          abs(bg.inputs["Strength"].default_value - 0.5) < 1e-6 and
          abs(nt.nodes["VC Sky Mapping"].inputs["Rotation"].default_value[2] - math.pi / 2) < 1e-6)

    key = ops.add_light(ctx, "Fresnel 2K", location=(2, 1, 2.5))
    key.rotation_euler = Euler((math.radians(50), 0, math.radians(120)))
    key.data.vc.spot = 0.8
    key.data.vc.dimmer_stops = -1
    key.data.vc.gel = "Rosmont 07 Pale Straw"
    key.data.vc.modifier = "Barn doors, a slash"
    gobo = ops.add_light(ctx, "Ellipsoidal 750", location=(-1.5, 2, 3))
    gobo.rotation_euler = Euler((math.radians(30), math.radians(10), math.radians(-140)))
    gobo.data.vc.modifier = "Gobo: window"
    gobo.data.vc.pattern_focus = 0.1
    gobo.data.vc.flare = False
    try:
        key.data.vc.modifier = "Gobo: bars"
        check(f"[{tag}] a gobo doesn't fit a Fresnel", False)
    except TypeError:
        check(f"[{tag}] a gobo doesn't fit a Fresnel", True)
    exp_angle = props.beam_angle(props.HEADS["Fresnel 2K"], 0.8)
    check(f"[{tag}] spot size previews the beam", abs(math.degrees(key.data.spot_size) - exp_angle) < 1e-3,
          f"{math.degrees(key.data.spot_size):.2f} deg")
    check(f"[{tag}] gel colours the preview", key.data.color[2] < key.data.color[0])
    soft = ops.add_light(ctx, "Fresnel 650", location=(0, -3, 2))
    soft.data.vc.modifier = "Flag off the top"
    soft.data.vc.head = "Softlight 2K"
    check(f"[{tag}] softlight is an area light", soft.data.type == 'AREA' and abs(soft.data.size - 0.62) < 1e-6
          and abs(soft.data.size_y - 0.46) < 1e-6, f"{soft.data.type} {soft.data.size:.2f}")
    soft.data.vc.head = "Ellipsoidal 750"
    check(f"[{tag}] changing head drops a modifier that no longer fits",
          soft.data.type == 'SPOT' and soft.data.vc.modifier == "Nothing" and
          abs(math.degrees(soft.data.spot_size) - 35) < 1e-3)
    bpy.data.objects.remove(soft)

    box = ops.add_bound(ctx, 'BOX', location=(0.5, 1.0, 1.2))
    box.rotation_euler = Euler((0, 0, math.radians(25)))
    box.scale = (4, 2.5, 1.5)                   # non-uniform
    box.empty_display_size = 1.5
    ball = ops.add_bound(ctx, 'SPHERE', location=(-3, 2, 1))
    ball.scale = (2, 2, 2)
    ball.empty_display_size = 0.75

    vc.fog = True
    vc.fog_visibility = 300
    vc.fog_colour = (0.9, 0.95, 1.0)
    vc.fog_falloff = 8
    vc.fog_base = 0.4
    mist = ops.add_fog_patch(ctx, 'BOX', location=(1.5, -0.5, 0.2))
    mist.rotation_euler = Euler((0, 0, math.radians(-20)))
    mist.scale = (3, 2, 0.3)                    # a flat slab over a pond
    mist.vc_fog.visibility = 4
    mist.vc_fog.colour = (0.8, 0.85, 0.9)
    mist.vc_fog.softness = 0.5
    zs = [v.co.z for v in mist.data.vertices]
    check(f"[{tag}] fog patch mesh is the unit box", abs(min(zs) + 1) < 1e-6 and abs(max(zs) - 1) < 1e-6)
    vnode = next(n for n in mist.active_material.node_tree.nodes if n.type == 'PRINCIPLED_VOLUME')
    check(f"[{tag}] fog patch previews its density and colour",
          abs(vnode.inputs["Density"].default_value - 3.912 / 4) < 1e-5 and
          abs(vnode.inputs["Color"].default_value[0] - 0.8) < 1e-6 and mist.display_type == 'WIRE')

    spk = ops.add_speaker(ctx, D + "stream.wav", location=(-2, -1, 0.3))
    spk.data.volume = 0.7
    spk.data.distance_reference = 3
    spk.data.distance_max = 25
    a = vc.ambience.add(); a.file = D + "wind.wav"; a.volume = 0.4
    a = vc.ambience.add(); a.file = D + "other/wind.wav"; a.volume = 0.2
    ctx.view_layer.update()

    out = D + f"test_{tag}.vcscene"
    j, problems = bundle.save(ctx, props.scan_of(ctx), out)
    check(f"[{tag}] nothing missing", not problems, str(problems))
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    want = {"scene.json", "scene.ply", "sky/forest.hdr", "sounds/stream.wav", "sounds/wind.wav", "sounds/wind_2.wav"}
    check(f"[{tag}] bundle contents", names == want, str(sorted(names)))
    check(f"[{tag}] scene.ply stored uncompressed", z.getinfo("scene.ply").compress_type == zipfile.ZIP_STORED)
    ply = z.read("scene.ply")
    check(f"[{tag}] scene.ply has every splat", ply_count(ply) == n_points, f"{ply_count(ply)} of {n_points}")
    s = json.loads(z.read("scene.json"))
    M = scan.matrix_world
    R = M.to_3x3()

    def to_world_dir(d):
        return (R @ Vector(d)).normalized()

    check(f"[{tag}] header", s["format"] == "vintage-click-scene" and s["version"] == 1 and
          s["splats"] == "scene.ply" and s["name"] == "Test " + tag)
    check(f"[{tag}] metresPerUnit", abs(s["metresPerUnit"] - 0.25) < 1e-6, str(s["metresPerUnit"]))
    check(f"[{tag}] up maps back to world +Z", close(to_world_dir(s["up"]), (0, 0, 1)) and
          abs(Vector(s["up"]).length - 1) < 1e-5, str(s["up"]))
    # For a COLMAP scan turned upright by -90 deg about X, PLY up is ~(0, -1, 0) before the extra turns.
    check(f"[{tag}] kind, EV, house lights", s["place"] is True and s["ev"] == 11 and s["houseLights"] == "dusk")
    st = s["start"]
    check(f"[{tag}] start position round-trips", close(M @ Vector(st["position"]), cam.matrix_world.translation))
    check(f"[{tag}] start forward round-trips",
          close(to_world_dir(st["forward"]), cam.matrix_world.to_3x3() @ Vector((0, 0, -1))))
    check(f"[{tag}] focalMM", abs(st["focalMM"] - 50) < 1e-6)
    check(f"[{tag}] sky", s["sky"] == {"file": "sky/forest.hdr", "yawDegrees": 90, "stops": -1}, str(s["sky"]))
    L = {l["head"]: l for l in s["lights"]}
    check(f"[{tag}] two lights", len(s["lights"]) == 2 and set(L) == {"Fresnel 2K", "Ellipsoidal 750"})
    for obj in (key, gobo):
        l = L[obj.data.vc.head]
        check(f"[{tag}] {obj.name} position round-trips", close(M @ Vector(l["position"]), obj.matrix_world.translation),
              f"{tuple(M @ Vector(l['position']))} vs {tuple(obj.matrix_world.translation)}")
        check(f"[{tag}] {obj.name} aim round-trips",
              close(to_world_dir(l["aim"]), obj.matrix_world.to_3x3() @ Vector((0, 0, -1))))
    k, g = L["Fresnel 2K"], L["Ellipsoidal 750"]
    check(f"[{tag}] key settings", k["spot"] == 0.8 and k["dimmerStops"] == -1 and k["gel"] == "Rosmont 07 Pale Straw"
          and k["modifier"] == "Barn doors, a slash" and k["flare"] is True, str(k))
    check(f"[{tag}] gobo settings", g["modifier"] == "Gobo: window" and abs(g["patternFocus"] - 0.1) < 1e-6
          and g["flare"] is False and g["gel"] == "No gel", str(g))
    bd = {b["shape"]: b for b in s["bounds"]}
    check(f"[{tag}] two bounds", len(s["bounds"]) == 2 and set(bd) == {"box", "sphere"})
    for obj, shape in ((box, "box"), (ball, "sphere")):
        m = Matrix([bd[shape]["matrix"][r * 4:r * 4 + 4] for r in range(4)])
        check(f"[{tag}] {shape} centre round-trips", close(M @ m.translation, obj.matrix_world.translation),
              f"{tuple(M @ m.translation)} vs {tuple(obj.matrix_world.translation)}")
        sz = obj.empty_display_size
        check(f"[{tag}] {shape} unit corner is the drawn corner",
              close(M @ (m @ Vector((1, 1, 1))), obj.matrix_world @ Vector((sz, sz, sz))))
    fg = s["fog"]
    check(f"[{tag}] ambient fog", fg["visibilityM"] == 300 and fg["heightFalloffM"] == 8 and
          close(fg["colour"], (0.9, 0.95, 1.0)), str(fg))
    check(f"[{tag}] fog base round-trips", close(M @ Vector(fg["base"]), (0, 0, 0.4)))
    fv = s["fogVolumes"]
    check(f"[{tag}] one fog patch", len(fv) == 1 and fv[0]["shape"] == "box" and fv[0]["visibilityM"] == 4
          and fv[0]["softness"] == 0.5 and close(fv[0]["colour"], (0.8, 0.85, 0.9)), str(fv))
    m = Matrix([fv[0]["matrix"][r * 4:r * 4 + 4] for r in range(4)])
    check(f"[{tag}] fog patch centre round-trips", close(M @ m.translation, mist.matrix_world.translation))
    check(f"[{tag}] fog patch unit corner is its mesh corner",
          close(M @ (m @ Vector((1, 1, 1))), mist.matrix_world @ Vector((1, 1, 1))))
    snd = s["sounds"]
    check(f"[{tag}] speaker", len(snd) == 1 and snd[0]["file"] == "sounds/stream.wav" and
          abs(snd[0]["volume"] - 0.7) < 1e-6 and snd[0]["fullWithinM"] == 3 and snd[0]["silentBeyondM"] == 25 and
          close(M @ Vector(snd[0]["position"]), spk.matrix_world.translation), str(snd))
    check(f"[{tag}] ambience", s["ambience"] == [{"file": "sounds/wind.wav", "volume": 0.4},
                                                  {"file": "sounds/wind_2.wav", "volume": 0.2}], str(s["ambience"]))
    check(f"[{tag}] packed sound is the right file", z.read("sounds/wind_2.wav") == open(D + "other/wind.wav", "rb").read())

    # Without Splat Patch: the scan's source .ply is copied in as it is.
    real = bundle.splat_patch
    bundle.splat_patch = lambda: None
    try:
        try:
            bundle.save(ctx, scan, D + "nosource.vcscene")
            check(f"[{tag}] no Splat Patch and no source refuses", False)
        except bundle.BundleError:
            check(f"[{tag}] no Splat Patch and no source refuses", True)
        vc.source_ply = scan_path
        bundle.save(ctx, scan, D + f"copy_{tag}.vcscene")
        check(f"[{tag}] fallback copies the source ply",
              zipfile.ZipFile(D + f"copy_{tag}.vcscene").read("scene.ply") == open(scan_path, "rb").read())
        vc.source_ply = ""
    finally:
        bundle.splat_patch = real
    # Through the operators, as the sidebar and File > Export run them.
    r = bpy.ops.vcs.add_light(head="Softlight 2K")
    added = ctx.view_layer.objects.active
    check(f"[{tag}] Add VC Light operator", r == {'FINISHED'} and added.data.vc.is_vc and added.data.type == 'AREA')
    r = bpy.ops.vcs.add_bound(shape='CYLINDER')
    cyl = ctx.view_layer.objects.active
    zs = [v.co.z for v in cyl.data.vertices]
    rs = [math.hypot(v.co.x, v.co.y) for v in cyl.data.vertices]
    check(f"[{tag}] Add Bound Cylinder is a unit cylinder on Z", r == {'FINISHED'} and cyl["vc_bound"] == 'CYLINDER'
          and abs(min(zs) + 1) < 1e-5 and abs(max(zs) - 1) < 1e-5 and abs(max(rs) - 1) < 1e-5)
    r = bpy.ops.vcs.save_scene(filepath=D + f"op_{tag}.vcscene")
    s2 = json.loads(zipfile.ZipFile(D + f"op_{tag}.vcscene").read("scene.json"))
    check(f"[{tag}] Save .vcscene operator", r == {'FINISHED'} and len(s2["lights"]) == 3 and
          [b["shape"] for b in s2["bounds"]] == ["box", "cylinder", "sphere"])
    bpy.data.objects.remove(added)
    bpy.data.objects.remove(cyl)
    r = bpy.ops.vcs.add_fog_patch(shape='SPHERE')
    ball_fog = ctx.view_layer.objects.active
    check(f"[{tag}] Add Fog Patch operator", r == {'FINISHED'} and ball_fog["vc_fog"] == 'SPHERE'
          and abs(max(v.co.length for v in ball_fog.data.vertices) - 1) < 1e-5)
    bpy.data.objects.remove(ball_fog)
    vc.fog = False
    s3 = bundle.describe(ctx, scan)[0]
    check(f"[{tag}] no fog key when ambient fog is off", "fog" not in s3)
    if tag == "0":
        print(json.dumps(s, indent=1)[:1500])


check("Splat Patch found", bundle.splat_patch() is not None)
for i, p in enumerate(SCANS):
    build_and_check(p, str(i))
print(f"\n{len(FAILS)} failures" + (": " + ", ".join(FAILS) if FAILS else "") + f"   (output in {D})")
sys.exit(1 if FAILS else 0)
