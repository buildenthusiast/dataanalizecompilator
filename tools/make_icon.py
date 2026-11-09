"""Прави иконата build_icon.ico за .exe файла (същата като в програмата)."""
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
k = S / 64
d.rounded_rectangle([2 * k, 2 * k, 62 * k, 62 * k], radius=12 * k, fill="#1f6feb")
for x, top, col in [(12, 34, "#C6EFCE"), (26, 22, "#FFEB9C"), (40, 12, "#FFC7CE")]:
    d.rounded_rectangle([x * k, top * k, (x + 11) * k, 52 * k], radius=3 * k, fill=col)
img.save("build_icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
