"""
Token fetch and refresh helpers.

Fetches an HTCondor IDTOKEN from the access point over SSH and stores it
in ~/.condor/tokens.d/<name>. No local daemon needed — just SSH access
to the AP and the htcondor2 Python package.

Usage on the AP side: condor_token_fetch
Token lands at: ~/.condor/tokens.d/<token_name>
"""
import subprocess
from pathlib import Path

from .config import Config

TOKENS_DIR = Path.home() / ".condor" / "tokens.d"


def fetch(cfg: Config, token_name: str = "ospool") -> Path:
    """
    SSH to the access point and fetch a new IDTOKEN.
    Stores it at ~/.condor/tokens.d/<token_name>.
    """
    token_path = TOKENS_DIR / token_name
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ssh",
        f"{cfg.remote.username}@{cfg.remote.schedd_host}",
        "condor_token_fetch",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"condor_token_fetch failed: {result.stderr.strip()}")

    token_path.write_text(result.stdout)
    token_path.chmod(0o600)
    return token_path
