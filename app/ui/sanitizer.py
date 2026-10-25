"""Shim module re-exporting sanitizer functionality from the active frontend."""

import importlib
import sys
import types
from typing import Any, List

from app.ui import active_frontend


class _SanitizerShim(types.ModuleType):
    """Dynamically proxies attributes to app.frontend2.sanitizer or falls back to app.frontend1.sanitizer."""

    def __init__(self, name: str):
        super().__init__(name)
        self._orig = {}

    def __getattr__(self, name: str) -> Any:
        version = active_frontend()
        if version == "2":
            try:
                mod2 = importlib.import_module("app.frontend2.sanitizer")
                if hasattr(mod2, name):
                    return getattr(mod2, name)
            except (ImportError, ModuleNotFoundError):
                pass

        try:
            mod1 = importlib.import_module("app.frontend1.sanitizer")
            if hasattr(mod1, name):
                return getattr(mod1, name)
        except (ImportError, ModuleNotFoundError):
            pass

        raise AttributeError(f"module 'app.ui.sanitizer' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_orig":
            super().__setattr__(name, value)
            return

        mod1 = sys.modules.get("app.frontend1.sanitizer")
        if mod1 is not None and hasattr(mod1, name):
            if name not in self._orig:
                self._orig[name] = getattr(mod1, name)
            setattr(mod1, name, value)

        mod2 = sys.modules.get("app.frontend2.sanitizer")
        if mod2 is not None and hasattr(mod2, name):
            setattr(mod2, name, value)

        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in self._orig:
            mod1 = sys.modules.get("app.frontend1.sanitizer")
            if mod1 is not None:
                setattr(mod1, name, self._orig.pop(name))

        super().__delattr__(name)

    def __dir__(self) -> List[str]:
        names = set(super().__dir__())
        version = active_frontend()
        if version == "2":
            try:
                mod2 = importlib.import_module("app.frontend2.sanitizer")
                names.update(dir(mod2))
            except (ImportError, ModuleNotFoundError):
                pass
        try:
            mod1 = importlib.import_module("app.frontend1.sanitizer")
            names.update(dir(mod1))
        except (ImportError, ModuleNotFoundError):
            pass
        return sorted(names)


_shim = _SanitizerShim(__name__)
_shim.__file__ = __file__
_shim.__doc__ = __doc__
_shim.__path__ = []
sys.modules[__name__] = _shim
