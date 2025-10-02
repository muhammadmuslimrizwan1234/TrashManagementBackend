import os
from mega import Mega
import time

# ------------------------------
# 1. Mega Client Setup
# ------------------------------
def get_mega_client(email: str, password: str):
    """Login to Mega and return client instance."""
    print("🔑 Logging in to Mega...")
    mega = Mega()
    client = mega.login(email, password)
    return client


# ------------------------------
# 2. Find or Create Folder (always returns folder_id)
# ------------------------------
def _find_or_create_folder(client, parent_id, folder_name: str):
    """
    Ensure a folder exists under parent_id. Return folder_id.
    """

    # 🔍 Get all children under parent
    children = client.get_files_in_node(parent_id)

    # Look for existing folder
    existing = None
    for cid, meta in children.items():
        if meta.get("t") == 1 and meta.get("a", {}).get("n") == folder_name:
            existing = cid
            break

    if existing:
        print(f"📂 Found folder: {folder_name}")
        return existing

    # 📂 Otherwise create new folder
    print(f"📂 Creating missing folder: {folder_name}")
    folder = client.create_folder(folder_name, parent_id)

    # ✅ Normalize different return formats
    if isinstance(folder, dict):
        if "h" in folder:  # normal Mega dict
            return folder["h"]
        elif len(folder) == 1 and folder_name in folder:  # {'wood': 'K8ph2JxR'}
            return folder[folder_name]
    elif isinstance(folder, list) and len(folder) > 0 and "h" in folder[0]:
        return folder[0]["h"]
    elif isinstance(folder, str):
        return folder
    elif isinstance(folder, tuple):
        return folder[0]

    raise ValueError(f"❌ Unexpected folder format: {folder}")


# ------------------------------
# 3. Upload File into Dataset
# ------------------------------
# ------------------------------
# 3. Upload File into Dataset
# ------------------------------
def upload_to_mega(client, hierarchy, local_path: str):
    try:
        print(f"📤 Uploading {local_path} to Mega under hierarchy {hierarchy}...")

        # 1. Get dataset root
        dataset_root = client.find("dataset")
        print(f"🔍 client.find('dataset') returned: {dataset_root}")

        if not dataset_root:
            raise ValueError("❌ 'dataset' root folder not found. Please create it manually.")

        # ✅ Handle tuple (folder_id, metadata)
        if isinstance(dataset_root, tuple):
            parent_id = dataset_root[0]
        elif isinstance(dataset_root, dict) and "h" in dataset_root:
            parent_id = dataset_root["h"]
        elif isinstance(dataset_root, list) and len(dataset_root) > 0:
            if isinstance(dataset_root[0], tuple):
                parent_id = dataset_root[0][0]
            elif isinstance(dataset_root[0], dict) and "h" in dataset_root[0]:
                parent_id = dataset_root[0]["h"]
            elif isinstance(dataset_root[0], str):
                parent_id = dataset_root[0]
            else:
                raise ValueError(f"❌ Unknown list format: {dataset_root}")
        elif isinstance(dataset_root, str):
            parent_id = dataset_root
        else:
            raise ValueError(f"❌ Unexpected dataset root format: {dataset_root}")

        # 2. Traverse / create hierarchy
        for level in hierarchy:
            parent_id = _find_or_create_folder(client, parent_id, level)

        # 3. Rename file → timestamp + extension
        ext = os.path.splitext(local_path)[1]
        timestamped_name = f"{int(time.time())}{ext}"

        # 4. Upload file with renamed filename
        uploaded = client.upload(local_path, dest=parent_id, dest_filename=timestamped_name)
        print(f"🔍 Raw upload result: {uploaded}")

        # ✅ Normalize file_id
        if isinstance(uploaded, dict):
            if "h" in uploaded:
                file_id = uploaded["h"]
            elif "f" in uploaded and isinstance(uploaded["f"], list) and len(uploaded["f"]) > 0:
                file_id = uploaded["f"][0]["h"]
            else:
                raise ValueError(f"❌ Unknown dict format: {uploaded}")
        elif isinstance(uploaded, str):
            file_id = uploaded
        elif isinstance(uploaded, tuple):
            file_id = uploaded[0]
        else:
            raise ValueError(f"❌ Unexpected upload result: {uploaded}")

        # 5. Try export link
        link = None
        try:
            export_result = client.export(file_id)
            if isinstance(export_result, dict) and "url" in export_result:
                link = export_result["url"]
            elif isinstance(export_result, str):
                link = export_result
            else:
                print(f"⚠️ Export returned unexpected: {export_result}, falling back to no-link")
        except Exception as e:
            print(f"⚠️ Export failed: {e}")

        print(f"✅ Upload successful! File ID: {file_id}, Link: {link}")
        return {"file_id": file_id, "link": link, "filename": timestamped_name}

    except Exception as e:
        print(f"❌ Upload error: {e}")
        return None
