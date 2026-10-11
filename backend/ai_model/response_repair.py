"""Recover usable JSON from an AI response that did not finish cleanly.

Two situations produce almost-JSON, and they need different handling:

* **Formatting slips** — a trailing comma, Python dict syntax with single
  quotes. The body is complete; it just does not parse.
* **Truncation** — the model hit its output token limit and stopped
  mid-structure, often mid-string. The body is genuinely incomplete, and the
  last element in it is garbage.

The second case used to cost a whole analysis. The response was discarded
entirely — zero issues, empty narrative, tokens already billed — even though
the model writes its conclusion first and only runs out of room part-way down
the issue list. Almost all of that answer was correct and recoverable.

The balancing that lived inline in ``analyze_batch`` could not recover it. It
counted braces and brackets separately and appended ``}`` before ``]``, so the
common shape ``{"correlated_issues": [ ... `` was closed as ``...}]`` — which
is not valid JSON in any arrangement. Closers have to come out in the reverse
order their openers went in, which means tracking a stack, and the scan has to
know when it is inside a string literal so that a brace in a log message is
not mistaken for structure.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# How many trailing elements to drop while hunting for a parsable prefix.
# Truncation strands one incomplete element; a handful of attempts covers
# nested cases without turning a malformed body into a long loop.
_MAX_TRIM_ATTEMPTS = 60

_PAIRS = {'{': '}', '[': ']'}


def _scan(text):
    """Return (stack_of_open_closers, ends_inside_string, comma_positions).

    ``comma_positions`` lists only commas that sit outside string literals —
    the boundaries where a trailing element can safely be cut off.
    """
    stack = []
    commas = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _PAIRS:
            stack.append(_PAIRS[ch])
        elif ch in ('}', ']'):
            if stack and stack[-1] == ch:
                stack.pop()
        elif ch == ',':
            commas.append(i)
    return stack, in_string, commas


def balance_json(text):
    """Close whatever the model left open, innermost first.

    An unterminated string is closed before any structure, otherwise the
    appended closers land inside the string and change nothing.
    """
    stack, in_string, _ = _scan(text)
    if in_string:
        text += '"'
    return text + ''.join(reversed(stack))


def repair_json(text):
    """Best-effort parse of an AI response. Returns a dict/list, or None.

    Tries, in order: the text as given; obvious formatting fixes; then closing
    whatever the model left open; then, only if that still will not parse,
    dropping the incomplete trailing element and re-closing — repeatedly, since
    the strand can be nested a couple of levels deep.

    A truncated body needs no special flag here, but it does leave the caller
    something to handle: the trailing element can balance into a HOLLOW object.
    A body cut at ``{"issue_type": "LATEN`` closes to ``{"issue_type": "LATEN"}``
    — valid JSON, and a phantom issue with no component and no evidence behind
    it. Recognising that needs the schema, so it belongs to the caller (see
    ``_drop_hollow_issues`` in ``ai_model.tasks``).
    """
    if not text or not text.strip():
        return None
    text = text.strip()

    # Strip Markdown fences, including an unclosed opening fence — truncation
    # means the closing ``` never arrived.
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    # Ignore any preamble before the first structural character. Models
    # occasionally narrate ("Here is the analysis:") despite instructions.
    first = min((p for p in (text.find('{'), text.find('[')) if p != -1),
                default=-1)
    if first > 0:
        text = text[first:]

    # A body that parses as given is complete, whatever the provider reported
    # about its stop reason — there is nothing to drop.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Formatting slips: trailing commas, and pure-Python dict syntax.
    candidate = re.sub(r',(\s*[}\]])', r'\1', text)
    if candidate.startswith('{') and "'" in candidate and '"' not in candidate[:100]:
        candidate = candidate.replace("'", '"')

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Close what is open. Balancing comes FIRST and trimming only on failure:
    # an element the model finished writing must survive, so nothing is dropped
    # while the body is still parseable. If the strand at the end cannot be
    # closed into valid JSON, cut back to the previous element boundary and try
    # again.
    working = candidate
    for _ in range(_MAX_TRIM_ATTEMPTS):
        try:
            return json.loads(balance_json(working))
        except json.JSONDecodeError:
            pass
        _, _, commas = _scan(working)
        if not commas:
            break
        working = working[:commas[-1]]

    logger.warning('repair_json exhausted all strategies on a %s-char body',
                   len(text))
    return None
