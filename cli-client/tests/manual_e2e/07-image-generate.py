from PIL import Image, ImageDraw
from pathlib import Path
from tempfile import gettempdir

img = Image.new("RGB", (512, 512), "white")
draw = ImageDraw.Draw(img)
draw.rectangle((30, 30, 150, 110), fill="blue")
draw.ellipse((156, 156, 356, 356), fill="red")
draw.text((30, 430), "CLI E2E TEST", fill="black")
output = Path(gettempdir()) / "cli_e2e_image.png"
img.save(output)
print(output)
