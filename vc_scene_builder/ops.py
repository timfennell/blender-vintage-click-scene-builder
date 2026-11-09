import json
import os
import zipfile

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix

from . import bundle, fog
from .props import HEAD_ITEMS, HEADS, START_NAME, pin_scan, preview, scan_of, start_camera


def place_start(context, matrix):
    """Create or move the "VC Start" camera to a world matrix (camera looks down its -Z)."""
    pin_scan(context)
    scene = context.scene
    cam = start_camera(scene)
    if cam is None:
        data = bpy.data.cameras.new(START_NAME)
        data.sensor_width = 36.0
        data.lens = 35.0
        cam = bpy.data.objects.new(START_NAME, data)
        cam["vc_start"] = True
        scene.collection.objects.link(cam)
    cam.matrix_world = Matrix(matrix)
    return cam


def add_light(context, head, location=None):
    """A Blender spot (area for the softlight) carrying VC head settings."""
    pin_scan(context)
    data = bpy.data.lights.new(head, 'AREA' if HEADS[head]["kind"] == "softlight" else 'SPOT')
    data.vc.is_vc = True
    data.vc.head = head
    obj = bpy.data.objects.new(head, data)
    context.collection.objects.link(obj)
    obj.location = location if location is not None else context.scene.cursor.location
    preview(data, context.scene)
    return obj


BOUND_ITEMS = [('BOX', "Box", "A box the camera can move inside"),
               ('SPHERE', "Sphere", "A sphere the camera can move inside"),
               ('CYLINDER', "Cylinder", "An upright cylinder the camera can move inside")]


def _unit_cylinder():
    me = bpy.data.meshes.get("VC Bound Cylinder")
    if me is None:
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1, radius2=1, depth=2)
        me = bpy.data.meshes.new("VC Bound Cylinder")
        bm.to_mesh(me)
        bm.free()
    return me


def add_bound(context, shape, location=None):
    """A movement bound: an empty (box, sphere) or a wireframe unit cylinder (axis local Z)."""
    pin_scan(context)
    name = "VC Bound " + shape.title()
    if shape == 'CYLINDER':
        obj = bpy.data.objects.new(name, _unit_cylinder())
        obj.display_type = 'WIRE'
        obj.hide_render = True
        obj.visible_camera = obj.visible_shadow = False
    else:
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = 'CUBE' if shape == 'BOX' else 'SPHERE'
        obj.empty_display_size = 1.0
    obj["vc_bound"] = shape
    context.collection.objects.link(obj)
    obj.location = location if location is not None else context.scene.cursor.location
    return obj


FOG_ITEMS = [('BOX', "Box", "A box of fog (flatten it over a pond)"),
             ('SPHERE', "Sphere", "A ball of fog"),
             ('CYLINDER', "Cylinder", "An upright cylinder of fog")]


def _unit_mesh(shape, name):
    """Cube ±1, UV sphere radius 1, or cylinder radius 1 from z -1 to 1: the unit primitives."""
    import bmesh
    bm = bmesh.new()
    if shape == 'BOX':
        bmesh.ops.create_cube(bm, size=2)
    elif shape == 'SPHERE':
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1)
    else:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1, radius2=1, depth=2)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def add_fog_patch(context, shape, location=None):
    """A local fog volume: a unit mesh primitive with a Principled Volume to preview it."""
    pin_scan(context)
    name = "VC Fog " + shape.title()
    obj = bpy.data.objects.new(name, _unit_mesh(shape, name))
    obj["vc_fog"] = shape
    context.collection.objects.link(obj)
    obj.location = location if location is not None else context.scene.cursor.location
    context.view_layer.update()
    fog.update_patch(obj, context.scene)
    return obj


def add_speaker(context, filepath, location=None):
    pin_scan(context)
    data = bpy.data.speakers.new(os.path.splitext(os.path.basename(filepath))[0] or "Sound")
    if filepath:
        data.sound = bpy.data.sounds.load(filepath, check_existing=True)
    data.distance_reference = 2.0
    data.distance_max = 40.0
    data.volume = 0.8
    obj = bpy.data.objects.new(data.name, data)
    context.collection.objects.link(obj)
    obj.location = location if location is not None else context.scene.cursor.location
    return obj


class VCS_OT_set_start(bpy.types.Operator):
    """Put the "VC Start" camera where the viewport is looking from (the game opens here)"""
    bl_idname = "vcs.set_start_from_view"
    bl_label = "Set Start From View"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        rv3d = context.space_data.region_3d
        cam = place_start(context, rv3d.view_matrix.inverted())
        if rv3d.view_perspective != 'CAMERA':
            # The viewport's lens is drawn on a 72 mm-wide sensor; give the camera the same view.
            cam.data.lens = context.space_data.lens * cam.data.sensor_width / 72.0
        self.report({'INFO'}, f"{cam.name} set ({cam.data.lens:.0f} mm)")
        return {'FINISHED'}


