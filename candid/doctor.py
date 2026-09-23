"""`candid doctor`: minimal health checks for a candid install.

Each check returns a dict::

    {"name": str, "ok": bool, "detail": str}

``check_health()`` never raises on its own — a failing check is data, not an
exception. The CLI wrapper exits nonzero when any check fails.
"""

from __future__ import annotations

import sys

from candid import config as C


def _check_config_loads() -> dict:
    try:
        cfg = C.load_config()
    except Exception as exc:  # noqa: BLE001 - surfaced as check data
        return {"name": "config loads", "ok": False,
                "detail": f"{C.CONFIG_PATH} is unreadable: {exc}"}
    ver = C.config_version_of(cfg)
    return {"name": "config loads", "ok": True,
            "detail": f"{C.CONFIG_PATH} (v{ver})"}


def _check_config_current() -> dict:
    try:
        cfg = C.load_config()
    except Exception as exc:  # noqa: BLE001
        return {"name": "config_version current", "ok": False,
                "detail": f"could not read config: {exc}"}
    ver = C.config_version_of(cfg)
    if ver == C.CONFIG_VERSION:
        return {"name": "config_version current", "ok": True,
                "detail": f"v{ver} is the current schema"}
    if ver > C.CONFIG_VERSION:
        return {"name": "config_version current", "ok": False,
                "detail": f"config is v{ver}, newer than this candid "
                          f"(max v{C.CONFIG_VERSION}) — upgrade candid"}
    return {"name": "config_version current", "ok": False,
            "detail": f"config is v{ver}, current is v{C.CONFIG_VERSION} — "
                      "run `python -m candid migrate`"}


def _check_data_dir_writable() -> dict:
    probe = C.DATA_DIR / ".doctor-probe"
    try:
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:  # noqa: BLE001
        return {"name": "data dir writable", "ok": False,
                "detail": f"{C.DATA_DIR}: {exc}"}
    return {"name": "data dir writable", "ok": True, "detail": str(C.DATA_DIR)}


def _check_python_version() -> dict:
    ok = sys.version_info >= (3, 9)
    return {"name": "python >= 3.9", "ok": ok,
            "detail": f"{sys.version.split()[0]}"}


CHECKS = [
    _check_config_loads,
    _check_config_current,
    _check_data_dir_writable,
    _check_python_version,
]


def check_health() -> list[dict]:
    """Run every health check; failing checks come back as data."""
    return [fn() for fn in CHECKS]


def all_ok(results: list[dict]) -> bool:
    return all(r["ok"] for r in results)


def render_health(results: list[dict]) -> str:
    """Human-readable report with a one-line verdict."""
    lines = []
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"{mark} {r['name']}: {r['detail']}")
    verdict = ("All checks passed." if all_ok(results)
               else f"{sum(not r['ok'] for r in results)} check(s) failed.")
    lines.append(verdict)
    return "\n".join(lines)
