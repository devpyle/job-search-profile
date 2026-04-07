"""Startup validation — checks env vars and config values before scripts run.

Usage:
    from startup import validate

    validate(
        env_required={"ADZUNA_APP_ID": "Adzuna job search"},
        env_optional={"BRAVE_API_KEY": "Brave web search (skipped if absent)"},
        config_attrs=["CANDIDATE_NAME", "JOB_DOCS"],
        script_name="job_radar.py",
    )
"""

import os
import sys
from pathlib import Path


def validate(
    env_required=None,
    env_optional=None,
    config_attrs=None,
    script_name="",
):
    """Check env vars and config attributes. Exits with clear message on failure.

    env_required: {"VAR_NAME": "what it's for"} — blocks startup if missing
    env_optional: {"VAR_NAME": "what it enables"} — warns but continues
    config_attrs: ["ATTR_NAME", ...] — checked on config module
    script_name: displayed in error output
    """
    env_required = env_required or {}
    env_optional = env_optional or {}
    config_attrs = config_attrs or []

    errors = []
    warnings = []

    # Check required env vars
    missing_env = []
    for var, desc in env_required.items():
        if not os.environ.get(var):
            missing_env.append((var, desc))
    if missing_env:
        errors.append("Required environment variables:")
        for var, desc in missing_env:
            errors.append(f"    {var:<25s} {desc}")

    # Check optional env vars
    missing_opt = []
    for var, desc in env_optional.items():
        if not os.environ.get(var):
            missing_opt.append((var, desc))
    if missing_opt:
        warnings.append("Optional (not blocking):")
        for var, desc in missing_opt:
            warnings.append(f"    {var:<25s} {desc}")

    # Check config module
    config_errors = _check_config(config_attrs)
    if config_errors:
        errors.extend(config_errors)

    # Report
    if errors:
        header = f"  {script_name} — missing configuration:" if script_name else "  Missing configuration:"
        print(f"\n  ✗ {header}\n")
        for line in errors:
            print(f"  {line}")
        if warnings:
            print()
            for line in warnings:
                print(f"  {line}")
        print()
        print("  Fix: set env vars in .env or your shell profile.")
        print("       If config.py is missing: cp config.example.py config.py")
        print()
        sys.exit(1)

    if warnings:
        for line in warnings:
            print(f"  {line}")


def _check_config(attrs):
    """Check that config module exists and has required attributes."""
    if not attrs:
        return []

    errors = []

    # If config is already in sys.modules (e.g., test mock), use it directly
    if "config" in sys.modules:
        mod = sys.modules["config"]
        missing = [a for a in attrs if not hasattr(mod, a)]
        if missing:
            errors.append("Missing config values:")
            for attr in missing:
                errors.append(f"    {attr}")
        return errors

    # Try to find and import config.py
    repo_root = Path(__file__).parent.parent
    config_path = repo_root / "config.py"

    if not config_path.exists():
        errors.append("config.py not found.")
        errors.append("    Copy config.example.py to config.py and fill in your details.")
        return errors

    # Try importing
    try:
        sys.path.insert(0, str(repo_root))
        import config as mod
        missing = [a for a in attrs if not hasattr(mod, a)]
        if missing:
            errors.append("Missing config values:")
            for attr in missing:
                errors.append(f"    {attr}")
    except Exception as e:
        errors.append(f"config.py failed to load: {e}")

    return errors
