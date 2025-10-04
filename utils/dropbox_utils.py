# utils/dropbox_utils.py
import os
import io
import mimetypes
import time
import dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError
import hashlib


# ------------------------------
# 1️⃣ Dropbox Client
# ------------------------------
def get_dropbox_client():
    DROPBOX_TOKEN = os.getenv("DropBoxToken")
    if not DROPBOX_TOKEN:
        raise ValueError("Dropbox token not set in environment variables")
    return dropbox.Dropbox(DROPBOX_TOKEN)


# ------------------------------
# 2️⃣ Upload Dataset Image
# ------------------------------
def upload_to_dropbox(local_path: str, hierarchy: list):
    """
    Uploads a dataset image to /dataset/<hierarchy...>/<filename>
    Returns dict with file info + shared link
    """
    dbx = get_dropbox_client()
    filename = os.path.basename(local_path)
    dropbox_path = f"/waste2worth/dataset/{'/'.join(hierarchy)}/{filename}"

    with open(local_path, "rb") as f:
        data = f.read()

    try:
        dbx.files_upload(data, dropbox_path, mode=WriteMode("overwrite"))
    except ApiError as e:
        print(f"❌ Dropbox upload failed: {e}")
        return None

    # Shared link
    shared_link = create_or_get_shared_link(dbx, dropbox_path)
    
    return {
        "name": filename,
        "dropbox_path": dropbox_path,
        "size": len(data),
        "link": shared_link,
    }


# ------------------------------
# 3️⃣ Upload Prediction Image
# ------------------------------
def upload_prediction_to_dropbox(local_path: str):
    """
    Uploads prediction images into /dataset/uploads/<filename>
    """
    dbx = get_dropbox_client()
    filename = os.path.basename(local_path)
    dropbox_path = f"/waste2worth/uploads/{int(time.time())}_{filename}"

    with open(local_path, "rb") as f:
        data = f.read()

    try:
        dbx.files_upload(data, dropbox_path, mode=WriteMode("overwrite"))
    except ApiError as e:
        print(f"❌ Dropbox prediction upload failed: {e}")
        return None

    shared_link = create_or_get_shared_link(dbx, dropbox_path)
    
    return {
        "name": filename,
        "dropbox_path": dropbox_path,
        "size": len(data),
        "link": shared_link,
    }


# ------------------------------
# 4️⃣ Stream / Download File
# ------------------------------
def stream_dropbox_file(dropbox_path: str):
    """
    Stream a Dropbox file into memory (BytesIO)
    Returns: file_obj, filename, mime_type
    """
    dbx = get_dropbox_client()
    filename = os.path.basename(dropbox_path)
    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"

    try:
        metadata, res = dbx.files_download(dropbox_path)
        buffer = io.BytesIO(res.content)
        return buffer, filename, mime_type
    except ApiError as e:
        print(f"❌ Dropbox download failed: {e}")
        return None, None, None


# ------------------------------
# 5️⃣ Delete File
# ------------------------------
def delete_dropbox_file(dropbox_path: str):
    dbx = get_dropbox_client()
    try:
        dbx.files_delete_v2(dropbox_path)
        return True
    except ApiError as e:
        print(f"❌ Dropbox delete failed: {e}")
        return False


# ------------------------------
# 6️⃣ Create or Get Shared Link
# ------------------------------
def create_or_get_shared_link(dbx_client, dropbox_path: str):
    """
    Returns a direct download link for a Dropbox file
    """
    try:
        link_metadata = dbx_client.sharing_create_shared_link_with_settings(dropbox_path)
        return link_metadata.url.replace("?dl=0", "?dl=1")
    except ApiError:
        # If link already exists
        links = dbx_client.sharing_list_shared_links(path=dropbox_path, direct_only=True).links
        return links[0].url.replace("?dl=0", "?dl=1") if links else None

# ------------------------------
# 7️⃣ Download Dropbox Folder Recursively
# ------------------------------
def download_folder(dropbox_folder_path: str, local_folder_path: str):
    """
    Downloads all files from a Dropbox folder recursively to local folder
    """
    dbx = get_dropbox_client()
    os.makedirs(local_folder_path, exist_ok=True)

    def _download_folder(path, local_path):
        try:
            res = dbx.files_list_folder(path)
        except ApiError as e:
            print(f"❌ Failed to list folder {path}: {e}")
            return

        for entry in res.entries:
            if isinstance(entry, dropbox.files.FileMetadata):
                rel_path = os.path.relpath(entry.path_lower, dropbox_folder_path.lower())
                local_file_path = os.path.join(local_path, rel_path)
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                try:
                    metadata, res_data = dbx.files_download(entry.path_lower)
                    with open(local_file_path, "wb") as f:
                        f.write(res_data.content)
                    print(f"✅ Downloaded: {entry.path_lower}")
                except ApiError as e:
                    print(f"❌ Failed to download {entry.path_lower}: {e}")
            elif isinstance(entry, dropbox.files.FolderMetadata):
                _download_folder(entry.path_lower, local_path)

        # Continue if more entries
        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            for entry in res.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    rel_path = os.path.relpath(entry.path_lower, dropbox_folder_path.lower())
                    local_file_path = os.path.join(local_path, rel_path)
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    try:
                        metadata, res_data = dbx.files_download(entry.path_lower)
                        with open(local_file_path, "wb") as f:
                            f.write(res_data.content)
                        print(f"✅ Downloaded: {entry.path_lower}")
                    except ApiError as e:
                        print(f"❌ Failed to download {entry.path_lower}: {e}")
                elif isinstance(entry, dropbox.files.FolderMetadata):
                    _download_folder(entry.path_lower, local_path)

    _download_folder(dropbox_folder_path, local_folder_path)

def get_dropbox_dataset_hashes():
    """
    Returns a dict: {md5_hash: dropbox_path} for all files in /waste2worth/dataset
    """
    dbx = get_dropbox_client()
    folder = "/waste2worth/dataset"
    hashes = {}

    def _scan_folder(path):
        try:
            res = dbx.files_list_folder(path)
        except Exception as e:
            print(f"Failed to list {path}: {e}")
            return

        for entry in res.entries:
            if isinstance(entry, dropbox.files.FileMetadata):
                # Stream file to memory
                buffer, _, _ = stream_dropbox_file(entry.path_lower)
                if buffer:
                    md5_hash = hashlib.md5(buffer.getvalue()).hexdigest()
                    hashes[md5_hash] = entry.path_lower
            elif isinstance(entry, dropbox.files.FolderMetadata):
                _scan_folder(entry.path_lower)

        # Pagination
        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            for entry in res.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    buffer, _, _ = stream_dropbox_file(entry.path_lower)
                    if buffer:
                        md5_hash = hashlib.md5(buffer.getvalue()).hexdigest()
                        hashes[md5_hash] = entry.path_lower
                elif isinstance(entry, dropbox.files.FolderMetadata):
                    _scan_folder(entry.path_lower)

    _scan_folder(folder)
    return hashes