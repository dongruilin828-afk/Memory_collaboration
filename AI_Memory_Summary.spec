# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).resolve()
playwright_datas, playwright_binaries, playwright_hidden = collect_all(
    "playwright"
)

browser_cache = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
browser_datas = []
for folder_name in ("chromium-1228",):
    source = browser_cache / folder_name
    if not source.exists():
        raise SystemExit(f"缺少 Playwright 打包资源：{source}")
    browser_datas.append(
        (str(source), f"playwright-browsers/{folder_name}")
    )

release_docs = [
    (str(project_root / "packaging" / "使用说明.txt"), "."),
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
    [str(project_root / "gui" / "app.py")],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas + browser_datas + release_docs,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging" / "pyi_rth_playwright.py")],
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
    name="AI记忆总结工具",
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
    name="AI记忆总结工具",
)
