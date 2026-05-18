"""Image upload helpers: validation, optimisation, thumbnail generation."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


def _safe_ext(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate_image_upload(uploaded_file) -> None:
    ext = _safe_ext(uploaded_file.name)
    if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            f"Unsupported image type '.{ext}'. Allowed: "
            + ", ".join(sorted(settings.ALLOWED_IMAGE_EXTENSIONS))
        )
    if uploaded_file.size > settings.FILE_UPLOAD_MAX_MEMORY_SIZE:
        raise ValidationError("File is too large. Max size is 10 MB.")


def validate_receipt_upload(uploaded_file) -> None:
    ext = _safe_ext(uploaded_file.name)
    if ext not in settings.ALLOWED_RECEIPT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '.{ext}'. Allowed: "
            + ", ".join(sorted(settings.ALLOWED_RECEIPT_EXTENSIONS))
        )
    if uploaded_file.size > settings.FILE_UPLOAD_MAX_MEMORY_SIZE:
        raise ValidationError("File is too large. Max size is 10 MB.")


def _open_image(uploaded_file) -> Image.Image:
    try:
        img = Image.open(uploaded_file)
        img.load()
    except UnidentifiedImageError as exc:
        raise ValidationError("Uploaded file is not a valid image.") from exc
    return img


def process_product_image(uploaded_file, *, prefix: str = "product"):
    """Convert/resize the uploaded image and return (master, thumbnail) ContentFiles.

    - Strips EXIF/metadata.
    - Resizes within PRODUCT_IMAGE_MAX_SIZE.
    - Converts to WebP for storage efficiency.
    - Generates a square-fit thumbnail at PRODUCT_THUMB_SIZE.
    """
    validate_image_upload(uploaded_file)
    image = _open_image(uploaded_file)
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    image.thumbnail(settings.PRODUCT_IMAGE_MAX_SIZE, Image.LANCZOS)

    master_buf = io.BytesIO()
    image.save(master_buf, format="WEBP", quality=82, method=6)
    master_buf.seek(0)

    thumb = ImageOps.fit(image, settings.PRODUCT_THUMB_SIZE, Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="WEBP", quality=80, method=6)
    thumb_buf.seek(0)

    uid = uuid.uuid4().hex[:16]
    master_name = f"{prefix}_{uid}.webp"
    thumb_name = f"{prefix}_{uid}_thumb.webp"
    return (
        ContentFile(master_buf.getvalue(), name=master_name),
        ContentFile(thumb_buf.getvalue(), name=thumb_name),
    )


def sanitize_filename(name: str) -> str:
    ext = _safe_ext(name)
    return f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
