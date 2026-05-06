"""
Phase 3: monitor job status.

Two monitoring modes:
  watch()     — polls schedd.query() via htcondor2 bindings, live Rich table.
  follow_log() — SSHs to the AP and tails the HTCondor event log for a job.
                 htcondor.JobEventLog is the native Python reader but requires
                 a local file; follow_log() bridges that by fetching the log
                 over SSH into a local temp file and tailing it with JobEventLog.
"""
import subprocess
import time
from pathlib import Path

import htcondor2 as htcondor
from rich.console import Console
from rich.live import Live
from rich.table import Table

from .config import Config

_STATUS_LABEL = {
    1: "Idle",
    2: "Running",
    3: "Removed",
    4: "Done",
    5: "Held",
    6: "Transferring",
    7: "Suspended",
}

_STATUS_STYLE = {
    1: "yellow",
    2: "green",
    3: "red",
    4: "dim green",
    5: "bold red",
    6: "cyan",
    7: "dim",
}

_PROJECTION = [
    "ClusterId", "ProcId", "JobStatus", "Cmd",
    "HoldReason", "EnteredCurrentStatus",
]

console = Console()


def _elapsed(entered: int) -> str:
    seconds = int(time.time() - entered)
    if seconds < 0:
        return "?"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d:
        return f"{d}d {h:02}h"
    if h:
        return f"{h}h {m:02}m"
    return f"{m}m {s:02}s"


def _schedd(cfg: Config) -> htcondor.Schedd:
    collector = htcondor.Collector(cfg.remote.collector_host)
    ad = collector.locate(htcondor.DaemonType.Schedd, cfg.remote.schedd_host)
    return htcondor.Schedd(ad)


def _build_table(jobs: list) -> Table:
    table = Table(title="OSPool Jobs", expand=True)
    table.add_column("Cluster", style="bold")
    table.add_column("Proc")
    table.add_column("Status")
    table.add_column("Time in State")
    table.add_column("Executable")
    table.add_column("Hold Reason")

    for j in jobs:
        status_id = int(j.get("JobStatus", 0))
        label = _STATUS_LABEL.get(status_id, str(status_id))
        style = _STATUS_STYLE.get(status_id, "")
        cmd = Path(str(j.get("Cmd", "?"))).name
        hold = str(j.get("HoldReason", "") or "")
        entered = j.get("EnteredCurrentStatus", None)
        elapsed = _elapsed(int(entered)) if entered is not None else "?"
        table.add_row(
            str(int(j.get("ClusterId", 0))),
            str(int(j.get("ProcId", 0))),
            f"[{style}]{label}[/{style}]",
            elapsed,
            cmd,
            hold,
        )
    return table


def watch(cfg: Config, cluster_id: int | None = None, interval: int = 5) -> None:
    """
    Live-polling job status table. Refreshes every `interval` seconds.
    Ctrl-C to stop. Exits automatically when no jobs remain.
    """
    schedd = _schedd(cfg)
    if cluster_id:
        constraint = f'Owner == "{cfg.remote.username}" && ClusterId == {cluster_id}'
    else:
        constraint = f'Owner == "{cfg.remote.username}"'

    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                jobs = schedd.query(constraint=constraint, projection=_PROJECTION)
            except Exception as exc:
                live.update(f"[red]Query error: {exc}[/red]")
                time.sleep(interval)
                continue

            if not jobs:
                live.update("[dim]No matching jobs in queue.[/dim]")
                break

            live.update(_build_table(jobs))
            time.sleep(interval)


def follow_log(
    cfg: Config,
    cluster_id: int,
    prefix: str | None = None,
) -> None:
    """
    Tail a job's .out and .err files live from the AP over SSH.

    Without --prefix, finds any .out/.err files containing the cluster ID
    in the logs/ directory automatically.
    Ctrl-C to stop.
    """
    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = ["-i", cfg.remote.ssh_key, "-o", "StrictHostKeyChecking=no"]
    proj = cfg.remote.project_dir
    logs_dir = f"{proj}/logs"

    if prefix is not None:
        # Explicit prefix: try both dot and underscore separators
        candidates = [
            f"{logs_dir}/{prefix}.{cluster_id}",
            f"{logs_dir}/{prefix}_{cluster_id}",
            f"{logs_dir}/{prefix}",
        ]
        find_and_tail = " || ".join(
            f"tail -f {base}.out {base}.err 2>&1" for base in candidates
        )
        full_cmd = (
            f"({find_and_tail})"
            f" || echo 'ERROR: no log files found for prefix {prefix!r} in {logs_dir}/'"
        )
        console.print(f"[dim]Tailing {prefix}[./_]{cluster_id}.out/.err in {logs_dir}/ — Ctrl-C to stop[/dim]")
    else:
        # No prefix: find any .out file whose name contains the cluster ID
        full_cmd = (
            f"files=$(ls {logs_dir}/*{cluster_id}*.out {logs_dir}/*{cluster_id}*.err 2>/dev/null);"
            f" if [ -z \"$files\" ]; then"
            f"   echo 'ERROR: no log files matching *{cluster_id}* found in {logs_dir}/';"
            f" else"
            f"   echo \"Tailing: $files\";"
            f"   tail -f $files 2>&1;"
            f" fi"
        )
        console.print(f"[dim]Looking for *{cluster_id}*.out/.err in {logs_dir}/ — Ctrl-C to stop[/dim]")

    cmd = ["ssh", *ssh_opts, ssh_target, full_cmd]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            console.print(line, end="")
    except KeyboardInterrupt:
        console.print("[dim]Stopped.[/dim]")
    finally:
        if proc is not None:
            proc.terminate()
