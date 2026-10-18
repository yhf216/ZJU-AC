import QtQuick
import QtQuick.Controls

TextField {
    id: control
    property var theme: ApplicationWindow.window ? ApplicationWindow.window.theme : fallbackTheme
    Theme { id: fallbackTheme }
    implicitHeight: 44
    leftPadding: 14
    rightPadding: 14
    color: theme.text
    placeholderTextColor: theme.muted
    selectionColor: theme.accent
    font.pixelSize: 13
    selectByMouse: true
    background: Rectangle {
        color: control.theme.field
        radius: 11
        border.width: 1
        border.color: control.activeFocus ? control.theme.accent : control.theme.border
    }
}
