"""
Verified Script: FreeCAD 3D L-Shaped Hollow Pipe with 90-Degree Curved Bend
Operation: wire_sweep / makePipe / cut
Validated: true
"""
import math
import FreeCAD
import Part

def create_l_shaped_pipe(
    outer_radius: float = 10.0,
    inner_radius: float = 7.0,
    length_1: float = 100.0,
    length_2: float = 100.0,
    bend_radius: float = 30.0,
    export_step_path: str = "model.step",
    export_stl_path: str = "model.stl",
    export_fcstd_path: str = "model.FCStd"
):
    """
    Creates an L-shaped hollow pipe with a 90-degree smooth curved elbow bend
    connecting two perpendicular straight sections.
    """
    assert outer_radius > inner_radius, "Outer radius must exceed inner radius"
    doc = FreeCAD.newDocument("LShapedPipeDoc")

    s1 = max(10.0, length_1 - bend_radius)
    s2 = max(10.0, length_2 - bend_radius)

    # 1. Trajectory path in XZ plane
    p0 = FreeCAD.Vector(0, 0, 0)
    p1 = FreeCAD.Vector(0, 0, s1)
    line1 = Part.makeLine(p0, p1)

    p_mid = FreeCAD.Vector(
        bend_radius - bend_radius * math.cos(math.pi / 4),
        0,
        s1 + bend_radius * math.sin(math.pi / 4)
    )
    p2 = FreeCAD.Vector(bend_radius, 0, s1 + bend_radius)
    arc = Part.Arc(p1, p_mid, p2).toShape()

    p3 = FreeCAD.Vector(length_2, 0, s1 + bend_radius)
    line2 = Part.makeLine(p2, p3)

    path_wire = Part.Wire([line1, arc, line2])

    # 2. Profiles at start point p0
    outer_circle = Part.makeCircle(outer_radius, p0, FreeCAD.Vector(0, 0, 1))
    outer_face = Part.Face(Part.Wire([outer_circle]))
    outer_pipe = outer_face.makePipe(path_wire)

    inner_circle = Part.makeCircle(inner_radius, p0, FreeCAD.Vector(0, 0, 1))
    inner_face = Part.Face(Part.Wire([inner_circle]))
    inner_pipe = inner_face.makePipe(path_wire)

    # 3. Hollow subtraction
    pipe = outer_pipe.cut(inner_pipe)
    if not pipe.isValid():
        raise RuntimeError("Geometry validation failed: L-shaped pipe geometry is invalid.")

    shape_obj = doc.addObject("Part::Feature", "LShapedPipePart")
    shape_obj.Shape = pipe
    doc.recompute()

    if export_step_path:
        pipe.exportStep(export_step_path)
    if export_stl_path:
        pipe.exportStl(export_stl_path)
    if export_fcstd_path:
        doc.saveAs(export_fcstd_path)

    return pipe

if __name__ == "__main__":
    create_l_shaped_pipe()
