# utils/file_utils.py
import os
import hashlib
import traceback
import tempfile
from bson import ObjectId
from utils.mega_utils import get_mega_client, delete_mega_file, _find_or_create_folder

# ------------------------------
# Hashing Utilities
# ------------------------------

def compute_file_hash(file_path: str) -> str:
    """Compute MD5 hash for a given file path."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def save_to_dataset(file, folder="dataset"):
    """Save file locally in dataset folder, return relative path + hash."""
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, file.filename)
    file.save(file_path)

    file_hash = compute_file_hash(file_path)
    return {"file_path": file_path, "hash": file_hash}


# ------------------------------
# Duplicate Removal (per upload, DB-based)
# ------------------------------
def remove_duplicate_from_other_categories(
    db, file_hash, new_hierarchy, mega_client, delete_mega_file_func, collection_name="dataset_images"
):
    """
    Remove any existing dataset entries that have the same hash (DB + Mega).
    """
    coll = db[collection_name]
    removed_ids = []
    try:
        print(f"🗂 remove_duplicate: looking for docs with hash={file_hash}")
        duplicates = list(coll.find({"hash": file_hash}))
        print(f"🗂 Found {len(duplicates)} existing record(s) with same hash")

        for doc in duplicates:
            doc_id = doc.get("_id")
            doc_hierarchy = doc.get("hierarchy", [])
            mega_file_id = doc.get("id") or doc.get("file_id") or doc.get("mega_id")

            # Delete file from Mega
            if mega_file_id:
                try:
                    print(f"🗑 Deleting mega file {mega_file_id} for DB id {doc_id} (hierarchy: {doc_hierarchy})")
                    delete_mega_file_func(mega_client, mega_file_id)
                except Exception as e:
                    print(f"⚠️ Failed to delete mega file {mega_file_id}: {e}")

            # Delete DB entry
            try:
                coll.delete_one({"_id": ObjectId(doc_id)})
            except Exception:
                try:
                    coll.delete_one({"_id": doc_id})
                except Exception as e:
                    print(f"⚠️ Could not delete DB record {doc_id}: {e}")
                    traceback.print_exc()
                    continue

            removed_ids.append(str(doc_id))
            print(f"✅ Removed DB record {doc_id} (was in hierarchy: {doc_hierarchy})")

        return {"removed_count": len(removed_ids), "removed_ids": removed_ids}

    except Exception as e:
        print(f"❌ remove_duplicate_from_other_categories ERROR: {e}")
        traceback.print_exc()
        return {"error": str(e)}





def find_duplicate_in_mega(client, dataset_root_id, new_file_path):
    """
    Search the entire dataset folder in Mega for duplicates of new_file_path.
    Returns: (duplicate_found, handle, meta, existing_hash)
    """
    try:
        new_hash = compute_file_hash(new_file_path)
        new_size = os.path.getsize(new_file_path)

        children = client.get_files_in_node(dataset_root_id)
        if not isinstance(children, dict):
            print(f"⚠️ Unexpected children type: {type(children)}")
            return None

        for handle, child in children.items():
            try:
                if child["t"] == 0:  # file
                    name = child["a"]["n"]
                    size = child.get("s", 0)

                    # Download existing temporarily
                    existing_file = client.download(handle, "temp_existing")
                    existing_hash = compute_file_hash(existing_file)
                    os.remove(existing_file)

                    if existing_hash == new_hash and size == new_size:
                        print(f"⚠️ Duplicate found in Mega: {name}")
                        return (True, handle, child, existing_hash)

                elif child["t"] == 1:  # folder → recurse
                    result = find_duplicate_in_mega(client, handle, new_file_path)
                    if result:
                        return result

            except Exception as e:
                print(f"⚠️ Error checking child {child}: {e}")
                continue

        return None
    except Exception as e:
        print(f"❌ Error in find_duplicate_in_mega: {e}")
        return None

# ------------------------------
# Global Duplicate Cleaner (DB-based)
# ------------------------------
def remove_all_duplicates(db, mega_client, delete_mega_file_func, collection_name="dataset_images"):
    """
    Scan the entire dataset_images collection and remove duplicates globally.
    Keeps the first occurrence of each hash, deletes all others (both DB + Mega).
    """
    coll = db[collection_name]
    seen_hashes = set()
    removed_ids = []
    total_checked = 0

    try:
        print("🔍 Scanning entire dataset for duplicates...")
        cursor = coll.find({})
        for doc in cursor:
            total_checked += 1
            file_hash = doc.get("hash")
            doc_id = doc.get("_id")
            mega_file_id = doc.get("id") or doc.get("file_id") or doc.get("mega_id")

            if not file_hash:
                continue

            if file_hash in seen_hashes:
                # Duplicate → delete from Mega + DB
                try:
                    if mega_file_id:
                        print(f"🗑 Deleting duplicate mega file {mega_file_id} for DB id {doc_id}")
                        delete_mega_file_func(mega_client, mega_file_id)
                except Exception as e:
                    print(f"⚠️ Failed to delete mega file {mega_file_id}: {e}")

                try:
                    coll.delete_one({"_id": ObjectId(doc_id)})
                except Exception:
                    try:
                        coll.delete_one({"_id": doc_id})
                    except Exception as e:
                        print(f"⚠️ Could not delete DB record {doc_id}: {e}")
                        traceback.print_exc()
                        continue

                removed_ids.append(str(doc_id))
                print(f"✅ Removed duplicate DB record {doc_id}")
            else:
                seen_hashes.add(file_hash)

        print(f"🏁 Finished scanning. Checked {total_checked} docs. Removed {len(removed_ids)} duplicates.")
        return {"scanned": total_checked, "removed_count": len(removed_ids), "removed_ids": removed_ids}

    except Exception as e:
        print(f"❌ remove_all_duplicates ERROR: {e}")
        traceback.print_exc()
        return {"error": str(e)}
