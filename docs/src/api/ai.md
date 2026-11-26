---
seo_title: "AI and chat API"
description: "API endpoints for SerOps batch analysis, AI chat sessions and AI provider administration."
---
# AI & Chat API

Endpoints for AI-powered text generation, batch analysis, chat session management, and AI system administration.

## Generate Text (Chat)

```
POST /api/chat/generate-text/
```

**Request body:**

```json
{
  "type": "chat",
  "prompt": {"message": "What caused the errors?"},
  "ai_model": "gemini",
  "chat_id": "3f0c9a52-6d1e-4b8a-9c2f-1e7d5a4b8c90",
  "batch_id": "batch_20260107_143000"
}
```

Sends a prompt to the AI model and returns the generated response. `"type": "chat"` is required for a chat message; without it the endpoint expects a batch-analysis request instead. `chat_id` (a UUID) and `batch_id` are optional. If `chat_id` is provided, the conversation continues within that existing session. If omitted, a new session is created. When the organisation's monthly AI budget is spent, it returns `409`.

## Trigger Batch Analysis

```
POST /api/chat/analyze-batch/
```

**Request body:**

```json
{
  "batch_id": "batch_20260107_143000"
}
```

Queues an AI analysis job for the specified batch. The analysis runs asynchronously and creates issues when problems are detected.

## List Chat Sessions

```
GET /api/chat/chat-sessions/
```

Returns all chat sessions for the authenticated user.

## Get Chat History

```
GET /api/chat/chats/{chat_id}/
```

Returns the full message history and details for a specific chat session.

## Update Chat Session

```
PATCH /api/chat/chats/{chat_id}/update/
```

**Request body:**

```json
{
  "title": "Payment latency investigation"
}
```

Renames a chat session. Only fields you include are changed.

## Delete Chat Session

```
DELETE /api/chat/chats/delete/{chat_id}
```

Archives the chat session: it is hidden from the session lists and can no longer be continued. The response is `{"status": "success", "message": "Chat session archived"}`.

---

## AI Admin (Platform Staff Only)

Endpoints for monitoring and managing AI provider health. These require the `platform.manage` permission, which only platform staff (`is_staff`) hold; an organisation admin gets `403`.

### Get AI Health Status

```
GET /api/chat/admin/health/
```

**Response:**

```json
{
  "status": "healthy",
  "providers": {
    "gemini": {"circuit": "CLOSED", "available": true, "rate_remaining": 8},
    "deepseek": {"circuit": "CLOSED", "available": true}
  }
}
```

Returns the overall health status of all configured AI providers.

### Get Circuit Breaker Status

```
GET /api/chat/admin/circuits/
```

Shows the circuit breaker state (`CLOSED`, `OPEN`, or `HALF_OPEN`), failure count, and recovery time for each AI provider.

### Get Rate Limit Status

```
GET /api/chat/admin/rates/
```

Shows remaining requests per minute/hour for each provider.

### Reset Circuit Breaker

```
POST /api/chat/admin/circuits/{provider}/reset/
```

Manually closes a circuit to resume requests after the provider has recovered.

`{provider}` is `gemini`, `deepseek`, `claude` or `openai` for reset and trip; any other name returns 400.

### Trip Circuit Breaker

```
POST /api/chat/admin/circuits/{provider}/trip/
```

**Request body:**

```json
{
  "duration": 300
}
```

Manually opens a circuit to block requests during maintenance. The `duration` is in seconds.

---

## Related

- [Batches & Data](batches.md) -- Batch data that AI analyzes
- [Issues](issues.md) -- Issues created by AI analysis
- [Settings & Admin](settings.md) -- AI settings at the organisation level
- [API Overview](overview.md) -- Base URL, response format, and error codes
