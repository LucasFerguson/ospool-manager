"""
Phase 3: monitor job status.

Two monitoring modes:
  watch()     — polls schedd.query() via htcondor2 bindings, live Rich table.
  follow_log() — SSHs to the AP and tails the HTCondor event log for a job.
                 htcondor.JobEventLog is the native Python reader but requires
                 a local file; follow_log() bridges that by fetching the log
                 over SSH into a local temp file and tailing it with JobEventLog.
"""
from __future__ import annotations
from typing import Optional
import subprocess
import time
from pathlib import Path

import htcondor2 as htcondor
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
    "HoldReason", "EnteredCurrentStatus", "QDate", "TransferInput",
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


# Job infrastructure files — excluded from the Input Data column regardless of path.
# In spool mode HTCondor rewrites TransferInput to spool dir paths, so we can't
# filter by "data/" in the path; we filter by filename instead.
_INPUT_EXCLUDES = {"analysis.tar.gz", "ospool_main.sh"}


def _data_inputs(transfer_input: str) -> str:
    """
    Return the data files from a comma-separated TransferInput string,
    excluding known job-infrastructure files (analysis.tar.gz, *.sh).
    Works for both spool mode (paths rewritten to spool dir) and ap-project mode.
    Returns bare filenames only, newline-separated.
    """
    if not transfer_input:
        return ""
    entries = [e.strip() for e in transfer_input.split(",") if e.strip()]
    data_files = [
        Path(e).name
        for e in entries
        if Path(e).name not in _INPUT_EXCLUDES and not Path(e).name.endswith(".sh")
    ]
    return "\n".join(data_files)


def _build_table(jobs: list) -> Table:
    table = Table(title="OSPool Jobs", expand=True)
    table.add_column("Cluster", style="bold")
    table.add_column("Proc")
    table.add_column("Status")
    table.add_column("Time in State")
    table.add_column("Input Data")
    table.add_column("Executable")
    table.add_column("Hold Reason")

    jobs = sorted(jobs, key=lambda j: int(j.get("QDate", 0)), reverse=True)

    for j in jobs:
        status_id = int(j.get("JobStatus", 0))
        label = _STATUS_LABEL.get(status_id, str(status_id))
        style = _STATUS_STYLE.get(status_id, "")
        cmd = Path(str(j.get("Cmd", "?"))).name
        hold = str(j.get("HoldReason", "") or "")
        entered = j.get("EnteredCurrentStatus", None)
        elapsed = _elapsed(int(entered)) if entered is not None else "?"
        transfer_input = str(j.get("TransferInput", "") or "")
        input_data = _data_inputs(transfer_input)
        table.add_row(
            str(int(j.get("ClusterId", 0))),
            str(int(j.get("ProcId", 0))),
            f"[{style}]{label}[/{style}]",
            elapsed,
            input_data,
            cmd,
            hold,
        )
    return table


def watch(cfg: Config, cluster_id: Optional[int] = None, interval: int = 5) -> None:
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


_DETAIL_PROJECTION = [
    "ClusterId", "ProcId", "JobStatus", "Cmd", "Owner",
    "HoldReason", "EnteredCurrentStatus", "RemoteHost",
    "JobStartDate", "JobCurrentStartDate", "CompletionDate",
    "QDate", "RequestCpus", "RequestMemory", "RequestDisk",
    "NumJobStarts", "NumShadowStarts", "TransferInput",
]

_IDLE = 1
_RUNNING = 2


def _query_job(cfg: Config, cluster_id: int) -> Optional[dict]:
    """Return the first proc of a cluster as a plain dict, or None if not found."""
    schedd = _schedd(cfg)
    constraint = f'Owner == "{cfg.remote.username}" && ClusterId == {cluster_id}'
    jobs = schedd.query(constraint=constraint, projection=_DETAIL_PROJECTION)
    return dict(jobs[0]) if jobs else None


