#!/usr/bin/env bash
# Simple test job — exercises the same infrastructure as ospool_main.sh
# without running the full Patchwork analysis.
# Checks: container env, Python venv install, OSDF file transfer, output bundle.
set -euo pipefail

JOB_DIR=$PWD
echo "=== test_job.sh start ==="
echo "JOB_DIR=${JOB_DIR}"
echo "Hostname: $(hostname)"
echo "Date    : $(date)"
echo "OS      : $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME || uname -a)"

# --- List transferred files --------------------------------------------------
echo ""
echo "=== transferred files ==="
ls -lh "${JOB_DIR}/"

# --- Check for pcap ----------------------------------------------------------
echo ""
echo "=== pcap check ==="
PCAP_FILE=$(ls "${JOB_DIR}"/*.pcap 2>/dev/null | head -1 || true)
if [ -z "${PCAP_FILE}" ]; then
  echo "ERROR: No .pcap file found in ${JOB_DIR}" >&2
  exit 1
fi
echo "Found pcap : ${PCAP_FILE}"
echo "Size       : $(ls -lh "${PCAP_FILE}" | awk '{print $5}')"

# --- Python venv -------------------------------------------------------------
echo ""
echo "=== python venv ==="
VENV="${JOB_DIR}/venv"
python3 -m venv "${VENV}"
echo "venv created at ${VENV}"

echo "Installing numpy ..."
if "${VENV}/bin/pip" install --quiet numpy 2>&1; then
  echo "  OK: numpy installed"
else
  echo "  ERROR: pip install failed" >&2
  exit 1
fi

PYTHON="${VENV}/bin/python3"
"${PYTHON}" -c "import numpy; print('numpy version:', numpy.__version__)"

# --- Minimal Python smoke test -----------------------------------------------
echo ""
echo "=== python smoke test ==="
"${PYTHON}" - <<'PYEOF'
import struct, os, sys

pcap_file = next(
    (f for f in os.listdir(".") if f.endswith(".pcap")),
    None
)
if pcap_file is None:
    print("ERROR: no pcap found from Python", file=sys.stderr)
    sys.exit(1)

with open(pcap_file, "rb") as f:
    magic = struct.unpack("<I", f.read(4))[0]

if magic in (0xa1b2c3d4, 0xd4c3b2a1):
    print(f"  OK: {pcap_file} is a valid pcap (magic=0x{magic:08x})")
elif magic in (0x0a0d0d0a,):
    print(f"  OK: {pcap_file} is a pcapng (magic=0x{magic:08x})")
else:
    print(f"  WARNING: unexpected magic 0x{magic:08x} in {pcap_file}")
PYEOF

# --- Bundle output -----------------------------------------------------------
echo ""
echo "=== bundling test_results.tar.gz ==="
echo "test_job completed successfully at $(date)" > test_summary.txt
echo "pcap: ${PCAP_FILE}" >> test_summary.txt
tar czf test_results.tar.gz test_summary.txt
echo "  OK: test_results.tar.gz created"

echo ""
echo "=== test_job.sh complete ==="
