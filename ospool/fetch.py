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


def retrieve_spool(cfg: Config, cluster_id: int, dest: Optional[Path] = None) -> Path:
    """
    Retrieve output files for a spool-mode job that had no OSDF output remap.

    schedd.retrieve() fails locally because the job's log/output/error use
    absolute AP paths that don't exist on WSL. Instead, we SSH to the AP and
    run condor_transfer_data there (where those paths exist), collect the
    output file into a temp dir, rsync it back, then clean up.
    Returns the local destination path.
    """
    if dest is None:
        dest = cfg.local.outputs_dir / str(cluster_id)

    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = _ssh_opts(cfg)
    ap_tmp = f"{cfg.remote.project_dir}/.spool_retrieve_{cluster_id}"

    print(f"Retrieving spooled output for cluster {cluster_id} via AP ...")

    # condor_transfer_data writes output files back to the job's iwd (initialdir),
    # which for spool-mode jobs is the schedd's spool directory, not CWD.
    # Strategy:
    #   1. Find where the schedd spool sandbox is for this job
    #   2. Run condor_transfer_data to flush the outputs there
    #   3. Rsync the output files (*.tar.gz, *.txt, etc.) back — skipping log files
    #      which are already on the AP in the logs/ dir

    # Step 1: find the spool sandbox path via condor_q
    find_result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target,
         f"condor_q {cluster_id}.0 -format '%s\\n' Iwd 2>/dev/null "
         f"|| condor_history {cluster_id}.0 -format '%s\\n' Iwd 2>/dev/null | head -1"],
        capture_output=True, text=True,
    )
    iwd = find_result.stdout.strip().splitlines()
    iwd = [l for l in iwd if l.strip()]
    sandbox = iwd[0] if iwd else None
    print(f"  Job iwd: {sandbox or '(not found — job may have been purged from spool)'}")

    # Step 2: run condor_transfer_data on the AP
    result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target,
         f"condor_transfer_data {cluster_id}.0 2>&1"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        print(f"  condor_transfer_data: {result.stdout.strip()}")
    if result.returncode != 0 and result.stderr.strip():
        print(f"  stderr: {result.stderr.strip()}")

    # Step 3: rsync output files from the sandbox back (skip .log/.out/.err)
    if sandbox:
        print(f"  Rsyncing output files from {sandbox}/ ...")
        subprocess.run(
            ["rsync", "-az", "--info=progress2",
             "--exclude=*.log", "--exclude=*.out", "--exclude=*.err",
             "--exclude=analysis.tar.gz", "--exclude=analysis/",
             "--exclude=venv/", "--exclude=*.pcap", "--exclude=*.tar.gz.bak",
             "--include=patchwork_results*.tar.gz",
             "--include=*.tar.gz", "--include=*.txt", "--include=*.csv",
             "--include=*.png", "--exclude=*",
             "-e", " ".join(["ssh"] + ssh_opts),
             f"{ssh_target}:{sandbox}/",
             str(dest) + "/"],
            check=True,
        )
    else:
        print("  WARNING: could not locate spool sandbox — no files to rsync.")

    # Rename files to include cluster ID so they don't collide with other jobs
    for f in list(dest.iterdir()):
        if str(cluster_id) not in f.name:
            stem = f.stem
            suffix = "".join(f.suffixes)
            f.rename(dest / f"{stem}_{cluster_id}{suffix}")

    final_files = list(dest.iterdir())
    print(f"\nRetrieved {len(final_files)} file(s) to {dest}/:")
    for f in sorted(final_files):
        print(f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)")

    return dest


def fetch_outputs(cfg: Config, cluster_id: int, dest: Optional[Path] = None) -> Path:
    """
    Rsync output files for a completed job to local outputs/<cluster_id>/.

    Checks in order:
      1. AP home outputs dir  (/home/<user>/ospool-manager/outputs/)  — used by
         patchwork_direct.sub which remaps there to avoid broken OSDF writes.
      2. OSDF outputs dir     (/ospool/ap40/data/<user>/outputs/)      — used by
         the original patchwork.sub.
    Returns the local destination path.
    """
    if dest is None:
        dest = cfg.local.outputs_dir / str(cluster_id)

    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = _ssh_opts(cfg)

    ap_home_outputs = f"{cfg.remote.project_dir}/outputs"
    osdf_outputs    = f"{_osdf_ssh_path(cfg)}/outputs"

    # Search both locations, prefer AP home
    find_result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target,
         f"ls {ap_home_outputs}/*{cluster_id}* {osdf_outputs}/*{cluster_id}* 2>/dev/null || true"],
        capture_output=True, text=True,
    )
    remote_files = [f for f in find_result.stdout.strip().splitlines() if f]

    if not remote_files:
        print(f"No files matching *{cluster_id}* found in:")
        print(f"  {ap_home_outputs}/")
        print(f"  {osdf_outputs}/")
        print("Job may still be running or output remap failed.")
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
    ap_home_outputs = f"{cfg.remote.project_dir}/outputs"
    osdf_outputs    = f"{_osdf_ssh_path(cfg)}/outputs"

    # Sync AP home outputs first (patchwork_direct.sub remaps here)
    print(f"Fetching outputs from {cfg.remote.access_point}:{ap_home_outputs}/ → {dest}/")
    subprocess.run(
        ["rsync", "-az", "--info=progress2",
         "-e", " ".join(["ssh"] + ssh_opts),
         f"{ssh_target}:{ap_home_outputs}/",
         str(dest) + "/"],
        check=True,
    )

    # Also sync OSDF outputs (original patchwork.sub remapped here)
    print(f"Fetching outputs from {cfg.remote.access_point}:{osdf_outputs}/ → {dest}/")
    subprocess.run(
        ["rsync", "-az", "--info=progress2",
         "-e", " ".join(["ssh"] + ssh_opts),
         f"{ssh_target}:{osdf_outputs}/",
         str(dest) + "/"],
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
