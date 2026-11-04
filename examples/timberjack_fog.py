"""Example: the Timberjack harvester in a misty forest clearing at dusk, with lamps shining
through the fog. Run:
    Blender --background --factory-startup --python examples/timberjack_fog.py -- SCAN.ply OUT_DIR
Writes OUT_DIR/Timberjack in the Mist.vcscene and a .blend beside it to tweak.

The scan is COLMAP-style (-Y up, ground at y = 0.77, about 1 unit = 1 m: the machine is
~7.5 units long). Turned upright and dropped so the ground is Blender's Z = 0; then Blender
X, Y = the scan's x, z. Positions below are in those metres.
"""
import math
import os
import sys
import zipfile

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vc_scene_builder
vc_scene_builder.register()
from vc_scene_builder import bundle, fog, ops

argv = sys.argv[sys.argv.index("--") + 1:]
SCAN, OUT_DIR = argv[0], argv[1]
NAME = "Timberjack in the Mist"


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
ctx = bpy.context
scene = ctx.scene
scene.name = NAME
scene.unit_settings.scale_length = 1.0

bpy.ops.wm.ply_import(filepath=SCAN)
scan = ctx.selected_objects[0]
scan.name = "Timberjack scan"
scan.rotation_euler = (math.radians(-90), 0, 0)     # PLY -Y up -> Blender +Z up
scan.location = (0, 0, 0.77)                          # the ground to Z = 0
scan.scale = (1, 1, 1)                                # ~1 m per unit
ctx.view_layer.update()
ctx.view_layer.objects.active = scan

vc = scene.vc
vc.scan = scan
vc.scene_name = NAME
vc.source_ply = SCAN          # copied in untouched (the scan's licence allows no modified versions)
vc.kind = 'PLACE'
vc.ev = "12"                  # an overcast forest
vc.house_lights = "dusk"

# Start: standing by the end of the boom, looking up the clearing at the cab.
cam = ops.place_start(ctx, Matrix.Identity(4))
cam.location = (3.2, 7.6, 1.6)
aim(cam, (-0.8, -1.5, 1.6))
cam.data.lens = 28

# Lamps.
moon = ops.add_light(ctx, "Fresnel 2K", location=(-4.5, -8.0, 6.0))
moon.name = "Moon through the branches"
aim(moon, (0.8, 2.0, 0.0))
s = moon.data.vc
s.spot, s.gel, s.modifier, s.pattern_focus = 0.55, "Rosmont 66 Steel Blue", "Cookie: branches", 0.7

dawn = ops.add_light(ctx, "Ellipsoidal 750", location=(7.5, -1.5, 6.5))
dawn.name = "Low sun through the leaves"
aim(dawn, (-1.0, -1.0, 1.0))
s = dawn.data.vc
s.spot, s.gel, s.modifier, s.pattern_focus = 0.4, "Leeward 205 Half CT Orange", "Gobo: leaf breakup", 0.3

cab = ops.add_light(ctx, "Fresnel 650", location=(-1.6, -2.4, 3.3))
cab.name = "Cab work light"
aim(cab, (2.5, 3.5, 0.0))
s = cab.data.vc
s.spot, s.gel, s.dimmer_stops, s.fog_scatter = 0.15, "Rosmont 02 Bastard Amber", -1.5, 1.2

# Fog: a forest haze thinning with height, and mist lying in the clearing.
vc.fog_visibility = 90
vc.fog_colour = (0.86, 0.9, 1.0)
vc.fog_falloff = 5
vc.fog_base = 0
vc.fog_anisotropy = 0.65
vc.fog_variation, vc.fog_variation_size, vc.fog_variation_detail = 0.5, 5, 3
vc.fog = True

mist = ops.add_fog_patch(ctx, 'BOX', location=(1.0, 0.8, 0.3))
mist.name = "Ground mist"
mist.rotation_euler = (0, 0, math.radians(-33))       # along the clearing
mist.scale = (6.5, 9.5, 0.4)
f = mist.vc_fog
f.visibility, f.colour, f.softness, f.height_falloff = 14, (0.9, 0.92, 0.96), 0.6, 0.35
f.variation, f.variation_size, f.variation_detail, f.anisotropy = 0.7, 1.5, 4, 0.6

bank = ops.add_fog_patch(ctx, 'SPHERE', location=(6.0, 0.5, 1.5))
bank.name = "Mist in the trees"
bank.scale = (3.0, 3.5, 2.0)
f = bank.vc_fog
f.visibility, f.softness, f.variation, f.variation_size = 20, 0.8, 0.6, 2.0

# Keep the camera in the clearing (and above the ground).
bound = ops.add_bound(ctx, 'CYLINDER', location=(0.8, 0.5, 2.6))
bound.name = "The clearing"
bound.rotation_euler = (0, 0, math.radians(-33))
bound.scale = (6.5, 9.5, 2.5)

# Sound: wind in the trees everywhere, the harvester idling at the cab.
engine = ops.add_speaker(ctx, os.path.join(HERE, "sounds", "diesel_idle.wav"), location=(-1.4, -2.0, 1.5))
engine.name = "Diesel idling"
engine.data.volume, engine.data.distance_reference, engine.data.distance_max = 0.55, 3, 35
a = vc.ambience.add()
a.file, a.volume = os.path.join(HERE, "sounds", "forest_wind.wav"), 0.45

ctx.view_layer.update()
scene.camera = cam
os.makedirs(OUT_DIR, exist_ok=True)
out = os.path.join(OUT_DIR, NAME + ".vcscene")
j, problems = bundle.save(ctx, scan, out)
lic = os.path.join(os.path.dirname(SCAN), "license.txt")
if os.path.isfile(lic):
    with zipfile.ZipFile(out, "a") as z:
        z.write(lic, "license.txt")
print("PROBLEMS", problems)
print("SAVED", out, os.path.getsize(out))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, NAME + ".blend"))
print("BLEND saved")
