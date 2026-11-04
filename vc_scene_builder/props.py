"""Settings: the scene's (on Scene), each VC light's (on Light) and the kit they choose from."""

import json
import math
import os

import bpy

KIT = json.load(open(os.path.join(os.path.dirname(__file__), "kit.json")))
HEADS = {h["name"]: h for h in KIT["heads"]}
GELS = {g["name"]: g for g in KIT["gels"]}
MODIFIERS = {m["name"]: m for m in KIT["modifiers"]}

# 3200 K tungsten in linear Rec.709, the game's `tungsten` (normalised to green there;
# here to its brightest channel, so it is a valid Blender colour).
_T = KIT.get("tungstenRGB", (1.0, 0.80, 0.56))
TUNGSTEN = tuple(c / max(_T) for c in _T)

START_NAME = "VC Start"


def start_camera(scene):
    """The scene's start camera: tagged vc_start (any name), else one named VC Start."""
    for o in scene.objects:
        if o.type == 'CAMERA' and o.get("vc_start"):
            return o
    o = scene.objects.get(START_NAME)
    return o if o is not None and o.type == 'CAMERA' else None


def _items(names, about=""):
    return [(n, n, about, i) for i, n in enumerate(names)]


HEAD_ITEMS = _items([h["name"] for h in KIT["heads"]])
GEL_ITEMS = _items([g["name"] for g in KIT["gels"]])
HOUSE_ITEMS = _items([h["name"] for h in KIT["houseLevels"]])
EV_ITEMS = [(str(c["ev"]), c["name"], "", i) for i, c in enumerate(KIT["sceneLight"])]
# Every modifier, numbered by its place in the kit so a stored value keeps its meaning
# whichever subset the head shows.
_ALL_MODIFIER_ITEMS = [(m["name"], m["name"], "", i) for i, m in enumerate(KIT["modifiers"])]
_mod_cache = {}


def modifiers_for(kind):
    """Modifiers that fit a head kind (gobos only ellipsoidals; doors, flags, cookies the rest)."""
    return [m["name"] for m in KIT["modifiers"] if kind in m["fits"]]


def _modifier_items(self, context):
    kind = HEADS.get(self.head, KIT["heads"][0])["kind"]
    if kind not in _mod_cache:     # Blender needs the item strings kept alive
        fit = set(modifiers_for(kind))
        _mod_cache[kind] = [it for it in _ALL_MODIFIER_ITEMS if it[0] in fit]
    return _mod_cache[kind]


# ---------------------------------------------------------------- scan
def is_splat(obj):
    """A point cloud carrying splat colour: Blender's importer ('radiance:base') or raw 'f_dc_*'."""
    if obj is None or obj.type != 'POINTCLOUD':
        return False
    names = obj.data.attributes.keys()
    return "radiance:base" in names or any(n.startswith("f_dc") for n in names)


def scan_of_scene(scene):
    """The chosen scan, else the scene's only splat object (no context needed)."""
    if scene.vc.scan is not None:
        return scene.vc.scan
    found = [o for o in scene.objects if is_splat(o)]
    return found[0] if len(found) == 1 else None


def scan_of(context):
    """The chosen scan, else the active splat object (what Splat Patch works on), else the
    scene's only splat object."""
    s = context.scene.vc.scan
    if s is not None:
        return s
    a = context.active_object
    if is_splat(a):
        return a
    found = [o for o in context.scene.objects if is_splat(o)]
    return found[0] if len(found) == 1 else None


def pin_scan(context):
    """Remember the scan the first time a VC thing is added, before the active object changes."""
    vc = context.scene.vc
    if vc.scan is None:
        vc.scan = scan_of(context)


def metres_per_unit(scene, scan):
    """One PLY unit in metres: the scan's world scale times the scene's unit scale."""
    sc = scan.matrix_world.to_scale()
    return (abs(sc.x) + abs(sc.y) + abs(sc.z)) / 3 * scene.unit_settings.scale_length


