import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1220; height: 840
    minimumWidth: 1050; minimumHeight: 720
    title: "ZJU-AC"
    color: theme.background
    font.family: "Microsoft YaHei UI"
    font.pixelSize: 13
    property alias theme: colors
    property int page: 0
    property var draft: ({})
    Theme { id: colors; dark: backend.state.dark }
    onClosing: function(close) { close.accepted = false; backend.closeWindow() }
    Component.onCompleted: draft = Object.assign({}, backend.preferences)
    Connections {
        target: backend
        function onPreferencesChanged() { root.draft = Object.assign({}, backend.preferences) }
        function onPromptChanged() {
            answerField.text = ""
            if (backend.prompt.token) confirmDialog.open()
            else confirmDialog.close()
        }
    }

    Rectangle {
        id: rail
        width: 202; height: parent.height
        color: theme.sidebar
        Rectangle { width: 1; height: parent.height; anchors.right: parent.right; color: theme.border }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 8
            RowLayout {
                Layout.topMargin: 10; spacing: 12
                Image { source: "../assets/mark.svg"; Layout.preferredWidth: 36; Layout.preferredHeight: 36 }
                Text { text: "ZJU-AC"; font.pixelSize: 19; font.weight: Font.Bold; color: theme.text }
            }
            Text { text: "让日常，有条不紊。"; color: theme.muted; font.pixelSize: 11; Layout.topMargin: 8 }
            Text { text: "WORKSPACE"; color: theme.muted; font.pixelSize: 10; font.letterSpacing: 1.5; Layout.topMargin: 46; Layout.bottomMargin: 8 }
            Repeater {
                model: [{name: "概览", number: "01"}, {name: "运行记录", number: "02"}, {name: "偏好设置", number: "03"}]
                delegate: Button {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true; Layout.preferredHeight: 46
                    hoverEnabled: true
                    onClicked: root.page = index
                    background: Rectangle { radius: 12; color: root.page === index ? theme.surface : parent.hovered ? theme.border : "transparent" }
                    contentItem: RowLayout {
                        spacing: 15
                        Text { text: modelData.number; font.pixelSize: 11; color: root.page === index ? theme.accent : theme.muted; Layout.leftMargin: 12 }
                        Text { text: modelData.name; color: root.page === index ? theme.text : theme.muted; font.weight: root.page === index ? Font.DemiBold : Font.Normal }
                        Item { Layout.fillWidth: true }
                        Rectangle { visible: root.page === index; width: 5; height: 5; radius: 3; color: theme.accent; Layout.rightMargin: 10 }
                    }
                }
            }
            Item { Layout.fillHeight: true }
            Rectangle {
                Layout.fillWidth: true; height: 76; radius: 14
                color: theme.dark ? "#193337" : "#e1ebe9"
                Column { anchors.fill: parent; anchors.margins: 14; spacing: 7
                    Row { spacing: 7
                        Rectangle { width: 6; height: 6; radius: 3; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: backend.state.running ? "本次会话进行中" : "等待开始"; color: theme.text; font.pixelSize: 11 }
                    }
                    Text { text: "WINDOWS  ·  v" + backend.state.version; color: theme.muted; font.pixelSize: 10; font.letterSpacing: 0.8 }
                }
            }
        }
    }

    ColumnLayout {
        anchors.left: rail.right; anchors.right: parent.right
        anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.margins: 30; spacing: 20
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout { spacing: 5
                Text { text: ["概览", "运行记录", "偏好设置"][root.page]; color: theme.text; font.pixelSize: 26; font.weight: Font.DemiBold }
                Text { text: backend.state.date + "    /    YOUR DAILY SPACE"; color: theme.muted; font.pixelSize: 10; font.letterSpacing: 0.8 }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                height: 30; width: statusLabel.implicitWidth + 35; radius: 15
                color: theme.tint
                Row { anchors.centerIn: parent; spacing: 7
                    Rectangle { width: 6; height: 6; radius: 3; color: theme.accent; anchors.verticalCenter: parent.verticalCenter }
                    Text { id: statusLabel; text: backend.state.status; color: theme.accent; font.pixelSize: 11 }
                }
            }
            ZButton { text: theme.dark ? "浅色" : "深色"; secondary: true; implicitWidth: 66; onClicked: backend.toggleTheme() }
        }

        ColumnLayout {
            visible: root.page === 0
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 18
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 196; radius: 22; clip: true
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "#173d43" }
                    GradientStop { position: 1; color: "#112832" }
                }
                Canvas {
                    anchors.right: parent.right; width: 300; height: parent.height
                    onPaint: {
                        let ctx = getContext("2d"); ctx.clearRect(0, 0, width, height)
                        ctx.strokeStyle = "#36555d"; ctx.lineWidth = 1
                        for (let r = 40; r <= 170; r += 32) {
                            ctx.beginPath(); ctx.arc(208, 92, r, 0, Math.PI * 2); ctx.stroke()
                        }
                        ctx.fillStyle = "#9bd4b1"; ctx.beginPath(); ctx.arc(208, 20, 5, 0, Math.PI * 2); ctx.fill()
                        ctx.fillStyle = "#4f9e97"; ctx.beginPath(); ctx.arc(102, 142, 7, 0, Math.PI * 2); ctx.fill()
                    }
                    Text { anchors.centerIn: parent; anchors.horizontalCenterOffset: 58; anchors.verticalCenterOffset: -5
                        text: "Z"; font.pixelSize: 64; font.weight: Font.Light; color: "#b7d6d2"; opacity: 0.7
                    }
                }
                ColumnLayout {
                    anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 27; spacing: 11
                    Text { text: "A LITTLE LESS TO THINK ABOUT"; color: "#89b3b4"; font.pixelSize: 10; font.letterSpacing: 1.6 }
                    Text { text: backend.state.running ? "日常，正在有序进行。" : "一切就绪，等你开始。"; color: "#f4faf7"; font.pixelSize: 26; font.weight: Font.DemiBold }
                    Text { text: backend.state.running ? "保持连接，重要的进展会及时通知你。" : "开启本次会话，把注意力留给更重要的事。"; color: "#afc9ca"; font.pixelSize: 12 }
                    ZButton {
                        Layout.topMargin: 5
                        text: backend.state.stopping ? "正在停止…" : backend.state.running ? "暂停监控" : "登录并开始  →"
                        enabled: !backend.state.stopping
                        onClicked: { if (backend.state.running) backend.stopMonitor(); else loginDialog.open() }
                        background: Rectangle { color: parent.down ? "#93c9a9" : "#b9e8c4"; radius: 11 }
                        contentItem: Text { text: parent.text; color: "#173d35"; font.pixelSize: 12; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 14
                Repeater {
                    model: [
                        {label: "本次已确认", value: backend.state.success, unit: "项"},
                        {label: "连接时长", value: backend.state.uptime, unit: ""},
                        {label: "最近同步", value: backend.state.lastPoll, unit: ""}
                    ]
                    delegate: Panel {
                        required property var modelData
                        Layout.fillWidth: true; Layout.preferredHeight: 100
                        Column { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 19; spacing: 10
                            Text { text: modelData.label; color: theme.muted; font.pixelSize: 11 }
                            Row { spacing: 9
                                Text { text: modelData.value; color: theme.text; font.pixelSize: 24; font.weight: Font.DemiBold; font.family: "Segoe UI" }
                                Text { text: modelData.unit; color: theme.muted; font.pixelSize: 11; anchors.bottom: parent.bottom; anchors.bottomMargin: 4 }
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 18
                Panel {
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 235
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 14
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "当前活动"; font.pixelSize: 15; font.weight: Font.DemiBold; color: theme.text }
                            Item { Layout.fillWidth: true }
                            Text { text: String(backend.activities.length).padStart(2, "0"); font.pixelSize: 11; color: theme.muted }
                        }
                        Item {
                            visible: backend.activities.length === 0
                            Layout.fillWidth: true; Layout.fillHeight: true
                            Column { anchors.centerIn: parent; spacing: 12
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 66; height: 66; radius: 33; color: theme.field
                                    Rectangle { anchors.centerIn: parent; width: 32; height: 32; radius: 16; border.color: theme.accent; border.width: 1.5; color: "transparent"
                                        Canvas { anchors.centerIn: parent; width: 18; height: 18
                                            onPaint: { let ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = theme.accent; ctx.lineWidth = 1.7; ctx.beginPath(); ctx.moveTo(4, 9); ctx.lineTo(8, 13); ctx.lineTo(15, 5); ctx.stroke() }
                                        }
                                    }
                                }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "此刻，没有待处理的事"; color: theme.text; font.pixelSize: 13 }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: backend.state.running ? "新活动会出现在这里" : "开始会话后，在这里查看进展"; color: theme.muted; font.pixelSize: 11 }
                            }
                        }
                        ListView {
                            visible: backend.activities.length > 0
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                            spacing: 10; model: backend.activities
                            ScrollIndicator.vertical: ScrollIndicator {}
                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width; height: 80; radius: 12; color: theme.field
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 13; spacing: 6
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text { text: modelData.course; textFormat: Text.PlainText; Layout.fillWidth: true; elide: Text.ElideRight; color: theme.text; font.weight: Font.DemiBold }
                                        Text { text: modelData.kind; color: theme.muted; font.pixelSize: 10 }
                                    }
                                    Text { text: modelData.message; textFormat: Text.PlainText; Layout.fillWidth: true; elide: Text.ElideRight; font.pixelSize: 11; color: modelData.stage === "failure" ? theme.danger : theme.accent }
                                }
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 270; Layout.minimumWidth: 270; Layout.maximumWidth: 270; Layout.fillWidth: false; Layout.fillHeight: true; spacing: 16
                    Panel {
                        Layout.fillWidth: true; Layout.preferredHeight: 166
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 20; spacing: 10
                            Text { text: "当前位置"; color: theme.text; font.pixelSize: 14; font.weight: Font.DemiBold }
                            Text { text: "手动选择本次使用的地点"; color: theme.muted; font.pixelSize: 11 }
                            ZCombo {
                                Layout.fillWidth: true; model: backend.locations; textRole: "name"
                                currentIndex: Math.max(0, backend.locations.findIndex(item => item.key === backend.preferences.location))
                                enabled: !backend.state.running
                                onActivated: backend.saveSettings(JSON.stringify({location: backend.locations[currentIndex].key}))
                            }
                            Text { text: backend.state.running ? "需切换时，请先暂停监控" : "地点将用于下一次会话"; color: theme.muted; font.pixelSize: 10 }
                        }
                    }
                    Panel {
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 115
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 20; spacing: 10
                            RowLayout {
                                Text { text: "处理方式"; color: theme.muted; font.pixelSize: 11 }
                                Item { Layout.fillWidth: true }
                                Text { text: backend.preferences.auto ? "自动模式" : "手动确认"; color: theme.accent; font.pixelSize: 11 }
                            }
                            Text { text: backend.preferences.auto ? "按已保存的等待条件处理" : "每次操作前由你确认"; color: theme.text; font.pixelSize: 12 }
                            Item { Layout.fillHeight: true }
                            Text { text: "登录信息仅保留在本次运行中"; color: theme.muted; font.pixelSize: 10 }
                        }
                    }
                }
            }
        }

        Panel {
            visible: root.page === 1
            Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 18
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout { spacing: 5
                        Text { text: "会话动态"; color: theme.text; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Text { text: "最近 200 条运行记录"; color: theme.muted; font.pixelSize: 11 }
                    }
                    Item { Layout.fillWidth: true }
                    ZButton { text: "导出诊断包"; secondary: true; onClicked: backend.exportLogs() }
                    ZButton { text: "打开数据目录"; secondary: true; onClicked: backend.openDirectory() }
                }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; model: backend.events; clip: true; spacing: 1
                    ScrollIndicator.vertical: ScrollIndicator {}
                    Text { visible: backend.events.length === 0; anchors.centerIn: parent; text: "运行记录会显示在这里"; color: theme.muted }
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width; height: Math.max(50, logText.implicitHeight + 24)
                        color: "transparent"
                        Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: theme.border }
                        RowLayout {
                            anchors.fill: parent; anchors.topMargin: 12; anchors.bottomMargin: 12; spacing: 16
                            Text { text: modelData.time; color: theme.muted; font.pixelSize: 11; font.family: "Consolas"; Layout.alignment: Qt.AlignTop }
                            Text { id: logText; text: modelData.message; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: modelData.level === "error" ? theme.danger : theme.text; font.pixelSize: 12 }
                        }
                    }
                }
            }
        }

        ScrollView {
            visible: root.page === 2
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 16
                Panel {
                    Layout.fillWidth: true; implicitHeight: 175
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 14
                        RowLayout {
                            ColumnLayout { spacing: 5
                                Text { text: "处理偏好"; color: theme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                Text { text: backend.state.running ? "请先暂停监控，再修改设置" : "保存后将在下次开始时使用"; color: theme.muted; font.pixelSize: 11 }
                            }
                            Item { Layout.fillWidth: true }
                            ZButton { text: "保存设置"; enabled: !backend.state.running; onClicked: backend.saveSettings(JSON.stringify(root.draft)) }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 20
                            Text { text: "自动处理"; color: theme.text }
                            ZSwitch { checked: root.draft.auto === true; enabled: !backend.state.running; onToggled: root.draft.auto = checked }
                            Item { Layout.fillWidth: true }
                            Text { text: "等待条件"; color: theme.muted }
                            ZCombo { Layout.preferredWidth: 170; model: ["人数与时间门控", "发现后直接处理"]; currentIndex: root.draft.gate === "immediate" ? 1 : 0; enabled: !backend.state.running; onActivated: root.draft.gate = currentIndex === 0 ? "attendance" : "immediate" }
                            Text { text: "运行方式"; color: theme.muted }
                            ZCombo { Layout.preferredWidth: 120; model: ["正常监控", "仅提醒", "查询一次", "离线演示"]; currentIndex: Math.max(0, ["monitor", "reminders", "once", "demo"].indexOf(root.draft.mode)); enabled: !backend.state.running; onActivated: root.draft.mode = ["monitor", "reminders", "once", "demo"][currentIndex] }
                        }
                    }
                }
                Panel {
                    Layout.fillWidth: true; implicitHeight: numbers.implicitHeight + 78
                    Text { text: "等待与读取"; x: 22; y: 22; font.pixelSize: 16; font.weight: Font.DemiBold; color: theme.text }
                    GridLayout {
                        id: numbers; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.leftMargin: 22; anchors.rightMargin: 22; anchors.topMargin: 62
                        columns: 3; rowSpacing: 20; columnSpacing: 24
                        Repeater {
                            model: [
                                {key: "interval", label: "监控间隔 / 秒"}, {key: "ratio", label: "已签比例 / 0–1"}, {key: "count", label: "已签人数"},
                                {key: "maxWait", label: "最长等待 / 秒"}, {key: "remaining", label: "截止前保底 / 秒"}, {key: "gateInterval", label: "名单读取间隔 / 秒"},
                                {key: "attempts", label: "取码总轮数 / 1–5"}, {key: "retryInterval", label: "取码间隔 / 至少 30 秒"}, {key: "accuracy", label: "定位精度字段 / 米"},
                                {key: "loginTimeout", label: "登录超时 / 秒"}, {key: "remindEvery", label: "重复提醒 / 秒，0 为一次"}, {key: "restartDelay", label: "异常恢复等待 / 秒"},
                                {key: "maxRestarts", label: "10 分钟内最多重启"}
                            ]
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; spacing: 8
                                Text { text: modelData.label; color: theme.muted; font.pixelSize: 11 }
                                ZField { Layout.fillWidth: true; text: root.draft[modelData.key] === undefined ? "" : String(root.draft[modelData.key]); enabled: !backend.state.running; inputMethodHints: Qt.ImhFormattedNumbersOnly; onTextEdited: root.draft[modelData.key] = Number(text) }
                            }
                        }
                    }
                }
                Panel {
                    Layout.fillWidth: true; implicitHeight: 200
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 12
                        RowLayout {
                            Text { text: "手动地点"; font.pixelSize: 16; font.weight: Font.DemiBold; color: theme.text }
                            Item { Layout.fillWidth: true }
                            ZCombo {
                                Layout.preferredWidth: 250; model: backend.locations; textRole: "name"
                                currentIndex: Math.max(0, backend.locations.findIndex(item => item.key === backend.preferences.location))
                                enabled: !backend.state.running
                                onActivated: backend.saveSettings(JSON.stringify({location: backend.locations[currentIndex].key}))
                            }
                        }
                        Text { text: "也可以填写一个自己的地点，保存后将手动选中该地点。"; color: theme.muted; font.pixelSize: 11 }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 12
                            ZField { id: customName; Layout.fillWidth: true; placeholderText: "地点名称"; enabled: !backend.state.running }
                            ZField { id: customLat; Layout.preferredWidth: 150; placeholderText: "纬度，例如 30.30"; enabled: !backend.state.running }
                            ZField { id: customLon; Layout.preferredWidth: 150; placeholderText: "经度，例如 120.08"; enabled: !backend.state.running }
                            ZButton { text: "保存地点"; enabled: !backend.state.running && customName.text.length > 0 && customLat.text.length > 0 && customLon.text.length > 0
                                onClicked: { if (backend.saveLocation(customName.text, Number(customLat.text), Number(customLon.text))) { customName.text = ""; customLat.text = ""; customLon.text = "" } }
                            }
                        }
                    }
                }
                Panel {
                    Layout.fillWidth: true; implicitHeight: 95
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 22; spacing: 16
                        Text { text: "桌面通知"; color: theme.text }
                        ZSwitch { checked: root.draft.desktop === true; enabled: !backend.state.running; onToggled: root.draft.desktop = checked }
                        Text { text: "提示音"; color: theme.text; Layout.leftMargin: 18 }
                        ZSwitch { checked: root.draft.bell === true; enabled: !backend.state.running; onToggled: root.draft.bell = checked }
                        Text { text: "异常恢复"; color: theme.text; Layout.leftMargin: 18 }
                        ZSwitch { checked: root.draft.watchdog === true; enabled: !backend.state.running; onToggled: root.draft.watchdog = checked }
                        Item { Layout.fillWidth: true }
                        ZButton { text: "测试通知"; secondary: true; onClicked: backend.testNotification() }
                    }
                }
                Item { height: 10 }
            }
        }

        Rectangle {
            visible: backend.state.message.length > 0
            Layout.fillWidth: true; implicitHeight: 34; radius: 9; color: theme.tint
            Text { anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; verticalAlignment: Text.AlignVCenter; text: backend.state.message; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: theme.accent; font.pixelSize: 11 }
        }
    }

    Dialog {
        id: loginDialog
        objectName: "loginDialog"
        anchors.centerIn: parent; width: 420; modal: true; padding: 28
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: theme.surface; radius: 22; border.color: theme.border }
        onClosed: password.text = ""
        contentItem: ColumnLayout {
            spacing: 15
            Image { source: "../assets/mark.svg"; Layout.preferredWidth: 42; Layout.preferredHeight: 42; Layout.bottomMargin: 5 }
            Text { text: "开始你的会话"; font.pixelSize: 23; font.weight: Font.DemiBold; color: theme.text }
            Text { text: "使用统一身份认证账号登录"; font.pixelSize: 12; color: theme.muted; Layout.bottomMargin: 6 }
            ZField { id: student; objectName: "studentField"; Layout.fillWidth: true; placeholderText: "学号"; selectByMouse: true; maximumLength: 40; Keys.onReturnPressed: password.forceActiveFocus() }
            ZField { id: password; objectName: "passwordField"; Layout.fillWidth: true; placeholderText: "统一身份认证密码"; echoMode: TextInput.Password; maximumLength: 256; onAccepted: { if (startButton.enabled) startButton.clicked() } }
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 7
                ZButton { text: "取消"; secondary: true; Layout.fillWidth: true; onClicked: loginDialog.close() }
                ZButton { id: startButton; text: "登录并开始"; Layout.fillWidth: true; enabled: student.text.trim().length > 0 && password.text.length > 0
                    onClicked: { backend.startMonitor(student.text, password.text); password.text = ""; loginDialog.close() }
                }
            }
        }
        onOpened: student.forceActiveFocus()
    }

    Dialog {
        id: confirmDialog
        objectName: "confirmDialog"
        anchors.centerIn: parent; width: 440; modal: true; padding: 28
        closePolicy: Popup.NoAutoClose
        background: Rectangle { color: theme.surface; radius: 22; border.color: theme.border }
        property bool otp: backend.prompt.type === "otp"
        property bool code: backend.prompt.stage === "code"
        contentItem: ColumnLayout {
            spacing: 18
            Text { text: confirmDialog.otp ? "完成身份验证" : confirmDialog.code ? "输入课堂数字码" : "确认本次操作"; font.pixelSize: 22; font.weight: Font.DemiBold; color: theme.text }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText; text: confirmDialog.otp ? "请输入统一身份认证的动态验证码" : (backend.prompt.activity ? backend.prompt.activity.course + " · " + backend.prompt.activity.kind : ""); color: theme.muted; font.pixelSize: 12 }
            Text { visible: !confirmDialog.otp && !confirmDialog.code; text: "将使用当前设置处理这项活动。"; color: theme.text; font.pixelSize: 12 }
            ZField { id: answerField; visible: confirmDialog.otp || confirmDialog.code; Layout.fillWidth: true; placeholderText: confirmDialog.otp ? "动态验证码" : "4–8 位课堂数字码"; echoMode: confirmDialog.otp ? TextInput.Password : TextInput.Normal; maximumLength: confirmDialog.otp ? 16 : 8; inputMethodHints: Qt.ImhDigitsOnly
                validator: RegularExpressionValidator { regularExpression: confirmDialog.otp ? /[0-9]{0,16}/ : /[0-9]{0,8}/ }
            }
            RowLayout {
                Layout.fillWidth: true
                ZButton { text: confirmDialog.otp ? "停止登录" : "跳过"; secondary: true; Layout.fillWidth: true
                    onClicked: { if (confirmDialog.otp) backend.stopMonitor(); else backend.replyPrompt(confirmDialog.code ? "" : "n") }
                }
                ZButton { text: "确认"; Layout.fillWidth: true; enabled: !(confirmDialog.otp || confirmDialog.code) || (confirmDialog.otp ? answerField.text.length > 0 : answerField.text.length >= 4)
                    onClicked: { let value = confirmDialog.otp || confirmDialog.code ? answerField.text : "y"; answerField.text = ""; backend.replyPrompt(value) }
                }
            }
        }
        onOpened: { if (answerField.visible) answerField.forceActiveFocus() }
    }
}
