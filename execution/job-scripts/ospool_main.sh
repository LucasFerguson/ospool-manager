#!/usr/bin/env bash
# OSPool-adapted Patchwork orchestrator.
# Replaces dashboard/frontend/main.sh for HTCondor execute nodes.
# See patchwork/OSPOOL_CHANGES.md for full change log.
# set -euo pipefail

JOB_DIR=$PWD
PW_PATH="${JOB_DIR}/analysis"

_log() { echo "[$(date '+%H:%M:%S')] $*"; }
_dir_snapshot() {
  local label=$1 dir=$2
  _log "--- ${label}: ${dir}"
  if [ -d "${dir}" ]; then
    ls -lh "${dir}" 2>&1 | sed 's/^/    /'
  else
    echo "    (directory does not exist)"
  fi
}

_log "=== Patchwork OSPool job starting ==="
_log "JOB_DIR=${JOB_DIR}  HOST=$(hostname)  OS=$(uname -r)"
_dir_snapshot "transferred files" "${JOB_DIR}"

# --- Unpack analysis bundle ---------------------------------------------------
if [ -f "${JOB_DIR}/analysis.tar.gz" ]; then
  _log "=== unpacking analysis.tar.gz ==="
  tar xzf "${JOB_DIR}/analysis.tar.gz" -C "${JOB_DIR}"
  _log "  OK: analysis/ unpacked"
  # Show the graphing script checksum so we can confirm the right version landed
  if [ -f "${PW_PATH}/graphing/framesizes_across_sites.py" ]; then
    _log "  framesizes_across_sites.py md5: $(md5sum "${PW_PATH}/graphing/framesizes_across_sites.py" | awk '{print $1}')"
  fi
elif [ ! -d "${PW_PATH}" ]; then
  echo "ERROR: neither analysis.tar.gz nor analysis/ found in ${JOB_DIR}" >&2
  exit 1
fi

# --- Create venv and install Python packages ----------------------------------
VENV="${JOB_DIR}/venv"
export PYTHONWARNINGS="ignore::SyntaxWarning"
_log "=== creating venv ==="
python3 -m venv "${VENV}"
_log "=== pip install matplotlib numpy ==="
if "${VENV}/bin/pip" install --quiet matplotlib numpy 2>&1; then
  _log "  OK: matplotlib and numpy installed"
else
  _log "  WARNING: pip install failed — graphing steps will likely fail"
fi
PYTHON="${VENV}/bin/python3"
PATCHWORK_DATA_PATH="${JOB_DIR}/patchwork_data"
mkdir -p "${PATCHWORK_DATA_PATH}"

# --- Verify tshark is available (digest.py requires it) ----------------------
_log "=== tshark check ==="
if command -v tshark >/dev/null 2>&1; then
  _log "  tshark: $(tshark --version 2>&1 | head -1)"
  # Smoke test: does tshark produce Frame lines on a real pcap?
  SAMPLE_PCAP=$(find "${JOB_DIR}" -name "*.tar.gz" | grep -v analysis | head -1)
  _log "  (full tshark smoke test will run after site archive is unpacked)"
else
  _log "  WARNING: tshark not found — digest.py will fail to parse pcap files"
fi

