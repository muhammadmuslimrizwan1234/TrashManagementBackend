import os
import certifi
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# ---------------- Utils ----------------
from utils.category_utils import get_categories
from utils.file_utils import save_to_dataset, remove_duplicate_from_other_categories
from utils.drive_utils import delete_drive_file

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
# ---------------- Dataset Management ----------------
@app.route("/api/upload_dataset_image", methods=["POST"])
def upload_dataset_image():
    if "files" not in request.files and "file" not in request.files:
        return jsonify({"error": "No file(s) uploaded"}), 400

    # Support multiple or single file
    files = request.files.getlist("files") if "files" in request.files else [request.files["file"]]

    # Convert form hierarchy to list
    hierarchy_list = [h for h in [
        request.form.get("main"),
        request.form.get("sub"),
        request.form.get("subsub")
    ] if h]

    if not hierarchy_list:
        return jsonify({"error": "At least one category (main) required"}), 400

    results = []
    for file in files:
        try:
            print(f"📂 Uploading file: {file.filename} → hierarchy: {hierarchy_list}")

            # Save to Drive
            file_id, hash_value = save_to_dataset(file, hierarchy_list)
            print(f"✅ File uploaded to Drive. ID={file_id}, hash={hash_value}")

            # Remove duplicates if needed
            remove_duplicate_from_other_categories(db, hash_value, file_id, hierarchy_list)

            # Save record in MongoDB
            record = {
                "file_id": file_id,
                "hierarchy": hierarchy_list,
                "hash": hash_value,
                "uploaded_by": request.form.get("user", "admin"),
                "timestamp": datetime.utcnow()
            }
            db["dataset_images"].insert_one(record)
            print(f"🗄️ Mongo record inserted: {record}")

            results.append({
                "message": "Image added",
                "file_id": file_id,
                "image_url": f"https://drive.google.com/uc?id={file_id}",
                "hierarchy": hierarchy_list
            })

        except Exception as e:
            print(f"❌ Error uploading {file.filename}: {e}")
            results.append({
                "message": f"Failed to upload {file.filename}",
                "error": str(e)
            })

    return jsonify({
        "uploaded": len([r for r in results if "file_id" in r]),
        "results": results
    }), 201

# ---------------- Get Categories ----------------
@app.route("/api/categories", methods=["GET"])
def categories():
    try:
        cats = get_categories()
        return jsonify({"categories": cats}), 200
    except Exception as e:
        print("❌ Error in /api/categories:", str(e))
        return jsonify({"error": str(e)}), 500

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

@app.route("/api/delete_category", methods=["POST"])
def delete_category():
    data = request.json
    hierarchy = data.get("hierarchy")

    if not hierarchy or not isinstance(hierarchy, list):
        return jsonify({"error": "Hierarchy list required"}), 400

    from utils.drive_utils import get_drive_client, ensure_drive_folder, delete_drive_folder
    drive = get_drive_client()

    try:
        parent = {"id": DRIVE_DATASET_ID}
        target = None

        # Traverse until last level
        for level in hierarchy:
            target = ensure_drive_folder(drive, parent["id"], level)
            parent = target

        if not target:
            return jsonify({"error": "Target folder not found"}), 404

        # ❌ Only delete the last folder in hierarchy
        delete_drive_folder(target["id"])

        # 🗑 Delete DB entries for this exact hierarchy
        db["dataset_images"].delete_many({"hierarchy": hierarchy})

        return jsonify({
            "message": "Deleted last category",
            "deleted": hierarchy[-1],
            "parent": hierarchy[:-1] if len(hierarchy) > 1 else None
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
