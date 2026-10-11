import asyncio
import datetime
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
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
    
    # Fast non-blocking check for Ollama server
    ollama_avail = False
    try:
        import httpx
        with httpx.Client(timeout=1.5) as client:
            resp = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            ollama_avail = (resp.status_code == 200)
    except Exception:
        pass

    return [
        ProviderInfo(
            provider_id="openrouter",
            name="OpenRouter (Universal API)",
            available=bool(settings.openrouter_api_key),
            current=(current == "openrouter"),
            models=[settings.openrouter_model, "anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct", "google/gemini-2.0-flash-001", "qwen/qwen-2.5-coder-32b-instruct"],
            description="Access cutting-edge models (Claude 3.5, DeepSeek, Llama 3.3) with OpenRouter API key.",
        ),
        ProviderInfo(
            provider_id="google_studio",
            name="Google AI Studio (Gemini)",
            available=bool(settings.google_studio_api_key),
            current=(current == "google_studio"),
            models=[settings.google_studio_model, "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.5-flash"],
            description="Fast, reliable reasoning & CAD Python code generation via Google Gemini API.",
        ),
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
            name="Cloud LLM (OpenAI API)",
            available=bool(settings.cloud_api_key),
            current=(current == "cloud"),
            models=[settings.cloud_model, "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-chat"],
            description="Direct OpenAI-compatible cloud endpoint with configurable API key and base URL.",
        ),
        ProviderInfo(
            provider_id="mock",
            name="Deterministic Mock Provider (Offline)",
            available=True,
            current=(current == "mock"),
            models=["mock-cad-engine"],
            description="Offline mock provider for deterministic verification and UI testing.",
        ),
    ]


@app.post("/providers/test", response_model=ProviderTestResponse)
def test_provider(req: ProviderTestRequest, settings: Settings = Depends(get_settings)):
    """Tests connectivity and latency of the selected provider and model."""
    try:
        # Build transient settings for test
        test_settings = settings.model_copy()
        if req.provider == "openrouter":
            test_settings.openrouter_api_key = req.openrouter_api_key or test_settings.openrouter_api_key
            test_settings.openrouter_base_url = req.openrouter_base_url or test_settings.openrouter_base_url
            test_settings.openrouter_model = req.openrouter_model or test_settings.openrouter_model
        elif req.provider == "google_studio":
            test_settings.google_studio_api_key = req.google_studio_api_key or test_settings.google_studio_api_key
            test_settings.google_studio_base_url = req.google_studio_base_url or test_settings.google_studio_base_url
            test_settings.google_studio_model = req.google_studio_model or test_settings.google_studio_model
        elif req.provider == "cloud":
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
            model=req.openrouter_model or req.google_studio_model or req.cloud_model or req.ollama_model or "unknown",
            message=f"Connection test failed: {str(e)}",
            capabilities=[],
        )


