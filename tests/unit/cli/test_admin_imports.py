"""Import-safety tests for ``kt admin`` optional dependencies."""

import subprocess
import sys


def test_cli_import_does_not_require_qr_dependency():
    script = """
import builtins

real_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    if name == "segno":
        raise ModuleNotFoundError("No module named 'segno'")
    return real_import(name, *args, **kwargs)


builtins.__import__ = guarded_import
import kohakuterrarium.cli  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
