#!/usr/bin/env bash
# Run ospool_main.sh locally for testing without submitting to OSPool.
#
# Creates a self-contained scratch directory that mirrors the HTCondor
# execute-node working directory, copies the required files in, and runs
# ospool_main.sh from there.
#
# Input must be a site archive (SITE.tar.gz) — NOT a bare .pcap.
# The site archive is the two-layer tgz structure produced by the capture
# tool (INDI.tar.gz, LOSA.tar.gz, MAX.tar.gz).
#
# Usage:
#   ./test_local.sh                        # uses first SITE.tar.gz in data/ (not analysis.tar.gz)
#   ./test_local.sh data/INDI.tar.gz       # explicit site archive
#   ./test_local.sh data/INDI.tar.gz --keep  # keep scratch dir on failure too
#
# Output lands in: test_scratch/YYYYMMDD_HHMMSS/
# Notably: patchwork_results.tar.gz, patchwork_data/, any .png graphs

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB_SCRIPTS="${SCRIPT_DIR}/execution/job-scripts"
MAIN_SCRIPT="${JOB_SCRIPTS}/ospool_main.sh"
ANALYSIS_TGZ="${JOB_SCRIPTS}/analysis.tar.gz"

KEEP=0
PCAP_ARG=""

for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    *) PCAP_ARG="$arg" ;;
  esac
done

# --- Locate site archive ------------------------------------------------------
if [ -n "${PCAP_ARG}" ]; then
  SITE_ARCHIVE="$(realpath "${PCAP_ARG}")"
else
  SITE_ARCHIVE="$(ls "${SCRIPT_DIR}/data/"*.tar.gz 2>/dev/null \
    | grep -v 'analysis\.tar\.gz' \
    | head -1 || true)"
fi

if [ -z "${SITE_ARCHIVE}" ] || [ ! -f "${SITE_ARCHIVE}" ]; then
  echo "ERROR: No site archive found." >&2
  echo "  Pass one as argument:  ./test_local.sh data/INDI.tar.gz" >&2
  echo "  Or place a site .tar.gz in: ${SCRIPT_DIR}/data/" >&2
  echo "  (any .tar.gz that is not analysis.tar.gz)" >&2
  exit 1
fi

# --- Locate analysis.tar.gz ---------------------------------------------------
if [ ! -f "${ANALYSIS_TGZ}" ]; then
  echo "ERROR: ${ANALYSIS_TGZ} not found." >&2
  echo "  Build it with: tar czf execution/job-scripts/analysis.tar.gz -C execution/job-scripts analysis/" >&2
  exit 1
fi

# --- Set up scratch dir -------------------------------------------------------
SCRATCH="${SCRIPT_DIR}/test_scratch/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${SCRATCH}"

echo "=============================="
echo " OSPool local test run"
echo "=============================="
echo "  Archive  : ${SITE_ARCHIVE}"
echo "  Scratch  : ${SCRATCH}"
echo "  Script   : ${MAIN_SCRIPT}"
echo "=============================="
echo ""

# --- Stage files (mirrors what HTCondor transfer_input_files delivers) --------
cp "${ANALYSIS_TGZ}"  "${SCRATCH}/"
cp "${SITE_ARCHIVE}"  "${SCRATCH}/"

# --- Run from scratch dir (same as execute-node CWD) --------------------------
cd "${SCRATCH}"
if bash "${MAIN_SCRIPT}"; then
  echo ""
  echo "=============================="
  echo " Done."
  echo "=============================="
  echo ""
  echo "  Results dir : ${SCRATCH}"
  if [ -f "${SCRATCH}/patchwork_results.tar.gz" ]; then
    echo "  Bundle size : $(du -sh "${SCRATCH}/patchwork_results.tar.gz" | cut -f1)"
    echo "  Contents    :"
    tar tzf "${SCRATCH}/patchwork_results.tar.gz" | sed 's/^/    /'
  fi
  if ls "${SCRATCH}"/*.png &>/dev/null; then
    echo ""
    echo "  Graphs      :"
    ls "${SCRATCH}"/*.png | sed 's/^/    /'
  fi
else
  EXIT=$?
  echo ""
  echo "ERROR: ospool_main.sh exited with code ${EXIT}" >&2
  echo "  Scratch dir kept for inspection: ${SCRATCH}" >&2

  # Show any run.log / run.err from inside patchwork_data/ to help diagnose
  for LOG in "${SCRATCH}"/patchwork_data/*/run.log "${SCRATCH}"/patchwork_data/*/run.err; do
    [ -f "${LOG}" ] || continue
    echo ""
    echo "=== ${LOG} ==="
    cat "${LOG}"
  done

  exit ${EXIT}
fi

# Show digest logs even on success — useful for spotting digest issues
echo ""
echo "--- digest logs (patchwork_data/*/run.log) ---"
for LOG in "${SCRATCH}"/patchwork_data/*/run.log; do
  [ -f "${LOG}" ] || continue
  echo "=== ${LOG} ==="
  cat "${LOG}"
done
echo ""
for ERR in "${SCRATCH}"/patchwork_data/*/run.err; do
  [ -f "${ERR}" ] || [ ! -s "${ERR}" ] && continue
  echo "=== ${ERR} ==="
  cat "${ERR}"
done
