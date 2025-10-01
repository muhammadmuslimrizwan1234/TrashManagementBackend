# models/classifier.py
import cv2
import numpy as np
from sklearn.cluster import KMeans
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image as keras_image
import os
import json

# ---------------- Paths ----------------
MODEL_PATH = os.path.join("models", "model.h5")
CLASS_NAMES_PATH = os.path.join("models", "class_names.json")

# ---------------- Globals ----------------
clf_model = None
class_names = None


# ---------------- Lazy Load ----------------
def get_model():
    """Load model only once, then reuse it."""
    global clf_model, class_names

    if clf_model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model not found at {MODEL_PATH}.")
        clf_model = load_model(MODEL_PATH)

    if class_names is None and os.path.exists(CLASS_NAMES_PATH):
        with open(CLASS_NAMES_PATH, "r") as f:
            class_names = json.load(f)

    return clf_model, class_names


# ---------------- Dominant Color ----------------
def get_dominant_color(img_path, k=3):
    """Extract dominant color from an image using KMeans."""
    img = cv2.imread(img_path)
    if img is None:
        return "#000000"
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.reshape((-1, 3))
    kmeans = KMeans(n_clusters=k, random_state=0, n_init="auto").fit(img)
    counts = np.bincount(kmeans.labels_)
    dominant_color = kmeans.cluster_centers_[np.argmax(counts)]
    return "#{:02x}{:02x}{:02x}".format(
        int(dominant_color[0]), int(dominant_color[1]), int(dominant_color[2])
    )


# ---------------- Classification ----------------
def classify_image(image_path):
    """Classify a single image and return hierarchy, label, confidence, and color."""
    model, class_names = get_model()

    img = keras_image.load_img(image_path, target_size=(224, 224))
    img_array = keras_image.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    preds = model.predict(img_array, verbose=0)
    class_idx = np.argmax(preds)
    confidence = float(preds[0][class_idx])

    if class_names:
        hierarchy = class_names[class_idx].split("_")
    else:
        hierarchy = ["unknown"]

    return {
        "label": hierarchy[-1],
        "hierarchy": hierarchy,
        "confidence": confidence,
        "dominant_color": get_dominant_color(image_path)
    }


# ---------------- Single Image Prediction ----------------
def predict_image_file(image_path):
    """Wrapper for external API usage."""
    classification = classify_image(image_path)
    return {"objects": [classification]}
