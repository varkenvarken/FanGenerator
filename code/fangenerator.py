bl_info = {
    "name": "Parametric Axial Fan Generator",
    "author": "Michel Anders",
    "version": (0, 0, 20261120103718),
    "blender": (5, 3, 0),
    "location": "View3D > Add > Mesh > Parametric Axial Fan",
    "description": "Generates a multi-blade NURBS axial fan rotor with a central hub",
    "category": "Add Mesh",
}

import math

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty


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

    # Slightly overlap r_hub by 1.5 mm so the blade roots cleanly inside the hub
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

    # Add a subtle nose bevel on the front (+Z) face for a realistic spinner cap
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

    # Smooth shading
    for poly in hub_obj.data.polygons:
        poly.use_smooth = True

    return hub_obj


class MESH_OT_add_parametric_fan(bpy.types.Operator):
    """Create a parametric multi-blade NURBS axial fan with central hub"""

    bl_idname = "mesh.add_parametric_fan"
    bl_label = "Parametric Axial Fan"
    bl_options = {"REGISTER", "UNDO"}

    blade_count: EnumProperty(
        name="Blades",
        description="Number of fan blades",
        items=[
            ("3", "3 Blades", "Standard 3-blade rotor"),
            ("4", "4 Blades", "4-blade rotor"),
            ("5", "5 Blades", "5-blade quiet rotor"),
        ],
        default="3",
    )

    fan_diameter: FloatProperty(
        name="Fan Diameter",
        description="Outer tip-to-tip diameter of the fan",
        default=0.30,
        min=0.05,
        max=5.0,
        unit="LENGTH",
    )

    hub_diameter: FloatProperty(
        name="Hub Diameter",
        description="Diameter of the central motor hub",
        default=0.07,
        min=0.01,
        max=2.5,
        unit="LENGTH",
    )

    hub_height: FloatProperty(
        name="Hub Height",
        description="Axial length of the central hub",
        default=0.045,
        min=0.005,
        max=1.0,
        unit="LENGTH",
    )

    beta_hub: FloatProperty(
        name="Hub Pitch (deg)",
        description="Blade pitch angle near the hub",
        default=42.0,
        min=5.0,
        max=75.0,
    )

    beta_tip: FloatProperty(
        name="Tip Pitch (deg)",
        description="Blade pitch angle at the outer tip",
        default=18.0,
        min=2.0,
        max=60.0,
    )

    chord_ratio: FloatProperty(
        name="Blade Width Scale",
        description="Multiplier for blade chord width",
        default=1.0,
        min=0.3,
        max=2.5,
    )

    camber: FloatProperty(
        name="Blade Cupping (Camber)",
        description="Parabolic camber depth across blade chord",
        default=0.008,
        min=0.0,
        max=0.05,
        unit="LENGTH",
    )

    sweep_deg: FloatProperty(
        name="Sweep Angle (deg)",
        description="Backward/forward rotational sweep at the tip",
        default=15.0,
        min=-45.0,
        max=45.0,
    )

    blade_thickness: FloatProperty(
        name="Blade Thickness",
        description="Solidify thickness applied to each NURBS blade",
        default=0.0022,
        min=0.0,
        max=0.02,
        unit="LENGTH",
    )

    convert_to_mesh: BoolProperty(
        name="Convert Blades to Mesh",
        description="Keep blades as live NURBS surfaces or convert to polygon meshes",
        default=False,
    )

    def execute(self, context):
        n_blades = int(self.blade_count)
        r_tip = self.fan_diameter * 0.5
        # Clamp hub radius so it never exceeds 85% of tip radius
        r_hub = min(self.hub_diameter * 0.5, r_tip * 0.85)

        # Scale default chord proportionally to fan radius (calibrated to 0.15 m reference)
        scale_factor = r_tip / 0.15
        chord_root = 0.045 * scale_factor * self.chord_ratio
        chord_swell = 0.065 * scale_factor * self.chord_ratio

        # Parent empty to keep the entire fan assembly tidy in the Outliner
        root_empty = bpy.data.objects.new(
            f"AxialFan_{n_blades}Blade", None
        )
        root_empty.empty_display_type = "PLAIN_AXES"
        root_empty.empty_display_size = r_hub * 1.2
        context.collection.objects.link(root_empty)

        # Build central hub
        hub_obj = build_central_hub(
            context, f"FanHub_{n_blades}Blade", r_hub, self.hub_height
        )
        hub_obj.parent = root_empty

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
        master_blade.parent = root_empty

        blades = [master_blade]

        # Instance remaining blades around Z-axis (sharing the same NURBS data-block)
        for i in range(1, n_blades):
            angle = (2.0 * math.pi * i) / n_blades
            blade_copy = master_blade.copy()
            blade_copy.name = f"FanBlade_{i + 1:02d}"
            blade_copy.rotation_euler = (0.0, 0.0, angle)
            context.collection.objects.link(blade_copy)
            blade_copy.parent = root_empty
            blades.append(blade_copy)

        if self.convert_to_mesh:
            bpy.ops.object.select_all(action="DESELECT")
            for b in blades:
                b.select_set(True)
            context.view_layer.objects.active = master_blade
            bpy.ops.object.convert(target="MESH")

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
    