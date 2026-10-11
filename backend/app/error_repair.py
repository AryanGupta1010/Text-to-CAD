import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.schemas import (
    CADSpecification,
    ExecutionReport,
    GeometryValidationReport,
    RepairAttempt,
    RetrievedChunk,
)
from backend.app.llm_provider import BaseLLMProvider, extract_python_code
from backend.app.retriever import HybridCADRetriever

logger = logging.getLogger(__name__)

ERROR_REPAIR_SYSTEM_PROMPT = """You are an expert FreeCAD / Open CASCADE CAD debugging specialist.
A previously generated Python CAD script failed during execution or geometric validation.
Your task is to analyze the error report, review the retrieved error-fixing knowledge, identify the root cause, and generate a corrected, fully working FreeCAD script.

GUIDELINES FOR REPAIR:
1. Retain the required imports:
   import FreeCAD
   import Part
2. If boolean cut failed (coincident faces or slivers):
   - Make the cutting tool slightly larger and offset its base to ensure a clean cut.
3. If dimensions mismatched:
   - Ensure variables match the exact requested specification parameters.
4. Always call shape.isValid() and verify not isNull().
5. Always export:
   shape.exportStep("model.step")
   shape.exportStl("model.stl")
   doc.saveAs("model.FCStd")
6. Return ONLY the corrected python script enclosed in ```python ... ``` block. No explanation text.
"""


def classify_error(
    execution_report: Optional[ExecutionReport],
    validation_report: Optional[GeometryValidationReport],
) -> Tuple[str, str]:
    """
    Classifies failure into a specific error category and extracts root cause message.
    """
    if execution_report and execution_report.execution_status == "timeout":
        return "timeout", "Script execution timed out."

    if execution_report and execution_report.execution_status == "failure":
        stderr = execution_report.stderr or ""
        stdout = execution_report.stdout or ""
        combined = (stderr + "\n" + stdout).lower()

        if "syntaxerror" in combined:
            return "syntax_error", stderr
        if "modulenotfounderror" in combined or "importerror" in combined:
            return "missing_import", stderr
        if "brep_api" in combined or "cut" in combined or "boolean" in combined:
            return "boolean_operation_failure", stderr
        if "exportstep" in combined or "exportstl" in combined or "export" in combined:
            return "export_failure", stderr
        if "isvalid" in combined or "invalid" in combined or "null" in combined:
            return "invalid_geometry", stderr
        return "runtime_api_error", stderr or stdout or "Unknown runtime error"

    if validation_report and not validation_report.valid:
        summary = validation_report.failure_summary or "Validation failed"
        if "diameter" in summary.lower() or "height" in summary.lower():
            return "dimensional_mismatch", summary
        if "cavity" in summary.lower() or "hollow" in summary.lower():
            return "boolean_operation_failure", summary
        if "manifold" in summary.lower() or "watertight" in summary.lower():
            return "invalid_geometry", summary
        return "geometry_validation_failure", summary

    return "unknown_error", "No detailed error information available"


class ErrorRepairManager:
    def __init__(self, provider: BaseLLMProvider, retriever: HybridCADRetriever):
        self.provider = provider
        self.retriever = retriever

    def build_repair_query(self, error_category: str, error_message: str) -> str:
        """Constructs an error-specific retrieval query."""
        if error_category == "boolean_operation_failure":
            return "FreeCAD boolean cut coincident face failure sliver Part.makeCylinder"
        elif error_category == "dimensional_mismatch":
            return "FreeCAD bounding box dimensions radius height container"
        elif error_category == "export_failure":
            return "FreeCAD exportStep exportStl Part.export API syntax"
        elif error_category == "invalid_geometry":
            return "FreeCAD Open CASCADE isValid shape null non manifold"
        else:
            return f"FreeCAD error fix {error_category} {error_message[:60]}"

    def retrieve_error_fixes(self, query: str) -> List[RetrievedChunk]:
        """Retrieves targeted error fixes from error_fixes documentation."""
        dense = self.retriever.dense_search(query, top_k=5)
        bm25 = self.retriever.bm25_search(query, top_k=5)
        fused = self.retriever.fuse_and_rerank(dense, bm25, query=query, top_k=3)
        return fused

    def generate_repair_script(
        self,
        current_script: str,
        spec: CADSpecification,
        error_category: str,
        error_message: str,
        retrieved_fixes: List[RetrievedChunk],
    ) -> str:
        """Prompts LLM to repair the script with error context and retrieved fix guidelines."""
        fixes_text = "\n\n".join([f"[{c.document_type}] {c.content}" for c in retrieved_fixes])
        
        prompt = f"""The following FreeCAD script failed execution or validation:

FAILED SCRIPT:
```python
{current_script}
```

ERROR CLASSIFICATION: {error_category}
ERROR DETAILS:
{error_message}

SPECIFICATION PARAMETERS:
{spec.parameters}

RETRIEVED ERROR-FIXING DOCUMENTATION:
{fixes_text}

Fix the issue and return the complete, corrected Python script.
"""
        try:
            raw = self.provider.generate(
                prompt=prompt,
                system=ERROR_REPAIR_SYSTEM_PROMPT,
                temperature=0.1,
            )
            return extract_python_code(raw)
        except Exception as e:
            logger.warning(f"LLM repair generation encountered issue: {e}. Falling back to parametric repair template.")
            from backend.app.code_generator import CADCodeGenerator
            return CADCodeGenerator(self.provider)._generate_script_from_spec(spec)
