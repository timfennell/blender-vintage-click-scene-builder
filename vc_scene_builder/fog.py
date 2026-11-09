"""Fog previews: volume materials matching what the game draws (as closely as Blender's
nodes allow).

Density everywhere is   sigma(visibility) x height x variation [x edge, for a patch]:
- sigma = 3.912 / visibility (metres): meteorological visibility, 2% contrast left.
- height = 2^(-h / heightFalloffM), h = metres above the base (ambient: the base height;
  a patch: its lowest point), h clamped at 0; 1 when heightFalloffM is 0.
- variation = max(0, 1 + amount x v), v = 3D noise in about [-1, 1] at feature size sizeM,
  `detail` octaves, `seed` picking the pattern. The game's noise differs from Blender's:
  the character matches, not the exact wisps.
- edge (a patch) = smoothstep from its surface (d = 1) to d = 1 - softness, where d is the
  unit primitive's own distance (box max|x|; sphere |x|; cylinder max(|xy|, |z|)).
VC lights scatter in the fog (Blender: the light's volume factor = its fogScatter), with
the fog's anisotropy (forward scattering: beams glow when you look into them).
"""

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

VISIBILITY_K = 3.912
AMBIENT_NAME = "VC Ambient Fog (preview)"


def sigma(visibility_m, scene):
    """Extinction per Blender unit for a visibility in metres."""
    return VISIBILITY_K / max(visibility_m, 1e-3) * scene.unit_settings.scale_length


def lowest(obj, shape):
    """World Z of the lowest point of an object's unit primitive (box, sphere, cylinder)."""
    m = obj.matrix_world
    g = m.to_3x3().transposed() @ Vector((0, 0, 1))    # up, seen in the primitive's frame
    if shape == 'BOX':
        support = abs(g.x) + abs(g.y) + abs(g.z)
    elif shape == 'SPHERE':
        support = g.length
    else:
        support = abs(g.z) + Vector((g.x, g.y)).length
    return m.translation.z - support


# ---------------------------------------------------------------- node building
class _Graph:
    def __init__(self, mat):
        mat.use_nodes = True
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = -1400

    def node(self, kind, **inputs):
        n = self.nt.nodes.new(kind)
        n.location = (self.x, -200 * (len(self.nt.nodes) % 6))
        self.x += 60
        for k, v in inputs.items():
            self.put(n.inputs[k] if isinstance(k, str) else n.inputs[k], v)
        return n

    def put(self, socket, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, socket)
        else:
            socket.default_value = v

    def math(self, op, a, b=0.0, c=0.0):
        n = self.nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.location = (self.x, -200 * (len(self.nt.nodes) % 6))
        self.x += 60
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        self.put(n.inputs[2], c)
        return n.outputs[0]

    def value(self, name, v):
        n = self.nt.nodes.new("ShaderNodeValue")
        n.name = n.label = name
        n.outputs[0].default_value = v
        n.location = (self.x, 200)
        self.x += 60
        return n.outputs[0]


def _height(g, z, base, falloff_bu):
    if falloff_bu <= 0:
        return None
    h = g.math('MAXIMUM', g.math('SUBTRACT', z, base), 0.0)
    return g.math('POWER', 2.0, g.math('MULTIPLY', h, -1.0 / falloff_bu))


def _variation(g, pos, amount, size_bu, detail, seed):
    if amount <= 0:
        return None
    noise = g.node("ShaderNodeTexNoise")
    noise.noise_dimensions = '4D'
    g.put(noise.inputs["Vector"], pos)
    noise.inputs["W"].default_value = float(seed) * 7.31
    noise.inputs["Scale"].default_value = 1.0 / max(size_bu, 1e-4)
    noise.inputs["Detail"].default_value = float(detail)
    v = g.math('MULTIPLY', g.math('SUBTRACT', noise.outputs["Fac"], 0.5), 4.0)   # ~[-1, 1]
    return g.math('MAXIMUM', g.math('MULTIPLY_ADD', v, amount, 1.0), 0.0)


