pragma ComponentBehavior: Bound

import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils
import QtQuick3D.Helpers

Rectangle {
    id: previewRoot
    signal modelLoadFailed(string error)

    function reportCurrentModelError() {
        if (modelLoader.status === RuntimeLoader.Error)
            modelLoadFailed(modelLoader.errorString)
    }

    function inverseRotation(rotation) {
        // A quaternion conjugate is the exact inverse for this unit rotation.
        // Negating Euler angles is not an inverse after yaw and pitch combine.
        return Qt.quaternion(
            rotation.scalar,
            -rotation.x,
            -rotation.y,
            -rotation.z
        )
    }

    gradient: Gradient {
        GradientStop { position: 0.0; color: "#263446" }
        GradientStop { position: 0.42; color: "#162230" }
        GradientStop { position: 1.0; color: "#090f17" }
    }

    View3D {
        id: sceneView
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.VeryHigh
            depthPrePassEnabled: true
            specularAAEnabled: true
            aoStrength: 58
            aoDistance: 7
            tonemapMode: SceneEnvironment.TonemapModeFilmic
        }

        Node {
            id: cameraOrigin
            property real pitch: -20
            property real yaw: -35

            // CAD-style turntable: yaw stays on world-up and pitch stays on
            // the horizontal camera axis, so orbiting cannot introduce roll.
            rotation: Quaternion.fromAxesAndAngles(
                Qt.vector3d(0, 1, 0), yaw,
                Qt.vector3d(1, 0, 0), pitch
            )

            PerspectiveCamera {
                id: camera
                property real defaultDistance: 340
                z: defaultDistance
                fieldOfView: 35
                clipNear: 0.1
                clipFar: 100000
            }
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-42, -36, 0)
            brightness: 1.65
            color: "#fff2df"
            castsShadow: true
            shadowFactor: 48
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-18, 138, 0)
            brightness: 0.75
            color: "#a8c8ff"
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(32, 212, 0)
            brightness: 0.52
            color: "#d7e7ff"
        }
        PointLight {
            position: Qt.vector3d(0, 130, 180)
            brightness: 28
            color: "#e4edff"
        }

        // Fine drafting grid plus a stronger major grid creates scale cues
        // without competing visually with the model.
        Model {
            id: fineGrid
            geometry: GridGeometry {
                horizontalLines: 61
                verticalLines: 61
                horizontalStep: 10
                verticalStep: 10
            }
            eulerRotation.x: 90
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#31475d"
                opacity: 0.42
            }
        }
        Model {
            id: majorGrid
            y: fineGrid.y + 0.08
            geometry: GridGeometry {
                horizontalLines: 13
                verticalLines: 13
                horizontalStep: 50
                verticalStep: 50
            }
            eulerRotation.x: 90
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#57728b"
                opacity: 0.52
            }
        }

        RuntimeLoader {
            id: modelLoader
            // Injected by ModelPreviewWindow through the QML context.
            // qmllint disable unqualified
            source: modelSourceUrl
            // qmllint enable unqualified
            property bool normalized: false

            onStatusChanged: {
                if (status === RuntimeLoader.Error) {
                    console.error("Model loading failed: " + errorString)
                    previewRoot.modelLoadFailed(errorString)
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
                const factor = 190 / extent
                scale = Qt.vector3d(factor, factor, factor)
                position = Qt.vector3d(
                    -(bounds.minimum.x + bounds.maximum.x) * factor / 2,
                    -(bounds.minimum.y + bounds.maximum.y) * factor / 2,
                    -(bounds.minimum.z + bounds.maximum.z) * factor / 2
                )
                fineGrid.y = -(sizeY * factor / 2) - 2
                camera.z = camera.defaultDistance
                normalized = true
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton | Qt.MiddleButton
        hoverEnabled: true
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.ArrowCursor
        property real lastX: 0
        property real lastY: 0

        onPressed: function(mouse) {
            lastX = mouse.x
            lastY = mouse.y
        }
        onPositionChanged: function(mouse) {
            const dx = mouse.x - lastX
            const dy = mouse.y - lastY
            lastX = mouse.x
            lastY = mouse.y
            if (mouse.buttons & Qt.RightButton) {
                cameraOrigin.yaw -= dx * 0.32
                cameraOrigin.pitch = Math.max(
                    -89,
                    Math.min(89, cameraOrigin.pitch - dy * 0.32)
                )
            } else if (mouse.buttons & Qt.MiddleButton) {
                const panScale = camera.z / 650
                const right = camera.mapDirectionToScene(Qt.vector3d(1, 0, 0))
                const up = camera.mapDirectionToScene(Qt.vector3d(0, 1, 0))
                cameraOrigin.x += (-right.x * dx + up.x * dy) * panScale
                cameraOrigin.y += (-right.y * dx + up.y * dy) * panScale
                cameraOrigin.z += (-right.z * dx + up.z * dy) * panScale
            }
        }
        onWheel: function(wheel) {
            const zoomFactor = Math.pow(1.0015, -wheel.angleDelta.y)
            camera.z = Math.max(10, Math.min(100000, camera.z * zoomFactor))
            wheel.accepted = true
        }
        onDoubleClicked: function(mouse) {
            if (mouse.button !== Qt.RightButton)
                return
            cameraOrigin.x = 0
            cameraOrigin.y = 0
            cameraOrigin.z = 0
            cameraOrigin.pitch = -20
            cameraOrigin.yaw = -35
            camera.z = camera.defaultDistance
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 16
        width: viewModeText.implicitWidth + 26
        height: 30
        radius: 5
        color: "#c5162230"
        border.color: "#526a82"

        Text {
            id: viewModeText
            anchors.centerIn: parent
            color: "#dbe8f5"
            font.pixelSize: 11
            font.letterSpacing: 1.2
            text: "PERSPECTIVE  ·  SHADED"
        }
    }

    Row {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        spacing: 6

        Repeater {
            model: [
                { "label": "ISO", "yaw": -35, "pitch": -20 },
                { "label": "TOP", "yaw": 0, "pitch": -89 },
                { "label": "FRONT", "yaw": 0, "pitch": 0 },
                { "label": "RIGHT", "yaw": -90, "pitch": 0 }
            ]
            delegate: Rectangle {
                id: viewButton
                required property var modelData
                width: viewLabel.implicitWidth + 20
                height: 30
                radius: 5
                color: viewMouse.containsMouse ? "#d12f475d" : "#c5162230"
                border.color: viewMouse.containsMouse ? "#7ea4c8" : "#526a82"

                Text {
                    id: viewLabel
                    anchors.centerIn: parent
                    color: "#e2edf7"
                    font.pixelSize: 11
                    font.bold: true
                    text: viewButton.modelData.label
                }
                MouseArea {
                    id: viewMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        cameraOrigin.yaw = viewButton.modelData.yaw
                        cameraOrigin.pitch = viewButton.modelData.pitch
                    }
                }
            }
        }
    }

    Rectangle {
        id: axisPanel
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 18
        anchors.bottomMargin: 52
        width: 124
        height: 142
        radius: 10
        color: "#c20e1824"
        border.color: "#526b83"
        visible: modelLoader.status !== RuntimeLoader.Error

        Text {
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.topMargin: 8
            color: "#8299ae"
            font.pixelSize: 9
            font.letterSpacing: 1.5
            text: "WORLD"
        }

        View3D {
            id: axisView
            anchors.fill: parent
            anchors.topMargin: 16
            anchors.bottomMargin: 18
            renderMode: View3D.Offscreen
            environment: SceneEnvironment {
                backgroundMode: SceneEnvironment.Transparent
                antialiasingMode: SceneEnvironment.MSAA
                antialiasingQuality: SceneEnvironment.High
            }
            camera: axisCamera

            OrthographicCamera {
                id: axisCamera
                z: 300
                horizontalMagnification: 600
                verticalMagnification: 600
            }
            Node {
                id: axisGizmo
                scale: Qt.vector3d(0.003, 0.003, 0.003)
                rotation: previewRoot.inverseRotation(cameraOrigin.rotation)

                Model {
                    geometry: SphereGeometry { radius: 2.7; rings: 16; segments: 16 }
                    materials: DefaultMaterial { diffuseColor: "#d8e6f4"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.35; length: 24; rings: 1; segments: 16 }
                    position.x: 12
                    eulerRotation.z: -90
                    materials: DefaultMaterial { diffuseColor: "#f05b61"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.35; length: 24; rings: 1; segments: 16 }
                    position.y: 12
                    materials: DefaultMaterial { diffuseColor: "#65c779"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.35; length: 24; rings: 1; segments: 16 }
                    position.z: 12
                    eulerRotation.x: 90
                    materials: DefaultMaterial { diffuseColor: "#4d9cf5"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.8; length: 9; rings: 1; segments: 16 }
                    position.x: 28.5
                    eulerRotation.z: -90
                    materials: DefaultMaterial { diffuseColor: "#f05b61"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.8; length: 9; rings: 1; segments: 16 }
                    position.y: 28.5
                    materials: DefaultMaterial { diffuseColor: "#65c779"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.8; length: 9; rings: 1; segments: 16 }
                    position.z: 28.5
                    eulerRotation.x: 90
                    materials: DefaultMaterial { diffuseColor: "#4d9cf5"; lighting: DefaultMaterial.NoLighting }
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            spacing: 12
            Text { color: "#f05b61"; font.bold: true; font.pixelSize: 10; text: "X" }
            Text { color: "#65c779"; font.bold: true; font.pixelSize: 10; text: "Y" }
            Text { color: "#4d9cf5"; font.bold: true; font.pixelSize: 10; text: "Z" }
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
        width: controlsText.implicitWidth + 28
        height: controlsText.implicitHeight + 14
        radius: 6
        color: "#c30d1721"
        border.color: "#40566b"
        visible: modelLoader.status !== RuntimeLoader.Error

        Text {
            id: controlsText
            anchors.centerIn: parent
            color: "#c9d7e4"
            font.pixelSize: 11
            // Injected by ModelPreviewWindow through the QML context.
            // qmllint disable unqualified
            text: modelControlsHint
            // qmllint enable unqualified
        }
    }
}
