import React, { useState, useEffect } from 'react';
import { Box, Sparkles, Layers, Cpu, ShieldCheck, Terminal, Compass, RefreshCw } from 'lucide-react';
import ProviderSettings from './components/ProviderSettings';
import PromptPanel from './components/PromptPanel';
import CodeEditor from './components/CodeEditor';
import ModelViewer from './components/ModelViewer';
import ValidationPanel from './components/ValidationPanel';
import { initiateGenerateCAD, executeEditedScript, fetchJobStatus } from './services/api';

const DEFAULT_PROMPT = 'Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and bottom thickness of 4 mm. Export it as a STEP file.';

export default function App() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [mockMode, setMockMode] = useState(false);
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExecutingScript, setIsExecutingScript] = useState(false);

  // Poll job status until completed, failed, or clarification_needed
  useEffect(() => {
    if (!activeJobId) return;

    let intervalId = null;
    const poll = async () => {
      try {
        const status = await fetchJobStatus(activeJobId);
        setJobStatus(status);

        if (['completed', 'failed', 'clarification_needed'].includes(status.status)) {
          setIsGenerating(false);
          clearInterval(intervalId);
        }
      } catch (err) {
        console.error('Error polling job status:', err);
      }
    };

    poll();
    intervalId = setInterval(poll, 1500);

    return () => clearInterval(intervalId);
  }, [activeJobId]);

  const [activeProvider, setActiveProvider] = useState(() => ({
    provider: localStorage.getItem('text2cad_provider') || 'google_studio',
  }));

  const handleGenerateCAD = async (userPrompt, useMock, outputFormats) => {
    setIsGenerating(true);
    setJobStatus(null);
    try {
      const provider = activeProvider?.provider || localStorage.getItem('text2cad_provider') || 'google_studio';
      let apiKey = undefined;
      let model = undefined;
      if (provider === 'google_studio') {
        apiKey = activeProvider?.google_studio_api_key || localStorage.getItem('text2cad_google_key') || undefined;
        model = activeProvider?.google_studio_model || localStorage.getItem('text2cad_google_model') || 'gemini-2.5-flash';
      } else if (provider === 'openrouter') {
        apiKey = activeProvider?.openrouter_api_key || localStorage.getItem('text2cad_openrouter_key') || undefined;
        model = activeProvider?.openrouter_model || localStorage.getItem('text2cad_openrouter_model') || 'anthropic/claude-3.5-sonnet';
      }

      const initRes = await initiateGenerateCAD(userPrompt, useMock, outputFormats, {
        provider,
        model,
        apiKey,
      });
      setActiveJobId(initRes.job_id);
      setJobStatus(initRes);
    } catch (e) {
      alert(`Generation failed: ${e.message}`);
      setIsGenerating(false);
    }
  };

  const handleRunScript = async (editedCode) => {
    setIsExecutingScript(true);
    try {
      const res = await executeEditedScript(
        editedCode,
        jobStatus?.specification?.parameters || null,
        mockMode,
        activeJobId || undefined
      );
      setJobStatus(res);
      setActiveJobId(res.job_id);
    } catch (e) {
      alert(`Script execution failed: ${e.message}`);
    } finally {
      setIsExecutingScript(false);
    }
  };

  return (
    <div className="app-container">
      {/* Header */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '42px', height: '42px', borderRadius: '12px',
            background: 'linear-gradient(135deg, #06b6d4, #2563eb)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'white', boxShadow: '0 4px 18px rgba(6, 182, 212, 0.4)'
          }}>
            <Box size={24} />
          </div>
          <div>
            <h1 style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.02em', background: 'linear-gradient(to right, #ffffff, #93c5fd)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Text-to-CAD RAG Agent
            </h1>
            <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>
              Hybrid Retrieval (Dense + BM25) • Dynamic LLM Switching • Python CAD Kernel • 3D Viewer
            </p>
          </div>
        </div>

        {/* Global Status Badges */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {jobStatus && (
            <span className={`badge ${
              jobStatus.status === 'completed' ? 'badge-success' :
              jobStatus.status === 'failed' ? 'badge-danger' :
              jobStatus.status === 'clarification_needed' ? 'badge-warning' : 'badge-cyan'
            }`}>
              Job {jobStatus.status.toUpperCase()}
            </span>
          )}
          <span className="badge badge-cyan">
            Kernel: Open CASCADE
          </span>
        </div>
      </header>

      {/* Provider Switcher Bar */}
      <ProviderSettings onProviderChanged={(p) => setActiveProvider(p)} />

      {/* Main 3-Column Layout */}
      <div className="main-grid">
        {/* Left Column: Prompt & Extraction & Diagnostics */}
        <div>
          <PromptPanel
            prompt={prompt}
            setPrompt={setPrompt}
            onGenerate={handleGenerateCAD}
            isGenerating={isGenerating}
            jobStatus={jobStatus}
            mockMode={mockMode}
            setMockMode={setMockMode}
          />
        </div>

        {/* Center Column: Editable Code Editor & Execution Logs */}
        <div>
          <CodeEditor
            initialCode={jobStatus?.generated_script || ''}
            onRunScript={handleRunScript}
            isRunning={isExecutingScript}
            executionReport={jobStatus?.execution_report}
            repairAttempts={jobStatus?.repair_attempts || []}
            jobId={activeJobId}
          />
        </div>

        {/* Right Column: Interactive 3D Model Viewer & Geometry Validation */}
        <div className="design-panel" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <ModelViewer
            jobId={activeJobId}
            isExecuting={isGenerating || isExecutingScript}
            validationReport={jobStatus?.validation_report}
            jobStatus={jobStatus}
          />
          <ValidationPanel
            validationReport={jobStatus?.validation_report}
            artifacts={jobStatus?.artifacts || []}
            jobId={activeJobId}
          />
        </div>
      </div>
    </div>
  );
}