class VCS_OT_add_light(bpy.types.Operator):
    """Add a Vintage Click light head at the 3D cursor"""
    bl_idname = "vcs.add_light"
    bl_label = "Add VC Light"
    bl_options = {'REGISTER', 'UNDO'}

    head: bpy.props.EnumProperty(name="Head", items=HEAD_ITEMS, default=HEAD_ITEMS[2][0])

    def execute(self, context):
        obj = add_light(context, self.head)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class VCS_OT_add_bound(bpy.types.Operator):
    """Add a movement bound at the 3D cursor: the camera stays inside the union of all bounds"""
    bl_idname = "vcs.add_bound"
    bl_label = "Add Bound"
    bl_options = {'REGISTER', 'UNDO'}

    shape: bpy.props.EnumProperty(name="Shape", items=BOUND_ITEMS)

    def execute(self, context):
        obj = add_bound(context, self.shape)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class VCS_OT_add_fog_patch(bpy.types.Operator):
    """Add a patch of fog at the 3D cursor (mist over a pond, a fog bank)"""
    bl_idname = "vcs.add_fog_patch"
    bl_label = "Add Fog Patch"
    bl_options = {'REGISTER', 'UNDO'}

    shape: bpy.props.EnumProperty(name="Shape", items=FOG_ITEMS)

    def execute(self, context):
        obj = add_fog_patch(context, self.shape)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class VCS_OT_select(bpy.types.Operator):
    """Select this object"""
    bl_idname = "vcs.select"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.name)
        if obj is None:
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


SOUND_GLOB = "*.wav;*.aif;*.aiff;*.mp3;*.m4a"


class VCS_OT_add_sound(bpy.types.Operator, ImportHelper):
    """Add a looping sound emitter (a Speaker) at the 3D cursor"""
    bl_idname = "vcs.add_sound"
    bl_label = "Add Sound Emitter"
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: bpy.props.StringProperty(default=SOUND_GLOB, options={'HIDDEN'})

    def execute(self, context):
        add_speaker(context, self.filepath)
        return {'FINISHED'}


class VCS_OT_ambience_add(bpy.types.Operator, ImportHelper):
    """Add an ambience bed (plays everywhere, not from a place)"""
    bl_idname = "vcs.ambience_add"
    bl_label = "Add Ambience"
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: bpy.props.StringProperty(default=SOUND_GLOB, options={'HIDDEN'})

    def execute(self, context):
        vc = context.scene.vc
        a = vc.ambience.add()
        a.file = self.filepath
        vc.ambience_index = len(vc.ambience) - 1
        return {'FINISHED'}


class VCS_OT_ambience_remove(bpy.types.Operator):
    """Remove the selected ambience bed"""
    bl_idname = "vcs.ambience_remove"
    bl_label = "Remove Ambience"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.vc.ambience) > 0

    def execute(self, context):
        vc = context.scene.vc
        vc.ambience.remove(vc.ambience_index)
        vc.ambience_index = max(0, min(vc.ambience_index, len(vc.ambience) - 1))
        return {'FINISHED'}


class VCS_OT_save(bpy.types.Operator, ExportHelper):
    """Save the scene as one .vcscene file for Vintage Click"""
    bl_idname = "vcs.save_scene"
    bl_label = "Save .vcscene"
    filename_ext = ".vcscene"
    filter_glob: bpy.props.StringProperty(default="*.vcscene", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        if scan_of(context) is None:
            cls.poll_message_set("No scan: choose the splat object in Scene > Scan")
            return False
        return True

    def invoke(self, context, event):
        if not self.filepath:
            vc = context.scene.vc
            self.filepath = bpy.path.clean_name(vc.scene_name or context.scene.name) + ".vcscene"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            j, problems = bundle.save(context, scan_of(context), self.filepath)
        except bundle.BundleError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        for p in problems:
            self.report({'WARNING'}, p)
        self.report({'INFO'}, f"Saved {os.path.basename(self.filepath)}: {len(j['lights'])} lights, "
                              f"{len(j['sounds'])} sounds, {len(j['ambience'])} ambience"
                              + f", {len(j['bounds'])} bounds, {len(j['fogVolumes'])} fog patches"
                              + (f" ({len(problems)} missing)" if problems else ""))
        return {'FINISHED'}


class VCS_OT_open_scene(bpy.types.Operator, ImportHelper):
    """Open a .vcscene to edit it: its scan, start, sky, lights, sounds, bounds and fog come
    back in a new scene, ready to save again"""
    bl_idname = "vcs.open_scene"
    bl_label = "Open .vcscene"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".vcscene"
    filter_glob: bpy.props.StringProperty(default="*.vcscene", options={'HIDDEN'})

    def execute(self, context):
        from . import opener
        try:
            scene, notes = opener.open_bundle(context, self.filepath)
        except (opener.OpenError, zipfile.BadZipFile, json.JSONDecodeError, KeyError) as e:
            self.report({'ERROR'}, f"Can't open {os.path.basename(self.filepath)}: {e}")
            return {'CANCELLED'}
        if context.window is not None:
            context.window.scene = scene
        for n in notes:
            self.report({'WARNING'}, n)
        self.report({'INFO'}, f"Opened {scene.name}" + (f" ({len(notes)} notes)" if notes else ""))
        return {'FINISHED'}


def menu_import(self, context):
    self.layout.operator(VCS_OT_open_scene.bl_idname, text="Vintage Click Scene (.vcscene)")


def menu_export(self, context):
    self.layout.operator(VCS_OT_save.bl_idname, text="Vintage Click Scene (.vcscene)")


CLASSES = (VCS_OT_set_start, VCS_OT_add_light, VCS_OT_add_bound, VCS_OT_add_fog_patch, VCS_OT_select, VCS_OT_add_sound,
           VCS_OT_ambience_add, VCS_OT_ambience_remove, VCS_OT_save, VCS_OT_open_scene)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
