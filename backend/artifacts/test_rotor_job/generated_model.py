import FreeCAD
import Part
import math

def create_model():
    # Define parameters
    outer_diameter = 280
    thickness = 25
    bore_diameter = 70
    mounting_hole_diameter = 12
    bolt_circle_diameter = 114.3
    outer_radius = outer_diameter / 2
    bore_radius = bore_diameter / 2
    mounting_hole_radius = mounting_hole_diameter / 2
    bolt_circle_radius = bolt_circle_diameter / 2

    # Create the main cylinder
    main_cylinder = Part.makeCylinder(outer_radius, thickness)

    # Create the central bore
    central_bore = Part.makeCylinder(bore_radius, thickness)

    # Create the mounting holes
    num_holes = 5
    angle_between_holes = 2 * math.pi / num_holes
    mounting_holes = []
    for i in range(num_holes):
        angle = i * angle_between_holes
        x = bolt_circle_radius * math.cos(angle)
        y = bolt_circle_radius * math.sin(angle)
        hole = Part.makeCylinder(mounting_hole_radius, thickness, FreeCAD.Vector(x, y, 0))
        mounting_holes.append(hole)

    # Combine all mounting holes into a single compound shape
    mounting_holes_compound = Part.Compound(mounting_holes)

    # Perform boolean cuts
    shape = main_cylinder.cut(central_bore)
    shape = shape.cut(mounting_holes_compound)

    # Verify the shape is valid
    if not shape.isValid():
        raise RuntimeError("Shape geometry is invalid")

    # Document setup & export
    doc = FreeCAD.newDocument("TextToCAD_Job")
    part_obj = doc.addObject("Part::Feature", "ModelPart")
    part_obj.Shape = shape
    doc.recompute()
    shape.exportStep("model.step")
    shape.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, part_obj

if __name__ == "__main__":
    doc, part_obj = create_model()