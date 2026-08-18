import React, { useEffect, useState, useRef, useCallback } from 'react';
import { StyleSheet, Text, View, Dimensions } from 'react-native';
import { Camera, useCameraDevice, useCameraPermission, useFrameProcessor, runAtTargetFps } from 'react-native-vision-camera';
import { useResizer } from 'react-native-vision-camera-resizer';
import { createRunOnJS } from 'react-native-worklets-core';

// React Native exposes the Web-compatible base64 encoder at runtime, but its
// TypeScript globals do not currently declare it.
declare function btoa(data: string): string;

// WEBSOCKET CONFIGURATION: Point this to your Python backend running on your PC
// Note: If using physical device, replace with your PC's local IP address (e.g. 192.168.x.x)
const SERVER_URL = "ws://172.21.0.250:8000/ws";

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get('window');
const FRAME_WIDTH = 480;
const FRAME_HEIGHT = 640;

type BoundingBox = {
  id: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

export default function App() {
  const { hasPermission, requestPermission } = useCameraPermission();
  const device = useCameraDevice('front'); // Use front camera for face detection

  const [faces, setFaces] = useState<BoundingBox[]>([]);
  const ws = useRef<WebSocket | null>(null);
  const { resizer, state, error } = useResizer({
  width: FRAME_WIDTH,
  height: FRAME_HEIGHT,
  channelOrder: 'rgb',
  dataType: 'uint8',
  scaleMode: 'stretch',
  pixelLayout: 'packed',
});
  // 1. Initialize WebSocket connection
  useEffect(() => {
    ws.current = new WebSocket(SERVER_URL);

    ws.current.onopen = () => console.log("Connected to Python backend");

    ws.current.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.faces) {
          // 4. Client receives ONLY the valid bounding boxes.
          // Faces that failed validation simply aren't sent back, clearing their box.
          setFaces(data.faces);
        }
      } catch (err) {
        console.log("Error parsing websocket message", err);
      }
    };

    ws.current.onerror = (e) => console.log("WebSocket error", e.message);
    ws.current.onclose = () => console.log("WebSocket closed");

    return () => {
      ws.current?.close();
    };
  }, []);

  const sendFrameToServer = useCallback((buffer: ArrayBuffer) => {
  const rgbFrame = new Uint8Array(buffer);

  if (ws.current && ws.current.readyState === WebSocket.OPEN) {
    let binary = '';
    const chunkSize = 0x8000;

    for (let index = 0; index < rgbFrame.length; index += chunkSize) {
      binary += String.fromCharCode(
        ...rgbFrame.subarray(index, index + chunkSize)
      );
    }

    ws.current.send(JSON.stringify({
      width: FRAME_WIDTH,
      height: FRAME_HEIGHT,
      pixels: btoa(binary),
    }));
  }
}, []);

const processFrameOnJS = createRunOnJS(sendFrameToServer);
  const frameProcessor = useFrameProcessor((frame) => {
    'worklet';

    runAtTargetFps(15, () => {
      try {
        if (resizer == null) {
          return;
        }

        const resized = resizer.resize(frame);
        const buffer = resized.getPixelBuffer();

        processFrameOnJS(buffer);

        resized.dispose();
      } catch (e) {
        console.log("Error resizing frame: ", e);
      }
    });
  }, [resizer, processFrameOnJS]);

  useEffect(() => {
    if (!hasPermission) {
      requestPermission();
    }
  }, [hasPermission, requestPermission]);

  if (!hasPermission) return <Text>Requesting Camera Permission...</Text>;
  if (!device) return <Text>No Camera Device Found</Text>;

  return (
    <View style={StyleSheet.absoluteFill}>
      <Camera
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={true} // Continuously capture without button presses
        frameProcessor={frameProcessor}
        pixelFormat="yuv"
      />

      {/* 3. Draw Bounding Boxes ONLY for Valid Faces */}
      {faces.map(face => {
        // Compute correct scaling factors.
        // We resized frame to 480x640 before sending to server.
        // Screen dimensions might differ, so we scale the bounding box.
        const scaleX = SCREEN_W / FRAME_WIDTH;
        const scaleY = SCREEN_H / FRAME_HEIGHT;

        return (
          <View
            key={face.id}
            style={[
              styles.faceBox,
              {
                left: face.x * scaleX,
                top: face.y * scaleY,
                width: face.width * scaleX,
                height: face.height * scaleY,
              },
            ]}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  faceBox: {
    position: 'absolute',
    borderWidth: 3,
    borderColor: 'lime',
    backgroundColor: 'transparent',
    borderRadius: 8,
  },
});
