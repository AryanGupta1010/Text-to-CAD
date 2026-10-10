# Error Fixes: Boolean Operation Failures in FreeCAD / Open CASCADE

## Error 1: Coincident Face / Coplanar Cut Failure
- **Symptom**: `BRep_API: command not done`, null shape returned, or sliver faces created when subtracting concentric cylinder.
- **Cause**: The top face of the subtracting tool is exactly coplanar with the top face of the outer cylinder.
- **Solution**: Extend the cutting cylinder height by at least 0.5 mm or 1.0 mm beyond the top face, ensuring a clean cut through the open top:
  ```python
  inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0)
  inner_cyl.translate(FreeCAD.Vector(0, 0, bottom_thickness))
  ```

## Error 2: Inverted or Disjoint Cut
- **Symptom**: Shape has 0 solids or 2 disconnected bodies.
- **Cause**: Subtracting tool was translated outside the bounding volume of the outer shape.
- **Solution**: Verify translation coordinates `FreeCAD.Vector(0, 0, bottom_thickness)`. Ensure `bottom_thickness < height`.
