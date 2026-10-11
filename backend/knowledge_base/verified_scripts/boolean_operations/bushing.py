"""
Verified Script: FreeCAD Bushing / Through-Hole Sleeve / Straight Pipe
Operation: cylinder_cut / boolean_cut
Validated: true
"""
import FreeCAD
import Part

def create_bushing(
    outer_radius: float = 25.0,
    inner_radius: float = 15.0,
    height: float = 60.0,
    export_step_path: str = "model.step",
    export_stl_path: str = "model.stl",
    export_fcstd_path: str = "model.FCStd"
):
    """
    Creates a cylindrical bushing/sleeve with an open through-hole bore
    and exports STEP and STL files.
    """
    assert outer_radius > inner_radius, "Outer radius must exceed inner bore radius"
    doc = FreeCAD.newDocument("BushingDoc")

    outer_cyl = Part.makeCylinder(outer_radius, height)
    cutter = Part.makeCylinder(inner_radius, height + 2.0)
    cutter.translate(FreeCAD.Vector(0, 0, -1.0))

    bushing = outer_cyl.cut(cutter)
    if not bushing.isValid():
        raise RuntimeError("Geometry validation failed: Bushing is invalid.")

    shape_obj = doc.addObject("Part::Feature", "BushingPart")
    shape_obj.Shape = bushing
    doc.recompute()

    if export_step_path:
        bushing.exportStep(export_step_path)
    if export_stl_path:
        bushing.exportStl(export_stl_path)
    if export_fcstd_path:
        doc.saveAs(export_fcstd_path)

    return bushing

if __name__ == "__main__":
    create_bushing()
