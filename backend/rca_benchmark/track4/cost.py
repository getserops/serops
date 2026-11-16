"""
Cost estimate for track 4, from token sizes measured on phase 2 and the
prompt sizes of this harness. Prices in $/MTok (input, output).

Measured 2026-11-15 on claude-sonnet-5-5: one batch analysis ≈ 1.5k input
(+ ~4.5k cached system prompt), 1.9k output ≈ $0.025 with cache tokens.
"""
PRICES = {'claude-sonnet-5-5': (2.0, 10.0), 'claude-opus-5-5': (4.0, 20.0), 'claude-haiku-5-5': (0.10, 0.50)}

# (calls, input tokens per call, output tokens per call, model)
LINES = {
    # 20 alerts, 15 analysed (2 unmatched, 3 refused never reach the AI), 2 rounds
    'alerts: analyses': (15 * 2, 6000, 1900, 'claude-sonnet-5-5'),
    # 10 scenarios analysed once for the chats, 110 turns: one intent call + one answer each
    'chat: scenario analyses': (10, 6000, 1900, 'claude-sonnet-5-5'),
    'chat: intent classification': (110, 900, 60, 'claude-sonnet-5-5'),
    'chat: answers': (110, 7000, 600, 'claude-sonnet-5-5'),
    # 20 scenarios analysed, 20 drafts
    'postmortem: analyses': (20, 6000, 1900, 'claude-sonnet-5-5'),
    'postmortem: drafts': (20, 5000, 1800, 'claude-sonnet-5-5'),
    # judge: chat turns marked judge (5 per scenario = 50) + 20 drafts; output includes medium-effort thinking
    'judge: chat turns': (50, 4500, 1400, 'claude-opus-5-5'),
    'judge: post-mortems': (20, 7000, 1800, 'claude-opus-5-5'),
}


def estimate():
    rows, total = [], 0.0
    for name, (calls, tin, tout, model) in LINES.items():
        pin, pout = PRICES[model]
        usd = calls * (tin * pin + tout * pout) / 1e6
        rows.append((name, calls, model, round(usd, 2)))
        total += usd
    return rows, round(total, 2)


if __name__ == '__main__':
    rows, total = estimate()
    for r in rows:
        print(f'{r[0]:32} {r[1]:4} × {r[2]:18} ${r[3]:.2f}')
    print(f'{"total":32} ${total:.2f}')
