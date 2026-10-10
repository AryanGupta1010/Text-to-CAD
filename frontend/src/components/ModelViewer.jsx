import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Maximize2, RotateCcw, Grid, Eye, AlertCircle, Loader2, Compass } from 'lucide-react';
import { getPreviewArtifactUrl } from '../services/api';

export default function ModelViewer({
  jobId,
  isExecuting,
  validationReport,
}) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const rendererRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const currentMeshRef = useRef(null);
  const gridHelperRef = useRef(null);
  const axesHelperRef = useRef(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showGrid, setShowGrid] = useState(true);
  const [showAxes, setShowAxes] = useState(true);
  const [wireframe, setWireframe] = useState(false);

  // Initialize Three.js scene once
  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    const width = container.clientWidth || 600;
    const height = container.clientHeight || 450;

    // 1. Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0e17);
    sceneRef.current = scene;

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
    camera.position.set(120, 120, 140);
    cameraRef.current = camera;

    // 3. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    container.innerHTML = '';
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // 4. Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.target.set(0, 0, 50);
    controlsRef.current = controls;

    // 5. Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0x06b6d4, 1.2);
    dirLight1.position.set(150, 200, 150);
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x3b82f6, 0.9);
    dirLight2.position.set(-150, -100, -150);
    scene.add(dirLight2);

    // 6. Helpers
    const gridHelper = new THREE.GridHelper(300, 30, 0x06b6d4, 0x1f2937);
    gridHelper.position.y = 0;
    scene.add(gridHelper);
    gridHelperRef.current = gridHelper;

    const axesHelper = new THREE.AxesHelper(60);
    scene.add(axesHelper);
    axesHelperRef.current = axesHelper;

    // 7. Animation Loop
    let animationFrameId;
    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    // 8. Resize Handler
    const handleResize = () => {
      if (!container || !renderer || !camera) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
      renderer.dispose();
      if (container && renderer.domElement) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  // Load preview mesh when jobId changes
  useEffect(() => {
    if (!jobId) return;
    loadCADArtifact(jobId);
  }, [jobId]);

  const loadCADArtifact = async (id) => {
    setIsLoading(true);
    setError(null);
    const scene = sceneRef.current;
    if (!scene) return;

    // Remove existing mesh
    if (currentMeshRef.current) {
      scene.remove(currentMeshRef.current);
      currentMeshRef.current = null;
    }

    const previewUrl = getPreviewArtifactUrl(id);

    try {
      // Fetch binary blob to determine if GLB or STL
      const res = await fetch(previewUrl);
      if (!res.ok) {
        throw new Error(`CAD preview artifact not available for job ${id}`);
      }

      const contentType = res.headers.get('content-type') || '';
      const arrayBuffer = await res.arrayBuffer();

      if (contentType.includes('gltf') || contentType.includes('glb')) {
        // Load GLB
        const loader = new GLTFLoader();
        loader.parse(
          arrayBuffer,
          '',
          (gltf) => {
            const model = gltf.scene;
            model.traverse((child) => {
              if (child.isMesh) {
                child.material = new THREE.MeshStandardMaterial({
                  color: 0x22d3ee,
                  roughness: 0.35,
                  metalness: 0.25,
                  wireframe: wireframe,
                });
              }
            });
            scene.add(model);
            currentMeshRef.current = model;
            fitCameraToMesh(model);
            setIsLoading(false);
          },
          (err) => {
            console.error('GLTF parse error:', err);
            loadFallbackSTL(arrayBuffer);
          }
        );
      } else {
        // Load STL
        loadFallbackSTL(arrayBuffer);
      }
    } catch (e) {
      console.warn('Preview mesh load error:', e);
      setError(e.message || 'Could not load CAD mesh artifact.');
      setIsLoading(false);
    }
  };

  const loadFallbackSTL = (arrayBuffer) => {
    try {
      const loader = new STLLoader();
      const geometry = loader.parse(arrayBuffer);
      geometry.computeVertexNormals();

      const material = new THREE.MeshStandardMaterial({
        color: 0x06b6d4,
        roughness: 0.4,
        metalness: 0.2,
        wireframe: wireframe,
      });

      const mesh = new THREE.Mesh(geometry, material);
      sceneRef.current.add(mesh);
      currentMeshRef.current = mesh;
      fitCameraToMesh(mesh);
      setIsLoading(false);
    } catch (err) {
      setError(`Failed to render STL geometry: ${err.message}`);
      setIsLoading(false);
    }
  };

  const fitCameraToMesh = (object) => {
    const box = new THREE.Box3().setFromObject(object);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());

    const maxDim = Math.max(size.x, size.y, size.z, 20);
    const fov = cameraRef.current.fov * (Math.PI / 180);
    let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * 1.8;

    cameraRef.current.position.set(center.x + cameraZ * 0.7, center.y + cameraZ * 0.7, center.z + cameraZ);
    cameraRef.current.lookAt(center);
    controlsRef.current.target.copy(center);
    controlsRef.current.update();
  };

  const handleResetCamera = () => {
    if (currentMeshRef.current) {
      fitCameraToMesh(currentMeshRef.current);
    } else {
      cameraRef.current.position.set(120, 120, 140);
      controlsRef.current.target.set(0, 0, 50);
      controlsRef.current.update();
    }
  };

  const toggleGrid = () => {
    setShowGrid(!showGrid);
    if (gridHelperRef.current) gridHelperRef.current.visible = !showGrid;
  };

  const toggleAxes = () => {
    setShowAxes(!showAxes);
    if (axesHelperRef.current) axesHelperRef.current.visible = !showAxes;
  };

  const toggleWireframe = () => {
    setWireframe(!wireframe);
    if (currentMeshRef.current) {
      currentMeshRef.current.traverse((child) => {
        if (child.isMesh && child.material) {
          child.material.wireframe = !wireframe;
        }
      });
    }
  };

  const bbox = validationReport?.bounding_box;

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '640px', overflow: 'hidden', position: 'relative' }}>
      {/* 3D Viewer Header Controls */}
      <div style={{
        position: 'absolute', top: '12px', left: '16px', right: '16px', zIndex: 10,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', pointerEvents: 'none'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', pointerEvents: 'auto' }}>
          <span className="badge badge-cyan" style={{ backdropFilter: 'blur(8px)', background: 'rgba(6, 182, 212, 0.2)' }}>
            <Compass size={13} />
            Interactive 3D CAD Preview
          </span>
          {validationReport?.valid && (
            <span className="badge badge-success" style={{ backdropFilter: 'blur(8px)' }}>
              Verified Solid
            </span>
          )}
        </div>

        {/* Viewport Toolbar */}
        <div style={{ display: 'flex', gap: '6px', pointerEvents: 'auto' }}>
          <button className={`btn btn-secondary btn-sm ${showGrid ? 'btn-primary' : ''}`} onClick={toggleGrid} title="Toggle Ground Grid">
            <Grid size={13} />
          </button>
          <button className={`btn btn-secondary btn-sm ${showAxes ? 'btn-primary' : ''}`} onClick={toggleAxes} title="Toggle XYZ Coordinate Axes">
            <Compass size={13} />
          </button>
          <button className={`btn btn-secondary btn-sm ${wireframe ? 'btn-primary' : ''}`} onClick={toggleWireframe} title="Toggle Wireframe Mesh">
            <Eye size={13} />
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleResetCamera} title="Fit & Reset Camera">
            <RotateCcw size={13} />
          </button>
        </div>
      </div>

      {/* Real Three.js Canvas Container */}
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      {/* Loading Overlay */}
      {(isLoading || isExecuting) && (
        <div style={{
          position: 'absolute', inset: 0, background: 'rgba(9, 13, 22, 0.75)',
          backdropFilter: 'blur(4px)', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: '12px', zIndex: 20
        }}>
          <Loader2 size={36} color="var(--primary)" className="spin" />
          <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>
            {isExecuting ? 'Executing CAD Runtime Kernel...' : 'Loading Generated 3D Mesh...'}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Calculating analytic geometry and boundary representation
          </div>
        </div>
      )}

      {/* Error Overlay */}
      {error && !isLoading && !isExecuting && (
        <div style={{
          position: 'absolute', bottom: '60px', left: '20px', right: '20px',
          padding: '12px 16px', background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.4)', borderRadius: 'var(--radius-sm)',
          backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', gap: '10px',
          color: '#f87171', fontSize: '0.8rem', zIndex: 15
        }}>
          <AlertCircle size={18} />
          <div>{error}</div>
        </div>
      )}

      {/* Dimension HUD Overlay */}
      {bbox && bbox.dx && (
        <div style={{
          position: 'absolute', bottom: '12px', left: '16px', right: '16px',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 14px', background: 'rgba(17, 24, 39, 0.85)',
          backdropFilter: 'blur(12px)', border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-sm)', fontSize: '0.775rem', pointerEvents: 'auto'
        }}>
          <div style={{ display: 'flex', gap: '16px', color: 'var(--text-secondary)' }}>
            <span>Envelope: <strong style={{ color: '#e2e8f0' }}>{bbox.dx} × {bbox.dy} × {bbox.dz} mm</strong></span>
            {validationReport?.total_volume && (
              <span>Volume: <strong style={{ color: '#22d3ee' }}>{validationReport.total_volume.toLocaleString()} mm³</strong></span>
            )}
            <span>Solids: <strong style={{ color: '#34d399' }}>{validationReport?.solid_count || 1}</strong></span>
          </div>
          <span style={{ color: 'var(--text-muted)' }}>Rotate: Left Click | Pan: Right Click | Zoom: Scroll</span>
        </div>
      )}
    </div>
  );
}
