"""
Phase 4: retrieve completed job outputs.

Jobs push output files directly to OSDF via transfer_output_remaps.
The OSDF path osdf:///ospool/ap40/data/<user>/outputs/ is accessible
via SSH on the AP at /ospool/ap40/data/<user>/outputs/.

fetch_outputs() rsyncs files matching the cluster ID from that path
back to local outputs/<cluster_id>/.
"""
from __future__ import annotations
from typing import Optional
import subprocess
from pathlib import Path

from .config import Config


def _ssh_opts(cfg: Config) -> list[str]:
    return ["-i", cfg.remote.ssh_key, "-o", "StrictHostKeyChecking=no", "-o", "IdentitiesOnly=yes"]


def _osdf_ssh_path(cfg: Config) -> str:
    """Convert osdf:///ospool/ap40/data/user → /ospool/ap40/data/user."""
    return cfg.osdf.base_path.replace("osdf://", "")


def fetch_outputs(cfg: Config, cluster_id: int, dest: Optional[Path] = None) -> Path:
    """
    Rsync output files for a completed job from OSDF to local outputs/<cluster_id>/.

    Looks for files matching *<cluster_id>* in the OSDF outputs/ directory.
    Returns the local destination path.
    """
    if dest is None:
        dest = cfg.local.outputs_dir / str(cluster_id)

    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = _ssh_opts(cfg)
    remote_outputs = f"{_osdf_ssh_path(cfg)}/outputs"

    print(f"Fetching outputs for cluster {cluster_id} from {cfg.remote.access_point}:{remote_outputs}/")

    # Find matching files on the AP
    find_result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target,
         f"ls {remote_outputs}/*{cluster_id}* 2>/dev/null || true"],
        capture_output=True, text=True,
    )
    remote_files = [f for f in find_result.stdout.strip().splitlines() if f]

    if not remote_files:
        print(f"No files matching *{cluster_id}* found in {remote_outputs}/")
        print("Job may still be running or output not yet written to OSDF.")
        return dest

    print(f"Found on AP:")
    for f in remote_files:
        print(f"  {f}")

    for remote_file in remote_files:
        subprocess.run(
            [
                "rsync", "-az", "--info=progress2",
                "-e", " ".join(["ssh"] + ssh_opts),
                f"{ssh_target}:{remote_file}",
                str(dest) + "/",
            ],
            check=True,
        )

    local_files = list(dest.iterdir())
    print(f"\nFetched {len(local_files)} file(s) to {dest}/:")
    for f in local_files:
        size = f.stat().st_size
        print(f"  {f.name}  ({size / 1024:.1f} KB)")

    # Also sync matching log files from AP logs/ → local logs/
    _sync_logs_for_cluster(cfg, cluster_id, ssh_target, ssh_opts)

    return dest


def _sync_logs_for_cluster(
    cfg: Config, cluster_id: int, ssh_target: str, ssh_opts: list[str]
) -> None:
    """Rsync log files matching the cluster ID from AP logs/ to local logs/."""
    remote_logs = f"{cfg.remote.project_dir}/logs"
    local_logs = cfg.local.logs_dir.resolve()
    local_logs.mkdir(parents=True, exist_ok=True)

    find_result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target,
         f"ls {remote_logs}/*{cluster_id}* 2>/dev/null || true"],
        capture_output=True, text=True,
    )
    log_files = [f for f in find_result.stdout.strip().splitlines() if f]

    if not log_files:
        return

    print(f"\nSyncing {len(log_files)} log file(s) to {local_logs}/:")
    for remote_file in log_files:
        subprocess.run(
            [
                "rsync", "-az",
                "-e", " ".join(["ssh"] + ssh_opts),
                f"{ssh_target}:{remote_file}",
                str(local_logs) + "/",
            ],
            check=True,
        )
        print(f"  {Path(remote_file).name}")


def fetch_all(cfg: Config, dest: Optional[Path] = None) -> Path:
    """
    Rsync everything in the OSDF outputs/ directory to local outputs/.
    Returns the local destination path.
    """
    if dest is None:
        dest = cfg.local.outputs_dir

    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = _ssh_opts(cfg)
    remote_outputs = f"{_osdf_ssh_path(cfg)}/outputs"

    print(f"Fetching all outputs from {cfg.remote.access_point}:{remote_outputs}/ → {dest}/")

    subprocess.run(
        [
            "rsync", "-az", "--info=progress2",
            "-e", " ".join(["ssh"] + ssh_opts),
            f"{ssh_target}:{remote_outputs}/",
            str(dest) + "/",
        ],
        check=True,
    )

    local_files = list(dest.iterdir())
    print(f"\nFetched {len(local_files)} file(s) to {dest}/:")
    for f in sorted(local_files):
        size = f.stat().st_size
        print(f"  {f.name}  ({size / 1024:.1f} KB)")

    # Also sync all logs from AP logs/ → local logs/
    remote_logs = f"{cfg.remote.project_dir}/logs"
    local_logs = cfg.local.logs_dir.resolve()
    local_logs.mkdir(parents=True, exist_ok=True)
    print(f"\nSyncing logs from {cfg.remote.access_point}:{remote_logs}/ → {local_logs}/")
    subprocess.run(
        [
            "rsync", "-az", "--info=progress2",
            "-e", " ".join(["ssh"] + ssh_opts),
            f"{ssh_target}:{remote_logs}/",
            str(local_logs) + "/",
        ],
        check=True,
    )

    return dest
