# utils/category_utils.py

def _build_tree_from_maps(parent_map, files_map, node_id):
    """Recursively build folder tree using parent_map and files_map starting at node_id."""
    tree = {}
    for (child_id, meta) in parent_map.get(node_id, []):
        # meta['t'] == 1 -> folder; meta['a'] contains attributes with 'n' = name
        if meta.get("t") == 1 and "a" in meta:
            name = meta["a"].get("n")
            if not name:
                continue
            tree[name] = _build_tree_from_maps(parent_map, files_map, child_id)
    return tree


def get_categories(client, dataset_folder_name="dataset"):
    """
    Return nested categories from Mega inside the folder named `dataset_folder_name`.
    If dataset folder is not found, returns actual top-level folders found in Mega root.
    """
    # ✅ use the already-authenticated client from app.py
    files = client.get_files()  # mapping node_id -> meta

    # build parent map: parent_id -> list of (child_id, meta)
    parent_map = {}
    for fid, meta in files.items():
        parent = meta.get("p")
        parent_map.setdefault(parent, []).append((fid, meta))

    # find dataset folder id (case-insensitive)
    dataset_id = None
    for fid, meta in files.items():
        if meta.get("t") == 1 and "a" in meta:
            name = meta["a"].get("n", "")
            if name and name.lower() == dataset_folder_name.lower():
                dataset_id = fid
                break

    if dataset_id:
        return _build_tree_from_maps(parent_map, files, dataset_id)

    # fallback: top-level folders
    roots = []
    for fid, meta in files.items():
        parent = meta.get("p")
        if parent is None or parent not in files:
            roots.append((fid, meta))

    tree = {}
    for fid, meta in roots:
        if meta.get("t") == 1 and "a" in meta:
            name = meta["a"].get("n")
            if not name:
                continue
            tree[name] = _build_tree_from_maps(parent_map, files, fid)

    return tree
