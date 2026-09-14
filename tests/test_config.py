"""core/config.py must never crash the CLI: a missing or invalid
settings.json falls back to built-in defaults, and a valid file's values
are honored."""
import json
from cis_benchmark.core.config import load_settings, _DEFAULTS


def test_missing_file_falls_back_to_defaults(tmp_path):
    settings = load_settings(path=str(tmp_path / "does_not_exist.json"))
    assert settings == _DEFAULTS


def test_invalid_json_falls_back_to_defaults(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text("{not valid json")
    settings = load_settings(path=str(bad))
    assert settings == _DEFAULTS


def test_valid_file_overrides_defaults(tmp_path):
    custom = tmp_path / "settings.json"
    custom.write_text(json.dumps({"max_worker_threads": 42, "key_expiration_threshold_days": 30}))
    settings = load_settings(path=str(custom))
    assert settings["max_worker_threads"] == 42
    assert settings["key_expiration_threshold_days"] == 30
    # unset keys still fall back to defaults
    assert settings["output_directory"] == _DEFAULTS["output_directory"]


def test_null_value_in_settings_file_does_not_clobber_default(tmp_path):
    """Regression test: config/settings.json in this repo ships with
    "google_workspace_domain": null (an example of an unset field). A naive
    merge would overwrite the "example.com" default with Python None, which
    then gets stringified as the literal domain "None" in DNS lookups."""
    custom = tmp_path / "settings.json"
    custom.write_text(json.dumps({"google_workspace_domain": None, "max_worker_threads": 20}))
    settings = load_settings(path=str(custom))
    assert settings["google_workspace_domain"] == _DEFAULTS["google_workspace_domain"]
    assert settings["max_worker_threads"] == 20
