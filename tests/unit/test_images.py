from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shop_scout.exceptions import InvalidImageError
from shop_scout.images.processor import process_image_bytes, safe_segment


def image_bytes(mode: str = "RGB", fmt: str = "PNG", size: tuple[int, int] = (400, 350)) -> bytes:
    image = Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else "red")
    buffer = BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


@pytest.mark.parametrize(("mode", "fmt"), [("RGB", "JPEG"), ("RGBA", "PNG"), ("RGB", "WEBP")])
def test_process_formats(tmp_path: Path, mode: str, fmt: str) -> None:
    artifact = process_image_bytes(
        image_bytes(mode, fmt), source_url="https://img/x", output_dir=tmp_path / fmt
    )
    assert len(artifact.sha256) == 64
    assert artifact.normalized_path.is_file()
    assert artifact.width == 400
    again = process_image_bytes(
        image_bytes(mode, fmt), source_url="https://img/x", output_dir=tmp_path / f"{fmt}-2"
    )
    assert artifact.sha256 == again.sha256


def test_rejects_bad_small_and_large(tmp_path: Path) -> None:
    with pytest.raises(InvalidImageError, match="DECODE"):
        process_image_bytes(b"not-image", source_url="x", output_dir=tmp_path / "bad")
    with pytest.raises(InvalidImageError, match="SMALL"):
        process_image_bytes(
            image_bytes(size=(20, 20)), source_url="x", output_dir=tmp_path / "small"
        )
    with pytest.raises(InvalidImageError, match="LARGE"):
        process_image_bytes(
            image_bytes(), source_url="x", output_dir=tmp_path / "large", max_bytes=10
        )
    assert not (tmp_path / "bad" / "source.raw").exists()
    assert not (tmp_path / "small" / "source.raw").exists()
    assert safe_segment("../bad url") == "___bad_url"


def test_flat_output_separates_normalized_and_original_files(tmp_path: Path) -> None:
    artifact = process_image_bytes(
        image_bytes(size=(400, 400)),
        source_url="https://example.com/product.webp",
        output_dir=tmp_path / "images",
        normalized_name="001-main.jpg",
        raw_output_dir=tmp_path / "evidence" / "original-images",
        role="main",
    )
    assert artifact.normalized_path == tmp_path / "images" / "001-main.jpg"
    assert artifact.raw_path == tmp_path / "evidence" / "original-images" / "001-main.raw"
    assert artifact.role == "main"
