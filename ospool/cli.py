from __future__ import annotations
import os
import typer
from pathlib import Path
from typing import Annotated, Optional
from datetime import datetime, timezone

from . import config as cfg_module
from . import token, submit, monitor as monitor_mod, fetch, remote as remote_mod, upload as upload_mod, runs as runs_mod, watcher as watcher_mod, osdf as osdf_mod

app = typer.Typer(
    name="ospool",
    help="Manage OSPool/HTCondor workflows from a local machine or the AP.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

submit_app = typer.Typer(help="Submit jobs or DAG workflows.", no_args_is_help=True)
app.add_typer(submit_app, name="submit", rich_help_panel="Jobs")

setup_app = typer.Typer(help="Setup and sync the remote Access Point.", no_args_is_help=True)
app.add_typer(setup_app, name="setup", rich_help_panel="System & Setup")


def _cfg(config: Optional[Path]) -> cfg_module.Config:
    return cfg_module.load(config)


def _resolve_sub(path: Path, cfg: cfg_module.Config) -> Path:
    """
    Resolve a submit file path. If the given path doesn't exist, try
    execution/submit-files/<name> and execution/submit-files/<name>.sub
    before giving up.
    """
    if path.exists():
        return path
    candidates = [
        cfg.local.execution_dir / "submit-files" / path.name,
        cfg.local.execution_dir / "submit-files" / (path.name + ".sub"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise typer.BadParameter(
        f"Submit file not found: {path}\n"
        f"Also tried: {candidates[0]}, {candidates[1]}"
    )


# ---------------------------------------------------------------------------
# System & Setup
# ---------------------------------------------------------------------------

@app.command(rich_help_panel="System & Setup")
def whereami(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Print current environment: local vs AP, paths, submit mode."""
    c = _cfg(config)
    remote_mod.whereami(c)


@app.command(rich_help_panel="System & Setup")
def ssh(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Open an interactive SSH session to the Access Point."""
    c = _cfg(config)
    target = f"{c.remote.username}@{c.remote.access_point}"
    typer.echo(f"Connecting to {target} ...")
    os.execvp("ssh", ["ssh", "-i", c.remote.ssh_key, "-o", "StrictHostKeyChecking=no", target])


@app.command("token-fetch", rich_help_panel="System & Setup")
def token_fetch(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Fetch or refresh the HTCondor auth token."""
    token.fetch()
    typer.echo("Token fetched.")


@setup_app.command("remote")
def setup_remote(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """SSH to the AP and create the project directory tree (run once)."""
    c = _cfg(config)
    typer.echo(f"Setting up {c.remote.project_dir} on {c.remote.access_point} ...")
    remote_mod.setup_remote(c)
    typer.echo("Done.")


@app.command("sync", rich_help_panel="System & Setup")
def sync_remote(
    include_data: Annotated[bool, typer.Option("--data", help="Also sync the local data/ directory.")] = False,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """rsync the local project to the AP."""
    c = _cfg(config)
    typer.echo(f"Syncing to {c.remote.username}@{c.remote.access_point}:{c.remote.project_dir}/ ...")
    remote_mod.sync_remote(c, include_data=include_data)
    typer.echo("Sync complete.")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@app.command("ls", rich_help_panel="Data")
def osdf_ls(
    path: Annotated[Optional[str], typer.Argument(
        help="Directory to list. Relative paths are joined onto your OSDF root. "
             "Absolute paths and osdf:// URLs are used as-is. "
             "Defaults to your OSDF large-storage root."
    )] = None,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """List contents of your OSDF large-storage directory (or any OSDF path)."""
    c = _cfg(config)
    osdf_mod.list_dir(c, path)


@app.command(rich_help_panel="Data")
def upload(
    source: Annotated[Optional[Path], typer.Argument(help="File or directory to upload (default: data/).")] = None,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Upload data/ (or a specific path) to OSDF large storage."""
    c = _cfg(config)
    dest = upload_mod.upload(c, source)
    label = str(source) if source else "data/"
    typer.echo(f"Uploaded {label} → {dest}")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _print_submit_summary(cluster_id: int, sub_file: str, kind: str = "job") -> None:
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    typer.echo(f"")
    typer.echo(f"  Submitted {kind}  : cluster {cluster_id}")
    typer.echo(f"  Submit file      : {sub_file}")
    typer.echo(f"  Submitted at     : {local_time}")
    typer.echo(f"")
    typer.echo(f"  Monitor live         : ospool monitor {cluster_id}")
    typer.echo(f"  Tail logs            : ospool logs {cluster_id}")
    typer.echo(f"  Auto-fetch when done : ospool watch")
    typer.echo(f"")


@submit_app.command("job")
def submit_job(
    sub_file: Annotated[Path, typer.Argument(help="Path to .sub file (name only also works).")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Tail logs after submitting.")] = False,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Submit a single HTCondor job."""
    c = _cfg(config)
    sub_file = _resolve_sub(sub_file, c)
    cluster_id = submit.submit_job(c, sub_file)
    runs_mod.save(c, cluster_id, str(sub_file))
    _print_submit_summary(cluster_id, str(sub_file))
    if follow:
        monitor_mod.follow_log(c, cluster_id)


@submit_app.command("dag")
def submit_dag(
    dag_file: Annotated[Path, typer.Argument(help="Path to .dag file.")],
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Submit a DAGMan workflow."""
    c = _cfg(config)
    dag_file = _resolve_sub(dag_file, c)
    cluster_id = submit.submit_dag(c, dag_file)
    runs_mod.save(c, cluster_id, str(dag_file))
    _print_submit_summary(cluster_id, str(dag_file), kind="DAG")


@app.command(rich_help_panel="Jobs")
def monitor(
    cluster_id: Annotated[Optional[int], typer.Argument(help="Cluster ID to watch (omit for all yours).")] = None,
    interval: Annotated[int, typer.Option("--interval", "-i", help="Poll interval in seconds.")] = 5,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Live job status table. Ctrl-C to stop."""
    c = _cfg(config)
    monitor_mod.watch(c, cluster_id, interval)


@app.command(rich_help_panel="Jobs")
def report(
    cluster_ids: Annotated[Optional[list[int]], typer.Argument(help="Cluster ID(s) to report on.")] = None,
    last: Annotated[Optional[int], typer.Option("--last", "-n", help="Report on the N most recent jobs.")] = None,
    csv_out: Annotated[bool, typer.Option("--csv", help="Output as CSV instead of rich panels.")] = False,
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Write CSV to this file (implies --csv).")] = None,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Show job metadata report: timing, duration, resources.

    Examples:

      ospool report 14798972              # single job panel
      ospool report 14798972 14798971     # multiple panels
      ospool report --last 10 --csv       # CSV of last 10 jobs
      ospool report --last 20 --out jobs.csv
      ospool report 14798972 --csv        # specific job as CSV
    """
    c = _cfg(config)
    if out is not None:
        csv_out = True

    if csv_out or last is not None:
        ids = list(cluster_ids) if cluster_ids else None
        monitor_mod.report_jobs_csv(c, cluster_ids=ids, last=last, out=out)
    elif cluster_ids:
        for cid in cluster_ids:
            monitor_mod.report_job(c, cid)
    else:
        typer.echo("Provide cluster ID(s), or use --last N [--csv].", err=True)
        raise typer.Exit(1)


@app.command("logs", rich_help_panel="Jobs")
def follow_logs(
    cluster_id: Annotated[int, typer.Argument(help="Cluster ID to follow.")],
    prefix: Annotated[Optional[str], typer.Option("--prefix", "-p", help="Log filename prefix.")] = None,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Show job info then tail .out/.err from the AP. Waits if job is still Idle."""
    c = _cfg(config)
    monitor_mod.follow_log(c, cluster_id, prefix)


@app.command(rich_help_panel="Jobs")
def watch(
    interval: Annotated[int, typer.Option("--interval", "-i", help="Poll interval in seconds.")] = 15,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Watch all pending jobs and auto-fetch outputs when they complete. Ctrl-C to stop."""
    c = _cfg(config)
    watcher_mod.watch_and_fetch(c, interval)


@app.command(rich_help_panel="Jobs")
def runs(
    days: Annotated[int, typer.Option("--days", "-d", help="Show runs from the last N days.")] = 30,
    all_runs: Annotated[bool, typer.Option("--all", "-a", help="Show all runs regardless of age.")] = False,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """List tracked job runs and their status. Defaults to last 30 days."""
    from rich.console import Console
    from rich.table import Table

    c = _cfg(config)
    records = runs_mod.list_runs(c, days=None if all_runs else days)

    if not records:
        typer.echo("No runs tracked yet.")
        return

    table = Table(title=f"Tracked Runs (last {days} days)" if not all_runs else "All Tracked Runs")
    table.add_column("Cluster", style="bold")
    table.add_column("Status")
    table.add_column("Sub file")
    table.add_column("Submitted")
    table.add_column("Fetched")

    for r in records:
        submitted = r.get("submitted_at", "")[:19].replace("T", " ")
        fetched = (r.get("fetched_at") or "")[:19].replace("T", " ")
        status = r.get("status", "?")
        style = {"fetched": "dim green", "failed": "red", "submitted": "yellow", "running": "green"}.get(status, "")
        table.add_row(
            str(r["cluster_id"]),
            f"[{style}]{status}[/{style}]" if style else status,
            r.get("sub_file", ""),
            submitted,
            fetched,
        )

    Console().print(table)


@app.command(rich_help_panel="Jobs")
def rm(
    cluster_ids: Annotated[list[int], typer.Argument(help="Cluster ID(s) to remove.")],
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Remove (kill) one or more job clusters."""
    c = _cfg(config)
    for cluster_id in cluster_ids:
        affected = submit.remove(c, cluster_id)
        typer.echo(f"Removed cluster {cluster_id} ({affected} job(s))")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@app.command("fetch", rich_help_panel="Outputs")
def fetch_cmd(
    cluster_id: Annotated[Optional[int], typer.Argument(help="Cluster ID to fetch (omit to fetch all).")] = None,
    spool: Annotated[bool, typer.Option("--spool", "-s", help="Retrieve from schedd spool instead of OSDF. Use when output was not remapped to OSDF.")] = False,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Fetch job outputs + logs from OSDF to local outputs/. Omit cluster ID to fetch everything."""
    c = _cfg(config)
    if spool:
        if cluster_id is None:
            typer.echo("ERROR: --spool requires a cluster ID.", err=True)
            raise typer.Exit(1)
        dest = fetch.retrieve_spool(c, cluster_id)
    elif cluster_id is None:
        dest = fetch.fetch_all(c)
    else:
        dest = fetch.fetch_outputs(c, cluster_id)
    typer.echo(f"Outputs saved to {dest}")
