import os
import json
import mimetypes
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

# Dataset root folder
DATASET_FOLDER_ID = os.getenv("DRIVE_DATASET_ID")

def get_drive_client():
    """Authenticate and return Google Drive client using service account JSON from env."""
    service_info = json.loads(os.getenv("GOOGLE_SERVICE_JSON"))
    creds = service_account.Credentials.from_service_account_info(
        service_info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def ensure_drive_folder(drive, parent_id, folder_name):
    """Find or create a folder inside parent folder."""
    query = f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = drive.files().list(q=query, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]

    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = drive.files().create(body=folder_metadata, fields="id, name").execute()
    return folder

def upload_to_drive(drive, parent_id, file_path, file_name=None):
    """Upload file into parent folder and return file_id."""
    if not file_name:
        file_name = os.path.basename(file_path)

    mime_type, _ = mimetypes.guess_type(file_path)
    file_metadata = {
        "name": file_name,
        "parents": [parent_id]
    }
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    file = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return file["id"]

def delete_drive_file(file_id):
    """Delete a file from Drive."""
    drive = get_drive_client()
    try:
        drive.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"⚠️ Error deleting file {file_id}: {e}")
        return False

def delete_drive_folder(folder_id):
    """Delete a folder (moves to trash)."""
    drive = get_drive_client()
    try:
        drive.files().delete(fileId=folder_id).execute()
        return True
    except Exception as e:
        print(f"⚠️ Error deleting folder {folder_id}: {e}")
        return False
