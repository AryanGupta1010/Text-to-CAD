"""
Verified Script: FreeCAD Hollow Cylindrical Container with Closed Bottom
Operation: boolean_cut / cylinder subtraction
Validated: true
"""
import sys
import FreeCAD
import Part

def create_hollow_container(
    outer_radius: float = 30.0,
    height: float = 100.0,
    wall_thickness: float = 3.0,
    bottom_thickness: float = 4.0,
    export_step_path: str = "model.step",
    export_stl_path: str = "model.stl",
    export_fcstd_path: str = "model.FCStd"
):
    """
    Creates a hollow cylindrical container with specified dimensions,
    a closed bottom, and open top, then exports STEP and STL models.
    """
    # 1. Validation of input parameters
    assert outer_radius > wall_thickness, "Outer radius must exceed wall thickness"
    assert height > bottom_thickness, "Height must exceed bottom thickness"
    
    inner_radius = outer_radius - wall_thickness
    # Cutting tool height: slightly taller than container to guarantee clean open top face
    cutting_height = height - bottom_thickness + 1.0

    # 2. Document initialization
    doc = FreeCAD.newDocument("CylindricalContainerDoc")

    # 3. Outer cylinder solid
    outer_cyl = Part.makeCylinder(outer_radius, height, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1))

    # 4. Inner cylinder solid (translated up by bottom_thickness)
    inner_cyl = Part.makeCylinder(inner_radius, cutting_height, FreeCAD.Vector(0, 0, bottom_thickness), FreeCAD.Vector(0, 0, 1))

    # 5. Boolean subtraction (cut)
    container = outer_cyl.cut(inner_cyl)

    # 6. Topological verification
    if not container.isValid():
        raise RuntimeError("Geometry validation failed: Resulting shape is topologically invalid.")
    if container.isNull():
        raise RuntimeError("Geometry validation failed: Shape is null.")
    if len(container.Solids) != 1:
        raise RuntimeError(f"Expected 1 solid, found {len(container.Solids)}")

    # 7. Add object to document
    part_feature = doc.addObject("Part::Feature", "HollowCylinderContainer")
    part_feature.Shape = container
    doc.recompute()

    # 8. Export artifacts
    if export_step_path:
        container.exportStep(export_step_path)
    if export_stl_path:
        container.exportStl(export_stl_path)
    if export_fcstd_path:
        doc.saveAs(export_fcstd_path)

    return container

if __name__ == "__main__":
    create_hollow_container()
