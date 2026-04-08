"""Application base directory: next to the PyInstaller exe, or the dev tree root."""

from __future__ import annotations

import os
import sys


def application_base_dir() -> str:
    """Directory used as the app 'home' for logs and file dialogs.

    * **Frozen (PyInstaller):** folder containing the ``.exe``.
    * **From source:** parent of the ``bmw_enet_tool`` package (typically the
      ``src`` directory in this repository).
    """
    if getattr(sys, "frozen", False):
        return os.path.normpath(os.path.dirname(os.path.abspath(sys.executable)))
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.dirname(pkg_dir))
