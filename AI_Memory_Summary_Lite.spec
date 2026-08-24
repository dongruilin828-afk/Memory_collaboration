# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).resolve()
playwright_datas, playwright_binaries, playwright_hidden = collect_all(
    "playwright"
)

release_docs = [
    (str(project_root / "packaging" / "轻量版使用说明.txt"), "."),
    (str(project_root / "packaging" / "轻量版版本信息.txt"), "."),
    (
        str(project_root / "packaging" / "轻量版第三方组件说明.txt"),
        ".",
    ),
]

hidden_imports = sorted(set(
    playwright_hidden
    + [
        "keyring.backends.Windows",
        "jaraco.classes",
        "win32ctypes",
    ]
))

a = Analysis(
    [str(project_root / "gui" / "lite_app.py")],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas + release_docs,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(project_root / "packaging" / "pyi_rth_lite_browser.py")
    ],
    excludes=["pytest", "IPython", "matplotlib", "numpy", "pandas"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI记忆总结工具_轻量版",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AI记忆总结工具_轻量版",
)
