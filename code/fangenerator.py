bl_info = {
    "name": "Table Fan Generator",
    "author": "Michel Anders",
    "version": (0, 0, 20261120015050),
    "blender": (5, 3, 0),
    "location": "View3D > Add > Mesh > Parametric Axial Fan",
    "description": "Generates a multi-blade NURBS axial fan with protective spiral/concentric cage, desk stand, PBR materials, and cyclic animation",
    "category": "Add Mesh",
}

import math

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

# ==============================================================================
# 1. NURBS BLADE & CENTRAL HUB BUILDERS
# ==============================================================================

def build_nurbs_blade(
    context,
    name,
    r_hub,
    r_tip,
    beta_hub_deg,
    beta_tip_deg,
    chord_root,
    chord_swell,
    camber,
    sweep_deg,
    thickness,
    n_u=14,
    n_v=8,
):
    surf_data = bpy.data.curves.new(name=name, type="SURFACE")
    surf_data.dimensions = "3D"
    surf_data.resolution_u = 24
    surf_data.resolution_v = 16

    # Overlap r_hub slightly so blade root embeds cleanly inside the hub
    r_start = max(0.001, r_hub - 0.0015)
    u_vals = np.linspace(0.0, 1.0, n_u)
    v_vals = np.linspace(-0.5, 0.5, n_v)

    for u in u_vals:
        r = r_start + u * (r_tip - r_start)
        chord = (chord_root + chord_swell * np.sin(np.pi * (u**0.75))) * np.sqrt(
            max(0.0, 1.0 - u**8)
        )
        beta = np.deg2rad(beta_hub_deg + u * (beta_tip_deg - beta_hub_deg))
        theta_sweep = np.deg2rad(sweep_deg) * (u**2)

        spline = surf_data.splines.new(type="NURBS")
        spline.points.add(n_v - 1)

        for j, v in enumerate(v_vals):
            z_camber = camber * (1.0 - 4.0 * v**2)
            s_local = v * chord * np.cos(beta) - z_camber * np.sin(beta)
            z_local = v * chord * np.sin(beta) + z_camber * np.cos(beta)

            theta = theta_sweep + s_local / r
            x = r * np.cos(theta)
            y = r * np.sin(theta)
            z = z_local

            spline.points[j].co = (float(x), float(y), float(z), 1.0)

        spline.use_endpoint_u = True
        spline.order_u = min(4, n_v)

    blade_obj = bpy.data.objects.new(name, surf_data)
    context.collection.objects.link(blade_obj)

    bpy.ops.object.select_all(action="DESELECT")
    blade_obj.select_set(True)
    context.view_layer.objects.active = blade_obj

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.select_all(action="SELECT")
    bpy.ops.curve.make_segment()

    for spline in blade_obj.data.splines:
        spline.use_endpoint_u = True
        spline.use_endpoint_v = True
        spline.order_u = min(4, n_v)
        spline.order_v = min(4, n_u)
        spline.use_smooth = True

    bpy.ops.object.mode_set(mode="OBJECT")

    if thickness > 0.0:
        mod = blade_obj.modifiers.new(name="BladeThickness", type="SOLIDIFY")
        mod.thickness = thickness
        mod.offset = 0.0

    return blade_obj


