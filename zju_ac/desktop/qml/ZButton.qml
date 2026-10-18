import QtQuick
import QtQuick.Controls

Button {
    id: control
    property var theme: ApplicationWindow.window ? ApplicationWindow.window.theme : fallbackTheme
    Theme { id: fallbackTheme }
    property bool secondary: false
    property bool danger: false
    implicitHeight: 43
    implicitWidth: Math.max(90, label.implicitWidth + 36)
    padding: 16
    hoverEnabled: true
    font.pixelSize: 13
    font.weight: Font.DemiBold
    opacity: enabled ? 1 : 0.45
    contentItem: Text {
        id: label
        text: control.text
        font: control.font
        color: control.secondary ? control.theme.text : (control.theme.dark ? "#102a29" : "white")
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 12
        color: control.secondary ? (control.hovered ? control.theme.border : control.theme.field)
                : control.danger ? control.theme.danger : control.theme.accent
        border.width: control.activeFocus ? 2 : 0
        border.color: control.theme.text
        opacity: control.down ? 0.8 : 1
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
