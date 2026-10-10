# FreeCAD Sketcher & PartDesign API Reference

For 2D profile generation with constraints followed by extrusion (pad), revolution, or pocketing.

## Basic Workflow

1. Create a `Sketcher::SketchObject` in the document.
2. Add geometries (lines, circles, arcs).
3. Add geometric and dimensional constraints.
4. Solve sketch constraints.
5. Extrude or Pad using PartDesign or Part.

## Creating a Constrained Circle Sketch
```python
import FreeCAD
import Sketcher
import Part

doc = FreeCAD.newDocument("SketchDoc")
sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
sketch.MapMode = "FlatFace"

# Add concentric circles for a hollow cylinder
# Part.GeomCircle(Center, Normal, Radius)
geo1 = Part.GeomCircle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 30.0)
geo2 = Part.GeomCircle(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 27.0)

sketch.addGeometry(geo1)
sketch.addGeometry(geo2)

# Solve constraints
sketch.solve()
doc.recompute()
```
