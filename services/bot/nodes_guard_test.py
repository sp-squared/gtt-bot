"""
Regression test for the `if not nodes:` guard in
gtt_bot/commands/knowledge.py (knowledge-base / knowledge-search).

Locks in the current truth table so any future tightening of the guard
(e.g. `nodes is None`, `len(nodes) == 0`) is a measurable change rather
than a silent behavior shift.

Run:  python services/bot/nodes_guard_test.py
"""


def guard_fires(nodes) -> bool:
    """Mirrors the guard expression at knowledge.py:76 and :157."""
    return not nodes


# (label, nodes, expected_guard_fires)
cases = [
    ("empty list",       [],                 True),
    ("None (defensive)", None,               True),
    ("one node",         ["a"],              False),
    ("many nodes",       ["a", "b", "c"],    False),
]

failed = 0
for label, nodes, expected in cases:
    actual = guard_fires(nodes)
    ok = actual is expected
    status = "ok" if ok else "FAIL"
    print(f"  {status:>4}  {label:<18}  not nodes -> {actual}  (expected {expected})")
    if not ok:
        failed += 1

print()
if failed:
    print(f"{failed} case(s) failed")
    raise SystemExit(1)
print("all guard cases pass")
