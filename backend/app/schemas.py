from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# -------------------------------------------------------------
# CAD Feature and Specification Models
# -------------------------------------------------------------

class CADFeature(BaseModel):
    feature_type: str = Field(..., description="Type of geometric feature, e.g., cylinder, box, pocket, fillet")
    dimensions: Dict[str, Union[float, int, str]] = Field(default_factory=dict, description="Dimensions for this feature")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Additional parameters (e.g. angle, radius)")
    geometric_constraints: List[str] = Field(default_factory=list, description="Constraints, e.g., concentric, perpendicular")
    dependencies: List[str] = Field(default_factory=list, description="IDs or names of features this feature depends on")
    expected_properties: Dict[str, Any] = Field(default_factory=dict, description="Expected properties like volume, thickness")


class CADSpecification(BaseModel):
    cad_engine: str = Field(default="FreeCAD", description="Target CAD engine")
    units: str = Field(default="mm", description="Dimensional units (normalized, e.g., mm)")
    object_description: str = Field(..., description="High-level description of the object to model")
    features: List[CADFeature] = Field(default_factory=list, description="List of structured CAD features")
    parameters: Dict[str, Union[float, int, str]] = Field(default_factory=dict, description="Global parameters")
    constraints: List[str] = Field(default_factory=list, description="Global geometric constraints")
    operations: List[str] = Field(default_factory=list, description="Sequence of modeling operations (e.g. create_cylinder, cut)")
    output_formats: List[str] = Field(default_factory=lambda: ["STEP", "STL"], description="Target export formats")
    assumptions: List[str] = Field(default_factory=list, description="Explicit assumptions made during extraction")
    clarification_required: bool = Field(default=False, description="Whether essential dimensions or info are missing")
    clarification_questions: List[str] = Field(default_factory=list, description="Clarification questions for the user")


# -------------------------------------------------------------
# Provider & Settings Schemas
# -------------------------------------------------------------

class ProviderInfo(BaseModel):
    provider_id: str
    name: str
    available: bool
    current: bool
    models: List[str] = Field(default_factory=list)
    description: str = ""


class ProviderSettingsUpdate(BaseModel):
    provider: Literal["cloud", "ollama", "mock"]
    cloud_provider: Optional[str] = None
    cloud_api_key: Optional[str] = None
    cloud_base_url: Optional[str] = None
    cloud_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class ProviderTestRequest(BaseModel):
    provider: Literal["cloud", "ollama", "mock"]
    cloud_provider: Optional[str] = None
    cloud_api_key: Optional[str] = None
    cloud_base_url: Optional[str] = None
    cloud_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class ProviderTestResponse(BaseModel):
    success: bool
    provider: str
    model: str
    message: str
    latency_ms: Optional[float] = None
    capabilities: List[str] = Field(default_factory=list)


# -------------------------------------------------------------
# Retrieval & Diagnostics Schemas
# -------------------------------------------------------------

class RetrievedChunk(BaseModel):
    document_id: str
    content: str
    document_type: str
    cad_engine: str
    operation: Optional[str] = None
    source: str
    score: float = 0.0
    dense_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    fused_score: Optional[float] = None
    rerank_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalDiagnostics(BaseModel):
    queries: List[str] = Field(default_factory=list)
    dense_results_count: int = 0
    bm25_results_count: int = 0
    fused_count: int = 0
    selected_documents: List[RetrievedChunk] = Field(default_factory=list)
    insufficient_evidence: bool = False
    notes: List[str] = Field(default_factory=list)


# -------------------------------------------------------------
# Execution & Validation Schemas
# -------------------------------------------------------------

class ValidationCheck(BaseModel):
    check_name: str
    expected_value: Any
    measured_value: Any
    tolerance: Optional[float] = None
    passed: bool
    explanation: str


class GeometryValidationReport(BaseModel):
    valid: bool
    solid_count: int = 0
    bounding_box: Dict[str, float] = Field(default_factory=dict)
    total_volume: Optional[float] = None
    checks: List[ValidationCheck] = Field(default_factory=list)
    failure_summary: Optional[str] = None


class ArtifactInfo(BaseModel):
    format: str
    filename: str
    file_path: str
    file_size_bytes: int
    is_preview: bool = False


class ExecutionReport(BaseModel):
    job_id: str
    execution_status: Literal["success", "failure", "timeout", "skipped"]
    cad_engine_version: str = "Unknown"
    start_timestamp: str = ""
    completion_timestamp: str = ""
    execution_duration_seconds: float = 0.0
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    generated_artifacts: List[ArtifactInfo] = Field(default_factory=list)
    timeout_occurred: bool = False


class RepairAttempt(BaseModel):
    attempt_number: int
    error_category: str
    error_message: str
    retrieval_query: str
    repaired_script: str
    execution_success: bool = False
    validation_success: bool = False
    log_snippet: str = ""


# -------------------------------------------------------------
# End-to-End Workflow Job State & Requests
# -------------------------------------------------------------

class GenerateCADRequest(BaseModel):
    prompt: str = Field(..., description="Natural language description of CAD object")
    output_formats: List[str] = Field(default_factory=lambda: ["STEP", "STL"])
    mock_mode: bool = Field(default=False, description="Force mock execution for testing")


class ExecuteCADRequest(BaseModel):
    job_id: Optional[str] = None
    script: str = Field(..., description="Python script to execute in CAD runtime")
    expected_dimensions: Optional[Dict[str, Any]] = None
    output_formats: List[str] = Field(default_factory=lambda: ["STEP", "STL"])
    mock_mode: bool = Field(default=False)


class CADJobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "extracting", "retrieving", "generating", "executing", "validating", "repairing", "completed", "failed", "clarification_needed"]
    request_prompt: str
    specification: Optional[CADSpecification] = None
    generated_script: Optional[str] = None
    retrieval_diagnostics: Optional[RetrievalDiagnostics] = None
    execution_report: Optional[ExecutionReport] = None
    validation_report: Optional[GeometryValidationReport] = None
    repair_attempts: List[RepairAttempt] = Field(default_factory=list)
    artifacts: List[ArtifactInfo] = Field(default_factory=list)
    preview_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
