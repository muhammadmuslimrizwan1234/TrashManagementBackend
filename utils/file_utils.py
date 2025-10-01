import os
import tempfile
from werkzeug.utils import secure_filename
from utils.hash_utils import get_image_hash
from utils.drive_utils import get_drive_client, ensure_drive_folder, upload_to_drive, delete_drive_file, delete_drive_folder, DATASET_FOLDER_ID

def save_to_dataset(file, hierarchy):
    """
    Save uploaded image into Drive under hierarchy folders.
    Returns (file_id, hash_value).
    """
    drive = get_drive_client()

    # Ensure folders exist
    parent = ensure_drive_folder(drive, DATASET_FOLDER_ID, hierarchy["main"])
    if hierarchy.get("sub"):
        parent = ensure_drive_folder(drive, parent["id"], hierarchy["sub"])
    if hierarchy.get("subsub"):
        parent = ensure_drive_folder(drive, parent["id"], hierarchy["subsub"])

    filename = secure_filename(file.filename)

    # Save to tmp for hashing + upload
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    hash_value = get_image_hash(tmp_path)

    file_id = upload_to_drive(drive, parent["id"], tmp_path, filename)

    os.remove(tmp_path)

    return file_id, hash_value

def remove_duplicate_from_other_categories(db, hash_value, file_id, hierarchy):
    """
    If duplicate exists in DB → update its category in DB (Drive already holds correct file).
    """
    dataset_images = db["dataset_images"]
    existing_doc = dataset_images.find_one({"hash": hash_value})
    if existing_doc:
        old_hierarchy = existing_doc["hierarchy"]
        if old_hierarchy == hierarchy:
            return

        dataset_images.update_one(
            {"_id": existing_doc["_id"]},
            {"$set": {
                "file_id": file_id,
                "hierarchy": hierarchy
            }}
        )
