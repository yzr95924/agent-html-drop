"""agent-html-drop CLI test runner — like model_switch's _cli_runner.py.

Captures stdin/stdout/stderr and returns a SimpleNamespace. The
``autouse`` conftest fixture redirects paths so tests never touch real
user configs.
"""
import io
import sys
from types import SimpleNamespace


def invoke(args, input=None):
    from agent_html_drop.cli import main as cli_main

    saved_stdin, saved_stdout, saved_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO(input if input is not None else "")
    sys.stdin.isatty = lambda: input is not None  # type: ignore[attr-defined]
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    rc = 1
    try:
        try:
            rc = cli_main(args)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    finally:
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
        sys.stdin, sys.stdout, sys.stderr = saved_stdin, saved_stdout, saved_stderr
    return SimpleNamespace(exit_code=rc, stdout=out, stderr=err)