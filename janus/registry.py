"""Janus Registry — service definitions from local cache + remote registry."""

import os
from pathlib import Path
import tempfile
import urllib.request
import yaml

REGISTRY_URL = "https://api.github.com/repos/Duskript/janus-registry/contents/services"
REGISTRY_INDEX_URL = "https://raw.githubusercontent.com/Duskript/janus-registry/main/INDEX.md"

CONFIG_DIR = Path.home() / ".config" / "janus"
SERVICES_DIR = CONFIG_DIR / "services.d"
CACHE_DIR = CONFIG_DIR / "cache"


def _ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_catalog() -> list[dict]:
    """Load all locally cached service definitions."""
    _ensure_dirs()
    services = []
    if not SERVICES_DIR.exists():
        return services
    for f in sorted(SERVICES_DIR.glob("*.yaml")):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data and data.get("name"):
                data["key"] = f.stem
                services.append(data)
        except Exception:
            continue
    return services


def _get_local(key: str) -> dict | None:
    path = SERVICES_DIR / f"{key}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        data = yaml.safe_load(f)
    if data:
        data["key"] = key
    return data


def registry_search(query: str = "") -> list[dict]:
    """Search cached services. Query is matched against name, key, and category."""
    services = _load_catalog()
    q = query.strip().lower()
    if not q:
        return services
    return [
        s for s in services
        if q in s.get("name", "").lower()
        or q in s.get("key", "").lower()
        or q in s.get("category", "").lower()
    ]


def registry_get(service_key: str) -> dict | None:
    """Get a service definition by key."""
    # Check local cache first
    local = _get_local(service_key)
    if local:
        return local
    # Fall back to fetching from registry
    from_temp = _fetch_from_registry(service_key)
    return from_temp


def registry_install(service_key: str) -> Path | None:
    """Download a service definition from the registry to local cache."""
    from_temp = _fetch_from_registry(service_key)
    if not from_temp:
        return None
    _ensure_dirs()
    dest = SERVICES_DIR / f"{service_key}.yaml"
    with open(dest, "w") as f:
        yaml.dump(from_temp, f, default_flow_style=False)
    return dest


def _fetch_from_registry(service_key: str) -> dict | None:
    """Fetch a single service yaml from GitHub raw content."""
    url = f"https://raw.githubusercontent.com/Duskript/janus-registry/main/services/{service_key}.yaml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "janus-mcp/0.1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = yaml.safe_load(resp.read().decode("utf-8"))
        if data and data.get("name"):
            data["key"] = service_key
            return data
    except Exception:
        return None
    return None


def registry_get_all_local() -> list[dict]:
    return _load_catalog()


def registry_update() -> int:
    """Fetch the INDEX.md to count available services."""
    try:
        req = urllib.request.Request(REGISTRY_INDEX_URL, headers={"User-Agent": "janus-mcp/0.1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            index_content = resp.read().decode("utf-8")
        _ensure_dirs()
        (CACHE_DIR / "INDEX.md").write_text(index_content)
        # Return a rough count (lines with "`" in the index)
        count = sum(1 for line in index_content.splitlines() if "`" in line and ".yaml" in line)
        return count
    except Exception:
        return 0
