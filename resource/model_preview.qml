pragma ComponentBehavior: Bound

import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils
import QtQuick3D.Helpers

Rectangle {
    id: previewRoot
    property real modelRadius: 100
    property real gridStep: 10
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

    function viewRotation(viewName) {
        const target = Qt.vector3d(0, 0, 0)
        const forward = Qt.vector3d(0, 0, -1)
        if (viewName === "TOP") {
            return Quaternion.lookAt(
                Qt.vector3d(0, 1, 0), target, forward, Qt.vector3d(0, 0, -1)
            )
        }
        if (viewName === "FRONT") {
            return Quaternion.lookAt(
                Qt.vector3d(0, 0, 1), target, forward, Qt.vector3d(0, 1, 0)
            )
        }
        if (viewName === "RIGHT") {
            return Quaternion.lookAt(
                Qt.vector3d(1, 0, 0), target, forward, Qt.vector3d(0, 1, 0)
            )
        }
        // Z-up isometric: camera is above the CAD XY floor and sees the
        // right, front and top faces with no screen-space roll.
        return Quaternion.lookAt(
            Qt.vector3d(1, 1, 1), target, forward, Qt.vector3d(0, 1, 0)
        )
    }

    function trackballPoint(x, y) {
        const diameter = Math.max(1, Math.min(width, height))
        let nx = (2 * x - width) / diameter
        let ny = (height - 2 * y) / diameter
        const lengthSquared = nx * nx + ny * ny
        let nz = 0
        if (lengthSquared <= 1) {
            nz = Math.sqrt(1 - lengthSquared)
        } else {
            const inverseLength = 1 / Math.sqrt(lengthSquared)
            nx *= inverseLength
            ny *= inverseLength
        }
        return Qt.vector3d(nx, ny, nz)
    }

    function applyTrackballRotation(fromPoint, toPoint) {
        const axisX = fromPoint.y * toPoint.z - fromPoint.z * toPoint.y
        const axisY = fromPoint.z * toPoint.x - fromPoint.x * toPoint.z
        const axisZ = fromPoint.x * toPoint.y - fromPoint.y * toPoint.x
        const axisLength = Math.sqrt(
            axisX * axisX + axisY * axisY + axisZ * axisZ
        )
        if (axisLength < 0.000001)
            return
        const dot = Math.max(-1, Math.min(1,
            fromPoint.x * toPoint.x
            + fromPoint.y * toPoint.y
            + fromPoint.z * toPoint.z
        ))
        const angle = Math.atan2(axisLength, dot) * 180 / Math.PI
        const axis = Qt.vector3d(
            axisX / axisLength,
            axisY / axisLength,
            axisZ / axisLength
        )
        // The trackball describes how the model follows the pointer in view
        // space. Apply its inverse to the camera orbit for the same result.
        const cameraDelta = Quaternion.fromAxisAndAngle(axis, -angle)
        cameraOrigin.orbitRotation = cameraOrigin.orbitRotation
            .times(cameraDelta).normalized()
    }

    function bestFitMagnification() {
        const viewportSize = Math.max(1, Math.min(width, height))
        return viewportSize / (2 * modelRadius * 1.22)
    }

    function resetView() {
        cameraOrigin.orbitRotation = viewRotation("ISO")
        camera.x = 0
        camera.y = 0
        camera.z = modelRadius * 4
        camera.defaultDistance = camera.z
        camera.defaultMagnification = bestFitMagnification()
        camera.horizontalMagnification = camera.defaultMagnification
        camera.verticalMagnification = camera.defaultMagnification
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
            property quaternion orbitRotation: previewRoot.viewRotation("ISO")
            rotation: orbitRotation

            OrthographicCamera {
                id: camera
                property real defaultDistance: 340
                property real defaultMagnification: 1
                z: defaultDistance
                horizontalMagnification: defaultMagnification
                verticalMagnification: defaultMagnification
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
                id: fineGridGeometry
                horizontalLines: 61
                verticalLines: 61
                horizontalStep: previewRoot.gridStep
                verticalStep: previewRoot.gridStep
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
            y: fineGrid.y + previewRoot.modelRadius * 0.0005
            geometry: GridGeometry {
                id: majorGridGeometry
                horizontalLines: 13
                verticalLines: 13
                horizontalStep: previewRoot.gridStep * 5
                verticalStep: previewRoot.gridStep * 5
            }
            eulerRotation.x: 90
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#57728b"
                opacity: 0.52
            }
        }

        // Qt Quick 3D is Y-up, while CAD data and the UI use Z-up. Rotating
        // the complete imported scene maps CAD +Z to scene +Y, CAD +Y to
        // scene -Z, and keeps CAD +X unchanged.
        Node {
            id: cadModelSpace
            eulerRotation.x: -90

            RuntimeLoader {
                id: modelLoader
                // Injected by ModelPreviewWindow through the QML context.
                // qmllint disable unqualified
                source: modelSourceUrl
                // qmllint enable unqualified
                property bool framed: false

                function frameModel() {
                    if (framed)
                        return
                    const sizeX = bounds.maximum.x - bounds.minimum.x
                    const sizeY = bounds.maximum.y - bounds.minimum.y
                    const sizeZ = bounds.maximum.z - bounds.minimum.z
                    const diagonal = Math.sqrt(
                        sizeX * sizeX + sizeY * sizeY + sizeZ * sizeZ
                    )
                    if (diagonal <= 0)
                        return

                    // The imported model's exact bounding-box center becomes
                    // the immutable orbit pivot at scene origin.
                    position = Qt.vector3d(
                        -(bounds.minimum.x + bounds.maximum.x) / 2,
                        -(bounds.minimum.y + bounds.maximum.y) / 2,
                        -(bounds.minimum.z + bounds.maximum.z) / 2
                    )
                    previewRoot.modelRadius = diagonal / 2
                    previewRoot.gridStep = Math.pow(
                        10,
                        Math.floor(
                            Math.log(Math.max(previewRoot.modelRadius, 1e-9) / 5)
                            / Math.LN10
                        )
                    )
                    fineGrid.y = -sizeZ / 2 - previewRoot.modelRadius * 0.015
                    camera.clipNear = Math.max(previewRoot.modelRadius * 0.0001, 1e-6)
                    camera.clipFar = Math.max(
                        previewRoot.modelRadius * 20,
                        1
                    )
                    previewRoot.resetView()
                    framed = true
                }

                onStatusChanged: {
                    if (status === RuntimeLoader.Error) {
                        console.error("Model loading failed: " + errorString)
                        previewRoot.modelLoadFailed(errorString)
                    } else if (status === RuntimeLoader.Success) {
                        // Some importers publish their final bounds before the
                        // QML boundsChanged handler is attached.
                        Qt.callLater(frameModel)
                    }
                }
                onBoundsChanged: {
                    if (status === RuntimeLoader.Success)
                        Qt.callLater(frameModel)
                }
            }

            Timer {
                // Importers can publish Success one frame before their final
                // aggregate bounds. Retry briefly so resetView never falls
                // back to an arbitrary distance for a valid model.
                property int attempts: 0
                interval: 16
                repeat: true
                running: modelLoader.status === RuntimeLoader.Success
                    && !modelLoader.framed
                    && attempts < 120
                onTriggered: {
                    attempts += 1
                    modelLoader.frameModel()
                }
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
        property var lastTrackballPoint: Qt.vector3d(0, 0, 1)

        onPressed: function(mouse) {
            lastX = mouse.x
            lastY = mouse.y
            lastTrackballPoint = previewRoot.trackballPoint(mouse.x, mouse.y)
        }
        onPositionChanged: function(mouse) {
            const dx = mouse.x - lastX
            const dy = mouse.y - lastY
            const currentTrackballPoint = previewRoot.trackballPoint(
                mouse.x,
                mouse.y
            )
            lastX = mouse.x
            lastY = mouse.y
            const rightPan = (mouse.buttons & Qt.RightButton)
                && (mouse.modifiers & Qt.ControlModifier)
            if ((mouse.buttons & Qt.MiddleButton) || rightPan) {
                const panScale = 1 / Math.max(
                    camera.verticalMagnification,
                    0.000001
                )
                // Pan the camera in its own image plane. The orbit node stays
                // at the model center, so later rotations keep the same pivot.
                camera.x -= dx * panScale
                camera.y += dy * panScale
            } else if (mouse.buttons & Qt.RightButton) {
                previewRoot.applyTrackballRotation(
                    lastTrackballPoint,
                    currentTrackballPoint
                )
            }
            lastTrackballPoint = currentTrackballPoint
        }
        onWheel: function(wheel) {
            const zoomFactor = Math.pow(1.0015, wheel.angleDelta.y)
            const magnification = Math.max(
                camera.defaultMagnification / 100,
                Math.min(
                    camera.defaultMagnification * 100,
                    camera.verticalMagnification * zoomFactor
                )
            )
            camera.horizontalMagnification = magnification
            camera.verticalMagnification = magnification
            wheel.accepted = true
        }
        onDoubleClicked: function(mouse) {
            if (mouse.button !== Qt.RightButton)
                return
            previewRoot.resetView()
        }
    }

    Row {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        spacing: 6

        Repeater {
            model: [
                { "label": "ISO", "view": "ISO" },
                { "label": "TOP", "view": "TOP" },
                { "label": "FRONT", "view": "FRONT" },
                { "label": "RIGHT", "view": "RIGHT" }
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
                        cameraOrigin.orbitRotation = previewRoot.viewRotation(
                            viewButton.modelData.view
                        )
                        camera.x = 0
                        camera.y = 0
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
                    position.z: -12
                    eulerRotation.x: -90
                    materials: DefaultMaterial { diffuseColor: "#65c779"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: CylinderGeometry { radius: 1.35; length: 24; rings: 1; segments: 16 }
                    position.y: 12
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
                    position.z: -28.5
                    eulerRotation.x: -90
                    materials: DefaultMaterial { diffuseColor: "#65c779"; lighting: DefaultMaterial.NoLighting }
                }
                Model {
                    geometry: ConeGeometry { topRadius: 0; bottomRadius: 3.8; length: 9; rings: 1; segments: 16 }
                    position.y: 28.5
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
