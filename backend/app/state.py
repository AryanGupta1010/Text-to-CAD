from typing import Any, Dict, List, Literal, Optional, TypedDict
from backend.app.schemas import (
    CADSpecification,
    RetrievedChunk,
    RetrievalDiagnostics,
    ExecutionReport,
    GeometryValidationReport,
    RepairAttempt,
    ArtifactInfo,
)


class CADWorkflowState(TypedDict, total=False):
    # Job and Request
    job_id: str
    original_user_request: str
    selected_llm_provider: str
    model_identifier: str
    mock_mode: bool
    
    # Specification
    structured_specification: Optional[CADSpecification]
    clarification_required: bool
    clarification_questions: List[str]
    
    # Retrieval
    retrieval_queries: List[str]
    dense_retrieval_results: List[RetrievedChunk]
    bm25_retrieval_results: List[RetrievedChunk]
    fused_candidates: List[RetrievedChunk]
    reranked_candidates: List[RetrievedChunk]
    retrieval_diagnostics: Optional[RetrievalDiagnostics]
    
    # Context & Generation
    assembled_context: str
    generated_script: str
    expected_dimensions: Dict[str, Any]
    source_document_ids: List[str]
    
    # Static Checks & Execution
    static_checks_passed: bool
    static_check_errors: List[str]
    execution_report: Optional[ExecutionReport]
    
    # Geometry Validation
    geometry_validation_report: Optional[GeometryValidationReport]
    is_valid_geometry: bool
    
    # Repair
    repair_attempt_count: int
    max_repair_attempts: int
    repair_history: List[RepairAttempt]
    error_category: Optional[str]
    error_details: Optional[str]
    
    # Artifacts & Status
    final_status: Literal["completed", "failed", "clarification_needed"]
    artifact_metadata: List[ArtifactInfo]
    preview_url: Optional[str]
    error_message: Optional[str]
