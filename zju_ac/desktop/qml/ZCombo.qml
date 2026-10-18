import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    property var theme: ApplicationWindow.window ? ApplicationWindow.window.theme : fallbackTheme
    Theme { id: fallbackTheme }
    implicitHeight: 44
    leftPadding: 13; rightPadding: 30
    font.pixelSize: 13
    contentItem: Text {
        textFormat: Text.PlainText
        text: control.displayText
        font: control.font
        color: control.theme.text
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Canvas {
        width: 12; height: 8
        anchors.right: parent.right; anchors.rightMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        onPaint: { let ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = control.theme.muted; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(2, 2); ctx.lineTo(6, 6); ctx.lineTo(10, 2); ctx.stroke() }
        Connections { target: control.theme; function onMutedChanged() { control.indicator.requestPaint() } }
    }
    background: Rectangle {
        color: control.theme.field; radius: 11
        border.color: control.activeFocus ? control.theme.accent : control.theme.border
    }
    delegate: ItemDelegate {
        required property var modelData
        width: control.width
        text: control.textRole ? modelData[control.textRole] : modelData
        contentItem: Text {
            textFormat: Text.PlainText
            text: parent.text; color: control.theme.text
            font.pixelSize: 13; verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle { color: parent.hovered ? control.theme.tint : control.theme.surface }
    }
    popup: Popup {
        y: control.height + 5; width: control.width
        padding: 6
        implicitHeight: Math.min(320, contentItem.implicitHeight + 12)
        background: Rectangle { color: control.theme.surface; radius: 12; border.color: control.theme.border }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }
}
