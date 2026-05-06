"""
Phase 2: submit HTCondor jobs and DAGMan workflows.

Two submit modes (set in config.toml [submit] mode):

  spool        — schedd.submit(spool=True) + schedd.spool().
                 Works from any machine with a valid auth token.
                 Log paths are relative to where the job runs (execute node CWD).

  ap-project   — inject initialdir = <remote.project_dir> into the submit text,
                 then submit normally (no spool).  Requires the project to already
                 be synced to the AP via `ospool sync remote`.
                 Fails with a helpful message if the remote dirs don't exist.

References:
  https://htcondor.readthedocs.io/en/latest/apis/python-bindings/
"""
import subprocess
from pathlib import Path

import htcondor2 as htcondor

from .config import Config


def _schedd(cfg: Config) -> htcondor.Schedd:
    collector = htcondor.Collector(cfg.remote.collector_host)
    schedd_ad = collector.locate(htcondor.DaemonType.Schedd, cfg.remote.schedd_host)
    return htcondor.Schedd(schedd_ad)


def _verify_remote_dirs(cfg: Config) -> None:
    """SSH check that the remote project_dir exists. Raises RuntimeError if not."""
    ssh_opts = ["-i", cfg.remote.ssh_key, "-o", "StrictHostKeyChecking=no"]
    target = f"{cfg.remote.username}@{cfg.remote.access_point}"
    result = subprocess.run(
        ["ssh", *ssh_opts, target, f"test -d {cfg.remote.project_dir}"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Remote project dir {cfg.remote.project_dir!r} not found on {cfg.remote.access_point}.\n"
            "Run:  ospool setup remote  &&  ospool sync remote"
        )


def remove(cfg: Config, cluster_id: int) -> int:
    """Remove (kill) a job cluster. Returns the number of jobs affected."""
    schedd = _schedd(cfg)
    constraint = f'Owner == "{cfg.remote.username}" && ClusterId == {cluster_id}'
    result = schedd.act(htcondor.JobAction.Remove, constraint)
    return int(result.get("TotalSuccess", 0))


def submit_job(cfg: Config, sub_file: Path) -> int:
    """
    Submit a single .sub file.

    spool mode      — transfers input files from local machine, works anywhere.
    ap-project mode — injects initialdir pointing to the synced project on the AP.
    """
    schedd = _schedd(cfg)
    sub_text = sub_file.resolve().read_text()

    if cfg.submit.mode == "ap-project":
        _verify_remote_dirs(cfg)
        sub_text = f"initialdir = {cfg.remote.project_dir}\n{sub_text}"
        sub = htcondor.Submit(sub_text)
        result = schedd.submit(sub)
    else:
        sub = htcondor.Submit(sub_text)
        result = schedd.submit(sub, spool=True)
        schedd.spool(result)

    return result.cluster()


def submit_dag(cfg: Config, dag_file: Path) -> int:
    """
    Submit a DAGMan .dag workflow.

    spool mode      — submit from local path (DAG file must be accessible).
    ap-project mode — set initialdir to remote project_dir so DAGMan resolves
                      relative paths against the synced project on the AP.
    """
    schedd = _schedd(cfg)

    if cfg.submit.mode == "ap-project":
        _verify_remote_dirs(cfg)
        dag_sub = htcondor.Submit.from_dag(str(dag_file))
        dag_sub["initialdir"] = cfg.remote.project_dir
        result = schedd.submit(dag_sub)
    else:
        dag_sub = htcondor.Submit.from_dag(str(dag_file.resolve()))
        result = schedd.submit(dag_sub, spool=True)
        schedd.spool(result)

    return result.cluster()
