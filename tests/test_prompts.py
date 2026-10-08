from repaircoder import prompts
from repaircoder.sandbox import SandboxResult, TestOutcome


def test_extract_code_from_fenced_block() -> None:
    assert prompts.extract_code("text\n```python\ndef f():\n    return 1\n```\nmore") == "def f():\n    return 1\n"


def test_extract_code_prefers_block_with_entry_point() -> None:
    reply = "```python\nimport os\n```\n\n```py\ndef target(x):\n    return x\n```"
    assert prompts.extract_code(reply, "target").startswith("def target")


def test_extract_code_without_fence_and_with_unterminated_fence() -> None:
    assert prompts.extract_code("def f():\n    return 2") == "def f():\n    return 2\n"
    assert prompts.extract_code("```python\ndef f():\n    return 3") == "def f():\n    return 3\n"


def test_parse_tests_keeps_only_asserts() -> None:
    reply = "```python\nimport math\nassert f(1) == 2\n  assert f(2) == 3\nprint('x')\n```"
    assert prompts.parse_tests(reply) == ["assert f(1) == 2", "assert f(2) == 3"]


def test_failure_report_lists_each_failure() -> None:
    result = SandboxResult(
        outcomes=[TestOutcome(0, "assert f(1) == 2", False, "AssertionError: expected 2, got 1"), TestOutcome(1, "assert f(0) == 0", True)]
    )
    report = prompts.failure_report(result)
    assert "FAILED `assert f(1) == 2`" in report and "expected 2, got 1" in report
    assert "f(0)" not in report


def test_failure_report_for_load_error_and_timeout() -> None:
    assert "failed to load" in prompts.failure_report(SandboxResult(load_error="SyntaxError: x"))
    assert "time limit" in prompts.failure_report(SandboxResult(outcomes=[TestOutcome(0, "assert f()", False, "timed out")], timed_out=True))


def test_repair_prompt_contains_code_and_failures() -> None:
    result = SandboxResult(outcomes=[TestOutcome(0, "assert f(1) == 2", False, "AssertionError: expected 2, got 1")])
    messages = prompts.repair_messages("Return x + 1.", "f", ["assert f(1) == 2"], "def f(x):\n    return x\n", result)
    user = messages[-1]["content"]
    assert "def f(x)" in user and "expected 2, got 1" in user and "0 of 1 passed" in user
