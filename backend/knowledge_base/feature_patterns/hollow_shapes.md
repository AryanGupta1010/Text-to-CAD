# Modeling Pattern: Hollow Shapes & Thin-Walled Containers

Creating hollow vessels, tubes, enclosures, or containers with closed bases in FreeCAD.

## Recommended Strategy: Constructive Solid Geometry (CSG) Subtraction

1. **Outer Shell**: Create outer solid boundary using `Part.makeCylinder` or `Part.makeBox`.
2. **Inner Core**: Create inner solid boundary:
   - Outer dimension minus wall thickness: `inner_radius = outer_radius - wall_thickness`
   - Inner tool height: `height - bottom_thickness + safety_margin`
3. **Translation**: Shift inner core by `bottom_thickness` along Z axis (`Part.translate(FreeCAD.Vector(0, 0, bottom_thickness))`).
4. **Boolean Cut**: `outer_shape.cut(inner_shape)`
5. **Quality Control**:
   - Check `shape.isValid()`
   - Verify `len(shape.Solids) == 1`
   - Ensure wall thickness is measured correctly via radial boundary faces.
