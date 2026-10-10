# FreeCAD Part Module API Reference

The `Part` module is the core geometric modeling interface in FreeCAD, built upon Open CASCADE Technology (OCCT).

## Core Primitives

### Part.makeCylinder
```python
cylinder = Part.makeCylinder(radius, height, pnt=FreeCAD.Vector(0,0,0), dir=FreeCAD.Vector(0,0,1), angle=360)
```
- **radius** (`float`): Outer radius in millimeters.
- **height** (`float`): Extrusion height along vector direction.
- **pnt** (`FreeCAD.Vector`, optional): Center point of cylinder base. Defaults to (0,0,0).
- **dir** (`FreeCAD.Vector`, optional): Axis direction vector. Defaults to (0,0,1) for Z-axis.
- **angle** (`float`, optional): Subtended rotation angle in degrees (default 360).

### Part.makeBox
```python
box = Part.makeBox(length, width, height, pnt=FreeCAD.Vector(0,0,0), dir=FreeCAD.Vector(0,0,1))
```
- Creates a solid cuboid aligned with coordinate axes.

### Part.makeSphere
```python
sphere = Part.makeSphere(radius, pnt=FreeCAD.Vector(0,0,0))
```

### Part.makeCone
```python
cone = Part.makeCone(radius1, radius2, height)
```

## Boolean Operations

FreeCAD shapes support CSG (Constructive Solid Geometry) boolean operations:

### Cut (Boolean Subtraction)
```python
result = shapeA.cut(shapeB)
```
- Subtracts `shapeB` from `shapeA`.
- Crucial rule: When cutting concentric shapes, ensure inner shape does not have coplanar boundary faces with outer shape if zero-thickness sliver edges cause OCCT kernel errors. Translate inner shape by bottom thickness along Z.

### Fuse (Boolean Union)
```python
result = shapeA.fuse(shapeB)
```

### Common (Boolean Intersection)
```python
result = shapeA.common(shapeB)
```

## Shape Transformation & Placement

```python
# Translation using vector
shape.translate(FreeCAD.Vector(dx, dy, dz))

# Rotation using Placement or rotate
shape.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 45.0)

# Direct Placement assignment
import FreeCAD
shape.Placement.Base = FreeCAD.Vector(x, y, z)
```

## Geometry Verification Methods

Before committing shapes or saving documents, always verify OCCT validity:
```python
# Check topological validity
is_valid = shape.isValid()

# Check shape is non-null
is_null = shape.isNull()

# Retrieve bounding box
bbox = shape.BoundBox
x_length = bbox.XLength
y_length = bbox.YLength
z_length = bbox.ZLength

# Solids count
solids = shape.Solids
num_solids = len(solids)
volume = shape.Volume
```
