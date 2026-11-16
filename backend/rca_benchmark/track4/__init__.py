"""
Phase 3, track 4: the AI features other than batch RCA.

* ``alerts``      20 alerts in the formats real alerters send, each tied to a
                  benchmark scenario, posted through the real webhook view.
* ``chat``        30 scripted conversations on analysed incidents.
* ``postmortem``  20 post-mortem drafts.
* ``judge``       a blind grader (claude-opus-5-5) for the free text the
                  deterministic checks cannot settle, and a 20 % hand-check export.

Expectations and the judge's rubric are committed before any run, under the
same rules as the held-out sets: never edited after a result is seen.
"""
