/**
 * ChatIssues - AI Chat assistant page component
 * Refactored to use useChatIssues hook for state management
 * 
 * UI-only component (~220 lines, reduced from 663)
 */

import React from "react";
import { Dropdown, Offcanvas, Badge, Card } from "react-bootstrap";
import { FaBars, FaPaperPlane, FaTrashAlt, FaRobot, FaShieldAlt, FaLink, FaChartLine, FaExternalLinkAlt, FaCog, FaProjectDiagram, FaExclamationCircle } from "react-icons/fa";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useChatIssues } from "../hooks/useChatIssues";
import { renderFormattedText } from "../utils/textFormatters";
import SensitiveDataWarningModal from "./SensitiveDataWarningModal";
import SimilarIssues from "./SimilarIssues";
import "./ChatIssues.css";

/**
 * Generate commit URL based on SCM provider
 */
const getCommitUrl = (commit) => {
  if (!commit || !commit.sha) return null;

  // For now, return null if provider is unknown
  // In the future, this could look up the project's SCM integration
  if (commit.provider === 'gitlab' && commit.project_id) {
    return `https://gitlab.com/projects/${commit.project_id}/-/commit/${commit.sha}`;
  }
  if (commit.provider === 'github' && commit.project_id) {
    return `https://github.com/${commit.project_id}/commit/${commit.sha}`;
  }
  return null;
};

/**
 * Confidence badge color helper
 */
const getConfidenceBadge = (confidence) => {
  switch (confidence?.toUpperCase()) {
    case 'HIGH': return { bg: 'success', label: 'HIGH' };
    case 'MEDIUM': return { bg: 'warning', label: 'MED' };
    case 'LOW': return { bg: 'secondary', label: 'LOW' };
    default: return null;
  }
};

/**
 * Metric anomaly label helper
 */
const getMetricLabel = (anomalyType) => {
  switch (anomalyType) {
    case 'sustained_high': return 'Sustained High';
    case 'spike': return 'Metric Spike';
    default: return 'Metric Spike';
  }
};

const getMetricBadgeBg = (anomalyType) => {
  return anomalyType === 'sustained_high' ? 'warning' : 'info';
};

/**
 * Correlation Section - Shows commit and metric correlations
 */
