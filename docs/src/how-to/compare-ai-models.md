---
seo_title: "Compare AI models on the same incident"
description: "Re-analyse a batch with another AI model and compare the root causes side by side to pick the best model for your workload."
---
# Compare AI Models

Re-analyze batches with different AI models and compare the results side by side to find the best model for your workload.

---

## When to Use Model Comparison

| Scenario | Recommendation |
|----------|----------------|
| Evaluating a new AI provider | Run the same batches through both models and compare quality |
| Cost optimization | Compare a thorough model against a cheaper one |
| Critical incidents | Re-analyze with a second model for a second opinion |
| Initial setup | Benchmark models on your log patterns before committing to one |

### Common Model Characteristics

The models available for re-analysis depend on your organisation's configured API keys. Common options include:

| Model | Strengths | Trade-offs |
|-------|-----------|------------|
| **Gemini 1.5 Pro** | Thorough analysis, strong root-cause identification | Higher cost, slower |
| **Gemini 1.5 Flash** | Good balance of speed and quality | Moderate cost |
| **DeepSeek Chat** | Fast, cost-effective | May miss subtle patterns in complex logs |
| **GPT-4** | Strong reasoning | Higher cost per token |
| **Claude** | Excellent reasoning and nuance | Higher cost |

!!! note
    Any AI provider registered in **Settings > AI Providers** with a valid API key for your organisation will appear as a re-analysis option. See [Admin Guide - Settings](../admin/settings.md) for how to configure providers.

---

## Step 1: Select Batches

1. Navigate to the **Data** page
2. Use filters to narrow down batches:
    - **Environment**: Production, Staging, or Development
    - **Date range**: Select the time period of interest
    - **Service**: Filter by specific service
3. Select one or more batches using the checkboxes

!!! tip
    For the most meaningful comparison, select batches with diverse log patterns -- including both routine operations and error-heavy periods.

---

## Step 2: Re-Analyze with a Different Model

1. Click the **"Analyze with AI"** dropdown button
2. The dropdown dynamically shows all models your organisation has configured (based on active API keys)
3. Select the model you want to use for re-analysis
4. A confirmation dialog appears showing the number of batches and estimated token usage
5. Click **Confirm**

The re-analysis task is queued as a background Celery task. Processing time depends on batch size and model.

!!! info
    Re-analysis does not replace the original analysis. Each model's results are stored separately, allowing you to compare them.

!!! warning "No models showing?"
    If the dropdown is empty, your organisation has no API keys configured for any active AI provider. Ask your admin to add API keys in **Settings > AI Providers**.

---

## Step 3: Wait for Processing

After submitting the re-analysis request:

- A notification appears confirming the task was queued
- The batch status updates to **"Analyzing"** while processing
- Once complete, the status returns to **"Analyzed"** with a badge showing the number of models that have analyzed this batch

You can continue using SerOps while the re-analysis runs in the background.

---

## Step 4: Compare Model Results

1. Select a batch that has been analyzed by multiple models
2. Click the **"Analyze with AI"** dropdown
3. Select **"Compare Model Results"**
4. A side-by-side comparison view opens showing:

    | Section | What It Shows |
    |---------|---------------|
    | **Summary** | Each model's high-level summary of the batch |
    | **Issues Found** | Issues identified by each model with severity ratings |
    | **Root Causes** | Root cause analysis from each model |
    | **Recommendations** | Suggested actions from each model |

---

## Using the API

### List Available Models

First, check which models your organisation can use:

```bash
curl https://api.yourdomain.com/api/settings/ai/available-models/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Response:

```json
{
  "models": [
    {"id": "gemini", "name": "Google Gemini"},
    {"id": "deepseek", "name": "DeepSeek"},
    {"id": "claude", "name": "Claude"}
  ]
}
```

Only models with an active API key (configured under Settings → AI Providers) are returned. If your organisation has no keys configured, this returns an empty list.

### Queue a Re-Analysis

The `model` field accepts any provider name returned by the available models endpoint:

```bash
curl -X POST https://api.yourdomain.com/api/data/batches/reanalyze/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "batch_ids": ["batch-001", "batch-002"],
    "model": "deepseek"
  }'
```

Response:

```json
{
  "status": "queued",
  "message": "2 batches queued for re-analysis with deepseek"
}
```

### View Analysis History

```bash
curl https://api.yourdomain.com/api/data/batches/batch-001/history/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Response:

```json
{
  "analysis_count": 2,
  "analysis_history": [
    {
      "model": "gemini-1.5-pro",
      "analyzed_at": "2026-02-17T08:00:00Z",
      "tokens_input": 12000,
      "tokens_output": 3420,
      "cost_usd": "0.004626"
    },
    {
      "model": "deepseek-chat",
      "analyzed_at": "2026-02-17T09:30:00Z",
      "tokens_input": 10500,
      "tokens_output": 2300,
      "cost_usd": "0.000538"
    }
  ]
}
```

---

## Cost Awareness

Each re-analysis consumes AI tokens that are recorded for [cost visibility](ai-costs.md). Token usage (input and output) is tracked per re-analysis and visible in the analysis history.

Estimate token spend before running large batch comparisons. Reference pricing for common models:

| Model | Approximate Cost per 1M Input Tokens | Approximate Cost per 1M Output Tokens |
|-------|---------------------------------------|----------------------------------------|
| Gemini 1.5 Pro | $0.075 | $0.30 |
| Gemini 1.5 Flash | $0.02 | $0.08 |
| DeepSeek Chat | $0.014 | $0.028 |
| GPT-4 | $0.03 | $0.06 |

!!! warning
    Running re-analysis on a large number of batches can consume significant tokens. Start with a small sample to evaluate model quality before scaling up.

---

## Next Steps

- [Track AI Costs](ai-costs.md) -- monitor token usage and spending
- [Batches & Analysis](../user-guide/batches.md) -- learn more about batch management
