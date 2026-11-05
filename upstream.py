"""Locate and load the EXISTING Indeed project's modules.

WHY THIS FILE EXISTS
--------------------
The brief is explicit:

    "Use the existing target_audience_roles.py.  Do not create another
     job-role dictionary."
    "Use `from new_mylib import city_by_states`."
    "Do not change the existing 32-column Excel contract."

The safest way to honour all three is to have exactly ONE copy of each of
those things, owned by the original project, and to IMPORT it here rather
than to duplicate it.  A duplicated role list or a duplicated 32-column
schema drifts the moment somebody edits one of the two copies; an import
cannot drift.

Nothing here writes to the original project.  It is read-only: the modules
are loaded from disk and used in this process.

WHERE THE ORIGINAL PROJECT IS
-----------------------------
Resolution order, first hit wins:

    1. the INDEED_UPSTREAM_DIR environment variable
    2. "upstream_dir" in config/settings.json
    3. the built-in default, DEFAULT_UPSTREAM_DIR below

If none of them points at a real Indeed project, every loader in this module
raises UpstreamNotFound with the paths it tried.  It never falls back to a
private copy, because a silent fallback is exactly how two role lists start
to disagree.

THE gtts PROBLEM
----------------
``new_mylib.py`` ends with a module-level ``from gtts import gTTS`` for a
text-to-speech helper this project never calls.  Rather than force a
needless dependency (restriction 8: "Do not introduce unnecessary
dependencies"), a harmless stand-in is installed in ``sys.modules`` for the
duration of the import when the real package is absent.  The same is done
for ``psutil`` and ``Levenshtein``.  If the real packages ARE installed they
are used untouched and no stand-in is created.
"""

import importlib.util
import json
import os
import sys
import types

DEFAULT_UPSTREAM_DIR = "/home/ubuntu/check_indeed"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_FILE = os.path.join(BASE_DIR, "config", "settings.json")

# Loaded upstream modules, keyed by module name, so the work is done once.
_CACHE = {}


class UpstreamNotFound(RuntimeError):
    """The original Indeed project could not be located or loaded."""


def _settings():
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def candidate_dirs():
    """Every directory that will be tried, in order."""
    found = []
    for value in (os.environ.get("INDEED_UPSTREAM_DIR", ""),
                  _settings().get("upstream_dir", ""),
                  DEFAULT_UPSTREAM_DIR):
        value = str(value or "").strip()
        if value and value not in found:
            found.append(os.path.abspath(os.path.expanduser(value)))
    return found


def _looks_like_indeed_project(path):
    return (os.path.isfile(os.path.join(path, "target_audience_roles.py"))
            and os.path.isfile(os.path.join(path, "new_mylib.py"))
            and os.path.isfile(os.path.join(path, "source_file",
                                            "indeed_extractor.py")))


def upstream_dir():
    """The original project's root directory.  Raises when there is none."""
    tried = candidate_dirs()
    for path in tried:
        if _looks_like_indeed_project(path):
            return path
    raise UpstreamNotFound(
        "The original Indeed project was not found.  Tried:\n  %s\n"
        "Set INDEED_UPSTREAM_DIR, or put \"upstream_dir\" in %s.  The "
        "directory must contain target_audience_roles.py, new_mylib.py and "
        "source_file/indeed_extractor.py."
        % ("\n  ".join(tried) or "(nothing configured)", _SETTINGS_FILE))


# ---------------------------------------------------------------------------
# OPTIONAL-DEPENDENCY STAND-INS
# ---------------------------------------------------------------------------

