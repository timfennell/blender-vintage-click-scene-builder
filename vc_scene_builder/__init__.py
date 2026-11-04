"""Vintage Click Scene Builder: compose a scan, start view, sky, lights and sounds in
Blender and save them as one .vcscene file the game opens."""

from . import props, ops, ui


def register():
    props.register()
    ops.register()
    ui.register()


def unregister():
    ui.unregister()
    ops.unregister()
    props.unregister()
