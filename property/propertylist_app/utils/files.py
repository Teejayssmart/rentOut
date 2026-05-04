import uuid
from pathlib import Path


def generate_upload_path(instance, filename, prefix="uploads"):
    ext = Path(filename).suffix
    return f"{prefix}/{uuid.uuid4().hex}{ext}"