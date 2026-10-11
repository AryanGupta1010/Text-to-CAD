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
      "feature_type": "string (e.g. cylinder, box, pocket, hole, fillet, l_shaped_pipe)",
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
  "operations": ["create_path_wire", "create_outer_profile", "create_inner_profile", "sweep", "cut"],
  "output_formats": ["STEP", "STL"],
  "assumptions": ["assumption 1"],
  "clarification_required": false,
  "clarification_questions": []
}

CRITICAL RULES:
1. Normalize all units to "mm". For example, if given 10 cm, convert to 100 mm.
2. For bent, swept, or L-shaped pipes, extract outer_radius, inner_radius, length_1, length_2, and bend_radius with feature_type "l_shaped_pipe".
3. Verify dimensional consistency: inner dimensions must fit inside outer dimensions.
4. If essential geometric parameters (like primary dimensions or thickness for a hollow part) are missing or materially ambiguous, set "clarification_required": true and list targeted "clarification_questions".
5. Do NOT hallucinate unspecified critical dimensions. Clearly list any inferred defaults in "assumptions".
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
            spec = self._validate_and_normalize_specification(data, user_prompt)
            return spec
        except Exception as e:
            logger.warning(f"LLM specification extraction encountered issue: {e}. Executing intelligent rule-based extraction fallback.")
            data = self._rule_based_fallback(user_prompt)
            spec = self._validate_and_normalize_specification(data, user_prompt)
            return spec

    def _validate_and_normalize_specification(self, data: dict, original_prompt: str) -> CADSpecification:
        # Guarantee required fields
        data.setdefault("cad_engine", "FreeCAD")
        data.setdefault("units", "mm")
        data.setdefault("object_description", original_prompt)
        data.setdefault("output_formats", ["STEP", "STL"])
        data.setdefault("assumptions", [])
        data.setdefault("clarification_questions", [])
        if "clarification_required" not in data:
            data["clarification_required"] = False

        params = data.get("parameters", {})
        if not isinstance(params, dict):
            params = {}

        # Ingest dimensions dict if LLM placed them there (e.g. {"dimensions": {"length": "50mm"}})
        if "dimensions" in data and isinstance(data["dimensions"], dict):
            for k, v in data["dimensions"].items():
                if k not in params:
                    try:
                        val, _ = normalize_units(str(v))
                        params[k] = val
                    except Exception:
                        params[k] = v

        # Ingest root-level dimensional keys if present
        for key in ["length", "width", "height", "radius", "outer_radius", "inner_radius", "diameter", "outer_diameter", "inner_diameter", "side", "size", "thickness", "wall_thickness", "bottom_thickness", "length_1", "length_2", "bend_radius"]:
            if key in data and key not in params:
                try:
                    val, _ = normalize_units(str(data[key]))
                    params[key] = val
                except Exception:
                    params[key] = data[key]

        # Normalize any string units inside params
        for k, v in list(params.items()):
            if isinstance(v, str):
                try:
                    val, _ = normalize_units(v)
                    params[k] = val
                except Exception:
                    pass

        # Handle diameter / radius equivalence
        if "diameter" in params and "radius" not in params:
            try: params["radius"] = float(params["diameter"]) / 2.0
            except (ValueError, TypeError): pass
        if "outer_diameter" in params and "outer_radius" not in params:
            try: params["outer_radius"] = float(params["outer_diameter"]) / 2.0
            except (ValueError, TypeError): pass
        if "inner_diameter" in params and "inner_radius" not in params:
            try: params["inner_radius"] = float(params["inner_diameter"]) / 2.0
            except (ValueError, TypeError): pass

        # Handle cube side/size equivalence
        if "side" in params and "length" not in params:
            params["length"] = params["side"]
            params["width"] = params["side"]
            params["height"] = params["side"]
        elif "size" in params and "length" not in params:
            params["length"] = params["size"]
            params["width"] = params["size"]
            params["height"] = params["size"]

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

        # Ensure features list is well-formed
        raw_features = data.get("features", [])
        features = []
        if isinstance(raw_features, list) and len(raw_features) > 0:
            for f in raw_features:
                if isinstance(f, dict):
                    f.setdefault("dimensions", params)
                    f.setdefault("parameters", {})
                    f.setdefault("geometric_constraints", [])
                    f.setdefault("dependencies", [])
                    f.setdefault("expected_properties", {})
                    features.append(f)
                elif isinstance(f, str):
                    features.append({
                        "feature_type": f,
                        "dimensions": params,
                        "parameters": {},
                        "geometric_constraints": [],
                        "dependencies": [],
                        "expected_properties": {}
                    })

        if not features:
            shape_type = str(data.get("type", "") or data.get("shape", "") or data.get("feature_type", "")).lower()
            prompt_lower = original_prompt.lower()

            is_l_pipe = any(k in prompt_lower or k in shape_type for k in ["l-shape", "l-shaped", "elbow", "90-degree", "90 degree", "curved bend", "curved pipe"]) or ("pipe" in prompt_lower and ("bend" in prompt_lower or "curve" in prompt_lower))
            is_box = any(k in prompt_lower or k in shape_type for k in ["cube", "box", "block", "enclosure", "rectangular plate", "plate", "prism", "cuboid"]) or ("length" in params and "width" in params and "height" in params)
            is_sphere = any(k in prompt_lower or k in shape_type for k in ["sphere", "ball", "globe"])
            is_bushing = not is_l_pipe and any(k in prompt_lower or k in shape_type for k in ["bushing", "flanged pipe", "tube", "washer", "spacer", "sleeve"])
            is_container = not is_l_pipe and not is_bushing and (any(k in prompt_lower or k in shape_type for k in ["container", "cup", "can", "pot", "pocket"]) or ("hollow" in prompt_lower and "cylinder" in prompt_lower))
            is_solid_cyl = not is_l_pipe and not is_container and not is_bushing and (any(k in prompt_lower or k in shape_type for k in ["cylinder", "rod", "pin", "shaft", "disc", "disk", "round bar"]) or ("radius" in params and "height" in params))

            if is_l_pipe:
                features.append({
                    "feature_type": "l_shaped_pipe",
                    "dimensions": params,
                    "parameters": {"shape": "elbow_bend"},
                    "geometric_constraints": ["smooth_bend"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True, "is_hollow": True}
                })
            elif is_box:
                features.append({
                    "feature_type": "box",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["orthogonal"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
            elif is_sphere:
                features.append({
                    "feature_type": "sphere",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["spherical_symmetry"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
            elif is_bushing:
                features.append({
                    "feature_type": "cylinder",
                    "dimensions": params,
                    "parameters": {"role": "outer"},
                    "geometric_constraints": ["concentric"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                features.append({
                    "feature_type": "cylinder_pocket",
                    "dimensions": params,
                    "parameters": {"role": "inner"},
                    "geometric_constraints": ["coaxial"],
                    "dependencies": ["cylinder"],
                    "expected_properties": {"subtraction": True}
                })
            elif is_container:
                features.append({
                    "feature_type": "cylinder",
                    "dimensions": params,
                    "parameters": {"role": "outer"},
                    "geometric_constraints": ["concentric"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                features.append({
                    "feature_type": "cylinder_pocket",
                    "dimensions": params,
                    "parameters": {"role": "inner"},
                    "geometric_constraints": ["coaxial"],
                    "dependencies": ["cylinder"],
                    "expected_properties": {"subtraction": True}
                })
            elif is_solid_cyl or "radius" in params or "diameter" in params:
                features.append({
                    "feature_type": "cylinder",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["cylindrical_symmetry"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
            else:
                features.append({
                    "feature_type": shape_type or "custom_solid",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": [],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })

        data["features"] = features
        data["parameters"] = params
        return CADSpecification(**data)

    def _rule_based_fallback(self, prompt: str) -> dict:
        """Deterministic regex-based fallback to extract parameters for any shape from text."""
        lower = prompt.lower()

        is_l_pipe = any(k in lower for k in ["l-shape", "l-shaped", "elbow", "90-degree", "90 degree", "curved bend", "curved pipe"]) or ("pipe" in lower and ("bend" in lower or "bent" in lower or "curve" in lower))
        is_box = not is_l_pipe and (any(k in lower for k in ["cube", "box", "block", "enclosure", "rectangular plate", "plate", "prism", "cuboid", "rectangular", "square"]) or bool(re.search(r"\d+\s*(?:x|\*)\s*\d+\s*(?:x|\*)\s*\d+", lower)))
        is_sphere = not is_l_pipe and any(k in lower for k in ["sphere", "spherical", "ball", "globe"])
        is_bushing = not is_l_pipe and any(k in lower for k in ["bushing", "flanged pipe", "straight pipe", "tube", "washer", "spacer", "sleeve"])
        is_hollow_container = not is_l_pipe and not is_bushing and (any(k in lower for k in ["container", "cup", "can", "pot", "pocket"]) or ("hollow" in lower and "cylinder" in lower))
        is_solid_cylinder = not is_l_pipe and not is_hollow_container and not is_bushing and any(k in lower for k in ["cylinder", "rod", "pin", "shaft", "disc", "disk", "round bar", "solid cylinder"])


        params = {}
        features = []
        operations = []
        constraints = []

        # 0. L-Shaped / Bent Pipe
        if is_l_pipe:
            od_m = re.search(r"outer\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            outer_r = float(od_m.group(1)) / 2.0 if od_m else 10.0
            if not od_m:
                or_m = re.search(r"outer\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
                if or_m:
                    outer_r = float(or_m.group(1))

            id_m = re.search(r"inner\s*diameter\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            inner_r = float(id_m.group(1)) / 2.0 if id_m else 7.0
            if not id_m:
                ir_m = re.search(r"inner\s*radius\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
                if ir_m:
                    inner_r = float(ir_m.group(1))

            side_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*long", lower)
            l1 = float(side_m.group(1)) if side_m else 100.0
            l2 = l1
            l1_m = re.search(r"(?:length\s*1|arm\s*1|section\s*1)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if l1_m:
                l1 = float(l1_m.group(1))
            l2_m = re.search(r"(?:length\s*2|arm\s*2|section\s*2)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if l2_m:
                l2 = float(l2_m.group(1))

            bend_r = 30.0
            br_m = re.search(r"(?:bend\s*radius|curve\s*radius)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if br_m:
                bend_r = float(br_m.group(1))

            params = {
                "outer_radius": outer_r,
                "inner_radius": inner_r,
                "length_1": l1,
                "length_2": l2,
                "bend_radius": bend_r,
                "bend_angle": 90.0,
                "wall_thickness": round(outer_r - inner_r, 4),
            }
            features.append({
                "feature_type": "l_shaped_pipe",
                "dimensions": params,
                "parameters": {"shape": "elbow_bend", "bend_angle": 90.0},
                "geometric_constraints": ["tangent_continuous", "smooth_bend"],
                "dependencies": [],
                "expected_properties": {"is_solid": True, "is_hollow": True}
            })
            operations = ["create_path_wire", "create_outer_profile", "create_inner_profile", "sweep_outer", "sweep_inner", "boolean_cut"]
            constraints = ["90_degree_bend", "hollow"]

        # 1. Box / Cube
            cube_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*cube|(?:cube\s*(?:of|with\s*side)?|side)\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)", lower)
            if cube_m:
                s = float(cube_m.group(1) or cube_m.group(2))
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
        elif is_hollow_container:
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

        # 6. Smart Generic Fallback (matches numeric dimensions to geometric forms)
        else:
            nums = [float(x) for x in re.findall(r"\b\d+(?:\.\d+)?\b", lower)]
            dim3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)", lower)
            if dim3:
                l, w, h = float(dim3.group(1)), float(dim3.group(2)), float(dim3.group(3))
                params = {"length": l, "width": w, "height": h}
                features.append({
                    "feature_type": "box",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["orthogonal"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                operations = ["create_box"]
                constraints = ["orthogonal"]
            elif any(w in lower for w in ["radius", "diameter", "dia", "round", "circular"]) or (len(nums) == 2 and any(w in lower for w in ["height", "len", "deep"])):
                r = nums[0] if len(nums) > 0 else 20.0
                if "diameter" in lower or "dia" in lower:
                    r = r / 2.0
                h = nums[1] if len(nums) > 1 else 50.0
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
            elif len(nums) >= 3:
                l, w, h = nums[0], nums[1], nums[2]
                params = {"length": l, "width": w, "height": h}
                features.append({
                    "feature_type": "box",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["orthogonal"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                operations = ["create_box"]
                constraints = ["orthogonal"]
            elif len(nums) == 1:
                s = nums[0]
                params = {"length": s, "width": s, "height": s}
                features.append({
                    "feature_type": "box",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["orthogonal"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                operations = ["create_box"]
                constraints = ["orthogonal"]
            else:
                params = {"length": 50.0, "width": 50.0, "height": 50.0}
                features.append({
                    "feature_type": "box",
                    "dimensions": params,
                    "parameters": {},
                    "geometric_constraints": ["orthogonal"],
                    "dependencies": [],
                    "expected_properties": {"is_solid": True}
                })
                operations = ["create_box"]
                constraints = ["orthogonal"]

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
