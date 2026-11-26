extends RefCounted
## 头像构图：先取中心正方形再缩放，圆形容器里不会出现拉伸或偏移。
const TARGET := 256

static func fit_square(image: Image, target: int = TARGET) -> Image:
	var side := mini(image.get_width(), image.get_height())
	var square := image.get_region(Rect2i((image.get_width() - side) / 2, (image.get_height() - side) / 2, side, side))
	if square.get_format() != Image.FORMAT_RGBA8:
		square.convert(Image.FORMAT_RGBA8)
	square.resize(maxi(1, target), maxi(1, target), Image.INTERPOLATE_LANCZOS)
	return square
