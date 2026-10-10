import React, { useState } from 'react';
import { Sparkles, HelpCircle, AlertCircle, Layers, Check, Database, ChevronDown, ChevronUp } from 'lucide-react';

const SAMPLE_PROMPTS = [
  {
    label: 'Cylindrical Container (Primary Example)',
    prompt: 'Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and bottom thickness of 4 mm. Export it as a STEP file.',
  },
  {
    label: 'Mechanical Box / Enclosure',
    prompt: 'Create a rectangular box with length 60 mm, width 40 mm, and height 25 mm. Export as STEP and STL.',
  },
  {
    label: 'Precision Bushing / Sleeve',
    prompt: 'Create a cylindrical bushing with outer radius 25 mm, inner bore radius 15 mm, and length 60 mm. Export as STEP and STL.',
  },
  {
    label: 'Primitive Solid Cylinder',
    prompt: 'Create a solid cylinder with radius 20 mm and height 50 mm. Export it as a STEP file.',
  },
];

export default function PromptPanel({
  prompt,
  setPrompt,
  onGenerate,
  isGenerating,
  jobStatus,
  mockMode,
  setMockMode,
}) {
  const [formats, setFormats] = useState(['STEP', 'STL']);
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  const toggleFormat = (fmt) => {
    if (formats.includes(fmt)) {
      setFormats(formats.filter((f) => f !== fmt));
    } else {
      setFormats([...formats, fmt]);
    }
  };

  const handleGenerateClick = () => {
    if (!prompt.trim() || isGenerating) return;
    onGenerate(prompt, mockMode, formats);
  };

  const diagnostics = jobStatus?.retrieval_diagnostics;
  const isClarification = jobStatus?.status === 'clarification_needed';

  return (
    <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={18} color="var(--primary)" />
            Natural-Language CAD Request
          </h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>FreeCAD RAG Agent</span>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '12px', lineHeight: '1.4' }}>
          Describe your 3D mechanical component. The RAG system retrieves FreeCAD API documentation, constructs verified geometry, validates dimensions, and renders in 3D.
        </p>

        {/* Prompt Input */}
        <textarea
          className="input-field"
          rows={5}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Create a hollow cylindrical container with an outer radius of 30 mm, height of 100 mm, wall thickness of 3 mm, and a closed bottom of thickness 4 mm. Export it as a STEP file."
          style={{ resize: 'vertical', fontSize: '0.875rem', lineHeight: '1.5' }}
        />
      </div>

      {/* Preset Chips */}
      <div>
        <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
          Quick Templates
        </label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {SAMPLE_PROMPTS.map((item, idx) => (
            <button
              key={idx}
              className="btn btn-secondary btn-sm"
              onClick={() => setPrompt(item.prompt)}
              style={{ justifyContent: 'flex-start', textAlign: 'left', fontSize: '0.75rem', padding: '6px 10px' }}
            >
              <span style={{ color: 'var(--primary)', fontWeight: 600 }}>•</span>
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* Options: Output Formats & Mock Mode */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
        <div>
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
            Target Formats
          </label>
          <div style={{ display: 'flex', gap: '8px' }}>
            {['STEP', 'STL', 'FCStd'].map((fmt) => (
              <label
                key={fmt}
                style={{
                  display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem',
                  cursor: 'pointer', userSelect: 'none', color: formats.includes(fmt) ? 'var(--text-primary)' : 'var(--text-muted)'
                }}
              >
                <input
                  type="checkbox"
                  checked={formats.includes(fmt)}
                  onChange={() => toggleFormat(fmt)}
                  style={{ accentColor: 'var(--primary)' }}
                />
                {fmt}
              </label>
            ))}
          </div>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          <input
            type="checkbox"
            checked={mockMode}
            onChange={(e) => setMockMode(e.target.checked)}
            style={{ accentColor: 'var(--warning)' }}
          />
          <span>Offline Mock Mode</span>
        </label>
      </div>

      {/* Generate Button */}
      <button
        className="btn btn-primary"
        onClick={handleGenerateClick}
        disabled={isGenerating || !prompt.trim()}
        style={{ width: '100%', padding: '12px', fontSize: '0.925rem' }}
      >
        {isGenerating ? (
          <>
            <span className="spin" style={{ display: 'inline-block', width: '14px', height: '14px', border: '2px solid white', borderTopColor: 'transparent', borderRadius: '50%' }}></span>
            Executing RAG Workflow ({jobStatus?.status || 'Processing'})...
          </>
        ) : (
          <>
            <Sparkles size={16} />
            Generate & Validate CAD Model
          </>
        )}
      </button>

      {/* Clarification Alert */}
      {isClarification && (
        <div style={{
          padding: '12px', borderRadius: 'var(--radius-sm)',
          background: 'var(--warning-bg)', border: '1px solid rgba(245, 158, 11, 0.3)',
          color: '#fbbf24', fontSize: '0.8rem'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, marginBottom: '6px' }}>
            <AlertCircle size={16} />
            Clarification Required:
          </div>
          <ul style={{ paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {jobStatus?.specification?.clarification_questions?.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Retrieval Diagnostics Accordion */}
      {diagnostics && (
        <div style={{ marginTop: '4px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowDiagnostics(!showDiagnostics)}
            style={{ width: '100%', justifyContent: 'space-between', fontSize: '0.75rem' }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Database size={13} color="var(--primary)" />
              Retrieval Diagnostics (Dense: {diagnostics.dense_results_count}, BM25: {diagnostics.bm25_results_count})
            </span>
            {showDiagnostics ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {showDiagnostics && (
            <div style={{ marginTop: '10px', fontSize: '0.75rem', background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>Constructed Queries:</div>
              <ul style={{ paddingLeft: '16px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                {diagnostics.queries.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
              <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>Top Selected Chunks:</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {diagnostics.selected_documents.map((d, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', color: '#93c5fd' }}>
                    <span>• [{d.document_type}] {d.metadata?.title || d.document_id}</span>
                    <span style={{ color: 'var(--text-muted)' }}>score: {d.rerank_score}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