def _print_job_info(j: dict) -> None:
    """Print a rich summary panel for a single job."""
    status_id = int(j.get("JobStatus", 0))
    label     = _STATUS_LABEL.get(status_id, str(status_id))
    style     = _STATUS_STYLE.get(status_id, "")
    cmd       = Path(str(j.get("Cmd", "?"))).name
    entered   = j.get("EnteredCurrentStatus")
    elapsed   = _elapsed(int(entered)) if entered else "?"
    qdate     = j.get("QDate")
    queued_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(qdate))) if qdate else "?"
    host      = str(j.get("RemoteHost", "—") or "—")
    cpus      = str(j.get("RequestCpus", "?"))
    mem       = str(j.get("RequestMemory", "?"))
    disk      = str(j.get("RequestDisk", "?"))
    starts    = str(j.get("NumJobStarts", 0))
    hold      = str(j.get("HoldReason", "") or "")

    console.print(f"  Cluster       : [bold]{int(j.get('ClusterId', 0))}.{int(j.get('ProcId', 0))}[/bold]")
    console.print(f"  Executable    : {cmd}")
    console.print(f"  Status        : [{style}]{label}[/{style}]  ({elapsed} in state)")
    console.print(f"  Queued at     : {queued_at}")
    console.print(f"  Execute host  : {host}")
    console.print(f"  Resources     : {cpus} CPU  {mem} MB RAM  {disk} KB disk")
    console.print(f"  Job starts    : {starts}")
    if hold:
        console.print(f"  Hold reason   : [bold red]{hold}[/bold red]")


def _fmt_ts(ts) -> str:
    """Format a unix timestamp as a human-readable string, or '—' if missing."""
    if ts is None:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except (ValueError, TypeError):
        return "—"


def _duration(start_ts, end_ts) -> str:
    """Return a human-readable duration between two unix timestamps."""
    if start_ts is None or end_ts is None:
        return "—"
    try:
        return _elapsed(int(start_ts)) if end_ts == start_ts else _elapsed_between(int(start_ts), int(end_ts))
    except (ValueError, TypeError):
        return "—"


def _elapsed_between(start: int, end: int) -> str:
    seconds = max(0, end - start)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d:
        return f"{d}d {h:02}h {m:02}m"
    if h:
        return f"{h}h {m:02}m {s:02}s"
    return f"{m}m {s:02}s"


def report_job(cfg: Config, cluster_id: int) -> None:
    """Print a metadata report panel for a single job cluster."""
    j = _query_job(cfg, cluster_id)
    if j is None:
        console.print(f"[yellow]Cluster {cluster_id} not found in queue.[/yellow]")
        return

    status_id = int(j.get("JobStatus", 0))
    label     = _STATUS_LABEL.get(status_id, str(status_id))
    style     = _STATUS_STYLE.get(status_id, "")
    cmd       = Path(str(j.get("Cmd", "?"))).name

    qdate      = j.get("QDate")
    start_date = j.get("JobStartDate") or j.get("JobCurrentStartDate")
    comp_date  = j.get("CompletionDate")
    entered    = j.get("EnteredCurrentStatus")

    # Run duration: completed → CompletionDate - JobStartDate
    #               running   → now - JobCurrentStartDate
    #               not yet   → —
    now = int(time.time())
    if start_date and comp_date:
        run_duration = _elapsed_between(int(start_date), int(comp_date))
    elif start_date and status_id == _RUNNING:
        run_duration = _elapsed_between(int(start_date), now) + "  (ongoing)"
    else:
        run_duration = "—"

    queue_wait = (
        _elapsed_between(int(qdate), int(start_date))
        if qdate and start_date else "—"
    )

    transfer_input = str(j.get("TransferInput", "") or "")
    input_data = _data_inputs(transfer_input) or "—"

    host   = str(j.get("RemoteHost", "—") or "—")
    cpus   = str(j.get("RequestCpus", "?"))
    mem    = str(j.get("RequestMemory", "?"))
    disk   = str(j.get("RequestDisk", "?"))
    starts = int(j.get("NumJobStarts", 0))
    hold   = str(j.get("HoldReason", "") or "")

    rows = [
        ("Job",            f"[bold]{cluster_id}.{int(j.get('ProcId', 0))}[/bold]"),
        ("Status",         f"[{style}]{label}[/{style}]"),
        ("Executable",     cmd),
        ("Input data",     input_data),
        ("",               ""),
        ("Submitted",      _fmt_ts(qdate)),
        ("Started",        _fmt_ts(start_date)),
        ("Completed",      _fmt_ts(comp_date)),
        ("Queue wait",     queue_wait),
        ("Run duration",   f"[bold]{run_duration}[/bold]"),
        ("",               ""),
        ("Execute host",   host),
        ("CPUs",           cpus),
        ("Memory",         f"{mem} MB"),
        ("Disk",           f"{disk} KB"),
        ("Job starts",     str(starts)),
    ]
    if hold:
        rows.append(("Hold reason", f"[bold red]{hold}[/bold red]"))

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=14)
    grid.add_column()
    for key, val in rows:
        grid.add_row(key, val)

    console.print(Panel(grid, title=f"Job Report  {cluster_id}", expand=False))


