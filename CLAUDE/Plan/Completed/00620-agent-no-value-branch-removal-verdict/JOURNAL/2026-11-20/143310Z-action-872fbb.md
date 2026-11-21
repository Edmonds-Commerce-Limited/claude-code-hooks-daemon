## 14:33 · action · —

Correctness review finding (4) fixed: the verdict recorder could block a stop. In read_review_transcript, a first human-turn user record with no `message` raised KeyError, and one with a non-dict `message` raised AttributeError. The SubagentStop handler caught only OSError/RuntimeError/ValueError, so strict mode turned the crash into a deny, and every later stop crashed the same way.

Fix: content is read only through the same dict check \_is_human_turn makes. The handler also catches LookupError, AttributeError and TypeError, records nothing, and allows. Tests written red first: two transcript-shape tests in test_branch_reject_recorder.py, plus a parametrised handler test (KeyError, AttributeError, IndexError).