def _edge(g, local, shape, softness):
    if softness <= 0:
        return None
    sep = g.node("ShaderNodeSeparateXYZ", Vector=local)
    ax, ay, az = (g.math('ABSOLUTE', sep.outputs[i]) for i in range(3))
    if shape == 'BOX':
        d = g.math('MAXIMUM', g.math('MAXIMUM', ax, ay), az)
    elif shape == 'SPHERE':
        d = g.node("ShaderNodeVectorMath", Vector=local)
        d.operation = 'LENGTH'
        d = d.outputs["Value"]
    else:
        r = g.math('SQRT', g.math('ADD', g.math('MULTIPLY', ax, ax), g.math('MULTIPLY', ay, ay)))
        d = g.math('MAXIMUM', r, az)
    mr = g.node("ShaderNodeMapRange")
    mr.interpolation_type = 'SMOOTHSTEP'
    g.put(mr.inputs["Value"], d)
    mr.inputs["From Min"].default_value = 1.0
    mr.inputs["From Max"].default_value = 1.0 - softness
    mr.inputs["To Min"].default_value = 0.0
    mr.inputs["To Max"].default_value = 1.0
    return mr.outputs["Result"]


def build(mat, scene, *, visibility, colour, anisotropy, falloff_m, base_bu,
          amount, size_m, detail, seed, shape=None, softness=0.0):
    """(Re)build a fog volume material. base_bu: world Z the height fall-off starts from."""
    s = scene.unit_settings.scale_length
    g = _Graph(mat)
    geo = g.node("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    z = g.node("ShaderNodeSeparateXYZ", Vector=pos).outputs["Z"]
    density = g.value("VC Density", sigma(visibility, scene))
    base = g.value("VC Base", base_bu)
    factors = [_height(g, z, base, falloff_m / s), _variation(g, pos, amount, size_m / s, detail, seed)]
    if shape is not None:
        local = g.node("ShaderNodeTexCoord").outputs["Object"]
        factors.append(_edge(g, local, shape, softness))
    for f in factors:
        if f is not None:
            density = g.math('MULTIPLY', density, f)
    vol = g.node("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (*colour, 1.0)
    vol.inputs["Anisotropy"].default_value = anisotropy
    g.put(vol.inputs["Density"], density)
    out = g.node("ShaderNodeOutputMaterial")
    g.nt.links.new(vol.outputs[0], out.inputs["Volume"])


def setup_render(scene):
    """So beams in the fog carry shadows (trees, the set, anything solid): EEVEE needs
    volumetric shadows switched on and its volume range to reach across the scene.
    Cycles shadows volumes on its own."""
    e = scene.eevee
    e.use_volumetric_shadows = True
    e.volumetric_shadow_samples = max(e.volumetric_shadow_samples, 32)
    e.volumetric_samples = max(e.volumetric_samples, 128)
    scan = None
    from .props import scan_of_scene
    scan = scan_of_scene(scene)
    if scan is not None:
        pts = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
        span = max((a - b).length for a in pts for b in pts)
        e.volumetric_end = max(e.volumetric_end, span * 1.5)


def show(obj, ambient=False):
    """Draw a fog object so its volume shows in Material Preview, EEVEE and Cycles (an object
    displayed as Wire or Bounds is left out of EEVEE's viewport), while in Solid mode it is a
    faint see-through box with its wireframe (ambient: just its bounds) over the scan."""
    obj.display_type = 'TEXTURED'
    obj.show_wire = not ambient
    obj.show_bounds = ambient
    mat = obj.active_material
    if mat is not None:
        c = mat.diffuse_color
        mat.diffuse_color = (c[0], c[1], c[2], 0.0 if ambient else 0.08)
    obj.visible_shadow = False          # fog dims light itself, as a volume; no surface shadow


def update_patch(obj, scene):
    f = obj.vc_fog
    mat = obj.active_material
    if mat is None:
        mat = bpy.data.materials.new(obj.name)
        obj.data.materials.append(mat)
    build(mat, scene, visibility=f.visibility, colour=f.colour, anisotropy=f.anisotropy,
          falloff_m=f.height_falloff, base_bu=lowest(obj, obj["vc_fog"]),
          amount=f.variation, size_m=f.variation_size, detail=f.variation_detail,
          seed=f.variation_seed, shape=obj["vc_fog"], softness=f.softness)
    mat.diffuse_color = (*f.colour, 0.08)
    show(obj)
    setup_render(scene)


def _set_base(obj, z):
    mat = obj.active_material
    if mat and mat.node_tree:
        n = mat.node_tree.nodes.get("VC Base")
        if n is not None and abs(n.outputs[0].default_value - z) > 1e-6:
            n.outputs[0].default_value = z


# ---------------------------------------------------------------- ambient preview
def update_ambient(scene):
    """A box round the scan carrying the ambient fog (the game's is everywhere; Blender's
    preview needs a volume to live in). Removed when ambient fog is off."""
    from .props import scan_of_scene
    vc = scene.vc
    obj = ambient_object(scene)
    scan = scan_of_scene(scene)
    if not vc.fog or scan is None:
        if obj is not None:
            me = obj.data
            bpy.data.objects.remove(obj)
            if me.users == 0:
                bpy.data.meshes.remove(me)
        return
    if obj is None:
        from .ops import _unit_mesh
        obj = bpy.data.objects.new(AMBIENT_NAME, _unit_mesh('BOX', AMBIENT_NAME))
        obj["vc_ambient"] = True
        obj.hide_select = True
        scene.collection.objects.link(obj)
        obj.data.materials.append(bpy.data.materials.new(AMBIENT_NAME))
    _fit_ambient(obj, scan, vc.fog_base)
    build(obj.active_material, scene, visibility=vc.fog_visibility, colour=vc.fog_colour,
          anisotropy=vc.fog_anisotropy, falloff_m=vc.fog_falloff, base_bu=vc.fog_base,
          amount=vc.fog_variation, size_m=vc.fog_variation_size, detail=vc.fog_variation_detail,
          seed=vc.fog_variation_seed)
    show(obj, ambient=True)
    setup_render(scene)


def ambient_object(scene):
    """This scene's ambient fog preview box, if it has one."""
    return next((o for o in scene.objects if o.get("vc_ambient")), None)


def _fit_ambient(obj, scan, base_z):
    pts = [scan.matrix_world @ Vector(c) for c in scan.bound_box]
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    lo.z = min(lo.z, base_z)
    centre, half = (lo + hi) / 2, (hi - lo) / 2 * 1.2 + Vector((0.01, 0.01, 0.01))
    if (obj.location - centre).length > 1e-5 or (Vector(obj.scale) - half).length > 1e-5:
        obj.location, obj.scale = centre, half


@persistent
def on_depsgraph(scene, depsgraph):
    """Keep patch bases on their lowest points and the ambient box round the scan as
    things move."""
    from .props import scan_of_scene
    scan = scan_of_scene(scene)
    for u in depsgraph.updates:
        if not u.is_updated_transform or not isinstance(u.id, bpy.types.Object):
            continue
        obj = scene.objects.get(u.id.name)
        if obj is None:
            continue
        if obj.get("vc_fog") in ('BOX', 'SPHERE', 'CYLINDER'):
            _set_base(obj, lowest(obj, obj["vc_fog"]))
        elif scan is not None and obj == scan and scene.vc.fog:
            amb = ambient_object(scene)
            if amb is not None:
                _fit_ambient(amb, scan, scene.vc.fog_base)


@persistent
def on_load(_):
    """Files saved before fog drew as a textured object showed no fog in the viewport."""
    for o in bpy.data.objects:
        if o.get("vc_fog") in ('BOX', 'SPHERE', 'CYLINDER') and o.display_type != 'TEXTURED':
            show(o)
        elif o.get("vc_ambient") and o.display_type != 'TEXTURED':
            show(o, ambient=True)


def register():
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph)
    bpy.app.handlers.load_post.append(on_load)


def unregister():
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
    if on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph)