const CorrelationSection = ({ issueContext }) => {
  if (!issueContext) return null;

  const relatedTraces = issueContext.related_traces || null;
  const hasTraceContext = relatedTraces && (relatedTraces.span_count || 0) > 0;
  const hasCorrelations = issueContext.has_commit_correlation || issueContext.has_metric_correlation || issueContext.has_cicd_correlation || hasTraceContext;
  if (!hasCorrelations) return null;

  const confidence = issueContext.correlation_confidence || '';
  const confidenceBadge = getConfidenceBadge(confidence);
  const anomalyType = issueContext.metric_anomaly_type || '';
  const details = issueContext.correlation_details || {};
  const metricAnomaly = details.metric_anomaly || {};

  return (
    <div className="correlation-section mb-3">
      <h6 className="text-muted mb-2">
        <FaLink className="me-2" />
        Correlations
        {confidenceBadge && (
          <Badge bg={confidenceBadge.bg} className="ms-2" style={{ fontSize: '0.65rem' }}>
            {confidenceBadge.label}
          </Badge>
        )}
      </h6>

      <div className="d-flex flex-wrap gap-2">
        {/* Commit correlation card */}
        {issueContext.has_commit_correlation && issueContext.linked_commits?.length > 0 && (
          <Card className="correlation-card commit-card" style={{ minWidth: '200px', maxWidth: '300px' }}>
            <Card.Body className="py-2 px-3">
              <div className="d-flex align-items-center justify-content-between mb-1">
                <Badge bg="purple" style={{ backgroundColor: '#7c3aed' }}>
                  <FaLink size={10} className="me-1" />
                  Code Change
                </Badge>
                {confidenceBadge && (
                  <Badge bg={confidenceBadge.bg} style={{ fontSize: '0.6rem' }}>
                    {confidenceBadge.label}
                  </Badge>
                )}
              </div>
              {issueContext.linked_commits.map((commit, idx) => {
                const sha = typeof commit === 'object' ? commit.sha : commit;
                const url = typeof commit === 'object' ? getCommitUrl(commit) : null;
                return (
                  <div key={idx} className="small">
                    <code className="text-primary">{String(sha).substring(0, 8)}</code>
                    {url && (
                      <a href={url} target="_blank" rel="noopener noreferrer" className="ms-2 text-muted">
                        <FaExternalLinkAlt size={10} />
                      </a>
                    )}
                  </div>
                );
              })}
            </Card.Body>
          </Card>
        )}

        {/* Metric correlation card */}
        {issueContext.has_metric_correlation && issueContext.metric_correlation_type && (
          <Card className="correlation-card metric-card" style={{ minWidth: '200px', maxWidth: '300px' }}>
            <Card.Body className="py-2 px-3">
              <div className="d-flex align-items-center justify-content-between mb-1">
                <Badge bg={getMetricBadgeBg(anomalyType)}>
                  <FaChartLine size={10} className="me-1" />
                  {getMetricLabel(anomalyType)}
                </Badge>
              </div>
              <div className="small">
                <span className="text-capitalize fw-medium">{issueContext.metric_correlation_type}</span>
                {metricAnomaly.peak_value != null && (
                  <span className="text-muted ms-1">peak {metricAnomaly.peak_value}%</span>
                )}
                {metricAnomaly.duration_seconds > 0 && (
                  <span className="text-muted ms-1">
                    ({Math.round(metricAnomaly.duration_seconds / 60)}m)
                  </span>
                )}
              </div>
            </Card.Body>
          </Card>
        )}

        {/* CI/CD pipeline failure correlation card */}
        {/* Related distributed traces from the issue's originating batch.
            Top slow + top error spans, each linking to the trace waterfall.
            Rendered only when the batch snapshotted spans (see #10.5). */}
        {hasTraceContext && (
          <Card className="correlation-card trace-card" style={{ minWidth: '260px', maxWidth: '380px' }}>
            <Card.Body className="py-2 px-3">
              <div className="d-flex align-items-center justify-content-between mb-1">
                <Badge bg={(relatedTraces.error_span_count || 0) > 0 ? 'danger' : 'info'}>
                  <FaProjectDiagram size={10} className="me-1" />
                  Traces
                </Badge>
                <small className="text-muted">
                  {relatedTraces.span_count} spans
                  {(relatedTraces.error_span_count || 0) > 0 && (
                    <span className="text-danger ms-1">
                      ({relatedTraces.error_span_count} err)
                    </span>
                  )}
                </small>
              </div>
              {(relatedTraces.top_errors || []).slice(0, 2).map((span, idx) => (
                <div key={`err-${idx}`} className="small text-truncate" style={{ maxWidth: '340px' }}>
                  <FaExclamationCircle size={9} className="me-1 text-danger" />
                  <span className="text-muted">{span.service_name || '?'}</span>
                  {' :: '}
                  <a
                    href={`/dash/traces/${span.trace_id}`}
                    className="text-decoration-none"
                    title={span.status_message || span.operation_name}
                  >{span.operation_name || '?'}</a>
                </div>
              ))}
              {(relatedTraces.top_slow || []).slice(0, 2).map((span, idx) => (
                <div key={`slow-${idx}`} className="small text-truncate" style={{ maxWidth: '340px' }}>
                  <span className="text-muted">{span.duration_ms}ms</span>{' '}
                  <span className="text-muted">{span.service_name || '?'}</span>
                  {' :: '}
                  <a
                    href={`/dash/traces/${span.trace_id}`}
                    className="text-decoration-none"
                    title={span.operation_name}
                  >{span.operation_name || '?'}</a>
                </div>
              ))}
            </Card.Body>
          </Card>
        )}

        {issueContext.has_cicd_correlation && (() => {
          const cicdDetail = details.cicd_correlation || {};
          const cicdConfidence = getConfidenceBadge(cicdDetail.confidence);
          return (
            <Card className="correlation-card cicd-card" style={{ minWidth: '200px', maxWidth: '320px' }}>
              <Card.Body className="py-2 px-3">
                <div className="d-flex align-items-center justify-content-between mb-1">
                  <Badge bg="secondary">
                    <FaCog size={10} className="me-1" />
                    Pipeline Failure
                  </Badge>
                  {cicdConfidence && (
                    <Badge bg={cicdConfidence.bg} style={{ fontSize: '0.6rem' }}>
                      {cicdConfidence.label}
                    </Badge>
                  )}
                </div>
                <div className="small">
                  {cicdDetail.job_name && (
                    <div><span className="text-muted">Job:</span> <span className="fw-medium">{cicdDetail.job_name}</span></div>
                  )}
                  {cicdDetail.pipeline_id && (
                    <div><span className="text-muted">Pipeline:</span> #{cicdDetail.pipeline_id}</div>
                  )}
                  {cicdDetail.commit_sha && (
                    <div><span className="text-muted">Commit:</span> <code className="text-primary">{cicdDetail.commit_sha}</code></div>
                  )}
                  {cicdDetail.trace_errors && (
                    <div className="mt-1 text-truncate" style={{ maxWidth: '280px' }} title={cicdDetail.trace_errors}>
                      <span className="text-danger" style={{ fontSize: '0.75rem' }}>{cicdDetail.trace_errors.substring(0, 80)}{cicdDetail.trace_errors.length > 80 ? '...' : ''}</span>
                    </div>
                  )}
                </div>
              </Card.Body>
            </Card>
          );
        })()}
      </div>
    </div>
  );
};


