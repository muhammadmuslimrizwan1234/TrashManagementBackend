from mega.reborn import Mega
import os

def get_dataset_folder(client):
    """
    Manually scan all folders to find 'dataset' (case-insensitive).
    """
    files = client.get_files()
    for fid, meta in files.items():
        if meta.get("t") == 1:  # folder
            folder_name = meta.get("a", {}).get("n")
            print(f"📂 Found folder: {folder_name} ({fid})")
            if folder_name and folder_name.lower() == "dataset":
                print(f"✅ Using dataset folder: {folder_name} ({fid})")
                return fid
    raise Exception("❌ 'dataset' root folder not found in Mega. Please create it manually.")

def main():
    print("🔑 Logging in to Mega...")
    mega = Mega()
    client = mega.login("muslim.rizwan12@gmail.com", "muslim123")  # put creds here

    # Create a test file
    with open("temp_test.txt", "w", encoding="utf-8") as f:
        f.write("This is a Mega upload test")

    print("\n📤 Uploading temp_test.txt to Mega under hierarchy ['cardboard']...")
    dataset_id = get_dataset_folder(client)

    print("☁️ Starting Mega upload...")
    try:
        # ensure "cardboard" subfolder exists
        files = client.get_files()
        cardboard_id = None
        for fid, meta in files.items():
            if meta.get("t") == 1 and meta.get("p") == dataset_id:  # folder inside dataset
                folder_name = meta.get("a", {}).get("n")
                if folder_name and folder_name.lower() == "cardboard":
                    cardboard_id = fid
                    break

        if cardboard_id is None:
            print("📂 Creating 'cardboard' folder inside dataset...")
            cardboard_id = client.create_folder("cardboard", dataset_id)["f"][0]["h"]

        # upload file into cardboard
        client.upload("temp_test.txt", cardboard_id)
        print("✅ Upload successful!")

    except Exception as e:
        print(f"❌ Upload error: {e}")

if __name__ == "__main__":
    main()
