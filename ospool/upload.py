"""
Upload local data to the OSDF origin on the Access Point.

Files land at /ospool/ap40/data/<username>/ and are accessible in jobs as:
  osdf:///ospool/ap40/data/<username>/<path>

Prefers rsync; falls back to scp if rsync is not installed.
"""
from __future__ import annotations
from typing import Optional
import shutil
import subprocess
from pathlib import Path

from .config import Config


def _osdf_ssh_path(cfg: Config) -> str:
    """Convert osdf:///ospool/ap40/data/user → /ospool/ap40/data/user."""
    return cfg.osdf.base_path.replace("osdf://", "")


def _has_rsync() -> bool:
    return shutil.which("rsync") is not None


def upload(cfg: Config, source: Optional[Path] = None) -> str:
    """
    Upload a file or directory to OSDF.

    If source is None, uploads the entire local data/ directory.
    Prefers rsync; falls back to scp if rsync is not available.
    Returns the remote OSDF path the data landed at.
    """
    if source is None:
        source = cfg.local.data_dir.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"data/ directory not found at {source}")
        is_default_dir = True
    else:
        source = source.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source}")
        is_default_dir = False

    remote_path = _osdf_ssh_path(cfg)
    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = cfg.remote.ssh_opts()

    print(f"Ensuring remote OSDF directory exists: {ssh_target}:{remote_path}/")
    subprocess.run(
        ["ssh", *ssh_opts, ssh_target, f"mkdir -p {remote_path}"],
        check=True,
    )

    if _has_rsync():
        tool = "rsync"
        source_arg = str(source) + "/" if is_default_dir else str(source)
        cmd = [
            "rsync",
            "-az",
            "--info=stats1,progress2",
            "-e", " ".join(["ssh"] + ssh_opts),
            source_arg,
            f"{ssh_target}:{remote_path}/",
        ]
    else:
        tool = "scp"
        print("rsync not found — falling back to scp")
        if source.is_dir():
            cmd = ["scp", *ssh_opts, "-r", str(source), f"{ssh_target}:{remote_path}/"]
        else:
            cmd = ["scp", *ssh_opts, str(source), f"{ssh_target}:{remote_path}/"]

    kind = "directory" if source.is_dir() else "file"
    print(f"Uploading {kind} {source} → {cfg.remote.access_point}:{remote_path}/ (via {tool})")
    subprocess.run(cmd, check=True)
    print(f"Upload complete. Reference in jobs as: osdf://{remote_path}/<filename>")
    return remote_path
