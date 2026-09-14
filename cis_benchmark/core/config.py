import json
import os
from importlib import resources

_DEFAULTS = {
    "gcp_project_id": None,
    "google_workspace_domain": "example.com",
    "max_worker_threads": 10,
    "key_expiration_threshold_days": 90,
    "output_directory": "./output",
}

# A settings.json dropped next to where the tool is run (project-local
# override) always wins if present; otherwise fall back to the defaults
# bundled inside the installed package.
_CWD_OVERRIDE_PATH = os.path.join("config", "settings.json")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_bundled_defaults() -> dict:
    try:
        data = json.loads(resources.files("cis_benchmark.core").joinpath("default_settings.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ModuleNotFoundError):
        return {}


def load_settings(path: str | None = None) -> dict:
    """Resolves settings with this precedence:

    1. An explicit `path` (used by tests / callers that know exactly which
       file to read).
    2. A project-local `./config/settings.json` relative to the current
       working directory, if present.
    3. The defaults bundled inside the installed package
       (cis_benchmark/core/default_settings.json).
    4. The hardcoded _DEFAULTS dict, as an absolute last resort.

    Never raises: a missing/invalid settings file at any layer must not
    prevent the CLI from running with sane defaults.
    """
    settings = dict(_DEFAULTS)

    if path is not None:
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return settings
    else:
        data = None
        if os.path.isfile(_CWD_OVERRIDE_PATH):
            try:
                data = _read_json(_CWD_OVERRIDE_PATH)
            except (OSError, json.JSONDecodeError):
                data = None
        if data is None:
            data = _load_bundled_defaults()

    if isinstance(data, dict):
        for key in _DEFAULTS:
            # A JSON `null` means "not set" here, not "explicitly override to
            # None" — otherwise a stray null in settings.json (e.g. an unset
            # google_workspace_domain) would silently clobber a meaningful
            # default like "example.com" with Python None.
            if key in data and data[key] is not None:
                settings[key] = data[key]

    return settings
