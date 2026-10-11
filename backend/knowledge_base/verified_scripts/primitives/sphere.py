"""
Verified Script: FreeCAD Sphere Primitive
Operation: makeSphere / primitive
Validated: true
"""
import FreeCAD
import Part

def create_sphere(
    radius: float = 25.0,
    export_step_path: str = "model.step",
    export_stl_path: str = "model.stl",
    export_fcstd_path: str = "model.FCStd"
):
    """
    Creates a solid sphere with specified radius and exports CAD artifacts.
    """
    doc = FreeCAD.newDocument("SphereDoc")
    sphere = Part.makeSphere(radius)

    if not sphere.isValid():
        raise RuntimeError("Geometry validation failed: Sphere is invalid.")

    part_obj = doc.addObject("Part::Feature", "SpherePart")
    part_obj.Shape = sphere
    doc.recompute()

    if export_step_path:
        sphere.exportStep(export_step_path)
    if export_stl_path:
        sphere.exportStl(export_stl_path)
    if export_fcstd_path:
        doc.saveAs(export_fcstd_path)

    return sphere

if __name__ == "__main__":
    create_sphere()
