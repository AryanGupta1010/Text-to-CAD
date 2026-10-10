import React, { useState, useEffect } from 'react';
import { Settings2, Cpu, CheckCircle2, XCircle, Loader2, Key, Globe, Shield, RefreshCw } from 'lucide-react';
import { fetchProviders, testProviderConfig, applyProviderSettings, fetchCadEngineStatus } from '../services/api';

export default function ProviderSettings({ onProviderChanged }) {
  const [isOpen, setIsOpen] = useState(false);
  const [providerType, setProviderType] = useState('ollama');
  
  // Cloud settings
  const [cloudProvider, setCloudProvider] = useState('openai');
  const [cloudApiKey, setCloudApiKey] = useState('');
  const [cloudBaseUrl, setCloudBaseUrl] = useState('https://api.openai.com/v1');
  const [cloudModel, setCloudModel] = useState('gpt-4o-mini');
  
  // Ollama settings
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState('http://localhost:11434');
  const [ollamaModel, setOllamaModel] = useState('qwen3:latest');

  // Status & testing
  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [cadEngine, setCadEngine] = useState(null);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const providers = await fetchProviders();
      const current = providers.find((p) => p.current);
      if (current) {
        setProviderType(current.provider_id);
      }
      const cad = await fetchCadEngineStatus();
      setCadEngine(cad);
    } catch (e) {
      console.warn('Could not load status on mount:', e);
    }
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await testProviderConfig({
        provider: providerType,
        cloud_provider: cloudProvider,
        cloud_api_key: cloudApiKey || undefined,
        cloud_base_url: cloudBaseUrl,
        cloud_model: cloudModel,
        ollama_base_url: ollamaBaseUrl,
        ollama_model: ollamaModel,
      });
      setTestResult(res);
    } catch (e) {
      setTestResult({
        success: false,
        message: e.message || 'Connection test failed',
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleApplySettings = async () => {
    setIsSaving(true);
    try {
      await applyProviderSettings({
        provider: providerType,
        cloud_provider: cloudProvider,
        cloud_api_key: cloudApiKey || undefined,
        cloud_base_url: cloudBaseUrl,
        cloud_model: cloudModel,
        ollama_base_url: ollamaBaseUrl,
        ollama_model: ollamaModel,
      });
      if (onProviderChanged) onProviderChanged(providerType);
      setIsOpen(false);
    } catch (e) {
      alert(`Failed to save settings: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="glass-panel" style={{ padding: '16px 20px', marginBottom: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '38px', height: '38px', borderRadius: '10px',
            background: 'linear-gradient(135deg, rgba(6,182,212,0.2), rgba(59,130,246,0.2))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--primary)', border: '1px solid var(--border-subtle)'
          }}>
            <Cpu size={20} />
          </div>
          <div>
            <div style={{ fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>LLM Provider:</span>
              <span className={`badge ${providerType === 'ollama' ? 'badge-cyan' : providerType === 'cloud' ? 'badge-success' : 'badge-warning'}`}>
                {providerType === 'ollama' ? 'Ollama (Local)' : providerType === 'cloud' ? 'Cloud API' : 'Mock (Offline)'}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                ({providerType === 'ollama' ? ollamaModel : providerType === 'cloud' ? cloudModel : 'Deterministic Mock'})
              </span>
            </div>
            <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
              CAD Kernel: <strong style={{ color: cadEngine?.runtime_available ? '#34d399' : '#22d3ee' }}>
                {cadEngine?.status || 'Detecting...'}
              </strong>
            </div>
          </div>
        </div>

        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsOpen(!isOpen)}
          style={{ gap: '6px' }}
        >
          <Settings2 size={15} />
          {isOpen ? 'Close Settings' : 'Configure Runtime'}
        </button>
      </div>

      {isOpen && (
        <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          {/* Provider Selection */}
          <div style={{ marginBottom: '16px' }}>
            <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
              Select Active Inference Engine
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
              {[
                { id: 'ollama', label: 'Local Ollama', sub: 'Private local LLM inference' },
                { id: 'cloud', label: 'Cloud API', sub: 'OpenAI / OpenRouter API' },
                { id: 'mock', label: 'Offline Mock', sub: 'Deterministic test simulator' },
              ].map((p) => (
                <div
                  key={p.id}
                  onClick={() => setProviderType(p.id)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-sm)',
                    background: providerType === p.id ? 'rgba(6, 182, 212, 0.12)' : 'rgba(0,0,0,0.25)',
                    border: `1px solid ${providerType === p.id ? 'var(--primary)' : 'var(--border-subtle)'}`,
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <div style={{ fontSize: '0.85rem', fontWeight: 600, color: providerType === p.id ? 'var(--primary)' : 'var(--text-primary)' }}>
                    {p.label}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>{p.sub}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Ollama Form */}
          {providerType === 'ollama' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Ollama Server URL
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={ollamaBaseUrl}
                  onChange={(e) => setOllamaBaseUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Ollama Model Identifier
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  placeholder="qwen3:latest or qwen2.5-coder:7b"
                />
              </div>
            </div>
          )}

          {/* Cloud API Form */}
          {providerType === 'cloud' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  API Key (Stored in Session Memory)
                </label>
                <input
                  type="password"
                  className="input-field"
                  value={cloudApiKey}
                  onChange={(e) => setCloudApiKey(e.target.value)}
                  placeholder="sk-..."
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Base URL (OpenAI / OpenRouter / Local Proxy)
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={cloudBaseUrl}
                  onChange={(e) => setCloudBaseUrl(e.target.value)}
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Cloud Model Identifier
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={cloudModel}
                  onChange={(e) => setCloudModel(e.target.value)}
                  placeholder="gpt-4o-mini or claude-3-5-sonnet"
                />
              </div>
            </div>
          )}

          {/* Action Row */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleTestConnection}
                disabled={isTesting}
              >
                {isTesting ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                Test Connection
              </button>

              {testResult && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.775rem',
                  color: testResult.success ? '#34d399' : '#f87171'
                }}>
                  {testResult.success ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                  <span>{testResult.message} {testResult.latency_ms ? `(${testResult.latency_ms}ms)` : ''}</span>
                </div>
              )}
            </div>

            <button
              className="btn btn-primary btn-sm"
              onClick={handleApplySettings}
              disabled={isSaving}
            >
              {isSaving ? <Loader2 size={14} className="spin" /> : null}
              Apply Configuration
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
