"""
Background job watcher.

watch_and_fetch() polls the schedd for all pending tracked runs.
When a job transitions to Done it automatically fetches its outputs
and marks the run record as fetched. Runs until all pending jobs are
fetched or Ctrl-C.

Run in the background with:
  ospool watch &
  nohup ospool watch > runs/watch.log 2>&1 &
"""
from __future__ import annotations
import time
from datetime import datetime

import htcondor2 as htcondor
from rich.console import Console
from rich.table import Table

from .config import Config
from . import fetch as fetch_mod
from . import runs as runs_mod

console = Console()

_JOB_STATUS = {1: "Idle", 2: "Running", 3: "Removed", 4: "Done", 5: "Held", 6: "Transferring"}
_DONE = 4
_REMOVED = 3
_HELD = 5


def _schedd(cfg: Config) -> htcondor.Schedd:
    collector = htcondor.Collector(cfg.remote.collector_host)
    ad = collector.locate(htcondor.DaemonType.Schedd, cfg.remote.schedd_host)
    return htcondor.Schedd(ad)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def watch_and_fetch(cfg: Config, interval: int = 15) -> None:
    """
    Poll all pending tracked runs. Auto-fetch when Done. Ctrl-C to stop.
    """
    pending = runs_mod.pending_runs(cfg)
    if not pending:
        console.print("[dim]No pending runs to watch. Submit a job first.[/dim]")
        return

    console.print(f"Watching {len(pending)} job(s). Polling every {interval}s. Ctrl-C to stop.\n")

    schedd = _schedd(cfg)
    watching = {r["cluster_id"]: r for r in pending}

    try:
        while True:
            # Pick up any jobs submitted since the watcher started
            for r in runs_mod.pending_runs(cfg):
                if r["cluster_id"] not in watching:
                    console.print(f"[dim][{_now()}] Picked up new job: cluster {r['cluster_id']}[/dim]")
                    watching[r["cluster_id"]] = r

            if not watching:
                break
            # Query status for all watched clusters
            ids = " || ".join(f"ClusterId == {cid}" for cid in watching)
            constraint = f'Owner == "{cfg.remote.username}" && ({ids})'
            try:
                jobs = schedd.query(
                    constraint=constraint,
                    projection=["ClusterId", "JobStatus", "HoldReason"],
                )
            except Exception as exc:
                console.print(f"[red][{_now()}] Query error: {exc}[/red]")
                time.sleep(interval)
                continue

            # Map cluster → status from live query
            live = {int(j["ClusterId"]): int(j["JobStatus"]) for j in jobs}

            # Print status table
            table = Table(show_header=True, header_style="bold")
            table.add_column("Cluster")
            table.add_column("Sub file")
            table.add_column("Status")

            for cid, run in list(watching.items()):
                status_id = live.get(cid)

                if status_id is None:
                    # Not in queue — assume done (already completed and left queue)
                    status_label = "Done (left queue)"
                    runs_mod.update_status(cfg, cid, "done")
                    status_id = _DONE
                else:
                    label = _JOB_STATUS.get(status_id, str(status_id))
                    runs_mod.update_status(cfg, cid, label.lower())
                    status_label = label

                table.add_row(str(cid), run["sub_file"], status_label)

                if status_id in (_DONE,):
                    console.print(f"[green][{_now()}] Cluster {cid} done — fetching outputs ...[/green]")
                    try:
                        dest = fetch_mod.fetch_outputs(cfg, cid)
                        runs_mod.update_status(cfg, cid, "fetched", fetched=True)
                        console.print(f"[green][{_now()}] Fetched → {dest}[/green]")
                    except Exception as exc:
                        console.print(f"[red][{_now()}] Fetch failed for {cid}: {exc}[/red]")
                        runs_mod.update_status(cfg, cid, "failed")
                    del watching[cid]

                elif status_id in (_REMOVED, _HELD):
                    console.print(f"[yellow][{_now()}] Cluster {cid} is {status_label} — skipping.[/yellow]")
                    runs_mod.update_status(cfg, cid, "failed")
                    del watching[cid]

            console.print(table)

            if watching:
                console.print(f"[dim][{_now()}] {len(watching)} job(s) still pending. Next poll in {interval}s ...[/dim]\n")
                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Watcher stopped.[/dim]")

    remaining = len(watching)
    if remaining == 0:
        console.print("[green]All watched jobs fetched.[/green]")
    else:
        console.print(f"[yellow]{remaining} job(s) still pending (watcher stopped).[/yellow]")
