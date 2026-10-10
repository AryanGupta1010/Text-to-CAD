import React from 'react';
import { CheckCircle2, XCircle, Download, FileText, Box, Layers, ShieldCheck } from 'lucide-react';
import { getArtifactDownloadUrl } from '../services/api';

export default function ValidationPanel({
  validationReport,
  artifacts = [],
  jobId,
}) {
  const isValid = validationReport?.valid;

  return (
    <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <ShieldCheck size={18} color="var(--primary)" />
          Kernel Geometry Validation
        </h3>
        {validationReport ? (
          <span className={`badge ${isValid ? 'badge-success' : 'badge-danger'}`}>
            {isValid ? 'Geometry Validated' : 'Validation Failed'}
          </span>
        ) : (
          <span className="badge badge-warning">Awaiting Execution</span>
        )}
      </div>

      {/* Validation Checks List */}
      <div>
        <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
          Topological & Dimensional Verification Checks
        </label>
        {validationReport?.checks && validationReport.checks.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {validationReport.checks.map((chk, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                  padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                  background: chk.passed ? 'rgba(16, 185, 129, 0.06)' : 'rgba(239, 68, 68, 0.08)',
                  border: `1px solid ${chk.passed ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.25)'}`,
                  fontSize: '0.775rem'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  {chk.passed ? (
                    <CheckCircle2 size={15} color="#34d399" style={{ marginTop: '2px', flexShrink: 0 }} />
                  ) : (
                    <XCircle size={15} color="#f87171" style={{ marginTop: '2px', flexShrink: 0 }} />
                  )}
                  <div>
                    <div style={{ fontWeight: 600, color: chk.passed ? '#f3f4f6' : '#fca5a5' }}>
                      {chk.check_name}
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginTop: '2px' }}>
                      {chk.explanation}
                    </div>
                  </div>
                </div>

                <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: '8px' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>
                    Meas: {String(chk.measured_value)}
                  </div>
                  {chk.expected_value !== undefined && (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>
                      Exp: {String(chk.expected_value)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: '0.775rem', color: 'var(--text-muted)', padding: '12px', textAlign: 'center', background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius-sm)' }}>
            No geometric validation checks performed yet.
          </div>
        )}
      </div>

      {/* Artifact Downloads */}
      <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
        <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
          Verified Artifact Downloads
        </label>
        {jobId && artifacts && artifacts.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {artifacts.map((art, idx) => (
              <a
                key={idx}
                href={getArtifactDownloadUrl(jobId, art.format.toLowerCase())}
                download={art.filename}
                className="btn btn-secondary btn-sm"
                style={{ textDecoration: 'none', justifyContent: 'flex-start', fontSize: '0.75rem', padding: '7px 10px' }}
              >
                <Download size={13} color="var(--primary)" />
                <span>{art.filename}</span>
                <span style={{ fontSize: '0.675rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                  ({Math.round(art.file_size_bytes / 1024)} KB)
                </span>
              </a>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Generated CAD artifacts (.step, .stl, .FCStd) will be available here after execution.
          </div>
        )}
      </div>
    </div>
  );
}
