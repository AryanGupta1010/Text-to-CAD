import ast
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from backend.app.schemas import CADSpecification
from backend.app.llm_provider import BaseLLMProvider, extract_python_code

logger = logging.getLogger(__name__)

CODE_GEN_SYSTEM_PROMPT = """You are an expert Python CAD engineer specializing in FreeCAD and Open CASCADE geometry scripting.
Your task is to write a clean, self-contained, and completely executable Python script using the FreeCAD Part module based strictly on the provided specification and retrieved verified examples.

STRICT GENERATION RULES:
1. Imports: Always start with:
   import FreeCAD
   import Part
2. Use parameter variables at the top of the function matching the specification (e.g. outer_radius, height, wall_thickness, bottom_thickness).
3. Do NOT invent arbitrary API methods. Use verified FreeCAD methods:
   - Part.makeCylinder(radius, height, pnt=FreeCAD.Vector(x,y,z), dir=FreeCAD.Vector(0,0,1))
   - Part.makeBox(l, w, h)
   - shapeA.cut(shapeB)
   - shapeA.fuse(shapeB)
4. For hollow cylinders with open top and closed bottom:
   - inner_radius = outer_radius - wall_thickness
   - cutting_height = height - bottom_thickness + 1.0 (to avoid degenerate coplanar top face)
   - inner_cyl = Part.makeCylinder(inner_radius, cutting_height, FreeCAD.Vector(0, 0, bottom_thickness), FreeCAD.Vector(0, 0, 1))
   - container = outer_cyl.cut(inner_cyl)
5. Topological Verification:
   if not container.isValid():
       raise RuntimeError("Shape geometry is invalid")
6. Document & Export:
   doc = FreeCAD.newDocument("ModelDoc")
   part_obj = doc.addObject("Part::Feature", "ModelPart")
   part_obj.Shape = container
   doc.recompute()
   container.exportStep("model.step")
   container.exportStl("model.stl")
   doc.saveAs("model.FCStd")
7. Output: Return ONLY the executable Python script enclosed in ```python ... ``` markdown block. No conversational text.
"""


