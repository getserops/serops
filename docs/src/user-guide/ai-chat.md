# AI Chat

The AI Chat provides contextual conversations about your logs, issues, and system health.

## Overview

SerOps AI Chat is powered by pluggable AI models (Claude, Gemini, DeepSeek, or any OpenAI-compatible provider, including a local Ollama). It understands:

- Your application logs
- Recent deployments and code changes
- Issue history and root causes
- Infrastructure metrics

---

## Starting a Chat

### New Conversation

1. Click the **Chat** icon in the sidebar
2. Type your question
3. The AI responds with context from your data

### With Batch Context

From the **Data** page:
1. Select a batch
2. Click **Chat about Batch**
3. The batch context is automatically included

---

## Chat Features

### Session Management

| Feature | Description |
|---------|-------------|
| **New Session** | Start fresh conversation |
| **Session History** | View past conversations |
| **Delete Session** | Remove old conversations |

### Context Awareness

The AI has access to:
- Last 24 hours of logs (configurable)
- Recent code changes from GitLab/GitHub
- Active issues and their severity
- System health metrics

---

## Sensitive Data Protection

!!! warning "Real-Time Scanning"
    All messages are scanned for sensitive data before sending to AI.

### How It Works

1. You type a message
2. SerOps scans for PII, credentials, API keys
3. If found → **Warning Modal** appears
4. Choose to edit, send anyway, or cancel

### What Gets Detected

- API keys and tokens
- Passwords and secrets
- Email addresses
- Credit card numbers
- Connection strings

See [Data Protection](../security/data-protection.md) for full details.

---

## Best Practices

!!! tip "Getting Better Responses"
    1. **Be Specific** - "Why did service X fail at 2pm?" vs "What's wrong?"
    2. **Reference Batches** - Use "Chat about Batch" for context
    3. **Ask Follow-ups** - The AI remembers conversation history
    4. **Request Actions** - "Show me the logs for this error"

### Example Questions

| Question | What AI Uses |
|----------|--------------|
| "What caused the spike in errors yesterday?" | Log analysis + deployment timeline |
| "Compare this batch with last week" | Historical batch data |
| "Is the payment service healthy?" | Metrics + recent issues |
| "What changed in the last deployment?" | Code change tracking |

---

## Model Selection

Configure the AI model in **Settings → AI**.
SerOps supports a pluggable architecture. While **Gemini** and **DeepSeek** are defaults, you can register other providers (like Claude) in the database.

| Model | Best For |
|-------|----------|
| **Gemini** | General analysis, faster responses (Default) |
| **DeepSeek** | Deep technical analysis, code understanding |
| **Custom** | Any compliant provider added to `AIModelProvider` |

### Fallback Configuration

If the primary model fails, SerOps automatically tries the fallback:

```
Primary (e.g., Gemini) → Fallback (e.g., DeepSeek)
```

---

## Performance & Quota

### Turbo Mode (Heuristics)
Turbo Mode is an automatic backend optimization -- it is not a user-configurable setting. SerOps uses **Heuristic Intent Detection** to save API quota and improve speed.
If your question contains keywords like `logs`, `metrics`, `issues`, or `code`, the system **automatically injects** the data without making an extra API call.

**Benefits**:
- **50% Less Quota**: Skips the "Intent Classification" step.
- **Guaranteed Context**: Data is always loaded for technical queries.

---

## API Reference

### Send Message
```
POST /api/ai/generate/
Content-Type: application/json

{
  "prompt": "What caused the error in batch_20260107?",
  "ai_model": "gemini",
  "chat_id": "optional-session-id"
}
```

### Get Chat History
```
GET /api/ai/chat/{chat_id}/history/
```

### List Sessions
```
GET /api/ai/chat/sessions/
```

### Delete Session
```
DELETE /api/ai/chat/{chat_id}/
```

---

## Related Pages

- [Batches & Analysis](batches.md) — Send batch context to chat
- [Issues](issues.md) — Send issues to AI for remediation guidance
- [Compare AI Models](../how-to/compare-ai-models.md) — Re-analyze with different models
- [Track AI Costs](../how-to/ai-costs.md) — Monitor token usage and costs
- [Data Protection](../security/data-protection.md) — PII redaction in chat messages
- [AI & Chat API](../api/ai.md) — REST API reference
