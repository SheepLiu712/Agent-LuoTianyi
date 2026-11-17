"""与 App 一致的两档本地图片压缩；不修改源文件。"""

from io import BytesIO

from PIL import Image, ImageOps

IMAGE_COMPRESSION_TARGET_BYTES = int(5.5 * 1024 * 1024)
COMPRESSION_STAGES = ((2560, 80), (2048, 60))


def compress_image_for_upload(data: bytes, mime_type: str) -> tuple[bytes, str, str]:
    """返回压缩字节、MIME 和后缀；两档都不达标时抛出异常。"""
    is_png = mime_type == "image/png"
    with Image.open(BytesIO(data)) as original:
        source = ImageOps.exif_transpose(original)
        source = source.convert("RGBA" if is_png else "RGB")
        for max_dimension, quality in COMPRESSION_STAGES:
            image = source.copy()
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="PNG" if is_png else "JPEG", **({} if is_png else {"quality": quality}))
            result = output.getvalue()
            if len(result) <= IMAGE_COMPRESSION_TARGET_BYTES:
                return result, "image/png" if is_png else "image/jpeg", ".png" if is_png else ".jpg"
    raise ValueError("compressed image remains too large")
