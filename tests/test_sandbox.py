from repaircoder.sandbox import run_tests


def test_passing_and_failing_tests_report_actual_values() -> None:
    result = run_tests("def add(a, b):\n    return a - b\n", ["assert add(1, 2) == 3", "assert add(0, 0) == 0"])
    assert result.passed == 1 and result.total == 2
    assert not result.all_passed
    assert result.failures()[0].error == "AssertionError: expected 3, got -1"


def test_all_passed() -> None:
    result = run_tests("def double(x):\n    return 2 * x\n", ["assert double(2) == 4", "assert double(-1) == -2"])
    assert result.all_passed


def test_raises_helper() -> None:
    code = "def parse(s):\n    if not s:\n        raise ValueError('empty')\n    return int(s)\n"
    result = run_tests(code, ["assert raises(ValueError, parse, '')", "assert not raises(ValueError, parse, '4')"])
    assert result.all_passed


def test_syntax_error_points_at_the_line() -> None:
    result = run_tests("from __future__ annotations\n", ["assert True"])
    assert result.load_error is not None
    assert "line 1: from __future__ annotations" in result.load_error
    assert not result.all_passed
    assert result.outcomes[0].error is not None and result.outcomes[0].error.startswith("not run")


def test_runtime_error_points_at_the_solution_line() -> None:
    result = run_tests("def first(xs):\n    return xs[3]\n", ["assert first([1]) == 1"])
    error = result.outcomes[0].error or ""
    assert error.startswith("IndexError") and "solution.py line 2: return xs[3]" in error


def test_infinite_loop_is_killed() -> None:
    result = run_tests("def spin():\n    while True:\n        pass\n", ["assert spin() is None"], timeout_s=1.5)
    assert result.timed_out
    assert result.outcomes[0].error == "timed out after 1.5s"
    assert result.duration_s < 10


def test_results_before_a_timeout_are_kept() -> None:
    code = "def f(x):\n    while x:\n        pass\n    return 0\n"
    result = run_tests(code, ["assert f(0) == 0", "assert f(1) == 0"], timeout_s=1.5)
    assert result.outcomes[0].passed
    assert not result.outcomes[1].passed and result.timed_out


def test_network_is_disabled() -> None:
    code = "import socket\ndef fetch():\n    socket.create_connection(('localhost', 9))\n"
    result = run_tests(code, ["fetch()"])
    assert "network access is disabled" in (result.outcomes[0].error or "")


def test_solution_output_does_not_break_the_harness() -> None:
    result = run_tests("print('loading')\ndef f():\n    print('hi')\n    return 1\n", ["assert f() == 1"])
    assert result.all_passed


def test_tests_are_isolated_from_each_other() -> None:
    result = run_tests("items = []\n", ["items_alias = 5", "assert 'items_alias' not in globals()"])
    assert result.all_passed


def test_crashing_process_is_reported() -> None:
    result = run_tests("import os\nos._exit(3)\n", ["assert True"])
    assert not result.all_passed
    assert "harness crashed" in (result.outcomes[0].error or "")


def test_no_tests_is_not_a_pass() -> None:
    assert not run_tests("x = 1\n", []).all_passed
