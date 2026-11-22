import { describe, it, expect } from 'vitest';
import { splitSentences, firstSentence, headline, HEADLINE_MAX, splitSteps } from '../sentences';

describe('splitSentences', () => {
  it('splits plain sentences, also when the next one starts with a service name in lower case', () => {
    expect(splitSentences('pricing returns HTTP 500 to catalog. catalog then returns 503 to web. Checkout fails!'))
      .toEqual(['pricing returns HTTP 500 to catalog.', 'catalog then returns 503 to web.', 'Checkout fails!']);
  });

  it('does not break on decimals', () => {
    expect(splitSentences('Tracking logs slow requests of about 3.9 s against an 800 ms threshold. Memory is at 97.4% of the limit.'))
      .toEqual(['Tracking logs slow requests of about 3.9 s against an 800 ms threshold.', 'Memory is at 97.4% of the limit.']);
  });

  it('does not break on times, with or without fractions of a second', () => {
    expect(splitSentences('Since the pricing rollout at 00:24:45, every /price call fails. The first errors are at 00:24:45.45-.48, and none before. The deploy time (23:59:36.57) is 2s later.'))
      .toEqual([
        'Since the pricing rollout at 00:24:45, every /price call fails.',
        'The first errors are at 00:24:45.45-.48, and none before.',
        'The deploy time (23:59:36.57) is 2s later.',
      ]);
    expect(firstSentence('It restarted at 23:59:35. The cap fills at once.')).toBe('It restarted at 23:59:35.');
  });

  it('does not break on versions, file names and addresses', () => {
    expect(splitSentences('The image is unchanged (v0.10.7) on SerOps 1.5.0. See app.py line 78 and fleet/fleet-redis.yaml. Nothing listens on checkoutservice:5050 at 10.0.3.17.'))
      .toEqual([
        'The image is unchanged (v0.10.7) on SerOps 1.5.0.',
        'See app.py line 78 and fleet/fleet-redis.yaml.',
        'Nothing listens on checkoutservice:5050 at 10.0.3.17.',
      ]);
  });

  it('keeps quoted error text whole: single quotes, double quotes, backticks and JSON', () => {
    expect(splitSentences("payments rejects charges with 'IdempotencyConflict: key ... already used. Retry with a new key' on both hosts. web gets HTTP 409."))
      .toEqual(["payments rejects charges with 'IdempotencyConflict: key ... already used. Retry with a new key' on both hosts.", 'web gets HTTP 409.']);
    expect(splitSentences('frontend logged 162 errors ("shipping quote failure ... connection refused. Giving up") on port 50051. The path is unavailable.'))
      .toEqual(['frontend logged 162 errors ("shipping quote failure ... connection refused. Giving up") on port 50051.', 'The path is unavailable.']);
    expect(splitSentences('Run `kubectl logs --previous. -n shop` on the pod. Then re-apply the change.'))
      .toEqual(['Run `kubectl logs --previous. -n shop` on the pod.', 'Then re-apply the change.']);
    expect(splitSentences('catalog returns 503 {"error":"pricing unavailable. Try later"} to web, so GET / fails. Traces show 1293 error spans.'))
      .toEqual(['catalog returns 503 {"error":"pricing unavailable. Try later"} to web, so GET / fails.', 'Traces show 1293 error spans.']);
  });

  it("takes an apostrophe for what it is: pricing's, can't, hosts'", () => {
    expect(splitSentences("pricing's own lines are logged on node-1. catalog's lookups can't succeed. Both hosts' logs agree."))
      .toEqual(["pricing's own lines are logged on node-1.", "catalog's lookups can't succeed.", "Both hosts' logs agree."]);
  });

  it('keeps going when a quote or a bracket never closes', () => {
    expect(splitSentences("It logged 'starting at 00:24:41. The rollout is listed later."))
      .toEqual(["It logged 'starting at 00:24:41.", 'The rollout is listed later.']);
    expect(splitSentences('The limit (128Mi was cut. The pod is killed.')).toEqual(['The limit (128Mi was cut.', 'The pod is killed.']);
  });

  it('does not break after an abbreviation or at an ellipsis the sentence continues after', () => {
    expect(splitSentences('orders-api fails to create shipments (192 errors, e.g. SHP-EDE580866C). Tracking fails too.'))
      .toEqual(['orders-api fails to create shipments (192 errors, e.g. SHP-EDE580866C).', 'Tracking fails too.']);
    expect(splitSentences('Use a replica, i.e. a read-only copy, vs. the primary. Done.'))
      .toEqual(['Use a replica, i.e. a read-only copy, vs. the primary.', 'Done.']);
    expect(splitSentences('The pod waits... then it is killed. It restarts.')).toEqual(['The pod waits... then it is killed.', 'It restarts.']);
  });

  it('handles empty and odd input', () => {
    expect(splitSentences('')).toEqual([]);
    expect(splitSentences(null)).toEqual([]);
    expect(splitSentences('  No full stop here  ')).toEqual(['No full stop here']);
    expect(firstSentence(undefined)).toBe('');
    expect(splitSentences('Line one.\nLine two.')).toEqual(['Line one.', 'Line two.']);
  });
});

