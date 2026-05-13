#!/usr/bin/env bash
set -euo pipefail

docker run --rm -v "$(pwd):/src" -w /src \
  ubuntu:20.04 \
  bash -c "
  export DEBIAN_FRONTEND=noninteractive && \
  apt-get update -q && \
  apt-get install -y \
    python3.9 \
    python3.9-venv \
    python3.9-dev \
    python3.9-distutils \
    libpython3.9 \
    build-essential && \
  python3.9 -m ensurepip --upgrade && \
  python3.9 -m pip install --upgrade pip && \
  python3.9 -m pip install pyinstaller && \
  python3.9 -m pip install . && \
  python3.9 -m PyInstaller ospool.spec --noconfirm
  "

echo "Build complete: dist/ospool"