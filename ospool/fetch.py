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


def _spool_cp(cfg: Config, cluster_ids: Optional[list[int]], dest_dir: Path, ssh_target: str, ssh_opts: list[str]) -> list[str]:
    """
    SSH to the AP, find patchwork_results.tar.gz files in the condor spool for
    the given cluster IDs (or all belonging to this user), copy them to dest_dir
    on the AP with cluster-ID-stamped names, and return the list of remote paths.

    This is the fallback when transfer_output_remaps fails to write to OSDF/home.
    """
    if cluster_ids:
        # Build a grep pattern to match any of the requested cluster IDs
        pattern = "|".join(f"cluster{c}" for c in cluster_ids)
        find_filter = f"| grep -E '{pattern}'"
    else:
        find_filter = ""

    script = f"""
set -e
mkdir -p {dest_dir}
find /var/lib/condor/spool -name "patchwork_results.tar.gz" -user {cfg.remote.username} 2>/dev/null {find_filter} | while read src; do
  cluster=$(echo "$src" | grep -oE 'cluster[0-9]+' | grep -oE '[0-9]+')
  dest="{dest_dir}/patchwork_results_${{cluster}}.tar.gz"
  if [ ! -f "$dest" ]; then
    cp "$src" "$dest"
    echo "$dest"
  fi
done
"""
    result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target, script],
        capture_output=True, text=True,
    )
    copied = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    return copied


def retrieve_spool(cfg: Config, cluster_id: int, dest: Optional[Path] = None) -> Path:
    """
    Retrieve output for a single job from the condor spool on the AP.
    Copies directly from /var/lib/condor/spool — no condor_transfer_data needed.
    """
    if dest is None:
        dest = cfg.local.outputs_dir / str(cluster_id)
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = _ssh_opts(cfg)
    ap_staging = f"{cfg.remote.project_dir}/outputs"

    print(f"Recovering spooled output for cluster {cluster_id} from AP spool ...")
    copied = _spool_cp(cfg, [cluster_id], ap_staging, ssh_target, ssh_opts)

    if not copied:
        print(f"  No spool file found for cluster {cluster_id} — spool may have been purged.")
        return dest

    for remote_path in copied:
        subprocess.run(
            ["rsync", "-az", "--info=progress2",
             "-e", " ".join(["ssh"] + ssh_opts),
             f"{ssh_target}:{remote_path}", str(dest) + "/"],
            check=True,
        )

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
        print(f"No files matching *{cluster_id}* found in outputs dirs — trying spool recovery ...")
        return retrieve_spool(cfg, cluster_id, dest)

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

    # Also sweep the condor spool for any outputs that never made it to the outputs dirs
    print(f"\nSweeping condor spool for any remaining output files ...")
    ap_staging = f"{cfg.remote.project_dir}/outputs"
    spool_copied = _spool_cp(cfg, None, ap_staging, ssh_target, ssh_opts)
    if spool_copied:
        print(f"  Found {len(spool_copied)} file(s) in spool — rsyncing ...")
        subprocess.run(
            ["rsync", "-az", "--info=progress2",
             "-e", " ".join(["ssh"] + ssh_opts),
             f"{ssh_target}:{ap_staging}/",
             str(dest) + "/"],
            check=True,
        )
    else:
        print("  No new files found in spool.")

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
