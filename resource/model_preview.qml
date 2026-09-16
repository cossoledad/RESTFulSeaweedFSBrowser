import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

Rectangle {
    signal modelLoadFailed(string error)

    function reportCurrentModelError() {
        if (modelLoader.status === RuntimeLoader.Error)
            modelLoadFailed(modelLoader.errorString)
    }

    color: "#202124"

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: "#202124"
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        Node {
            id: cameraOrigin
            property real pitch: 0
            property real yaw: 0
            eulerRotation: Qt.vector3d(pitch, yaw, 0)

            PerspectiveCamera {
                id: camera
                z: 300
                clipNear: 0.1
                clipFar: 100000
            }
        }

        DirectionalLight {
            eulerRotation.x: -35
            eulerRotation.y: -35
            brightness: 1.5
        }

        DirectionalLight {
            eulerRotation.x: 145
            eulerRotation.y: 145
            brightness: 0.8
        }

        RuntimeLoader {
            id: modelLoader
            source: modelSourceUrl
            property bool normalized: false

            onStatusChanged: {
                if (status === RuntimeLoader.Error) {
                    console.error("Model loading failed: " + errorString)
                    modelLoadFailed(errorString)
                }
            }

            onBoundsChanged: {
                if (normalized)
                    return
                const sizeX = bounds.maximum.x - bounds.minimum.x
                const sizeY = bounds.maximum.y - bounds.minimum.y
                const sizeZ = bounds.maximum.z - bounds.minimum.z
                const extent = Math.max(sizeX, sizeY, sizeZ)
                if (extent <= 0)
                    return
                const factor = 200 / extent
                scale = Qt.vector3d(factor, factor, factor)
                position = Qt.vector3d(
                    -(bounds.minimum.x + bounds.maximum.x) * factor / 2,
                    -(bounds.minimum.y + bounds.maximum.y) * factor / 2,
                    -(bounds.minimum.z + bounds.maximum.z) * factor / 2
                )
                normalized = true
            }
        }
    }

    MouseArea {
        id: cameraController
        anchors.fill: parent
        acceptedButtons: Qt.MiddleButton
        hoverEnabled: true
        property real lastX: 0
        property real lastY: 0

        onPressed: function(mouse) {
            lastX = mouse.x
            lastY = mouse.y
        }

        onPositionChanged: function(mouse) {
            if (!(mouse.buttons & Qt.MiddleButton))
                return
            const dx = mouse.x - lastX
            const dy = mouse.y - lastY
            lastX = mouse.x
            lastY = mouse.y
            if (mouse.modifiers & Qt.ShiftModifier) {
                const panScale = camera.z / 600
                const right = camera.mapDirectionToScene(Qt.vector3d(1, 0, 0))
                const up = camera.mapDirectionToScene(Qt.vector3d(0, 1, 0))
                cameraOrigin.x += (-right.x * dx + up.x * dy) * panScale
                cameraOrigin.y += (-right.y * dx + up.y * dy) * panScale
                cameraOrigin.z += (-right.z * dx + up.z * dy) * panScale
            } else {
                cameraOrigin.yaw -= dx * 0.35
                cameraOrigin.pitch = Math.max(
                    -89,
                    Math.min(89, cameraOrigin.pitch - dy * 0.35)
                )
            }
        }

        onWheel: function(wheel) {
            const zoomFactor = Math.pow(1.0015, -wheel.angleDelta.y)
            camera.z = Math.max(10, Math.min(100000, camera.z * zoomFactor))
            wheel.accepted = true
        }

        onDoubleClicked: function(mouse) {
            if (mouse.button !== Qt.MiddleButton)
                return
            cameraOrigin.x = 0
            cameraOrigin.y = 0
            cameraOrigin.z = 0
            cameraOrigin.pitch = 0
            cameraOrigin.yaw = 0
            camera.z = 300
        }
    }

    Text {
        anchors.centerIn: parent
        width: parent.width * 0.8
        visible: modelLoader.status === RuntimeLoader.Error
        color: "#ff8a80"
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: modelLoader.errorString
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        width: controlsText.implicitWidth + 24
        height: controlsText.implicitHeight + 12
        radius: 5
        color: "#b3000000"
        visible: modelLoader.status !== RuntimeLoader.Error

        Text {
            id: controlsText
            anchors.centerIn: parent
            color: "#eeeeee"
            text: modelControlsHint
        }
    }
}