def build_central_hub(context, name, r_hub, hub_height):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=r_hub,
        depth=hub_height,
        end_fill_type="NGON",
        location=(0.0, 0.0, 0.0),
    )
    hub_obj = context.active_object
    hub_obj.name = name

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")

    for poly in hub_obj.data.polygons:
        if poly.normal.z > 0.9:
            poly.select = True

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.bevel(
        offset=min(r_hub * 0.28, hub_height * 0.35),
        segments=5,
        affect="EDGES",
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    for poly in hub_obj.data.polygons:
        poly.use_smooth = True

    return hub_obj


# ==============================================================================
# 2. PROTECTIVE CAGE / SHROUD BUILDER (CONCENTRIC & SPIRAL)
# ==============================================================================

def build_protective_cage(
    context,
    name,
    r_cage,
    r_badge,
    z_half_depth,
    dome_bulge,
    grille_style,
    num_spokes,
    num_rings,
    spiral_turns,
    spiral_twist_deg,
    wire_radius,
    rim_width,
):
    """Build a beveled curve wire cage (concentric or spiral) and solid outer rim band."""
    curve_data = bpy.data.curves.new(name=f"{name}_WireCurve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = wire_radius
    curve_data.bevel_resolution = 3
    curve_data.use_fill_caps = True

    def dome_z(r, side_sign):
        t = min(1.0, max(0.0, r / r_cage))
        bulge = dome_bulge * math.cos(0.5 * math.pi * t)
        return side_sign * (z_half_depth + bulge)

    r_inner = r_badge
    r_outer = r_cage - wire_radius
    spoke_angles = np.linspace(0.0, 2.0 * math.pi, num_spokes, endpoint=False)
    n_circle_pts = 72
    n_spoke_pts = 24

    for side_sign in (1.0, -1.0):
        # Outer boundary retaining ring
        outer_ring = curve_data.splines.new(type="POLY")
        outer_ring.use_cyclic_u = True
        outer_ring.points.add(n_circle_pts - 1)
        z_rim = dome_z(r_outer, side_sign)
        for idx in range(n_circle_pts):
            ang = (2.0 * math.pi * idx) / n_circle_pts
            outer_ring.points[idx].co = (
                float(r_outer * math.cos(ang)),
                float(r_outer * math.sin(ang)),
                float(z_rim),
                1.0,
            )

        if grille_style == "CONCENTRIC":
            ring_radii = np.linspace(r_inner, r_outer, num_rings, endpoint=False)
            for rr in ring_radii:
                spline = curve_data.splines.new(type="POLY")
                spline.use_cyclic_u = True
                spline.points.add(n_circle_pts - 1)
                z_val = dome_z(rr, side_sign)
                for idx in range(n_circle_pts):
                    ang = (2.0 * math.pi * idx) / n_circle_pts
                    spline.points[idx].co = (
                        float(rr * math.cos(ang)),
                        float(rr * math.sin(ang)),
                        float(z_val),
                        1.0,
                    )
            twist_rad = 0.0
        else:
            # Continuous Archimedean spiral from badge edge to outer rim
            total_theta = 2.0 * math.pi * spiral_turns
            n_spiral_pts = max(72, int(spiral_turns * 48))
            thetas = np.linspace(0.0, total_theta, n_spiral_pts)
            radii = r_inner + (thetas / total_theta) * (r_outer - r_inner)

            spline = curve_data.splines.new(type="POLY")
            spline.points.add(n_spiral_pts - 1)
            for idx, (ang, rs) in enumerate(zip(thetas, radii)):
                spline.points[idx].co = (
                    float(rs * math.cos(ang)),
                    float(rs * math.sin(ang)),
                    float(dome_z(rs, side_sign)),
                    1.0,
                )
            twist_rad = math.radians(spiral_twist_deg)

        # Radial / vortex support ribs from badge edge to outer rim
        t_samples = np.linspace(0.0, 1.0, n_spoke_pts)
        for base_ang in spoke_angles:
            spline = curve_data.splines.new(type="POLY")
            spline.points.add(n_spoke_pts - 1)
            for idx, t in enumerate(t_samples):
                rs = r_inner + t * (r_outer - r_inner)
                ang = base_ang + twist_rad * (t**1.3)
                spline.points[idx].co = (
                    float(rs * math.cos(ang)),
                    float(rs * math.sin(ang)),
                    float(dome_z(rs, side_sign)),
                    1.0,
                )

    # Axial side struts bridging front and rear outer rings
    for ang in spoke_angles:
        ca, sa = math.cos(ang), math.sin(ang)
        spline = curve_data.splines.new(type="POLY")
        spline.points.add(1)
        spline.points[0].co = (
            float(r_outer * ca),
            float(r_outer * sa),
            float(-z_half_depth),
            1.0,
        )
        spline.points[1].co = (
            float(r_outer * ca),
            float(r_outer * sa),
            float(z_half_depth),
            1.0,
        )

    wire_obj = bpy.data.objects.new(f"{name}_Grille", curve_data)
    context.collection.objects.link(wire_obj)

    # Outer shroud rim band
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=72,
        radius=r_cage + wire_radius * 0.5,
        depth=rim_width,
        end_fill_type="NOTHING",
        location=(0.0, 0.0, 0.0),
    )
    rim_obj = context.active_object
    rim_obj.name = f"{name}_RimBand"
    for poly in rim_obj.data.polygons:
        poly.use_smooth = True

    sol = rim_obj.modifiers.new(name="RimThickness", type="SOLIDIFY")
    sol.thickness = max(wire_radius * 2.2, 0.002)
    sol.offset = 0.0

    # Front center badge cap
    z_front_center = dome_z(0.0, 1.0)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=r_badge,
        depth=wire_radius * 2.5,
        end_fill_type="NGON",
        location=(0.0, 0.0, z_front_center),
    )
    badge_obj = context.active_object
    badge_obj.name = f"{name}_CenterBadge"
    for poly in badge_obj.data.polygons:
        poly.use_smooth = True

    return wire_obj, rim_obj, badge_obj


# ==============================================================================
# 3. DESK STAND & MOTOR HOUSING BUILDER
# ==============================================================================

