import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils
import QtQuick3D.Helpers

Rectangle {
    signal modelLoadFailed(string error)

    function reportCurrentModelError() {
        if (modelLoader.status === RuntimeLoader.Error)
            modelLoadFailed(modelLoader.errorString)
    }

    gradient: Gradient {
        GradientStop { position: 0.0; color: "#283446" }
        GradientStop { position: 0.48; color: "#18212e" }
        GradientStop { position: 1.0; color: "#0c111a" }
    }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoStrength: 35
            aoDistance: 8
            tonemapMode: SceneEnvironment.TonemapModeFilmic
        }

        Node {
            id: cameraOrigin
            property real pitch: -12
            property real yaw: -28
            eulerRotation: Qt.vector3d(pitch, yaw, 0)

            PerspectiveCamera {
                id: camera
                z: 300
                clipNear: 0.1
                clipFar: 100000
            }
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-38, -32, 0)
            brightness: 1.8
            color: "#fff2dd"
            castsShadow: true
            shadowFactor: 35
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-12, 142, 0)
            brightness: 0.9
            color: "#a9c7ff"
        }
        PointLight {
            position: Qt.vector3d(0, 120, 150)
            brightness: 35
            color: "#d8e6ff"
        }

        Model {
            id: groundGrid
            geometry: GridGeometry {
                horizontalLines: 41
                verticalLines: 41
                horizontalStep: 10
                verticalStep: 10
            }
            eulerRotation.x: 90
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#40546d"
                opacity: 0.72
            }
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
                groundGrid.y = -(sizeY * factor / 2) - 2
                normalized = true
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton | Qt.MiddleButton
        hoverEnabled: true
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
                cameraOrigin.yaw -= dx * 0.35
                cameraOrigin.pitch = Math.max(-89, Math.min(89, cameraOrigin.pitch - dy * 0.35))
            } else if (mouse.buttons & Qt.MiddleButton) {
                const panScale = camera.z / 600
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
            cameraOrigin.pitch = -12
            cameraOrigin.yaw = -28
            camera.z = 300
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 18
        anchors.bottomMargin: 52
        width: 132
        height: 132
        radius: 66
        color: "#99101825"
        border.color: "#5d7894"
        border.width: 1
        visible: modelLoader.status !== RuntimeLoader.Error

        View3D {
            id: axisView
            anchors.fill: parent
            renderMode: View3D.Offscreen
            environment: SceneEnvironment {
                backgroundMode: SceneEnvironment.Transparent
                antialiasingMode: SceneEnvironment.MSAA
                antialiasingQuality: SceneEnvironment.Medium
            }
            camera: axisCamera
            OrthographicCamera {
                id: axisCamera
                z: 300
                horizontalMagnification: 600
                verticalMagnification: 600
            }
            Node {
                // The helper geometries use scene units much larger than the
                // compact overlay needs. Keep the complete gizmo at 1% scale.
                scale: Qt.vector3d(0.003, 0.003, 0.003)
                eulerRotation: Qt.vector3d(-cameraOrigin.pitch, -cameraOrigin.yaw, 0)
                Model {
                    geometry: SphereGeometry { radius: 2.5; rings: 16; segments: 16 }
                    materials: DefaultMaterial { diffuseColor: "#d8e6f4"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.25; length: 22; rings: 1; segments: 16 }
                    position.x: 11
                    eulerRotation.z: -90
                    materials: DefaultMaterial { diffuseColor: "#ef5350"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.25; length: 22; rings: 1; segments: 16 }
                    position.y: 11
                    materials: DefaultMaterial { diffuseColor: "#66bb6a"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.25; length: 22; rings: 1; segments: 16 }
                    position.z: 11
                    eulerRotation.x: 90
                    materials: DefaultMaterial { diffuseColor: "#42a5f5"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.5; length: 8; rings: 1; segments: 16 }
                    position.x: 26
                    eulerRotation.z: -90
                    materials: DefaultMaterial { diffuseColor: "#ef5350"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.5; length: 8; rings: 1; segments: 16 }
                    position.y: 26
                    materials: DefaultMaterial { diffuseColor: "#66bb6a"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.5; length: 8; rings: 1; segments: 16 }
                    position.z: 26
                    eulerRotation.x: 90
                    materials: DefaultMaterial { diffuseColor: "#42a5f5"; lighting: DefaultMaterial.NoLighting }
                }
            }
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
