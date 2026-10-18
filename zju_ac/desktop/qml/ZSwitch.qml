import QtQuick
import QtQuick.Controls

Switch {
    id: control
    property var theme: ApplicationWindow.window ? ApplicationWindow.window.theme : fallbackTheme
    Theme { id: fallbackTheme }
    implicitWidth: 46
    implicitHeight: 28
    padding: 0
    indicator: Rectangle {
        width: 44; height: 26; radius: 13
        y: (control.height - height) / 2
        color: control.checked ? control.theme.accent : control.theme.border
        border.width: control.activeFocus ? 2 : 0
        border.color: control.theme.muted
        Rectangle {
            width: 20; height: 20; radius: 10; y: 3
            x: control.checked ? 21 : 3
            color: "white"
            Behavior on x { NumberAnimation { duration: 130 } }
        }
    }
    opacity: enabled ? 1 : 0.45
}
