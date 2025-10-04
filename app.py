import os
import io
import certifi
import mimetypes
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from bson import ObjectId
import traceback

# ---------------- Utils ----------------
from utils.file_utils import remove_duplicate_from_other_categories
from utils.db_utils import save_to_mongo, delete_from_mongo
from utils.category_utils import get_categories
from utils.dropbox_utils import (
    upload_to_dropbox,
    upload_prediction_to_dropbox,
    stream_dropbox_file,
    delete_dropbox_file,
    get_dropbox_client
)

from models import classifier

# ---------------- Load Env ----------------
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "TrashApp")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# ---------------- Flask App ----------------
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ---------------- MongoDB ----------------
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]
preds_col = db["predictions"]
dataset_col = db["dataset_images"]

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
    os.makedirs("uploads", exist_ok=True)
    tmp_path = os.path.join("uploads", filename)
    file.save(tmp_path)

    try:
        result = classifier.predict_image_file(tmp_path)
        classification = result["objects"][0]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Upload prediction to Dropbox
    dropbox_info = None
    try:
        dropbox_info = upload_prediction_to_dropbox(tmp_path)
    except Exception as e:
        print(f"⚠️ Dropbox upload failed: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # Prepare record for MongoDB
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
        "dropbox_info": dropbox_info
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
        "dominant_color": classification["dominant_color"],
        "dropbox_info": dropbox_info
    }

    return jsonify(response), 201


# ---------------- Upload Dataset ----------------
@app.route("/api/upload_dataset_image", methods=["POST"])
def upload_dataset_image():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        hierarchy = request.form.get("hierarchy")
        if not hierarchy:
            return jsonify({"error": "Missing 'hierarchy' field"}), 400

        hierarchy = hierarchy.split("/") if "/" in hierarchy else [hierarchy]

        os.makedirs("temp_uploads", exist_ok=True)
        temp_path = os.path.join("temp_uploads", file.filename)
        file.save(temp_path)

        # Compute hash
        import hashlib
        with open(temp_path, "rb") as f:
            file_bytes = f.read()
            file_hash = hashlib.md5(file_bytes).hexdigest()

        # Upload to Dropbox
        dropbox_info = upload_to_dropbox(temp_path, hierarchy)

        os.remove(temp_path)

        if not dropbox_info:
            return jsonify({"error": "Upload failed"}), 500

        record = {
            "hierarchy": hierarchy,
            "hash": file_hash,
            "timestamp": datetime.utcnow(),
            "dropbox_info": dropbox_info
        }
        record = save_to_mongo(record)
        return jsonify(record), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------------- Categories ----------------
@app.route("/api/categories", methods=["GET"])
def categories():
    try:
        dbx = get_dropbox_client()
        cats = get_categories(dbx)  # adjust if needed
        return jsonify(cats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- List Dataset Images ----------------
@app.route("/api/dataset_images", methods=["GET"])
def list_dataset_images():
    try:
        files = dataset_col.find()
        response = []
        for f in files:
            dropbox_info = f.get("dropbox_info", {})
            response.append({
                "id": str(f["_id"]),
                "hierarchy": f.get("hierarchy"),
                "name": dropbox_info.get("name"),
                "size": dropbox_info.get("size"),
                "link": dropbox_info.get("link")
            })
        return jsonify(response), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------------- Delete Dataset Image ----------------
@app.route("/api/delete_dataset_image/<record_id>", methods=["DELETE"])
def delete_dataset_image(record_id):
    try:
        record = dataset_col.find_one({"_id": ObjectId(record_id)})
        if not record:
            return jsonify({"error": "Record not found"}), 404

        dropbox_info = record.get("dropbox_info")
        if dropbox_info:
            delete_dropbox_file(dropbox_info["dropbox_path"])

        deleted = delete_from_mongo(record_id)
        return jsonify({"message": "Deleted successfully"}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------------- Get Image ----------------
@app.route("/api/get_image/<record_id>", methods=["GET"])
def get_image(record_id):
    try:
        record = preds_col.find_one({"_id": ObjectId(record_id)}) or dataset_col.find_one({"_id": ObjectId(record_id)})
        if not record or "dropbox_info" not in record:
            return jsonify({"error": "File not found"}), 404

        dropbox_info = record["dropbox_info"]
        file_obj, filename, mime_type = stream_dropbox_file(dropbox_info["dropbox_path"])
        if not file_obj:
            return jsonify({"error": "File could not be retrieved"}), 404

        return send_file(file_obj, mimetype=mime_type, download_name=filename, as_attachment=False)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/delete_prediction_image/<record_id>", methods=["DELETE"])
def delete_prediction_image(record_id):
    try:
        predictions_col = db["predictions"]  # <-- add this

        record = predictions_col.find_one({"_id": ObjectId(record_id)})
        if not record:
            return jsonify({"error": "Prediction image not found"}), 404

        # Delete from Dropbox if dropbox_info exists
        dropbox_info = record.get("dropbox_info")
        if dropbox_info and "dropbox_path" in dropbox_info:
            delete_dropbox_file(dropbox_info["dropbox_path"])

        # Delete from MongoDB
        predictions_col.delete_one({"_id": ObjectId(record_id)})

        return jsonify({"message": "Prediction image deleted successfully"}), 200

    except Exception as e:
        import traceback
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
        # Delete from MongoDB
        dataset_col.delete_many({"hierarchy": hierarchy})

        # Construct Dropbox path
        dropbox_path = f"/waste2worth/dataset/{'/'.join(hierarchy)}"

        # Delete from Dropbox
        dropbox_deleted = delete_dropbox_file(dropbox_path)

        return jsonify({
            "message": "Deleted last category",
            "deleted": hierarchy[-1],
            "parent": hierarchy[:-1] if len(hierarchy) > 1 else None,
            "dropbox_deleted": dropbox_deleted
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    try:
        from models.classifier import get_model
        model, _ = get_model()
        print("✅ Model loaded into memory at startup.")
    except Exception as e:
        print(f"⚠️ Warning: Could not preload model - {e}")

    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
