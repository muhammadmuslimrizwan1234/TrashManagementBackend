import os
import certifi
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from bson import ObjectId
from utils.file_utils import remove_duplicate_from_other_categories
import traceback
from utils.db_utils import save_to_mongo
# ---------------- Utils ----------------
from utils.db_utils import save_to_mongo
from utils.category_utils import get_categories
from utils.mega_utils import (
    get_mega_client,
    upload_to_mega,
    delete_mega_file,
)
from models import classifier  # ML model (lazy-loaded)

# ---------------- Load Env ----------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "TrashApp")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# ✅ Mega credentials
MEGA_EMAIL = os.getenv("MEGA_EMAIL")
MEGA_PASSWORD = os.getenv("MEGA_PASSWORD")

# ---------------- Flask App ----------------
app = Flask(__name__)

# ✅ Allow CORS from anywhere
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ---------------- MongoDB ----------------
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]
preds_col = db["predictions"]
dataset_col = db["dataset_images"]

# ---------------- Mega Client ----------------
mega_client = get_mega_client(MEGA_EMAIL, MEGA_PASSWORD)  # ✅ pass credentials

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

    # Save temp file
    filename = secure_filename(file.filename)
    os.makedirs("uploads", exist_ok=True)
    tmp_path = os.path.join("uploads", filename)
    file.save(tmp_path)

    try:
        # ✅ Run classifier
        result = classifier.predict_image_file(tmp_path)
        classification = result["objects"][0]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # --- Upload to Mega (uploads folder) ---
    try:
        from utils.mega_utils import upload_prediction_to_mega
        file_id = upload_prediction_to_mega(mega_client, tmp_path)
    except Exception as e:
        print(f"⚠️ Mega upload failed: {e}")
        file_id = None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # --- Prepare DB record ---
    label = classification["label"]
    confidence = float(classification["confidence"])
    if confidence < 0.6:
        label = "Unknown"

    hierarchy = classification.get("hierarchy", [])
    if not hierarchy:
        hierarchy = ["Unknown"]

    record = {
        "label": label,
        "hierarchy": hierarchy,
        "confidence": confidence,
        "dominant_color": classification["dominant_color"],
        "timestamp": datetime.utcnow(),
        "file_id": file_id  # ✅ only file_id stored now
    }
    record_id = preds_col.insert_one(record).inserted_id

    # --- Response ---
    response = {
        "id": str(record_id),
        "label": label,
        "hierarchy": hierarchy,
        "main_type": hierarchy[0] if len(hierarchy) > 0 else "N/A",
        "sub_type": hierarchy[1] if len(hierarchy) > 1 else "N/A",
        "sub_sub_type": hierarchy[2] if len(hierarchy) > 2 else "N/A",
        "confidence": round(confidence * 100, 2),
        "dominant_color": classification["dominant_color"],
        "file_id": file_id
    }

    return jsonify(response), 201


# ---------------- Upload Dataset ----------------
# ---------------- Upload Dataset ----------------
@app.route("/api/upload_dataset_image", methods=["POST"])
def upload_dataset_image():
    try:
        print("📥 Incoming Upload Request")
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        hierarchy = request.form.get("hierarchy")
        if not hierarchy:
            return jsonify({"error": "Missing 'hierarchy' field"}), 400

        hierarchy = hierarchy.split("/") if "/" in hierarchy else [hierarchy]
        print(f"✅ Final hierarchy to use: {hierarchy}")

        os.makedirs("temp_uploads", exist_ok=True)
        temp_path = os.path.join("temp_uploads", file.filename)
        file.save(temp_path)
        print(f"💾 Saved temp file: {temp_path}")

        # Compute hash BEFORE deleting
        import hashlib
        with open(temp_path, "rb") as f:
            file_bytes = f.read()
            file_hash = hashlib.md5(file_bytes).hexdigest()

        # ⬆️ Upload to Mega
        result = upload_to_mega(mega_client, hierarchy, temp_path)

        try:
            os.remove(temp_path)
        except:
            pass

        if not result:
            return jsonify({"error": "Upload failed"}), 500

        # ✅ Save metadata to MongoDB
        # ✅ Save metadata to MongoDB
        record = {
            "id": result.get("file_id"),
            "name": result.get("name"),
            "hierarchy": hierarchy,
            "size": result.get("size"),
            "link": result.get("link"),
            "hash": file_hash,
            "timestamp": datetime.utcnow(),
        }
        record = save_to_mongo(record)  # this will auto attach _id
        return jsonify(record), 200


    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/categories", methods=["GET"])
