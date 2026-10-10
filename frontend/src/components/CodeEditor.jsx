import React, { useState, useEffect } from 'react';
import { Play, RotateCcw, Download, Terminal, Wrench, FileCode, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function CodeEditor({
  initialCode,
  onRunScript,
  isRunning,
  executionReport,
  repairAttempts = [],
  jobId,
}) {
  const [code, setCode] = useState(initialCode || '');
  const [activeTab, setActiveTab] = useState('editor'); // 'editor', 'logs', 'repairs'

  useEffect(() => {
    if (initialCode) {
      setCode(initialCode);
    }
  }, [initialCode]);

  const handleReset = () => {
    setCode(initialCode || '');
  };

  const handleDownload = () => {
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'generated_model.py';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '640px', overflow: 'hidden' }}>
      {/* Editor Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', background: 'rgba(0,0,0,0.2)'
      }}>
        {/* Tabs */}
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            className={`btn btn-sm ${activeTab === 'editor' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('editor')}
            style={{ fontSize: '0.75rem', padding: '4px 10px' }}
          >
            <FileCode size={13} />
            Python Script
          </button>
          <button
            className={`btn btn-sm ${activeTab === 'logs' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('logs')}
            style={{ fontSize: '0.75rem', padding: '4px 10px' }}
          >
            <Terminal size={13} />
            Execution Logs {executionReport?.exit_code !== undefined && `(Code: ${executionReport.exit_code})`}
          </button>
          {repairAttempts && repairAttempts.length > 0 && (
            <button
              className={`btn btn-sm ${activeTab === 'repairs' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('repairs')}
              style={{ fontSize: '0.75rem', padding: '4px 10px', background: activeTab === 'repairs' ? 'var(--warning)' : undefined }}
            >
              <Wrench size={13} />
              Repairs ({repairAttempts.length})
            </button>
          )}
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleReset}
            title="Reset code to original generated model"
          >
            <RotateCcw size={13} />
            Reset
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleDownload}
            title="Download script"
          >
            <Download size={13} />
            Download
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => onRunScript(code)}
            disabled={isRunning || !code.trim()}
          >
            <Play size={13} />
            {isRunning ? 'Executing CAD...' : 'Run CAD Script'}
          </button>
        </div>
      </div>

      {/* Main Tab Views */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {/* Editor View */}
        {activeTab === 'editor' && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              spellCheck="false"
              className="font-mono"
              placeholder="# Generated Python CAD script will appear here..."
              style={{
                width: '100%',
                height: '100%',
                padding: '16px',
                background: '#070a12',
                color: '#e2e8f0',
                border: 'none',
                resize: 'none',
                outline: 'none',
                fontSize: '0.85rem',
                lineHeight: '1.6',
                fontFamily: 'JetBrains Mono, monospace',
                tabSize: 4,
              }}
            />
          </div>
        )}

        {/* Execution Logs View */}
        {activeTab === 'logs' && (
          <div style={{ height: '100%', padding: '16px', background: '#05070d', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-muted)', marginBottom: '10px' }}>
              CAD Kernel: {executionReport?.cad_engine_version || 'Not executed yet'} | Duration: {executionReport?.execution_duration_seconds || 0}s
            </div>

            {executionReport?.stdout && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#34d399', marginBottom: '4px' }}>[STDOUT]</div>
                <pre className="font-mono" style={{ fontSize: '0.8rem', color: '#cbd5e1', whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
                  {executionReport.stdout}
                </pre>
              </div>
            )}

            {executionReport?.stderr && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#f87171', marginBottom: '4px' }}>[STDERR / DIAGNOSTICS]</div>
                <pre className="font-mono" style={{ fontSize: '0.8rem', color: '#fca5a5', whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
                  {executionReport.stderr}
                </pre>
              </div>
            )}

            {!executionReport?.stdout && !executionReport?.stderr && (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.825rem', textAlign: 'center', marginTop: '40px' }}>
                No execution logs recorded yet. Click "Run CAD Script" to execute.
              </div>
            )}
          </div>
        )}

        {/* Repair History View */}
        {activeTab === 'repairs' && (
          <div style={{ height: '100%', padding: '16px', background: '#05070d', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#fbbf24', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <AlertTriangle size={15} />
              Bounded Self-Healing Repairs Triggered ({repairAttempts.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {repairAttempts.map((att, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(245, 158, 11, 0.08)',
                    border: '1px solid rgba(245, 158, 11, 0.25)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '0.775rem', fontWeight: 600 }}>
                    <span style={{ color: '#fbbf24' }}>Attempt #{att.attempt_number}: {att.error_category}</span>
                    <span style={{ color: 'var(--text-muted)' }}>Query: {att.retrieval_query}</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#fca5a5', marginBottom: '8px' }}>
                    Error: {att.error_message}
                  </div>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setCode(att.repaired_script);
                      setActiveTab('editor');
                    }}
                    style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                  >
                    Load Repaired Script #{att.attempt_number}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Editor Footer */}
      <div style={{
        padding: '6px 14px', background: 'rgba(0,0,0,0.3)', borderTop: '1px solid var(--border-subtle)',
        display: 'flex', justifyContent: 'space-between', fontSize: '0.725rem', color: 'var(--text-muted)'
      }}>
        <span>Status: {isRunning ? 'Executing script...' : 'Ready'}</span>
        <span>Isolated Job: {jobId || 'None'}</span>
      </div>
    </div>
  );
}
