from pymongo import MongoClient
import certifi
import os

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "TrashApp")
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]

def get_categories():
    """
    Builds a nested category tree from dataset_images collection.
    Example:
    {
        "metal": {
            "zinc": {},
            "iron": {}
        },
        "plastic": {
            "pp": {}
        },
        "glass": {}
    }
    """
    categories = {}

    images = db["dataset_images"].find({}, {"hierarchy": 1, "_id": 0})
    for img in images:
        hierarchy = img.get("hierarchy", [])
        node = categories
        for level in hierarchy:
            if level not in node:
                node[level] = {}
            node = node[level]

    return categories
