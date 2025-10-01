from utils.drive_utils import get_drive_client, DATASET_FOLDER_ID

def get_categories():
    """
    Recursively scan Drive dataset folder.
    """
    drive = get_drive_client()

    def scan_folder(parent_id):
        out = {}
        query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        subfolders = drive.files().list(q=query, fields="files(id, name)").execute().get("files", [])

        for sub in subfolders:
            out[sub["name"]] = scan_folder(sub["id"])
        return out

    return scan_folder(DATASET_FOLDER_ID)
