import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.config import get_settings
from backend.app.graph import create_cad_workflow
from backend.app.state import CADWorkflowState


def run_cli_demo(
    prompt: str,
    provider: str = "ollama",
    mock_mode: bool = False,
):
    settings = get_settings()
    job_id = f"cli_{uuid.uuid4().hex[:8]}"

    print("\n" + "=" * 80)
    print("                TEXT-TO-CAD RAG PIPELINE EXECUTION")
    print("=" * 80)
    print(f"[*] Original Prompt:    {prompt}")
    print(f"[*] Selected Provider:  {provider}")
    print(f"[*] Model Identifier:   {settings.ollama_model if provider == 'ollama' else settings.cloud_model}")
    print(f"[*] Mock Mode:          {mock_mode}")
    print(f"[*] Job ID:             {job_id}")
    print("-" * 80)

    initial_state: CADWorkflowState = {
        "job_id": job_id,
        "original_user_request": prompt,
        "selected_llm_provider": provider,
        "model_identifier": settings.ollama_model if provider == "ollama" else settings.cloud_model,
        "mock_mode": mock_mode,
        "repair_attempt_count": 0,
        "max_repair_attempts": settings.max_repair_attempts,
        "repair_history": [],
        "artifact_metadata": [],
    }

    graph = create_cad_workflow(settings)
    final_state = graph.invoke(initial_state)

    print("\n[1] STRUCTURED CAD SPECIFICATION:")
    spec = final_state.get("structured_specification")
    if spec:
        print(json.dumps(spec.model_dump(), indent=2))
    else:
        print("    None")

    if final_state.get("clarification_required"):
        print("\n[!] CLARIFICATION REQUIRED:")
        for q in final_state.get("clarification_questions", []):
            print(f"    - {q}")
        print("\nWorkflow ended awaiting user clarification.")
        return

    print("\n[2] RETRIEVAL DIAGNOSTICS:")
    diag = final_state.get("retrieval_diagnostics")
    if diag:
        print(f"    - Generated Queries: {diag.queries}")
        print(f"    - Dense Candidates:  {diag.dense_results_count}")
        print(f"    - BM25 Candidates:   {diag.bm25_results_count}")
        print(f"    - Fused Candidates:  {diag.fused_count}")
        print("    - Top Selected Chunks:")
        for doc in diag.selected_documents:
            print(f"        * [{doc.document_type}] {doc.metadata.get('title', doc.document_id)} (Rerank score: {doc.rerank_score})")

    print("\n[3] GENERATED PYTHON CAD SCRIPT:")
    script = final_state.get("generated_script", "")
    print(script)

    print("\n[4] CAD EXECUTION REPORT:")
    exec_rep = final_state.get("execution_report")
    if exec_rep:
        print(f"    - Engine:   {exec_rep.cad_engine_version}")
        print(f"    - Status:   {exec_rep.execution_status} (exit code: {exec_rep.exit_code})")
        print(f"    - Duration: {exec_rep.execution_duration_seconds}s")
        if exec_rep.stdout:
            print(f"    - STDOUT:\n{exec_rep.stdout}")
        if exec_rep.stderr:
            print(f"    - STDERR:\n{exec_rep.stderr}")

    print("\n[5] GEOMETRY VALIDATION REPORT:")
    val_rep = final_state.get("geometry_validation_report")
    if val_rep:
        print(f"    - Valid:        {val_rep.valid}")
        print(f"    - Bounding Box: {val_rep.bounding_box}")
        print(f"    - Total Volume: {val_rep.total_volume} mm³")
        print("    - Validation Checks:")
        for chk in val_rep.checks:
            mark = "PASSED" if chk.passed else "FAILED"
            print(f"        [{mark}] {chk.check_name}: expected {chk.expected_value}, measured {chk.measured_value}")

    print("\n[6] REPAIR ATTEMPTS:")
    repairs = final_state.get("repair_history", [])
    if repairs:
        for r in repairs:
            print(f"    - Attempt #{r.attempt_number} [{r.error_category}]: {r.error_message}")
    else:
        print("    None (Initial generation validated successfully without repair).")

    print("\n[7] GENERATED ARTIFACTS:")
    artifacts = final_state.get("artifact_metadata", [])
    for a in artifacts:
        print(f"    - [{a.format}] {a.filename} ({a.file_size_bytes} bytes) -> {a.file_path}")

    print("\n" + "=" * 80)
    print(f"FINAL WORKFLOW STATUS: {final_state.get('final_status', 'unknown').upper()}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Text-To-CAD RAG CLI Demo")
    parser.add_argument(
        "--prompt",
        type=str,
        default="Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and bottom thickness of 4 mm. Export it as a STEP file.",
        help="Natural language CAD prompt",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["ollama", "cloud", "mock"],
        default="ollama",
        help="LLM provider",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in offline deterministic mock mode",
    )
    args = parser.parse_args()

    run_cli_demo(prompt=args.prompt, provider=args.provider, mock_mode=args.mock)
