
import FreeCAD
import Part

doc = FreeCAD.newDocument('CustomDesign')
# Create a custom block with 2 cylindrical holes
block = Part.makeBox(80, 50, 30)
hole1 = Part.makeCylinder(8, 40)
hole1.translate(FreeCAD.Vector(20, 25, -5))
hole2 = Part.makeCylinder(8, 40)
hole2.translate(FreeCAD.Vector(60, 25, -5))

result = block.cut(hole1).cut(hole2)
part_obj = doc.addObject('Part::Feature', 'CustomPart')
part_obj.Shape = result
result.exportStl('model.stl')
result.exportStep('model.step')
