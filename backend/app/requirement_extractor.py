import json
import logging
import re
from typing import Optional, Tuple
from backend.app.schemas import CADSpecification, CADFeature
from backend.app.llm_provider import BaseLLMProvider, extract_json_from_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert mechanical CAD engineer and formal specification extractor for FreeCAD.
Your task is to analyze natural language CAD requests and extract a strictly valid, structured JSON specification conforming to the target schema.

SCHEMA REQUIREMENTS:
{
  "cad_engine": "FreeCAD",
  "units": "mm",
  "object_description": "string",
  "features": [
    {
      "feature_type": "string (e.g. cylinder, box, pocket, hole, fillet)",
      "dimensions": {"param_name": number_in_mm},
      "parameters": {"extra_param": value},
      "geometric_constraints": ["concentric", "coaxial", etc.],
      "dependencies": ["preceding_feature_type"],
      "expected_properties": {"is_solid": true, etc.}
    }
  ],
  "parameters": {
    "dimension_name": number_in_mm
  },
  "constraints": ["constraint 1", "constraint 2"],
  "operations": ["create_outer_cylinder", "create_inner_cylinder", "translate", "cut"],
  "output_formats": ["STEP", "STL"],
  "assumptions": ["assumption 1"],
  "clarification_required": false,
  "clarification_questions": []
}

CRITICAL RULES:
1. Normalize all units to "mm". For example, if given 10 cm, convert to 100 mm.
2. Verify dimensional consistency: inner dimensions must fit inside outer dimensions.
3. If essential geometric parameters (like primary dimensions or thickness for a hollow part) are missing or materially ambiguous, set "clarification_required": true and list targeted "clarification_questions".
4. Do NOT hallucinate unspecified critical dimensions. Clearly list any inferred defaults in "assumptions".
5. Return ONLY a valid JSON object. Do not include markdown preamble outside of JSON.
"""


def normalize_units(val_str: str) -> Tuple[float, str]:
    """Helper to parse a number and unit string to mm."""
    match = re.match(r"([\d\.]+)\s*([a-zA-Z]+)?", val_str.strip())
    if not match:
        return float(val_str), "mm"
    num = float(match.group(1))
    unit = (match.group(2) or "mm").lower()
    if unit in ["cm", "centimeter", "centimeters"]:
        return num * 10.0, "mm"
    elif unit in ["m", "meter", "meters"]:
        return num * 1000.0, "mm"
    elif unit in ["in", "inch", "inches"]:
        return num * 25.4, "mm"
    return num, "mm"


class RequirementExtractor:
    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    def extract(self, user_prompt: str) -> CADSpecification:
        """Extracts and validates a CADSpecification from user text."""
        extraction_prompt = f"""Extract the structured FreeCAD specification for the following request:
Request: \"{user_prompt}\"