/**
 * AIAnalysisSection — shows the AI's reasoning chain, confidence, and
 * which past resolutions fed the prompt. Renders nothing when none of
 * those are present so old issues (analysed before this feature
 * shipped) stay clean.
 */
const AIAnalysisSection = ({ issueContext }) => {
  if (!issueContext) return null;

  const reasoning = (issueContext.reasoning || '').trim();
  const confidence = (issueContext.confidence || '').toUpperCase();
  const confidenceLabel = issueContext.confidence_display || confidence;
  const informedBy = issueContext.informed_by || { count: 0, items: [] };

  if (!reasoning && !confidence && informedBy.count === 0) {
    return null;
  }

  // Numbered steps are stored as "1. ...\n2. ...\n3. ...". Split for
  // an ordered list; fall back to plain text if the format is loose.
  const steps = reasoning
    .split(/\n+/)
    .map((line) => line.replace(/^\d+\.\s*/, '').trim())
    .filter(Boolean);

  const confidenceBadgeBg = {
    HIGH: 'success',
    MEDIUM: 'warning',
    LOW: 'secondary',
  }[confidence] || 'light';

  return (
    <div className="correlation-section mb-3">
      <h6 className="text-muted mb-2 d-flex align-items-center">
        <FaRobot className="me-2" />
        How SerOps reached this conclusion
        {confidence && confidence !== 'UNKNOWN' && (
          <Badge
            bg={confidenceBadgeBg}
            className="ms-2"
            title="The AI's self-reported confidence — LOW means evidence was thin and you should verify."
            style={{ fontSize: '0.65rem' }}
          >
            {confidenceLabel || confidence}
          </Badge>
        )}
      </h6>

      {steps.length > 0 && (
        <Card className="mb-2">
          <Card.Body className="py-2 px-3">
            <ol className="mb-0 ps-3 small">
              {steps.map((step, idx) => (
                <li key={idx} className="mb-1">{step}</li>
              ))}
            </ol>
          </Card.Body>
        </Card>
      )}

      {informedBy.count > 0 && (
        <div
          className="small text-muted mt-2"
          title={informedBy.items
            .map((it) => `#${it.id} ${it.issue_type} on ${it.component}`)
            .join('\n')}
        >
          <FaLink className="me-1" />
          Informed by {informedBy.count} past resolution
          {informedBy.count === 1 ? '' : 's'} on this project
          {informedBy.items.length > 0 && (
            <>
              :&nbsp;
              {informedBy.items.slice(0, 3).map((it, idx) => (
                <span key={it.id}>
                  {idx > 0 && ', '}
                  <span className="fw-medium">#{it.id}</span>
                  {' '}
                  <span>({it.issue_type} on {it.component})</span>
                </span>
              ))}
              {informedBy.items.length > 3 && ` and ${informedBy.items.length - 3} more`}
            </>
          )}
        </div>
      )}
    </div>
  );
};


