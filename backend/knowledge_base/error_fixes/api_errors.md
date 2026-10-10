# Error Fixes: API and Script Execution Errors

## Error 1: ModuleNotFoundError: No module named 'FreeCAD'
- **Cause**: Script was executed with standard python interpreter rather than FreeCAD Python environment or `FreeCADCmd`.
- **Solution**: Execute the script using `FreeCADCmd -c <script.py>` or provide FreeCAD lib path to `sys.path`.

## Error 2: 'Part' has no attribute 'exportSTEP' (Case Sensitivity)
- **Cause**: Method name in Part is `exportStep` (lowercase 'tep') or `shape.exportStep(path)`.
- **Solution**: Use `shape.exportStep("filepath.step")` or `Part.export([shape_obj], "filepath.step")`.

## Error 3: exportStl failure on non-solid
- **Cause**: Attempting to mesh an open shell or invalid wire.
- **Solution**: Ensure shape is closed and valid (`shape.isValid()`).

## Error 4: document.recompute() failed
- **Cause**: Broken feature dependency or circular reference in tree.
- **Solution**: Assign shape directly to `doc.addObject("Part::Feature", "Name").Shape = shape`.