@app.post("/settings/provider")
def update_provider_settings(req: ProviderSettingsUpdate):
    """Updates runtime provider settings dynamically without server restart."""
    updates = {"default_llm_provider": req.provider}
    if req.openrouter_api_key is not None:
        updates["openrouter_api_key"] = req.openrouter_api_key
    if req.openrouter_base_url:
        updates["openrouter_base_url"] = req.openrouter_base_url
    if req.openrouter_model:
        updates["openrouter_model"] = req.openrouter_model

    if req.google_studio_api_key is not None:
        updates["google_studio_api_key"] = req.google_studio_api_key
    if req.google_studio_base_url:
        updates["google_studio_base_url"] = req.google_studio_base_url
    if req.google_studio_model:
        updates["google_studio_model"] = req.google_studio_model

    if req.cloud_provider:
        updates["cloud_provider"] = req.cloud_provider
    if req.cloud_api_key is not None:
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
        if settings.default_llm_provider == "openrouter":
            model_ident = settings.openrouter_model
        elif settings.default_llm_provider == "google_studio":
            model_ident = settings.google_studio_model
        elif settings.default_llm_provider == "ollama":
            model_ident = settings.ollama_model
        elif settings.default_llm_provider == "cloud":
            model_ident = settings.cloud_model
        else:
            model_ident = "mock-cad-engine"

        initial_state: CADWorkflowState = {
            "job_id": job_id,
            "original_user_request": prompt,
            "selected_llm_provider": settings.default_llm_provider,
            "model_identifier": model_ident,
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

    # Build job-scoped settings based on request parameters
    job_settings = settings.model_copy()
    if req.provider:
        job_settings.default_llm_provider = req.provider
        if req.provider == "google_studio":
            if req.api_key:
                job_settings.google_studio_api_key = req.api_key
            if req.model:
                job_settings.google_studio_model = req.model
            if req.base_url:
                job_settings.google_studio_base_url = req.base_url
        elif req.provider == "openrouter":
            if req.api_key:
                job_settings.openrouter_api_key = req.api_key
            if req.model:
                job_settings.openrouter_model = req.model
            if req.base_url:
                job_settings.openrouter_base_url = req.base_url
        elif req.provider == "cloud":
            if req.api_key:
                job_settings.cloud_api_key = req.api_key
            if req.model:
                job_settings.cloud_model = req.model
            if req.base_url:
                job_settings.cloud_base_url = req.base_url
        elif req.provider == "ollama":
            if req.model:
                job_settings.ollama_model = req.model
            if req.base_url:
                job_settings.ollama_base_url = req.base_url

        # Sync global runtime settings to keep them in sync
        update_runtime_settings(
            default_llm_provider=job_settings.default_llm_provider,
            google_studio_api_key=job_settings.google_studio_api_key,
            google_studio_model=job_settings.google_studio_model,
            google_studio_base_url=job_settings.google_studio_base_url,
            openrouter_api_key=job_settings.openrouter_api_key,
            openrouter_model=job_settings.openrouter_model,
            openrouter_base_url=job_settings.openrouter_base_url,
        )

    job_status = CADJobStatus(
        job_id=job_id,
        status="pending",
        request_prompt=req.prompt,
        created_at=now,
        updated_at=now,
    )
    JOB_STORE[job_id] = job_status

    background_tasks.add_task(run_cad_job_async, job_id, req.prompt, req.mock_mode, job_settings)
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
            parameters=req.expected_dimensions or {},
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
        status="completed" if report.execution_status == "success" else "failed",
        request_prompt="Direct Script Execution",
        generated_script=req.script,
        execution_report=report,
        validation_report=val_report,
        artifacts=report.generated_artifacts,
        preview_url=preview_url,
        error_message=report.stderr if report.execution_status != "success" else None,
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
    safe_job_id = Path(job_id).name
    backend_base = Path(__file__).resolve().parent.parent
    
    # Check all possible canonical artifact locations
    candidates = [
        Path(settings.artifacts_dir) / safe_job_id,
        backend_base / "artifacts" / safe_job_id,
        backend_base.parent / "backend" / "artifacts" / safe_job_id,
        backend_base / "backend" / "artifacts" / safe_job_id,
    ]
    job_dir = next((c for c in candidates if c.exists()), None)

    if not job_dir:
        job_status = JOB_STORE.get(safe_job_id)
        if job_status and job_status.status in ["pending", "extracting", "retrieving", "generating", "executing"]:
            raise HTTPException(status_code=425, detail="CAD model generation is currently in progress. Preview will be ready once execution finishes.")
        if job_status and job_status.status == "failed":
            raise HTTPException(status_code=404, detail=f"CAD model generation failed: {job_status.error_message or 'Execution failure'}")
        if job_status and job_status.status == "clarification_needed":
            raise HTTPException(status_code=404, detail="Clarification needed for missing dimensions before 3D preview can be built.")
        raise HTTPException(status_code=404, detail=f"No preview artifacts generated for job '{safe_job_id}'.")

    # Check for GLB first, then STL
    glb_files = list(job_dir.glob("*.glb")) + list(job_dir.glob("*.GLB"))
    if glb_files and glb_files[0].stat().st_size > 0:
        return FileResponse(
            str(glb_files[0].resolve()),
            media_type="model/gltf-binary",
            filename=glb_files[0].name,
        )

    stl_files = list(job_dir.glob("*.stl")) + list(job_dir.glob("*.STL"))
    if stl_files and stl_files[0].stat().st_size > 0:
        return FileResponse(
            str(stl_files[0].resolve()),
            media_type="model/stl",
            filename=stl_files[0].name,
        )

    # Check if job failed
    job_status = JOB_STORE.get(safe_job_id)
    if job_status and job_status.status in ["pending", "extracting", "retrieving", "generating", "executing"]:
        raise HTTPException(status_code=425, detail="Model preview being generated...")
        
    raise HTTPException(status_code=404, detail=f"No preview mesh (STL or GLB) generated for job '{safe_job_id}'.")


@app.get("/cad/jobs/{job_id}/artifacts/{format_name}")
def download_artifact(job_id: str, format_name: str, settings: Settings = Depends(get_settings)):
    """Downloads an artifact in a supported format with path sanitization."""
    safe_job_id = Path(job_id).name
    backend_base = Path(__file__).resolve().parent.parent
    candidates = [
        Path(settings.artifacts_dir) / safe_job_id,
        backend_base / "artifacts" / safe_job_id,
        backend_base.parent / "backend" / "artifacts" / safe_job_id,
        backend_base / "backend" / "artifacts" / safe_job_id,
    ]
    job_dir = next((c for c in candidates if c.exists()), None)
    
    if not job_dir:
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


# Mount static frontend build if it exists to allow single-command execution
from fastapi.staticfiles import StaticFiles

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    def serve_frontend_index():
        return FileResponse(str(frontend_dist / "index.html"))

    @app.get("/favicon.ico")
    def serve_favicon():
        fav = frontend_dist / "favicon.svg"
        if fav.exists():
            return FileResponse(str(fav), media_type="image/svg+xml")
        return FileResponse(str(frontend_dist / "index.html"))

