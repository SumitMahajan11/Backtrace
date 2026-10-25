"""Thin frontend switch dynamically delegating to app.frontend1 or app.frontend2."""

import importlib
import os
import sys
from typing import Any, List


def active_frontend() -> str:
    """Return the active frontend version ('1' or '2')."""
    version = os.getenv("FRONTEND_VERSION", "1").strip()
    return "2" if version == "2" else "1"


def __getattr__(name: str) -> Any:
    if name == "components":
        return importlib.import_module("app.ui.components")
    if name == "sanitizer":
        return importlib.import_module("app.ui.sanitizer")

    version = active_frontend()
    if version == "2":
        try:
            fe2 = importlib.import_module("app.frontend2")
            if hasattr(fe2, name):
                return getattr(fe2, name)
        except (ImportError, ModuleNotFoundError):
            pass

    try:
        fe1 = importlib.import_module("app.frontend1")
        if hasattr(fe1, name):
            return getattr(fe1, name)
    except (ImportError, ModuleNotFoundError):
        pass

    raise AttributeError(f"module 'app.ui' has no attribute '{name}'")


def __dir__() -> List[str]:
    names = set(globals().keys())
    version = active_frontend()
    if version == "2":
        try:
            fe2 = importlib.import_module("app.frontend2")
            names.update(dir(fe2))
        except (ImportError, ModuleNotFoundError):
            pass

    try:
        fe1 = importlib.import_module("app.frontend1")
        names.update(dir(fe1))
    except (ImportError, ModuleNotFoundError):
        pass

    names.update(["components", "sanitizer"])
    return sorted(names)
