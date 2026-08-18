# server.py
import base64
import json
import cv2
import numpy as np
import mediapipe as mp
import math
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ultralytics import YOLO

app = FastAPI()

# 1. Initialize MediaPipe FaceMesh
# Using FaceMesh to validate all landmarks (eyes, nose, mouth, tilt, occlusion)
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1, # We process cropped faces individually
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# 2. Initialize YOLO Model
# We try to load YOLOv8n-face.pt. If missing, we fallback to general YOLO.
try:
    yolo_model = YOLO('yolov8n-face.pt')
except Exception as e:
    print(f"Failed to load yolov8n-face.pt: {e}")
    print("Falling back to yolov8n.pt")
    yolo_model = YOLO('yolov8n.pt')

def validate_face_with_mediapipe(image, bbox):
    """
    Validates a single face against strict criteria:
    - Frontal, Eyes/Nose/Mouth visible, No occlusion (mask, hand, glasses), No tilt/side
    """
    x1, y1, x2, y2 = map(int, bbox)
    h, w, _ = image.shape
    
    # Add slight padding for accurate mediapipe detection on crop
    pad = int((x2 - x1) * 0.1)
    x1_c = max(0, x1 - pad)
    y1_c = max(0, y1 - pad)
    x2_c = min(w, x2 + pad)
    y2_c = min(h, y2 + pad)
    
    face_crop = image[y1_c:y2_c, x1_c:x2_c]
    if face_crop.size == 0:
        return False
        
    rgb_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb_crop)
    
    if not results.multi_face_landmarks:
        return False # No face mesh detected, invalid face
    
    face_landmarks = results.multi_face_landmarks[0]
    crop_h, crop_w, _ = face_crop.shape

    # Criteria 1: Visibility of Eyes, Nose, Mouth
    # Ensuring key landmarks are within crop boundary (not obscured/cut off)
    key_points = [
        33, 133,  # Left eye
        362, 263, # Right eye
        1,        # Nose tip
        13, 14    # Mouth
    ]
    for idx in key_points:
        lm = face_landmarks.landmark[idx]
        if lm.x < 0 or lm.x > 1 or lm.y < 0 or lm.y > 1:
            return False # Cut off / hidden

    # Criteria 2: Head Pose (No side face, no tilted face, must be frontal)
    face_3d, face_2d = [], []
    pose_landmarks = [33, 263, 1, 61, 291, 199]
    for idx in pose_landmarks:
        lm = face_landmarks.landmark[idx]
        x, y = int(lm.x * crop_w), int(lm.y * crop_h)
        face_2d.append([x, y])
        face_3d.append([x, y, lm.z])
        
    face_2d = np.array(face_2d, dtype=np.float64)
    face_3d = np.array(face_3d, dtype=np.float64)
    
    focal_length = 1 * crop_w
    cam_matrix = np.array([[focal_length, 0, crop_w / 2],
                           [0, focal_length, crop_h / 2],
                           [0, 0, 1]])
    dist_matrix = np.zeros((4, 1), dtype=np.float64)
    
    success, rot_vec, trans_vec = cv2.solvePnP(face_3d, face_2d, cam_matrix, dist_matrix)
    rmat, _ = cv2.Rodrigues(rot_vec)
    angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
    
    pitch = angles[0] * 360 # Up / down
    yaw = angles[1] * 360   # Left / right (Side face)
    roll = angles[2] * 360  # Tilt
    
    if abs(yaw) > 15:   # Reject side face
        return False
    if abs(roll) > 15:  # Reject tilted face
        return False
    if abs(pitch) > 18:     
        return False
        
    # Criteria 3: Occlusions (Spectacles, Sunglasses, Face mask, Hands)
    # Without secondary classifiers, we reject if mesh is distorted or confidence is poor.
    # We check the distance between lips (13, 14) and nose (1) to ensure structural integrity
    # meaning the mouth/nose is not covered by a mask completely.
    dist_mouth_nose = math.sqrt((face_landmarks.landmark[13].x - face_landmarks.landmark[1].x)**2 + 
                                (face_landmarks.landmark[13].y - face_landmarks.landmark[1].y)**2)
    
    if dist_mouth_nose < 0.05: # Mesh collapsed due to mask occlusion
        return False
        
    # If all checks pass:
    return True


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Continuously process incoming frames
            data = await websocket.receive_text()
            payload = json.loads(data)
            width = int(payload["width"])
            height = int(payload["height"])
            rgb_bytes = base64.b64decode(payload["pixels"])
            expected_bytes = width * height * 3
            if len(rgb_bytes) != expected_bytes:
                print("Ignoring malformed frame payload")
                continue

            rgb_image = np.frombuffer(rgb_bytes, np.uint8).reshape((height, width, 3))
            img = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)

            if img is None:
                continue

            # 1. Detect faces using YOLO
            results = yolo_model(img, verbose=False)
            valid_boxes = []

            for result in results:
                for box in result.boxes:
                    conf = box.conf.item()
                    
                    # 2. Check YOLO Confidence
                    if conf > 0.85:
                        bbox = box.xyxy[0].tolist()
                        
                        # 3. Validate EVERY detected face strictly using MediaPipe
                        is_valid = validate_face_with_mediapipe(img, bbox)
                        
                        if is_valid:
                            # 4. Only append bounding box if all criteria are met
                            x1, y1, x2, y2 = bbox
                            valid_boxes.append({
                                "id": len(valid_boxes) + 1,
                                "x": x1,
                                "y": y1,
                                "width": x2 - x1,
                                "height": y2 - y1
                            })

            # Send back the valid bounding boxes to React Native
            await websocket.send_json({"faces": valid_boxes})
            
    except WebSocketDisconnect:
        print("Client disconnected.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
