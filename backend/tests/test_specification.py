import pytest
from backend.app.schemas import CADSpecification
from backend.app.requirement_extractor import RequirementExtractor, normalize_units
from backend.app.llm_provider import MockProvider


def test_normalize_units():
    val, u = normalize_units("10 cm")
    assert val == 100.0
    assert u == "mm"

    val_in, u_in = normalize_units("2 in")
    assert val_in == 50.8
    assert u_in == "mm"

    val_mm, u_mm = normalize_units("45 mm")
    assert val_mm == 45.0
    assert u_mm == "mm"


def test_specification_extraction_container():
    provider = MockProvider()
    extractor = RequirementExtractor(provider)
    prompt = "Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and bottom thickness of 4 mm."
    
    spec = extractor.extract(prompt)
    assert isinstance(spec, CADSpecification)
    assert spec.cad_engine == "FreeCAD"
    assert spec.units == "mm"
    assert spec.parameters["outer_radius"] == 30.0
    assert spec.parameters["height"] == 100.0
    assert spec.parameters["wall_thickness"] == 3.0
    assert spec.parameters["bottom_thickness"] == 4.0
    assert spec.parameters["inner_radius"] == 27.0
    assert spec.clarification_required is False


def test_clarification_on_ambiguous_request():
    provider = MockProvider()
    extractor = RequirementExtractor(provider)
    prompt = "Make a container for me"
    
    spec = extractor.extract(prompt)
    assert spec.clarification_required is True
    assert len(spec.clarification_questions) > 0


def test_invalid_dimension_rejection():
    provider = MockProvider()
    extractor = RequirementExtractor(provider)
    # Wall thickness 35mm exceeds outer radius 30mm
    data = {
        "cad_engine": "FreeCAD",
        "units": "mm",
        "object_description": "Invalid container",
        "parameters": {"outer_radius": 30.0, "wall_thickness": 35.0, "height": 100.0},
        "features": [],
    }
    spec = extractor._validate_and_normalize_specification(data, "Invalid container")
    assert spec.clarification_required is True
    assert any("Wall thickness" in q for q in spec.clarification_questions)
