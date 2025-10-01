import os
import certifi
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# ---------------- Utils ----------------
from utils.file_utils import save_to_dataset, remove_duplicate_from_other_categories, delete_drive_file, delete_drive_folder
from utils.category_utils import get_categories
from models import classifier  # will lazy-load TensorFlow

# ---------------- Load Env ----------------
load_dotenv()

# ---------------- Config ----------------
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "TrashApp")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Dataset root (Google Drive folder ID from env)
DRIVE_DATASET_ID = os.getenv("DRIVE_DATASET_ID")

# ---------------- Flask App ----------------
app = Flask(__name__)

# ✅ Allow CORS from anywhere (fix frontend error)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ---------------- MongoDB ----------------
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]
preds_col = db["predictions"]

# ---------------- Health ----------------
@app.route("/health")
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200

# ---------------- Predict ----------------
@app.route("/api/predict", methods=["POST"])
def predict():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    tmp_path = os.path.join("uploads", filename)
    os.makedirs("uploads", exist_ok=True)
    file.save(tmp_path)

    try:
        # ✅ Lazy load model inside classifier
        result = classifier.predict_image_file(tmp_path)
        classification = result["objects"][0]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Handle low confidence
    label = classification["label"]
    confidence = float(classification["confidence"])
    if confidence < 0.6:
        label = "Unknown"

    hierarchy = classification.get("hierarchy", [])

    # Save prediction record
    record = {
        "label": label,
        "hierarchy": hierarchy,
        "confidence": confidence,
        "dominant_color": classification["dominant_color"],
        "timestamp": datetime.utcnow()
    }
    record_id = preds_col.insert_one(record).inserted_id

    response = {
        "id": str(record_id),
        "label": label,
        "hierarchy": hierarchy,
        "main_type": hierarchy[0] if len(hierarchy) > 0 else "N/A",
        "sub_type": hierarchy[1] if len(hierarchy) > 1 else "N/A",
        "sub_sub_type": hierarchy[2] if len(hierarchy) > 2 else "N/A",
        "confidence": round(confidence * 100, 2),
        "dominant_color": classification["dominant_color"]
    }

    return jsonify(response), 201

# ---------------- Dataset Management ----------------
@app.route("/api/upload_dataset_image", methods=["POST"])
def upload_dataset_image():
    if "files" not in request.files and "file" not in request.files:
        return jsonify({"error": "No file(s) uploaded"}), 400

    files = request.files.getlist("files") if "files" in request.files else [request.files["file"]]

    hierarchy = {
        "main": request.form.get("main"),
        "sub": request.form.get("sub"),
        "subsub": request.form.get("subsub"),
    }

    if not hierarchy["main"]:
        return jsonify({"error": "Main category required"}), 400

    results = []
    for file in files:
        file_id, hash_value = save_to_dataset(file, hierarchy)
        remove_duplicate_from_other_categories(db, hash_value, file_id, hierarchy)

        record = {
            "file_id": file_id,
            "hierarchy": hierarchy,
            "hash": hash_value,
            "uploaded_by": request.form.get("user", "admin"),
            "timestamp": datetime.utcnow()
        }
        db["dataset_images"].insert_one(record)

        results.append({
            "message": "Image added",
            "file_id": file_id,
            "image_url": f"https://drive.google.com/uc?id={file_id}",
            "hierarchy": hierarchy
        })

    return jsonify({
        "uploaded": len(results),
        "results": results
    }), 201

# Get categories
@app.route("/api/categories", methods=["GET"])
def categories():
    return jsonify(get_categories()), 200

# List dataset images
@app.route("/api/dataset_images", methods=["GET"])
def list_dataset_images():
    images = list(db["dataset_images"].find({}, {"_id": 0}))
    for img in images:
        if "file_id" in img:
            img["image_url"] = f"https://drive.google.com/uc?id={img['file_id']}"
    return jsonify({"count": len(images), "images": images}), 200

# Delete dataset image by hash
@app.route("/api/delete_dataset_image/<hash_value>", methods=["DELETE"])
def delete_dataset_image(hash_value):
    doc = db["dataset_images"].find_one({"hash": hash_value})
    if not doc:
        return jsonify({"error": "Image not found"}), 404

    if "file_id" in doc:
        delete_drive_file(doc["file_id"])

    db["dataset_images"].delete_one({"hash": hash_value})
    return jsonify({"message": "Image deleted"}), 200

# Delete category
@app.route("/api/delete_category", methods=["POST"])
def delete_category():
    data = request.json
    main = data.get("main")
    sub = data.get("sub")
    subsub = data.get("subsub")

    if not main:
        return jsonify({"error": "main required"}), 400

    from utils.drive_utils import get_drive_client, ensure_drive_folder
    drive = get_drive_client()

    parent = ensure_drive_folder(drive, DRIVE_DATASET_ID, main)
    target = parent
    if sub:
        target = ensure_drive_folder(drive, parent["id"], sub)
    if subsub:
        target = ensure_drive_folder(drive, target["id"], subsub)

    delete_drive_folder(target["id"])

    db["dataset_images"].delete_many({
        "hierarchy.main": main,
        "hierarchy.sub": sub,
        "hierarchy.subsub": subsub
    })

    return jsonify({"message": "Category deleted"}), 200


# ---------------- Main ----------------
if __name__ == "__main__":
    # Warm up the model at startup
    try:
        from models.classifier import get_model
        model, _ = get_model()
        print("✅ Model loaded into memory at startup.")
    except Exception as e:
        print(f"⚠️ Warning: Could not preload model - {e}")

    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
