import bpy

from . import bundle
from .props import metres_per_unit, scan_of, start_camera


class _Panel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Vintage Click"


class VCS_PT_scene(_Panel, bpy.types.Panel):
    bl_label = "Scene"

    def draw(self, context):
        layout = self.layout
        vc = context.scene.vc
        layout.prop(vc, "scene_name")
        layout.prop(vc, "scan")
        scan = scan_of(context)
        col = layout.column(align=True)
        if scan is None:
            col.label(text="No scan: pick one, or make a splat object active", icon='ERROR')
        else:
            if vc.scan is None:
                col.label(text=f"Using the active splats: {scan.name}", icon='POINTCLOUD_DATA')
            col.label(text=f"{metres_per_unit(context.scene, scan):.4g} m per PLY unit")
            sc = scan.matrix_world.to_scale()
            if max(sc) - min(sc) > 1e-4 * max(abs(max(sc)), 1e-9):
                col.label(text="Scale it evenly: the game takes one scale", icon='ERROR')
        gsp = bundle.splat_patch()
        if gsp is None:
            layout.prop(vc, "source_ply")
        if scan is not None:
            extra = bundle.merged_in(context.scene, scan)
            if extra:
                box = layout.box()
                box.label(text=f"Also saved into the scene's splats ({len(extra)}):", icon='AUTOMERGE_ON')
                for o in extra:
                    box.label(text=o.name, icon='POINTCLOUD_DATA')
                box.label(text="Turn off Show in Renders to leave one out")
                if gsp is None:
                    box.label(text="Needs Splat Patch enabled to merge", icon='ERROR')
        if hasattr(bpy.types, "GSP_OT_convert_mesh"):
            layout.operator("gsp.convert_mesh", text="Convert Meshes to Splats", icon='POINTCLOUD_DATA')
        layout.prop(vc, "kind", expand=True)
        layout.prop(vc, "ev")
        layout.separator()
        row = layout.row(align=True)
        row.operator("vcs.open_scene", text="Open…", icon='FILE_FOLDER')
        row.operator("vcs.save_scene", text="Save .vcscene…", icon='EXPORT')


class VCS_PT_start(_Panel, bpy.types.Panel):
    bl_label = "Start"

    def draw(self, context):
        layout = self.layout
        layout.operator("vcs.set_start_from_view", icon='CAMERA_DATA')
        cam = start_camera(context.scene)
        if cam is not None:
            row = layout.row()
            row.prop(cam.data, "lens", text="Lens (mm)")
            layout.operator("vcs.select", text=f"Select {cam.name}", icon='RESTRICT_SELECT_OFF').name = cam.name
        else:
            layout.label(text="No start: the game will guess one")


class VCS_PT_sky(_Panel, bpy.types.Panel):
    bl_label = "Sky"

    def draw(self, context):
        vc = context.scene.vc
        col = self.layout.column()
        col.prop(vc, "sky_path", text="")
        row = col.row(align=True)
        row.prop(vc, "sky_yaw")
        row.prop(vc, "sky_stops")


class VCS_PT_house(_Panel, bpy.types.Panel):
    bl_label = "House Lights"

    def draw(self, context):
        self.layout.prop(context.scene.vc, "house_lights", text="")


class VCS_PT_lights(_Panel, bpy.types.Panel):
    bl_label = "Lights"

    def draw(self, context):
        layout = self.layout
        layout.operator_menu_enum("vcs.add_light", "head", text="Add VC Light", icon='LIGHT_SPOT')
        lights = bundle.vc_lights(context.scene)
        active = context.active_object
        if lights:
            box = layout.box()
            for o in lights:
                row = box.row(align=True)
                row.operator("vcs.select", text=o.name, depress=(o == active),
                             icon='LIGHT_AREA' if o.data.type == 'AREA' else 'LIGHT_SPOT').name = o.name
                row.label(text=o.data.vc.head)
        if active is not None and active.type == 'LIGHT' and active.data.vc.is_vc:
            s = active.data.vc
            col = layout.column()
            col.label(text=active.name, icon='LIGHT')
            col.prop(s, "head")
            col.prop(s, "spot")
            col.prop(s, "dimmer_stops")
            col.prop(s, "gel")
            col.prop(s, "modifier")
            sub = col.column()
            sub.active = s.modifier.startswith(("Gobo", "Cookie"))
            sub.prop(s, "pattern_focus")
            col.prop(s, "flare")
            col.prop(s, "fog_scatter")


class VCS_UL_ambience(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "file", text="", emboss=False)
        row.prop(item, "volume", text="")


