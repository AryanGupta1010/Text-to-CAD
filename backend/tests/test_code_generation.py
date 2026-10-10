import pytest
from backend.app.code_generator import perform_static_checks, CADCodeGenerator
from backend.app.llm_provider import MockProvider
from backend.app.schemas import CADSpecification


def test_static_checks_safe_code():
    safe_code = """import FreeCAD
import Part

doc = FreeCAD.newDocument("Doc")
cyl = Part.makeCylinder(30, 100)
cyl.exportStep("model.step")
cyl.exportStl("model.stl")
"""
    passed, errors = perform_static_checks(safe_code)
    assert passed is True
    assert len(errors) == 0


def test_static_checks_unsafe_code():
    unsafe_code = """import os
import subprocess
os.system("rm -rf /")
"""
    passed, errors = perform_static_checks(unsafe_code)
    assert passed is False
    assert any("Security check failed" in e for e in errors)


def test_static_checks_syntax_error():
    syntax_err_code = "def broken(: print('hello')"
    passed, errors = perform_static_checks(syntax_err_code)
    assert passed is False
    assert any("SyntaxError" in e for e in errors)


def test_code_generator():
    provider = MockProvider()
    generator = CADCodeGenerator(provider)
    spec = CADSpecification(
        object_description="Hollow container",
        parameters={"outer_radius": 30.0, "height": 100.0, "wall_thickness": 3.0, "bottom_thickness": 4.0},
    )
    res = generator.generate(spec, "Retrieved context snippet", ["doc_1"])
    assert "script" in res
    assert "FreeCAD" in res["script"]
    assert res["static_checks_passed"] is True
