import asyncio
import datetime
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMSMSMiddleware if False else None
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.app.config import Settings, get_settings, update_runtime_settings
from backend.app.schemas import (
    ProviderInfo,
    ProviderSettingsUpdate,
    ProviderTestRequest,
    ProviderTestResponse,
    GenerateCADRequest,
    ExecuteCADRequest,
    CADJobStatus,
    ArtifactInfo,
)
from backend.app.llm_provider import ProviderFactory
from backend.app.cad_executor import CADExecutor
from backend.app.geometry_validator import GeometryValidator
from backend.app.graph import create_cad_workflow
from backend.app.state import CADWorkflowState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title="Text-to-CAD RAG API",
    description="Modular Text-to-CAD system with hybrid retrieval, dynamic LLM provider switching, and isolated CAD execution.",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory Job Store
JOB_STORE: Dict[str, CADJobStatus] = {}


# -----------------------------------------------------------------------------
# Provider & Settings Endpoints
# -----------------------------------------------------------------------------

@app.get("/providers", response_model=List[ProviderInfo])
def get_providers(settings: Settings = Depends(get_settings)):
    """Returns available provider types and non-secret configuration status."""
    current = settings.default_llm_provider
    
    # Check Ollama availability
    ollama_avail = False
    ollama_models = []
    try:
        ollama_test = ProviderFactory.get_provider("ollama", settings).test_connection()
        ollama_avail = ollama_test.success
        if ollama_avail:
            ollama_models = [settings.ollama_model]
    except Exception:
        pass

    return [
        ProviderInfo(
            provider_id="ollama",
            name="Ollama (Local LLM)",
            available=ollama_avail,
            current=(current == "ollama"),
            models=[settings.ollama_model, "qwen3:latest", "qwen2.5-coder:7b", "deepseek-coder:6.7b"],
            description="Locally running private inference via Ollama server.",
        ),
        ProviderInfo(
            provider_id="cloud",
            name="Cloud LLM (OpenAI / OpenRouter API)",
            available=bool(settings.cloud_api_key),
            current=(current == "cloud"),
            models=[settings.cloud_model, "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-chat"],
            description="Cloud API provider with configurable API key and base URL.",
        ),
        ProviderInfo(
            provider_id="mock",
            name="Deterministic Mock Provider (Offline)",
            available=True,
            current=(current == "mock"),
            models=["mock-qwen-cad"],
            description="Offline mock provider for testing workflow and UI transitions.",
        ),
    ]


@app.post("/providers/test", response_model=ProviderTestResponse)
def test_provider(req: ProviderTestRequest, settings: Settings = Depends(get_settings)):
    """Tests connectivity and latency of the selected provider and model."""
    try:
        # Build transient settings for test
        test_settings = settings.model_copy()
        if req.provider == "cloud":
            test_settings.cloud_provider = req.cloud_provider or test_settings.cloud_provider
            test_settings.cloud_api_key = req.cloud_api_key or test_settings.cloud_api_key
            test_settings.cloud_base_url = req.cloud_base_url or test_settings.cloud_base_url
            test_settings.cloud_model = req.cloud_model or test_settings.cloud_model
        elif req.provider == "ollama":
            test_settings.ollama_base_url = req.ollama_base_url or test_settings.ollama_base_url
            test_settings.ollama_model = req.ollama_model or test_settings.ollama_model

        provider = ProviderFactory.get_provider(req.provider, test_settings)
        return provider.test_connection()
    except Exception as e:
        return ProviderTestResponse(
            success=False,
            provider=req.provider,
            model=req.cloud_model or req.ollama_model or "unknown",
            message=f"Connection test failed: {str(e)}",
            capabilities=[],
        )


@app.post("/settings/provider")
def update_provider_settings(req: ProviderSettingsUpdate):
    """Updates runtime provider settings dynamically without server restart."""
    updates = {"default_llm_provider": req.provider}
    if req.cloud_provider:
        updates["cloud_provider"] = req.cloud_provider
    if req.cloud_api_key:
        updates["cloud_api_key"] = req.cloud_api_key
    if req.cloud_base_url:
        updates["cloud_base_url"] = req.cloud_base_url
    if req.cloud_model:
        updates["cloud_model"] = req.cloud_model
    if req.ollama_base_url:
        updates["ollama_base_url"] = req.ollama_base_url
    if req.ollama_model:
        updates["ollama_model"] = req.ollama_model

    new_settings = update_runtime_settings(**updates)
    return {
        "status": "success",
        "current_provider": new_settings.default_llm_provider,
        "message": f"Active LLM provider switched to '{new_settings.default_llm_provider}'.",
    }


@app.get("/cad/engine")
def get_cad_engine_status(settings: Settings = Depends(get_settings)):
    """Returns detected FreeCAD runtime status."""
    executor = CADExecutor(settings)
    return executor.get_cad_engine_info()


# -----------------------------------------------------------------------------
# CAD Generation & Execution Endpoints
# -----------------------------------------------------------------------------

