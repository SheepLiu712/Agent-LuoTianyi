from PIL import Image, ImageDraw

img = Image.new("RGB", (512, 512), "white")
draw = ImageDraw.Draw(img)
draw.rectangle((30, 30, 150, 110), fill="blue")
draw.ellipse((156, 156, 356, 356), fill="red")
draw.text((30, 430), "CLI E2E TEST", fill="black")
img.save(r"<TEMP>\cli_e2e_image.png")
print("saved")
