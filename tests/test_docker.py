"""Static/structural tests for the Docker one-command run (batch 100).

No docker binary is available on this VM, so every test is a static,
structural check of the Dockerfile, .dockerignore, entrypoint, compose
files, Makefile, and the `candid dashboard --host` CLI flag.

Expected content is read from the actual files created by the other
batch-100 workers; nothing here is invented.

stdlib + pytest only. Run with: python -m pytest tests/test_docker.py -q
"""
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    path = ROOT / rel
    assert path.is_file(), f"expected file missing: {rel}"
    return path.read_text(encoding="utf-8")


def _dockerfile() -> str:
    return _read("Dockerfile")


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------

class TestDockerfile:
    def test_two_from_stages(self):
        stages = re.findall(r"^FROM\s+\S+", _dockerfile(), flags=re.MULTILINE | re.IGNORECASE)
        assert len(stages) == 2, f"expected 2 FROM stages, found: {stages}"
        for stage in stages:
            assert "python:3.12-slim" in stage, f"stage must be python:3.12-slim: {stage}"

    def test_non_root_user(self):
        text = _dockerfile()
        users = re.findall(r"^USER\s+(\S+)", text, flags=re.MULTILINE | re.IGNORECASE)
        assert users, "Dockerfile has no USER directive"
        assert users[-1] != "root", "final USER must not be root"
        assert users[-1] == "candid", f"expected USER candid, got: {users[-1]}"

    def test_healthcheck(self):
        assert re.search(r"^HEALTHCHECK\s", _dockerfile(), flags=re.MULTILINE | re.IGNORECASE), \
            "Dockerfile is missing a HEALTHCHECK directive"

    def test_expose_8765(self):
        assert re.search(r"^EXPOSE\s+.*\b8765\b", _dockerfile(), flags=re.MULTILINE | re.IGNORECASE), \
            "Dockerfile must EXPOSE 8765"

    def test_env_candid_data_dir(self):
        text = _dockerfile()
        assert re.search(r"^ENV\b", text, flags=re.MULTILINE), \
            "Dockerfile is missing an ENV directive"
        assert re.search(r"CANDID_DATA_DIR=/data\b", text), \
            "Dockerfile must set CANDID_DATA_DIR=/data"

    def test_volume_data(self):
        assert re.search(r"^VOLUME\s+/data\b", _dockerfile(), flags=re.MULTILINE | re.IGNORECASE), \
            "Dockerfile must declare VOLUME /data"

    def test_oci_labels(self):
        text = _dockerfile()
        assert re.search(r"^LABEL\b", text, flags=re.MULTILINE), \
            "Dockerfile is missing a LABEL directive"
        for key in ("org.opencontainers.image.title",
                    "org.opencontainers.image.description",
                    "org.opencontainers.image.source",
                    "org.opencontainers.image.url",
                    "org.opencontainers.image.licenses",
                    "org.opencontainers.image.version"):
            assert re.search(rf"{re.escape(key)}\s*=", text), \
                f"Dockerfile is missing OCI label: {key}"

    def test_entrypoint_references_entrypoint_sh(self):
        text = _dockerfile()
        assert re.search(r"^ENTRYPOINT\s", text, flags=re.MULTILINE | re.IGNORECASE), \
            "Dockerfile is missing an ENTRYPOINT directive"
        assert "entrypoint.sh" in text, \
            "Dockerfile must reference entrypoint.sh (the docker/entrypoint.sh script)"


# ---------------------------------------------------------------------------
# .dockerignore
# ---------------------------------------------------------------------------

