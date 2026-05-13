#!/usr/bin/env bash
# Build a self-contained ospool binary using PyInstaller.
# Run this on a Linux x86_64 machine (Ubuntu 20.04+ / glibc >= 2.28).
#
# Usage:
#   bash build-binary.sh           # builds dist/ospool
#   bash build-binary.sh --clean   # wipe build/ dist/ first

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ "${1:-}" == "--clean" ]]; then
  echo "=== Cleaning build/ and dist/ ==="
  rm -rf build/ dist/
fi

echo "=== Installing build dependencies ==="
pip install --quiet pyinstaller

echo "=== Ensuring ospool-manager is installed ==="
pip install --quiet -e .

echo "=== Running PyInstaller ==="
pyinstaller ospool.spec --noconfirm

echo ""
echo "=== Build complete ==="
ls -lh dist/ospool
echo ""
echo "Test it:"
echo "  ./dist/ospool --help"
echo ""
echo "Copy to target machine:"
echo "  scp dist/ospool user@host:~/bin/ospool"
