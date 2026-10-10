"""
Verified Script: Generic Boolean Cut in FreeCAD
Operation: Part.cut
Validated: true
"""
import FreeCAD
import Part

def cut_shapes(base_shape, tool_shape):
    """Safely executes Part.cut with topological validity checks."""
    result = base_shape.cut(tool_shape)
    if not result.isValid():
        raise RuntimeError("Boolean cut resulted in invalid topology")
    return result
