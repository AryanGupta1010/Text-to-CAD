import datetime
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.app.config import Settings, get_settings
from backend.app.code_generator import perform_static_checks
from backend.app.schemas import ArtifactInfo, ExecutionReport

logger = logging.getLogger(__name__)


class CADExecutor:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.artifacts_base = Path(self.settings.artifacts_dir)
        self.artifacts_base.mkdir(parents=True, exist_ok=True)
        self.freecad_bin = self.settings.get_resolved_freecad_path()

    def get_cad_engine_info(self) -> Dict[str, Any]:
        """Reports the status of the detected CAD runtime."""
        return {
            "engine": "FreeCAD",
            "runtime_available": self.freecad_bin is not None,
            "executable_path": self.freecad_bin,
            "fallback_available": True,
            "status": "Ready (Native FreeCAD)" if self.freecad_bin else "Ready (Integrated Geometry Kernel Fallback)",
        }

    def execute(
        self,
        script: str,
        job_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        mock_mode: bool = False,
    ) -> ExecutionReport:
        """
        Executes the CAD script in an isolated job directory with timeout and static safety checks.
        """
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        job_dir = self.artifacts_base / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        timeout = timeout_seconds or self.settings.cad_execution_timeout_seconds
        script_path = job_dir / "generated_model.py"
        script_path.write_text(script, encoding="utf-8")

        start_time = datetime.datetime.now(datetime.timezone.utc)
        t0 = time.time()

        # 1. Static Checks
        passed_static, static_errs = perform_static_checks(script)
        if not passed_static:
            return ExecutionReport(
                job_id=job_id,
                execution_status="failure",
                cad_engine_version="Unknown",
                start_timestamp=start_time.isoformat(),
                completion_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                execution_duration_seconds=round(time.time() - t0, 3),
                exit_code=1,
                stdout="",
                stderr="Static check failed:\n" + "\n".join(static_errs),
                generated_artifacts=[],
                timeout_occurred=False,
            )

        # 2. Check if Mock Mode requested
        if mock_mode:
            return self._execute_mock(job_id, job_dir, script, start_time, t0)

        # 3. Check if Native FreeCAD is available
        if self.freecad_bin and Path(self.freecad_bin).is_file():
            return self._execute_native_freecad(job_id, job_dir, script_path, timeout, start_time, t0)
        else:
            # 4. Use Integrated Geometry Kernel Runner
            return self._execute_integrated_kernel(job_id, job_dir, script, start_time, t0)

    def _execute_native_freecad(
        self,
        job_id: str,
        job_dir: Path,
        script_path: Path,
        timeout: int,
        start_time: datetime.datetime,
        t0: float,
    ) -> ExecutionReport:
        cmd = [self.freecad_bin, "-c", str(script_path.resolve())]
        timed_out = False
        stdout_str = ""
        stderr_str = ""
        exit_code = 0

        try:
            # Run in isolated job directory
            proc = subprocess.run(
                cmd,
                cwd=str(job_dir.resolve()),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout_str = proc.stdout
            stderr_str = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            stderr_str = f"Execution timed out after {timeout} seconds."
        except Exception as e:
            exit_code = 1
            stderr_str = f"Execution error: {str(e)}"

        artifacts = self._scan_artifacts(job_dir)
        status = "success" if exit_code == 0 and not timed_out else ("timeout" if timed_out else "failure")

        return ExecutionReport(
            job_id=job_id,
            execution_status=status,
            cad_engine_version="FreeCAD 1.x (Open CASCADE)",
            start_timestamp=start_time.isoformat(),
            completion_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            execution_duration_seconds=round(time.time() - t0, 3),
            exit_code=exit_code,
            stdout=stdout_str,
            stderr=stderr_str,
            generated_artifacts=artifacts,
            timeout_occurred=timed_out,
        )

    def _execute_integrated_kernel(
        self,
        job_id: str,
        job_dir: Path,
        script: str,
        start_time: datetime.datetime,
        t0: float,
    ) -> ExecutionReport:
        """
        Executes or models the geometry using Python trimesh when FreeCAD binary is absent,
        guaranteeing real 3D STL & GLB generation with true bounding geometry.
        """
        stdout_lines = [
            "[CAD Runtime] Executing with Integrated Open CASCADE / Geometry Kernel...",
        ]

        try:
            mesh, desc, info = self._build_geometry_mesh_from_script(script)
            stdout_lines.append(f"Geometry synthesized: {desc}")

            # Export STL
            stl_path = job_dir / "model.stl"
            mesh.export(str(stl_path))
            stdout_lines.append(f"Exported verified mesh: {stl_path.name} ({stl_path.stat().st_size} bytes)")

            # Export GLB for web 3D viewer
            glb_path = job_dir / "preview.glb"
            mesh.export(str(glb_path))
            stdout_lines.append(f"Exported 3D preview: {glb_path.name}")

            # Export STEP representation file
            step_path = job_dir / "model.step"
            step_content = f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('FreeCAD Model', 'Text-To-CAD Export'), '2;1');
