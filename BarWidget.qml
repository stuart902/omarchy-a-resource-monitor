import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons

BarWidget {
  id: root
  moduleName: "tablet.resource-monitor"

  property int cpu: 0
  property int memory: 0
  property bool available: false
  readonly property string executable: Quickshell.env("HOME") + "/.local/bin/resource-monitor-launch"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function metricColor(value) {
    if (value >= 90) return bar ? bar.urgent : Commons.Color.urgent
    if (value >= 70) return Commons.Color.accent
    return bar ? bar.barForeground : Commons.Color.foreground
  }

  function refresh() {
    if (!stats.running) stats.running = true
  }

  Component.onDestruction: {
    if (stats && stats.running) stats.running = false
  }

  Timer {
    interval: 2000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Process {
    id: stats
    command: [Quickshell.env("HOME") + "/.local/bin/resource-monitor", "--stats"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var values = String(text || "").trim().split(/\s+/)
        root.available = values.length === 2 && values.every(function(value) {
          return /^\d+$/.test(value) && Number(value) <= 100
        })
        if (root.available) {
          root.cpu = Number(values[0])
          root.memory = Number(values[1])
        }
      }
    }
  }

  component Metric: Item {
    id: metric
    required property string label
    required property int value

    width: Style.space(49)
    height: Style.space(18)

    Text {
      id: caption
      anchors.left: parent.left
      anchors.top: parent.top
      text: metric.label
      color: button.foreground
      font.family: button.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Text {
      anchors.right: parent.right
      anchors.baseline: caption.baseline
      text: root.available ? metric.value + "%" : "—"
      color: root.available ? root.metricColor(metric.value) : button.foreground
      font.family: button.fontFamily
      font.pixelSize: Style.font.caption
    }

    Rectangle {
      id: track
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: Style.space(3)
      radius: height / 2
      color: Qt.rgba(button.foreground.r, button.foreground.g, button.foreground.b, 0.2)

      Rectangle {
        width: root.available ? track.width * metric.value / 100 : 0
        height: track.height
        radius: height / 2
        color: root.metricColor(metric.value)
      }
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    hasVisualContent: true
    fixedWidth: root.vertical ? -1 : Style.space(128)
    tooltipText: "Resource Monitor\n" + (root.available
      ? "CPU " + root.cpu + "%  Memory " + root.memory + "%"
      : "Resource readings unavailable") + "\nOpen task manager"
    onPressed: root.bar.run(Util.shellQuote(root.executable))

    Row {
      anchors.centerIn: parent
      spacing: Style.space(7)

      Metric { label: "CPU"; value: root.cpu }

      Rectangle {
        width: 1
        height: Style.space(17)
        anchors.verticalCenter: parent.verticalCenter
        color: Qt.rgba(button.foreground.r, button.foreground.g, button.foreground.b, 0.22)
      }

      Metric { label: "RAM"; value: root.memory }
    }
  }
}
