import os
import json
import numpy as np
import gdown, zipfile
from dotenv import load_dotenv   # <--- NEW
from tensorflow.keras.preprocessing.image import load_img, img_to_array
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras import layers, models
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import LabelEncoder
from tensorflow.keras.utils import to_categorical
from sklearn.model_selection import train_test_split

# Load environment variables from .env file
load_dotenv()

# CONFIG
ROOT = os.path.dirname(__file__)
OUT_MODEL_DIR = os.path.join(ROOT, "models")
OUT_MODEL_PATH = os.path.join(OUT_MODEL_DIR, "model.h5")
CLASS_NAMES_PATH = os.path.join(OUT_MODEL_DIR, "class_names.json")

IMG_SIZE = (224, 224)
BATCH = 16
EPOCHS = 6  

os.makedirs(OUT_MODEL_DIR, exist_ok=True)

# 🔑 Dataset URL comes from .env
DRIVE_DATASET_URL = os.getenv("DRIVE_DATASET_URL")
if not DRIVE_DATASET_URL:
    raise ValueError("❌ Missing DRIVE_DATASET_URL in .env file")

DATASET_ZIP = os.path.join(ROOT, "dataset.zip")
DATASET_DIR = os.path.join(ROOT, "dataset")

def download_and_extract_dataset():
    if not os.path.exists(DATASET_DIR):
        print("📂 Downloading dataset from Google Drive...")
        gdown.download(DRIVE_DATASET_URL, DATASET_ZIP, quiet=False)
        print("📦 Extracting dataset...")
        with zipfile.ZipFile(DATASET_ZIP, "r") as zip_ref:
            zip_ref.extractall(ROOT)
        print("✅ Dataset extracted")



def get_image_paths_labels(dataset_dir):
    paths, labels = [], []
    for root, dirs, files in os.walk(dataset_dir):
        for file in files:
            if file.lower().endswith((".jpg", ".png", ".jpeg")):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, dataset_dir)
                label = os.path.dirname(rel_path).replace("\\", "_").replace("/", "_")
                paths.append(full_path)
                labels.append(label)
    return paths, labels

def load_images(paths, img_size):
    X = []
    for p in paths:
        img = load_img(p, target_size=img_size)
        arr = img_to_array(img)/255.0
        X.append(arr)
    return np.array(X)

def main():
    download_and_extract_dataset()

    print("Loading dataset...")
    paths, labels = get_image_paths_labels(DATASET_DIR)
    if not paths:
        raise SystemExit("Dataset empty or structure incorrect.")

    # Encode labels
    le = LabelEncoder()
    y_int = le.fit_transform(labels)
    class_names = list(le.classes_)
    y_cat = to_categorical(y_int)

    with open(CLASS_NAMES_PATH, "w") as f:
        json.dump(class_names, f)
    print(f"✅ Class names saved to {CLASS_NAMES_PATH}")

    X = load_images(paths, IMG_SIZE)

    # Split into train/val/test
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y_cat, test_size=0.3, random_state=42, stratify=y_int
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=42
    )

    print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    # Build model
    base_model = MobileNetV2(weights="imagenet", include_top=False, input_shape=(IMG_SIZE[0], IMG_SIZE[1], 3))
    base_model.trainable = False

    x = base_model.output
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dense(128, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(len(class_names), activation="softmax")(x)

    model = models.Model(inputs=base_model.input, outputs=outputs)
    model.compile(optimizer=Adam(1e-4), loss="categorical_crossentropy", metrics=["accuracy"])

    print("Training model...")
    model.fit(X_train, y_train, validation_data=(X_val, y_val), epochs=EPOCHS, batch_size=BATCH)

    print("Evaluating on test set...")
    test_loss, test_acc = model.evaluate(X_test, y_test, verbose=2)
    print(f"✅ Final Test Accuracy: {test_acc*100:.2f}%")

    # Save model
    model.save(OUT_MODEL_PATH)
    print(f"✅ Model saved to {OUT_MODEL_PATH}")

if __name__ == "__main__":
    main()
