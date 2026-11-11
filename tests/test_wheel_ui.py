"""Executable checks for browser wheel geometry and request-key persistence."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_wheel_landing_and_durable_request_keys():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser JavaScript checks")
    test = Path(__file__).with_name("test_wheel_behavior.cjs")
    result = subprocess.run([node, str(test)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "geometric landings" in result.stdout
