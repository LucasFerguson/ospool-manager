import typer
from pathlib import Path
from typing import Annotated

from . import config as cfg_module
from datetime import datetime, timezone

from . import token, submit, monitor as monitor_mod, fetch, remote as remote_mod, upload as upload_mod, runs as runs_mod, watcher as watcher_mod

app = typer.Typer(
    name="ospool",
    help="Manage OSPool/HTCondor workflows from a local machine or the AP.",
    no_args_is_help=True,
)

submit_app = typer.Typer(help="Submit jobs or DAG workflows.", no_args_is_help=True)
app.add_typer(submit_app, name="submit")

setup_app = typer.Typer(help="Setup and sync the remote Access Point.", no_args_is_help=True)
app.add_typer(setup_app, name="setup")


def _cfg(config: Path | None) -> cfg_module.Config:
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
# ospool token
# ---------------------------------------------------------------------------

@app.command("token-fetch")
def token_fetch(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Fetch or refresh the HTCondor auth token."""
    token.fetch()
    typer.echo("Token fetched.")


# ---------------------------------------------------------------------------
# ospool upload
# ---------------------------------------------------------------------------

@app.command()
def upload(
    source: Annotated[Path | None, typer.Argument(help="File or directory to upload (default: data/).")] = None,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Upload data/ (or a specific path) to OSDF. Reference in jobs as osdf:///ospool/ap40/data/<user>/..."""
    c = _cfg(config)
    dest = upload_mod.upload(c, source)
    label = str(source) if source else "data/"
    typer.echo(f"Uploaded {label} → {dest}")


# ---------------------------------------------------------------------------
# ospool setup remote / ospool sync remote
# ---------------------------------------------------------------------------

@setup_app.command("remote")
def setup_remote(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """SSH to the AP and create the project directory tree."""
    c = _cfg(config)
    typer.echo(f"Setting up {c.remote.project_dir} on {c.remote.access_point} ...")
    remote_mod.setup_remote(c)
    typer.echo("Done.")


@app.command("sync")
def sync_remote(
    include_data: Annotated[bool, typer.Option("--data", help="Also sync the local data/ directory.")] = False,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """rsync the local project to the AP (excludes logs/, outputs/, runs/, data/ by default)."""
    c = _cfg(config)
    typer.echo(f"Syncing to {c.remote.username}@{c.remote.access_point}:{c.remote.project_dir}/ ...")
    remote_mod.sync_remote(c, include_data=include_data)
    typer.echo("Sync complete.")


# ---------------------------------------------------------------------------
# ospool whereami
# ---------------------------------------------------------------------------

@app.command()
def whereami(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Print current execution environment (local vs AP, paths, submit mode)."""
    c = _cfg(config)
    remote_mod.whereami(c)


# ---------------------------------------------------------------------------
# ospool submit job / dag
# ---------------------------------------------------------------------------

def _print_submit_summary(cluster_id: int, sub_file: str, kind: str = "job") -> None:
    now = datetime.now(timezone.utc)
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    typer.echo(f"")
    typer.echo(f"  Submitted {kind}  : cluster {cluster_id}")
    typer.echo(f"  Submit file      : {sub_file}")
    typer.echo(f"  Submitted at     : {local_time}")
    typer.echo(f"")
    typer.echo(f"  Monitor live     : ospool monitor {cluster_id}")
    typer.echo(f"  Tail logs        : ospool logs {cluster_id}")
    typer.echo(f"  Auto-fetch when done : ospool watch")
    typer.echo(f"")


@submit_app.command("job")
def submit_job(
    sub_file: Annotated[Path, typer.Argument(help="Path to .sub file.")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Tail logs after submitting.")] = False,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
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
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Submit a DAGMan workflow."""
    c = _cfg(config)
    dag_file = _resolve_sub(dag_file, c)
    cluster_id = submit.submit_dag(c, dag_file)
    runs_mod.save(c, cluster_id, str(dag_file))
    _print_submit_summary(cluster_id, str(dag_file), kind="DAG")


# ---------------------------------------------------------------------------
# ospool monitor
# ---------------------------------------------------------------------------

@app.command()
def monitor(
    cluster_id: Annotated[int | None, typer.Argument(help="Cluster ID to watch (omit for all).")] = None,
    interval: Annotated[int, typer.Option("--interval", "-i", help="Poll interval in seconds.")] = 5,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Watch job status live via schedd.query(). Ctrl-C to stop."""
    c = _cfg(config)
    monitor_mod.watch(c, cluster_id, interval)


@app.command("logs")
def follow_logs(
    cluster_id: Annotated[int, typer.Argument(help="Cluster ID to follow logs for.")],
    prefix: Annotated[str | None, typer.Option("--prefix", "-p", help="Log filename prefix (default: patchwork).")] = None,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Tail a job's .out and .err from the AP over SSH. Ctrl-C to stop."""
    c = _cfg(config)
    monitor_mod.follow_log(c, cluster_id, prefix)


# ---------------------------------------------------------------------------
# ospool rm
# ---------------------------------------------------------------------------

@app.command()
def rm(
    cluster_ids: Annotated[list[int], typer.Argument(help="Cluster ID(s) to remove.")],
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Remove (kill) one or more job clusters."""
    c = _cfg(config)
    for cluster_id in cluster_ids:
        affected = submit.remove(c, cluster_id)
        typer.echo(f"Removed cluster {cluster_id} ({affected} job(s))")


# ---------------------------------------------------------------------------
# ospool fetch
# ---------------------------------------------------------------------------

@app.command("fetch")
def fetch_cmd(
    cluster_id: Annotated[int | None, typer.Argument(help="Cluster ID to fetch (omit to fetch all).")] = None,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Fetch job outputs from OSDF to local outputs/. Omit cluster ID to fetch everything."""
    c = _cfg(config)
    if cluster_id is None:
        dest = fetch.fetch_all(c)
    else:
        dest = fetch.fetch_outputs(c, cluster_id)
    typer.echo(f"Outputs saved to {dest}")


# ---------------------------------------------------------------------------
# ospool watch
# ---------------------------------------------------------------------------

@app.command()
def watch(
    interval: Annotated[int, typer.Option("--interval", "-i", help="Poll interval in seconds.")] = 15,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Watch pending submitted jobs and auto-fetch outputs when they complete. Ctrl-C to stop."""
    c = _cfg(config)
    watcher_mod.watch_and_fetch(c, interval)


# ---------------------------------------------------------------------------
# ospool runs
# ---------------------------------------------------------------------------

@app.command()
def runs(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """List all tracked job runs and their status."""
    from rich.console import Console
    from rich.table import Table

    c = _cfg(config)
    records = runs_mod.list_runs(c)

    if not records:
        typer.echo("No runs tracked yet.")
        return

    table = Table(title="Tracked Runs")
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


# ---------------------------------------------------------------------------
# ospool ssh
# ---------------------------------------------------------------------------

@app.command()
def ssh(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Open an interactive SSH session to the Access Point."""
    import os
    c = _cfg(config)
    target = f"{c.remote.username}@{c.remote.access_point}"
    typer.echo(f"Connecting to {target} ...")
    os.execvp("ssh", ["ssh", "-i", c.remote.ssh_key, "-o", "StrictHostKeyChecking=no", target])
