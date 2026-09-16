# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - onedir build (faster startup than onefile).

    pyinstaller PriceMatcher.spec --noconfirm
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('config.json', '.'),
    ],
    hiddenimports=[
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
        'pythonnet',
    ],
    hookspath=[],
    runtime_hooks=[],
    # keep the bundle small and the startup fast: these are never used
    excludes=[
        'tkinter', 'unittest', 'pytest', 'pandas', 'numpy', 'matplotlib',
        'scipy', 'IPython', 'notebook', 'PyQt5', 'PySide6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PriceMatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # put an .ico path here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PriceMatcher',
)