def perform_static_checks(code: str) -> Tuple[bool, List[str]]:
    """Performs AST static checks on generated script for safety and syntax."""
    errors = []
    
    # Check 1: Syntax parsing
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError on line {e.lineno}: {e.msg}"]
    except Exception as e:
        return False, [f"Failed to parse script AST: {str(e)}"]

    # Check 2: Prohibited modules
    prohibited_modules = {"os", "subprocess", "socket", "urllib", "requests", "shutil", "builtins"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in prohibited_modules:
                    errors.append(f"Security check failed: Prohibited module import '{mod}'.")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in prohibited_modules:
                errors.append(f"Security check failed: Prohibited module import '{mod}'.")

    # Check 3: Required CAD imports
    has_freecad = "FreeCAD" in code or "Part" in code
    if not has_freecad:
        errors.append("Missing required CAD module: Script must import FreeCAD or Part.")

    # Check 4: Check for export calls
    if "exportStep" not in code and "exportStl" not in code:
        errors.append("Warning: Script does not appear to call exportStep or exportStl.")

    passed = len(errors) == 0 or all(e.startswith("Warning") for e in errors)
    return passed, errors


class CADCodeGenerator:
    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    def generate(
        self,
        spec: CADSpecification,
        context: str,
        source_doc_ids: List[str],
    ) -> Dict[str, Any]:
        """Generates a complete Python CAD script."""
        user_prompt = f"""Generate the FreeCAD Python script for the following specification:
Object: {spec.object_description}
Parameters: {spec.parameters}
Features: {[f.feature_type for f in spec.features]}

Retrieved Reference Context:
{context}

Provide ONLY the complete executable Python script.
"""
        script = ""
        try:
            raw_output = self.provider.generate(
                prompt=user_prompt,
                system=CODE_GEN_SYSTEM_PROMPT,
                temperature=0.2,
            )
            script = extract_python_code(raw_output)
        except Exception as e:
            logger.warning(f"LLM script generation failed or timed out: {e}. Utilizing deterministic CAD script generator.")
            script = self._generate_script_from_spec(spec)

        passed_static, static_errors = perform_static_checks(script)
        if not passed_static:
            logger.warning(f"Generated script failed static checks ({static_errors}). Falling back to verified parametric template.")
            script = self._generate_script_from_spec(spec)
            passed_static, static_errors = perform_static_checks(script)

        # Expected features and dimensions summary
        expected_features = [f.feature_type for f in spec.features]
        expected_dims = spec.parameters

        return {
            "script": script,
            "engine": spec.cad_engine,
            "expected_features": expected_features,
            "expected_dimensions": expected_dims,
            "source_document_ids": source_doc_ids,
            "static_checks_passed": passed_static,
            "static_check_errors": static_errors,
        }

    def _generate_script_from_spec(self, spec: CADSpecification) -> str:
        """Constructs a certified, watertight FreeCAD Python script directly from CADSpecification."""
        features = [f.feature_type for f in spec.features]
        params = spec.parameters

        if "box" in features or ("length" in params and "width" in params and "height" in params):
            l = float(params.get("length", 60.0))
            w = float(params.get("width", 40.0))
            h = float(params.get("height", 25.0))
            return f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    length = {l}
    width = {w}
    height = {h}
    
    box = Part.makeBox(length, width, height)
    if not box.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = box
    doc.recompute()

    box.exportStep("model.step")
    box.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""

        elif "sphere" in features or ("radius" in params and "height" not in params):
            r = float(params.get("radius", 25.0))
            return f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius = {r}
    
    sphere = Part.makeSphere(radius)
    if not sphere.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = sphere
    doc.recompute()

    sphere.exportStep("model.step")
    sphere.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""

        elif "cylinder_pocket" in features and "wall_thickness" not in params and "inner_radius" in params:
            # Bushing / through-hole pipe
            r_out = float(params.get("outer_radius", 25.0))
            r_in = float(params.get("inner_radius", 15.0))
            h = float(params.get("height", 60.0))
            return f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    outer_radius = {r_out}
    inner_radius = {r_in}
    height = {h}
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    cutter = Part.makeCylinder(inner_radius, height + 2.0)
    cutter.translate(FreeCAD.Vector(0, 0, -1.0))
    
    bushing = outer_cyl.cut(cutter)
    if not bushing.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = bushing
    doc.recompute()

    bushing.exportStep("model.step")
    bushing.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""

        elif "cylinder" in features and "cylinder_pocket" not in features and "wall_thickness" not in params:
            # Solid cylinder
            r = float(params.get("radius", params.get("outer_radius", 20.0)))
            h = float(params.get("height", 50.0))
            return f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    radius = {r}
    height = {h}
    
    cyl = Part.makeCylinder(radius, height)
    if not cyl.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "ModelPart")
    shape_obj.Shape = cyl
    doc.recompute()

    cyl.exportStep("model.step")
    cyl.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""

        else:
            # Hollow cylindrical container with closed bottom
            outer_r = float(params.get("outer_radius", 30.0))
            h = float(params.get("height", 100.0))
            wall_t = float(params.get("wall_thickness", 3.0))
            bot_t = float(params.get("bottom_thickness", 4.0))
            inner_r = round(outer_r - wall_t, 4)
            return f"""import FreeCAD
import Part

def create_model():
    doc = FreeCAD.newDocument("TextToCAD_Job")
    outer_radius = {outer_r}
    height = {h}
    wall_thickness = {wall_t}
    bottom_thickness = {bot_t}
    inner_radius = outer_radius - wall_thickness
    
    outer_cyl = Part.makeCylinder(outer_radius, height)
    inner_cyl = Part.makeCylinder(inner_radius, height - bottom_thickness + 1.0)
    inner_cyl.translate(FreeCAD.Vector(0, 0, bottom_thickness))
    
    container = outer_cyl.cut(inner_cyl)
    if not container.isValid():
        raise RuntimeError("Generated shape is invalid")
        
    shape_obj = doc.addObject("Part::Feature", "CylindricalContainer")
    shape_obj.Shape = container
    doc.recompute()

    container.exportStep("model.step")
    container.exportStl("model.stl")
    doc.saveAs("model.FCStd")
    return doc, shape_obj

if __name__ == "__main__":
    doc, shape_obj = create_model()
"""
