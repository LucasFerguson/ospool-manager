from __future__ import annotations
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.9/3.10

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RemoteConfig:
    username: str
    access_point: str
    schedd_host: str
    collector_host: str
    project_dir: str
    ssh_key: Optional[str]  # path to private key, or None to use ssh-agent

    def ssh_opts(self) -> list[str]:
        """
        SSH/rsync options for connecting to the AP.

        If ssh_key is set: use that key explicitly (IdentitiesOnly=yes prevents
        ssh-agent interference).
        If ssh_key is unset/empty: omit -i so ssh-agent / ~/.ssh/id_* are tried.
        """
        base = ["-o", "StrictHostKeyChecking=no"]
        if self.ssh_key:
            return ["-i", self.ssh_key, "-o", "IdentitiesOnly=yes"] + base
        return base

    def ssh_target(self) -> str:
        return f"{self.username}@{self.access_point}"


@dataclass
class OsdfConfig:
    base_path: str


@dataclass
class LocalConfig:
    project_dir: Path
    execution_dir: Path
    data_dir: Path
    logs_dir: Path
    outputs_dir: Path
    runs_dir: Path


@dataclass
class SubmitConfig:
    mode: str  # "spool" or "ap-project"


@dataclass
class Config:
    remote: RemoteConfig
    osdf: OsdfConfig
    local: LocalConfig
    submit: SubmitConfig


def load(config_path: Optional[Path] = None) -> Config:
    path = config_path or Path(__file__).parent.parent / "config.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    r = raw["remote"]
    o = raw["osdf"]
    l = raw["local"]
    s = raw.get("submit", {})

    return Config(
        remote=RemoteConfig(
            username=r["username"],
            access_point=r["access_point"],
            schedd_host=r["schedd_host"],
            collector_host=r["collector_host"],
            project_dir=r["project_dir"],
            ssh_key=str(Path(r["ssh_key"]).expanduser()) if r.get("ssh_key") else None,
        ),
        osdf=OsdfConfig(base_path=o["base_path"]),
        local=LocalConfig(
            project_dir=Path(l["project_dir"]),
            execution_dir=Path(l["execution_dir"]),
            data_dir=Path(l["data_dir"]),
            logs_dir=Path(l["logs_dir"]),
            outputs_dir=Path(l["outputs_dir"]),
            runs_dir=Path(l["runs_dir"]),
        ),
        submit=SubmitConfig(mode=s.get("mode", "spool")),
    )