# ------------------------------
# 4. Delete File by Mega ID
# ------------------------------
def delete_mega_file(client, file_id):
    """Delete file/folder by Mega ID."""
    client.destroy(file_id)
    print(f"🗑️ Deleted file/folder with ID: {file_id}")
    return True




def upload_prediction_to_mega(client, local_path: str):
    """
    Upload a prediction file into the `uploads` folder in Mega.
    Returns only the file_id (no public link).
    """
    try:
        print(f"📤 Uploading prediction {local_path} into uploads/ folder...")

        # Find or create dataset root
        dataset_root = client.find("dataset")
        if not dataset_root:
            raise ValueError("❌ 'dataset' root folder not found. Please create it manually.")

        # Normalize parent_id
        if isinstance(dataset_root, tuple):
            parent_id = dataset_root[0]
        elif isinstance(dataset_root, dict) and "h" in dataset_root:
            parent_id = dataset_root["h"]
        elif isinstance(dataset_root, list) and len(dataset_root) > 0:
            first = dataset_root[0]
            parent_id = first[0] if isinstance(first, tuple) else first.get("h", first)
        elif isinstance(dataset_root, str):
            parent_id = dataset_root
        else:
            raise ValueError(f"❌ Unexpected dataset root format: {dataset_root}")

        # Ensure uploads folder
        uploads_folder = None
        children = client.get_files_in_node(parent_id)
        for child_id, meta in children.items():
            if "a" in meta and meta["a"].get("n") == "uploads":
                uploads_folder = child_id
                break

        if not uploads_folder:
            created = client.create_folder("uploads", parent_id)
            print(f"📂 Created 'uploads' folder: {created}")
            if isinstance(created, dict):
                uploads_folder = created.get("uploads") or created.get("h")
            elif isinstance(created, tuple):
                uploads_folder = created[0]
            elif isinstance(created, str):
                uploads_folder = created
            else:
                raise ValueError(f"❌ Unexpected uploads root format: {created}")

        # Upload file
        import time, os
        ext = os.path.splitext(local_path)[1]
        filename = f"{int(time.time())}{ext}"
        uploaded = client.upload(local_path, dest=uploads_folder, dest_filename=filename)
        print(f"🔍 Raw upload result: {uploaded}")

        # ✅ Extract file_id safely
        file_id = None
        if isinstance(uploaded, dict):
            if "h" in uploaded:
                file_id = uploaded["h"]
            elif "f" in uploaded and uploaded["f"]:
                file_id = uploaded["f"][0].get("h")
        elif isinstance(uploaded, tuple):
            file_id = uploaded[0]
        elif isinstance(uploaded, str):
            file_id = uploaded

        if not file_id:
            raise ValueError(f"❌ Could not extract file_id from upload result: {uploaded}")

        print(f"✅ Upload successful → File ID: {file_id}")
        return file_id

    except Exception as e:
        print(f"❌ upload_prediction_to_mega error: {e}")
        return None
