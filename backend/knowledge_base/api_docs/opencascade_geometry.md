# Open CASCADE Technology (OCCT) Geometry & Kernel Principles

FreeCAD utilizes Open CASCADE as its geometric modeling kernel. Understanding OCCT topological and geometric concepts ensures robust CAD generation.

## Topological Entities vs Geometric Entities

OCCT distinguishes between:
1. **Geometry**: Infinite analytical curves and surfaces (Geom_Surface, Geom_Cylinder, Geom_Plane).
2. **Topology**: Bound representations restricting geometries:
   - `Compound`: Arbitrary group of topological shapes.
   - `CompSolid`: Set of connected solids.
   - `Solid`: Finite volume bounded by Shells.
   - `Shell`: Connected set of Faces.
   - `Face`: Portion of a surface bounded by Wires.
   - `Wire`: Loop of Edges connected by Vertices.
   - `Edge`: Segment of a curve bounded by Vertices.
   - `Vertex`: Point in 3D space with tolerance.

## Non-manifold Geometries & Self-intersections

A common failure mode in CSG operations is producing non-manifold geometry:
- Sharing coincident boundaries where an inner cylinder shares an exact top boundary face with an outer cylinder without properly extending through.
- When creating through-holes or pockets open at one end, ensure the cutting tool extends slightly beyond the open face (e.g. +0.1 mm) to avoid zero-thickness degenerate faces.

## Measurement and Inspection in FreeCAD

```python
# Volume inspection
volume = shape.Volume

# Surface area
area = shape.Area

# Center of gravity
cog = shape.CenterOfMass

# Dimension verification along axes
bbox = shape.BoundBox
dx = bbox.XMax - bbox.XMin
dy = bbox.YMax - bbox.YMin
dz = bbox.ZMax - bbox.ZMin
```
