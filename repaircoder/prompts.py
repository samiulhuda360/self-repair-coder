"""Prompt templates and the code extractor."""

from __future__ import annotations

import re

from .llm import Message
from .sandbox import SandboxResult

SYSTEM = (
    "You are a careful Python engineer. Write one self-contained Python 3.11 module that uses only the standard "
    "library. Reply with a single ```python code block and nothing else. Do not include tests, example usage, "
    "print statements or input() calls."
)

TEST_HELPER_NOTE = "`raises(Error, fn, *args)` is a test helper that returns True when the call raises Error."

_FENCE = re.compile(r"```(?:python|py|python3)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str, entry_point: str | None = None) -> str:
    """Pull the Python source out of a model reply. Prefers the fenced block that defines the entry point."""
    blocks: list[str] = [str(b).strip("\n") for b in _FENCE.findall(text)]
    if not blocks:
        stripped = text.strip()
        if stripped.startswith("```"):  # an unterminated fence
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        return stripped + "\n"
    if entry_point:
        pattern = re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(entry_point)}\b", re.MULTILINE)
        for block in blocks:
            if pattern.search(block):
                return block + "\n"
    return max(blocks, key=len) + "\n"


def _bullets(tests: list[str]) -> str:
    return "\n".join(tests)


def generate_messages(prompt: str, entry_point: str, tests: list[str]) -> list[Message]:
    user = f"Task:\n{prompt}\n\nImplement `{entry_point}`. These tests must pass ({TEST_HELPER_NOTE}):\n```python\n{_bullets(tests)}\n```"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def failure_report(result: SandboxResult) -> str:
    if result.load_error:
        return f"The module failed to load: {result.load_error}"
    lines = []
    for outcome in result.failures():
        lines.append(f"- FAILED `{outcome.test}`\n  -> {outcome.error}")
    if result.timed_out:
        lines.append("- The run hit the time limit; look for an infinite loop or very slow code.")
    return "\n".join(lines) or "No test failed."


def fix_messages(prompt: str, entry_point: str, tests: list[str], code: str, baseline: SandboxResult) -> list[Message]:
    user = (
        f"This code is meant to do the following:\n{prompt}\n\n"
        f"```python\n{code.rstrip()}\n```\n\n"
        f"When run against the tests below ({TEST_HELPER_NOTE}), {baseline.total - baseline.passed} of "
        f"{baseline.total} failed:\n{failure_report(baseline)}\n\n"
        f"All tests:\n```python\n{_bullets(tests)}\n```\n\n"
        f"Fix the bug in `{entry_point}`. Keep the same function signature. Reply with the complete corrected module."
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def repair_messages(prompt: str, entry_point: str, tests: list[str], code: str, result: SandboxResult) -> list[Message]:
    user = (
        f"Task:\n{prompt}\n\n"
        f"Your previous implementation of `{entry_point}`:\n```python\n{code.rstrip()}\n```\n\n"
        f"It was run in a sandbox against the tests ({TEST_HELPER_NOTE}). {result.passed} of {result.total} passed. "
        f"Failures:\n{failure_report(result)}\n\n"
        f"All tests:\n```python\n{_bullets(tests)}\n```\n\n"
        "Work out the root cause from the failures, then reply with the complete corrected module. Keep the "
        "behaviour that already passes."
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def write_tests_messages(prompt: str, entry_point: str) -> list[Message]:
    user = (
        f"Task:\n{prompt}\n\n"
        f"Write 6 to 8 one-line Python assert statements that check `{entry_point}` against this task, including "
        f"edge cases. {TEST_HELPER_NOTE} Use it for expected exceptions. Only use behaviour the task states. "
        "Reply with one ```python block holding only the assert lines, one per line, no imports and no other code."
    )
    return [
        {"role": "system", "content": "You write precise unit tests. Reply with a single ```python code block."},
        {"role": "user", "content": user},
    ]


def parse_tests(text: str) -> list[str]:
    code = extract_code(text)
    return [line.strip() for line in code.splitlines() if line.strip().startswith("assert ")]
