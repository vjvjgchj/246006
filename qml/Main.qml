import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    width: 1460
    height: 920
    minimumWidth: 1120
    minimumHeight: 760
    visible: true
    title: "TensorRT Quantum Console - QML Trial"
    color: backend.surfaceAltColor
    property bool compactLayout: width < 1280
    property int shellMargin: compactLayout ? 10 : 14
    property int shellSpacing: compactLayout ? 10 : 14
    property int sidebarPreferredWidth: compactLayout ? 238 : 270
    property int cardRadius: compactLayout ? 20 : 24
    property int compactValueWidth: 112
    property int formLabelWidth: 82
    property int visualMiniCardMinHeight: compactLayout ? 130 : 146
    property int paramGroupMinHeight: compactLayout ? 188 : 204
    property int keyDisplayWidth: 156
    property int keyActionWidth: 108
    property real cardFillAlpha: Math.max(0.0, Math.min(1.0, backend.cardOpacityValue / 100.0))
    property real controlFillAlpha: Math.max(0.18, Math.min(0.72, window.cardFillAlpha * 0.72))
    property real controlReadOnlyAlpha: Math.max(0.14, Math.min(0.64, window.cardFillAlpha * 0.58))
    property real controlFocusAlpha: Math.max(0.28, Math.min(0.82, window.cardFillAlpha * 0.82))
    property real popupFillAlpha: Math.max(0.24, Math.min(0.78, window.cardFillAlpha * 0.76))
    property real listFillAlpha: Math.max(0.16, Math.min(0.68, window.cardFillAlpha * 0.66))
    property real logFillAlpha: Math.max(0.18, Math.min(0.70, window.cardFillAlpha * 0.68))
    property color inputFillColor: window.withAlpha(
                                       window.mixColors(
                                           window.mixColors(backend.surfaceColor, backend.textColor, 0.24),
                                           backend.accentColor,
                                           0.10
                                       ),
                                       window.controlFillAlpha
                                   )
    property color inputReadOnlyFillColor: window.withAlpha(
                                               window.mixColors(
                                                   window.mixColors(backend.surfaceColor, backend.textColor, 0.18),
                                                   "#ffffff",
                                                   0.05
                                               ),
                                               window.controlReadOnlyAlpha
                                           )
    property color inputFillFocusColor: window.withAlpha(
                                            window.mixColors(
                                                window.mixColors(backend.surfaceColor, backend.textColor, 0.30),
                                                backend.accentColor,
                                                0.16
                                            ),
                                            window.controlFocusAlpha
                                        )
    property color inputPopupFillColor: window.withAlpha(
                                            window.mixColors(
                                                window.mixColors(backend.surfaceColor, backend.textColor, 0.20),
                                                backend.accent2Color,
                                                0.10
                                            ),
                                            window.popupFillAlpha
                                        )
    property color listRowFillColor: window.withAlpha(
                                         window.mixColors(
                                             window.mixColors(backend.surfaceColor, backend.textColor, 0.18),
                                             backend.accent2Color,
                                             0.08
                                         ),
                                         window.listFillAlpha
                                     )
    property color logInfoFillColor: window.withAlpha(
                                         window.mixColors(backend.surfaceColor, backend.textColor, 0.16),
                                         window.logFillAlpha
                                     )
    property color logWarnFillColor: window.withAlpha(
                                         window.mixColors(backend.surfaceColor, "#D3A14C", 0.18),
                                         Math.min(0.76, window.logFillAlpha + 0.02)
                                     )
    property color logErrorFillColor: window.withAlpha(
                                          window.mixColors(backend.surfaceColor, "#C85D7A", 0.18),
                                          Math.min(0.76, window.logFillAlpha + 0.02)
                                      )
    property color logSuccessFillColor: window.withAlpha(
                                            window.mixColors(backend.surfaceColor, "#43C78A", 0.18),
                                            Math.min(0.76, window.logFillAlpha + 0.02)
                                        )
    palette.window: backend.surfaceAltColor
    palette.base: backend.surfaceColor
    palette.alternateBase: backend.surfaceAltColor
    palette.button: backend.surfaceColor
    palette.buttonText: backend.textColor
    palette.text: backend.textColor
    palette.windowText: backend.textColor
    palette.highlight: backend.accentColor
    palette.highlightedText: "#ffffff"
    palette.placeholderText: backend.mutedColor
    property var cpuHistory: []
    property var gpuHistory: []
    property var memoryHistory: []
    property string monitorLastSampleKey: ""

    function normalizedMetric(value) {
        const numberValue = Number(value)
        if (isNaN(numberValue) || numberValue < 0)
            return 0
        return Math.max(0, Math.min(100, numberValue))
    }

    function pushMonitorSample(history, value) {
        const next = history.slice(0)
        next.push(normalizedMetric(value))
        while (next.length > 24)
            next.shift()
        return next
    }

    function refreshMonitorHistory() {
        const sampleKey = backend.cpuMetricText + "|" + backend.gpuMetricText + "|" + backend.memoryMetricText
        if (sampleKey === monitorLastSampleKey)
            return
        monitorLastSampleKey = sampleKey
        cpuHistory = pushMonitorSample(cpuHistory, backend.cpuUsageValue)
        gpuHistory = pushMonitorSample(gpuHistory, backend.gpuUsageValue)
        memoryHistory = pushMonitorSample(memoryHistory, backend.memoryUsageValue)
    }

    Connections {
        target: backend
        function onStateChanged() {
            window.refreshMonitorHistory()
        }
    }

    function normalizeColor(colorValue) {
        if (typeof colorValue === "string")
            return Qt.color(colorValue)
        return colorValue
    }

    function withAlpha(colorValue, alphaValue) {
        const c = window.normalizeColor(colorValue)
        return Qt.rgba(c.r, c.g, c.b, Math.max(0.0, Math.min(1.0, alphaValue)))
    }

    function mixColors(colorA, colorB, ratio) {
        const a = window.normalizeColor(colorA)
        const b = window.normalizeColor(colorB)
        const t = Math.max(0.0, Math.min(1.0, ratio))
        return Qt.rgba(
            a.r * (1.0 - t) + b.r * t,
            a.g * (1.0 - t) + b.g * t,
            a.b * (1.0 - t) + b.b * t,
            1.0
        )
    }

    function adaptiveColumns(availableWidth, wide, medium) {
        if (availableWidth >= wide)
            return 3
        if (availableWidth >= medium)
            return 2
        return 1
    }

    component SoftHelpPopup: Item {
        id: popup
        property Item anchorItem: null
        property string helpText: ""
        property string placement: "below-left"
        property real maxTextWidth: 280
        property real edgeMargin: 12
        property real anchorGap: 8
        property real popupPadding: 10
        property bool shown: false
        parent: window.contentItem
        visible: shown && helpText.length > 0
        opacity: shown ? 1.0 : 0.0
        z: 1000
        implicitWidth: Math.min(maxTextWidth, helpTextItem.implicitWidth) + popupPadding * 2
        implicitHeight: helpTextItem.implicitHeight + popupPadding * 2
        width: implicitWidth
        height: implicitHeight
        Behavior on opacity {
            NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
        }
        function clampX(value, bubbleWidth) {
            return Math.max(edgeMargin, Math.min(parent.width - bubbleWidth - edgeMargin, value))
        }
        function clampY(value, bubbleHeight) {
            return Math.max(edgeMargin, Math.min(parent.height - bubbleHeight - edgeMargin, value))
        }
        function resolvedPosition() {
            const bubbleWidth = Math.max(width, implicitWidth)
            const bubbleHeight = Math.max(height, implicitHeight)
            if (!anchorItem || !parent)
                return Qt.point(edgeMargin, edgeMargin)

            const p = anchorItem.mapToItem(parent, 0, 0)
            const rightX = p.x + anchorItem.width + anchorGap
            const belowY = p.y + anchorItem.height + anchorGap
            const aboveY = p.y - bubbleHeight - anchorGap

            if (placement === "badge") {
                let xPos = rightX + bubbleWidth <= parent.width - edgeMargin
                           ? rightX
                           : p.x + anchorItem.width - bubbleWidth
                let yPos = belowY + bubbleHeight <= parent.height - edgeMargin
                           ? belowY
                           : aboveY >= edgeMargin
                             ? aboveY
                             : belowY
                return Qt.point(clampX(xPos, bubbleWidth), clampY(yPos, bubbleHeight))
            }

            if (placement === "below-center") {
                const centeredX = p.x + (anchorItem.width - bubbleWidth) / 2
                const preferredY = belowY + bubbleHeight <= parent.height - edgeMargin
                                   ? belowY
                                   : aboveY >= edgeMargin
                                     ? aboveY
                                     : belowY
                return Qt.point(clampX(centeredX, bubbleWidth), clampY(preferredY, bubbleHeight))
            }

            const leftAlignedY = belowY + bubbleHeight <= parent.height - edgeMargin
                                 ? belowY
                                 : aboveY >= edgeMargin
                                   ? aboveY
                                   : belowY
            return Qt.point(clampX(p.x, bubbleWidth), clampY(leftAlignedY, bubbleHeight))
        }
        function open() {
            if (helpText.length === 0 || !anchorItem || !parent)
                return
            shown = true
            popupDebugTimer.restart()
        }
        function close() {
            shown = false
        }
        x: visible ? resolvedPosition().x : edgeMargin
        y: visible ? resolvedPosition().y : edgeMargin
        Rectangle {
            anchors.fill: parent
            radius: 14
            color: window.withAlpha(
                       window.mixColors(backend.surfaceColor, "#ffffff", 0.08),
                       Math.max(0.84, Math.min(0.94, window.cardFillAlpha + 0.18))
                   )
            border.color: window.withAlpha(backend.accent2Color, 0.75)
            border.width: 1
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 13
                color: "#ffffff"
                opacity: 0.035
            }
        }
        Text {
            id: helpTextItem
            anchors.fill: parent
            anchors.margins: popup.popupPadding
            text: popup.helpText
            width: popup.width - popup.popupPadding * 2
            wrapMode: Text.WordWrap
            lineHeight: 1.08
            color: backend.textColor
            font.pixelSize: 12
        }
    }

    component HintBadge: Item {
        id: control
        property string helpText: ""
        property bool hovered: hoverHandler.hovered
        implicitWidth: helpText.length > 0 ? 18 : 0
        implicitHeight: helpText.length > 0 ? 18 : 0
        visible: helpText.length > 0
        HoverHandler {
            id: hoverHandler
        }
        Rectangle {
            anchors.centerIn: parent
            width: 16
            height: 16
            radius: 8
            color: window.withAlpha(backend.surfaceColor, 0.42)
            border.width: 1
            border.color: control.hovered ? backend.accentColor : backend.accent2Color
        }
        Text {
            anchors.centerIn: parent
            text: "?"
            color: backend.textColor
            font.pixelSize: 10
            font.bold: true
        }
        SoftHelpPopup {
            id: hintPopup
            anchorItem: control
            helpText: control.helpText
            placement: "badge"
        }
        Timer {
            id: hintTimer
            interval: 360
            repeat: false
            onTriggered: {
                if (control.hovered && control.helpText.length > 0)
                    hintPopup.open()
            }
        }
        onHoveredChanged: {
            if (hovered)
                hintTimer.restart()
            else {
                hintTimer.stop()
                hintPopup.close()
            }
        }
    }

    component ThemedButton: Button {
        id: control
        implicitHeight: 34
        implicitWidth: 110
        font.pixelSize: 13
        property string helpText: ""
        contentItem: Text {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            text: control.text
            color: "#ffffff"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: control.font.pixelSize
            font.bold: true
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 12
            border.width: 1
            border.color: control.down ? backend.accent2Color : backend.accentColor
            color: control.down
                   ? Qt.darker(backend.accentColor, 1.28)
                   : control.hovered
                     ? Qt.lighter(backend.accentColor, 1.08)
                     : backend.accentColor
            opacity: control.enabled ? 0.92 : 0.45
        }
        readonly property string resolvedHelpText: control.helpText.length > 0
                                                  ? control.helpText
                                                  : contentItem.implicitWidth > (control.width - 20)
                                                    ? control.text
                                                    : ""
        SoftHelpPopup {
            id: primaryButtonHelp
            anchorItem: control
            helpText: control.resolvedHelpText
            placement: "below-left"
        }
        Timer {
            id: primaryButtonHelpTimer
            interval: 380
            repeat: false
            onTriggered: {
                if (control.hovered && control.enabled && control.resolvedHelpText.length > 0)
                    primaryButtonHelp.open()
            }
        }
        onHoveredChanged: {
            if (hovered)
                primaryButtonHelpTimer.restart()
            else {
                primaryButtonHelpTimer.stop()
                primaryButtonHelp.close()
            }
        }
    }

    component SecondaryButton: Button {
        id: control
        implicitHeight: 34
        implicitWidth: 110
        font.pixelSize: 13
        property string helpText: ""
        contentItem: Text {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            text: control.text
            color: backend.textColor
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: control.font.pixelSize
            font.bold: true
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 12
            border.width: 1
            border.color: control.down ? backend.accentColor : backend.accent2Color
            color: control.down
                   ? Qt.darker(backend.surfaceColor, 1.15)
                   : control.hovered
                     ? Qt.lighter(backend.surfaceColor, 1.08)
                     : backend.surfaceColor
            opacity: control.enabled ? 0.88 : 0.42
        }
        readonly property string resolvedHelpText: control.helpText.length > 0
                                                  ? control.helpText
                                                  : contentItem.implicitWidth > (control.width - 20)
                                                    ? control.text
                                                    : ""
        SoftHelpPopup {
            id: secondaryButtonHelp
            anchorItem: control
            helpText: control.resolvedHelpText
            placement: "below-left"
        }
        Timer {
            id: secondaryButtonHelpTimer
            interval: 380
            repeat: false
            onTriggered: {
                if (control.hovered && control.enabled && control.resolvedHelpText.length > 0)
                    secondaryButtonHelp.open()
            }
        }
        onHoveredChanged: {
            if (hovered)
                secondaryButtonHelpTimer.restart()
            else {
                secondaryButtonHelpTimer.stop()
                secondaryButtonHelp.close()
            }
        }
    }

    component MetricRing: Item {
        id: control
        property string label: ""
        property string detail: ""
        property real value: 0
        property color accent: backend.accentColor
        implicitWidth: 64
        implicitHeight: 82

        function percent() {
            return window.normalizedMetric(value)
        }

        onValueChanged: ringCanvas.requestPaint()
        onAccentChanged: ringCanvas.requestPaint()

        Canvas {
            id: ringCanvas
            width: 54
            height: 54
            anchors.horizontalCenter: parent.horizontalCenter
            contextType: "2d"
            antialiasing: true
            onPaint: {
                const ctx = getContext("2d")
                const p = control.percent() / 100.0
                const cx = width / 2
                const cy = height / 2
                const radius = Math.min(width, height) / 2 - 6
                ctx.reset()
                ctx.lineWidth = 5
                ctx.lineCap = "round"
                ctx.strokeStyle = window.withAlpha(backend.textColor, 0.14)
                ctx.beginPath()
                ctx.arc(cx, cy, radius, 0, Math.PI * 2)
                ctx.stroke()
                ctx.shadowColor = window.withAlpha(control.accent, 0.45)
                ctx.shadowBlur = 8
                ctx.strokeStyle = control.accent
                ctx.beginPath()
                ctx.arc(cx, cy, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * p)
                ctx.stroke()
                ctx.shadowBlur = 0
            }
        }

        Text {
            anchors.centerIn: ringCanvas
            text: control.value < 0 ? "--" : Math.round(control.percent()).toString()
            color: backend.textColor
            font.pixelSize: 13
            font.bold: true
        }

        Column {
            anchors.top: ringCanvas.bottom
            anchors.topMargin: 5
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 1
            Text {
                width: parent.width
                text: control.label
                color: backend.textColor
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 11
                font.bold: true
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: control.detail
                color: backend.mutedColor
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }
    }

    component MonitorSparkline: Item {
        id: control
        property var cpuValues: []
        property var gpuValues: []
        property var memoryValues: []
        implicitHeight: 82
        onCpuValuesChanged: graphCanvas.requestPaint()
        onGpuValuesChanged: graphCanvas.requestPaint()
        onMemoryValuesChanged: graphCanvas.requestPaint()

        Canvas {
            id: graphCanvas
            anchors.fill: parent
            contextType: "2d"
            antialiasing: true
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d")
                const padX = 8
                const padY = 8
                const graphW = Math.max(1, width - padX * 2)
                const graphH = Math.max(1, height - padY * 2)

                function yFor(value) {
                    return padY + graphH * (1.0 - window.normalizedMetric(value) / 100.0)
                }

                function drawLine(values, color, lineWidth) {
                    if (!values || values.length < 2)
                        return
                    ctx.beginPath()
                    for (let i = 0; i < values.length; ++i) {
                        const x = padX + graphW * i / Math.max(1, values.length - 1)
                        const y = yFor(values[i])
                        if (i === 0)
                            ctx.moveTo(x, y)
                        else
                            ctx.lineTo(x, y)
                    }
                    ctx.lineWidth = lineWidth
                    ctx.lineCap = "round"
                    ctx.lineJoin = "round"
                    ctx.strokeStyle = color
                    ctx.stroke()
                }

                ctx.reset()
                ctx.fillStyle = window.withAlpha(backend.surfaceAltColor, 0.22)
                ctx.fillRect(0, 0, width, height)
                ctx.strokeStyle = window.withAlpha(backend.textColor, 0.08)
                ctx.lineWidth = 1
                for (let i = 1; i <= 3; ++i) {
                    const y = padY + graphH * i / 4
                    ctx.beginPath()
                    ctx.moveTo(padX, y)
                    ctx.lineTo(width - padX, y)
                    ctx.stroke()
                }
                ctx.shadowColor = window.withAlpha(backend.accentColor, 0.32)
                ctx.shadowBlur = 8
                drawLine(control.memoryValues, window.withAlpha(backend.textColor, 0.74), 1.5)
                drawLine(control.cpuValues, backend.accent2Color, 2.0)
                drawLine(control.gpuValues, backend.accentColor, 2.4)
                ctx.shadowBlur = 0
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: 14
            color: "transparent"
            border.width: 1
            border.color: window.withAlpha(backend.accent2Color, 0.28)
        }
    }

    component ThemedTextField: Control {
        id: control
        property alias text: field.text
        property alias validator: field.validator
        property alias cursorPosition: field.cursorPosition
        property bool textEditing: field.activeFocus
        property string placeholderText: ""
        property color color: backend.textColor
        property color placeholderTextColor: backend.mutedColor
        property color selectionColor: backend.accentColor
        property color selectedTextColor: "#ffffff"
        property bool readOnly: false
        signal editingFinished()
        implicitHeight: 34
        implicitWidth: 240
        leftPadding: 10
        rightPadding: 10
        topPadding: 0
        bottomPadding: 0
        focusPolicy: Qt.StrongFocus
        property bool hoverActive: hoverHandler.hovered
        contentItem: Item {
            clip: true

            TextInput {
                id: field
                anchors.fill: parent
                color: control.color
                font.pixelSize: 13
                verticalAlignment: TextInput.AlignVCenter
                selectByMouse: true
                selectedTextColor: control.selectedTextColor
                selectionColor: control.selectionColor
                readOnly: control.readOnly
                renderType: TextInput.QtRendering
                onEditingFinished: control.editingFinished()
            }

            Text {
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                color: control.placeholderTextColor
                text: control.placeholderText
                visible: field.text.length === 0 && field.preeditText.length === 0
                elide: Text.ElideRight
            }
        }
        HoverHandler {
            id: hoverHandler
        }
        background: Rectangle {
            id: bgRect
            radius: 12
            border.width: field.activeFocus ? 1.5 : 1
            border.color: field.activeFocus
                          ? backend.accentColor
                          : control.hoverActive
                            ? Qt.lighter(backend.accent2Color, 1.15)
                            : backend.accent2Color
            color: field.activeFocus
                   ? window.inputFillFocusColor
                   : control.readOnly
                     ? window.inputReadOnlyFillColor
                     : window.inputFillColor
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 11
                color: "#ffffff"
                opacity: field.activeFocus ? 0.028 : control.readOnly ? 0.010 : 0.014
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 1
                anchors.rightMargin: 1
                anchors.topMargin: 1
                height: Math.max(1, Math.round(parent.height * 0.38))
                radius: 11
                color: "#ffffff"
                opacity: field.activeFocus ? 0.018 : control.readOnly ? 0.006 : 0.010
            }
        }
    }

    component WheelValueField: TextField {
        id: control
        property real wheelStep: 1.0
        property int wheelPrecision: 0
        property bool integerOnly: false
        property bool clampEnabled: false
        property real minimumValue: 0.0
        property real maximumValue: 1.0
        implicitHeight: 34
        implicitWidth: window.compactValueWidth
        color: backend.textColor
        font.pixelSize: 13
        placeholderTextColor: backend.mutedColor
        selectedTextColor: "#ffffff"
        selectionColor: backend.accentColor
        leftPadding: 10
        rightPadding: 10
        topPadding: 0
        bottomPadding: 0
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: TextInput.AlignVCenter
        background: Rectangle {
            id: bgRect
            radius: 12
            border.width: control.activeFocus ? 1.5 : 1
            border.color: control.activeFocus
                          ? backend.accentColor
                          : control.hovered
                            ? Qt.lighter(backend.accent2Color, 1.15)
                            : backend.accent2Color
            color: control.activeFocus ? window.inputFillFocusColor : window.inputFillColor
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 11
                color: "#ffffff"
                opacity: control.activeFocus ? 0.028 : 0.014
            }
        }
        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
                if (!control.activeFocus) {
                    event.accepted = false
                    return
                }
                let currentValue = Number(control.text)
                if (isNaN(currentValue))
                    currentValue = 0
                let delta = event.angleDelta.y !== 0 ? event.angleDelta.y : event.pixelDelta.y
                if (delta === 0) {
                    event.accepted = false
                    return
                }
                let direction = delta > 0 ? 1 : -1
                let nextValue = currentValue + direction * control.wheelStep
                if (control.clampEnabled)
                    nextValue = Math.max(control.minimumValue, Math.min(control.maximumValue, nextValue))
                control.text = control.integerOnly
                               ? Math.round(nextValue).toString()
                               : nextValue.toFixed(control.wheelPrecision)
                control.selectAll()
                event.accepted = true
            }
        }
    }

    component ThemedComboBox: ComboBox {
        id: control
        implicitHeight: 34
        font.pixelSize: 13
        property string helpText: ""
        delegate: ItemDelegate {
            width: control.width
            contentItem: Text {
                text: modelData
                color: backend.textColor
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            background: Rectangle {
                color: highlighted ? backend.accentColor : backend.surfaceColor
                opacity: highlighted ? 0.78 : 0.96
            }
        }
        contentItem: Text {
            leftPadding: 10
            rightPadding: 30
            text: control.displayText
            color: backend.textColor
            horizontalAlignment: Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Canvas {
            x: control.width - width - 12
            y: control.topPadding + (control.availableHeight - height) / 2
            width: 12
            height: 8
            contextType: "2d"
            onPaint: {
                context.reset()
                context.moveTo(0, 0)
                context.lineTo(width, 0)
                context.lineTo(width / 2, height)
                context.closePath()
                context.fillStyle = backend.textColor
                context.fill()
            }
        }
        background: Rectangle {
            id: comboBg
            radius: 12
            border.width: control.visualFocus ? 1.5 : 1
            border.color: control.visualFocus
                          ? backend.accentColor
                          : control.hovered
                            ? Qt.lighter(backend.accent2Color, 1.15)
                            : backend.accent2Color
            color: control.visualFocus ? window.inputFillFocusColor : window.inputReadOnlyFillColor
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 11
                color: "#ffffff"
                opacity: control.visualFocus ? 0.022 : 0.008
            }
        }
        popup: Popup {
            y: control.height + 4
            width: control.width
            padding: 4
            background: Rectangle {
                id: popupBg
                radius: 12
                color: window.inputPopupFillColor
                border.color: backend.accent2Color
                border.width: 1
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: 11
                    color: "#ffffff"
                    opacity: 0.007
                }
            }
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: control.popup.visible ? control.delegateModel : null
                currentIndex: control.highlightedIndex
                ScrollBar.vertical: ScrollBar {}
            }
        }
        SoftHelpPopup {
            id: comboHelpPopup
            anchorItem: control
            helpText: control.helpText
            placement: "below-left"
        }
        Timer {
            id: comboHelpTimer
            interval: 380
            repeat: false
            onTriggered: {
                if (control.hovered && control.helpText.length > 0)
                    comboHelpPopup.open()
            }
        }
        onHoveredChanged: {
            if (hovered)
                comboHelpTimer.restart()
            else {
                comboHelpTimer.stop()
                comboHelpPopup.close()
            }
        }
    }

    component ThemedCheckBox: CheckBox {
        id: control
        spacing: 8
        font.pixelSize: 13
        indicator: Rectangle {
            implicitWidth: 18
            implicitHeight: 18
            radius: 6
            border.width: 1
            border.color: control.checked ? backend.accentColor : backend.accent2Color
            color: control.checked ? backend.accentColor : backend.surfaceAltColor
            Rectangle {
                anchors.centerIn: parent
                width: 8
                height: 8
                radius: 3
                visible: control.checked
                color: "#ffffff"
            }
        }
        contentItem: Text {
            text: control.text
            color: backend.textColor
            verticalAlignment: Text.AlignVCenter
            leftPadding: control.indicator.width + control.spacing
        }
    }

    component ThemedGroupBox: GroupBox {
        id: control
        property bool hoverActive: hoverHandler.hovered
        property string titleHelpText: ""
        topPadding: 28
        leftPadding: 9
        rightPadding: 9
        bottomPadding: 8
        HoverHandler {
            id: hoverHandler
        }
        label: RowLayout {
            spacing: 6
            x: 4
            Label {
                text: control.title
                color: backend.textColor
                font.pixelSize: 15
                font.bold: true
            }
            HintBadge {
                helpText: control.titleHelpText
                Layout.alignment: Qt.AlignVCenter
            }
        }
        background: Rectangle {
            radius: 16
            color: window.withAlpha(backend.surfaceAltColor, window.cardFillAlpha)
            border.color: control.hoverActive ? Qt.lighter(backend.accent2Color, 1.18) : backend.accent2Color
            border.width: 1
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 15
                color: "#ffffff"
                opacity: control.hoverActive ? 0.018 : 0.0
                Behavior on opacity { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
            }
        }
    }

    component HoverInfoLabel: Label {
        id: control
        property string fullText: text
        property bool allowWrap: false
        wrapMode: allowWrap ? Text.WordWrap : Text.NoWrap
        elide: allowWrap ? Text.ElideNone : Text.ElideRight
        maximumLineCount: allowWrap ? 4 : 1
        HoverHandler {
            id: labelHover
        }
        ToolTip.visible: labelHover.hovered && (control.implicitWidth > control.width || (allowWrap && control.implicitHeight > control.height))
        ToolTip.delay: 380
        ToolTip.timeout: 2400
        ToolTip.text: control.fullText
    }

    component FormLabel: Label {
        color: backend.mutedColor
        font.pixelSize: 13
        verticalAlignment: Text.AlignVCenter
        Layout.preferredWidth: window.formLabelWidth
        Layout.alignment: Qt.AlignVCenter
    }

    component ThemedSlider: Slider {
        id: control
        implicitHeight: 28
        background: Rectangle {
            x: control.leftPadding
            y: control.topPadding + control.availableHeight / 2 - height / 2
            width: control.availableWidth
            height: 6
            radius: 3
            color: backend.surfaceAltColor
            border.color: backend.accent2Color
        }
        handle: Rectangle {
            x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
            y: control.topPadding + control.availableHeight / 2 - height / 2
            width: 18
            height: 18
            radius: 9
            color: backend.accentColor
            border.color: "#ffffff"
            border.width: 1
        }
    }

    function collectSettings() {
        let activeMode = backgroundImageField.text.length > 0 ? "image" : "none"

        return {
            model_path: modelPathField.text,
            engine_path: enginePathField.text,
            imgsz: imgszField.text,
            roi: roiField.text,
            conf: confField.text,
            nms: nmsField.text,
            pid_p: pidPField.text,
            pid_i: pidIField.text,
            pid_d: pidDField.text,
            y_offset: yOffsetField.text,
            fps_limit: fpsLimitField.text,
            trigger_mode: triggerModeBox.currentText,
            trigger_delay: triggerDelayField.text,
            kalman_en: kalmanEnableBox.checked,
            kalman_pred: kalmanPredField.text,
            recoil_en: recoilEnableBox.checked,
            trigger_recoil_en: triggerRecoilEnableBox.checked,
            recoil_strength: recoilStrengthField.text,
            recoil_delay: recoilDelayField.text,
            motion_mode: neuralMotionBox.checked ? "神经模式" : "经典模式",
            neural_curvature: neuralCurvatureSlider.value / 100.0,
            neural_tremor: neuralTremorField.text,
            stick_enable: stickEnableBox.checked,
            stick_int: stickIntField.text,
            stick_rad: stickRadField.text,
            lghub_enabled: lghubBox.checked,
            esp32_enabled: esp32EnableBox.checked,
            esp32_port: esp32PortField.text,
            esp32_baud: esp32BaudField.text,
            pipeline_mode: pipelineModeBox.currentText,
            aim_keys: aimKeysField.text,
            trigger_keys: triggerKeysField.text,
            selected_classes_text: backend.selectedClassesText,
            card_opacity: opacitySlider.value,
            theme_name: themeCombo.currentText,
            custom_theme_color: customThemeField.text,
            background_image_path: backgroundImageField.text,
            background_video_path: "",
            background_video_url: "",
            background_volume: backend.backgroundVolumeValue,
            active_background_mode: activeMode
        }
    }

    function commitSettings() {
        backend.updateVisualSettings(window.collectSettings())
    }

    function syncFromBackend() {
        if (!modelPathField.textEditing) modelPathField.text = backend.modelPath
        if (!enginePathField.textEditing) enginePathField.text = backend.enginePath
        if (!imgszField.activeFocus) imgszField.text = backend.imgszValue.toString()
        if (!roiField.activeFocus) roiField.text = backend.roiValue.toString()
        if (!confField.activeFocus) confField.text = backend.confValue.toFixed(3)
        if (!nmsField.activeFocus) nmsField.text = backend.nmsValue.toFixed(3)
        if (!pidPField.activeFocus) pidPField.text = backend.pidPValue.toFixed(3)
        if (!pidIField.activeFocus) pidIField.text = backend.pidIValue.toFixed(3)
        if (!pidDField.activeFocus) pidDField.text = backend.pidDValue.toFixed(3)
        if (!yOffsetField.activeFocus) yOffsetField.text = backend.yOffsetValue.toFixed(3)
        if (!fpsLimitField.activeFocus) fpsLimitField.text = backend.fpsLimitValue.toString()
        neuralCurvatureSlider.value = backend.neuralCurvatureValue * 100.0
        if (!neuralTremorField.activeFocus) neuralTremorField.text = backend.neuralTremorValue.toFixed(2)
        if (!kalmanPredField.activeFocus) kalmanPredField.text = backend.kalmanPredValue.toFixed(1)
        if (!triggerDelayField.activeFocus) triggerDelayField.text = backend.triggerDelayValue.toFixed(1)
        if (!recoilStrengthField.activeFocus) recoilStrengthField.text = backend.recoilStrengthValue.toFixed(2)
        if (!recoilDelayField.activeFocus) recoilDelayField.text = backend.recoilDelayValue.toFixed(1)
        if (!stickIntField.activeFocus) stickIntField.text = backend.stickIntValue.toFixed(3)
        if (!stickRadField.activeFocus) stickRadField.text = backend.stickRadValue.toFixed(3)
        if (!aimKeysField.textEditing) aimKeysField.text = backend.aimKeysValue
        if (!triggerKeysField.textEditing) triggerKeysField.text = backend.triggerKeysValue
        if (!esp32PortField.textEditing) esp32PortField.text = backend.esp32PortValue
        if (!esp32BaudField.activeFocus) esp32BaudField.text = backend.esp32BaudValue.toString()
        if (!customThemeField.textEditing) customThemeField.text = backend.customThemeColorValue
        if (!backgroundImageField.textEditing) backgroundImageField.text = backend.backgroundImagePathValue
        opacitySlider.value = backend.cardOpacityValue
        kalmanEnableBox.checked = backend.kalmanEnableValue
        recoilEnableBox.checked = backend.recoilEnableValue
        triggerRecoilEnableBox.checked = backend.triggerRecoilEnableValue
        stickEnableBox.checked = backend.stickEnableValue
        lghubBox.checked = backend.lghubEnabledValue
        esp32EnableBox.checked = backend.esp32EnabledValue

        let themeIndex = themeCombo.find(backend.themeNameValue)
        if (themeIndex >= 0)
            themeCombo.currentIndex = themeIndex

        let pipelineIndex = pipelineModeBox.find(backend.pipelineModeValue)
        if (pipelineIndex >= 0)
            pipelineModeBox.currentIndex = pipelineIndex

        neuralMotionBox.checked = backend.motionModeValue === "神经模式"

        let triggerIndex = triggerModeBox.find(backend.triggerModeValue)
        if (triggerIndex >= 0)
            triggerModeBox.currentIndex = triggerIndex
    }

    Component.onCompleted: {
        syncFromBackend()
        refreshMonitorHistory()
    }

    Connections {
        target: backend
        function onStateChanged() {
            window.syncFromBackend()
        }
    }

    FileDialog {
        id: modelDialog
        title: "选择模型文件"
        currentFolder: backend.modelsLibraryUrl
        nameFilters: ["Model Files (*.onnx)", "All Files (*.*)"]
        onAccepted: {
            const path = backend.toLocalPath(selectedFile.toString())
            modelPathField.text = path
            backend.setModelPath(path)
        }
    }

    FileDialog {
        id: engineDialog
        title: "选择引擎文件"
        currentFolder: backend.modelsLibraryUrl
        nameFilters: ["TensorRT Engine (*.engine)", "All Files (*.*)"]
        onAccepted: {
            const path = backend.toLocalPath(selectedFile.toString())
            enginePathField.text = path
            backend.setEnginePath(path)
        }
    }

    FileDialog {
        id: backgroundImageDialog
        title: "选择背景图片"
        nameFilters: ["Image Files (*.png *.jpg *.jpeg *.bmp *.webp)", "All Files (*.*)"]
        onAccepted: {
            const path = backend.toLocalPath(selectedFile.toString())
            backgroundImageField.text = path
            backend.setBackgroundVideoPath("")
            backend.setBackgroundVideoUrl("")
            backend.setBackgroundImagePath(path)
        }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: backend.surfaceAltColor }
            GradientStop { position: 0.4; color: backend.heroStartColor }
            GradientStop { position: 1.0; color: backend.heroEndColor }
        }
    }

    Image {
        anchors.fill: parent
        source: backend.activeBackgroundModeValue === "image" && backend.backgroundImagePathValue.length > 0
                ? "file:///" + backend.backgroundImagePathValue.replace(/\\/g, "/")
                : ""
        visible: source !== ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        opacity: 0.35
    }


    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: backend.activeBackgroundModeValue === "image" ? 0.12 : 0.08
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: window.shellMargin
        spacing: window.shellSpacing

        Rectangle {
            Layout.preferredWidth: window.sidebarPreferredWidth
            Layout.fillHeight: true
            radius: 26
            color: window.withAlpha(backend.sidebarColor, window.cardFillAlpha)
            border.color: backend.accentColor
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 12

                Label {
                    text: "TRT\nQuantum"
                    color: backend.textColor
                    font.pixelSize: 30
                    font.bold: true
                }

                Label {
                    text: "控制面板"
                    color: backend.mutedColor
                    font.pixelSize: 16
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: statusCardLayout.implicitHeight + 24
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: statusCardLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Label {
                            text: "运行状态"
                            color: backend.textColor
                            font.pixelSize: 18
                            font.bold: true
                        }
                        HoverInfoLabel { text: backend.statusModeText; fullText: backend.statusModeText; color: backend.textColor; Layout.fillWidth: true }
                        HoverInfoLabel { text: backend.statusModelText; fullText: backend.statusModelText; color: backend.mutedColor; Layout.fillWidth: true }
                        HoverInfoLabel { text: backend.statusEngineText; fullText: backend.statusEngineText; color: backend.mutedColor; Layout.fillWidth: true }
                        HoverInfoLabel { text: backend.backgroundStatusText; fullText: backend.backgroundStatusText; color: backend.accentColor; Layout.fillWidth: true }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 56
                            radius: 16
                            color: window.withAlpha(window.mixColors(backend.surfaceAltColor, backend.accentColor, 0.10), 0.30)
                            border.width: 1
                            border.color: window.withAlpha(backend.accentColor, 0.42)

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 8

                                Rectangle {
                                    Layout.preferredWidth: 46
                                    Layout.preferredHeight: 26
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: 9
                                    color: (backend.licenseBadgeText === "有效")
                                           ? window.withAlpha("#45D68D", 0.18)
                                           : window.withAlpha("#D3A14C", 0.16)
                                    border.width: 1
                                    border.color: (backend.licenseBadgeText === "有效")
                                                  ? window.withAlpha("#45D68D", 0.62)
                                                  : window.withAlpha("#D3A14C", 0.56)
                                    Label {
                                        anchors.centerIn: parent
                                        text: backend.licenseBadgeText
                                        color: backend.licenseBadgeText === "有效" ? "#7CF2B5" : "#FFD88A"
                                        font.pixelSize: 12
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Layout.alignment: Qt.AlignVCenter
                                    spacing: 1

                                    Label {
                                        text: backend.licenseExpiryCompactText
                                        color: backend.textColor
                                        font.pixelSize: 12
                                        font.bold: true
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        Layout.alignment: Qt.AlignVCenter
                                    }

                                    Label {
                                        text: backend.licenseRemainingText
                                        color: backend.accentColor
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                    }
                                }
                            }

                            TapHandler {
                                onTapped: backend.refreshLicenseStatus()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: updateCardLayout.implicitHeight + 24
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accentColor
                    border.width: 1

                    ColumnLayout {
                        id: updateCardLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Label {
                            text: "Update"
                            color: backend.textColor
                            font.pixelSize: 17
                            font.bold: true
                        }

                        HoverInfoLabel {
                            text: backend.updateStatusText
                            fullText: backend.updateStatusText + "\n" + backend.updateManifestUrl
                            color: backend.mutedColor
                            Layout.fillWidth: true
                        }

                        HoverInfoLabel {
                            text: "Local: " + backend.updateCurrentVersion + " / Latest: " + backend.updateLatestVersion
                            fullText: "Current version: " + backend.updateCurrentVersion + "\nLatest version: " + backend.updateLatestVersion
                            color: backend.accentColor
                            Layout.fillWidth: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            SecondaryButton {
                                text: backend.updateRunning ? "Checking..." : "Check"
                                enabled: !backend.updateRunning
                                Layout.fillWidth: true
                                onClicked: backend.checkForUpdates()
                            }

                            ThemedButton {
                                text: backend.updateRunning ? "Updating..." : "Apply"
                                enabled: backend.updateAvailable && !backend.updateRunning && !backend.pipelineRunning
                                Layout.fillWidth: true
                                onClicked: backend.applyAvailableUpdate()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: monitorCardLayout.implicitHeight + 26
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: monitorCardLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label {
                                text: "系统监控"
                                color: backend.textColor
                                font.pixelSize: 18
                                font.bold: true
                                Layout.fillWidth: true
                            }
                            Rectangle {
                                Layout.preferredWidth: 58
                                Layout.preferredHeight: 22
                                radius: 11
                                color: window.withAlpha(backend.accentColor, 0.16)
                                border.width: 1
                                border.color: window.withAlpha(backend.accentColor, 0.42)
                                Text {
                                    anchors.centerIn: parent
                                    text: "LIVE"
                                    color: backend.accentColor
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.letterSpacing: 1.2
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            MetricRing {
                                Layout.fillWidth: true
                                label: "CPU"
                                detail: backend.cpuUsageValue < 0 ? "--" : Math.round(backend.cpuUsageValue) + "%"
                                value: backend.cpuUsageValue
                                accent: backend.accent2Color
                            }
                            MetricRing {
                                Layout.fillWidth: true
                                label: "GPU"
                                detail: backend.gpuUsageValue < 0 ? "N/A" : Math.round(backend.gpuUsageValue) + "%"
                                value: backend.gpuUsageValue
                                accent: backend.accentColor
                            }
                            MetricRing {
                                Layout.fillWidth: true
                                label: "内存"
                                detail: backend.memoryUsageValue < 0 ? "--" : Math.round(backend.memoryUsageValue) + "%"
                                value: backend.memoryUsageValue
                                accent: window.mixColors(backend.accentColor, backend.textColor, 0.42)
                            }
                        }

                        MonitorSparkline {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 82
                            cpuValues: window.cpuHistory
                            gpuValues: window.gpuHistory
                            memoryValues: window.memoryHistory
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 1
                            rowSpacing: 5
                            columnSpacing: 5
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 28
                                radius: 10
                                color: window.withAlpha(backend.surfaceAltColor, 0.22)
                                border.width: 1
                                border.color: window.withAlpha(backend.accent2Color, 0.22)
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    text: backend.latencyMetricText + "    " + backend.fpsMetricText
                                    color: backend.textColor
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 28
                                radius: 10
                                color: window.withAlpha(backend.surfaceAltColor, 0.18)
                                border.width: 1
                                border.color: window.withAlpha(backend.accentColor, 0.18)
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    text: backend.cpuMetricText + "  |  " + backend.gpuMetricText
                                    color: backend.mutedColor
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        ScrollView {
            id: mainScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.interactive: true

            Component.onCompleted: {
                if (contentItem) {
                    contentItem.boundsBehavior = Flickable.StopAtBounds
                    contentItem.boundsMovement = Flickable.StopAtBounds
                    contentItem.flickDeceleration = 9000
                    contentItem.maximumFlickVelocity = 3400
                    contentItem.pixelAligned = true
                }
            }

            ColumnLayout {
                width: mainScroll.availableWidth
                spacing: window.compactLayout ? 10 : 12

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: visualCardLayout.implicitHeight + (window.compactLayout ? 24 : 30)
                    clip: true
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: visualCardLayout
                        anchors.fill: parent
                        anchors.margins: window.compactLayout ? 12 : 16
                        spacing: window.compactLayout ? 8 : 10

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Label {
                                text: "外观与背景"
                                color: backend.textColor
                                font.pixelSize: 22
                                font.bold: true
                            }
                            HoverInfoLabel {
                                Layout.fillWidth: true
                                text: backend.backgroundStatusText
                                fullText: backend.backgroundStatusText
                                color: backend.mutedColor
                                horizontalAlignment: Text.AlignRight
                            }
                        }

                        GridLayout {
                            id: visualSettingsGrid
                            Layout.fillWidth: true
                            columns: window.adaptiveColumns(width, 980, 620) > 1 ? 2 : 1
                            columnSpacing: window.compactLayout ? 10 : 12
                            rowSpacing: window.compactLayout ? 8 : 10

                            ThemedGroupBox {
                                title: "外观设置"
                                titleHelpText: "精简主题、透明度和保存入口，减少面板层级与滚动高度。"
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: visualSettingsGrid.columns === 1 ? 0 : 360
                                Layout.alignment: Qt.AlignTop
                                implicitHeight: appearanceLayout.implicitHeight + 26

                                GridLayout {
                                    id: appearanceLayout
                                    anchors.fill: parent
                                    columns: 3
                                    columnSpacing: 10
                                    rowSpacing: 8

                                    FormLabel { text: "透明度" }
                                    ThemedSlider {
                                        id: opacitySlider
                                        Layout.fillWidth: true
                                        from: 0
                                        to: 100
                                        stepSize: 1
                                        onMoved: backend.updateVisualSettings(window.collectSettings())
                                    }
                                    Label {
                                        text: Math.round(opacitySlider.value) + "%"
                                        color: backend.textColor
                                        horizontalAlignment: Text.AlignRight
                                        verticalAlignment: Text.AlignVCenter
                                    }

                                    FormLabel { text: "主题" }
                                    ThemedComboBox {
                                        id: themeCombo
                                        Layout.columnSpan: 2
                                        Layout.fillWidth: true
                                        helpText: "选择当前界面的主题风格。"
                                        model: ["极夜青辉", "紫电星云", "熔岩赤曜", "自定义主题"]
                                        onActivated: backend.updateVisualSettings(window.collectSettings())
                                    }

                                    FormLabel { text: "主题色" }
                                    ThemedTextField {
                                        id: customThemeField
                                        Layout.fillWidth: true
                                        placeholderText: "例如 #5EF2FF"
                                    }
                                    SecondaryButton {
                                        text: "应用"
                                        Layout.preferredWidth: 84
                                        helpText: "将输入的主题色立即应用到当前面板。"
                                        onClicked: {
                                            themeCombo.currentIndex = themeCombo.find("自定义主题")
                                            backend.updateVisualSettings(window.collectSettings())
                                        }
                                    }

                                    Item { Layout.columnSpan: 1 }
                                    SecondaryButton {
                                        text: "保存当前配置"
                                        Layout.columnSpan: 2
                                        Layout.fillWidth: true
                                        helpText: "保存当前主题、背景和参数配置，便于下次直接恢复。"
                                        onClicked: backend.saveSettings(window.collectSettings())
                                    }
                                }
                            }

                            ThemedGroupBox {
                                title: "背景图片"
                                titleHelpText: "只保留本地图片背景，减少多媒体背景带来的布局和渲染开销。"
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: visualSettingsGrid.columns === 1 ? 0 : 360
                                Layout.alignment: Qt.AlignTop
                                implicitHeight: backgroundImageLayout.implicitHeight + 26

                                GridLayout {
                                    id: backgroundImageLayout
                                    anchors.fill: parent
                                    columns: 3
                                    columnSpacing: 10
                                    rowSpacing: 8

                                    FormLabel { text: "图片路径" }
                                    ThemedTextField {
                                        id: backgroundImageField
                                        Layout.columnSpan: 2
                                        Layout.fillWidth: true
                                        placeholderText: "选择本地图片作为面板背景..."
                                        onEditingFinished: {
                                            backend.setBackgroundVideoPath("")
                                            backend.setBackgroundVideoUrl("")
                                            backend.setBackgroundImagePath(text)
                                        }
                                    }

                                    Item { Layout.columnSpan: 1 }
                                    SecondaryButton {
                                        text: "上传背景图"
                                        Layout.fillWidth: true
                                        helpText: "选择本地图片作为面板背景，会自动切换到图片模式。"
                                        onClicked: backgroundImageDialog.open()
                                    }
                                    SecondaryButton {
                                        text: "清除背景"
                                        Layout.fillWidth: true
                                        helpText: "清空当前背景图，恢复为默认渐变背景。"
                                        onClicked: {
                                            backgroundImageField.text = ""
                                            backend.clearBackgroundImage()
                                            backend.setBackgroundVideoPath("")
                                            backend.setBackgroundVideoUrl("")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: buildCardLayout.implicitHeight + 32
                    clip: true
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: buildCardLayout
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10

                        Label {
                            text: "模型编译"
                            color: backend.textColor
                            font.pixelSize: 22
                            font.bold: true
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 4
                            columnSpacing: 10
                            rowSpacing: 8

                            FormLabel { text: "模型路径" }
                            ThemedTextField {
                                id: modelPathField
                                Layout.columnSpan: 2
                                Layout.fillWidth: true
                                placeholderText: "选择 .onnx 文件用于编译..."
                                onEditingFinished: backend.setModelPath(text)
                            }
                            SecondaryButton {
                                text: "浏览模型"
                                Layout.preferredWidth: 96
                                helpText: "从本地选择待编译为 TexPre FP16 引擎的 ONNX 模型文件。"
                                onClicked: modelDialog.open()
                            }

                            FormLabel { text: "结构预览" }
                            SecondaryButton {
                                text: "查看结构"
                                Layout.preferredWidth: 96
                                helpText: "使用 Netron 打开当前模型，查看输入输出与网络结构。"
                                enabled: modelPathField.text.length > 0
                                onClicked: backend.openNetron()
                            }
                            Item { Layout.fillWidth: true }
                            Item { Layout.fillWidth: true }

                            FormLabel { text: "输入尺寸" }
                            WheelValueField {
                                id: imgszField
                                Layout.preferredWidth: window.compactValueWidth
                                placeholderText: "416"
                                wheelStep: 32
                                wheelPrecision: 0
                                integerOnly: true
                                onEditingFinished: window.commitSettings()
                            }
                            ThemedButton {
                                text: backend.conversionRunning ? "编译中..." : "编译 TexPre FP16"
                                Layout.columnSpan: 2
                                Layout.fillWidth: true
                                helpText: "调用 runtime/build_texture_preprocess_engine.exe，将 ONNX 编译为 TexturePreprocessPlugin FP16 Engine。"
                                enabled: !backend.conversionRunning
                                onClicked: backend.startConversion(window.collectSettings())
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: runCardLayout.implicitHeight + 32
                    clip: true
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: runCardLayout
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 12

                        Label {
                            text: "运行控制"
                            color: backend.textColor
                            font.pixelSize: 22
                            font.bold: true
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            columnSpacing: 12
                            rowSpacing: 10

                            Label { text: "引擎文件"; color: backend.textColor }
                            ThemedTextField {
                                id: enginePathField
                                Layout.fillWidth: true
                                placeholderText: "选择已编译好的 .engine 文件..."
                                onEditingFinished: backend.setEnginePath(text)
                            }
                            SecondaryButton { text: "浏览引擎"; helpText: "从本地选择已编译完成的 TensorRT Engine 文件。"; onClicked: engineDialog.open() }

                            HoverInfoLabel {
                                text: backend.modelInfoText
                                fullText: backend.modelInfoText
                                color: backend.mutedColor
                                Layout.columnSpan: 3
                                Layout.fillWidth: true
                            }
                        }

                        GridLayout {
                            id: paramGrid
                            Layout.fillWidth: true
                            columns: width >= 980 ? 2 : 1
                            columnSpacing: window.compactLayout ? 10 : 12
                            rowSpacing: window.compactLayout ? 10 : 12

                            ColumnLayout {
                                id: leftParamStack
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1.04
                                Layout.minimumWidth: paramGrid.columns === 1 ? 0 : 470
                                Layout.alignment: Qt.AlignTop
                                spacing: window.compactLayout ? 10 : 12

                                ThemedGroupBox {
                                    title: "基础参数"
                                    titleHelpText: "调整推理范围、阈值和运行模式。"
                                    Layout.fillWidth: true
                                    implicitHeight: basicParamsLayout.implicitHeight + 24

                                    GridLayout {
                                        id: basicParamsLayout
                                        anchors.fill: parent
                                        columns: 4
                                        columnSpacing: 10
                                        rowSpacing: 8

                                        FormLabel { text: "ROI" }
                                        WheelValueField { id: roiField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 32; wheelPrecision: 0; integerOnly: true; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "Conf" }
                                        WheelValueField { id: confField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }

                                        FormLabel { text: "NMS" }
                                        WheelValueField { id: nmsField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "限帧" }
                                        WheelValueField {
                                            id: fpsLimitField
                                            Layout.preferredWidth: window.compactValueWidth
                                            placeholderText: "0"
                                            wheelStep: 5
                                            wheelPrecision: 0
                                            integerOnly: true
                                            onEditingFinished: window.commitSettings()
                                        }

                                        FormLabel { text: "模式" }
                                        ThemedComboBox {
                                            id: pipelineModeBox
                                            Layout.columnSpan: 3
                                            Layout.fillWidth: true
                                            helpText: "切换推理运行通道：性能模式更轻，调试模式更适合排查问题。"
                                            model: ["性能模式", "调试模式"]
                                            onActivated: window.commitSettings()
                                        }

                                        FormLabel { text: "采集" }
                                        HoverInfoLabel {
                                            text: backend.capturePathText
                                            fullText: backend.capturePathText
                                            color: backend.accent2Color
                                            Layout.columnSpan: 3
                                            Layout.fillWidth: true
                                        }
                                    }
                                }

                                ThemedGroupBox {
                                    title: "自瞄参数"
                                    titleHelpText: "配置 PID、Y 轴修正和神经移动曲线。"
                                    Layout.fillWidth: true
                                    implicitHeight: aimParamsLayout.implicitHeight + 24

                                    GridLayout {
                                        id: aimParamsLayout
                                        anchors.fill: parent
                                        columns: 4
                                        columnSpacing: 10
                                        rowSpacing: 8

                                        FormLabel { text: "PID-P" }
                                        WheelValueField { id: pidPField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "PID-I" }
                                        WheelValueField { id: pidIField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.001; wheelPrecision: 3; onEditingFinished: window.commitSettings() }

                                        FormLabel { text: "PID-D" }
                                        WheelValueField { id: pidDField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.001; wheelPrecision: 3; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "Y轴" }
                                        WheelValueField { id: yOffsetField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }

                                        ThemedCheckBox {
                                            id: neuralMotionBox
                                            text: "启用神经移动"
                                            Layout.columnSpan: 4
                                            onToggled: window.commitSettings()
                                        }

                                        FormLabel { text: "曲率" }
                                        ThemedSlider {
                                            id: neuralCurvatureSlider
                                            Layout.columnSpan: 3
                                            Layout.fillWidth: true
                                            from: 0
                                            to: 60
                                            stepSize: 1
                                            onMoved: window.commitSettings()
                                        }

                                        FormLabel { text: "微抖" }
                                        ThemedSlider {
                                            id: neuralTremorSlider
                                            Layout.columnSpan: 3
                                            Layout.fillWidth: true
                                            from: 0
                                            to: 160
                                            stepSize: 1
                                            value: Number(neuralTremorField.text) * 100.0
                                            onMoved: {
                                                neuralTremorField.text = (value / 100.0).toFixed(2)
                                                window.commitSettings()
                                            }
                                        }
                                    }

                                    WheelValueField {
                                        id: neuralTremorField
                                        visible: false
                                        wheelStep: 0.01
                                        wheelPrecision: 2
                                        clampEnabled: true
                                        minimumValue: 0.0
                                        maximumValue: 1.60
                                    }
                                }
                            }

                            ThemedGroupBox {
                                title: "扳机、粘性与压枪"
                                titleHelpText: "控制扳机触发、粘性、卡尔曼预测和压枪。"
                                Layout.fillWidth: true
                                Layout.preferredWidth: 0.96
                                Layout.minimumWidth: paramGrid.columns === 1 ? 0 : 470
                                Layout.alignment: Qt.AlignTop
                                implicitHeight: triggerParamsLayout.implicitHeight + 24

                                ColumnLayout {
                                    id: triggerParamsLayout
                                    anchors.fill: parent
                                    spacing: 8

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: 4
                                        columnSpacing: 10
                                        rowSpacing: 8

                                        FormLabel { text: "扳机模式" }
                                        ThemedComboBox {
                                            id: triggerModeBox
                                            Layout.columnSpan: 3
                                            Layout.fillWidth: true
                                            helpText: "关闭表示只检测不触发；连续单点会按间隔点射；连续长按开火会持续触发。"
                                            model: ["关闭", "连续单点", "连续长按开火"]
                                            onActivated: window.commitSettings()
                                        }

                                        FormLabel { text: "间隔" }
                                        WheelValueField { id: triggerDelayField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 5; wheelPrecision: 1; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "预测" }
                                        WheelValueField {
                                            id: kalmanPredField
                                            Layout.preferredWidth: window.compactValueWidth
                                            wheelStep: 0.1
                                            wheelPrecision: 1
                                            clampEnabled: true
                                            minimumValue: 0.0
                                            maximumValue: 4.0
                                            placeholderText: "0.0~4.0"
                                            onEditingFinished: window.commitSettings()
                                        }

                                        FormLabel { text: "粘性强度" }
                                        WheelValueField { id: stickIntField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "粘性半径" }
                                        WheelValueField { id: stickRadField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.01; wheelPrecision: 3; onEditingFinished: window.commitSettings() }

                                        FormLabel { text: "压枪力度" }
                                        WheelValueField { id: recoilStrengthField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 0.1; wheelPrecision: 2; onEditingFinished: window.commitSettings() }
                                        FormLabel { text: "压枪延迟" }
                                        WheelValueField { id: recoilDelayField; Layout.preferredWidth: window.compactValueWidth; wheelStep: 5; wheelPrecision: 1; onEditingFinished: window.commitSettings() }
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: 2
                                        columnSpacing: 14
                                        rowSpacing: 8
                                        ThemedCheckBox { id: stickEnableBox; text: "启用锁定粘性"; Layout.fillWidth: true; onToggled: window.commitSettings() }
                                        ThemedCheckBox { id: kalmanEnableBox; text: "启用卡尔曼滤波轨迹预测"; Layout.fillWidth: true; onToggled: window.commitSettings() }
                                        ThemedCheckBox { id: recoilEnableBox; text: "启用压枪"; Layout.fillWidth: true; onToggled: window.commitSettings() }
                                        ThemedCheckBox { id: triggerRecoilEnableBox; text: "启用扳机压枪"; Layout.fillWidth: true; onToggled: window.commitSettings() }
                                        ThemedCheckBox { id: lghubBox; text: "启用 LGHub 驱动自瞄"; Layout.fillWidth: true; onToggled: window.commitSettings() }
                                    }
                                }
                            }
                        }

                        GridLayout {
                            id: auxControlGrid
                            Layout.fillWidth: true
                            columns: width >= 920 ? 2 : 1
                            columnSpacing: window.compactLayout ? 10 : 12
                            rowSpacing: window.compactLayout ? 10 : 12

                            ThemedGroupBox {
                                title: "锁定类别"
                                titleHelpText: "勾选需要参与锁定的目标类别。"
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: auxControlGrid.columns === 1 ? 0 : 320
                                Layout.alignment: Qt.AlignTop
                                implicitHeight: auxRightStack.implicitHeight

                                ListView {
                                    id: classListView
                                    anchors.fill: parent
                                    anchors.margins: 4
                                    model: backend.classModel
                                    spacing: 4
                                    clip: true
                                    cacheBuffer: 160
                                    reuseItems: true
                                    delegate: Rectangle {
                                        width: classListView.width
                                        height: 30
                                        radius: 9
                                        color: window.listRowFillColor
                                        border.color: backend.accent2Color
                                        border.width: 1

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 5
                                            spacing: 6
                                            ThemedCheckBox {
                                                checked: model.checked
                                                onToggled: backend.setClassChecked(index, checked)
                                            }
                                            HoverInfoLabel {
                                                Layout.fillWidth: true
                                                text: model.display
                                                fullText: model.display
                                                color: backend.textColor
                                            }
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                id: auxRightStack
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: auxControlGrid.columns === 1 ? 0 : 320
                                Layout.alignment: Qt.AlignTop
                                spacing: window.compactLayout ? 10 : 12

                                ThemedGroupBox {
                                    title: "触发按键"
                                    titleHelpText: "设置自瞄键和扳机键，支持录入、显示与一键重置。"
                                    Layout.fillWidth: true
                                    implicitHeight: Math.max(keyGroupLayout.implicitHeight + 24, 112)

                                    GridLayout {
                                        id: keyGroupLayout
                                        anchors.fill: parent
                                        columns: 1
                                        rowSpacing: 8

                                        GridLayout {
                                            Layout.fillWidth: true
                                            columns: 4
                                            columnSpacing: 8
                                            rowSpacing: 6
                                            FormLabel { text: "自瞄键" }
                                            ThemedTextField {
                                                id: aimKeysField
                                                Layout.preferredWidth: 78
                                                placeholderText: "2"
                                                onEditingFinished: window.commitSettings()
                                            }
                                            HoverInfoLabel {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                text: backend.aimKeysDisplayValue
                                                fullText: backend.aimKeysDisplayValue
                                                color: backend.mutedColor
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                            RowLayout {
                                                spacing: 6
                                                SecondaryButton {
                                                    text: backend.currentRecordTarget === "aim" ? "录入中..." : "录入"
                                                    Layout.preferredWidth: 72
                                                    enabled: !backend.recordingActive
                                                    onClicked: backend.startKeyRecord("aim")
                                                }
                                                SecondaryButton {
                                                    text: "重置"
                                                    Layout.preferredWidth: 58
                                                    onClicked: backend.resetKeys("aim")
                                                }
                                            }
                                        }

                                        GridLayout {
                                            Layout.fillWidth: true
                                            columns: 4
                                            columnSpacing: 8
                                            rowSpacing: 6
                                            FormLabel { text: "扳机键" }
                                            ThemedTextField {
                                                id: triggerKeysField
                                                Layout.preferredWidth: 78
                                                placeholderText: "1"
                                                onEditingFinished: window.commitSettings()
                                            }
                                            HoverInfoLabel {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                text: backend.triggerKeysDisplayValue
                                                fullText: backend.triggerKeysDisplayValue
                                                color: backend.mutedColor
                                                verticalAlignment: Text.AlignVCenter
                                            }
                                            RowLayout {
                                                spacing: 6
                                                SecondaryButton {
                                                    text: backend.currentRecordTarget === "trigger" ? "录入中..." : "录入"
                                                    Layout.preferredWidth: 72
                                                    enabled: !backend.recordingActive
                                                    onClicked: backend.startKeyRecord("trigger")
                                                }
                                                SecondaryButton {
                                                    text: "重置"
                                                    Layout.preferredWidth: 58
                                                    onClicked: backend.resetKeys("trigger")
                                                }
                                            }
                                        }
                                    }
                                }

                                ThemedGroupBox {
                                    title: "ESP32 串口"
                                    titleHelpText: "串口控制后端状态和快速检测。"
                                    Layout.fillWidth: true
                                    implicitHeight: Math.max(esp32Layout.implicitHeight + 24, 150)

                                    GridLayout {
                                        id: esp32Layout
                                        anchors.fill: parent
                                        columns: 4
                                        columnSpacing: 8
                                        rowSpacing: 7

                                        ThemedCheckBox {
                                            id: esp32EnableBox
                                            text: "启用 ESP32"
                                            Layout.columnSpan: 2
                                            onToggled: window.commitSettings()
                                        }
                                        HoverInfoLabel {
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            text: backend.esp32ScanStatusValue
                                            fullText: backend.esp32ScanStatusValue
                                            color: backend.mutedColor
                                            horizontalAlignment: Text.AlignRight
                                        }

                                        FormLabel { text: "串口" }
                                        ThemedTextField {
                                            id: esp32PortField
                                            Layout.preferredWidth: 96
                                            placeholderText: "COM3"
                                            onEditingFinished: window.commitSettings()
                                        }
                                        FormLabel { text: "波特率" }
                                        WheelValueField {
                                            id: esp32BaudField
                                            Layout.preferredWidth: 104
                                            placeholderText: "115200"
                                            wheelStep: 9600
                                            wheelPrecision: 0
                                            integerOnly: true
                                            onEditingFinished: window.commitSettings()
                                        }

                                        SecondaryButton {
                                            text: "刷新"
                                            Layout.fillWidth: true
                                            enabled: !backend.esp32ScanRunningValue
                                            onClicked: backend.refreshEsp32SerialPorts()
                                        }
                                        SecondaryButton {
                                            text: "自动探测"
                                            Layout.fillWidth: true
                                            enabled: !backend.esp32ScanRunningValue
                                            onClicked: backend.autoDetectEsp32Serial()
                                        }
                                        SecondaryButton {
                                            text: backend.esp32ScanRunningValue ? "检测中..." : "检测当前"
                                            Layout.columnSpan: 2
                                            Layout.fillWidth: true
                                            enabled: !backend.esp32ScanRunningValue
                                            onClicked: backend.probeEsp32Connection()
                                        }

                                        HoverInfoLabel {
                                            Layout.columnSpan: 4
                                            Layout.fillWidth: true
                                            text: backend.esp32SerialPortsTextValue
                                            fullText: backend.esp32SerialPortsTextValue
                                            color: backend.mutedColor
                                        }
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            ThemedButton {
                                text: backend.pipelineRunning ? "推理运行中..." : "启动极速推理"
                                helpText: "按当前引擎、目标类别和参数配置启动推理与控制流程。"
                                enabled: !backend.pipelineRunning
                                onClicked: backend.startPipeline(window.collectSettings())
                            }
                            SecondaryButton {
                                text: "停止推理"
                                helpText: "停止当前推理进程，并中断相关运行状态。"
                                enabled: backend.pipelineRunning
                                onClicked: backend.stopPipeline()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: window.compactLayout ? 280 : 320
                    clip: true
                    radius: window.cardRadius
                    color: window.withAlpha(backend.surfaceColor, window.cardFillAlpha)
                    border.color: backend.accent2Color
                    border.width: 1

                    ColumnLayout {
                        id: logCardLayout
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 12

                        Label {
                            text: "日志"
                            color: backend.textColor
                            font.pixelSize: 22
                            font.bold: true
                        }

                        ListView {
                            id: logListView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            model: backend.logModel
                            cacheBuffer: 420
                            reuseItems: true
                            boundsBehavior: Flickable.StopAtBounds
                            boundsMovement: Flickable.StopAtBounds
                            maximumFlickVelocity: 2800
                            flickDeceleration: 9000

                            delegate: Rectangle {
                                width: logListView.width
                                radius: 10
                                color: model.level === "error" ? window.logErrorFillColor
                                       : model.level === "warn" ? window.logWarnFillColor
                                       : model.level === "success" ? window.logSuccessFillColor
                                       : window.logInfoFillColor
                                border.color: model.level === "error" ? "#8f3a4f"
                                              : model.level === "warn" ? "#8e6f2f"
                                              : model.level === "success" ? "#2c8a63"
                                              : backend.accent2Color
                                border.width: 1
                                implicitHeight: logTextItem.implicitHeight + 18

                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    radius: 9
                                    color: "#ffffff"
                                    opacity: 0.006
                                }

                                Text {
                                    id: logTextItem
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    text: model.text
                                    color: backend.textColor
                                    wrapMode: Text.Wrap
                                    font.family: "Consolas"
                                    font.pixelSize: 13
                                }
                            }

                            Timer {
                                id: logAutoScrollTimer
                                interval: 80
                                repeat: false
                                onTriggered: {
                                    if (logListView.count > 0)
                                        logListView.positionViewAtEnd()
                                }
                            }

                            Connections {
                                target: backend
                                function onLogTextChanged() {
                                    logAutoScrollTimer.restart()
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
