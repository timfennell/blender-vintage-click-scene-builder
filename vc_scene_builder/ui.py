import bpy

from . import bundle
from .props import START_NAME, metres_per_unit, scan_of


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
        if bundle.splat_patch() is None:
            layout.prop(vc, "source_ply")
        layout.prop(vc, "kind", expand=True)
        layout.prop(vc, "ev")
        layout.separator()
        layout.operator("vcs.save_scene", text="Save .vcscene…", icon='EXPORT')


class VCS_PT_start(_Panel, bpy.types.Panel):
    bl_label = "Start"

    def draw(self, context):
        layout = self.layout
        layout.operator("vcs.set_start_from_view", icon='CAMERA_DATA')
        cam = context.scene.objects.get(START_NAME)
        if cam is not None and cam.type == 'CAMERA':
            row = layout.row()
            row.prop(cam.data, "lens", text="Lens (mm)")
            layout.operator("vcs.select", text=f"Select {START_NAME}", icon='RESTRICT_SELECT_OFF').name = cam.name
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


class VCS_UL_ambience(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "file", text="", emboss=False)
        row.prop(item, "volume", text="")


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


CLASSES = (VCS_PT_scene, VCS_PT_start, VCS_PT_sky, VCS_PT_house, VCS_PT_lights, VCS_UL_ambience, VCS_PT_sounds)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
