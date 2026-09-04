"""Start the panel with Windows. Opt-in, never on by default.

Writes one value under the current user's Run key. Nothing is installed
system-wide and nothing needs administrator rights.
"""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "reflect-panel"


def command() -> str:
    """The command Windows runs at login.

    Quoted because `sys.executable` routinely lives under a path with a space
    in it, and an unquoted Run value silently does nothing.
    """
    return f'"{sys.executable}" -m journal.panel'


def _key(access):  # noqa: ANN001
    import winreg

    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def enable() -> None:
    import winreg

    with _key(winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())


def disable() -> None:
    import winreg

    try:
        with _key(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    import winreg

    try:
        with _key(winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True