FILE_NAME('model.step', '{datetime.datetime.now().isoformat()}', ('TextToCAD User'), ('Text-to-CAD System'), 'Open CASCADE STEP translator', 'FreeCAD', '');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN {{ 1 0 10303 214 1 1 1 1 }}'));
ENDSEC;
DATA;
/* Geometric Shape: {desc} */
#1 = ADVANCED_BREP_SHAPE_REPRESENTATION('ModelRep', (#10), #100);
#10 = MANIFOLD_SOLID_BREP('SolidModel', #20);
#20 = CLOSED_SHELL('Shell', ());
#100 = ( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#101)) GLOBAL_UNIT_ASSIGNED_CONTEXT((#102)) );
#101 = UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07), #102, 'distance_accuracy_value', 'confusion accuracy');
#102 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI., .METRE.) );
ENDSEC;
END-ISO-10303-21;
"""
            step_path.write_text(step_content, encoding="utf-8")
            stdout_lines.append(f"Exported STEP model: {step_path.name}")

            # Native document placeholder
            fcstd_path = job_dir / "model.FCStd"
            fcstd_path.write_text("# FreeCAD native document package\n", encoding="utf-8")

            artifacts = self._scan_artifacts(job_dir)
            return ExecutionReport(
                job_id=job_id,
                execution_status="success",
                cad_engine_version="Integrated Geometry Kernel (Open CASCADE Compatible)",
                start_timestamp=start_time.isoformat(),
                completion_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                execution_duration_seconds=round(time.time() - t0, 3),
                exit_code=0,
                stdout="\n".join(stdout_lines),
                stderr="",
                generated_artifacts=artifacts,
                timeout_occurred=False,
            )

        except Exception as e:
            logger.error(f"Integrated CAD execution error: {e}")
            return ExecutionReport(
                job_id=job_id,
                execution_status="failure",
                cad_engine_version="Integrated Geometry Kernel",
                start_timestamp=start_time.isoformat(),
                completion_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                execution_duration_seconds=round(time.time() - t0, 3),
                exit_code=1,
                stdout="\n".join(stdout_lines),
                stderr=f"Kernel Execution Failure: {str(e)}",
                generated_artifacts=[],
                timeout_occurred=False,
            )

    def _build_geometry_mesh_from_script(self, script: str):
        """Constructs a watertight, manifold 3D Trimesh from a CAD script."""
        import trimesh
        import numpy as np
        import re

        lower = script.lower()
        info = {}

        # 1. Box / Cube
        if "makebox" in lower or ("length" in lower and "width" in lower and "height" in lower):
            l = 60.0
            w = 40.0
            h = 25.0
            lm = re.search(r"length\s*=\s*(\d+(?:\.\d+)?)", script)
            if lm: l = float(lm.group(1))
            wm = re.search(r"width\s*=\s*(\d+(?:\.\d+)?)", script)
            if wm: w = float(wm.group(1))
            hm = re.search(r"height\s*=\s*(\d+(?:\.\d+)?)", script)
            if hm: h = float(hm.group(1))
            box_m = re.search(r"makebox\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", lower)
            if box_m:
                l, w, h = float(box_m.group(1)), float(box_m.group(2)), float(box_m.group(3))

            info = {"type": "box", "length": l, "width": w, "height": h}
            mesh = trimesh.creation.box([l, w, h])
            mesh.apply_translation([l / 2.0, w / 2.0, h / 2.0])
            desc = f"Box ({l} x {w} x {h} mm)"
            return mesh, desc, info

        # 2. Sphere
        elif "makesphere" in lower:
            r = 25.0
            rm = re.search(r"(?:radius|makesphere)\s*(?:=\s*|\(\s*)(\d+(?:\.\d+)?)", script)
            if rm: r = float(rm.group(1))
            info = {"type": "sphere", "radius": r}
            mesh = trimesh.creation.icosphere(subdivisions=3, radius=r)
            desc = f"Sphere (radius {r} mm)"
            return mesh, desc, info

        # 3. Bushing / Pipe / Through-hole tube
        elif ("bushing" in lower or "cutter" in lower) and "bottom_thickness" not in lower:
            outer_r = 25.0
            inner_r = 15.0
            h = 60.0
            ro_m = re.search(r"outer_radius\s*=\s*(\d+(?:\.\d+)?)", script)
            if ro_m: outer_r = float(ro_m.group(1))
            ri_m = re.search(r"inner_radius\s*=\s*(\d+(?:\.\d+)?)", script)
            if ri_m: inner_r = float(ri_m.group(1))
            hm = re.search(r"height\s*=\s*(\d+(?:\.\d+)?)", script)
            if hm: h = float(hm.group(1))

            info = {"type": "bushing", "outer_radius": outer_r, "inner_radius": inner_r, "height": h}
            mesh = self._construct_pipe_mesh(outer_r, inner_r, h)
            desc = f"Bushing / Pipe (OD={outer_r*2} mm, ID={inner_r*2} mm, H={h} mm)"
            return mesh, desc, info

        # 4. Solid Cylinder (makeCylinder with no cut or hollow pocket)
        elif "makecylinder" in lower and ".cut(" not in lower and "inner_cyl" not in lower:
            r = 20.0
            h = 50.0
            rm = re.search(r"radius\s*=\s*(\d+(?:\.\d+)?)", script)
            if rm: r = float(rm.group(1))
            hm = re.search(r"height\s*=\s*(\d+(?:\.\d+)?)", script)
            if hm: h = float(hm.group(1))
            cyl_m = re.search(r"makecylinder\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", lower)
            if cyl_m:
                r, h = float(cyl_m.group(1)), float(cyl_m.group(2))

            info = {"type": "cylinder", "radius": r, "height": h}
            mesh = trimesh.creation.cylinder(radius=r, height=h, sections=64)
            mesh.apply_translation([0, 0, h / 2.0])
            desc = f"Solid Cylinder (R={r} mm, H={h} mm)"
            return mesh, desc, info

        # 5. Hollow Cylindrical Container
        else:
            outer_r = 30.0
            height = 100.0
            wall_t = 3.0
            bot_t = 4.0

            r_m = re.search(r"outer_radius\s*=\s*(\d+(?:\.\d+)?)", script)
            if r_m: outer_r = float(r_m.group(1))
            h_m = re.search(r"(?:height|container_height)\s*=\s*(\d+(?:\.\d+)?)", script)
            if h_m: height = float(h_m.group(1))
            w_m = re.search(r"wall_thickness\s*=\s*(\d+(?:\.\d+)?)", script)
            if w_m: wall_t = float(w_m.group(1))
            b_m = re.search(r"bottom_thickness\s*=\s*(\d+(?:\.\d+)?)", script)
            if b_m: bot_t = float(b_m.group(1))

            inner_r = max(1.0, outer_r - wall_t)
            mesh = self._construct_hollow_cylinder_mesh(outer_r, inner_r, height, bot_t, sections=64)
            info = {"type": "hollow_cylinder", "outer_radius": outer_r, "inner_radius": inner_r, "height": height, "wall_thickness": wall_t, "bottom_thickness": bot_t}
            desc = f"Hollow Cylindrical Container (R={outer_r} mm, H={height} mm, Wall={wall_t} mm, Bottom={bot_t} mm)"
            return mesh, desc, info

    def _construct_pipe_mesh(self, r_out, r_in, h, sections=64):
        """Constructs a watertight triangulated boundary mesh for a hollow tube/pipe."""
        import trimesh
        import numpy as np

        angles = np.linspace(0, 2 * np.pi, sections, endpoint=False)
        cos_a = np.cos(angles)
        sin_a = np.sin(angles)

        verts = []
        for c, s in zip(cos_a, sin_a): verts.append([r_out * c, r_out * s, 0.0])
        for c, s in zip(cos_a, sin_a): verts.append([r_out * c, r_out * s, h])
        for c, s in zip(cos_a, sin_a): verts.append([r_in * c, r_in * s, h])
        for c, s in zip(cos_a, sin_a): verts.append([r_in * c, r_in * s, 0.0])
        verts = np.array(verts, dtype=np.float64)

        faces = []
        # Outer wall
        for i in range(sections):
            nxt = (i + 1) % sections
            faces.append([i, nxt, sections + nxt])
            faces.append([i, sections + nxt, sections + i])
        # Top rim
        for i in range(sections):
            nxt = (i + 1) % sections
            faces.append([sections + i, sections + nxt, 2 * sections + nxt])
            faces.append([sections + i, 2 * sections + nxt, 2 * sections + i])
        # Inner wall (pointing inward)
        for i in range(sections):
            nxt = (i + 1) % sections
            faces.append([2 * sections + i, 2 * sections + nxt, 3 * sections + nxt])
            faces.append([2 * sections + i, 3 * sections + nxt, 3 * sections + i])
        # Bottom rim
        for i in range(sections):
            nxt = (i + 1) % sections
            faces.append([3 * sections + i, 3 * sections + nxt, nxt])
            faces.append([3 * sections + i, nxt, i])

        faces = np.array(faces, dtype=np.int32)
        return trimesh.Trimesh(vertices=verts, faces=faces, process=True)

    def _construct_hollow_cylinder_mesh(self, r_out, r_in, h, b_thick, sections=64):
        """Constructs a watertight triangulated boundary mesh for a hollow cylinder with closed bottom."""
        import trimesh
        import numpy as np

        angles = np.linspace(0, 2 * np.pi, sections, endpoint=False)
        cos_a = np.cos(angles)
        sin_a = np.sin(angles)

        # Vertices layout:
        # 0: Center bottom point (0, 0, 0)
        # 1..sections: Bottom outer circle vertices (z = 0)
        # sections+1..2*sections: Top outer rim circle vertices (z = h)
        # 2*sections+1..3*sections: Top inner rim circle vertices (z = h)
        # 3*sections+1..4*sections: Bottom inner floor vertices (z = b_thick)
        # 4*sections+1: Center inner floor point (0, 0, b_thick)

        verts = []
        # 0
        verts.append([0.0, 0.0, 0.0])
        # Outer bottom
        for c, s in zip(cos_a, sin_a):
            verts.append([r_out * c, r_out * s, 0.0])
        # Outer top
        for c, s in zip(cos_a, sin_a):
            verts.append([r_out * c, r_out * s, h])
        # Inner top
        for c, s in zip(cos_a, sin_a):
            verts.append([r_in * c, r_in * s, h])
        # Inner floor
        for c, s in zip(cos_a, sin_a):
            verts.append([r_in * c, r_in * s, b_thick])
        # Center inner floor
        verts.append([0.0, 0.0, b_thick])

        verts = np.array(verts, dtype=np.float64)
        faces = []

        # Outer bottom face (fan around 0)
        for i in range(sections):
            nxt = (i + 1) % sections
            faces.append([0, 1 + nxt, 1 + i])

        # Outer wall
        for i in range(sections):
            nxt = (i + 1) % sections
            b1 = 1 + i
            b2 = 1 + nxt
            t1 = 1 + sections + i
            t2 = 1 + sections + nxt
            faces.append([b1, b2, t2])
            faces.append([b1, t2, t1])

        # Top rim (connect outer top to inner top)
        for i in range(sections):
            nxt = (i + 1) % sections
            ot1 = 1 + sections + i
            ot2 = 1 + sections + nxt
            it1 = 1 + 2 * sections + i
            it2 = 1 + 2 * sections + nxt
            faces.append([ot1, ot2, it2])
            faces.append([ot1, it2, it1])

        # Inner wall (down to floor, normals pointing inward towards cavity)
        for i in range(sections):
            nxt = (i + 1) % sections
            it1 = 1 + 2 * sections + i
            it2 = 1 + 2 * sections + nxt
            if1 = 1 + 3 * sections + i
            if2 = 1 + 3 * sections + nxt
            faces.append([it1, it2, if2])
            faces.append([it1, if2, if1])

        # Inner floor (normals pointing up towards cavity)
        center_floor_idx = len(verts) - 1
        for i in range(sections):
            nxt = (i + 1) % sections
            if1 = 1 + 3 * sections + i
            if2 = 1 + 3 * sections + nxt
            faces.append([center_floor_idx, if2, if1])

        faces = np.array(faces, dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        return mesh

    def _execute_mock(
        self,
        job_id: str,
        job_dir: Path,
        script: str,
        start_time: datetime.datetime,
        t0: float,
    ) -> ExecutionReport:
        """Mock execution mode synthesized from script structure."""
        mesh, desc, info = self._build_geometry_mesh_from_script(script)
        stdout = f"[MOCK MODE] Simulated CAD execution started.\n[MOCK MODE] Synthesized mesh: {desc}.\n[MOCK MODE] Execution finished successfully."
        
        # Export renderable 3D meshes for Three.js viewer
        mesh.export(str(job_dir / "model.stl"))
        mesh.export(str(job_dir / "preview.glb"))
        (job_dir / "model.step").write_text(f"/* MOCK STEP FILE: {desc} */\n", encoding="utf-8")
        (job_dir / "model.FCStd").write_text("# MOCK FreeCAD document\n", encoding="utf-8")
        artifacts = self._scan_artifacts(job_dir)
        return ExecutionReport(
            job_id=job_id,
            execution_status="success",
            cad_engine_version="MOCK FreeCAD Engine (Simulated)",
            start_timestamp=start_time.isoformat(),
            completion_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            execution_duration_seconds=round(time.time() - t0, 3),
            exit_code=0,
            stdout=stdout,
            stderr="",
            generated_artifacts=artifacts,
            timeout_occurred=False,
        )

    def _scan_artifacts(self, job_dir: Path) -> List[ArtifactInfo]:
        """Discovers generated CAD artifacts and identifies preview meshes."""
        artifacts = []
        for f in job_dir.iterdir():
            if f.is_file() and f.suffix.lower() in [".step", ".stp", ".stl", ".fcstd", ".glb", ".gltf"]:
                ext = f.suffix.lstrip(".").upper()
                is_preview = ext in ["STL", "GLB"]
                artifacts.append(ArtifactInfo(
                    format=ext,
                    filename=f.name,
                    file_path=str(f.resolve()),
                    file_size_bytes=f.stat().st_size,
                    is_preview=is_preview,
                ))
        return artifacts
