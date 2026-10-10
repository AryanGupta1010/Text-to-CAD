import pytest
import uuid
from backend.app.config import get_settings
from backend.app.graph import create_cad_workflow
from backend.app.state import CADWorkflowState


def test_end_to_end_pipeline_success():
    settings = get_settings()
    job_id = f"test_e2e_{uuid.uuid4().hex[:8]}"
    prompt = "Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and bottom thickness of 4 mm. Export it as a STEP file."

    initial_state: CADWorkflowState = {
        "job_id": job_id,
        "original_user_request": prompt,
        "selected_llm_provider": "mock",
        "model_identifier": "mock-qwen-cad",
        "mock_mode": False,
        "repair_attempt_count": 0,
        "max_repair_attempts": 2,
        "repair_history": [],
        "artifact_metadata": [],
    }

    workflow = create_cad_workflow(settings)
    final_state = workflow.invoke(initial_state)

    assert final_state["final_status"] == "completed"
    assert final_state["is_valid_geometry"] is True
    assert final_state["geometry_validation_report"].valid is True
    assert len(final_state["artifact_metadata"]) > 0
    # Verified that STEP and STL exist
    formats = [a.format for a in final_state["artifact_metadata"]]
    assert "STEP" in formats
    assert "STL" in formats
