# Investigate

**Investigate** analyses a time window **now**, without waiting for the
next scheduled batch or for an alert. Use it when something looks wrong and
nothing has fired yet: a customer report, a dashboard that looks off, a
check right after a deploy.

It runs the same pipeline as scheduled analysis (logs, metrics, traces,
code changes and CI/CD runs, secrets masked, then your AI model), so the
result is an ordinary batch with issues, a root cause and evidence.

!!! note "Investigate or AI Chat?"
    AI Chat answers questions about analyses that already exist.
    Investigate collects fresh data for a window and analyses it.

## Start an investigation

1. Open **Investigate** in the sidebar.
2. Choose the **project**, and optionally an **environment**, a
   **deployment** and some **services**. No service selected means every
   service of the project.
3. Choose the **time window**: the last 15 minutes, 30 minutes, hour or
   3 hours, **since the last deploy**, or a custom start and end.
4. Optionally describe **what you are seeing**, for example *"checkout is
   slow for customers in Europe since 10:00"*. The AI treats it as a
   symptom to confirm or rule out, not as an instruction.
5. Click **Run investigation**.

The run shows its progress (queued → collecting data → AI analysis → done)
and how much data it found per source. When it finishes, **Open analysis**
goes to the batch.

You can also start one from:

- a **deployment** on the dashboard (**Investigate**): from 5 minutes before
  the deploy to 30 minutes after;
- a **batch** page (**Re-run analysis**): the batch's scope and window, with
  fresh data.

## How it differs from scheduled analysis

| | Scheduled batch | Investigation |
|---|---|---|
| Window | Since the previous batch | The one you choose (5 min to 6 h, within 30 days) |
| Sentinel | Can skip quiet windows | Never skipped, and does not change Sentinel's baseline |
| Logs already analysed | Skipped | Included: you get the whole window |
| On-call notifications | Through routing rules | Only you, in the app, unless you tick **Also notify on-call** |
| Badge on the batch | — | **INVESTIGATION** |

Investigations never hide logs from the scheduler: the next scheduled batch
still sees everything, and still notifies on-call as usual.

## Limits

- Role **User** or **Admin**. Viewers can follow investigations but not
  start them.
- Two investigations running at a time and ten an hour per organisation.
- The monthly AI budget applies (Settings → AI).
- A window with no data ends as **No data**, with the count per source,
  rather than silently.

## Statuses

| Status | Meaning |
|---|---|
| Queued, Collecting data, Analyzing | In progress |
| Done | Analysis finished; open it from the run or the history |
| No data | Nothing was recorded for that scope and window |
| Failed | Collection or analysis failed; the reason is shown (budget used up, AI provider error, timeout) |
