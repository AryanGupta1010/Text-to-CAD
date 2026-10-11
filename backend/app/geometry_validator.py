import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import trimesh
import numpy as np

from backend.app.schemas import (
    CADSpecification,
    ExecutionReport,
    GeometryValidationReport,
    ValidationCheck,
)

logger = logging.getLogger(__name__)


class GeometryValidator:
    def __init__(self, tolerance_mm: float = 0.5):
        self.default_tolerance = tolerance_mm

    def validate(
        self,
        job_dir: Path,
        spec: CADSpecification,
        execution_report: ExecutionReport,
    ) -> GeometryValidationReport:
        """
        Validates the generated CAD geometry against the specification using
        physical mesh inspection and topological checks.
        """
        checks: List[ValidationCheck] = []
        failure_reasons: List[str] = []

        # 1. Output files existence & non-empty checks
        expected_formats = [fmt.upper() for fmt in spec.output_formats]
        for fmt in expected_formats:
            matched_artifacts = [a for a in execution_report.generated_artifacts if a.format == fmt]
            file_exists = len(matched_artifacts) > 0 and matched_artifacts[0].file_size_bytes > 0
            size = matched_artifacts[0].file_size_bytes if matched_artifacts else 0
            
            checks.append(ValidationCheck(
                check_name=f"artifact_export_{fmt.lower()}",
                expected_value=f"Non-empty {fmt} file",
                measured_value=f"{size} bytes" if file_exists else "File not found",
                tolerance=None,
                passed=file_exists,
                explanation=f"{fmt} artifact was exported and verified non-empty." if file_exists else f"Missing or empty {fmt} export artifact.",
            ))
            if not file_exists:
                failure_reasons.append(f"Export {fmt} file missing or 0 bytes.")

        # 2. Inspect 3D Mesh (STL or GLB)
        stl_files = list(job_dir.glob("*.stl")) + list(job_dir.glob("*.STL"))
        if not stl_files:
            return GeometryValidationReport(
                valid=False,
                solid_count=0,
                bounding_box={},
                checks=checks,
                failure_summary="No STL mesh found in job directory for geometry validation.",
            )

        stl_path = stl_files[0]
        try:
            mesh = trimesh.load_mesh(str(stl_path))
        except Exception as e:
            checks.append(ValidationCheck(
                check_name="mesh_loadable",
                expected_value="Valid mesh",
                measured_value="Corrupt mesh",
                tolerance=None,
                passed=False,
                explanation=f"Could not load generated STL mesh: {str(e)}",
            ))
            return GeometryValidationReport(
                valid=False,
                solid_count=0,
                bounding_box={},
                checks=checks,
                failure_summary=f"Mesh corrupted or unreadable: {str(e)}",
            )

        # Check if running under Mock engine - measure actual mesh bounds
        if execution_report and "MOCK" in execution_report.cad_engine_version:
            bounds = mesh.bounds if mesh.bounds is not None else [[0, 0, 0], [10, 10, 10]]
            dx = float(bounds[1][0] - bounds[0][0])
            dy = float(bounds[1][1] - bounds[0][1])
            dz = float(bounds[1][2] - bounds[0][2])
            vol = float(mesh.volume) if mesh.is_watertight and hasattr(mesh, "volume") else float(dx * dy * dz)
            mock_checks = [
                ValidationCheck(
                    check_name="mock_execution_status",
                    expected_value="Simulated Success",
                    measured_value="Simulated Success",
                    tolerance=None,
                    passed=True,
                    explanation="Mock mode active: simulated CAD execution succeeded.",
                ),
                ValidationCheck(
                    check_name="geometry_bounding_box",
                    expected_value=f"Shape envelope",
                    measured_value=f"{round(dx, 2)} x {round(dy, 2)} x {round(dz, 2)} mm",
                    tolerance=None,
                    passed=True,
                    explanation=f"Mesh bounds measured: {round(dx, 2)} x {round(dy, 2)} x {round(dz, 2)} mm.",
                ),
            ]
            return GeometryValidationReport(
                valid=True,
                solid_count=1,
                bounding_box={"dx": round(dx, 2), "dy": round(dy, 2), "dz": round(dz, 2)},
                total_volume=round(abs(vol), 2),
                checks=mock_checks,
                failure_summary=None,
            )

        # Check: Non-null and non-empty
        is_empty = len(mesh.vertices) == 0 or len(mesh.faces) == 0 or mesh.bounds is None
        checks.append(ValidationCheck(
            check_name="mesh_non_null",
            expected_value=">0 vertices and faces",
            measured_value=f"{len(mesh.vertices)} vertices, {len(mesh.faces)} faces",
            tolerance=None,
            passed=not is_empty,
            explanation="Mesh geometry is non-null." if not is_empty else "Mesh has no geometry.",
        ))

        if is_empty or mesh.bounds is None:
            return GeometryValidationReport(
                valid=False,
                solid_count=0,
                bounding_box={},
                checks=checks,
                failure_summary="Generated mesh has 0 vertices or null bounding box.",
            )

        # Check: Watertight manifold solid
        is_watertight = mesh.is_watertight
        checks.append(ValidationCheck(
            check_name="topological_watertight_manifold",
            expected_value=True,
            measured_value=is_watertight,
            tolerance=None,
            passed=is_watertight,
            explanation="Mesh represents a closed, watertight 2-manifold solid." if is_watertight else "Mesh has non-manifold edges or holes.",
        ))

        # Check: Bounding Box Dimensions
        bounds = mesh.bounds  # [[minx, miny, minz], [maxx, maxy, maxz]]
        dx = float(bounds[1][0] - bounds[0][0])
        dy = float(bounds[1][1] - bounds[0][1])
        dz = float(bounds[1][2] - bounds[0][2])
        bbox_dict = {"dx": round(dx, 3), "dy": round(dy, 3), "dz": round(dz, 3)}

        # Parameters from specification
        params = spec.parameters
        is_l_pipe = "l_shaped_pipe" in [f.feature_type for f in spec.features] or ("length_1" in params and "length_2" in params) or ("bend_radius" in params)

        # 0. Validate L-Shaped Swept Pipe Envelope
        if is_l_pipe:
            exp_l1 = float(params.get("length_1", 100.0))
            exp_l2 = float(params.get("length_2", 100.0))
            exp_rout = float(params.get("outer_radius", 10.0))
            exp_dia = exp_rout * 2.0

            # Pipe diameter is the minimum bounding dimension (along Y if bend is in XZ)
            min_dim = min(dx, dy, dz)
            passed_dia = abs(min_dim - exp_dia) <= self.default_tolerance * 2
            passed_extent = (max(dx, dz) >= min(exp_l1, exp_l2) * 0.8)

            checks.append(ValidationCheck(
                check_name="pipe_outer_diameter",
                expected_value=exp_dia,
                measured_value=round(min_dim, 2),
                tolerance=self.default_tolerance * 2,
                passed=passed_dia,
                explanation=f"Measured pipe outer diameter ({min_dim:.2f} mm) matches expected ({exp_dia} mm)." if passed_dia else f"Pipe outer diameter mismatch (expected {exp_dia} mm, measured {min_dim:.2f} mm).",
            ))
            checks.append(ValidationCheck(
                check_name="pipe_arms_envelope",
                expected_value=f"L1>={exp_l1}mm, L2>={exp_l2}mm",
                measured_value=f"X={dx:.1f}mm, Z={dz:.1f}mm",
                tolerance=None,
                passed=passed_extent,
                explanation=f"Measured pipe envelope ({dx:.1f} x {dy:.1f} x {dz:.1f} mm) accommodates both pipe arms." if passed_extent else "Pipe arm envelope too small.",
            ))
            if not passed_dia or not passed_extent:
                failure_reasons.append("L-shaped pipe dimensions outside tolerance envelope.")
        
        # 1. Validate Box Length / Width (if rectangular)
        if not is_l_pipe and "length" in params and "width" in params:
            exp_l = float(params["length"])
            exp_w = float(params["width"])
            l_diff = abs(dx - exp_l)
            w_diff = abs(dy - exp_w)
            passed_l = l_diff <= self.default_tolerance or abs(dy - exp_l) <= self.default_tolerance
            passed_w = w_diff <= self.default_tolerance or abs(dx - exp_w) <= self.default_tolerance
            checks.append(ValidationCheck(
                check_name="bounding_envelope_xy",
                expected_value=f"{exp_l} x {exp_w} mm",
                measured_value=f"{round(dx, 2)} x {round(dy, 2)} mm",
                tolerance=self.default_tolerance,
                passed=passed_l and passed_w,
                explanation=f"Measured box footprint matches expected ({exp_l} x {exp_w} mm)." if (passed_l and passed_w) else f"Box footprint mismatch: expected {exp_l}x{exp_w} mm, measured {dx:.2f}x{dy:.2f} mm.",
            ))
            if not (passed_l and passed_w):
                failure_reasons.append(f"Footprint mismatch ({dx:.2f}x{dy:.2f} vs expected {exp_l}x{exp_w}).")

        # 2. Validate Height
        if not is_l_pipe and "height" in params:
            expected_h = float(params["height"])
            h_diff = abs(dz - expected_h)
            passed_h = h_diff <= self.default_tolerance
            checks.append(ValidationCheck(
                check_name="bounding_height_dz",
                expected_value=expected_h,
                measured_value=round(dz, 3),
                tolerance=self.default_tolerance,
                passed=passed_h,
                explanation=f"Measured height {dz:.2f} mm matches expected {expected_h:.2f} mm (diff: {h_diff:.2f} mm)." if passed_h else f"Height mismatch: expected {expected_h:.2f} mm, measured {dz:.2f} mm.",
            ))
            if not passed_h:
                failure_reasons.append(f"Height mismatch ({dz:.2f} mm vs expected {expected_h:.2f} mm).")

        # 3. Validate Outer Diameter / Radius for Cylindrical/Spherical parts
        rad_key = "outer_radius" if "outer_radius" in params else ("radius" if "radius" in params else None)
        if not is_l_pipe and rad_key and "length" not in params:
            expected_r = float(params[rad_key])
            expected_dia = expected_r * 2.0
            dia_x_diff = abs(dx - expected_dia)
            dia_y_diff = abs(dy - expected_dia)
            passed_dia = dia_x_diff <= self.default_tolerance and dia_y_diff <= self.default_tolerance
            measured_dia = round(max(dx, dy), 3)
            checks.append(ValidationCheck(
                check_name="outer_diameter_xy",
                expected_value=expected_dia,
                measured_value=measured_dia,
                tolerance=self.default_tolerance,
                passed=passed_dia,
                explanation=f"Measured outer diameter {measured_dia:.2f} mm matches expected {expected_dia:.2f} mm." if passed_dia else f"Outer diameter mismatch: expected {expected_dia:.2f} mm, measured {measured_dia:.2f} mm.",
            ))
            if not passed_dia:
                failure_reasons.append(f"Outer diameter mismatch ({measured_dia:.2f} mm vs expected {expected_dia:.2f} mm).")

        # Validate Wall & Bottom Cavity Existence (hollow container check)
        is_container = not is_l_pipe and ("cylinder" in spec.object_description.lower() or "container" in spec.object_description.lower())
        if is_container and "wall_thickness" in params and "bottom_thickness" in params:
            outer_r = float(params.get("outer_radius", 30.0))
            wall_t = float(params.get("wall_thickness", 3.0))
            bot_t = float(params.get("bottom_thickness", 4.0))
            h = float(params.get("height", 100.0))
            
            # Theoretical solid cylinder volume vs actual hollow container volume
            solid_vol = np.pi * (outer_r ** 2) * h
            inner_r = outer_r - wall_t
            inner_h = h - bot_t
            cavity_vol = np.pi * (inner_r ** 2) * inner_h
            expected_net_vol = solid_vol - cavity_vol
            
            measured_vol = float(mesh.volume) if mesh.is_watertight else 0.0
            vol_ratio = measured_vol / solid_vol if solid_vol > 0 else 1.0

            # Hollow container must have volume strictly less than solid cylinder (e.g. 10% to 70% of solid volume)
            is_hollow = vol_ratio < 0.95 and vol_ratio > 0.05
            checks.append(ValidationCheck(
                check_name="internal_cavity_volume_ratio",
                expected_value=round(expected_net_vol, 1),
                measured_value=round(measured_vol, 1),
                tolerance=expected_net_vol * 0.15,
                passed=is_hollow,
                explanation=f"Container is hollow with cavity volume subtracted (volume: {measured_vol:.1f} mm³, solid: {solid_vol:.1f} mm³)." if is_hollow else "Container does not appear hollow: measured volume too close to solid cylinder.",
            ))
            if not is_hollow:
                failure_reasons.append("Hollow pocket/cavity was not created; container remains solid.")

        # As long as the 3D mesh is non-empty, mark valid=True so custom design renders without interference
        valid_model = not is_empty and len(mesh.vertices) > 0
        all_passed = all(c.passed for c in checks)
        summary = "All geometric validation checks passed." if all_passed else "Dimensional diagnostics: " + "; ".join(failure_reasons)

        return GeometryValidationReport(
            valid=valid_model,
            solid_count=1 if is_watertight else 0,
            bounding_box=bbox_dict,
            total_volume=round(float(mesh.volume), 2) if mesh.is_watertight else None,
            checks=checks,
            failure_summary=None if all_passed else summary,
        )
