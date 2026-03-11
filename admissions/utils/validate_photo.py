## Install the headless version of OpenCV (recommended for servers) to avoid CV2 errors related to missing GUI libraries. If you need GUI features, use the standard opencv-python package instead.
#pip install opencv-python-headless => to manage dependencies better and avoid conflicts with GUI libraries on servers. If you need GUI features, use opencv-python instead.
import cv2 
import numpy as np
from PIL import Image, ImageStat
from django.core.exceptions import ValidationError


def validate_passport_photo(file):
    # ---------- 1. FILE SIZE ----------
    if file.size < 20_000:
        raise ValidationError(
            "Image appears too small or compressed. Upload a studio-quality passport photo."
        )

    # ---------- 2. LOAD IMAGE ----------
    image = Image.open(file).convert("RGB")
    width, height = image.size

    if width < 400 or height < 500:
        raise ValidationError(
            "Image must be at least 400x500 pixels (passport portrait). please get a passport studio photo"
        )

    if height <= width:
        raise ValidationError(
            "Image must be portrait orientation (taller than wide). please get a passport studio photo"
        )

    img_array = np.array(image)
    img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

    # ---------- 3. FACE DETECTION ----------
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.3,
        minNeighbors=5,
        minSize=(120, 120)
    )

    if len(faces) == 0:
        raise ValidationError("No face detected. Upload a clear passport-style photo.")

    if len(faces) > 1:
        raise ValidationError("Multiple faces detected. Upload a single-person photo.")

    # ---------- 4. BRIGHTNESS CHECK ----------
    brightness = ImageStat.Stat(image.convert("L")).mean[0]

    if brightness < 75:
        raise ValidationError(
            "Image is too dark. Ensure proper studio lighting."
        )

    # ---------- 5. BACKGROUND CHECK (EDGE-BASED) ----------
    h, w = gray.shape
    edge_width = int(w * 0.15)
    edge_height = int(h * 0.15)

    # Extract border regions
    top = gray[0:edge_height, :]
    bottom = gray[h - edge_height:h, :]
    left = gray[:, 0:edge_width]
    right = gray[:, w - edge_width:w]

    edges = np.concatenate(
        [top.flatten(), bottom.flatten(), left.flatten(), right.flatten()]
    )

    # Count light pixels (studio white / off-white)
    light_pixels = np.sum(edges > 180)
    light_ratio = light_pixels / edges.size

    # Require at least 60% light background in edges
    if light_ratio < 0.50:
        raise ValidationError(
            "Background must be light and uniform (studio passport style)."
        )
    return True
