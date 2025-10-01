import os
import tempfile
from werkzeug.utils import secure_filename
from utils.hash_utils import get_image_hash
from utils.drive_utils import (
    get_drive_client, ensure_drive_folder,
    upload_to_drive, delete_drive_file, DATASET_FOLDER_ID
)

def save_to_dataset(file, hierarchy_list):
    """
    Save uploaded file into Google Drive following the given hierarchy.
    hierarchy_list = ["metal", "zinc"] or ["plastic", "pp"]
    Returns: (file_id, hash_value)
    """
    if not hierarchy_list or not isinstance(hierarchy_list, list):
        raise ValueError("Hierarchy must be a non-empty list")

    drive = get_drive_client()
    parent = {"id": DATASET_FOLDER_ID, "title": "root"}

    # Traverse hierarchy (create folders if missing)
    for level in hierarchy_list:
        parent = ensure_drive_folder(drive, parent["id"], level)

    # Save temp file
    filename = secure_filename(file.filename)
    os.makedirs("uploads", exist_ok=True)
    tmp_path = os.path.join("uploads", filename)
    file.save(tmp_path)

    # Upload to Drive
    file_id = upload_to_drive(drive, parent["id"], tmp_path, filename)

    # Compute perceptual hash
    hash_value = get_image_hash(tmp_path)

    # Cleanup temp file
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    return file_id, hash_value


def remove_duplicate_from_other_categories(db, hash_value, file_id, hierarchy_list):
    """
    Remove duplicates of same hash in other categories.
    - If duplicate exists in DB under *different hierarchy*, remove it from Drive + DB.
    """
    dataset_images = db["dataset_images"]
    duplicates = dataset_images.find({"hash": hash_value})

    for dup in duplicates:
        if dup.get("file_id") != file_id:
            if dup.get("hierarchy") != hierarchy_list:
                # Delete duplicate file in Drive
                try:
                    delete_drive_file(dup["file_id"])
                except Exception as e:
                    print(f"⚠️ Could not delete duplicate file from Drive: {e}")

                # Delete duplicate record from DB
                dataset_images.delete_one({"_id": dup["_id"]})
