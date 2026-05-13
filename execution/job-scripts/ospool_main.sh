#!/usr/bin/env bash
# OSPool-adapted Patchwork orchestrator.
# Replaces dashboard/frontend/main.sh for HTCondor execute nodes.
# See patchwork/OSPOOL_CHANGES.md for full change log.
# set -euo pipefail

JOB_DIR=$PWD
PW_PATH="${JOB_DIR}/analysis"

# --- Unpack analysis bundle ---------------------------------------------------
# HTCondor on OSPool doesn't reliably transfer directories recursively,
# so we tar analysis/ before transfer and untar here.
if [ -f "${JOB_DIR}/analysis.tar.gz" ]; then
  echo "=== unpacking analysis.tar.gz ==="
  tar xzf "${JOB_DIR}/analysis.tar.gz" -C "${JOB_DIR}"
  echo "  OK: analysis/ unpacked"
elif [ ! -d "${PW_PATH}" ]; then
  echo "ERROR: neither analysis.tar.gz nor analysis/ found in ${JOB_DIR}" >&2
  exit 1
fi

# --- Create venv and install Python packages ----------------------------------
VENV="${JOB_DIR}/venv"
export PYTHONWARNINGS="ignore::SyntaxWarning"
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
mkdir -p "${PATCHWORK_DATA_PATH}"

# --- Find the site archive (e.g. INDI.tar.gz, LOSA.tar.gz, MAX.tar.gz) -------
# Any .tar.gz that is not analysis.tar.gz is treated as the site archive.
SITE_ARCHIVE=$(ls "${JOB_DIR}"/*.tar.gz 2>/dev/null \
  | grep -v 'analysis\.tar\.gz' \
  | head -1 || true)

if [ -z "${SITE_ARCHIVE}" ]; then
  echo "ERROR: No site .tar.gz found in ${JOB_DIR}" >&2
  echo "  Expected something like INDI.tar.gz, LOSA.tar.gz, or MAX.tar.gz" >&2
  exit 1
fi

SITE=$(basename "${SITE_ARCHIVE}" .tar.gz)
echo "SITE=${SITE}"
echo "SITE_ARCHIVE=${SITE_ARCHIVE}"

# --- Unpack the site archive --------------------------------------------------
# Produces: JOB_DIR/SITE/all_packet_traces_*/SITE_node0_packet_trace.tgz
echo "=== unpacking site archive ==="
tar xzf "${SITE_ARCHIVE}" -C "${JOB_DIR}"
SITE_PATH="${JOB_DIR}/${SITE}"
echo "SITE_PATH=${SITE_PATH}"

# --- Generate a per-job patchwork config with correct absolute paths ----------
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

# --- Unpack nested tgz archives into DEST_PATH --------------------------------
# process_structure1.sh:
#   1. Finds all_packet_traces_*.tgz in SITE_PATH → unpacks to DEST_PATH
#   2. Finds *node*.tgz in DEST_PATH → unpacks to SITE_nodeN_packet_trace/
# After this, DEST_PATH contains the full nested path that digest.py expects:
#   DEST_PATH/all_packet_traces_.../SITE_nodeN_packet_trace/
#     packet_trace/UPLINK/pcap_MM_DD_YYYY_HH:MM:SS/NAME-RUN.pcap
echo "=== running process_structure1.sh ==="
bash "${PW_PATH}/process_structure1.sh" "${SITE_PATH}"
cd "${JOB_DIR}"  # process_structure1.sh may cd around; reset to job dir

# --- Run digest jobs ----------------------------------------------------------
"${PW_PATH}/run.sh" "${SITE_PATH}"

# --- Wait for parallel digest jobs to finish ----------------------------------
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

# --- Post-processing and graphing ---------------------------------------------
DBFILES=$(find "${PATCHWORK_DATA_PATH}" -name "dbfile_*" | tr '\n' ' ')
"${PYTHON}" "${PW_PATH}/analyse.py" db_index ${DBFILES}
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_sizehisto.py"  answer_framesizes db_index
"${PYTHON}" "${PW_PATH}/analyses/analyse_to_protodiverse.py" answer_protocols db_index
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_framesizes  answer_framesizes_P2
"${PYTHON}" "${PW_PATH}/graphing/convert_dump.py" answer_protocols   answer_protocols_P2
"${PYTHON}" "${PW_PATH}/graphing/framesizes_across_sites.py"  answer_framesizes
"${PYTHON}" "${PW_PATH}/graphing/protocol_diversity.py"       answer_protocols answer_protocols_popularity
"${PYTHON}" "${PW_PATH}/graphing/protocol_popularity.py"      answer_protocols_popularity

# --- Bundle all results for transfer back to AP -------------------------------
echo "=== bundling results ==="
tar czf patchwork_results.tar.gz \
  patchwork_data/ \
  db_index \
  answer_framesizes answer_framesizes_P2 \
  answer_protocols  answer_protocols_P2 \
  $(find . -maxdepth 1 -name "*.png" 2>/dev/null | tr '\n' ' ')
echo "  OK: patchwork_results.tar.gz created"

echo "=== Patchwork OSPool analysis complete ==="
