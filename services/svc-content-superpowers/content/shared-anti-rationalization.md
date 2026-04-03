# Anti-Rationalization — Cross-Phase Reminders

## Spirit vs Letter

Violating the letter of a process rule IS violating the spirit.

Common rationalizations to reject:

- "I'll just quickly add this one thing first, then write the test" — No. Write the test first.
- "The spec didn't explicitly say I can't do this" — If it wasn't specified, don't add it.
- "I already know it works, the test is just a formality" — Then write the test and prove it.
- "This is just a minor cleanup, it doesn't count as a feature" — Scope creep starts with minor things.
- "I'll refactor while I'm in here" — Refactor is its own step; don't mix it with GREEN.
- "The test would be too hard to write for this" — That's a design smell; address the design.

## YAGNI — Ruthless Scope Control

You Aren't Gonna Need It.

- Do not add while-I'm-here improvements — if the task doesn't require it, don't touch it.
- Do not implement hypothetical requirements — build only what is specified now.
- Do not introduce unnecessary abstractions — solve the actual problem with the simplest code.
- Do not apply premature optimization — make it work correctly first; optimize only when measured.

## False Completion Prevention

Done means verified, not "I think it works."

Before claiming any task is complete:

1. Run the full test suite and confirm all tests pass — not just the new ones.
2. Verify the specific behavior described in the spec — not just that tests are green.
3. Check for regressions — confirm nothing that was passing before is now failing.

## The Three-Fix Escalation

If you find yourself making a third fix to the same problem, stop.

Three or more fixes to the same area signals an architectural issue, not an implementation detail. At that point:

- Stop writing fixes.
- Question the architecture — something deeper is wrong.
- Discuss with the user before proceeding.

Continuing to apply patches when fixes keep failing is a form of false progress. Escalate instead.