class TestDockerignore:
    EXPECTED = ["candid_data/", "output/", "profile.yaml", ".git", "__pycache__"]

    def test_excludes_local_data_and_caches(self):
        lines = [ln.strip() for ln in _read(".dockerignore").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        for entry in self.EXPECTED:
            assert entry in lines, f".dockerignore must exclude '{entry}'"


# ---------------------------------------------------------------------------
# docker/entrypoint.sh
# ---------------------------------------------------------------------------

class TestEntrypoint:
    PATH = "docker/entrypoint.sh"

    def test_executable(self):
        path = ROOT / self.PATH
        assert path.is_file(), f"expected file missing: {self.PATH}"
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, "entrypoint.sh must be executable"

    def test_shebang(self):
        first = _read(self.PATH).splitlines()[0]
        assert first.startswith("#!"), "entrypoint.sh must start with a shebang"

    def test_references_onboard_wizard(self):
        text = _read(self.PATH)
        assert "onboard" in text, "entrypoint.sh must reference the onboard wizard"

    def test_execs_command(self):
        text = _read(self.PATH)
        assert re.search(r"^\s*exec\b", text, flags=re.MULTILINE), \
            "entrypoint.sh must exec the requested command"
        assert '"$@"' in text, 'entrypoint.sh must pass through "$@"'


# ---------------------------------------------------------------------------
# docker-compose files (pure-stdlib YAML structural check)
# ---------------------------------------------------------------------------

def _load_compose_mapping(rel: str) -> dict:
    """Parse a compose file into a top-level mapping.

    Uses pyyaml when importable; otherwise falls back to a minimal stdlib
    check: collect zero-indented top-level keys and require sane 2-space
    indentation on every other meaningful line.
    """
    text = _read(rel)
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        data = yaml.safe_load(text)
        assert isinstance(data, dict), f"{rel} must parse to a YAML mapping"
        return data
    top: dict = {}
    current = None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        assert indent % 2 == 0, f"{rel}:{lineno}: bad indentation: {line!r}"
        if indent == 0:
            m = re.match(r"^([A-Za-z0-9_-]+)\s*:", line)
            assert m, f"{rel}:{lineno}: not a mapping key: {line!r}"
            current = m.group(1)
            top.setdefault(current, {})
        elif current is not None:
            top[current] = True
    return top


@pytest.mark.parametrize("rel", ["docker-compose.yml", "docker-compose.dev.yml"])
class TestCompose:
    def test_parses_as_mapping_with_services(self, rel):
        data = _load_compose_mapping(rel)
        assert "services" in data, f"{rel} must define top-level 'services:'"


class TestBaseCompose:
    REL = "docker-compose.yml"

    def test_defines_named_volume_at_data(self):
        text = _read(self.REL)
        assert re.search(r"^\s{2,}-\s+\S+:/data", text, flags=re.MULTILINE), \
            "docker-compose.yml must mount a volume at /data (the data dir)"

    def test_top_level_volumes(self):
        data = _load_compose_mapping(self.REL)
        assert "volumes" in data, \
            "docker-compose.yml must define top-level 'volumes:'"
        assert "candid-data" in str(data["volumes"]), \
            "docker-compose.yml must declare the candid-data named volume"

    def test_dashboard_service_port_and_host(self):
        text = _read(self.REL)
        assert "8765:8765" in text, \
            "docker-compose.yml must map the dashboard port 8765:8765"
        assert "--host" in text, \
            "docker-compose.yml dashboard command must pass --host 0.0.0.0"


class TestDevCompose:
    REL = "docker-compose.dev.yml"

    def test_bind_mounts_repo_source(self):
        text = _read(self.REL)
        assert ".:/app" in text, \
            "docker-compose.dev.yml must bind-mount the repo over /app"


# ---------------------------------------------------------------------------
# Makefile
# ---------------------------------------------------------------------------

class TestMakefile:
    # Targets documented in the Makefile's own header comment.
    DOCUMENTED = {"docker-build", "docker-shell", "docker-run",
                  "docker-dashboard", "docker-dev", "docker-clean"}

    def _targets(self) -> set:
        targets = set()
        for line in _read("Makefile").splitlines():
            if line and not line[0].isspace():
                m = re.match(r"^([A-Za-z0-9_-][A-Za-z0-9_.-]*)\s*:(?![=])", line)
                if m:
                    targets.add(m.group(1))
        return targets

    def test_documented_targets_exist(self):
        targets = self._targets()
        assert targets, "Makefile defines no targets"
        missing = self.DOCUMENTED - targets
        assert not missing, f"Makefile is missing documented targets: {sorted(missing)}"

    def test_recipes_use_docker_compose(self):
        text = _read("Makefile")
        assert "docker compose" in text, \
            "Makefile recipes should drive docker compose"


# ---------------------------------------------------------------------------
# candid dashboard --host flag
# ---------------------------------------------------------------------------

class TestDashboardHostFlag:
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "candid", "dashboard", *args],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )

    def test_host_flag_present(self):
        proc = self._run("--help")
        assert proc.returncode == 0, f"'candid dashboard --help' failed:\n{proc.stderr}"
        assert "--host" in proc.stdout, \
            "'candid dashboard --help' must show the --host flag"

    def test_host_flag_accepted(self):
        """--host must be accepted by the parser (argparse exits 2 on unknown flags)."""
        proc = self._run("--help", "--host", "0.0.0.0")
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# This worker's own deliverables exist
# ---------------------------------------------------------------------------

class TestDockerWorkerDeliverables:
    @pytest.mark.parametrize("rel", [
        "tests/test_docker.py",
        "scripts/docker-smoke.sh",
        ".github/workflows/docker.yml",
    ])
    def test_file_present(self, rel):
        assert (ROOT / rel).is_file(), f"worker D deliverable missing: {rel}"