def follow_log(
    cfg: Config,
    cluster_id: int,
    prefix: Optional[str] = None,
    poll_interval: int = 10,
) -> None:
    """
    Show job info, wait for the job to leave Idle, then tail .out/.err over SSH.

    Automatically finds log files by cluster ID — no prefix needed.
    Ctrl-C to stop.
    """
    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = ["-i", cfg.remote.ssh_key, "-o", "StrictHostKeyChecking=no"]
    proj = cfg.remote.project_dir
    logs_dir = f"{proj}/logs"

    # --- Job info header ---
    console.print("")
    j = _query_job(cfg, cluster_id)
    if j is None:
        console.print(f"[yellow]Cluster {cluster_id} not found in queue (may have already completed).[/yellow]")
    else:
        _print_job_info(j)
        status_id = int(j.get("JobStatus", 0))

        # --- Wait out Idle ---
        if status_id == _IDLE:
            console.print(f"\n[yellow]Job is Idle — waiting for it to start before tailing logs ...[/yellow]")
            try:
                while True:
                    time.sleep(poll_interval)
                    j = _query_job(cfg, cluster_id)
                    if j is None:
                        console.print("[dim]Job left the queue.[/dim]")
                        return
                    status_id = int(j.get("JobStatus", 0))
                    label = _STATUS_LABEL.get(status_id, str(status_id))
                    style = _STATUS_STYLE.get(status_id, "")
                    entered = j.get("EnteredCurrentStatus")
                    elapsed = _elapsed(int(entered)) if entered else "?"
                    console.print(f"  [{style}]{label}[/{style}]  {elapsed} in state ...")
                    if status_id != _IDLE:
                        break
            except KeyboardInterrupt:
                console.print("[dim]Stopped.[/dim]")
                return

        console.print("")
        # Re-print updated info now that it's running
        if status_id != _IDLE:
            _print_job_info(j)

    # --- Tail logs ---
    console.print(f"\n[dim]Tailing *{cluster_id}*.out/.err in {logs_dir}/ — Ctrl-C to stop[/dim]\n")

    if prefix is not None:
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
    else:
        full_cmd = (
            f"files=$(ls {logs_dir}/*{cluster_id}*.out {logs_dir}/*{cluster_id}*.err 2>/dev/null);"
            f" if [ -z \"$files\" ]; then"
            f"   echo 'ERROR: no log files matching *{cluster_id}* found in {logs_dir}/';"
            f" else"
            f"   echo \"Tailing: $files\";"
            f"   tail -f $files 2>&1;"
            f" fi"
        )

    proc = None
    try:
        proc = subprocess.Popen(
            ["ssh", *ssh_opts, ssh_target, full_cmd],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            console.print(line, end="")
    except KeyboardInterrupt:
        console.print("[dim]Stopped.[/dim]")
    finally:
        if proc is not None:
            proc.terminate()
