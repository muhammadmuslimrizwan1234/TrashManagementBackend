import os
import hashlib
from pymongo import MongoClient
from dotenv import load_dotenv

# Load .env values
load_dotenv()

# ✅ Use the same env keys as app.py
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "TrashApp")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION", "dataset_images")

# Connect
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]


def compute_hash_from_bytes(file_bytes: bytes) -> str:
    """Return MD5 hash from raw bytes (used before uploading)."""
    return hashlib.md5(file_bytes).hexdigest()


def save_to_mongo(record: dict) -> dict:
    """
    Save record into MongoDB dataset_images collection.
    Ensures a hash is always stored.
    """
    if "hash" not in record:
        if "file_path" in record and record["file_path"]:
            with open(record["file_path"], "rb") as f:
                record["hash"] = hashlib.md5(f.read()).hexdigest()
        elif "file_bytes" in record:
            record["hash"] = compute_hash_from_bytes(record["file_bytes"])
        else:
            raise Exception("❌ Cannot save record: missing hash and file content.")

    inserted = collection.insert_one(record)
    record["_id"] = str(inserted.inserted_id)
    return record


def get_all_images():
    """Fetch all dataset images."""
    return list(collection.find({}, {"_id": 0}))


def get_categories():
    """Fetch unique categories + subcategories from dataset."""
    categories = {}
    for item in collection.find({}, {"_id": 0, "category": 1, "subcategory": 1}):
        cat = item["category"]
        sub = item.get("subcategory")
        if cat not in categories:
            categories[cat] = set()
        if sub:
            categories[cat].add(sub)
    return {k: list(v) for k, v in categories.items()}


def delete_from_mongo(file_id: str) -> int:
    """Delete dataset image metadata by Mega file id."""
    return collection.delete_one({"id": file_id}).deleted_count
