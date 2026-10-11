# AI & Chat API

Endpoints for AI-powered text generation, batch analysis, chat session management, and AI system administration.

## Generate Text (Chat)

```
POST /api/chat/generate-text/
```

**Request body:**

```json
{
  "prompt": "What caused the errors?",
  "ai_model": "gemini",
  "chat_id": "optional-session-id"
}
```

Sends a prompt to the AI model and returns the generated response. If `chat_id` is provided, the conversation continues within that existing session. If omitted, a new session is created.

## Trigger Batch Analysis

```
POST /api/chat/analyze-batch/
```

**Request body:**

```json
{
  "batch_id": "batch_20260107_143000",
  "model": "gemini"
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
PUT /api/chat/chats/{chat_id}/update/
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

Permanently deletes a chat session and all of its messages.

---

## AI Admin (Admin Only)

Endpoints for monitoring and managing AI provider health. These require admin-level permissions.

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
