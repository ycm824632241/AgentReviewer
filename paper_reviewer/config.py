import os


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
LEGACY_ENV_PATH = os.path.join(PROJECT_ROOT, "20-multi-agent-debate", ".env")


def get_env_path() -> str:
    """Prefer root .env, with legacy demo path kept for existing local setups."""
    if os.path.exists(ROOT_ENV_PATH):
        return ROOT_ENV_PATH
    return LEGACY_ENV_PATH


def get_env_value(primary_key: str, legacy_key: str | None = None, default: str | None = None) -> str | None:
    """Read provider-neutral env vars first, then legacy provider-specific names."""
    value = os.getenv(primary_key)
    if value:
        return value
    if legacy_key:
        legacy_value = os.getenv(legacy_key)
        if legacy_value:
            return legacy_value
    return default
