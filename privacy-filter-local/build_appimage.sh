#!/bin/bash
# ============================================================================
# build_appimage.sh -- Build an AppImage for pf-redact (Privacy Filter CLI)
#
# This script creates a self-contained AppImage that bundles:
#   - Python 3.10 runtime
#   - All pip dependencies (transformers, torch, pytesseract, etc.)
#   - pf-local source code (exact same pipeline as the DPI website)
#   - CLI entry point
#
# Usage:
#   chmod +x build_appimage.sh
#   ./build_appimage.sh
#
# Output:
#   pf-redact-1.0.0-x86_64.AppImage
#
# Requirements:
#   - Linux x86_64
#   - Python 3.10+
#   - pip
#   - wget
#   - fuse (for appimagetool)
#   - tesseract-ocr (runtime dependency for OCR)
# ============================================================================

set -euo pipefail

APP_NAME="pf-redact"
APP_VERSION="1.0.0"
ARCH="x86_64"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/appimage_build"
APPDIR="${BUILD_DIR}/${APP_NAME}.AppDir"

echo "============================================"
echo "  Building ${APP_NAME} AppImage v${APP_VERSION}"
echo "============================================"
echo ""

# ── Step 0: Clean previous build ────────────────────────────────────────────
echo "[0/6] Cleaning previous build..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# ── Step 1: Download appimagetool ───────────────────────────────────────────
APPIMAGETOOL="${BUILD_DIR}/appimagetool"
if [ ! -f "${APPIMAGETOOL}" ]; then
    echo "[1/6] Downloading appimagetool..."
    wget -q -O "${APPIMAGETOOL}" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "${APPIMAGETOOL}"
else
    echo "[1/6] appimagetool already present."
fi

# ── Step 2: Create AppDir structure ─────────────────────────────────────────
echo "[2/6] Creating AppDir structure..."
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/lib/python3/site-packages"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/scalable/apps"

# ── Step 3: Create virtual environment and install dependencies ─────────────
echo "[3/6] Creating Python environment and installing dependencies..."
echo "       (This may take 5-10 minutes on first run)"

VENV_DIR="${BUILD_DIR}/venv"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

pip install --quiet --upgrade pip setuptools wheel
pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
pip install --quiet "${SCRIPT_DIR}"

echo "       Dependencies installed."

# ── Step 4: Bundle Python + packages into AppDir ────────────────────────────
echo "[4/6] Bundling Python runtime and packages..."

# Copy Python interpreter
PYTHON_BIN="$(which python3)"
PYTHON_REAL="$(readlink -f "${PYTHON_BIN}")"
cp "${PYTHON_REAL}" "${APPDIR}/usr/bin/python3"

# Copy Python standard library
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_LIB="$(python3 -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"

mkdir -p "${APPDIR}/usr/lib/python${PYTHON_VERSION}"
echo "       Copying standard library from ${PYTHON_LIB}..."

rsync -a --quiet \
    --exclude='test/' \
    --exclude='tests/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='tkinter/' \
    --exclude='idlelib/' \
    --exclude='turtle*' \
    --exclude='ensurepip/' \
    --exclude='distutils/' \
    "${PYTHON_LIB}/" "${APPDIR}/usr/lib/python${PYTHON_VERSION}/"

# Copy lib-dynload (compiled C modules like _ssl, _hashlib, etc.)
DYNLOAD="$(python3 -c 'import sysconfig; print(sysconfig.get_path("platstdlib"))')/lib-dynload"
if [ -d "${DYNLOAD}" ]; then
    mkdir -p "${APPDIR}/usr/lib/python${PYTHON_VERSION}/lib-dynload"
    cp -a "${DYNLOAD}"/*.so "${APPDIR}/usr/lib/python${PYTHON_VERSION}/lib-dynload/" 2>/dev/null || true
fi

# Copy site-packages (all installed pip packages)
SITE_PACKAGES="$(python3 -c 'import site; print(site.getsitepackages()[0])')"
echo "       Copying site-packages from ${SITE_PACKAGES}..."
rsync -a --quiet \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='pip/' \
    --exclude='pip-*' \
    --exclude='setuptools/' \
    --exclude='setuptools-*' \
    --exclude='wheel/' \
    --exclude='wheel-*' \
    --exclude='_distutils_hack/' \
    --exclude='pkg_resources/' \
    --exclude='nvidia/' \
    --exclude='nvidia-*' \
    --exclude='triton/' \
    --exclude='triton-*' \
    --exclude='torchvision/' \
    --exclude='torchvision-*' \
    --exclude='torchaudio/' \
    --exclude='torchaudio-*' \
    --exclude='torch/test/' \
    "${SITE_PACKAGES}/" "${APPDIR}/usr/lib/python3/site-packages/"

# Copy shared libraries that Python extensions need
echo "       Copying shared libraries..."
mkdir -p "${APPDIR}/usr/lib/x86_64-linux-gnu"

for so_file in $(find "${APPDIR}" -name "*.so" -type f 2>/dev/null); do
    ldd "${so_file}" 2>/dev/null | grep "=> /" | awk '{print $3}' | while read dep; do
        dep_name="$(basename "${dep}")"
        case "${dep_name}" in
            libc.so*|libm.so*|libpthread.so*|libdl.so*|librt.so*|ld-linux*|libgcc_s*)
                continue ;;
        esac
        if [ ! -f "${APPDIR}/usr/lib/x86_64-linux-gnu/${dep_name}" ]; then
            cp -L "${dep}" "${APPDIR}/usr/lib/x86_64-linux-gnu/" 2>/dev/null || true
        fi
    done || true
done

# ── Step 5: Copy AppImage metadata ─────────────────────────────────────────
echo "[5/6] Adding AppImage metadata..."

# AppRun (entry point)
cp "${SCRIPT_DIR}/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

# Desktop file
cp "${SCRIPT_DIR}/appimage/pf-redact.desktop" "${APPDIR}/${APP_NAME}.desktop"
cp "${SCRIPT_DIR}/appimage/pf-redact.desktop" "${APPDIR}/usr/share/applications/"

# Icon (SVG + generate PNG for compatibility)
cp "${SCRIPT_DIR}/appimage/pf-redact.svg" "${APPDIR}/${APP_NAME}.svg"
cp "${SCRIPT_DIR}/appimage/pf-redact.svg" "${APPDIR}/usr/share/icons/hicolor/scalable/apps/"

# Generate a PNG icon from SVG using Python Pillow (always available since it's a dependency)
python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (220, 38, 38, 255))
draw = ImageDraw.Draw(img)
draw.text((80, 80), 'PII', fill=(255,255,255))
draw.text((60, 140), 'REDACT', fill=(252,165,165))
img.save('${APPDIR}/${APP_NAME}.png')
" 2>/dev/null || touch "${APPDIR}/${APP_NAME}.png"

deactivate

# ── Step 6: Build the AppImage ──────────────────────────────────────────────
echo "[6/6] Building AppImage..."
echo ""

OUTPUT_FILE="${SCRIPT_DIR}/${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage"

export ARCH="${ARCH}"
APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" "${APPDIR}" "${OUTPUT_FILE}" 2>&1 | tail -5

echo ""
echo "============================================"
echo "  BUILD COMPLETE!"
echo "============================================"
echo ""
echo "  Output: ${OUTPUT_FILE}"
echo "  Size:   $(du -sh "${OUTPUT_FILE}" | cut -f1)"
echo ""
echo "  Test it:"
echo "    chmod +x ${OUTPUT_FILE}"
echo "    ./${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage check"
echo "    ./${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage redact scan.png -o redacted.png"
echo ""
