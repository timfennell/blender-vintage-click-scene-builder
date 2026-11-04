"""Vintage Click Scene Builder: compose a scan, start view, sky, lights and sounds in
Blender and save them as one .vcscene file the game opens."""

from . import props, ops, ui, fog


def register():
    props.register()
    ops.register()
    ui.register()
    fog.register()


def unregister():
    fog.unregister()
    ui.unregister()
    ops.unregister()
    props.unregister()
