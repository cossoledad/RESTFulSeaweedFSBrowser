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

    color: "#202124"

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: "#202124"
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            id: camera
            z: 300
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

    OrbitCameraController {
        anchors.fill: parent
        origin: modelLoader
        camera: camera
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
}
