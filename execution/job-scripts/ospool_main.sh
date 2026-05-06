#!/usr/bin/env bash
# OSPool-adapted Patchwork orchestrator.
# Replaces dashboard/frontend/main.sh for HTCondor execute nodes.
# See patchwork/OSPOOL_CHANGES.md for full change log.
# set -euo pipefail

JOB_DIR=$PWD
PW_PATH="${JOB_DIR}/analysis"

# --- Unpack analysis bundle -----------------------------------------------
# HTCondor on OSPool doesn't reliably transfer directories recursively,
# so run_ospool_patchwork.sh tars analysis/ before rsync and we untar here.
if [ -f "${JOB_DIR}/analysis.tar.gz" ]; then
  echo "=== unpacking analysis.tar.gz ==="
  tar xzf "${JOB_DIR}/analysis.tar.gz" -C "${JOB_DIR}"
  echo "  OK: analysis/ unpacked"
elif [ ! -d "${PW_PATH}" ]; then
  echo "ERROR: neither analysis.tar.gz nor analysis/ found in ${JOB_DIR}" >&2
  exit 1
fi

# --- Create venv and install Python packages ------------------------------
# Alpine Linux (netshoot) uses PEP 668 — system pip is blocked.
# We create a job-local venv so installs are isolated and reliable.
VENV="${JOB_DIR}/venv"
echo "=== creating venv ==="
python3 -m venv "${VENV}"
echo "=== pip install matplotlib numpy ==="
if "${VENV}/bin/pip" install --quiet matplotlib numpy 2>&1; then
  echo "  OK: matplotlib and numpy installed"
else
  echo "  WARNING: pip install failed — graphing steps will likely fail" >&2
fi
PYTHON="${VENV}/bin/python3"
PATCHWORK_DATA_PATH="${JOB_DIR}/patchwork_data"
PROCESSING_TEMP_DIR="${JOB_DIR}/temp"

# --- Locate the transferred pcap -----------------------------------------
PCAP_FILE=$(ls "${JOB_DIR}"/*.pcap 2>/dev/null | head -1 || true)
if [ -z "${PCAP_FILE}" ]; then
  echo "ERROR: No .pcap file found in ${JOB_DIR}" >&2
  exit 1
fi
SITE=$(basename "${PCAP_FILE}" .pcap)
echo "SITE=${SITE}"
echo "PCAP_FILE=${PCAP_FILE}"

# --- Prepare directories --------------------------------------------------
[ -d "${PROCESSING_TEMP_DIR}" ] && rm -rf "${PROCESSING_TEMP_DIR}"
mkdir -p "${PATCHWORK_DATA_PATH}" "${PROCESSING_TEMP_DIR}/${SITE}"

# --- Generate a per-job patchwork config with correct absolute paths ------
# (Bypasses the hardcoded /home/ubuntu/ paths in the original patchwork_config.sh)
cat > "${JOB_DIR}/ospool_patchwork_config.sh" <<PWCFG
#!/bin/bash
set -e
PATCHWORK_PATH=${PW_PATH}
PATCHWORK_DATA_PATH=${PATCHWORK_DATA_PATH}
N=1
PATCHWORK_JOB_SCALING=1
PWCFG
export PATCHWORK_CONFIG="${JOB_DIR}/ospool_patchwork_config.sh"
echo "PATCHWORK_CONFIG=${PATCHWORK_CONFIG}"

# --- Stage pcap into DEST_PATH --------------------------------------------
# Bypasses process_structure1.sh (which unpacks .tgz archives we don't have).
# We mirror the MD5-based path that process_structure1.sh and run.sh share.
SITE_PATH="${PROCESSING_TEMP_DIR}/${SITE}"
PATH_CODE=$(echo "${SITE_PATH}" | md5sum | awk '{ print $1 }')
DEST_PATH="${PATCHWORK_DATA_PATH}/${PATH_CODE}"
mkdir -p "${DEST_PATH}"
echo "PATH_OF_SAMPLE=${SITE_PATH}" > "${DEST_PATH}/origin"
echo "${DEST_PATH}" >> "${PATCHWORK_DATA_PATH}/index"
cp "${PCAP_FILE}" "${DEST_PATH}/"
echo "DEST_PATH=${DEST_PATH}"

# --- Run digest jobs ------------------------------------------------------
"${PW_PATH}/run.sh" "${SITE_PATH}"

# --- Wait for parallel digest jobs to finish ------------------------------
echo "Waiting for analyses to terminate."
SLEEPINTERVAL=5
CHECK_CMD="ps ax | grep run_job_ | grep -v grep | wc -l"
CHECK_RUNS=0
sleep "${SLEEPINTERVAL}"
while [ "0" != "$(eval "${CHECK_CMD}")" ]; do
  CHECK_RUNS=$((CHECK_RUNS + 1))
  echo "  Analyses ongoing: $(eval "${CHECK_CMD}"). CHECK_RUNS=${CHECK_RUNS}."
  sleep "${SLEEPINTERVAL}"
done
echo "Analysis terminated. CHECK_RUNS=${CHECK_RUNS}"

# --- Post-processing and graphing -----------------------------------------
DBFILES=$(find "${DEST_PATH}" -name "dbfile_*" | tr '\n' ' ')
"${PYTHON}" "${PW_PATH}/analyse.py" db_index ${DBFILES}
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_sizehisto.py"  answer_framesizes db_index
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_protodiverse.py" answer_protocols db_index
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_framesizes  answer_framesizes_P2
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_protocols   answer_protocols_P2
"${PYTHON}" "${PW_PATH}/graphing/framesizes_across_sites.py"  answer_framesizes
"${PYTHON}" "${PW_PATH}/graphing/protocol_diversity.py"       answer_protocols answer_protocols_popularity
"${PYTHON}" "${PW_PATH}/graphing/protocol_popularity.py"      answer_protocols_popularity

# --- Bundle all results for transfer back to AP ---------------------------
echo "=== bundling results ==="
tar czf patchwork_results.tar.gz \
  patchwork_data/ \
  db_index \
  answer_framesizes answer_framesizes_P2 \
  answer_protocols  answer_protocols_P2 \
  $(find . -maxdepth 1 -name "*.png" 2>/dev/null | tr '\n' ' ')
echo "  OK: patchwork_results.tar.gz created"

echo "=== Patchwork OSPool analysis complete ==="