def build_stand_and_motor(
    context,
    name,
    r_hub,
    r_cage,
    z_rear_cage,
    motor_length,
    stand_height,
    base_radius,
    base_height,
    tilt_deg,
):
    """Build motor housing pod, oscillation knob, tilt neck, and desk base (+Z up, -Y front)."""
    created_parts = []

    # Pivot Empty at the tilt joint beneath the motor housing
    pivot_z = -r_cage * 0.28
    pivot_y = z_rear_cage + motor_length * 0.35
    head_pivot = bpy.data.objects.new(f"{name}_HeadTiltPivot", None)
    head_pivot.empty_display_type = "SINGLE_ARROW"
    head_pivot.empty_display_size = r_hub * 0.8
    head_pivot.location = (0.0, pivot_y, pivot_z)
    head_pivot.rotation_euler = (math.radians(tilt_deg), 0.0, 0.0)
    context.collection.objects.link(head_pivot)
    created_parts.append(head_pivot)

    # 1. Rear Motor Housing Pod (aligned along Y axis behind rear cage)
    motor_radius = r_hub * 1.12
    motor_center_y = z_rear_cage + motor_length * 0.5
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=motor_radius,
        depth=motor_length,
        end_fill_type="NGON",
        location=(0.0, motor_center_y, 0.0),
        rotation=(math.radians(90.0), 0.0, 0.0),
    )
    motor_obj = context.active_object
    motor_obj.name = f"{name}_MotorHousing"

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in motor_obj.data.polygons:
        if poly.normal.y > 0.9:
            poly.select = True
    bpy.ops.object.mode_set(mode="EDIT")
    # bpy.ops.mesh.select_mode(type='FACE')
    # note sure what was the intention of this, but it doesn bevel anything properly
    # bpy.ops.mesh.bevel(
    #     offset=min(motor_radius * 0.45, motor_length * 0.4),
    #     segments=6,
    #     affect="EDGES",
    # )
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in motor_obj.data.polygons:
        poly.use_smooth = True
    created_parts.append(motor_obj)

    # 2. Oscillation Clutch Knob on top of motor pod
    knob_y = z_rear_cage + motor_length * 0.65
    knob_z = motor_radius + r_hub * 0.16
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=24,
        radius=r_hub * 0.16,
        depth=r_hub * 0.35,
        location=(0.0, knob_y, knob_z),
    )
    knob_obj = context.active_object
    knob_obj.name = f"{name}_OscillationKnob"
    for poly in knob_obj.data.polygons:
        poly.use_smooth = True
    created_parts.append(knob_obj)

    # 3. Tilt Neck Bracket connecting motor pod to pivot joint
    neck_r = r_hub * 0.28
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=neck_r,
        depth=abs(pivot_z) + motor_radius * 0.5,
        location=(0.0, pivot_y, pivot_z * 0.5),
    )
    upper_neck = context.active_object
    upper_neck.name = f"{name}_TiltBracket"
    for poly in upper_neck.data.polygons:
        poly.use_smooth = True
    created_parts.append(upper_neck)

    # 4. Vertical Support Column (from pivot down to base)
    z_base_top = -stand_height + base_height
    col_height = max(0.02, pivot_z - z_base_top)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=36,
        radius=neck_r * 1.15,
        depth=col_height,
        location=(0.0, pivot_y, z_base_top + col_height * 0.5),
    )
    column_obj = context.active_object
    column_obj.name = f"{name}_StandColumn"
    for poly in column_obj.data.polygons:
        poly.use_smooth = True
    created_parts.append(column_obj)

    # 5. Weighted Desk Base
    base_y = pivot_y - base_radius * 0.25
    base_z = -stand_height + base_height * 0.5
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=base_radius,
        depth=base_height,
        end_fill_type="NGON",
        location=(0.0, base_y, base_z),
    )
    base_obj = context.active_object
    base_obj.name = f"{name}_DeskBase"

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in base_obj.data.polygons:
        if poly.normal.z > 0.9:
            poly.select = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.bevel(
        offset=min(base_height * 0.45, base_radius * 0.12),
        segments=5,
        affect="EDGES",
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in base_obj.data.polygons:
        poly.use_smooth = True
    created_parts.append(base_obj)

    # 6. Four Speed Control Push-Buttons on front of base (0, 1, 2, 3)
    btn_spacing = base_radius * 0.22
    btn_y = base_y - base_radius * 0.58
    btn_z = -stand_height + base_height
    for i in range(4):
        btn_x = (i - 1.5) * btn_spacing
        btn_h = base_height * (0.22 if i == 1 else 0.35)
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(btn_x, btn_y, btn_z + btn_h * 0.35),
        )
        btn = context.active_object
        btn.name = f"{name}_SpeedButton_{i}"
        btn.scale = (btn_spacing * 0.55, btn_spacing * 0.85, btn_h)
        bpy.ops.object.transform_apply(scale=True)
        created_parts.append(btn)

    return head_pivot, motor_obj, knob_obj, upper_neck, column_obj, base_obj, created_parts


# ==============================================================================
# 4. PBR MATERIALS & ANIMATION HELPERS
# ==============================================================================

def _set_bsdf_input(bsdf, names, value):
    """Safely set a Principled BSDF input across Blender 3.x and 4.x+ socket names."""
    for n in names:
        if n in bsdf.inputs:
            bsdf.inputs[n].default_value = value
            return


