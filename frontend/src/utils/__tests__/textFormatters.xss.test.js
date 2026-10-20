// Chat answers are rendered as HTML and quote text from monitored logs,
// which an attacker can influence. No payload position may come out
// executable (2026-10-20 security review; see FE-P0-01 in textFormatters).
import { describe, it, expect } from 'vitest';
import { renderFormattedText } from '../textFormatters';

const P = '<img src=x onerror=alert(1)>';
const S = '<script>alert(1)</script>';
const cases = {
  plain: `Root cause: ${P}`,
  bold: `**${P}**`,
  inline: `\`${P}\``,
  fence: '```\n' + P + '\n```',
  fence_script: '```js\n' + S + '\n```',
  traceback: '```\nTraceback (most recent call last):\n  File "app.py", line 1, in <module>\n    ' + P + '\nValueError: ' + S + '\n```',
  java_trace: '```\nException in thread "main" java.lang.NullPointerException: ' + P + '\n\tat com.x.Main.main(Main.java:5)\n```',
  lang_name: '```' + '"><img src=x onerror=alert(1)>' + '\ncode\n```',
  section: `**Root Cause:** ${P}`,
};

describe('renderFormattedText never emits executable HTML', () => {
  for (const [name, input] of Object.entries(cases)) {
    it(name, () => {
      const html = renderFormattedText(input);
      const div = document.createElement('div');
      div.innerHTML = html;
      const bad = [...div.querySelectorAll('img,script,iframe,svg,[onerror],[onload]')].map((e) => e.outerHTML);
      expect(bad).toEqual([]);
    });
  }
});
