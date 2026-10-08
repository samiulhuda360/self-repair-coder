from pathlib import Path

import pytest
from conftest import ScriptedLLM, fenced

from repaircoder import __main__ as cli


def test_recorded_demo_replays_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "Attempt 1" in out and "Solved in" in out and "(recorded)" in out


def test_solve_and_fix_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "make_llm", lambda _settings: ScriptedLLM(fenced("def inc(x):\n    return x + 1\n")))
    out_file = tmp_path / "inc.py"
    assert cli.main(["solve", "Return x + 1.", "--entry", "inc", "--test", "assert inc(1) == 2", "--out", str(out_file)]) == 0
    assert "return x + 1" in out_file.read_text(encoding="utf-8")

    broken = tmp_path / "broken.py"
    broken.write_text("def inc(x):\n    return x\n", encoding="utf-8")
    assert cli.main(["fix", str(broken), "--entry", "inc", "--prompt", "Return x + 1.", "--test", "assert inc(1) == 2", "--write"]) == 0
    assert "Your code: 0/1 tests pass" in capsys.readouterr().out
    assert "return x + 1" in broken.read_text(encoding="utf-8")


def test_fix_without_tests_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "b.py"
    broken.write_text("x = 1\n", encoding="utf-8")
    assert cli.main(["fix", str(broken), "--entry", "f", "--prompt", "p"]) == 2
