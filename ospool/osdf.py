"""
OSDF large-storage utilities.

list_dir() — SSH to the AP and run ls on an OSDF directory, then render the
             result as a Rich table.
"""
from __future__ import annotations
import subprocess
from typing import Optional

from rich.console import Console
from rich.table import Table

from .config import Config

console = Console()


def _osdf_to_ssh(cfg: Config, path: Optional[str] = None) -> str:
    """
    Resolve a target directory as an SSH-accessible path on the AP.

    Rules:
      - No path  → cfg.osdf.base_path (the user's OSDF root)
      - Relative  → appended to cfg.osdf.base_path
      - Absolute  → used as-is (strips osdf:// prefix if present)
    """
    base = cfg.osdf.base_path.replace("osdf://", "")  # /ospool/ap40/data/<user>

    if path is None:
        return base

    # Strip any osdf:// scheme the user may have copied from a .sub file
    clean = path.replace("osdf://", "")

    if clean.startswith("/"):
        return clean  # absolute — use directly

    # Relative — join onto base
    return f"{base}/{clean}"


def list_dir(cfg: Config, path: Optional[str] = None) -> None:
    """
    List an OSDF directory by SSH-ing to the Access Point.

    Parameters
    ----------
    cfg:
        Loaded project config.
    path:
        Directory to list.  Defaults to the OSDF large-storage root
        (``osdf.base_path`` from config.toml).  Accepts:
          - relative subpath   →  joined onto the base path
          - absolute posix path →  used as-is
          - osdf:// URL        →  scheme is stripped, rest used as absolute
    """
    target = _osdf_to_ssh(cfg, path)
    ssh_target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    ssh_opts = ["-i", cfg.remote.ssh_key, "-o", "StrictHostKeyChecking=no", "-o", "IdentitiesOnly=yes"]

    console.print(f"[dim]{ssh_target}:{target}/[/dim]\n")

    result = subprocess.run(
        ["ssh", *ssh_opts, ssh_target, f"ls -la --time-style=long-iso {target} 2>&1"],
        capture_output=True,
        text=True,
    )

    raw = result.stdout.strip()
    if not raw:
        console.print("[yellow]Empty directory or no output returned.[/yellow]")
        return

    lines = raw.splitlines()

    # ls -la output: permissions links owner group size date time name
    # First line is usually "total N" — keep it as a subtitle
    total_line = ""
    entry_lines = []
    for line in lines:
        if line.startswith("total "):
            total_line = line
        else:
            entry_lines.append(line)

    if not entry_lines:
        console.print(raw)
        return

    # Check whether output looks like an error (e.g. "ls: cannot access")
    if entry_lines and entry_lines[0].startswith("ls:"):
        console.print(f"[red]{raw}[/red]")
        return

    table = Table(
        title=f"OSDF  {target}",
        caption=total_line or None,
        expand=False,
    )
    table.add_column("Permissions")
    table.add_column("Links", justify="right")
    table.add_column("Owner")
    table.add_column("Group")
    table.add_column("Size", justify="right")
    table.add_column("Date")
    table.add_column("Time")
    table.add_column("Name")

    for line in entry_lines:
        parts = line.split(None, 7)
        if len(parts) < 8:
            # Fallback: print raw line spanning all columns
            table.add_row(line, "", "", "", "", "", "", "")
            continue

        perms, links, owner, group, size, date, time_, name = parts

        # Style directories and symlinks
        if perms.startswith("d"):
            name_rendered = f"[bold blue]{name}[/bold blue]"
        elif perms.startswith("l"):
            name_rendered = f"[cyan]{name}[/cyan]"
        else:
            name_rendered = name

        table.add_row(perms, links, owner, group, size, date, time_, name_rendered)

    console.print(table)
