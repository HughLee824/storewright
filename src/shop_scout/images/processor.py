from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import imagehash
from PIL import Image, ImageOps, UnidentifiedImageError

from shop_scout.domain.models import ImageArtifact
from shop_scout.exceptions import InvalidImageError


def safe_segment(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in "-_" else "_" for character in value
    )
    return safe[:120] or "unknown"


def process_image_bytes(
    content: bytes,
    *,
    source_url: str,
    output_dir: Path,
    content_type: str = "application/octet-stream",
    min_width: int = 300,
    min_height: int = 300,
    max_bytes: int = 15_728_640,
    normalized_name: str | None = None,
    raw_output_dir: Path | None = None,
    role: str = "gallery",
) -> ImageArtifact:
    if len(content) > max_bytes:
        raise InvalidImageError("IMAGE_TOO_LARGE")
    try:
        with Image.open(BytesIO(content)) as opened:
            opened.seek(0)
            image = ImageOps.exif_transpose(opened).copy()
    except (UnidentifiedImageError, OSError) as error:
        raise InvalidImageError("IMAGE_DECODE_FAILED") from error
    if image.width < min_width or image.height < min_height:
        raise InvalidImageError("IMAGE_DIMENSIONS_TOO_SMALL")
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = output_dir / (normalized_name or "normalized.jpg")
    if normalized_name:
        raw_dir = raw_output_dir or output_dir
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{Path(normalized_name).stem}.raw"
    else:
        raw_path = output_dir / "source.raw"
    raw_path.write_bytes(content)
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    else:
        image = image.convert("RGB")
    if max(image.size) > 2000:
        image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
    image.save(normalized_path, "JPEG", quality=95)
    normalized = normalized_path.read_bytes()
    return ImageArtifact(
        source_url=source_url,
        raw_path=raw_path,
        normalized_path=normalized_path,
        sha256=hashlib.sha256(normalized).hexdigest(),
        phash=str(imagehash.phash(image)),
        width=image.width,
        height=image.height,
        file_size=len(content),
        content_type=content_type,
        role=role,
    )