def create_fan_materials(preset="CLASSIC_WHITE"):
    """Create or update PBR materials for blades, wire grille, body housing, and accents."""
    presets = {
        "CLASSIC_WHITE": {
            "blade_color": (0.72, 0.86, 0.96, 1.0),
            "blade_roughness": 0.14,
            "blade_transmission": 0.78,
            "body_color": (0.88, 0.89, 0.91, 1.0),
            "body_roughness": 0.32,
            "metal_color": (0.86, 0.88, 0.90, 1.0),
            "metal_roughness": 0.18,
            "accent_color": (0.12, 0.13, 0.15, 1.0),
        },
        "RETRO_TEAL": {
            "blade_color": (0.82, 0.78, 0.68, 1.0),
            "blade_roughness": 0.22,
            "blade_transmission": 0.0,
            "body_color": (0.14, 0.42, 0.43, 1.0),
            "body_roughness": 0.28,
            "metal_color": (0.88, 0.68, 0.34, 1.0),
            "metal_roughness": 0.24,
            "accent_color": (0.85, 0.82, 0.74, 1.0),
        },
        "MATTE_BLACK": {
            "blade_color": (0.04, 0.04, 0.05, 1.0),
            "blade_roughness": 0.26,
            "blade_transmission": 0.0,
            "body_color": (0.05, 0.05, 0.06, 1.0),
            "body_roughness": 0.42,
            "metal_color": (0.22, 0.23, 0.25, 1.0),
            "metal_roughness": 0.30,
            "accent_color": (0.75, 0.15, 0.12, 1.0),
        },
        "SMOKED_BLUE": {
            "blade_color": (0.08, 0.24, 0.52, 1.0),
            "blade_roughness": 0.10,
            "blade_transmission": 0.85,
            "body_color": (0.16, 0.18, 0.21, 1.0),
            "body_roughness": 0.30,
            "metal_color": (0.82, 0.84, 0.87, 1.0),
            "metal_roughness": 0.15,
            "accent_color": (0.15, 0.45, 0.85, 1.0),
        },
    }
    cfg = presets.get(preset, presets["CLASSIC_WHITE"])

    def get_or_create_mat(mat_name):
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        out = nodes.new(type="ShaderNodeOutputMaterial")
        out.location = (300, 0)
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        return mat, bsdf

    mat_blade, bsdf_blade = get_or_create_mat(f"FanMat_Blades_{preset}")
    _set_bsdf_input(bsdf_blade, ["Base Color"], cfg["blade_color"])
    _set_bsdf_input(bsdf_blade, ["Roughness"], cfg["blade_roughness"])
    _set_bsdf_input(bsdf_blade, ["IOR"], 1.49)
    _set_bsdf_input(bsdf_blade, ["Transmission Weight", "Transmission"], cfg["blade_transmission"])
    _set_bsdf_input(bsdf_blade, ["Coat Weight", "Clearcoat"], 0.35)

    mat_metal, bsdf_metal = get_or_create_mat(f"FanMat_MetalGrille_{preset}")
    _set_bsdf_input(bsdf_metal, ["Base Color"], cfg["metal_color"])
    _set_bsdf_input(bsdf_metal, ["Metallic"], 1.0)
    _set_bsdf_input(bsdf_metal, ["Roughness"], cfg["metal_roughness"])

    mat_body, bsdf_body = get_or_create_mat(f"FanMat_ABSBody_{preset}")
    _set_bsdf_input(bsdf_body, ["Base Color"], cfg["body_color"])
    _set_bsdf_input(bsdf_body, ["Roughness"], cfg["body_roughness"])
    _set_bsdf_input(bsdf_body, ["Coat Weight", "Clearcoat"], 0.15)

    mat_accent, bsdf_accent = get_or_create_mat(f"FanMat_Accent_{preset}")
    _set_bsdf_input(bsdf_accent, ["Base Color"], cfg["accent_color"])
    _set_bsdf_input(bsdf_accent, ["Roughness"], 0.25)

    return {
        "blade": mat_blade,
        "metal": mat_metal,
        "body": mat_body,
        "accent": mat_accent,
    }


def assign_material(obj, mat):
    if obj is None or obj.data is None:
        return
    if len(obj.data.materials) == 0:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat


def _iter_action_fcurves(animated_object):
    animation_data = animated_object.animation_data
    if animation_data is None or animation_data.action is None:
        return

    action = animation_data.action
    if hasattr(action, "fcurves"):
        yield from action.fcurves
        return

    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            channelbag = strip.channelbag(animation_data.action_slot)
            if channelbag is not None:
                yield from channelbag.fcurves


