"""Resolve official renderers installed on PATH or by this skill group."""

import os
import re
import shutil
import subprocess
from pathlib import Path


ENGINE_BINARIES = {"mermaid": "mmdc", "plantuml": "plantuml",
                   "drawio": "drawio", "archify": "archify"}
NODE_VERSION = "24.22.0"


def renderer_home():
    configured = os.environ.get("UNDERSTAND_RENDERER_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".local/share/understand-skills/renderers"


def find_engine(engine, explicit=None):
    if engine not in ENGINE_BINARIES:
        raise ValueError(f"unknown renderer: {engine}")
    if explicit is not None:
        return shutil.which(str(explicit))
    configured = os.environ.get(f"{engine.upper()}_OFFICIAL_CLI")
    if configured:
        return shutil.which(configured)
    managed = renderer_home() / "bin" / ENGINE_BINARIES[engine]
    if managed.is_file() and os.access(managed, os.X_OK):
        return str(managed)
    return shutil.which(ENGINE_BINARIES[engine])


def prepare_runtime():
    """Let managed Node power its renderers without changing the user's shell PATH."""
    runtime_version = NODE_VERSION
    node_bin = renderer_home() / "runtime" / f"node-v{runtime_version}" / "bin"
    if not (node_bin / "node").is_file():
        # Keep existing installations usable until their dependency update installs the new pin.
        runtime_version = "22.13.1"
        node_bin = renderer_home() / "runtime" / f"node-v{runtime_version}" / "bin"
    if not (node_bin / "node").is_file():
        return
    current = shutil.which("node")
    if current:
        try:
            result = subprocess.run([current, "--version"], capture_output=True, text=True, timeout=20)
            version = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout.strip())
            if result.returncode == 0 and version and tuple(map(int, version.groups())) >= tuple(map(int, runtime_version.split("."))):
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    os.environ["PATH"] = str(node_bin) + os.pathsep + os.environ.get("PATH", "")
