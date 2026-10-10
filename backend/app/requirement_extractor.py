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
        raw_output = self.provider.generate(
            prompt=extraction_prompt,
            system=SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.1,
        )

        try:
            data = extract_json_from_text(raw_output)
        except Exception as e:
            logger.warning(f"Failed to parse LLM JSON: {e}. Falling back to rule-based fallback.")
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
        """Deterministic regex-based fallback to extract parameters from text."""
        lower = prompt.lower()
        params = {}
        
        # Search for outer radius / diameter
        r_match = re.search(r"(?:outer\s*radius|radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
        if r_match:
            params["outer_radius"] = float(r_match.group(1))
            
        d_match = re.search(r"(?:outer\s*diameter|diameter)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
        if d_match:
            params["outer_radius"] = float(d_match.group(1)) / 2.0
            
        h_match = re.search(r"height\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
        if h_match:
            params["height"] = float(h_match.group(1))
            
        w_match = re.search(r"wall\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
        if w_match:
            params["wall_thickness"] = float(w_match.group(1))
            
        b_match = re.search(r"bottom\s*thickness\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
        if b_match:
            params["bottom_thickness"] = float(b_match.group(1))

        # Check if hollow container
        is_container = "cylinder" in lower or "container" in lower
        
        clarification = False
        questions = []
        if not params:
            clarification = True
            questions.append("Could not extract any explicit geometric dimensions. Please specify required sizes.")

        features = []
        if is_container and "outer_radius" in params and "height" in params:
            features.append({
                "feature_type": "cylinder",
                "dimensions": {"radius": params["outer_radius"], "height": params["height"]},
                "parameters": {"type": "outer_body"},
                "geometric_constraints": ["concentric"],
                "dependencies": [],
                "expected_properties": {"is_solid": True}
            })
            if "wall_thickness" in params and "bottom_thickness" in params:
                inner_r = params["outer_radius"] - params["wall_thickness"]
                inner_h = params["height"] - params["bottom_thickness"]
                params["inner_radius"] = inner_r
                params["inner_height"] = inner_h
                features.append({
                    "feature_type": "cylinder_pocket",
                    "dimensions": {"radius": inner_r, "height": inner_h, "z_offset": params["bottom_thickness"]},
                    "parameters": {"type": "inner_cavity"},
                    "geometric_constraints": ["concentric", "coaxial"],
                    "dependencies": ["cylinder"],
                    "expected_properties": {"subtraction": True}
                })

        return {
            "cad_engine": "FreeCAD",
            "units": "mm",
            "object_description": prompt,
            "features": features,
            "parameters": params,
            "constraints": ["concentric", "solid"],
            "operations": ["create_outer_cylinder", "create_inner_cylinder", "boolean_cut"],
            "output_formats": ["STEP", "STL"],
            "assumptions": ["Z-axis orientation", "Default centered coordinate system"],
            "clarification_required": clarification,
            "clarification_questions": questions,
        }
