/**
 * PR-UI2 · console hygiene helpers for vitest.
 *
 * Catches React warnings that would otherwise flow to the browser
 * console silently. In a real user's browser these fire on every
 * page load — reading them is the operator's job. In a unit test we
 * can catch them at build time.
 *
 * Typical usage inside a test file:
 *
 *   import { armConsoleHygiene } from '../../test/console-hygiene';
 *
 *   describe('MyComponent', () => {
 *     armConsoleHygiene();   // spies + auto-asserts after each test
 *
 *     it('renders', () => { render(<MyComponent />); });
 *   });
 *
 * Or more surgically per-test with the returned handle:
 *
 *   it('renders', () => {
 *     const hyg = armConsoleHygieneOnce();
 *     render(<MyComponent />);
 *     hyg.assertClean();
 *   });
 */

import { afterEach, beforeEach, expect, vi } from 'vitest';

/**
 * Patterns that are noisy-but-harmless in test-time renders and
 * would drown out real regressions. Kept as REGEXPS so ``.test`` is
 * O(1) at run time.
 *
 * Add sparingly — every entry here is a class of warning we've
 * DELIBERATELY chosen to ignore. When a new pattern shows up in
 * real code, prefer fixing the code over adding the pattern here.
 */
const KNOWN_TEST_TIME_NOISE = [
  // React Router in jsdom: v7 flag warnings printed on every render
  /React Router Future Flag Warning/,
  // React Testing Library: expected during act() batching in some flows
  /Warning: An update to .* inside a test was not wrapped in act/,
];


function _isNoise(argString) {
  return KNOWN_TEST_TIME_NOISE.some((re) => re.test(argString));
}


function _serialiseArgs(args) {
  // console.error is variadic; the first arg is usually the format
  // string and subsequent args are formatArgs. We concat them lossily
  // for noise-matching + failure reporting; a real assertion also
  // reports the FULL args array.
  return args.map((a) => {
    if (a === null || a === undefined) return String(a);
    if (a instanceof Error) return `${a.name}: ${a.message}`;
    if (typeof a === 'object') {
      try { return JSON.stringify(a); } catch { return String(a); }
    }
    return String(a);
  }).join(' ');
}


export function armConsoleHygiene() {
  let errors, warns, errSpy, warnSpy;

  beforeEach(() => {
    errors = [];
    warns = [];
    errSpy = vi.spyOn(console, 'error').mockImplementation((...args) => {
      const line = _serialiseArgs(args);
      if (!_isNoise(line)) errors.push(line);
    });
    warnSpy = vi.spyOn(console, 'warn').mockImplementation((...args) => {
      const line = _serialiseArgs(args);
      if (!_isNoise(line)) warns.push(line);
    });
  });

  afterEach(() => {
    try {
      expect(errors, `console.error was called during test:\n${errors.join('\n---\n')}`).toEqual([]);
      expect(warns, `console.warn was called during test:\n${warns.join('\n---\n')}`).toEqual([]);
    } finally {
      errSpy?.mockRestore();
      warnSpy?.mockRestore();
    }
  });
}


/**
 * Same idea but as an imperative single-shot for a test that
 * DELIBERATELY expects some warnings (e.g. a component that fires
 * a PropType warning by design). Call ``arm()`` first, exercise the
 * component, then ``assertClean()``.
 */
export function armConsoleHygieneOnce() {
  const errors = [];
  const warns = [];
  const errSpy = vi.spyOn(console, 'error').mockImplementation((...args) => {
    const line = _serialiseArgs(args);
    if (!_isNoise(line)) errors.push(line);
  });
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation((...args) => {
    const line = _serialiseArgs(args);
    if (!_isNoise(line)) warns.push(line);
  });
  return {
    errors,
    warns,
    assertClean() {
      try {
        expect(errors, `console.error:\n${errors.join('\n---\n')}`).toEqual([]);
        expect(warns, `console.warn:\n${warns.join('\n---\n')}`).toEqual([]);
      } finally {
        errSpy.mockRestore();
        warnSpy.mockRestore();
      }
    },
    restore() {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    },
  };
}
