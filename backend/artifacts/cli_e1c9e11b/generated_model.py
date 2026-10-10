{
  "cad_engine": "FreeCAD",
  "units": "mm",
  "object_description": "Hollow cylindrical container with closed bottom and open top",
  "features": [
    {
      "feature_type": "cylinder",
      "dimensions": {
        "radius": 30.0,
        "height": 100.0
      },
      "parameters": {
        "outer_cylinder": true
      },
      "geometric_constraints": [
        "concentric"
      ],
      "dependencies": [],
      "expected_properties": {
        "is_solid": true
      }
    },
    {
      "feature_type": "cylinder_pocket",
      "dimensions": {
        "radius": 27.0,
        "height": 96.0,
        "z_offset": 4.0
      },
      "parameters": {
        "inner_cylinder": true
      },
      "geometric_constraints": [
        "concentric",
        "coaxial"
      ],
      "dependencies": [
        "cylinder"
      ],
      "expected_properties": {
        "subtraction": true
      }
    }
  ],
  "parameters": {
    "outer_radius": 30.0,
    "height": 100.0,
    "wall_thickness": 3.0,
    "bottom_thickness": 4.0,
    "inner_radius": 27.0
  },
  "constraints": [
    "concentric",
    "closed_bottom",
    "open_top"
  ],
  "operations": [
    "create_outer_cylinder",
    "create_inner_cylinder",
    "translate_inner_cylinder",
    "boolean_cut"
  ],
  "output_formats": [
    "STEP",
    "STL"
  ],
  "assumptions": [
    "Z-axis alignment",
    "Cylindrical symmetry"
  ],
  "clarification_required": false,
  "clarification_questions": []
}