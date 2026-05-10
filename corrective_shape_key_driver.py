# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Paradise Pictures
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

bl_info = {
    "name": "Corrective Shape Key Drivers",
    "author": "Paradise Pictures",
    "version": (1, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Corrective SK",
    "description": (
        "Create corrective shape key drivers from evaluated bone positions "
        "(IK-friendly), with bake-to-keyframes for game engine export"
    ),
    "category": "Rigging",
    "license": "GPL",
}

import bpy
from bpy.props import (
    FloatProperty,
    StringProperty,
    IntProperty,
    EnumProperty,
    PointerProperty,
    CollectionProperty,
    BoolProperty,
)


# ---------------------------------------------------------------------------
# Property Groups
# ---------------------------------------------------------------------------

class CSK_ControlPoint(bpy.types.PropertyGroup):
    """A single captured control point: normalized bone position -> shape key value."""
    norm_value: FloatProperty(
        name="Bone Position",
        description=(
            "Normalized bone position along the selected axis, "
            "captured automatically from the current pose"
        ),
        default=0.0,
    )
    sk_value: FloatProperty(
        name="Shape Key Value",
        description=(
            "How strongly the shape key should apply at this bone position "
            "(0 = off, 1 = fully on)"
        ),
        default=0.0,
        soft_min=0.0,
        soft_max=1.0,
    )


def _poll_mesh_with_shape_keys(self, obj):
    return (
        obj.type == 'MESH'
        and obj.data.shape_keys is not None
        and len(obj.data.shape_keys.key_blocks) > 1
    )


def _poll_armature(self, obj):
    return obj.type == 'ARMATURE'


class CSK_Properties(bpy.types.PropertyGroup):
    """Main addon state, stored on the Scene."""
    mesh_object: PointerProperty(
        type=bpy.types.Object,
        name="Mesh",
        description="Mesh with corrective shape keys",
        poll=_poll_mesh_with_shape_keys,
    )
    shape_key_name: StringProperty(
        name="Shape Key",
        description="Target shape key to drive",
    )
    armature: PointerProperty(
        type=bpy.types.Object,
        name="Armature",
        description="Armature that drives the mesh",
        poll=_poll_armature,
    )
    bone_name: StringProperty(
        name="Bone",
        description=(
            "Bone whose movement drives the shape key "
            "(works with IK, FK, and constraints)"
        ),
    )
    axis: EnumProperty(
        name="Axis",
        description="Which axis of bone movement to track",
        items=[
            ('0', 'X', 'Left / Right'),
            ('1', 'Y', 'Forward / Back'),
            ('2', 'Z', 'Up / Down'),
        ],
        default='2',
    )
    control_points: CollectionProperty(type=CSK_ControlPoint)
    active_point_index: IntProperty()


# ---------------------------------------------------------------------------
# UIList
# ---------------------------------------------------------------------------

class CSK_UL_ControlPointList(bpy.types.UIList):
    bl_idname = "CSK_UL_control_points"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        row = layout.row(align=True)
        row.label(text=f"Bone: {item.norm_value:.4f}  →")
        row.prop(item, "sk_value", text="Strength")
        op = row.operator(
            "corrective_sk.recapture_point", text="", icon='FILE_REFRESH')
        op.index = index
        op = row.operator(
            "corrective_sk.remove_point", text="", icon='X')
        op.index = index


# ---------------------------------------------------------------------------
# Helper: expression builder
# ---------------------------------------------------------------------------

def _build_expression(points):
    """Build a mapping expression string from control points.

    Uses ``__N__`` as the placeholder for the normalized bone position.
    The caller replaces the placeholder with the actual driver computation.

    Strategies by point count:
        2 points  -> linear ramp, clamped to the output range
        3 points  -> quadratic fit through all three, clamped 0-1
        4+ points -> clamped ramp-sum (piecewise linear)
    """
    N = '__N__'
    pts = sorted(points, key=lambda p: p[0])

    if len(pts) < 2:
        return str(pts[0][1]) if pts else '0'

    # --- 2-point: linear ---------------------------------------------------
    if len(pts) == 2:
        n0, v0 = pts[0]
        n1, v1 = pts[1]
        dn = n1 - n0
        if abs(dn) < 1e-10:
            return str(v0)
        slope = (v1 - v0) / dn
        intercept = v0 - slope * n0
        v_lo = min(v0, v1)
        v_hi = max(v0, v1)
        return (f'max({v_lo:.6f}, min({v_hi:.6f}, '
                f'{slope:.6f} * {N} + {intercept:.6f}))')

    # --- 3-point: quadratic ------------------------------------------------
    if len(pts) == 3:
        x0, y0 = pts[0]
        x1, y1 = pts[1]
        x2, y2 = pts[2]
        denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
        if abs(denom) < 1e-10:
            return _build_expression([pts[0], pts[-1]])
        a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
        b = (x2**2 * (y0 - y1) + x1**2 * (y2 - y0)
             + x0**2 * (y1 - y2)) / denom
        c = (x1**2 * (x2 * y0 - x0 * y2)
             + x1 * (x0**2 * y2 - x2**2 * y0)
             + x0 * x2 * (x2 - x0) * y1) / denom
        return (f'max(0, min(1, {a:.6f} * {N} * {N} '
                f'+ {b:.6f} * {N} + {c:.6f}))')

    # --- 4+ points: clamped ramp sum (piecewise linear) --------------------
    parts = [f'{pts[0][1]:.6f}']
    for i in range(len(pts) - 1):
        n0, v0 = pts[i]
        n1, v1 = pts[i + 1]
        dv = v1 - v0
        dn = n1 - n0
        if abs(dn) < 1e-10 or abs(dv) < 1e-10:
            continue
        parts.append(
            f'max(0, min(1, ({N} - {n0:.6f}) / {dn:.6f})) * {dv:.6f}'
        )
    return f'max(0, min(1, {" + ".join(parts)}))'


# ---------------------------------------------------------------------------
# Helper: create driver
# ---------------------------------------------------------------------------

def create_corrective_driver(mesh_obj, sk_name, armature, bone_name, axis,
                             points):
    """Build a corrective shape key driver using a mathematical expression.

    The driver computes a normalized bone position along the chosen axis,
    then maps it through an expression derived from the control points.

    Args:
        mesh_obj:  Mesh object with shape keys.
        sk_name:   Name of the target shape key.
        armature:  Armature object.
        bone_name: Name of the driving pose bone.
        axis:      ``'0'``, ``'1'``, or ``'2'`` for X, Y, Z.
        points:    list of ``(norm_value, sk_value)`` tuples (>= 2).

    Returns:
        The created ``FCurve``, or ``None`` on failure.
    """
    shape_keys = mesh_obj.data.shape_keys
    if not shape_keys or sk_name not in shape_keys.key_blocks:
        return None

    data_path = f'key_blocks["{sk_name}"].value'

    # Remove existing driver
    try:
        shape_keys.driver_remove(data_path)
    except TypeError:
        pass

    fcurve = shape_keys.driver_add(data_path)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'

    # Variable: tail component
    var_t = driver.variables.new()
    var_t.name = 'tail_ax'
    var_t.type = 'SINGLE_PROP'
    var_t.targets[0].id = armature
    var_t.targets[0].data_path = f'pose.bones["{bone_name}"].tail[{axis}]'

    # Variable: head component
    var_h = driver.variables.new()
    var_h.name = 'head_ax'
    var_h.type = 'SINGLE_PROP'
    var_h.targets[0].id = armature
    var_h.targets[0].data_path = f'pose.bones["{bone_name}"].head[{axis}]'

    # Variable: bone length
    var_l = driver.variables.new()
    var_l.name = 'bone_len'
    var_l.type = 'SINGLE_PROP'
    var_l.targets[0].id = armature
    var_l.targets[0].data_path = f'pose.bones["{bone_name}"].length'

    mapping_expr = _build_expression(points)
    full_expr = mapping_expr.replace(
        '__N__', '((tail_ax - head_ax) / bone_len)')
    driver.expression = full_expr

    return fcurve


# ---------------------------------------------------------------------------
# Helper: bake shape key drivers to keyframes
# ---------------------------------------------------------------------------

def bake_shape_key_drivers(mesh_obj, frame_start, frame_end, step=1,
                           remove_drivers=True):
    """Bake all driven shape keys on *mesh_obj* to per-frame keyframes.

    This evaluates each driver at every frame in the range and inserts a
    keyframe on the shape key value, producing an animation that is fully
    independent of drivers.  After baking, the drivers are optionally
    removed so the file can be exported to game engines (Unity, Unreal,
    Godot) that do not support Blender drivers.

    Args:
        mesh_obj:       The mesh whose shape key drivers to bake.
        frame_start:    First frame (inclusive).
        frame_end:      Last frame (inclusive).
        step:           Frame step (default 1 = every frame).
        remove_drivers: If ``True``, remove drivers after baking.

    Returns:
        List of shape key names that were baked, or empty list on failure.
    """
    if not mesh_obj or mesh_obj.type != 'MESH':
        return []

    shape_keys = mesh_obj.data.shape_keys
    if not shape_keys:
        return []

    # Find all shape keys that have drivers
    driven_sk_names = []
    if shape_keys.animation_data and shape_keys.animation_data.drivers:
        for fc in shape_keys.animation_data.drivers:
            # data_path looks like: key_blocks["SomeName"].value
            if fc.data_path.startswith('key_blocks["'):
                sk_name = fc.data_path.split('"')[1]
                if sk_name in shape_keys.key_blocks:
                    driven_sk_names.append(sk_name)

    if not driven_sk_names:
        return []

    scene = bpy.context.scene
    original_frame = scene.frame_current

    # Collect values for every frame
    # {sk_name: [(frame, value), ...]}
    baked_data = {name: [] for name in driven_sk_names}

    for frame in range(frame_start, frame_end + 1, step):
        scene.frame_set(frame)
        # Force dependency graph evaluation
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()

        for sk_name in driven_sk_names:
            val = shape_keys.key_blocks[sk_name].value
            baked_data[sk_name].append((frame, val))

    # Remove drivers first (so we can insert keyframes on the values)
    if remove_drivers:
        for sk_name in driven_sk_names:
            data_path = f'key_blocks["{sk_name}"].value'
            try:
                shape_keys.driver_remove(data_path)
            except TypeError:
                pass

    # Ensure shape_keys has animation_data for keyframes
    if not shape_keys.animation_data:
        shape_keys.animation_data_create()
    if not shape_keys.animation_data.action:
        shape_keys.animation_data.action = bpy.data.actions.new(
            name=f"{mesh_obj.name}_ShapeKeyBake"
        )

    action = shape_keys.animation_data.action

    # Insert keyframes from baked data
    for sk_name, frames_values in baked_data.items():
        data_path = f'key_blocks["{sk_name}"].value'

        # Find or create the FCurve
        fcurve = action.fcurves.find(data_path)
        if fcurve is None:
            fcurve = action.fcurves.new(data_path)
        else:
            # Clear existing keyframes
            while len(fcurve.keyframe_points) > 0:
                fcurve.keyframe_points.remove(fcurve.keyframe_points[0])

        # Bulk-insert keyframes (much faster than one-by-one)
        fcurve.keyframe_points.add(len(frames_values))
        for i, (frame, val) in enumerate(frames_values):
            kp = fcurve.keyframe_points[i]
            kp.co = (frame, val)
            kp.interpolation = 'LINEAR'

        # Update the fcurve
        fcurve.update()

    # Restore original frame
    scene.frame_set(original_frame)

    return driven_sk_names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_run_enabled():
    """Return True if Auto Run Python Scripts is enabled in preferences."""
    return bpy.context.preferences.filepaths.use_scripts_auto_execute


def _has_existing_driver(props):
    """Return True if the target shape key already has a driver."""
    if not props.mesh_object or not props.shape_key_name:
        return False
    sk = props.mesh_object.data.shape_keys
    if not sk or not sk.animation_data or not sk.animation_data.drivers:
        return False
    dp = f'key_blocks["{props.shape_key_name}"].value'
    for fc in sk.animation_data.drivers:
        if fc.data_path == dp:
            return True
    return False


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class CSK_OT_CapturePoint(bpy.types.Operator):
    bl_idname = "corrective_sk.capture_point"
    bl_label = "Capture Point"
    bl_description = (
        "Capture the current bone position as a control point. "
        "Pose your character first, then click this"
    )
    bl_options = {'REGISTER', 'UNDO'}

    sk_value: FloatProperty(
        name="Strength at this pose",
        description=(
            "How strongly the shape key should apply when the bone "
            "is in this position (0 = off, 1 = fully on)"
        ),
        default=1.0,
        soft_min=0.0,
        soft_max=1.0,
    )

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        return (
            props.armature is not None
            and props.bone_name != ""
            and props.armature.pose.bones.get(props.bone_name) is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "sk_value", slider=True)

    def execute(self, context):
        props = context.scene.corrective_sk
        bone = props.armature.pose.bones[props.bone_name]
        ax = int(props.axis)

        if bone.length < 1e-10:
            self.report({'ERROR'}, "Bone has zero length")
            return {'CANCELLED'}

        norm = (bone.tail[ax] - bone.head[ax]) / bone.length

        pt = props.control_points.add()
        pt.norm_value = norm
        pt.sk_value = self.sk_value
        props.active_point_index = len(props.control_points) - 1

        self.report({'INFO'},
                    f"Captured: Bone={norm:.4f} -> Strength={self.sk_value:.3f}")
        return {'FINISHED'}


class CSK_OT_RemovePoint(bpy.types.Operator):
    bl_idname = "corrective_sk.remove_point"
    bl_label = "Remove Point"
    bl_description = "Remove this control point"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        props = context.scene.corrective_sk
        if 0 <= self.index < len(props.control_points):
            props.control_points.remove(self.index)
            props.active_point_index = min(
                props.active_point_index,
                max(0, len(props.control_points) - 1),
            )
        return {'FINISHED'}


class CSK_OT_RecapturePoint(bpy.types.Operator):
    bl_idname = "corrective_sk.recapture_point"
    bl_label = "Recapture"
    bl_description = (
        "Update this point's bone position to the current pose "
        "(keeps the same strength value)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        return (
            props.armature is not None
            and props.bone_name != ""
            and props.armature.pose.bones.get(props.bone_name) is not None
        )

    def execute(self, context):
        props = context.scene.corrective_sk
        if 0 <= self.index < len(props.control_points):
            bone = props.armature.pose.bones[props.bone_name]
            ax = int(props.axis)

            if bone.length < 1e-10:
                self.report({'ERROR'}, "Bone has zero length")
                return {'CANCELLED'}

            norm = (bone.tail[ax] - bone.head[ax]) / bone.length
            props.control_points[self.index].norm_value = norm
            self.report({'INFO'}, f"Recaptured: Bone={norm:.4f}")
        return {'FINISHED'}


class CSK_OT_GenerateDriver(bpy.types.Operator):
    bl_idname = "corrective_sk.generate_driver"
    bl_label = "Generate Driver"
    bl_description = ("Create a corrective driver from the captured "
                      "control points")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        return (
            props.mesh_object is not None
            and props.shape_key_name != ""
            and props.armature is not None
            and props.bone_name != ""
            and len(props.control_points) >= 2
        )

    def execute(self, context):
        props = context.scene.corrective_sk

        if not _auto_run_enabled():
            self.report(
                {'ERROR'},
                "Enable 'Auto Run Python Scripts' in "
                "Preferences > Save & Load first",
            )
            return {'CANCELLED'}

        sk = props.mesh_object.data.shape_keys
        if not sk or props.shape_key_name not in sk.key_blocks:
            self.report({'ERROR'},
                        f"Shape key '{props.shape_key_name}' not found")
            return {'CANCELLED'}

        if props.armature.pose.bones.get(props.bone_name) is None:
            self.report({'ERROR'},
                        f"Bone '{props.bone_name}' not found")
            return {'CANCELLED'}

        points = [(cp.norm_value, cp.sk_value)
                  for cp in props.control_points]

        fcurve = create_corrective_driver(
            props.mesh_object, props.shape_key_name, props.armature,
            props.bone_name, props.axis, points,
        )

        if fcurve:
            context.view_layer.update()
            self.report(
                {'INFO'},
                f"Driver created for '{props.shape_key_name}' "
                f"with {len(points)} control points",
            )
            return {'FINISHED'}

        self.report({'ERROR'}, "Failed to create driver")
        return {'CANCELLED'}


class CSK_OT_RemoveDriver(bpy.types.Operator):
    bl_idname = "corrective_sk.remove_driver"
    bl_label = "Remove Driver"
    bl_description = "Remove the driver from the target shape key"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        if props.mesh_object and props.shape_key_name:
            sk = props.mesh_object.data.shape_keys
            if sk and props.shape_key_name in sk.key_blocks:
                if sk.animation_data and sk.animation_data.drivers:
                    dp = f'key_blocks["{props.shape_key_name}"].value'
                    for fc in sk.animation_data.drivers:
                        if fc.data_path == dp:
                            return True
        return False

    def execute(self, context):
        props = context.scene.corrective_sk
        sk = props.mesh_object.data.shape_keys
        data_path = f'key_blocks["{props.shape_key_name}"].value'
        try:
            sk.driver_remove(data_path)
            self.report({'INFO'},
                        f"Driver removed from '{props.shape_key_name}'")
        except TypeError:
            self.report({'WARNING'}, "No driver to remove")
        return {'FINISHED'}


class CSK_OT_MirrorDriver(bpy.types.Operator):
    bl_idname = "corrective_sk.mirror_driver"
    bl_label = "Mirror to Other Side"
    bl_description = ("Mirror the driver setup to the opposite side "
                      "(.l <-> .r)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        if not (props.mesh_object and props.armature
                and props.bone_name and props.shape_key_name):
            return False
        if len(props.control_points) < 2:
            return False
        mirrored_bone = bpy.utils.flip_name(props.bone_name)
        return mirrored_bone != props.bone_name

    def execute(self, context):
        props = context.scene.corrective_sk

        mirrored_bone = bpy.utils.flip_name(props.bone_name)
        mirrored_sk = bpy.utils.flip_name(props.shape_key_name)

        if props.armature.pose.bones.get(mirrored_bone) is None:
            self.report({'ERROR'},
                        f"Mirrored bone '{mirrored_bone}' not found")
            return {'CANCELLED'}

        sk = props.mesh_object.data.shape_keys
        if not sk or mirrored_sk not in sk.key_blocks:
            self.report(
                {'ERROR'},
                f"Mirrored shape key '{mirrored_sk}' not found. "
                f"Create it first, then mirror.",
            )
            return {'CANCELLED'}

        # For X axis negate the normalized value (opposite side)
        negate = (props.axis == '0')
        points = []
        for cp in props.control_points:
            n = -cp.norm_value if negate else cp.norm_value
            points.append((n, cp.sk_value))

        fcurve = create_corrective_driver(
            props.mesh_object, mirrored_sk, props.armature,
            mirrored_bone, props.axis, points,
        )

        if fcurve:
            context.view_layer.update()
            self.report(
                {'INFO'},
                f"Mirrored driver: '{mirrored_sk}' on bone "
                f"'{mirrored_bone}'",
            )
            return {'FINISHED'}

        self.report({'ERROR'}, "Failed to create mirrored driver")
        return {'CANCELLED'}


class CSK_OT_BakeDrivers(bpy.types.Operator):
    bl_idname = "corrective_sk.bake_drivers"
    bl_label = "Bake to Keyframes"
    bl_description = (
        "Bake all driven shape keys on this mesh to per-frame keyframes "
        "for game engine export (Unity / Unreal / Godot). "
        "Drivers are removed after baking"
    )
    bl_options = {'REGISTER', 'UNDO'}

    frame_start: IntProperty(
        name="Start Frame",
        description="First frame to bake",
        default=1,
    )
    frame_end: IntProperty(
        name="End Frame",
        description="Last frame to bake",
        default=250,
    )
    step: IntProperty(
        name="Step",
        description="Bake every Nth frame (1 = every frame)",
        default=1,
        min=1,
        max=10,
    )
    remove_drivers: BoolProperty(
        name="Remove Drivers After Bake",
        description=(
            "Remove drivers after baking so the file is ready for export. "
            "Disable to keep drivers alongside keyframes"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        if not props.mesh_object:
            return False
        sk = props.mesh_object.data.shape_keys
        if not sk or not sk.animation_data:
            return False
        return bool(sk.animation_data.drivers)

    def invoke(self, context, event):
        # Pre-fill with scene frame range
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "frame_start")
        col.prop(self, "frame_end")
        col.prop(self, "step")
        layout.separator()
        layout.prop(self, "remove_drivers")

    def execute(self, context):
        props = context.scene.corrective_sk

        if self.frame_end < self.frame_start:
            self.report({'ERROR'}, "End frame must be >= start frame")
            return {'CANCELLED'}

        baked = bake_shape_key_drivers(
            props.mesh_object,
            self.frame_start,
            self.frame_end,
            step=self.step,
            remove_drivers=self.remove_drivers,
        )

        if baked:
            total_frames = (self.frame_end - self.frame_start) // self.step + 1
            self.report(
                {'INFO'},
                f"Baked {len(baked)} shape key(s) over {total_frames} frames: "
                + ", ".join(baked),
            )
            return {'FINISHED'}

        self.report({'WARNING'}, "No driven shape keys found to bake")
        return {'CANCELLED'}


class CSK_OT_ClearBakedKeyframes(bpy.types.Operator):
    bl_idname = "corrective_sk.clear_baked"
    bl_label = "Clear Baked Keyframes"
    bl_description = (
        "Remove baked shape key keyframes (does not affect drivers)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.corrective_sk
        if not props.mesh_object:
            return False
        sk = props.mesh_object.data.shape_keys
        if not sk or not sk.animation_data or not sk.animation_data.action:
            return False
        return bool(sk.animation_data.action.fcurves)

    def execute(self, context):
        props = context.scene.corrective_sk
        sk = props.mesh_object.data.shape_keys
        action = sk.animation_data.action

        count = len(action.fcurves)
        for fc in list(action.fcurves):
            action.fcurves.remove(fc)

        self.report({'INFO'}, f"Cleared {count} baked shape key curve(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class CSK_PT_MainPanel(bpy.types.Panel):
    bl_idname = "CSK_PT_main_panel"
    bl_label = "Corrective Shape Key Drivers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Corrective SK"

    def draw(self, context):
        layout = self.layout
        props = context.scene.corrective_sk

        # --- Auto Run Python Scripts warning ---
        if not _auto_run_enabled():
            row = layout.row()
            row.alert = True
            row.label(text="Enable Auto Run Python Scripts!",
                      icon='ERROR')

        # --- Target Selection ---
        col = layout.column(align=True)
        col.prop(props, "mesh_object")
        if props.mesh_object and props.mesh_object.data.shape_keys:
            col.prop_search(
                props, "shape_key_name",
                props.mesh_object.data.shape_keys, "key_blocks",
                text="Shape Key",
            )

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "armature")
        if props.armature:
            col.prop_search(
                props, "bone_name",
                props.armature.pose, "bones",
                text="Bone",
            )

        layout.separator()
        layout.label(text="Axis:")
        layout.prop(props, "axis", expand=True)

        # --- Live Readout ---
        if (props.armature and props.bone_name
                and props.armature.pose.bones.get(props.bone_name)):
            bone = props.armature.pose.bones[props.bone_name]
            ax = int(props.axis)
            axis_name = ['X', 'Y', 'Z'][ax]

            layout.separator()
            box = layout.box()
            box.label(text="Live Bone Position", icon='BONE_DATA')
            col = box.column(align=True)
            col.label(text=f"Head ({axis_name}):  {bone.head[ax]:.4f}")
            col.label(text=f"Tail ({axis_name}):  {bone.tail[ax]:.4f}")
            col.label(text=f"Length:     {bone.length:.4f}")
            if bone.length > 0:
                norm = (bone.tail[ax] - bone.head[ax]) / bone.length
                col.label(text=f"Normalized: {norm:.4f}")

        # --- Control Points ---
        layout.separator()
        row = layout.row()
        row.label(text="Control Points:", icon='KEYFRAME')
        row.operator("corrective_sk.capture_point",
                      text="Capture", icon='ADD')

        if len(props.control_points) > 0:
            layout.template_list(
                "CSK_UL_control_points", "",
                props, "control_points",
                props, "active_point_index",
                rows=3,
            )
        elif (props.armature and props.bone_name
              and props.mesh_object and props.shape_key_name):
            col = layout.column()
            col.scale_y = 0.8
            col.label(text="Pose the bone, then click Capture",
                      icon='INFO')

        # --- Driver Buttons ---
        layout.separator()
        row = layout.row(align=True)
        row.operator("corrective_sk.generate_driver", icon='DRIVER')
        row.operator("corrective_sk.remove_driver", text="", icon='TRASH')

        layout.separator()
        layout.operator("corrective_sk.mirror_driver", icon='MOD_MIRROR')

        # --- Current Shape Key Value ---
        if props.mesh_object and props.shape_key_name:
            sk = props.mesh_object.data.shape_keys
            if sk and props.shape_key_name in sk.key_blocks:
                val = sk.key_blocks[props.shape_key_name].value
                layout.separator()
                box = layout.box()
                box.label(text=f"Current Value: {val:.4f}",
                          icon='SHAPEKEY_DATA')

        # --- Bake Section ---
        if props.mesh_object:
            sk = props.mesh_object.data.shape_keys
            has_drivers = (sk and sk.animation_data
                          and sk.animation_data.drivers)
            has_baked = (sk and sk.animation_data
                        and sk.animation_data.action
                        and sk.animation_data.action.fcurves)

            if has_drivers or has_baked:
                layout.separator()
                box = layout.box()
                box.label(text="Game Engine Export", icon='EXPORT')
                col = box.column(align=True)
                if has_drivers:
                    col.operator("corrective_sk.bake_drivers",
                                 icon='ACTION')
                if has_baked:
                    col.operator("corrective_sk.clear_baked",
                                 icon='CANCEL')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    CSK_ControlPoint,
    CSK_Properties,
    CSK_UL_ControlPointList,
    CSK_OT_CapturePoint,
    CSK_OT_RemovePoint,
    CSK_OT_RecapturePoint,
    CSK_OT_GenerateDriver,
    CSK_OT_RemoveDriver,
    CSK_OT_MirrorDriver,
    CSK_OT_BakeDrivers,
    CSK_OT_ClearBakedKeyframes,
    CSK_PT_MainPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.corrective_sk = PointerProperty(type=CSK_Properties)


def unregister():
    del bpy.types.Scene.corrective_sk
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
