"""
Verified Script: FreeCAD Primitive Cylinder Solid
Operation: makeCylinder
Validated: true
"""
import FreeCAD
import Part

def create_cylinder(radius: float = 20.0, height: float = 50.0, step_path: str = "cylinder.step"):
    doc = FreeCAD.newDocument("CylinderDoc")
    cyl = Part.makeCylinder(radius, height)
    obj = doc.addObject("Part::Feature", "Cylinder")
    obj.Shape = cyl
    doc.recompute()
    if step_path:
        cyl.exportStep(step_path)
    return cyl

if __name__ == "__main__":
    create_cylinder()