def _variation(layout, owner, prefix):
    box = layout.box()
    box.prop(owner, prefix + "variation")
    sub = box.column(align=True)
    sub.active = getattr(owner, prefix + "variation") > 0
    sub.prop(owner, prefix + "variation_size", text="Size (m)")
    sub.prop(owner, prefix + "variation_detail")
    sub.prop(owner, prefix + "variation_seed")


class VCS_PT_fog(_Panel, bpy.types.Panel):
    bl_label = "Fog"

    def draw(self, context):
        layout = self.layout
        vc = context.scene.vc
        layout.prop(vc, "fog")
        col = layout.column()
        col.active = vc.fog
        col.prop(vc, "fog_visibility", text="Visibility (m)")
        col.prop(vc, "fog_colour")
        col.prop(vc, "fog_falloff", text="Height Fall-off (m)")
        col.prop(vc, "fog_base")
        col.prop(vc, "fog_anisotropy")
        _variation(col, vc, "fog_")
        layout.separator()
        layout.prop(vc, "ground_fog")
        col = layout.column()
        col.active = vc.ground_fog
        col.prop(vc, "ground_visibility", text="Visibility (m)")
        row = col.row(align=True)
        row.prop(vc, "ground_level")
        row.operator("vcs.ground_from_cursor", text="", icon='EYEDROPPER')
        col.prop(vc, "ground_depth", text="Depth (m)")
        col.prop(vc, "ground_fade", text="Fade (m)")
        col.prop(vc, "ground_patchiness")
        col.prop(vc, "ground_drift", text="Drift Size (m)")
        layout.separator()
        layout.operator_menu_enum("vcs.add_fog_patch", "shape", text="Add Fog Patch", icon='OUTLINER_DATA_VOLUME')
        active = context.active_object
        for o in bundle.fog_patches(context.scene):
            layout.operator("vcs.select", text=o.name, depress=(o == active),
                            icon='OUTLINER_OB_VOLUME').name = o.name
        if active is not None and active.get("vc_fog") in bundle.FOG_SHAPES:
            col = layout.column()
            col.label(text=active.name, icon='OUTLINER_OB_VOLUME')
            col.prop(active.vc_fog, "visibility", text="Visibility (m)")
            col.prop(active.vc_fog, "colour")
            col.prop(active.vc_fog, "softness")
            col.prop(active.vc_fog, "height_falloff", text="Height Fall-off (m)")
            col.prop(active.vc_fog, "anisotropy")
            _variation(col, active.vc_fog, "")


class VCS_PT_bounds(_Panel, bpy.types.Panel):
    bl_label = "Bounds"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        for shape, icon in (('BOX', 'MESH_CUBE'), ('SPHERE', 'MESH_UVSPHERE'), ('CYLINDER', 'MESH_CYLINDER')):
            col.operator("vcs.add_bound", text=f"Add Bound {shape.title()}", icon=icon).shape = shape
        found = bundle.bounds(context.scene)
        if not found:
            layout.label(text="No bounds: the camera goes anywhere")
            return
        layout.label(text="The camera stays inside any of these:")
        active = context.active_object
        for o in found:
            layout.operator("vcs.select", text=o.name, depress=(o == active),
                            icon='CUBE' if o["vc_bound"] == 'BOX' else
                            'SPHERE' if o["vc_bound"] == 'SPHERE' else 'MESH_CYLINDER').name = o.name


class VCS_PT_sounds(_Panel, bpy.types.Panel):
    bl_label = "Sounds"

    def draw(self, context):
        layout = self.layout
        vc = context.scene.vc
        layout.operator("vcs.add_sound", icon='SPEAKER')
        active = context.active_object
        for o in bundle.speakers(context.scene):
            row = layout.row(align=True)
            row.operator("vcs.select", text=o.name, depress=(o == active), icon='SPEAKER').name = o.name
        if active is not None and active.type == 'SPEAKER':
            col = layout.column()
            col.template_ID(active.data, "sound", open="sound.open_mono")
            col.prop(active.data, "volume")
            col.prop(active.data, "distance_reference", text="Full Within")
            col.prop(active.data, "distance_max", text="Silent Beyond")
        layout.label(text="Ambience")
        row = layout.row()
        row.template_list("VCS_UL_ambience", "", vc, "ambience", vc, "ambience_index", rows=2)
        col = row.column(align=True)
        col.operator("vcs.ambience_add", text="", icon='ADD')
        col.operator("vcs.ambience_remove", text="", icon='REMOVE')


CLASSES = (VCS_PT_scene, VCS_PT_start, VCS_PT_sky, VCS_PT_house, VCS_PT_lights, VCS_PT_fog, VCS_PT_bounds, VCS_UL_ambience, VCS_PT_sounds)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
