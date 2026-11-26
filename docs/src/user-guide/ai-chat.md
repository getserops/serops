---
seo_title: "AI chat about your incidents"
description: "Ask questions about your logs, issues and system health in natural language; SerOps answers from the analyses it already ran."
---
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

1. Click **AI Chat** in the sidebar
2. Type your question
3. The AI responds with context from your data

### With Batch Context

From the **Analyses** page:
1. Select a batch
2. In the **Analyze with AI** dropdown, choose **Chat about Batch**
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

!!! warning "A warning, then masking"
    Your message is scanned before it is sent. If it looks sensitive you get
    a warning. If you choose **Send anyway**, the server still masks what it
    detects in your message, and in the log lines chat pulls from the batch,
    before anything reaches the AI provider; anything it does not detect is
    sent as written (see
    [Current limits](../security/data-protection.md#current-limits)).

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

Configure the AI model in **Settings → AI Providers**.
SerOps supports a pluggable architecture. While **Gemini** and **DeepSeek** are defaults, you can add other providers (like Claude) with **Add Provider** on the same page (see [AI Settings](../admin/settings.md#ai-settings)).

| Model | Best For |
|-------|----------|
| **Gemini** | General analysis, faster responses (Default) |
| **DeepSeek** | Deep technical analysis, code understanding |
| **Custom** | Any compliant provider added with **Add Provider** |

### Fallback Configuration

If the primary model fails, SerOps automatically tries the fallback:

```
Primary (e.g., Gemini) → Fallback (e.g., DeepSeek)
```

The fallback model has no control in **Settings → AI Providers**. It is set through the API: `PUT /api/settings/ai/` with `fallback_provider` (the provider's id).

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
POST /api/chat/generate-text/
Content-Type: application/json

{
  "type": "chat",
  "prompt": {"message": "What caused the error in this batch?"},
  "ai_model": "gemini"
}
```

`"type": "chat"` is required: without it the request is treated as a batch analysis. To continue a conversation, add `"chat_id"` with the UUID of an existing chat; without it a new chat is created. `"batch_id"` attaches a batch to the chat.

### Get Chat History
```
GET /api/chat/chats/{chat_id}/
```

### List Sessions
```
GET /api/chat/chat-sessions/
```

### Delete Session
```
DELETE /api/chat/chats/delete/{chat_id}
```

---

## Related Pages

- [Analyses](batches.md) — Send batch context to chat
- [Issues](issues.md) — Send issues to AI for remediation guidance
- [Compare AI Models](../how-to/compare-ai-models.md) — Re-analyze with different models
- [Track AI Costs](../how-to/ai-costs.md) — Monitor token usage and costs
- [Data Protection](../security/data-protection.md) — PII redaction in chat messages
- [AI & Chat API](../api/ai.md) — REST API reference
