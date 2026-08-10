/* eslint-env jest */

jest.mock('react-native-vision-camera', () => ({
  Camera: require('react-native').View,
  useCameraDevice: () => undefined,
  useCameraPermission: () => ({ hasPermission: true, requestPermission: jest.fn() }),
  useFrameProcessor: processor => processor,
  runAtTargetFps: (_fps, callback) => callback(),
}));

jest.mock('vision-camera-resize-plugin', () => ({
  useResizePlugin: () => ({ resize: jest.fn(() => new Uint8Array()) }),
}));

jest.mock('react-native-worklets-core', () => ({
  Worklets: { createRunOnJS: callback => callback },
}));

global.WebSocket = class WebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = WebSocket.OPEN;
  }

  close() {}
  send() {}
};