def setup_fan_animation(
    context,
    rotor_empty,
    head_pivot,
    rpm=180.0,
    oscillate=True,
    osc_angle_deg=50.0,
    osc_period_sec=6.0,
):
    """Add endless F-curve spin to the rotor and smooth cyclic oscillation to the head pivot."""
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base

    # 1. Continuous Rotor Spin (around local Z-axis)
    rev_per_sec = rpm / 60.0
    frames_per_rev = max(2.0, fps / max(0.01, rev_per_sec))

    rotor_empty.rotation_mode = "XYZ"
    rotor_empty.rotation_euler = (0.0, 0.0, 0.0)
    rotor_empty.keyframe_insert(data_path="rotation_euler", index=2, frame=1)

    rotor_empty.rotation_euler = (0.0, 0.0, -2.0 * math.pi)
    rotor_empty.keyframe_insert(data_path="rotation_euler", index=2, frame=1 + frames_per_rev)

    for fcurve in _iter_action_fcurves(rotor_empty):
        if fcurve.data_path == "rotation_euler" and fcurve.array_index == 2:
            for kp in fcurve.keyframe_points:
                kp.interpolation = "LINEAR"
            mod = fcurve.modifiers.new(type="CYCLES")
            mod.mode_before = "REPEAT_OFFSET"
            mod.mode_after = "REPEAT_OFFSET"

    # 2. Smooth Head Oscillation (around Z yaw axis)
    if oscillate and head_pivot is not None:
        head_pivot.rotation_mode = "XYZ"
        tilt_x = head_pivot.rotation_euler.x
        half_swing = math.radians(osc_angle_deg * 0.5)
        half_period_frames = max(10.0, (osc_period_sec * fps) * 0.5)

        keyframes = [
            (1.0, 0.0),
            (1.0 + half_period_frames * 0.5, half_swing),
            (1.0 + half_period_frames * 1.5, -half_swing),
            (1.0 + half_period_frames * 2.0, 0.0),
        ]

        for frame_num, yaw_z in keyframes:
            head_pivot.rotation_euler = (tilt_x, 0.0, yaw_z)
            head_pivot.keyframe_insert(data_path="rotation_euler", index=2, frame=frame_num)

        for fcurve in _iter_action_fcurves(head_pivot):
            if fcurve.data_path == "rotation_euler" and fcurve.array_index == 2:
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "BEZIER"
                    kp.handle_left_type = "AUTO_CLAMPED"
                    kp.handle_right_type = "AUTO_CLAMPED"
                mod = fcurve.modifiers.new(type="CYCLES")
                mod.mode_before = "REPEAT"
                mod.mode_after = "REPEAT"


# ==============================================================================
# 5. MAIN OPERATOR & UI
# ==============================================================================

