"""vision_service.encode_image: downscale + JPEG-encode for Ollama."""
from __future__ import annotations

import base64
import io


def test_encode_image_downscales_and_returns_jpeg(tmp_path):
    from PIL import Image

    from app.services import vision_service

    src = tmp_path / "big.png"
    Image.new("RGBA", (4000, 1000), (255, 0, 0, 128)).save(src)
    out = Image.open(io.BytesIO(base64.b64decode(vision_service.encode_image(src))))
    assert out.format == "JPEG"
    assert max(out.size) == vision_service.MAX_IMAGE_DIM
    assert out.size[0] / out.size[1] == 4  # aspect ratio kept


def test_encode_image_leaves_small_images_alone(tmp_path):
    from PIL import Image

    from app.services import vision_service

    src = tmp_path / "small.png"
    Image.new("RGB", (64, 48), "blue").save(src)
    out = Image.open(io.BytesIO(base64.b64decode(vision_service.encode_image(src))))
    assert out.size == (64, 48)