def categories():
    try:
        cats = get_categories(mega_client)   # ✅ pass the global client
        return jsonify(cats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- List Dataset ----------------
# ---------------- List Dataset ----------------
@app.route("/api/dataset_images", methods=["GET"])
def list_dataset_images():
    try:
        dataset_folder = mega_client.find("dataset")
        print("🔍 dataset_folder from Mega:", dataset_folder)

        if not dataset_folder:
            return jsonify({"error": "dataset folder not found"}), 404

        # ✅ Normalize dataset folder id
        if isinstance(dataset_folder, dict) and "h" in dataset_folder:
            dataset_id = dataset_folder["h"]
        elif isinstance(dataset_folder, list) and len(dataset_folder) > 0 and "h" in dataset_folder[0]:
            dataset_id = dataset_folder[0]["h"]
        elif isinstance(dataset_folder, str):
            dataset_id = dataset_folder
        elif isinstance(dataset_folder, tuple) and len(dataset_folder) == 2:
            # Mega sometimes returns (id, metadata)
            dataset_id = dataset_folder[0]
        else:
            return jsonify({
                "error": f"Unexpected dataset folder format: {dataset_folder}"
            }), 500

        # ✅ Get files under dataset folder
        files = mega_client.get_files_in_node(dataset_id) or {}
        print("📂 Files found in dataset:", files)

        response = []
        for file_id, file_info in files.items():
            if file_info.get("t") == 0:  # 0 = file
                try:
                    link = mega_client.export(file_id)
                except Exception as e:
                    print(f"⚠️ Export failed for {file_id}: {e}")
                    link = None
                response.append({
                    "file_id": file_id,
                    "name": file_info.get("a", {}).get("n", "unknown"),
                    "size": file_info.get("s"),
                    "link": link,
                })

        return jsonify(response), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ---------------- Delete Dataset Image ----------------
@app.route("/api/delete_dataset_image/<file_id>", methods=["DELETE"])
def delete_dataset_image(file_id):
    try:
        print(f"🗑️ Deleting file {file_id} from Mega...")
        mega_client.destroy(file_id)

        # ✅ Delete metadata from MongoDB
        from utils.db_utils import delete_from_mongo
        deleted = delete_from_mongo(file_id)

        if deleted == 0:
            return jsonify({"warning": f"No MongoDB record found for {file_id}"}), 200

        return jsonify({"message": f"File {file_id} deleted from Mega and MongoDB"}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------------- Delete Category ----------------
@app.route("/api/delete_category", methods=["POST"])
def delete_category():
    data = request.json
    hierarchy = data.get("hierarchy")

    if not hierarchy or not isinstance(hierarchy, list):
        return jsonify({"error": "Hierarchy list required"}), 400

    try:
        # For simplicity: just delete all DB entries under that hierarchy
        dataset_col.delete_many({"hierarchy": hierarchy})
        return jsonify({
            "message": "Deleted last category",
            "deleted": hierarchy[-1],
            "parent": hierarchy[:-1] if len(hierarchy) > 1 else None
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- Main ----------------
if __name__ == "__main__":
    try:
        from models.classifier import get_model
        model, _ = get_model()
        print("✅ Model loaded into memory at startup.")
    except Exception as e:
        print(f"⚠️ Warning: Could not preload model - {e}")

    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
