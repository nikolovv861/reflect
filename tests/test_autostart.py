"""Only the part that does not touch the registry. Mocking winreg would test
the mock, so enable/disable are verified by hand.
"""
from __future__ import annotations

import sys

from journal.autostart import command


def test_the_command_runs_this_interpreter():
    assert sys.executable in command()


def test_the_command_launches_the_panel_module():
    assert "journal.panel" in command()


def test_the_command_is_quoted_against_spaces_in_the_path():
    assert command().startswith('"')