# ---------------------------------------------------------------- light preview
def beam_angle(head, spot):
    """Full beam angle (degrees) at this spot/flood setting: 1 = full spot, 0 = full flood."""
    return head["floodAngle"] + (head["spotAngle"] - head["floodAngle"]) * spot


def preview(light, scene=None):
    """Make the Blender light show the VC settings: beam size, tungsten x gel colour and
    a lumens x dimmer energy. A preview only; the game uses its own photometry."""
    s = light.vc
    head = HEADS.get(s.head)
    if head is None:
        return
    want = 'AREA' if head["kind"] == "softlight" else 'SPOT'
    if light.type != want:
        name = light.name
        light.type = want
        light = bpy.data.lights[name]       # the old handle keeps the old type's class
        s = light.vc
    angle = beam_angle(head, s.spot)
    gel = GELS.get(s.gel, KIT["gels"][0])["rgb"]
    c = [t * g for t, g in zip(TUNGSTEN, gel)]
    peak = max(c) or 1.0
    light.color = [x / peak for x in c]
    # The colour was scaled up to its peak channel; scaling the energy back down by the
    # same factor leaves what the gel lets through (an ungelled head has peak 1).
    lumens = head["lumens"] * 2.0 ** s.dimmer_stops * peak
    scale = scene.unit_settings.scale_length if scene else 1.0
    half = math.radians(angle) / 2
    light.volume_factor = s.fog_scatter
    if want == 'SPOT':
        light.spot_size = math.radians(min(angle, 180))
        light.spot_blend = 0.15 if head["kind"] == "ellipsoidal" else 0.6
        light.shadow_soft_size = head["size"][0] * 0.4 / scale
        # Blender spreads a spot's watts as if over the whole sphere; the head puts its
        # lumens into the beam, so scale up by sphere / beam solid angle.
        omega = 2 * math.pi * (1 - math.cos(half))
        light.energy = 4 * math.pi / 683 * lumens / max(omega, 1e-4) / scale ** 2
    else:
        light.shape = 'RECTANGLE'
        light.size = head["size"][0] / scale
        light.size_y = head["size"][1] / scale
        light.spread = math.radians(min(angle, 180))
        light.energy = lumens / 683 / scale ** 2


def _light_update(self, context):
    light = self.id_data
    if self.modifier not in modifiers_for(HEADS.get(self.head, KIT["heads"][0])["kind"]):
        self["modifier"] = 0            # "Nothing"; set raw to avoid recursing
    preview(light, context.scene if context else None)


class VCLightSettings(bpy.types.PropertyGroup):
    is_vc: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    head: bpy.props.EnumProperty(name="Head", items=HEAD_ITEMS, default=HEAD_ITEMS[2][0],
                                 update=_light_update)
    spot: bpy.props.FloatProperty(name="Spot / Flood", min=0, max=1, default=0.5, subtype='FACTOR',
                                  description="1 = full spot (narrow), 0 = full flood (wide)",
                                  update=_light_update)
    dimmer_stops: bpy.props.FloatProperty(name="Dimmer", min=-8, max=0, default=0, step=50,
                                          description="Scrims / dimmer in stops: 0 = full, -1 = half",
                                          update=_light_update)
    gel: bpy.props.EnumProperty(name="Gel", items=GEL_ITEMS, update=_light_update)
    modifier: bpy.props.EnumProperty(name="Modifier", items=_modifier_items, update=_light_update)
    pattern_focus: bpy.props.FloatProperty(
        name="Pattern Focus", min=0, max=1, default=0.25, subtype='FACTOR',
        description="A gobo's focus (0 sharp, 1 soft), or how far a cookie stands from the head (0 near: soft, 1 far: crisper)")
    flare: bpy.props.BoolProperty(name="Flare", default=True,
                                  description="Lens flare from this light when it shines into the lens")
    fog_scatter: bpy.props.FloatProperty(name="Beam in Fog", min=0, soft_max=2, default=1, subtype='FACTOR',
                                         update=_light_update,
                                         description="How strongly this light's beam shows in fog (1: physical, 0: none)")


