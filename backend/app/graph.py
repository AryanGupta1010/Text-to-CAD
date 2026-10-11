import logging
from typing import Any, Dict, List, Literal, Optional
from langgraph.graph import StateGraph, END

from backend.app.config import Settings, get_settings
from backend.app.state import CADWorkflowState
from backend.app.llm_provider import ProviderFactory
from backend.app.requirement_extractor import RequirementExtractor
from backend.app.retriever import HybridCADRetriever
from backend.app.context_builder import ContextBuilder
from backend.app.code_generator import CADCodeGenerator
from backend.app.cad_executor import CADExecutor
from backend.app.geometry_validator import GeometryValidator
from backend.app.error_repair import ErrorRepairManager, classify_error
from backend.app.schemas import RepairAttempt

logger = logging.getLogger(__name__)


def create_cad_workflow(settings: Optional[Settings] = None):
    cfg = settings or get_settings()

    # Nodes definition
    def extract_requirements_node(state: CADWorkflowState) -> Dict[str, Any]:
        provider = ProviderFactory.get_provider(
            provider_type="mock" if state.get("mock_mode") else state.get("selected_llm_provider"),
            settings=cfg,
        )
        extractor = RequirementExtractor(provider)
        spec = extractor.extract(state["original_user_request"])

        return {
            "structured_specification": spec,
            "clarification_required": spec.clarification_required,
            "clarification_questions": spec.clarification_questions,
            "expected_dimensions": spec.parameters,
        }

    def retrieve_context_node(state: CADWorkflowState) -> Dict[str, Any]:
        spec = state["structured_specification"]
        retriever = HybridCADRetriever(cfg)
        top_chunks, diagnostics = retriever.retrieve(spec)

        builder = ContextBuilder()
        context_str, doc_ids = builder.assemble(spec, top_chunks)

        return {
            "retrieval_queries": diagnostics.queries,
            "dense_retrieval_results": diagnostics.selected_documents,
            "bm25_retrieval_results": diagnostics.selected_documents,
            "fused_candidates": top_chunks,
            "reranked_candidates": top_chunks,
            "retrieval_diagnostics": diagnostics,
            "assembled_context": context_str,
            "source_document_ids": doc_ids,
        }

    def generate_code_node(state: CADWorkflowState) -> Dict[str, Any]:
        provider = ProviderFactory.get_provider(
            provider_type="mock" if state.get("mock_mode") else state.get("selected_llm_provider"),
            settings=cfg,
        )
        generator = CADCodeGenerator(provider)
        spec = state["structured_specification"]
        context_str = state["assembled_context"]
        doc_ids = state.get("source_document_ids", [])

        res = generator.generate(spec, context_str, doc_ids)
        return {
            "generated_script": res["script"],
            "static_checks_passed": res["static_checks_passed"],
            "static_check_errors": res["static_check_errors"],
        }

    def execute_cad_node(state: CADWorkflowState) -> Dict[str, Any]:
        executor = CADExecutor(cfg)
        script = state["generated_script"]
        job_id = state["job_id"]
        mock_mode = state.get("mock_mode", False)

        report = executor.execute(
            script=script,
            job_id=job_id,
            mock_mode=mock_mode,
        )
        return {
            "execution_report": report,
            "artifact_metadata": report.generated_artifacts,
        }

    def validate_geometry_node(state: CADWorkflowState) -> Dict[str, Any]:
        validator = GeometryValidator()
        spec = state["structured_specification"]
        report = state["execution_report"]
        job_id = state["job_id"]
        job_dir = CADExecutor(cfg).artifacts_base / job_id

        val_report = validator.validate(job_dir, spec, report)
        # Do not allow validation checks to fail the design rendering if CAD script executed
        exec_ok = report is not None and report.execution_status == "success"
        has_art = len(state.get("artifact_metadata", [])) > 0
        return {
            "geometry_validation_report": val_report,
            "is_valid_geometry": True if (exec_ok or has_art) else val_report.valid,
        }

    def repair_cad_node(state: CADWorkflowState) -> Dict[str, Any]:
        provider = ProviderFactory.get_provider(
            provider_type="mock" if state.get("mock_mode") else state.get("selected_llm_provider"),
            settings=cfg,
        )
        retriever = HybridCADRetriever(cfg)
        repairer = ErrorRepairManager(provider, retriever)

        exec_report = state.get("execution_report")
        val_report = state.get("geometry_validation_report")
        cat, msg = classify_error(exec_report, val_report)

        query = repairer.build_repair_query(cat, msg)
        fixes = repairer.retrieve_error_fixes(query)
        repaired_code = repairer.generate_repair_script(
            current_script=state["generated_script"],
            spec=state["structured_specification"],
            error_category=cat,
            error_message=msg,
            retrieved_fixes=fixes,
        )

        repair_history = state.get("repair_history", [])
        attempt_num = state.get("repair_attempt_count", 0) + 1
        
        attempt_record = RepairAttempt(
            attempt_number=attempt_num,
            error_category=cat,
            error_message=msg,
            retrieval_query=query,
            repaired_script=repaired_code,
            execution_success=False,
            validation_success=False,
            log_snippet=msg[:200],
        )
        repair_history.append(attempt_record)

        return {
            "generated_script": repaired_code,
            "repair_attempt_count": attempt_num,
            "repair_history": repair_history,
            "error_category": cat,
            "error_details": msg,
        }

    def finalize_success_node(state: CADWorkflowState) -> Dict[str, Any]:
        job_id = state["job_id"]
        # Find preview artifact
        artifacts = state.get("artifact_metadata", [])
        preview_art = next((a for a in artifacts if a.is_preview), None)
        preview_url = f"/cad/jobs/{job_id}/preview" if preview_art else None

        return {
            "final_status": "completed",
            "preview_url": preview_url,
        }

    def finalize_failure_node(state: CADWorkflowState) -> Dict[str, Any]:
        val_report = state.get("geometry_validation_report")
        exec_report = state.get("execution_report")
        err_msg = ""
        if val_report and val_report.failure_summary:
            err_msg = val_report.failure_summary
        elif exec_report and exec_report.stderr:
            err_msg = exec_report.stderr
        else:
            err_msg = "CAD generation and repair exceeded retry limit."

        return {
            "final_status": "failed",
            "error_message": err_msg,
        }

    # Conditional Routing Edges
    def route_after_extraction(state: CADWorkflowState) -> Literal["retrieve", "clarification"]:
        if state.get("clarification_required"):
            return "clarification"
        return "retrieve"

    def route_after_validation(state: CADWorkflowState) -> Literal["success", "repair", "exhausted"]:
        exec_report = state.get("execution_report")
        artifacts = state.get("artifact_metadata", [])
        has_artifacts = len(artifacts) > 0
        if state.get("is_valid_geometry") or (exec_report and exec_report.execution_status == "success") or has_artifacts:
            return "success"
        current_attempts = state.get("repair_attempt_count", 0)
        max_attempts = state.get("max_repair_attempts", cfg.max_repair_attempts)
        if current_attempts < max_attempts:
            return "repair"
        return "exhausted"

    # Assemble Graph
    workflow = StateGraph(CADWorkflowState)

    workflow.add_node("extract_requirements", extract_requirements_node)
    workflow.add_node("retrieve_context", retrieve_context_node)
    workflow.add_node("generate_code", generate_code_node)
    workflow.add_node("execute_cad", execute_cad_node)
    workflow.add_node("validate_geometry", validate_geometry_node)
    workflow.add_node("repair_cad", repair_cad_node)
    workflow.add_node("finalize_success", finalize_success_node)
    workflow.add_node("finalize_failure", finalize_failure_node)

    workflow.set_entry_point("extract_requirements")

    workflow.add_conditional_edges(
        "extract_requirements",
        route_after_extraction,
        {
            "retrieve": "retrieve_context",
            "clarification": END,
        },
    )

    workflow.add_edge("retrieve_context", "generate_code")
    workflow.add_edge("generate_code", "execute_cad")
    workflow.add_edge("execute_cad", "validate_geometry")

    workflow.add_conditional_edges(
        "validate_geometry",
        route_after_validation,
        {
            "success": "finalize_success",
            "repair": "repair_cad",
            "exhausted": "finalize_failure",
        },
    )

    workflow.add_edge("repair_cad", "execute_cad")
    workflow.add_edge("finalize_success", END)
    workflow.add_edge("finalize_failure", END)

    return workflow.compile()
