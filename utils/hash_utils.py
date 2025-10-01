import imagehash
from PIL import Image

def get_image_hash(image_path):
    """
    Compute perceptual hash for image → used for duplicate detection.
    """
    img = Image.open(image_path).convert("RGB")
    return str(imagehash.average_hash(img))
