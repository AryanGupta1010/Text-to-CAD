"""
Verified Script: FreeCAD Box / Rectangular Plate / Block
Operation: makeBox / primitive
Validated: true
"""
import FreeCAD
import Part

def create_box(
    length: float = 60.0,
    width: float = 40.0,
    height: float = 25.0,
    export_step_path: str = "model.step",
    export_stl_path: str = "model.stl",
    export_fcstd_path: str = "model.FCStd"
):
    """
    Creates a solid rectangular box or plate with specified dimensions
    and exports STEP, STL, and FCStd models.
    """
    doc = FreeCAD.newDocument("BoxDoc")
    box = Part.makeBox(length, width, height)

    if not box.isValid():
        raise RuntimeError("Geometry validation failed: Box is invalid.")

    part_obj = doc.addObject("Part::Feature", "BoxPart")
    part_obj.Shape = box
    doc.recompute()

    if export_step_path:
        box.exportStep(export_step_path)
    if export_stl_path:
        box.exportStl(export_stl_path)
    if export_fcstd_path:
        doc.saveAs(export_fcstd_path)

    return box

if __name__ == "__main__":
    create_box()