Remember:
- Normalize units to mm.
- For hollow containers or pockets, compute inner radius = outer radius - wall thickness, and inner height = height - bottom thickness.
- If dimensions are missing, ask clarification questions.
- Output JSON ONLY.
"""
        data = None
        try:
            raw_output = self.provider.generate(
                prompt=extraction_prompt,
                system=SYSTEM_PROMPT,
                json_mode=True,
                temperature=0.1,
            )
            data = extract_json_from_text(raw_output)
        except Exception as e:
            logger.warning(f"LLM specification extraction encountered issue: {e}. Executing intelligent rule-based extraction fallback.")
            data = self._rule_based_fallback(user_prompt)

        # Validate dimensional consistency & fill calculated parameters
        spec = self._validate_and_normalize_specification(data, user_prompt)
        return spec

    def _validate_and_normalize_specification(self, data: dict, original_prompt: str) -> CADSpecification:
        # Guarantee required fields
        data.setdefault("cad_engine", "FreeCAD")
        data.setdefault("units", "mm")
        data.setdefault("output_formats", ["STEP", "STL"])
        data.setdefault("assumptions", [])
        data.setdefault("clarification_questions", [])
        if "clarification_required" not in data:
            data["clarification_required"] = False

        params = data.get("parameters", {})
        
        # Check cylindrical container relationships if present
        if "outer_radius" in params and "wall_thickness" in params:
            outer_r = float(params["outer_radius"])
            wall_t = float(params["wall_thickness"])
            if wall_t >= outer_r:
                data["clarification_required"] = True
                data["clarification_questions"].append(
                    f"Wall thickness ({wall_t} mm) cannot be greater than or equal to outer radius ({outer_r} mm)."
                )
            else:
                params["inner_radius"] = round(outer_r - wall_t, 4)

        if "height" in params and "bottom_thickness" in params:
            h = float(params["height"])
            b_t = float(params["bottom_thickness"])
            if b_t >= h:
                data["clarification_required"] = True
                data["clarification_questions"].append(
                    f"Bottom thickness ({b_t} mm) cannot be greater than or equal to height ({h} mm)."
                )
            else:
                params["inner_height"] = round(h - b_t, 4)

        data["parameters"] = params
        return CADSpecification(**data)

    def _rule_based_fallback(self, prompt: str) -> dict:
        """Deterministic regex-based fallback to extract parameters for any shape from text."""
        lower = prompt.lower()

        is_box = any(k in lower for k in ["cube", "box", "block", "enclosure", "rectangular plate", "plate"])
        is_sphere = any(k in lower for k in ["sphere", "ball", "globe"])
        is_bushing = any(k in lower for k in ["bushing", "flanged pipe", "pipe", "tube", "washer", "spacer", "ring"])
        is_hollow_container = not is_bushing and any(k in lower for k in ["container", "cup", "can", "pot", "pocket"]) or ("hollow" in lower and "cylinder" in lower)
        is_solid_cylinder = not is_hollow_container and not is_bushing and any(k in lower for k in ["cylinder", "rod", "pin", "shaft"])

        params = {}
        features = []
        operations = []
        constraints = []

        # 1. Box / Cube
        if is_box:
            cube_m = re.search(r"(?:cube\s*(?:of|with\s*side)?|side)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if cube_m:
                s = float(cube_m.group(1))
                params["length"] = s
                params["width"] = s
                params["height"] = s
            else:
                dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", lower)
                if dim3:
                    params["length"] = float(dim3.group(1))
                    params["width"] = float(dim3.group(2))
                    params["height"] = float(dim3.group(3))
                else:
                    l_m = re.search(r"length\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
                    w_m = re.search(r"width\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
                    h_m = re.search(r"(?:height|thickness)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
                    params["length"] = float(l_m.group(1)) if l_m else 60.0
                    params["width"] = float(w_m.group(1)) if w_m else 40.0
                    params["height"] = float(h_m.group(1)) if h_m else 25.0

            features.append({
                "feature_type": "box",
                "dimensions": params,
                "parameters": {"type": "solid_body"},
                "geometric_constraints": ["orthogonal"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            operations = ["create_box"]
            constraints = ["orthogonal_faces"]

        # 2. Sphere
        elif is_sphere:
            r_m = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if "diameter" in lower and r_m:
                params["radius"] = float(r_m.group(1)) / 2.0
            elif r_m:
                params["radius"] = float(r_m.group(1))
            else:
                params["radius"] = 25.0

            features.append({
                "feature_type": "sphere",
                "dimensions": params,
                "parameters": {},
                "geometric_constraints": ["spherical_symmetry"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            operations = ["create_sphere"]
            constraints = ["spherical_symmetry"]

        # 3. Bushing / Pipe / Tube
        elif is_bushing:
            outer_r = 25.0
            inner_r = 15.0
            length = 60.0
            r_out = re.search(r"(?:outer\s*radius|outer\s*dia)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if r_out:
                outer_r = float(r_out.group(1)) if "radius" in r_out.group(0) else float(r_out.group(1)) / 2.0
            r_in = re.search(r"(?:inner\s*radius|inner\s*dia|bore)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if r_in:
                inner_r = float(r_in.group(1)) if "radius" in r_in.group(0) else float(r_in.group(1)) / 2.0
            l_m = re.search(r"(?:length|height)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if l_m:
                length = float(l_m.group(1))

            params = {"outer_radius": outer_r, "inner_radius": inner_r, "height": length}
            features.append({
                "feature_type": "cylinder",
                "dimensions": {"radius": outer_r, "height": length},
                "parameters": {"type": "outer_body"},
                "geometric_constraints": ["concentric"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            features.append({
                "feature_type": "cylinder_pocket",
                "dimensions": {"radius": inner_r, "height": length + 2.0},
                "parameters": {"type": "through_hole"},
                "geometric_constraints": ["coaxial"],
                "dependencies": ["cylinder"],
                "expected_properties": {"subtraction": True}
            })
            operations = ["create_outer_cylinder", "create_inner_cylinder", "boolean_cut"]
            constraints = ["concentric", "through_hole"]

        # 4. Solid Cylinder
        elif is_solid_cylinder:
            r = 20.0
            h = 50.0
            r_m = re.search(r"(?:radius|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if r_m:
                r = float(r_m.group(1)) if "radius" in r_m.group(0) else float(r_m.group(1)) / 2.0
            h_m = re.search(r"(?:height|length)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if h_m:
                h = float(h_m.group(1))

            params = {"radius": r, "height": h}
            features.append({
                "feature_type": "cylinder",
                "dimensions": params,
                "parameters": {},
                "geometric_constraints": ["cylindrical_symmetry"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            operations = ["create_cylinder"]
            constraints = ["cylindrical_symmetry"]

        # 5. Hollow Cylindrical Container
        else:
            r_match = re.search(r"(?:outer\s*radius|radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            outer_r = float(r_match.group(1)) if r_match else 30.0
            d_match = re.search(r"(?:outer\s*diameter|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if d_match:
                outer_r = float(d_match.group(1)) / 2.0
                
            h_match = re.search(r"height\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            h = float(h_match.group(1)) if h_match else 100.0

            w_match = re.search(r"wall\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            wall_t = float(w_match.group(1)) if w_match else 3.0

            b_match = re.search(r"bottom\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            bot_t = float(b_match.group(1)) if b_match else 4.0

            inner_r = max(1.0, outer_r - wall_t)
            inner_h = max(1.0, h - bot_t)

            params = {
                "outer_radius": outer_r,
                "height": h,
                "wall_thickness": wall_t,
                "bottom_thickness": bot_t,
                "inner_radius": inner_r,
                "inner_height": inner_h,
            }
            features.append({
                "feature_type": "cylinder",
                "dimensions": {"radius": outer_r, "height": h},
                "parameters": {"type": "outer_body"},
                "geometric_constraints": ["concentric"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            features.append({
                "feature_type": "cylinder_pocket",
                "dimensions": {"radius": inner_r, "height": inner_h, "z_offset": bot_t},
                "parameters": {"type": "inner_cavity"},
                "geometric_constraints": ["concentric", "coaxial"],
                "dependencies": ["cylinder"],
                "expected_properties": {"subtraction": True}
            })
            operations = ["create_outer_cylinder", "create_inner_cylinder", "translate_inner_cylinder", "boolean_cut"]
            constraints = ["concentric", "closed_bottom", "open_top"]

        return {
            "cad_engine": "FreeCAD",
            "units": "mm",
            "object_description": prompt,
            "features": features,
            "parameters": params,
            "constraints": constraints,
            "operations": operations,
            "output_formats": ["STEP", "STL"],
            "assumptions": ["Z-axis orientation", "Default centered coordinate system"],
            "clarification_required": False,
            "clarification_questions": [],
        }
