"""
Phase 1: stage local data to OSDF.

Wraps the logic currently in deploy_osdf_data.sh. Will use osdf-client or
direct HTTP PUT once the venv and workflow are finalized.
"""
from pathlib import Path

from .config import Config


def stage_data(cfg: Config, source: Path) -> None:
    """Stage a local file or directory to OSDF."""
    raise NotImplementedError("stage not yet implemented")