# ---------------------------------------------------------------- sky
def sync_world(scene):
    """Mirror the sky into the World (environment texture, yaw and strength)."""
    vc = scene.vc
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None) or nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new("ShaderNodeOutputWorld")
    if not bg.outputs[0].links:
        nt.links.new(bg.outputs[0], out.inputs[0])
    env = nt.nodes.get("VC Sky")
    path = bpy.path.abspath(vc.sky_path) if vc.sky_path else ""
    if not path:
        if env is not None:
            nt.nodes.remove(env)
            m = nt.nodes.get("VC Sky Mapping")
            if m:
                nt.nodes.remove(m)
        return
    if env is None:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.name = env.label = "VC Sky"
        env.location = bg.location.x - 300, bg.location.y
    mapping = nt.nodes.get("VC Sky Mapping")
    if mapping is None:
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.name = mapping.label = "VC Sky Mapping"
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = env.location.x - 400, env.location.y
        mapping.location = env.location.x - 200, env.location.y
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    mapping.inputs["Rotation"].default_value[2] = math.radians(vc.sky_yaw)
    bg.inputs["Strength"].default_value = 2.0 ** vc.sky_stops
    if env.image is None or bpy.path.abspath(env.image.filepath) != path:
        if os.path.isfile(path):
            env.image = bpy.data.images.load(path, check_existing=True)


def _sky_update(self, context):
    sync_world(self.id_data)            # the scene that owns the setting, not just the one showing


class VCAmbience(bpy.types.PropertyGroup):
    file: bpy.props.StringProperty(name="File", subtype='FILE_PATH')
    volume: bpy.props.FloatProperty(name="Volume", min=0, max=2, default=0.5, subtype='FACTOR')


def _scan_poll(self, obj):
    return is_splat(obj)


# ---------------------------------------------------------------- fog
def _patch_update(self, context):
    from . import fog
    obj = self.id_data
    fog.update_patch(obj, obj.users_scene[0] if obj.users_scene else context.scene)


def _ambient_update(self, context):
    from . import fog
    fog.update_ambient(self.id_data)


def _variation_props(update, size_default):
    """Shared by the ambient fog and the patches: 3D variation through the fog."""
    return dict(
        amount=bpy.props.FloatProperty(name="Variation", min=0, max=1, default=0, subtype='FACTOR', update=update,
                                       description="How much the fog thickens and thins through space (0: even)"),
        size=bpy.props.FloatProperty(name="Size", min=0.01, soft_max=500, default=size_default, update=update,
                                     description="Size of the wisps and banks (metres)"),
        detail=bpy.props.IntProperty(name="Detail", min=0, max=8, default=3, update=update,
                                     description="Finer wisps on the larger banks (noise octaves)"),
        seed=bpy.props.IntProperty(name="Seed", min=0, default=0, update=update,
                                   description="Picks a different pattern"))


ANISOTROPY_DOC = ("How much the fog scatters light forward: beams glow when you look into them "
                  "(0: evenly every way; real fog is about 0.5-0.8)")
_pv = _variation_props(_patch_update, 1.0)


class VCFogPatch(bpy.types.PropertyGroup):
    visibility: bpy.props.FloatProperty(name="Visibility", min=0.05, soft_max=1000, default=5,
                                        description="How far you can see through it (metres)",
                                        update=_patch_update)
    colour: bpy.props.FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0, max=1,
                                          default=(1, 1, 1), update=_patch_update)
    softness: bpy.props.FloatProperty(name="Softness", min=0, max=1, default=0.4, subtype='FACTOR',
                                      update=_patch_update,
                                      description="Share of the radius over which the edge fades out")
    height_falloff: bpy.props.FloatProperty(
        name="Height Fall-off", min=0, soft_max=50, default=0, update=_patch_update,
        description="The fog halves about every this many metres above the patch's lowest point (0: even)")
    anisotropy: bpy.props.FloatProperty(name="Anisotropy", min=0, max=0.95, default=0.6,
                                        update=_patch_update, description=ANISOTROPY_DOC)
    variation: _pv["amount"]
    variation_size: _pv["size"]
    variation_detail: _pv["detail"]
    variation_seed: _pv["seed"]


