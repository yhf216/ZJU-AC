"""Build the Windows portable application using the current Python environment."""

import os
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make_icon(target: Path) -> None:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(ROOT / "zju_ac/desktop/assets/mark.svg"))
    images = []
    for size in (16, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        images.append((size, bytes(data)))
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    for size, data in images:
        header += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    target.write_bytes(header + b"".join(data for _, data in images))


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("请在 Windows 的 Python 3.12 环境中运行。")
    build = ROOT / "build/windows"
    build.mkdir(parents=True, exist_ok=True)
    icon = build / "app.ico"
    make_icon(icon)
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    app_version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    version = tuple(int(part) for part in app_version.split(".")) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=version,
            prodvers=version,
            mask=0x3F,
            flags=0,
            OS=0x40004,
            fileType=1,
            subtype=0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("FileDescription", "ZJU-AC"),
                            StringStruct("ProductName", "ZJU-AC"),
                            StringStruct("FileVersion", app_version),
                            StringStruct("ProductVersion", app_version),
                            StringStruct("OriginalFilename", "ZJU-AC.exe"),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    version_file = build / "version.txt"
    version_file.write_text(str(info), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--noupx",
        "--name",
        "ZJU-AC",
        "--icon",
        str(icon),
        "--version-file",
        str(version_file),
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(build / "work"),
        "--specpath",
        str(build),
        "--paths",
        str(ROOT),
        "--hidden-import",
        "PySide6.QtQuickControls2",
        "--hidden-import",
        "PySide6.QtSvg",
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "pytest",
    ]
    for source, destination in (
        (ROOT / "config.toml", "."),
        (ROOT / "zju_ac/desktop/qml", "zju_ac/desktop/qml"),
        (ROOT / "zju_ac/desktop/assets", "zju_ac/desktop/assets"),
    ):
        command += ["--add-data", f"{source}{os.pathsep}{destination}"]
    command.append(str(ROOT / "scripts/desktop_entry.py"))
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(build / "cache")
    subprocess.run(command, cwd=ROOT, check=True, env=environment)
    folder = ROOT / "dist/ZJU-AC"
    archive = ROOT / "dist/ZJU-AC-win-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(folder.parent))
    print(f"\n构建完成：{folder / 'ZJU-AC.exe'}\n分发文件：{archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