async def run_cad_job_async(job_id: str, prompt: str, mock_mode: bool, settings: Settings):
    """Background task executing the LangGraph CAD state machine."""
    current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    job_status = JOB_STORE[job_id]

    try:
        initial_state: CADWorkflowState = {
            "job_id": job_id,
            "original_user_request": prompt,
            "selected_llm_provider": settings.default_llm_provider,
            "model_identifier": settings.ollama_model if settings.default_llm_provider == "ollama" else settings.cloud_model,
            "mock_mode": mock_mode,
            "repair_attempt_count": 0,
            "max_repair_attempts": settings.max_repair_attempts,
            "repair_history": [],
            "artifact_metadata": [],
        }

        job_status.status = "extracting"
        app_graph = create_cad_workflow(settings)

        # Run state machine
        final_state = await asyncio.to_thread(app_graph.invoke, initial_state)

        # Update in-memory job status
        job_status.specification = final_state.get("structured_specification")
        job_status.generated_script = final_state.get("generated_script")
        job_status.retrieval_diagnostics = final_state.get("retrieval_diagnostics")
        job_status.execution_report = final_state.get("execution_report")
        job_status.validation_report = final_state.get("geometry_validation_report")
        job_status.repair_attempts = final_state.get("repair_history", [])
        job_status.artifacts = final_state.get("artifact_metadata", [])
        job_status.preview_url = final_state.get("preview_url")
        job_status.error_message = final_state.get("error_message")
        
        if final_state.get("clarification_required"):
            job_status.status = "clarification_needed"
        elif final_state.get("final_status") == "completed":
            job_status.status = "completed"
        else:
            job_status.status = "failed"

    except Exception as e:
        logger.exception(f"Job {job_id} encountered unexpected failure: {e}")
        job_status.status = "failed"
        job_status.error_message = str(e)
    finally:
        job_status.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()


@app.post("/generate-cad", response_model=CADJobStatus)
async def generate_cad(
    req: GenerateCADRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Initiates natural-language CAD generation workflow."""
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    job_status = CADJobStatus(
        job_id=job_id,
        status="pending",
        request_prompt=req.prompt,
        created_at=now,
        updated_at=now,
    )
    JOB_STORE[job_id] = job_status

    background_tasks.add_task(run_cad_job_async, job_id, req.prompt, req.mock_mode, settings)
    return job_status


@app.post("/cad/execute", response_model=CADJobStatus)
def execute_cad_script(
    req: ExecuteCADRequest,
    settings: Settings = Depends(get_settings),
):
    """Executes a supplied (or user-edited) script in the isolated CAD runtime with validation."""
    job_id = req.job_id or f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    executor = CADExecutor(settings)
    report = executor.execute(
        script=req.script,
        job_id=job_id,
        mock_mode=req.mock_mode,
    )

    # Perform geometry validation if execution succeeded
    val_report = None
    preview_url = None
    if report.execution_status == "success":
        from backend.app.schemas import CADSpecification
        spec = CADSpecification(
            object_description="Custom user edited CAD script",
            parameters=req.expected_dimensions or {"outer_radius": 30.0, "height": 100.0, "wall_thickness": 3.0, "bottom_thickness": 4.0},
            output_formats=req.output_formats,
        )
        validator = GeometryValidator()
        job_dir = executor.artifacts_base / job_id
        val_report = validator.validate(job_dir, spec, report)
        
        # Check preview
        if any(a.is_preview for a in report.generated_artifacts):
            preview_url = f"/cad/jobs/{job_id}/preview"

    job_status = CADJobStatus(
        job_id=job_id,
        status="completed" if (report.execution_status == "success" and val_report and val_report.valid) else "failed",
        request_prompt="Direct Script Execution",
        generated_script=req.script,
        execution_report=report,
        validation_report=val_report,
        artifacts=report.generated_artifacts,
        preview_url=preview_url,
        error_message=report.stderr if report.execution_status != "success" else (val_report.failure_summary if val_report and not val_report.valid else None),
        created_at=now,
        updated_at=now,
    )
    JOB_STORE[job_id] = job_status
    return job_status


@app.get("/cad/jobs/{job_id}", response_model=CADJobStatus)
def get_job_status(job_id: str):
    """Returns status and reports for a given CAD job."""
    if job_id not in JOB_STORE:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JOB_STORE[job_id]


@app.get("/cad/jobs/{job_id}/preview")
def get_preview_artifact(job_id: str, settings: Settings = Depends(get_settings)):
    """Serves the verified 3D preview mesh (STL or GLB) for Three.js."""
    job_dir = Path(settings.artifacts_dir) / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job directory not found.")

    # Check for GLB first, then STL
    glb_files = list(job_dir.glob("*.glb")) + list(job_dir.glob("*.GLB"))
    if glb_files:
        return FileResponse(
            str(glb_files[0].resolve()),
            media_type="model/gltf-binary",
            filename=glb_files[0].name,
        )

    stl_files = list(job_dir.glob("*.stl")) + list(job_dir.glob("*.STL"))
    if stl_files:
        return FileResponse(
            str(stl_files[0].resolve()),
            media_type="model/stl",
            filename=stl_files[0].name,
        )

    raise HTTPException(status_code=404, detail="No preview artifact (STL or GLB) available for this job.")


@app.get("/cad/jobs/{job_id}/artifacts/{format_name}")
def download_artifact(job_id: str, format_name: str, settings: Settings = Depends(get_settings)):
    """Downloads an artifact in a supported format with path sanitization."""
    # Sanitize job_id and format_name
    safe_job_id = Path(job_id).name
    job_dir = (Path(settings.artifacts_dir) / safe_job_id).resolve()
    
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    format_lower = format_name.lower().lstrip(".")
    matching = [
        f for f in job_dir.iterdir()
        if f.is_file() and f.suffix.lower().lstrip(".") == format_lower
    ]

    if not matching:
        raise HTTPException(status_code=404, detail=f"No artifact with format '{format_name}' found for job '{job_id}'.")

    target_file = matching[0]
    return FileResponse(
        str(target_file),
        filename=target_file.name,
        media_type="application/octet-stream",
    )


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "text-to-cad-rag"}
