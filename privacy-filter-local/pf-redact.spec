# -*- mode: python ; coding: utf-8 -*-
# ============================================================================
# pf-redact.spec -- PyInstaller spec file for pf-redact (Privacy Filter CLI)
#
# Builds a single-file executable that bundles:
#   - Python runtime
#   - All pip dependencies (transformers, torch, pytesseract, etc.)
#   - pf-local source code (exact same pipeline as DPI website)
#   - CLI entry point
#
# Usage (run on the TARGET OS):
#   pip install pyinstaller
#   pip install torch --index-url https://download.pytorch.org/whl/cpu
#   pip install .
#   pyinstaller pf-redact.spec
#
# Output:
#   dist/pf-redact       (Linux/Mac)
#   dist/pf-redact.exe   (Windows)
# ============================================================================

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Hidden imports ──────────────────────────────────────────────────────────
# These packages use dynamic imports that PyInstaller can't detect statically
hidden_imports = [
    # pf_local submodules
    'pf_local.cli',
    'pf_local.model',
    'pf_local.ner_model',
    'pf_local.rule_detectors',
    'pf_local.redactor',
    'pf_local.extractors',
    'pf_local.extractors.txt',
    'pf_local.extractors.pdf',
    'pf_local.extractors.docx',
    'pf_local.extractors.image',
    'pf_local.extractors.dicom',
    # Transformers (heavy dynamic imports)
    *collect_submodules('transformers'),
    # Torch core (need most of it for model inference)
    'torch',
    'torch.nn',
    'torch.nn.functional',
    'torch.utils',
    'torch.utils.data',
    # safetensors (used by newer transformers for model loading)
    'safetensors',
    'safetensors.torch',
    # Other dependencies
    'click',
    'PIL',
    'pytesseract',
    'fitz',
    'docx',
    'pydicom',
    'numpy',
    'json',
    'logging',
]

# ── Collect data files from key packages ────────────────────────────────────
extra_datas = []

transformers_datas = collect_data_files('transformers')
extra_datas.extend(transformers_datas)

# ── Analysis ────────────────────────────────────────────────────────────────
a = Analysis(
    ['src/pf_local/cli.py'],
    pathex=['src'],
    binaries=[],
    datas=extra_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude CUDA/GPU packages to keep size small
        'nvidia',
        'triton',
        # torchvision is not needed (we only do text NER, not vision tasks)
        # and causes conflicts if the user has a different version installed
        'torchvision',
        'torchaudio',
        # Exclude unnecessary stdlib
        'tkinter',
        'turtle',
        'idlelib',
        'test',
        'unittest',
    ],
    noarchive=False,
)

# ── Build ───────────────────────────────────────────────────────────────────
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pf-redact',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
