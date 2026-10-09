#!/usr/bin/env python3
"""Draws Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png (1024x1024).

The PNG is committed to the repository, so this script is only needed if you want
to change the icon. Requires Pillow (pip install pillow).
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SS = 2  # supersampling factor
W = SIZE * SS


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def gradient(stops):
    img = Image.new("RGB", (W, W))
    px = img.load()
    for y in range(W):
        t = y / (W - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                color = lerp(c0, c1, (t - p0) / (p1 - p0))
                break
        for x in range(W):
            px[x, y] = color
    return img


def eye_polygon(cx, cy, half_width, half_height, steps=180):
    top, bottom = [], []
    for i in range(steps + 1):
        x = -1 + 2 * i / steps
        y = half_height * (1 - x * x) ** 1.15
        top.append((cx + x * half_width, cy - y))
        bottom.append((cx + x * half_width, cy + y))
    return top + bottom[::-1]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "Resources", "Assets.xcassets", "AppIcon.appiconset", "AppIcon.png")

    img = gradient([
        (0.0, (10, 14, 40)),
        (0.45, (46, 26, 92)),
        (0.78, (196, 82, 92)),
        (1.0, (255, 170, 84)),
    ])

    # Soft glow behind the eye.
    glow = Image.new("L", (W, W), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.18, W * 0.22, W * 0.82, W * 0.86), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.08))
    img = Image.composite(Image.new("RGB", (W, W), (255, 196, 120)), img, glow.point(lambda v: int(v * 0.55)))

    draw = ImageDraw.Draw(img)
    cx, cy = W / 2, W * 0.55
    half_width, half_height = W * 0.36, W * 0.2
    ink = (24, 16, 48)
    cream = (250, 244, 232)

    # Lashes radiate from the upper lid like the rays of a rising sun.
    stroke = W * 0.024
    for k in range(-3, 4):
        x = k / 4.2
        px_, py_ = cx + x * half_width, cy - half_height * (1 - x * x) ** 1.15
        eps = 1e-3
        qx, qy = cx + (x + eps) * half_width, cy - half_height * (1 - (x + eps) ** 2) ** 1.15
        tx, ty = qx - px_, qy - py_
        norm = math.hypot(tx, ty)
        nx, ny = ty / norm, -tx / norm
        if ny > 0:
            nx, ny = -nx, -ny
        length = W * (0.1 if k == 0 else 0.085 - 0.006 * abs(k))
        x0, y0 = px_ + nx * W * 0.02, py_ + ny * W * 0.02
        x1, y1 = px_ + nx * length, py_ + ny * length
        draw.line((x0, y0, x1, y1), fill=cream, width=int(stroke))
        for ex, ey in ((x0, y0), (x1, y1)):
            draw.ellipse((ex - stroke / 2, ey - stroke / 2, ex + stroke / 2, ey + stroke / 2), fill=cream)

    # Dark rim first, then the white of the eye on top: cleaner than a stroked line.
    draw.polygon(eye_polygon(cx, cy, half_width + W * 0.022, half_height + W * 0.022), fill=ink)
    outline = eye_polygon(cx, cy, half_width, half_height)
    draw.polygon(outline, fill=cream)

    # Iris as a rising sun, clipped to the eye shape.
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    sun = Image.new("RGB", (W, W), (0, 0, 0))
    sun_draw = ImageDraw.Draw(sun)
    radius = W * 0.165
    for i in range(80, 0, -1):
        t = i / 80
        r = radius * t
        sun_draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=lerp((255, 220, 100), (238, 88, 46), t))
    sun_mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(sun_mask).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    img.paste(sun, (0, 0), Image.composite(sun_mask, Image.new("L", (W, W), 0), mask))

    pupil = W * 0.068
    draw.ellipse((cx - pupil, cy - pupil, cx + pupil, cy + pupil), fill=ink)
    highlight = W * 0.027
    hx, hy = cx + W * 0.036, cy - W * 0.04
    draw.ellipse((hx - highlight, hy - highlight, hx + highlight, hy + highlight), fill=(255, 255, 255))

    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, optimize=True)
    print("wrote", os.path.abspath(out))


if __name__ == "__main__":
    main()