def _stub_module(name, attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    module.__doc__ = (
        "Stand-in installed by new_indeed_script/upstream.py because the real "
        "%r is not installed and this project never calls it.  Install the "
        "real package to replace this." % name)
    return module


def _unavailable(name):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(
            "%s is not installed.  new_indeed_script never calls it; it is "
            "only imported because new_mylib.py imports it at module level."
            % name)
    return _raise


class _StubbedImports(object):
    """Install stand-ins for absent optional packages, then remove them."""

    def __init__(self):
        self.installed = []

    def __enter__(self):
        wanted = {
            "gtts": {"gTTS": _unavailable("gtts")},
            "psutil": {"sensors_battery": _unavailable("psutil"),
                       "process_iter": _unavailable("psutil")},
            "Levenshtein": {"distance": _unavailable("Levenshtein"),
                            "ratio": _unavailable("Levenshtein")},
        }
        for name, attributes in wanted.items():
            if name in sys.modules:
                continue
            if importlib.util.find_spec(name) is not None:
                continue
            sys.modules[name] = _stub_module(name, attributes)
            self.installed.append(name)
        return self

    def __exit__(self, *_exc):
        # Leave the stand-ins in place: new_mylib keeps a reference to the
        # name at module level, so removing them now would not help, and a
        # later real import would still find the real package first.
        return False


def stubbed_packages():
    """Names a stand-in was installed for, for the startup banner."""
    return [name for name in ("gtts", "psutil", "Levenshtein")
            if getattr(sys.modules.get(name), "__doc__", "")
            and "Stand-in installed by" in (sys.modules[name].__doc__ or "")]


# ---------------------------------------------------------------------------
# LOADING
# ---------------------------------------------------------------------------

def _load_file(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise UpstreamNotFound("cannot build an import spec for %s"
                               % file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_module(name):
    """Load one top-level upstream module (``target_audience_roles`` etc.).

    It is registered under its PLAIN name so that `from target_audience_roles
    import build_role_plan` inside this project resolves to the upstream
    file, exactly as the brief asks.
    """
    if name in _CACHE:
        return _CACHE[name]

    root = upstream_dir()
    path = os.path.join(root, "%s.py" % name)
    if not os.path.isfile(path):
        raise UpstreamNotFound("%s does not exist" % path)

    # new_mylib.py reads data files relative to the ORIGINAL project, so the
    # original root goes on sys.path while it loads.
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        with _StubbedImports():
            module = _load_file("upstream_%s" % name, path)
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass

    _CACHE[name] = module
    return module


# ---------------------------------------------------------------------------
# VENDORED AUTHORITATIVE FILES
# ---------------------------------------------------------------------------
# The change request supplied two files and named them THE authoritative
# sources: target_audience_roles.py (the complete keyword plan, Track A +
# Track B) and new_mylib.py (the active 110-city dictionary).
#
# They are COPIED into vendor/ rather than imported from wherever they were
# delivered, for two reasons that are not style preferences:
#
#   1. target_audience_roles.py's own MAINTENANCE section says every script
#      folder is self-contained ON PURPOSE and must never import across
#      folders -- the file exists as byte-identical copies by design.
#   2. The delivered copy sat in an unzipped folder under ~/Desktop. A
#      project whose role plan disappears when a Desktop folder is tidied up
#      is not a project, so the bytes live here and their md5 is recorded in
#      vendor/PROVENANCE.json.
#
# NOTE ON new_mylib.py: at the time of vendoring, the delivered file was
# byte-identical (md5 5e06a7d1edef...) to the one in the original project,
# so no city has changed. The copy records that fact rather than relying on
# it staying true.
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")


def load_vendored(name):
    """Load one vendored authoritative module by its plain name.

    Registered under its PLAIN name so ``from target_audience_roles import
    build_role_plan`` resolves here. The optional-dependency stand-ins are
    installed first, because new_mylib.py imports gtts at module level.
    """
    cache_key = "vendor:%s" % name
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    path = os.path.join(VENDOR_DIR, "%s.py" % name)
    if not os.path.isfile(path):
        raise UpstreamNotFound(
            "vendored %s.py is missing from %s. Restore it from the "
            "authoritative copy named in vendor/PROVENANCE.json."
            % (name, VENDOR_DIR))

    inserted = VENDOR_DIR not in sys.path
    if inserted:
        sys.path.insert(0, VENDOR_DIR)
    try:
        with _StubbedImports():
            module = _load_file("vendored_%s" % name, path)
    finally:
        if inserted:
            try:
                sys.path.remove(VENDOR_DIR)
            except ValueError:
                pass

    _CACHE[cache_key] = module
    return module


def vendor_provenance():
    """vendor/PROVENANCE.json as a dict, or {} when it cannot be read."""
    try:
        with open(os.path.join(VENDOR_DIR, "PROVENANCE.json"),
                  "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


_UPSTREAM_PACKAGE = "upstream_indeed_source"


def load_source_module(name):
    """Load one module out of the original ``source_file/`` package.

    The package is registered under a DISTINCT name so that it cannot
    collide with this project's own ``source_file`` package, while its
    internal relative imports (``from .indeed_apply_url import ...``) still
    resolve.
    """
    full_name = "%s.%s" % (_UPSTREAM_PACKAGE, name)
    if full_name in sys.modules:
        return sys.modules[full_name]

    root = upstream_dir()
    package_dir = os.path.join(root, "source_file")

    if _UPSTREAM_PACKAGE not in sys.modules:
        package = types.ModuleType(_UPSTREAM_PACKAGE)
        package.__path__ = [package_dir]
        package.__doc__ = ("The ORIGINAL project's source_file package, "
                           "loaded read-only from %s" % package_dir)
        sys.modules[_UPSTREAM_PACKAGE] = package

    # indeed_extractor does `from .indeed_apply_url import extract_apply_url`,
    # so the dependency is loaded first and registered under the package.
    for dependency in ("indeed_apply_url",):
        if dependency == name:
            continue
        dep_full = "%s.%s" % (_UPSTREAM_PACKAGE, dependency)
        if dep_full not in sys.modules:
            _load_file(dep_full, os.path.join(package_dir,
                                              "%s.py" % dependency))
            setattr(sys.modules[_UPSTREAM_PACKAGE], dependency,
                    sys.modules[dep_full])

    module = _load_file(full_name, os.path.join(package_dir, "%s.py" % name))
    setattr(sys.modules[_UPSTREAM_PACKAGE], name, module)
    return module


def describe():
    """A one-line summary for the startup banner."""
    try:
        root = upstream_dir()
    except UpstreamNotFound:
        return "upstream: NOT FOUND"
    stubs = stubbed_packages()
    return "upstream: %s%s" % (
        root, "  (stand-ins: %s)" % ", ".join(stubs) if stubs else "")
