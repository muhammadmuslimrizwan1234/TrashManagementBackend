# utils/category_utils.py
import dropbox
from dropbox.files import FolderMetadata, FileMetadata

def _build_tree_from_dropbox(dbx, folder_path):
    """
    Recursively builds a nested dictionary of folders in Dropbox starting at folder_path
    """
    tree = {}
    try:
        res = dbx.files_list_folder(folder_path)
        entries = res.entries

        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            entries.extend(res.entries)

        for entry in entries:
            if isinstance(entry, FolderMetadata):
                tree[entry.name] = _build_tree_from_dropbox(dbx, entry.path_lower)
        return tree
    except Exception as e:
        print(f"❌ Failed to list folder {folder_path}: {e}")
        return {}

def get_categories(dbx, dataset_folder="/waste2worth/dataset"):
    """
    Returns nested categories from Dropbox starting at `dataset_folder`.
    If dataset folder does not exist, returns top-level folders in Dropbox root.
    """
    try:
        # Check if dataset folder exists
        try:
            dbx.files_get_metadata(dataset_folder)
            return _build_tree_from_dropbox(dbx, dataset_folder)
        except dropbox.exceptions.ApiError:
            print(f"⚠ Dataset folder not found: {dataset_folder}. Using root folder instead.")
            return _build_tree_from_dropbox(dbx, "")
    except Exception as e:
        print(f"❌ get_categories error: {e}")
        return {}