const ChatIssues = () => {
  const { t } = useTranslation();
  const {
    // Context
    contextMessages,
    issueContext,  // Added for correlation display

    // State
    messages,
    input,
    setInput,
    selectedModel,
    isLoading,
    error,
    showHistory,
    chatHistory,
    messagesEndRef,
    loadedFromHistory,

    // Handlers
    handleSend,
    handleSelectModel,
    handleKeyPress,
    toggleHistory,
    loadChatFromHistory,
    deleteSession,

    // Sensitive data scan
    isScanning,
    showSensitiveWarning,
    availableModels, // Dynamic models list
    sensitiveFindings,
    handleSendAnyway,
    handleCancelSend,
  } = useChatIssues();

  // Helper to get display name for selected model. When no provider
  // is configured yet the toggle shows a prompt instead of a stale id.
  const getSelectedModelName = () => {
    if (!availableModels || availableModels.length === 0) {
      return t('chat.noModelConfigured', 'No AI provider');
    }
    const model = availableModels.find(m => m.id === selectedModel);
    return model ? model.name : selectedModel;
  };

  return (
    <div className="chat-page-wrapper">
      <div className="chat-container-modern">
        {/* Chat header */}
        <div className="chat-header">
          <div className="chat-header-left">
            <button
              className="history-toggle-btn"
              onClick={toggleHistory}
              title={t('chat.history')}
            >
              <FaBars size={20} />
            </button>
            <h3
              style={{
                margin: 0,
                fontSize: "var(--text-lg)",
                fontWeight: "var(--font-semibold)",
              }}
            >
              {t('chat.aiAssistant')}
            </h3>
          </div>
          <div className="chat-header-right">
            <span className="model-label">{t('chat.model')}:</span>
            <Dropdown onSelect={handleSelectModel} className="model-dropdown">
              <Dropdown.Toggle variant="outline-primary" size="sm">
                {getSelectedModelName()}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                {availableModels && availableModels.length > 0 ? (
                  availableModels.map(model => (
                    <Dropdown.Item key={model.id} eventKey={model.id}>
                      {model.name}
                    </Dropdown.Item>
                  ))
                ) : (
                  // Empty state — prior hardcoded [Gemini, DeepSeek]
                  // fallback would 500 on first chat message because the
                  // demo (or any freshly-installed org) has no matching
                  // API key. Point the admin at Settings instead.
                  <Dropdown.Item as={Link} to="/dash/settings/ai" className="text-muted">
                    {t('chat.configureAIInSettings', 'No AI provider configured — set one up in Settings → AI')}
                  </Dropdown.Item>
                )}
              </Dropdown.Menu>
            </Dropdown>
          </div>
        </div>

        {/* Messages area */}
        <div className="chat-messages-area">
          {/* AI reasoning + confidence + past-resolutions — only show for issue context */}
          {!loadedFromHistory && issueContext && (
            <AIAnalysisSection issueContext={issueContext} />
          )}

          {/* Correlation Section - only show for issue context */}
          {!loadedFromHistory && issueContext && (
            <CorrelationSection issueContext={issueContext} />
          )}

          {/* Similar past resolved incidents (Item #27) — hidden when
              this issue has no embedding yet or when there are no matches. */}
          {!loadedFromHistory && issueContext?.issueId && (
            <SimilarIssues issueId={issueContext.issueId} />
          )}

          {/* Context messages (analysis/issue context) - only show if NOT loaded from history */}
          {!loadedFromHistory && contextMessages.map((msg) => (
            <div
              key={msg.id}
              className={`message-row ${msg.sender === "bot" && !msg.isIssueContext ? "bot" : "user"
                }`}
            >
              <div
                className={`message-bubble ${msg.sender === "bot" ? "bot" : "user"} ${msg.isIssueContext ? "issue-context" : ""
                  }`}
              >
                <div className="message-sender">
                  {msg.sender === "bot" && !msg.isIssueContext
                    ? selectedModel
                    : msg.isIssueContext
                      ? t('chat.issueContext')
                      : t('chat.you')}
                </div>
                <div className="message-content">
                  {msg.sender === "bot" || msg.isIssueContext ? (
                    <div
                      dangerouslySetInnerHTML={{
                        __html: renderFormattedText(msg.text),
                      }}
                    />
                  ) : (
                    msg.text
                  )}
                </div>
                <div className="message-time">
                  {new Date(msg.timestamp).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </div>
            </div>
          ))}

          {/* Chat messages */}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-row ${msg.sender === "bot" ? "bot" : "user"}`}
            >
              <div
                className={`message-bubble ${msg.sender === "bot" ? "bot" : "user"}`}
              >
                <div className="message-sender">
                  {msg.sender === "bot" ? selectedModel : t('chat.you')}
                  {msg.isError && (
                    <span className="text-danger ms-2">({t('common.error')})</span>
                  )}
                </div>
                <div className="message-content">
                  {msg.sender === "bot" ? (
                    <div
                      dangerouslySetInnerHTML={{
                        __html: renderFormattedText(msg.text),
                      }}
                    />
                  ) : (
                    msg.text
                  )}
                </div>
                <div className="message-time">
                  {new Date(msg.timestamp).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </div>
            </div>
          ))}

          {/* Loading indicator */}
          {isLoading && (
            <div className="message-loading">
              <FaRobot />
              <span>{t('chat.isThinking', { model: selectedModel })}</span>
              <div className="typing-indicator">
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
                <div className="typing-dot"></div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="chat-input-area">
          {error && <div className="chat-error-alert">{error}</div>}

          <div className="chat-input-wrapper">
            <textarea
              placeholder={t('chat.placeholder')}
              className="chat-textarea"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={isLoading}
              rows={1}
            />
            <button
              className="send-button"
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
            >
              <FaPaperPlane size={18} />
            </button>
          </div>
        </div>
      </div>

      {/* Chat history sidebar */}
      <Offcanvas
        show={showHistory}
        onHide={toggleHistory}
        placement="start"
        className="history-panel"
      >
        <Offcanvas.Header closeButton>
          <Offcanvas.Title>{t('chat.history')}</Offcanvas.Title>
        </Offcanvas.Header>
        <Offcanvas.Body>
          {chatHistory.length === 0 ? (
            <div className="history-empty">{t('chat.noHistory')}</div>
          ) : (
            <div>
              {chatHistory.map((session, idx) => (
                <div
                  key={session.chat_id || idx}
                  className="history-item"
                  onClick={() => loadChatFromHistory(session)}
                >
                  <div className="history-item-content">
                    <div className="history-item-title">
                      {session.title || t('chat.untitledSession')}
                    </div>
                    <div className="history-item-meta">
                      {new Date(session.created_at).toLocaleDateString()}
                      <br />
                      {session.message_count} {t('chat.messages')}
                    </div>
                  </div>
                  <button
                    className="history-delete-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(session.chat_id);
                    }}
                    title={t('chat.deleteChat')}
                  >
                    <FaTrashAlt />
                  </button>
                </div>
              ))}
            </div>
          )}
        </Offcanvas.Body>
      </Offcanvas>

      {/* Sensitive Data Warning Modal */}
      <SensitiveDataWarningModal
        show={showSensitiveWarning}
        onHide={handleCancelSend}
        onSendAnyway={handleSendAnyway}
        onCancel={handleCancelSend}
        findings={sensitiveFindings}
      />
    </div>
  );
};

export default ChatIssues;
