"""
Remote Access Point operations: setup, sync, and location detection.

setup_remote()  — SSH mkdir the project tree on the AP.
sync_remote()   — rsync the local project to AP, excluding runtime artifacts.
is_on_ap()      — True when running directly on the Access Point.
whereami()      — Print a summary of the current execution environment.
"""
from __future__ import annotations
import socket
import subprocess
from pathlib import Path

from .config import Config

# Subdirectories to create under remote.project_dir
_REMOTE_SUBDIRS = [
    "execution/workflows",
    "execution/submit-files",
    "execution/job-scripts",
    "data",
    "logs",
    "outputs",
    "runs",
]

# Paths excluded from rsync (relative to project root)
_RSYNC_EXCLUDES = [
    ".venv/",
    "__pycache__/",
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "*.pyc",
    "logs/",
    "outputs/",
    "runs/",
    ".condor/",
    "tokens/",
    "data/",
]


def _ssh_target(cfg: Config) -> str:
    return cfg.remote.ssh_target()


def setup_remote(cfg: Config) -> None:
    """
    SSH to the AP and create the project directory tree.
    Safe to run multiple times (mkdir -p).
    """
    dirs = " ".join(
        f"{cfg.remote.project_dir}/{sub}" for sub in _REMOTE_SUBDIRS
    )
    cmd = [
        "ssh",
        *cfg.remote.ssh_opts(),
        _ssh_target(cfg),
        f"mkdir -p {cfg.remote.project_dir} {dirs}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")


def sync_remote(cfg: Config, include_data: bool = False) -> None:
    """
    rsync the local project directory to the AP.

    By default, excludes data/, logs/, outputs/, runs/, and build artifacts.
    Pass include_data=True to also sync the local data/ directory.
    """
    excludes = list(_RSYNC_EXCLUDES)
    if include_data:
        excludes = [e for e in excludes if e != "data/"]

    exclude_args = []
    for exc in excludes:
        exclude_args += ["--exclude", exc]

    local_root = str(cfg.local.project_dir.resolve()) + "/"
    remote_dest = f"{_ssh_target(cfg)}:{cfg.remote.project_dir}/"

    cmd = [
        "rsync",
        "-avz",
        "--delete",
        "-e", f"ssh {' '.join(cfg.remote.ssh_opts())}",
        *exclude_args,
        local_root,
        remote_dest,
    ]
    subprocess.run(cmd, check=True)


def is_on_ap(cfg: Config) -> bool:
    """Return True when the current hostname matches the AP hostname."""
    try:
        local_hostname = socket.getfqdn()
        return cfg.remote.access_point in local_hostname or local_hostname in cfg.remote.access_point
    except Exception:
        return False


def whereami(cfg: Config) -> None:
    """Print a summary of the current execution environment."""
    on_ap = is_on_ap(cfg)
    hostname = socket.getfqdn()
    location = "Access Point (AP)" if on_ap else "Local machine"
    local_root = str(cfg.local.project_dir.resolve())
    remote_root = cfg.remote.project_dir
    cwd = str(Path.cwd())
    mode = cfg.submit.mode

    print(f"Location    : {location}")
    print(f"Hostname    : {hostname}")
    print(f"Local root  : {local_root}")
    print(f"Remote root : {remote_root}")
    print(f"CWD         : {cwd}")
    print(f"Submit mode : {mode}")
