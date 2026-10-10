import pytest
import uuid
from pathlib import Path
from backend.app.schemas import CADSpecification
from backend.app.cad_executor import CADExecutor
from backend.app.geometry_validator import GeometryValidator


def test_cad_execution_and_geometry_validation():
    executor = CADExecutor()
    validator = GeometryValidator()
    
    script = """import FreeCAD
import Part

outer_radius = 30.0
height = 100.0
wall_thickness = 3.0
bottom_thickness = 4.0
inner_radius = outer_radius - wall_thickness
"""
    job_id = f"test_val_{uuid.uuid4().hex[:8]}"
    report = executor.execute(script, job_id=job_id)
    assert report.execution_status == "success"
    assert len(report.generated_artifacts) > 0

    spec = CADSpecification(
        object_description="Hollow cylindrical container",
        parameters={"outer_radius": 30.0, "height": 100.0, "wall_thickness": 3.0, "bottom_thickness": 4.0},
        output_formats=["STEP", "STL"],
    )
    job_dir = executor.artifacts_base / job_id
    val_report = validator.validate(job_dir, spec, report)
    
    assert val_report.valid is True
    assert val_report.solid_count == 1
    assert val_report.bounding_box["dz"] == 100.0
    assert val_report.bounding_box["dx"] == 60.0
    assert all(chk.passed for chk in val_report.checks)
