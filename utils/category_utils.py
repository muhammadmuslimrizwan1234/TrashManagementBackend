import os
from utils.drive_utils import get_drive_client, list_drive_folders

# Root dataset folder (Google Drive ID)
DRIVE_DATASET_ID = os.getenv("DRIVE_DATASET_ID")

def get_categories():
    """
    Fetch dataset categories from Google Drive.
    Returns a list of dicts in a clean hierarchy format:
    [
        {"main": "glass", "sub": None, "subsub": None},
        {"main": "plastic", "sub": "PET", "subsub": None},
        {"main": "metal", "sub": "aluminum", "subsub": "cans"}
    ]
    """
    if not DRIVE_DATASET_ID:
        raise ValueError("DRIVE_DATASET_ID not configured in environment")

    drive = get_drive_client()

    categories = []

    # Level 1: Main categories
    mains = list_drive_folders(drive, DRIVE_DATASET_ID)
    for main in mains:
        main_name = main["title"]

        # Level 2: Sub categories
        subs = list_drive_folders(drive, main["id"])
        if not subs:
            categories.append({"main": main_name, "sub": None, "subsub": None})
            continue

        for sub in subs:
            sub_name = sub["title"]

            # Level 3: Sub-sub categories
            subsubs = list_drive_folders(drive, sub["id"])
            if not subsubs:
                categories.append({"main": main_name, "sub": sub_name, "subsub": None})
                continue

            for subsub in subsubs:
                subsub_name = subsub["title"]
                categories.append({"main": main_name, "sub": sub_name, "subsub": subsub_name})

    return categories
