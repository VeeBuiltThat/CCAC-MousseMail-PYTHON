# Re-export all settings from the parent config.py.
# This is required because Python resolves `import config` to this package
# (config/__init__.py) rather than the root config.py module. By loading
# config.py here and merging its namespace, all `import config` calls
# throughout the codebase will find the correct settings.
import importlib.util as _ilu
import os as _os

_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config.py")
_spec = _ilu.spec_from_file_location("config._root", _path)
_module = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_module)

_names = [n for n in dir(_module) if not n.startswith("_")]
globals().update({n: getattr(_module, n) for n in _names})
__all__ = _names
