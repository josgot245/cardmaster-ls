# -*- mode: python ; coding: utf-8 -*-
import certifi

# Aktuelles CA-Bundle mit ins Programm packen, damit die Ortssuche auch
# auf Geraeten mit fehlenden/veralteten Windows-Root-Zertifikaten läuft.
_CA_BUNDLE = (certifi.where(), 'certifi')


a = Analysis(
    ['C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/spesenzettel_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/Spesen.pdf', '.'), ('C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/installer/cardmaster.ico', '.'), ('C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/assets', 'assets'), ('C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/ANLEITUNG CardMaster LS.txt', '.'), _CA_BUNDLE],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CardMaster LS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/installer/version.txt',
    icon=['C:/Users/joshu/Documents/Standardprojekt/Fahrerkarte/installer/cardmaster.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CardMaster LS',
)