class MESH_OT_add_parametric_fan(bpy.types.Operator):
    """Create a complete parametric axial table fan assembly"""

    bl_idname = "mesh.add_parametric_fan"
    bl_label = "Parametric Axial Fan"
    bl_options = {"REGISTER", "UNDO"}

    # --- Rotor & Hub Dimensions ---
    blade_count: EnumProperty(
        name="Blades",
        description="Number of fan blades",
        items=[
            ("3", "3 Blades", "Standard 3-blade rotor"),
            ("4", "4 Blades", "4-blade rotor"),
            ("5", "5 Blades", "5-blade quiet rotor"),
        ],
        default="3",
    ) # type: ignore

    fan_diameter: FloatProperty(
        name="Fan Diameter",
        description="Outer tip-to-tip diameter of the fan",
        default=0.30,
        min=0.05,
        max=5.0,
        unit="LENGTH",
    ) # type: ignore

    hub_diameter: FloatProperty(
        name="Hub Diameter",
        description="Diameter of the central motor hub",
        default=0.07,
        min=0.01,
        max=2.5,
        unit="LENGTH",
    ) # type: ignore

    hub_height: FloatProperty(
        name="Hub Height",
        description="Axial length of the central hub",
        default=0.045,
        min=0.005,
        max=1.0,
        unit="LENGTH",
    ) # type: ignore

    # --- Blade Geometry ---
    beta_hub: FloatProperty(
        name="Hub Pitch (deg)",
        description="Blade pitch angle near the hub",
        default=42.0,
        min=5.0,
        max=75.0,
    ) # type: ignore

    beta_tip: FloatProperty(
        name="Tip Pitch (deg)",
        description="Blade pitch angle at the outer tip",
        default=18.0,
        min=2.0,
        max=60.0,
    ) # type: ignore

    chord_ratio: FloatProperty(
        name="Blade Width Scale",
        description="Multiplier for blade chord width",
        default=1.0,
        min=0.3,
        max=2.5,
    ) # type: ignore

    camber: FloatProperty(
        name="Blade Cupping (Camber)",
        description="Parabolic camber depth across blade chord",
        default=0.008,
        min=0.0,
        max=0.05,
        unit="LENGTH",
    ) # type: ignore

    sweep_deg: FloatProperty(
        name="Sweep Angle (deg)",
        description="Backward/forward rotational sweep at the tip",
        default=15.0,
        min=-45.0,
        max=45.0,
    ) # type: ignore

    blade_thickness: FloatProperty(
        name="Blade Thickness",
        description="Solidify thickness applied to each NURBS blade",
        default=0.0022,
        min=0.0,
        max=0.02,
        unit="LENGTH",
    ) # type: ignore

    convert_to_mesh: BoolProperty(
        name="Convert Blades to Mesh",
        description="Keep blades as live NURBS surfaces or convert to polygon meshes",
        default=False,
    ) # type: ignore

    # --- Protective Cage / Shroud Settings ---
    include_cage: BoolProperty(
        name="Include Protective Cage",
        description="Generate a protective front/rear wire grille and outer shroud rim",
        default=True,
    ) # type: ignore

    grille_style: EnumProperty(
        name="Grille Style",
        description="Wire pattern for the front and rear safety grilles",
        items=[
            ("SPIRAL", "Continuous Spiral", "Vortex/Archimedean spiral wire grille"),
            ("CONCENTRIC", "Concentric Rings", "Classic parallel circular rings"),
        ],
        default="SPIRAL",
    ) # type: ignore

    tip_clearance: FloatProperty(
        name="Cage Tip Clearance",
        description="Radial gap between blade tips and protective cage",
        default=0.015,
        min=0.002,
        max=0.25,
        unit="LENGTH",
    ) # type: ignore

    cage_depth: FloatProperty(
        name="Cage Axial Depth",
        description="Axial spacing between front and rear grille rims",
        default=0.075,
        min=0.02,
        max=1.0,
        unit="LENGTH",
    ) # type: ignore

    cage_dome: FloatProperty(
        name="Cage Dome Bulge",
        description="Outward curvature depth of the front and rear grilles",
        default=0.018,
        min=0.0,
        max=0.25,
        unit="LENGTH",
    ) # type: ignore

    cage_spokes: IntProperty(
        name="Radial Spokes",
        description="Number of radial support ribs on the cage",
        default=12,
        min=4,
        max=48,
    ) # type: ignore

    cage_rings: IntProperty(
        name="Concentric Rings",
        description="Number of concentric safety wire rings per side",
        default=14,
        min=3,
        max=60,
    ) # type: ignore

    spiral_turns: FloatProperty(
        name="Spiral Turns",
        description="Number of full revolutions from center badge to outer rim",
        default=12.0,
        min=2.0,
        max=50.0,
    ) # type: ignore

    spiral_twist_deg: FloatProperty(
        name="Spoke Twist (deg)",
        description="Curved vortex twist applied to the radial support ribs",
        default=35.0,
        min=-120.0,
        max=120.0,
    ) # type: ignore

    wire_diameter: FloatProperty(
        name="Wire Diameter",
        description="Thickness of the protective grille wires",
        default=0.0022,
        min=0.0005,
        max=0.02,
        unit="LENGTH",
    ) # type: ignore

    rim_width: FloatProperty(
        name="Shroud Rim Width",
        description="Axial width of the outer retaining ring band",
        default=0.024,
        min=0.002,
        max=0.3,
        unit="LENGTH",
    ) # type: ignore

    # --- Desk Stand & Motor Housing Settings ---
    include_stand: BoolProperty(
        name="Include Desk Stand & Motor",
        description="Add rear motor pod, tilt neck, and weighted table base",
        default=True,
    ) # type: ignore

    motor_length: FloatProperty(
        name="Motor Housing Length",
        description="Depth of the rear motor pod behind the cage",
        default=0.095,
        min=0.02,
        max=0.6,
        unit="LENGTH",
    ) # type: ignore

    stand_height: FloatProperty(
        name="Center-to-Desk Height",
        description="Height from the desk surface to the rotor center",
        default=0.28,
        min=0.10,
        max=2.0,
        unit="LENGTH",
    ) # type: ignore

    base_diameter: FloatProperty(
        name="Base Diameter",
        description="Diameter of the circular desk stand foot",
        default=0.20,
        min=0.06,
        max=1.5,
        unit="LENGTH",
    ) # type: ignore

    base_height: FloatProperty(
        name="Base Thickness",
        description="Height of the weighted desk base",
        default=0.026,
        min=0.005,
        max=0.2,
        unit="LENGTH",
    ) # type: ignore

    tilt_angle: FloatProperty(
        name="Head Tilt Angle (deg)",
        description="Upward/downward pitch tilt of the fan head",
        default=8.0,
        min=-30.0,
        max=45.0,
    ) # type: ignore

    # --- PBR Material Settings ---
    assign_materials: BoolProperty(
        name="Auto-Assign PBR Materials",
        description="Assign realistic Principled BSDF materials to all fan components",
        default=True,
    ) # type: ignore

    material_preset: EnumProperty(
        name="Color Theme",
        description="Preconfigured material and finish palette",
        items=[
            ("CLASSIC_WHITE", "Classic White & Chrome", "White ABS housing, chrome grille, translucent ice blades"),
            ("RETRO_TEAL", "Retro Teal & Brass", "Vintage teal enamel body, brushed brass grille, cream blades"),
            ("MATTE_BLACK", "Stealth Matte Black", "Matte black housing, gunmetal grille, red accent buttons"),
            ("SMOKED_BLUE", "Smoked Translucent Blue", "Dark charcoal housing, chrome grille, deep blue acrylic blades"),
        ],
        default="CLASSIC_WHITE",
    ) # type: ignore

    # --- Animation Settings ---
    animate_fan: BoolProperty(
        name="Enable Spin & Oscillation Animation",
        description="Keyframes continuous rotor spin and cyclic head oscillation",
        default=False,
    ) # type: ignore

    fan_rpm: FloatProperty(
        name="Rotor Speed (RPM)",
        description="Rotations per minute (120-240 for viewport preview, 900+ for motion blur)",
        default=180.0,
        min=10.0,
        max=3000.0,
    ) # type: ignore

    enable_oscillation: BoolProperty(
        name="Oscillate Head",
        description="Sweep the fan head side-to-side smoothly",
        default=True,
    ) # type: ignore

    oscillation_angle: FloatProperty(
        name="Oscillation Sweep (deg)",
        description="Total side-to-side sweep angle",
        default=50.0,
        min=10.0,
        max=140.0,
    ) # type: ignore

    oscillation_period: FloatProperty(
        name="Oscillation Cycle (sec)",
        description="Seconds for one complete left-right-center sweep",
        default=6.0,
        min=1.0,
        max=30.0,
    ) # type: ignore

    def draw(self, context):
        layout = self.layout

        box_rotor = layout.box()
        box_rotor.label(text="Rotor & Hub Dimensions", icon="FORCE_VORTEX")
        box_rotor.prop(self, "blade_count")
        box_rotor.prop(self, "fan_diameter")
        box_rotor.prop(self, "hub_diameter")
        box_rotor.prop(self, "hub_height")

        box_aero = layout.box()
        box_aero.label(text="Blade Geometry", icon="SURFACE_NSURFACE")
        box_aero.prop(self, "beta_hub")
        box_aero.prop(self, "beta_tip")
        box_aero.prop(self, "chord_ratio")
        box_aero.prop(self, "camber")
        box_aero.prop(self, "sweep_deg")
        box_aero.prop(self, "blade_thickness")
        box_aero.prop(self, "convert_to_mesh")

        box_cage = layout.box()
        box_cage.prop(self, "include_cage", icon="MESH_CIRCLE")
        if self.include_cage:
            box_cage.prop(self, "grille_style")
            box_cage.prop(self, "tip_clearance")
            box_cage.prop(self, "cage_depth")
            box_cage.prop(self, "cage_dome")
            box_cage.prop(self, "cage_spokes")
            if self.grille_style == "CONCENTRIC":
                box_cage.prop(self, "cage_rings")
            else:
                box_cage.prop(self, "spiral_turns")
                box_cage.prop(self, "spiral_twist_deg")
            box_cage.prop(self, "wire_diameter")
            box_cage.prop(self, "rim_width")

        box_stand = layout.box()
        box_stand.prop(self, "include_stand", icon="ANCHOR_BOTTOM")
        if self.include_stand:
            box_stand.prop(self, "motor_length")
            box_stand.prop(self, "stand_height")
            box_stand.prop(self, "base_diameter")
            box_stand.prop(self, "base_height")
            box_stand.prop(self, "tilt_angle")

        box_mat = layout.box()
        box_mat.prop(self, "assign_materials", icon="MATERIAL")
        if self.assign_materials:
            box_mat.prop(self, "material_preset")

        box_anim = layout.box()
        box_anim.prop(self, "animate_fan", icon="PLAY")
        if self.animate_fan:
            box_anim.prop(self, "fan_rpm")
            if self.include_stand:
                box_anim.prop(self, "enable_oscillation")
                if self.enable_oscillation:
                    box_anim.prop(self, "oscillation_angle")
                    box_anim.prop(self, "oscillation_period")

    def execute(self, context):
        n_blades = int(self.blade_count)
        r_tip = self.fan_diameter * 0.5
        r_hub = min(self.hub_diameter * 0.5, r_tip * 0.85)

        scale_factor = r_tip / 0.15
        chord_root = 0.045 * scale_factor * self.chord_ratio
        chord_swell = 0.065 * scale_factor * self.chord_ratio

        # Root container Empty
        root_empty = bpy.data.objects.new(f"AxialFan_{n_blades}Blade", None)
        root_empty.empty_display_type = "PLAIN_AXES"
        root_empty.empty_display_size = r_hub * 1.2
        context.collection.objects.link(root_empty)

        # Sub-container for the fan head (rotor + cage)
        fan_head_empty = bpy.data.objects.new("FanHead_Assembly", None)
        fan_head_empty.empty_display_type = "PLAIN_AXES"
        fan_head_empty.empty_display_size = r_hub
        context.collection.objects.link(fan_head_empty)
        fan_head_empty.parent = root_empty

        # Dedicated spinning sub-container for hub + blades (keeps cage stationary)
        rotor_spin_empty = bpy.data.objects.new("Rotor_SpinPivot", None)
        rotor_spin_empty.empty_display_type = "CIRCLE"
        rotor_spin_empty.empty_display_size = r_hub * 1.1
        context.collection.objects.link(rotor_spin_empty)
        rotor_spin_empty.parent = fan_head_empty

        # Build central hub
        hub_obj = build_central_hub(
            context, f"FanHub_{n_blades}Blade", r_hub, self.hub_height
        )
        hub_obj.parent = rotor_spin_empty

        # Build master NURBS blade
        master_blade = build_nurbs_blade(
            context=context,
            name="FanBlade_01",
            r_hub=r_hub,
            r_tip=r_tip,
            beta_hub_deg=self.beta_hub,
            beta_tip_deg=self.beta_tip,
            chord_root=chord_root,
            chord_swell=chord_swell,
            camber=self.camber * scale_factor,
            sweep_deg=self.sweep_deg,
            thickness=self.blade_thickness,
        )
        master_blade.parent = rotor_spin_empty

        blades = [master_blade]

        for i in range(1, n_blades):
            angle = (2.0 * math.pi * i) / n_blades
            blade_copy = master_blade.copy()
            blade_copy.name = f"FanBlade_{i + 1:02d}"
            blade_copy.rotation_euler = (0.0, 0.0, angle)
            context.collection.objects.link(blade_copy)
            blade_copy.parent = rotor_spin_empty
            blades.append(blade_copy)

        if self.convert_to_mesh:
            bpy.ops.object.select_all(action="DESELECT")
            for b in blades:
                b.select_set(True)
            context.view_layer.objects.active = master_blade
            bpy.ops.object.convert(target="MESH")

        # Build protective cage / shroud
        cage_parts = ()
        if self.include_cage:
            r_cage = r_tip + self.tip_clearance
            r_badge = min(r_hub * 0.95, r_cage * 0.35)
            z_half = max(self.cage_depth * 0.5, self.hub_height * 0.55)

            cage_parts = build_protective_cage(
                context=context,
                name="FanCage",
                r_cage=r_cage,
                r_badge=r_badge,
                z_half_depth=z_half,
                dome_bulge=self.cage_dome,
                grille_style=self.grille_style,
                num_spokes=self.cage_spokes,
                num_rings=self.cage_rings,
                spiral_turns=self.spiral_turns,
                spiral_twist_deg=self.spiral_twist_deg,
                wire_radius=self.wire_diameter * 0.5,
                rim_width=self.rim_width,
            )
            for part in cage_parts:
                part.parent = fan_head_empty

        # Build desk stand & motor housing
        head_pivot = None
        if self.include_stand:
            fan_head_empty.rotation_euler = (math.radians(90.0), 0.0, 0.0)

            r_cage = r_tip + self.tip_clearance
            z_half = max(self.cage_depth * 0.5, self.hub_height * 0.55)
            z_rear_cage = z_half + (self.cage_dome if self.include_cage else 0.0)
            eff_stand_height = max(self.stand_height, r_cage + self.base_height + 0.015)

            (
                head_pivot,
                motor_obj,
                knob_obj,
                upper_neck,
                column_obj,
                base_obj,
                all_stand_parts,
            ) = build_stand_and_motor(
                context=context,
                name="FanStand",
                r_hub=r_hub,
                r_cage=r_cage,
                z_rear_cage=z_rear_cage,
                motor_length=self.motor_length,
                stand_height=eff_stand_height,
                base_radius=self.base_diameter * 0.5,
                base_height=self.base_height,
                tilt_deg=self.tilt_angle,
            )

            for part in all_stand_parts:
                part.parent = root_empty

            for tilt_part in (fan_head_empty, motor_obj, knob_obj, upper_neck):
                mat_world = tilt_part.matrix_world.copy()
                tilt_part.parent = head_pivot
                tilt_part.matrix_world = mat_world

        # Auto-assign PBR materials
        if self.assign_materials:
            mats = create_fan_materials(self.material_preset)

            for b in blades:
                assign_material(b, mats["blade"])
            assign_material(hub_obj, mats["body"])

            if self.include_cage:
                wire_obj, rim_obj, badge_obj = cage_parts
                assign_material(wire_obj, mats["metal"])
                assign_material(rim_obj, mats["body"])
                assign_material(badge_obj, mats["accent"])

            if self.include_stand:
                assign_material(motor_obj, mats["body"])
                assign_material(upper_neck, mats["body"])
                assign_material(column_obj, mats["metal"])
                assign_material(base_obj, mats["body"])
                assign_material(knob_obj, mats["accent"])
                for part in all_stand_parts:
                    if "SpeedButton" in part.name:
                        assign_material(part, mats["accent"])

        # Setup cyclic spin & oscillation animation
        if self.animate_fan:
            setup_fan_animation(
                context=context,
                rotor_empty=rotor_spin_empty,
                head_pivot=head_pivot if self.include_stand else None,
                rpm=self.fan_rpm,
                oscillate=self.enable_oscillation and self.include_stand,
                osc_angle_deg=self.oscillation_angle,
                osc_period_sec=self.oscillation_period,
            )

        bpy.ops.object.select_all(action="DESELECT")
        root_empty.select_set(True)
        context.view_layer.objects.active = root_empty

        return {"FINISHED"}


def menu_func(self, context):
    self.layout.operator(
        MESH_OT_add_parametric_fan.bl_idname,
        text="Parametric Axial Fan",
        icon="FORCE_VORTEX",
    )


def register():
    bpy.utils.register_class(MESH_OT_add_parametric_fan)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)
    bpy.utils.unregister_class(MESH_OT_add_parametric_fan)


if __name__ == "__main__":
    register()