describe('splitSteps', () => {
  it('turns sentences into steps', () => {
    expect(splitSteps("Roll back pricing to the version before the 00:24:45 rollout (the pre-c9cabe46 build) to restore /price. Then inspect pricing's rounding logic (app.py around line 78). Add a test for SKU-1001. Consider cached prices."))
      .toEqual([
        'Roll back pricing to the version before the 00:24:45 rollout (the pre-c9cabe46 build) to restore /price.',
        "Then inspect pricing's rounding logic (app.py around line 78).",
        'Add a test for SKU-1001.',
        'Consider cached prices.',
      ]);
  });

  it('uses a list the text already holds and drops its marks', () => {
    expect(splitSteps('1. Restore the limit. It was 128Mi.\n2. Confirm the pod is Ready.\n- Add a guard.'))
      .toEqual(['Restore the limit. It was 128Mi.', 'Confirm the pod is Ready.', 'Add a guard.']);
    expect(splitSteps('1. Restore the limit to 128Mi. 2. Confirm the pod is Ready.')).toEqual(['Restore the limit to 128Mi.', 'Confirm the pod is Ready.']);
  });

  it('returns nothing for an empty text', () => {
    expect(splitSteps('')).toEqual([]);
    expect(splitSteps(null)).toEqual([]);
  });
});

describe('headline', () => {
  const long = "Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation ('quantize result has too many digits for current context') in the rounding step. Catalog then returns 503.";

  it('is the whole first sentence when it fits', () => {
    expect(headline('Frontend is CPU-throttled 97% of the time after its CPU limit was halved. It restarted at 23:59:35.'))
      .toBe('Frontend is CPU-throttled 97% of the time after its CPU limit was halved.');
    expect(headline('')).toBe('');
    expect(headline(null)).toBe('');
  });

  it('cuts a long first sentence at a word boundary, within the limit, with an ellipsis', () => {
    const out = headline(long);
    expect(out.endsWith('…')).toBe(true);
    expect(out.length).toBeLessThanOrEqual(HEADLINE_MAX + 1);
    const kept = out.slice(0, -1);
    expect(long.startsWith(kept)).toBe(true);
    expect(long[kept.length]).toMatch(/[\s,;:.('"-]/);          // the next character is not part of a word
    expect(out).not.toContain('Catalog');
  });

  it('never cuts inside a word, a time or a number', () => {
    expect(headline('The first errors are at 00:24:45.45 and none before that time at all.', 30)).toBe('The first errors are at…');
    expect(headline('Memory is at 97.4% of the limit on every node.', 16)).toBe('Memory is at…');
  });

  it('does not cut inside quoted error text: it stops before the quote or bracket opens', () => {
    expect(headline(long)).toBe('Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation…');
    expect(headline('payments rejects charges with "IdempotencyConflict: key already used with a different payload" since 01:20.', 60))
      .toBe('payments rejects charges with…');
    expect(headline('The pod fails (see `kubectl logs notifier` for it) and then restarts again and again.', 60))
      .toBe('The pod fails (see `kubectl logs notifier` for it) and then…');
  });

  it('drops punctuation and an opening quote left hanging at the cut', () => {
    expect(headline("pricing fails, ('quantize result has too many digits') in rounding.", 17)).toBe('pricing fails…');
  });

  it('leaves one unbroken word alone', () => {
    expect(headline('a'.repeat(40), 10)).toBe('a'.repeat(40));
  });
});
