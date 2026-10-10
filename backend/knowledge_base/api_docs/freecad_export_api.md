# FreeCAD Export API Reference

Exporting FreeCAD shapes and documents to standard industrial exchange formats (STEP, STL, OBJ, FCStd).

## STEP Export (Standard for the Exchange of Product model data - ISO 10303)

STEP export preserves true B-Rep (Boundary Representation) CAD topology, nurbs surfaces, and exact dimensional fidelity.

### Direct Shape STEP Export via Part
```python
import Part

# Direct export of a TopoShape object
shape.exportStep("output_path/model.step")
```

### Document Object Export via ImportGui / Part.export
```python
import Part

# Export list of document objects
Part.export([shape_obj], "output_path/model.step")
```

## STL Export (Stereolithography Mesh for 3D Printing & Web Preview)

STL converts analytical surfaces to triangulated surface meshes.

### Direct Shape STL Export
```python
# Direct shape mesh export (deflection controls tessellation resolution in mm)
shape.exportStl("output_path/model.stl")
```

### Document Object Export to STL via Mesh module
```python
import Mesh
import MeshPart

# Create fine tessellation mesh from shape
mesh = MeshPart.meshFromShape(
    Shape=shape,
    LinearDeflection=0.05,
    AngularDeflection=0.25,
    Relative=False
)
mesh.write("output_path/model.stl")
```

## Native FreeCAD Document (.FCStd)

Saving the native document preserves full parametric tree history and feature dependencies:

```python
import FreeCAD

doc = FreeCAD.newDocument("ModelDoc")
# ... add features ...
doc.recompute()
doc.saveAs("output_path/model.FCStd")
```