_av = _variation_props(_ambient_update, 20.0)


class VCSceneSettings(bpy.types.PropertyGroup):
    scene_name: bpy.props.StringProperty(name="Name", description="Shown as the game's window title (blank: the Blender scene's name)")
    scan: bpy.props.PointerProperty(name="Scan", type=bpy.types.Object, poll=_scan_poll,
                                    description="The splat object (blank: the active splat object)")
    opened_from: bpy.props.StringProperty(
        name="Opened From", subtype='DIR_PATH', options={'HIDDEN'},
        description="Where an opened .vcscene was unpacked (its other files are saved again with it)")
    source_ply: bpy.props.StringProperty(
        name="Source PLY", subtype='FILE_PATH',
        description="The scan's .ply, copied in as-is when Splat Patch isn't enabled to write it")
    kind: bpy.props.EnumProperty(name="Kind", items=[
        ('PLACE', "A place", "A place to stand in"),
        ('OBJECT', "An object", "Scanned on the rig, lit from the camera")], default='PLACE')
    ev: bpy.props.EnumProperty(name="Scene Light", items=EV_ITEMS, default=EV_ITEMS[4][0],
                               description="The light the scan was captured in")
    sky_path: bpy.props.StringProperty(name="Sky", subtype='FILE_PATH', update=_sky_update,
                                       description="An .hdr or .exr environment")
    sky_yaw: bpy.props.FloatProperty(name="Yaw", min=-360, max=360, default=0, update=_sky_update,
                                     description="Turn of the sky, in degrees")
    sky_stops: bpy.props.FloatProperty(name="Stops", min=-10, max=10, default=0, step=50,
                                       update=_sky_update, description="Sky brightness, in stops")
    house_lights: bpy.props.EnumProperty(name="House Lights", items=HOUSE_ITEMS)
    ambience: bpy.props.CollectionProperty(type=VCAmbience)
    ambience_index: bpy.props.IntProperty()
    fog: bpy.props.BoolProperty(name="Ambient Fog", update=_ambient_update,
                                description="Fog through the whole scene, lit by the scene's light and the VC lights")
    fog_visibility: bpy.props.FloatProperty(name="Visibility", min=1, soft_max=20000, default=300,
                                            update=_ambient_update,
                                            description="How far you can see through it (metres)")
    fog_colour: bpy.props.FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0, max=1,
                                              default=(1, 1, 1), update=_ambient_update)
    fog_falloff: bpy.props.FloatProperty(name="Height Fall-off", min=0, soft_max=200, default=8,
                                         update=_ambient_update,
                                         description="The fog halves about every this many metres above its base (0: even everywhere)")
    fog_base: bpy.props.FloatProperty(name="Base Height", default=0, unit='LENGTH', update=_ambient_update,
                                      description="World Z of the ground: below it the fog stays at full density")
    fog_anisotropy: bpy.props.FloatProperty(name="Anisotropy", min=0, max=0.95, default=0.6,
                                            update=_ambient_update, description=ANISOTROPY_DOC)
    fog_variation: _av["amount"]
    fog_variation_size: _av["size"]
    fog_variation_detail: _av["detail"]
    fog_variation_seed: _av["seed"]


CLASSES = (VCLightSettings, VCAmbience, VCFogPatch, VCSceneSettings)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.vc = bpy.props.PointerProperty(type=VCSceneSettings)
    bpy.types.Light.vc = bpy.props.PointerProperty(type=VCLightSettings)
    bpy.types.Object.vc_fog = bpy.props.PointerProperty(type=VCFogPatch)


def unregister():
    del bpy.types.Object.vc_fog
    del bpy.types.Light.vc
    del bpy.types.Scene.vc
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