# --- Find the site archive (e.g. INDI.tar.gz, LOSA.tar.gz, MAX.tar.gz) -------
SITE_ARCHIVE=$(ls "${JOB_DIR}"/*.tar.gz 2>/dev/null \
  | grep -v 'analysis\.tar\.gz' \
  | head -1 || true)

if [ -z "${SITE_ARCHIVE}" ]; then
  echo "ERROR: No site .tar.gz found in ${JOB_DIR}" >&2
  exit 1
fi

SITE=$(basename "${SITE_ARCHIVE}" .tar.gz)
_log "SITE=${SITE}  SITE_ARCHIVE=${SITE_ARCHIVE}  SIZE=$(du -sh "${SITE_ARCHIVE}" | cut -f1)"

# --- Unpack the site archive --------------------------------------------------
_log "=== unpacking site archive ==="
tar xzf "${SITE_ARCHIVE}" -C "${JOB_DIR}"
SITE_PATH="${JOB_DIR}/${SITE}"
_dir_snapshot "site archive contents" "${SITE_PATH}"

# --- Generate patchwork config ------------------------------------------------
cat > "${JOB_DIR}/ospool_patchwork_config.sh" <<PWCFG
#!/bin/bash
set -e
PATCHWORK_PATH=${PW_PATH}
PATCHWORK_DATA_PATH=${PATCHWORK_DATA_PATH}
N=1
PATCHWORK_JOB_SCALING=1
PWCFG
export PATCHWORK_CONFIG="${JOB_DIR}/ospool_patchwork_config.sh"
_log "PATCHWORK_CONFIG=${PATCHWORK_CONFIG}"

# --- Unpack nested tgz archives (process_structure1.sh) ----------------------
_log "=== running process_structure1.sh ==="
bash "${PW_PATH}/process_structure1.sh" "${SITE_PATH}"
cd "${JOB_DIR}"

_log "=== patchwork_data after process_structure1 ==="
find "${PATCHWORK_DATA_PATH}" | head -40 | sed 's/^/    /'
_log "  pcap count: $(find "${PATCHWORK_DATA_PATH}" -name '*.pcap' | wc -l)"

# --- tshark smoke test on the actual pcap before digest runs -----------------
FIRST_PCAP=$(find "${PATCHWORK_DATA_PATH}" -name "*.pcap" | head -1)
if [ -n "${FIRST_PCAP}" ]; then
  _log "=== tshark smoke test on ${FIRST_PCAP} ==="
  # Show first 5 lines of tshark -V output so we can see Frame line format
  tshark -V -r "${FIRST_PCAP}" 2>/dev/null | grep -vE '^ ' | head -10 | sed 's/^/    /'
  # Count how many Frame lines match the regex digest.py expects
  FRAME_LINES=$(tshark -V -r "${FIRST_PCAP}" 2>/dev/null | grep -vE '^ ' | grep -cE '^Frame [0-9]+: [0-9]+ bytes' || true)
  _log "  Frame lines matching digest.py regex: ${FRAME_LINES}"
fi

# --- Run digest jobs ----------------------------------------------------------
_log "=== running run.sh ==="
"${PW_PATH}/run.sh" "${SITE_PATH}"

# --- Wait for parallel digest jobs to finish ----------------------------------
_log "Waiting for analyses to terminate."
SLEEPINTERVAL=5
CHECK_CMD="ps ax | grep run_job_ | grep -v grep | wc -l"
CHECK_RUNS=0
sleep "${SLEEPINTERVAL}"
while [ "0" != "$(eval "${CHECK_CMD}")" ]; do
  CHECK_RUNS=$((CHECK_RUNS + 1))
  _log "  Analyses ongoing: $(eval "${CHECK_CMD}"). CHECK_RUNS=${CHECK_RUNS}."
  sleep "${SLEEPINTERVAL}"
done
_log "Analysis terminated. CHECK_RUNS=${CHECK_RUNS}"

# --- Inspect dbfiles before post-processing -----------------------------------
_log "=== dbfile inspection ==="
DBFILES=$(find "${PATCHWORK_DATA_PATH}" -name "dbfile_*" | tr '\n' ' ')
_log "  dbfiles found: $(echo "${DBFILES}" | wc -w)"
for DB in ${DBFILES}; do
  _log "  ${DB}: $(du -sh "${DB}" | cut -f1)"
  "${PYTHON}" - "${DB}" <<'PYEOF' 2>&1 | sed 's/^/    /'
import sys, pickle

with open(sys.argv[1], 'rb') as f:
    d = pickle.load(f)

# Count entries and check for Size: entries
total_ts = 0
total_stacks = 0
size_entries = 0
sample_stack = None

for loc in d:
    for node in d[loc]:
        for iface in d[loc][node]:
            for ts in d[loc][node][iface]:
                total_ts += 1
                for run in d[loc][node][iface][ts]:
                    stacks = d[loc][node][iface][ts][run]
                    total_stacks += len(stacks)
                    for stack in stacks:
                        if sample_stack is None:
                            sample_stack = stack
                        for layer in stack:
                            if layer.startswith("Size:"):
                                size_entries += 1

print(f"locations={list(d.keys())}")
print(f"total_timestamps={total_ts}  total_stacks={total_stacks}  size_entries={size_entries}")
if sample_stack is not None:
    print(f"sample stack ({len(sample_stack)} layers): {sample_stack[:8]}")
else:
    print("WARNING: no stacks found in dbfile")
PYEOF
done

# Show run.log/run.err from each DEST_PATH to diagnose digest failures
for RUNLOG in "${PATCHWORK_DATA_PATH}"/*/run.log; do
  [ -f "${RUNLOG}" ] || continue
  _log "  run.log ($(dirname "${RUNLOG}" | xargs basename)):"
  cat "${RUNLOG}" | tail -20 | sed 's/^/    /'
done
for RUNERR in "${PATCHWORK_DATA_PATH}"/*/run.err; do
  [ -f "${RUNERR}" ] && [ -s "${RUNERR}" ] || continue
  _log "  run.err ($(dirname "${RUNERR}" | xargs basename)):"
  cat "${RUNERR}" | tail -20 | sed 's/^/    /'
done

# --- Post-processing and graphing ---------------------------------------------
_log "=== post-processing ==="
"${PYTHON}" "${PW_PATH}/analyse.py" db_index ${DBFILES}
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_sizehisto.py"  answer_framesizes db_index
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_protodiverse.py" answer_protocols db_index
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_framesizes  answer_framesizes_P2
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_protocols   answer_protocols_P2
"${PYTHON}" "${PW_PATH}/graphing/framesizes_across_sites.py"  answer_framesizes
"${PYTHON}" "${PW_PATH}/graphing/protocol_diversity.py"       answer_protocols answer_protocols_popularity
"${PYTHON}" "${PW_PATH}/graphing/protocol_popularity.py"      answer_protocols_popularity

_log "=== graphs produced: $(find . -maxdepth 1 -name '*.png' | wc -l) png(s) ==="
find . -maxdepth 1 -name "*.png" | sed 's/^/    /'

# --- Bundle all results for transfer back to AP -------------------------------
_log "=== bundling results ==="
tar czf patchwork_results.tar.gz \
  patchwork_data/ \
  db_index \
  answer_framesizes answer_framesizes_P2 \
  answer_protocols  answer_protocols_P2 \
  $(find . -maxdepth 1 -name "*.png" 2>/dev/null | tr '\n' ' ')
_log "  OK: patchwork_results.tar.gz  $(du -sh patchwork_results.tar.gz | cut -f1)"

_log "=== Patchwork OSPool analysis complete ==="
