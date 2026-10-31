import QtQuick
import Quickshell

// A fresh native registry, with no bar/plugin loaded. This checks the installed
// desktop entry; it does not inspect the already-running desktop's Apps menu.
ShellRoot {
    Timer {
        interval: 1000
        running: true
        onTriggered: {
            var entry = DesktopEntries.byId("resource-monitor")
            var visible = DesktopEntries.applications.values.some(function(app) {
                return app.id === "resource-monitor"
            })
            console.log("APPS_PROBE=" + JSON.stringify({
                found: !!entry,
                visible: visible,
                command: entry ? entry.command : [],
                name: entry ? entry.name : ""
            }))
            if (visible && Quickshell.env("APPS_PROBE_EXECUTE") === "1") entry.execute()
            finish.start()
        }
    }
    Timer {
        id: finish
        interval: 500
        onTriggered: Qt.quit()
    }
}
