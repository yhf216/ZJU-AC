"""Qt Quick application entry; frozen children enter freeze_support before Qt."""

import hashlib
import multiprocessing
import os
import sys
from pathlib import Path


def main() -> int:
    multiprocessing.freeze_support()
    if "--worker-smoke-test" in sys.argv:
        from .worker import smoke_test

        return smoke_test(Path(os.environ["ZJU_AC_SMOKE_DIR"]))
    from .storage import ConfigStore, default_directory

    smoke = "--smoke-test" in sys.argv
    directory = Path(os.environ["ZJU_AC_SMOKE_DIR"]) if smoke else default_directory()
    os.environ["QML_DISK_CACHE_PATH"] = str(directory / "cache/qml")
    from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, QUrl
    from PySide6.QtGui import QAction, QFont, QFontDatabase, QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

    from .bridge import DesktopBridge

    QApplication.setAttribute(Qt.AA_DisableShaderDiskCache)
    app = QApplication([sys.argv[0]])
    if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setApplicationName("ZJU-AC")
    app.setOrganizationName("ZJU-AC")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setQuitOnLastWindowClosed(False)
    QQuickStyle.setStyle("Basic")
    root = Path(__file__).resolve().parent
    icon = QIcon(str(root / "assets/mark.svg"))
    app.setWindowIcon(icon)
    server = None
    if not smoke:
        server_name = "zju-ac-" + hashlib.sha256(str(directory).encode()).hexdigest()[:16]
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if socket.waitForConnected(250):
            socket.write(b"show")
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return 0
        server = QLocalServer(app)
        if not server.listen(server_name):
            QLocalServer.removeServer(server_name)
            if not server.listen(server_name):
                QMessageBox.critical(None, "ZJU-AC", "应用已在运行，或无法创建本地会话。")
                return 1
    try:
        bridge = DesktopBridge(ConfigStore(directory))
    except Exception as exc:
        from ..diagnostics import report_error, setup

        setup(directory / "logs")
        report_error("config_error", exc)
        QMessageBox.critical(
            None,
            "ZJU-AC",
            "无法读写安装目录下的 data 文件夹。"
            "请检查 data/config.toml，或选择有写入权限的安装目录。",
        )
        return 1
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", bridge)
    engine.load(QUrl.fromLocalFile(str(root / "qml/Main.qml")))
    if not engine.rootObjects():
        bridge.shutdown()
        return 1
    window = engine.rootObjects()[0]
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("ZJU-AC")
    menu = QMenu()

    def show_window():
        window.showNormal()
        window.raise_()
        window.requestActivate()

    if server is not None:

        def activate_existing():
            connection = server.nextPendingConnection()
            if connection is not None:
                connection.readyRead.connect(connection.readAll)
                connection.disconnected.connect(connection.deleteLater)
                show_window()

        server.newConnection.connect(activate_existing)

    for label, callback in (
        ("打开窗口", show_window),
        ("暂停监控", bridge.pauseMonitor),
        ("继续监控", bridge.resumeMonitor),
        ("停止监控", bridge.requestQuit),
    ):
        action = QAction(label, menu)
        action.triggered.connect(callback)
        menu.addAction(action)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: show_window() if reason == QSystemTrayIcon.Trigger else None
    )
    bridge.tray_available = QSystemTrayIcon.isSystemTrayAvailable() and not smoke
    if bridge.tray_available:
        tray.show()

    def notify(title, message, outcome):
        level = (
            QSystemTrayIcon.Warning
            if outcome in {"failure", "pending"}
            else QSystemTrayIcon.Information
        )
        tray.showMessage(title, message, level, 8000)

    bridge.notification.connect(notify)
    bridge.hideRequested.connect(window.hide)
    bridge.quitReady.connect(app.quit)
    app.aboutToQuit.connect(bridge.shutdown)
    window.show()
    if smoke:
        bridge._dark = False
        bridge.changed.emit()
        dialog = window.findChild(QObject, "loginDialog")

        def capture_dark():
            window.grabWindow().save(str(directory / "desktop-dark.png"))
            window.setWidth(620)
            window.setHeight(480)
            QTimer.singleShot(300, capture_compact)

        def capture_compact():
            window.grabWindow().save(str(directory / "desktop-compact.png"))
            scroll = window.findChild(QObject, "mainScroll").property("contentItem")
            scroll.setProperty(
                "contentY", max(0, scroll.property("contentHeight") - scroll.height())
            )
            QTimer.singleShot(300, capture_compact_bottom)

        def capture_compact_bottom():
            window.grabWindow().save(str(directory / "desktop-compact-bottom.png"))
            app.quit()

        def capture_login():
            window.grabWindow().save(str(directory / "desktop-login.png"))
            QMetaObject.invokeMethod(dialog, "close")
            bridge.toggleTheme()
            QTimer.singleShot(300, capture_dark)

        def capture_settings():
            window.grabWindow().save(str(directory / "desktop-settings.png"))
            window.setProperty("page", 0)
            QMetaObject.invokeMethod(dialog, "open")
            QTimer.singleShot(300, capture_login)

        def capture():
            window.grabWindow().save(str(directory / "desktop.png"))
            window.setProperty("page", 2)
            QTimer.singleShot(300, capture_settings)

        QTimer.singleShot(800, capture)
    return app.exec()
