import os
import sys

from PySide6.QtGui import QIcon


def is_bundled_app() -> bool:
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def get_base_dir() -> str:
    pyinstaller_base_dir = getattr(sys, "_MEIPASS", "")
    if pyinstaller_base_dir:
        return os.path.abspath(pyinstaller_base_dir)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    return os.path.join(get_base_dir(), relative_path)


def get_app_window_icon() -> QIcon:
    return QIcon(get_resource_path(os.path.join("resource", "seaweedfs.png")))


def get_windows_icon_path() -> str:
    ico_path = get_resource_path(os.path.join("resource", "seaweedfs.ico"))
    return ico_path if os.path.exists(ico_path) else ""
