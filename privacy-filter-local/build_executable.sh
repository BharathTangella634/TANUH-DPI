#!/bin/bash
# ============================================================================
# build_executable.sh -- Build a single-file executable for pf-redact
#
# This script works on Linux, macOS, and Windows (via Git Bash / MSYS2).
# It uses PyInstaller to create a self-contained executable.
#
# Usage:
#   chmod +x build_executable.sh
#   ./build_executable.sh
#
# Output:
#   dist/pf-redact         (Linux/macOS)
#   dist/pf-redact.exe     (Windows)
#
# Requirements:
#   - Python 3.10+
#   - pip
#   - tesseract-ocr (runtime dependency)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

echo "============================================"
echo "  Building pf-redact executable"
echo "  Platform: $(uname -s) $(uname -m)"
echo "============================================"
echo ""

# ── Step 1: Create virtual environment ─────────────────────────────────────
echo "[1/4] Creating build environment..."
BUILD_VENV="${SCRIPT_DIR}/build_venv"
rm -rf "${BUILD_VENV}"
python3 -m venv "${BUILD_VENV}"

# Activate venv (cross-platform)
if [ -f "${BUILD_VENV}/bin/activate" ]; then
    source "${BUILD_VENV}/bin/activate"
elif [ -f "${BUILD_VENV}/Scripts/activate" ]; then
    source "${BUILD_VENV}/Scripts/activate"
fi

# ── Step 2: Install dependencies ──────────────────────────────────────────
echo "[2/4] Installing dependencies..."
echo "       (This may take 5-10 minutes on first run)"

pip install --quiet --upgrade pip setuptools wheel

# Install CPU-only PyTorch (keeps executable small)
pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu

# Install pf-local and all its dependencies
pip install --quiet "${SCRIPT_DIR}"

# Install PyInstaller
pip install --quiet pyinstaller

echo "       Dependencies installed."

# ── Step 3: Build with PyInstaller ─────────────────────────────────────────
echo "[3/4] Building executable with PyInstaller..."
echo "       This may take 5-10 minutes..."

pyinstaller \
    --clean \
    --noconfirm \
    "${SCRIPT_DIR}/pf-redact.spec"

echo "       Build complete."

# ── Step 4: Verify ────────────────────────────────────────────────────────
echo "[4/4] Verifying..."

EXECUTABLE="${SCRIPT_DIR}/dist/pf-redact"
if [ "$(uname -s)" = "MINGW"* ] || [ "$(uname -s)" = "MSYS"* ] || [ -n "${OS:-}" ]; then
    EXECUTABLE="${EXECUTABLE}.exe"
fi

if [ -f "${EXECUTABLE}" ]; then
    SIZE=$(du -sh "${EXECUTABLE}" | cut -f1)
    echo ""
    echo "============================================"
    echo "  BUILD COMPLETE!"
    echo "============================================"
    echo ""
    echo "  Output: ${EXECUTABLE}"
    echo "  Size:   ${SIZE}"
    echo ""
    echo "  Test it:"
    echo "    ${EXECUTABLE} --version"
    echo "    ${EXECUTABLE} check"
    echo ""
else
    echo ""
    echo "  BUILD FAILED -- executable not found at ${EXECUTABLE}"
    exit 1
fi

deactivate 2>/dev/null || true
