import QtQuick

QtObject {
    property bool dark: false
    readonly property color background: dark ? "#101923" : "#f4f6f8"
    readonly property color surface: dark ? "#182430" : "#ffffff"
    readonly property color sidebar: dark ? "#121e29" : "#edf1f3"
    readonly property color field: dark ? "#111e29" : "#f6f8fa"
    readonly property color text: dark ? "#e8eff4" : "#192c37"
    readonly property color muted: dark ? "#91a4b4" : "#768793"
    readonly property color border: dark ? "#2a3947" : "#e5ebee"
    readonly property color accent: dark ? "#5fd0ba" : "#167d77"
    readonly property color tint: dark ? "#1e3b3a" : "#e6f3ee"
    readonly property color danger: dark ? "#f3a68d" : "#b7553e"
}
