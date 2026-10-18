import QtQuick
import QtQuick.Controls

Rectangle {
    property var theme: ApplicationWindow.window ? ApplicationWindow.window.theme : fallbackTheme
    Theme { id: fallbackTheme }
    color: theme.surface
    border.color: theme.border
    radius: 19
}
