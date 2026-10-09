#!/usr/bin/env python3
"""Draws the four "sunrise over the city" app icon options for Vigilia.

Each option is written to design/icons/ as an SVG (the editable source), next
to a preview of all four. --use renders one of them as the app icon:

    python3 scripts/make_icon.py              # SVGs + design/icons/preview.png
    python3 scripts/make_icon.py --use 2      # ...and option 2 becomes the app icon

Everything is drawn from code with fixed random seeds, so every run gives the
same result. Rendering needs Chrome, Chromium or Playwright's
chrome-headless-shell (set CHROME=/path/to/binary if it is not found) and
Pillow (pip install pillow).
"""

import argparse
import glob
import math
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile

W = 1024
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DESIGN_DIR = os.path.join(ROOT, "design", "icons")
APP_ICON = os.path.join(ROOT, "Resources", "Assets.xcassets", "AppIcon.appiconset", "AppIcon.png")


# ---------------------------------------------------------------------------
# SVG helpers


def f(value):
    """Compact number formatting for SVG attributes."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def stops(*pairs):
    out = []
    for pair in pairs:
        offset, color = pair[0], pair[1]
        opacity = pair[2] if len(pair) > 2 else 1
        out.append(f'<stop offset="{f(offset)}" stop-color="{color}" stop-opacity="{f(opacity)}"/>')
    return "".join(out)


def linear(gid, x1, y1, x2, y2, *pairs):
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
            f'x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}">{stops(*pairs)}</linearGradient>')


def radial(gid, cx, cy, r, *pairs, fx=None, fy=None, transform=None):
    focus = f' fx="{f(fx)}" fy="{f(fy)}"' if fx is not None else ""
    extra = f' gradientTransform="{transform}"' if transform else ""
    return (f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" '
            f'cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}"{focus}{extra}>{stops(*pairs)}</radialGradient>')


def blur(fid, amount, region=0.5):
    return (f'<filter id="{fid}" x="-{region}" y="-{region}" width="{1 + 2 * region}" height="{1 + 2 * region}">'
            f'<feGaussianBlur stdDeviation="{f(amount)}"/></filter>')


def poly(points):
    return "M" + " L".join(f"{f(x)} {f(y)}" for x, y in points) + " Z"


def rect(x, y, w, h, fill, extra=""):
    return f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="{fill}"{extra}/>'


def circle(cx, cy, r, fill, extra=""):
    return f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{fill}"{extra}/>'


def ellipse(cx, cy, rx, ry, fill, extra=""):
    return f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="{fill}"{extra}/>'


def path(d, fill, extra=""):
    return f'<path d="{d}" fill="{fill}"{extra}/>'


def document(defs, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">\n'
            f'<defs>\n{chr(10).join(defs)}\n</defs>\n{chr(10).join(body)}\n</svg>\n')


def vignette(defs, color="#0b0820", strength=0.5):
    defs.append(radial("vignette", W / 2, W * 0.46, W * 0.78,
                       (0.55, color, 0), (1, color, strength)))
    return rect(0, 0, W, W, "url(#vignette)")


def birds(points, color, width=4.0):
    out = []
    for x, y, s in points:
        d = (f"M{f(x - 14 * s)} {f(y - 2 * s)} Q{f(x - 7 * s)} {f(y - 9 * s)} {f(x)} {f(y)} "
             f"Q{f(x + 7 * s)} {f(y - 9 * s)} {f(x + 14 * s)} {f(y - 2 * s)}")
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{f(width * s)}" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Skylines


class Building:
    def __init__(self, x, w, h, roof):
        self.x, self.w, self.h, self.roof = x, w, h, roof


def make_skyline(rng, x0, x1, profile, wmin, wmax, roofs, gap=(0, 0)):
    """Buildings side by side from x0 to x1. profile(x) gives the typical height."""
    out = []
    x = x0
    while x < x1:
        w = rng.uniform(wmin, wmax)
        h = profile(x + w / 2) * rng.uniform(0.75, 1.15)
        out.append(Building(x, w, max(20, h), rng.choice(roofs)))
        x += w + rng.uniform(*gap)
    # No slivers at the edges of the icon.
    out = [b for b in out if b.x + b.w > 24 and b.x < W - 24]
    first, last = out[0], out[-1]
    first.w += first.x + 40
    first.x = -40
    last.w = W + 40 - last.x
    return out


def building_outline(b, base):
    """Silhouette path of one building, roof details included."""
    x, w, top = b.x, b.w, base - b.h
    pts = [(x, base)]
    if b.roof == "step":
        s1, s2 = w * 0.14, w * 0.3
        pts += [(x, top + 34), (x + s1, top + 34), (x + s1, top + 14), (x + s2, top + 14), (x + s2, top),
                (x + w - s2, top), (x + w - s2, top + 14), (x + w - s1, top + 14), (x + w - s1, top + 34),
                (x + w, top + 34)]
    elif b.roof == "spire":
        cx = x + w / 2
        pts += [(x, top), (cx - w * 0.18, top), (cx - w * 0.18, top - 18), (cx - 3, top - 18),
                (cx, top - 70), (cx + 3, top - 18), (cx + w * 0.18, top - 18), (cx + w * 0.18, top), (x + w, top)]
    elif b.roof == "slant":
        pts += [(x, top + w * 0.35), (x + w, top)]
    elif b.roof == "antenna":
        cx = x + w * 0.62
        pts += [(x, top), (cx - 2, top), (cx - 2, top - 46), (cx + 2, top - 46), (cx + 2, top), (x + w, top)]
    elif b.roof == "tank":
        tx = x + w * 0.22
        pts += [(x, top), (tx, top), (tx, top - 8), (tx + 3, top - 8), (tx + 3, top - 24), (tx + 26, top - 24),
                (tx + 26, top - 8), (tx + 29, top - 8), (tx + 29, top), (x + w, top)]
    elif b.roof == "dome":
        cx, r = x + w / 2, w * 0.32
        pts += [(x, top), (cx - r, top)]
        for i in range(1, 12):
            a = math.pi - math.pi * i / 12
            pts.append((cx + r * math.cos(a), top - r * 0.8 * math.sin(a)))
        pts += [(cx + r, top), (x + w, top)]
    else:  # flat with a parapet
        pts += [(x, top + 6), (x + 3, top + 6), (x + 3, top), (x + w - 3, top), (x + w - 3, top + 6), (x + w, top + 6)]
    pts.append((x + w, base))
    return poly(pts)


def windows(rng, b, base, lit_color, dark_color, lit_ratio, size=(7, 10), gap=(6, 7), margin=(9, 16)):
    """Grid of windows on a facade; some are lit."""
    ww, wh = size
    gx, gy = gap
    mx, my = margin
    top = base - b.h + my + (34 if b.roof == "step" else 0)
    cols = int((b.w - 2 * mx + gx) // (ww + gx))
    if cols <= 0:
        return ""
    used = cols * (ww + gx) - gx
    x0 = b.x + (b.w - used) / 2
    out = []
    y = top
    row = 0
    while y + wh < base - 14:
        floor_lit = rng.random() < 0.85
        for c in range(cols):
            lit = floor_lit and rng.random() < lit_ratio
            if lit:
                opacity = rng.uniform(0.55, 1.0)
                out.append(rect(x0 + c * (ww + gx), y, ww, wh, lit_color, f' opacity="{f(opacity)}"'))
            elif dark_color:
                out.append(rect(x0 + c * (ww + gx), y, ww, wh, dark_color))
        y += wh + gy
        row += 1
    return "".join(out)


def rim_light(b, base, sun_x, color, width=3.0, opacity=0.9):
    """A thin line of sunlight on the edge facing the sun."""
    edge = b.x + b.w if b.x + b.w / 2 < sun_x else b.x
    x = edge - width if edge == b.x + b.w else edge
    return rect(x, base - b.h, width, b.h, color, f' opacity="{f(opacity)}"')


# ---------------------------------------------------------------------------
# Option 1: skyline at dawn over the river


def option_skyline():
    rng = random.Random(11)
    defs, body = [], []
    horizon = 694
    sun_x, sun_y, sun_r = 512, 590, 148

    defs.append(linear("sky", 0, 0, 0, horizon,
                       (0, "#151239"), (0.26, "#2e2566"), (0.46, "#673b8a"), (0.62, "#b8517f"),
                       (0.76, "#ec7a6b"), (0.88, "#ffaa6a"), (1, "#ffd896")))
    body.append(rect(0, 0, W, horizon + 2, "url(#sky)"))

    # Last stars of the night and a fading moon.
    for _ in range(40):
        x, y = rng.uniform(20, W - 20), rng.uniform(16, 290)
        r = rng.choice([1.1, 1.4, 1.7, 2.2])
        body.append(circle(x, y, r, "#ffffff", f' opacity="{f(rng.uniform(0.25, 0.8) * (1 - y / 340))}"'))
    defs.append('<mask id="moonmask"><rect width="1024" height="1024" fill="white"/>'
                '<circle cx="236" cy="150" r="32" fill="black"/></mask>')
    body.append(circle(222, 160, 33, "#fff1da", ' opacity="0.7" mask="url(#moonmask)"'))

    # Glow and soft rays around the sun.
    defs.append(radial("sunglow", sun_x, sun_y, 700,
                       (0, "#fff4cc", 1), (0.1, "#ffe08e", 0.85), (0.26, "#ffa766", 0.45),
                       (0.5, "#e0607c", 0.16), (1, "#e0607c", 0)))
    body.append(rect(0, 0, W, horizon, "url(#sunglow)"))
    defs.append(blur("raysblur", 14))
    rays = []
    for i in range(13):
        a = math.radians(200 + i * 11.7 + rng.uniform(-3, 3))
        spread = math.radians(rng.uniform(1.6, 3.4))
        far = 1000
        p1 = (sun_x + far * math.cos(a - spread), sun_y + far * math.sin(a - spread))
        p2 = (sun_x + far * math.cos(a + spread), sun_y + far * math.sin(a + spread))
        rays.append(path(poly([(sun_x, sun_y), p1, p2]), "#fff1cf", f' opacity="{f(rng.uniform(0.04, 0.09))}"'))
    body.append(f'<g filter="url(#raysblur)" style="mix-blend-mode:screen">{"".join(rays)}</g>')

    # Thin clouds, lit from below.
    defs.append(blur("cloudsoft", 2.2))
    clouds = [(250, 236, 360, "#4c3a7c"), (402, 812, 330, "#6d4688"), (470, 168, 280, "#8f4f86")]
    for i, (cy, cx, span, top_color) in enumerate(clouds):
        gid = f"cloud{i}"
        defs.append(linear(gid, 0, cy - 22, 0, cy + 16, (0, top_color), (0.6, "#e07d88"), (1, "#ffcf98")))
        parts = []
        x = cx - span / 2
        while x < cx + span / 2:
            rx = rng.uniform(34, 70)
            parts.append(ellipse(x + rx, cy + rng.uniform(-8, 4), rx, rng.uniform(8, 15), f"url(#{gid})"))
            x += rx * rng.uniform(1.0, 1.5)
        body.append(f'<g filter="url(#cloudsoft)" opacity="0.9">{"".join(parts)}</g>')

    # The sun.
    defs.append(radial("sundisk", sun_x - 30, sun_y - 50, sun_r * 1.25,
                       (0, "#fffef6"), (0.5, "#fff2bf"), (0.82, "#ffd57a"), (1, "#ffb25a")))
    defs.append(blur("bloom", 36, 1))
    body.append(circle(sun_x, sun_y, sun_r * 1.3, "#ffe3a0", ' opacity="0.85" filter="url(#bloom)"'))
    body.append(circle(sun_x, sun_y, sun_r, "url(#sundisk)"))

    # Three layers of city: hazy in the distance, darker and more detailed up close.
    def profile_far(x):
        d = abs(x - sun_x) / 512
        return 70 + 150 * d + 30 * math.sin(x / 31)

    def profile_mid(x):
        d = abs(x - sun_x) / 512
        return 60 + 250 * d ** 1.4 + 20 * math.sin(x / 23)

    def profile_near(x):
        d = abs(x - sun_x) / 512
        return 34 + 380 * d ** 2.1

    far = make_skyline(rng, -20, W + 20, profile_far, 22, 50, ["flat", "flat", "antenna", "spire", "slant", "dome"])
    mid = make_skyline(rng, -30, W + 30, profile_mid, 30, 62, ["flat", "step", "antenna", "tank", "flat", "slant"])
    near = make_skyline(rng, -40, W + 40, profile_near, 44, 92, ["flat", "step", "antenna", "tank", "flat", "spire"],
                        gap=(-4, 6))

    defs.append(linear("farfill", 0, horizon - 260, 0, horizon, (0, "#c46b8c"), (1, "#f09888")))
    body.append(f'<g opacity="0.9">{"".join(path(building_outline(b, horizon), "url(#farfill)") for b in far)}</g>')
    defs.append(linear("haze", 0, horizon - 200, 0, horizon, (0, "#ffb07c", 0), (1, "#ffd8a0", 0.7)))
    body.append(rect(0, horizon - 200, W, 202, "url(#haze)"))

    defs.append(linear("midfill", 0, horizon - 340, 0, horizon, (0, "#5a3374"), (1, "#8a4677")))
    for b in mid:
        body.append(path(building_outline(b, horizon), "url(#midfill)"))
        body.append(windows(rng, b, horizon, "#ffd08e", None, 0.14, size=(4, 6), gap=(4, 6), margin=(6, 12)))
        body.append(rim_light(b, horizon, sun_x, "#ffb27a", 2.0, 0.6))

    defs.append(linear("nearfill", 0, 240, 0, horizon, (0, "#1f1844"), (1, "#2b1e4f")))
    defs.append(blur("windowglow", 2.5))
    lit = []
    for b in near:
        body.append(path(building_outline(b, horizon), "url(#nearfill)"))
        body.append(windows(rng, b, horizon, "#ffd994", "#2c2457", 0.26, size=(6, 9), gap=(6, 7), margin=(9, 16)))
        body.append(rim_light(b, horizon, sun_x, "#ffa06a", 3.0, 0.9))
    tower = max((b for b in near if b.roof == "antenna"), key=lambda b: b.h)
    light_x, light_y = tower.x + tower.w * 0.62, horizon - tower.h - 47
    body.append(circle(light_x, light_y, 12, "#ff5a5a", ' opacity="0.45" filter="url(#windowglow)"'))
    body.append(circle(light_x, light_y, 4.5, "#ff6b6b"))

    # The river: the sky's colors, the city upside down and the sun's glitter.
    defs.append(linear("water", 0, horizon, 0, W,
                       (0, "#e47d79"), (0.12, "#a14f7c"), (0.4, "#4a2f6b"), (1, "#140f33")))
    body.append(rect(0, horizon, W, W - horizon, "url(#water)"))
    defs.append(
        '<filter id="ripple" x="-0.1" y="-0.1" width="1.2" height="1.2">'
        '<feTurbulence type="fractalNoise" baseFrequency="0.002 0.06" numOctaves="2" seed="5" result="n"/>'
        '<feDisplacementMap in="SourceGraphic" in2="n" scale="18" xChannelSelector="R" yChannelSelector="B"/>'
        '<feGaussianBlur stdDeviation="2 0.8"/></filter>')
    reflection = "".join(path(building_outline(b, horizon), "#6b3a73", ' opacity="0.6"') for b in mid)
    reflection += "".join(path(building_outline(b, horizon), "#241a4a", ' opacity="0.85"') for b in near)
    for b in near:
        for _ in range(int(b.w // 22)):
            if rng.random() < 0.5:
                x = b.x + rng.uniform(8, b.w - 8)
                y = horizon - rng.uniform(20, b.h - 20)
                reflection += ellipse(x, y, 2.2, 9, "#ffcf87", f' opacity="{f(rng.uniform(0.3, 0.7))}"')
    defs.append(linear("reflfade", 0, horizon, 0, W, (0, "white", 0.9), (0.6, "white", 0.35), (1, "white", 0.12)))
    defs.append(f'<mask id="reflmask"><rect y="{horizon}" width="{W}" height="{W - horizon}" fill="url(#reflfade)"/></mask>')
    body.append(f'<g mask="url(#reflmask)"><g filter="url(#ripple)">'
                f'<g transform="translate(0 {2 * horizon}) scale(1 -1)">{reflection}</g></g></g>')

    defs.append(radial("sunpath", sun_x, horizon, 330, (0, "#ffd890", 0.75), (0.4, "#ff9f6a", 0.3), (1, "#ff9f6a", 0),
                       transform=f"translate({sun_x} {horizon}) scale(0.42 1) translate({-sun_x} {-horizon})"))
    body.append(rect(0, horizon, W, W - horizon, "url(#sunpath)"))
    defs.append(blur("glint", 0.7))
    glints = []
    y = horizon + 5
    while y < W:
        t = (y - horizon) / (W - horizon)
        for _ in range(3):
            half = rng.uniform(8, 30) + 80 * t * rng.uniform(0.3, 1)
            x = sun_x + rng.gauss(0, 18 + 70 * t)
            color = rng.choice(["#fff6d6", "#ffe1a0", "#ffc27a"])
            opacity = (1 - t * 0.75) * rng.uniform(0.5, 1)
            glints.append(ellipse(x, y, half, 1.4 + 2.6 * t, color, f' opacity="{f(opacity)}"'))
        y += 5 + 15 * t * rng.uniform(0.7, 1.3)
    body.append(f'<g filter="url(#glint)">{"".join(glints)}</g>')
    defs.append(linear("shore", 0, horizon - 2, 0, horizon + 10, (0, "#ffe2ac", 0.95), (1, "#ffe2ac", 0)))
    body.append(rect(0, horizon - 1, W, 11, "url(#shore)"))

    body.append(birds([(720, 214, 1.25), (762, 238, 0.95), (686, 250, 0.8)], "#2a1d4d", 4.4))
    body.append(vignette(defs, "#0a0720", 0.42))
    return document(defs, body)


# ---------------------------------------------------------------------------
# Option 2: an alarm clock whose face is a window onto the city at sunrise


def option_clock():
    rng = random.Random(23)
    defs, body = [], []
    cx, cy = 512, 574
    case_r, bezel_r, face_r = 312, 290, 266

    # Background: warm dawn light with a faint sunburst behind the clock.
    defs.append(radial("bg", 512, 470, 760,
                       (0, "#ffe6b2"), (0.32, "#ffbe7e"), (0.62, "#f6836d"), (1, "#c8456f")))
    body.append(rect(0, 0, W, W, "url(#bg)"))
    burst = []
    for i in range(24):
        a0 = math.radians(i * 15)
        a1 = math.radians(i * 15 + 7.5)
        burst.append(path(poly([(512, 470), (512 + 1100 * math.cos(a0), 470 + 1100 * math.sin(a0)),
                                (512 + 1100 * math.cos(a1), 470 + 1100 * math.sin(a1))]), "#fff3d8"))
    defs.append(radial("burstfade", 512, 470, 640, (0, "white", 0.16), (1, "white", 0)))
    defs.append(f'<mask id="burstmask"><rect width="{W}" height="{W}" fill="url(#burstfade)"/></mask>')
    body.append(f'<g mask="url(#burstmask)">{"".join(burst)}</g>')

    # Shadow on the "table".
    defs.append(blur("shadow", 22, 1))
    body.append(ellipse(cx, 930, 290, 34, "#6b1f3f", ' opacity="0.45" filter="url(#shadow)"'))

    brass = [(0, "#fff4d2"), (0.25, "#f6cd73"), (0.5, "#c88936"), (0.7, "#f9dc94"), (1, "#8f561c")]

    # Legs.
    defs.append(linear("leg", 300, 800, 330, 900, *brass))
    for side in (-1, 1):
        x0, y0 = cx + side * 176, cy + 236
        x1, y1 = cx + side * 232, 902
        body.append(f'<path d="M{f(x0)} {f(y0)} L{f(x1)} {f(y1)}" stroke="url(#leg)" stroke-width="30" stroke-linecap="round"/>')
        body.append(circle(x1, y1 + 4, 22, "url(#leg)"))

    # Bells, hammer and handle sit behind the case.
    defs.append(radial("bell", -40, -70, 150, (0, "#fff8e0"), (0.3, "#f8d27c"), (0.7, "#c98a38"), (1, "#7d4815")))
    defs.append(linear("bellrim", -100, 0, 100, 0, (0, "#8a5420"), (0.4, "#f7d488"), (0.6, "#ffefc2"), (1, "#7a4614")))
    for side in (-1, 1):
        angle = side * 38
        bx = cx + side * 316 * math.sin(math.radians(38))
        by = cy - 316 * math.cos(math.radians(38))
        bell = ('<path d="M-104 0 C-104 -66 -62 -104 0 -104 C62 -104 104 -66 104 0 Z" fill="url(#bell)"/>'
                '<ellipse cx="0" cy="2" rx="112" ry="17" fill="url(#bellrim)"/>'
                '<rect x="-9" y="-128" width="18" height="30" rx="5" fill="#b9792e"/>'
                '<circle cx="0" cy="-132" r="13" fill="url(#bell)"/>'
                '<path d="M-70 -62 C-58 -84 -34 -96 -8 -98" stroke="#fffbe8" stroke-width="10" '
                'stroke-linecap="round" fill="none" opacity="0.75"/>')
        body.append(f'<g transform="translate({f(bx)} {f(by)}) rotate({angle}) translate(0 -14)">{bell}</g>')
    body.append(f'<path d="M{cx} {cy - case_r + 10} L{cx} {cy - case_r - 66}" stroke="#b77a32" stroke-width="12" stroke-linecap="round"/>')
    body.append(circle(cx, cy - case_r - 74, 19, "url(#leg)"))
    defs.append(linear("handle", 400, 150, 620, 250, *brass))
    body.append(f'<path d="M{cx - 92} {cy - case_r + 26} C{cx - 86} {cy - case_r - 120} {cx + 86} {cy - case_r - 120} '
                f'{cx + 92} {cy - case_r + 26}" stroke="url(#handle)" stroke-width="20" fill="none" stroke-linecap="round"/>')

    # Ringing.
    for side in (-1, 1):
        ox = cx + side * 316 * math.sin(math.radians(38))
        oy = cy - 316 * math.cos(math.radians(38))
        for k, radius in enumerate((142, 178)):
            a_mid = -90 + side * 56
            a0, a1 = math.radians(a_mid - 26), math.radians(a_mid + 26)
            p0 = (ox + radius * math.cos(a0), oy + radius * math.sin(a0))
            p1 = (ox + radius * math.cos(a1), oy + radius * math.sin(a1))
            body.append(f'<path d="M{f(p0[0])} {f(p0[1])} A{radius} {radius} 0 0 1 {f(p1[0])} {f(p1[1])}" '
                        f'stroke="#fffaf0" stroke-width="{14 - 3 * k}" stroke-linecap="round" fill="none" '
                        f'opacity="{0.9 - 0.25 * k}"/>')

    # Case: glossy navy enamel.
    defs.append(radial("case", cx - 120, cy - 150, 470,
                       (0, "#4a5fb0"), (0.35, "#26357a"), (0.75, "#141d4d"), (1, "#0b1030")))
    body.append(circle(cx, cy, case_r, "url(#case)"))
    defs.append(linear("caserim", cx - 200, cy - 260, cx + 220, cy + 280,
                       (0, "#ffffff", 0.55), (0.35, "#ffffff", 0), (0.7, "#ff9d6e", 0), (1, "#ff9d6e", 0.55)))
    body.append(circle(cx, cy, case_r - 4, "none", ' stroke="url(#caserim)" stroke-width="8"'))

    # Bezel.
    defs.append(linear("bezel", cx - 260, cy - 260, cx + 260, cy + 260,
                       (0, "#fff6da"), (0.2, "#f3c86e"), (0.42, "#a96b26"), (0.6, "#fbe3a6"), (0.8, "#c9893a"), (1, "#7a4512")))
    body.append(circle(cx, cy, bezel_r, "url(#bezel)"))
    body.append(circle(cx, cy, face_r + 6, "#5a3313"))

    # The face: the city at sunrise.
    defs.append(f'<clipPath id="face"><circle cx="{cx}" cy="{cy}" r="{face_r}"/></clipPath>')
    horizon = cy + 108
    sun_x, sun_y, sun_r = cx + 66, horizon - 44, 90
    scene = []
    defs.append(linear("facesky", 0, cy - face_r, 0, horizon,
                       (0, "#232566"), (0.35, "#55408f"), (0.62, "#c25a86"), (0.82, "#f5906f"), (1, "#ffd08c")))
    scene.append(rect(cx - face_r, cy - face_r, 2 * face_r, horizon - cy + face_r + 2, "url(#facesky)"))
    for _ in range(26):
        x, y = cx + rng.uniform(-200, 200), cy - face_r + rng.uniform(20, 150)
        scene.append(circle(x, y, rng.choice([1.2, 1.6, 2.0]), "#ffffff", f' opacity="{f(rng.uniform(0.3, 0.8))}"'))
    defs.append(radial("faceglow", sun_x, sun_y, 330,
                       (0, "#fff2c4", 1), (0.2, "#ffd27e", 0.7), (0.5, "#ff8f6a", 0.25), (1, "#ff8f6a", 0)))
    scene.append(rect(cx - face_r, cy - face_r, 2 * face_r, 2 * face_r, "url(#faceglow)"))
    defs.append(radial("facesun", sun_x - 20, sun_y - 30, sun_r * 1.3, (0, "#fffef4"), (0.6, "#ffeaa8"), (1, "#ffb95c")))
    scene.append(circle(sun_x, sun_y, sun_r, "url(#facesun)"))

    def profile(x):
        d = abs(x - sun_x) / face_r
        return 20 + 230 * d ** 1.6

    mid = make_skyline(rng, cx - face_r - 20, cx + face_r + 20, lambda x: profile(x) * 1.25 + 30, 22, 40,
                       ["flat", "spire", "antenna", "dome", "slant"])
    near = make_skyline(rng, cx - face_r - 20, cx + face_r + 20, profile, 30, 54,
                        ["flat", "step", "antenna", "tank", "flat"], gap=(-3, 3))
    defs.append(linear("facemid", 0, horizon - 220, 0, horizon, (0, "#8e4a86"), (1, "#d97a86")))
    scene.append("".join(path(building_outline(b, horizon), "url(#facemid)") for b in mid))
    for b in near:
        scene.append(path(building_outline(b, horizon), "#1f1a4a"))
        scene.append(windows(rng, b, horizon, "#ffd68f", None, 0.3, size=(4, 6), gap=(4, 5), margin=(6, 10)))
        scene.append(rim_light(b, horizon, sun_x, "#ffa46c", 2.0, 0.85))
    defs.append(linear("facewater", 0, horizon, 0, cy + face_r, (0, "#d4727c"), (0.3, "#5a3772"), (1, "#1a1440")))
    scene.append(rect(cx - face_r, horizon, 2 * face_r, cy + face_r - horizon, "url(#facewater)"))
    for k in range(16):
        y = horizon + 6 + k * 10
        half = 20 + k * 6 + rng.uniform(-6, 6)
        scene.append(ellipse(sun_x + rng.uniform(-8, 8), y, half, 2 + k * 0.15, "#ffe2a4",
                             f' opacity="{f(0.9 - k * 0.05)}"'))
    body.append(f'<g clip-path="url(#face)">{"".join(scene)}</g>')

    # Dial: ticks, hands at 7:00 and a second hand.
    dial = []
    for i in range(60):
        a = math.radians(i * 6)
        major = i % 5 == 0
        r0 = face_r - (34 if i % 15 == 0 else 26 if major else 12)
        r1 = face_r - 8
        width = 10 if i % 15 == 0 else 7 if major else 3
        x0, y0 = cx + r0 * math.sin(a), cy - r0 * math.cos(a)
        x1, y1 = cx + r1 * math.sin(a), cy - r1 * math.cos(a)
        dial.append(f'<path d="M{f(x0)} {f(y0)} L{f(x1)} {f(y1)}" stroke="#fff8ea" stroke-width="{width}" '
                    f'stroke-linecap="round" opacity="{1 if major else 0.75}"/>')
    defs.append('<filter id="handshadow" x="-0.5" y="-0.5" width="2" height="2">'
                '<feDropShadow dx="0" dy="5" stdDeviation="5" flood-color="#0b0a2a" flood-opacity="0.55"/></filter>')
    body.append(f'<g filter="url(#handshadow)">{"".join(dial)}</g>')

    def hand(angle, length, width, tail, color):
        a = math.radians(angle)
        ux, uy = math.sin(a), -math.cos(a)
        px, py = -uy, ux
        tip = (cx + ux * length, cy + uy * length)
        back = (cx - ux * tail, cy - uy * tail)
        pts = [(back[0] + px * width * 0.35, back[1] + py * width * 0.35),
               (cx + ux * length * 0.82 + px * width / 2, cy + uy * length * 0.82 + py * width / 2), tip,
               (cx + ux * length * 0.82 - px * width / 2, cy + uy * length * 0.82 - py * width / 2),
               (back[0] - px * width * 0.35, back[1] - py * width * 0.35)]
        return path(poly(pts), color, ' stroke="#141236" stroke-width="3" stroke-linejoin="round"')

    hands = [hand(210, 132, 26, 26, "#fff8ea"), hand(0, 214, 18, 30, "#fff8ea")]
    sa = math.radians(62)
    hands.append(f'<path d="M{f(cx - 52 * math.sin(sa))} {f(cy + 52 * math.cos(sa))} '
                 f'L{f(cx + 226 * math.sin(sa))} {f(cy - 226 * math.cos(sa))}" stroke="#ff5b3a" stroke-width="6" '
                 f'stroke-linecap="round"/>')
    hands.append(circle(cx, cy, 22, "url(#leg)"))
    hands.append(circle(cx, cy, 8, "#5a3313"))
    body.append(f'<g filter="url(#handshadow)">{"".join(hands)}</g>')

    # Glass: inner shadow, a soft reflection and a bright highlight.
    defs.append(radial("glassedge", cx, cy, face_r, (0.8, "#0b0a2a", 0), (1, "#0b0a2a", 0.45)))
    body.append(circle(cx, cy, face_r, "url(#glassedge)"))
    defs.append(linear("glare", cx - 200, cy - 240, cx + 60, cy + 40, (0, "#ffffff", 0.42), (1, "#ffffff", 0)))
    body.append(f'<path d="M{cx - 236} {cy + 40} A{face_r - 22} {face_r - 22} 0 0 1 {cx + 120} {cy - 214} '
                f'C{cx - 20} {cy - 150} {cx - 160} {cy - 60} {cx - 236} {cy + 40} Z" fill="url(#glare)"/>')
    body.append(ellipse(cx - 150, cy - 168, 26, 12, "#ffffff", ' opacity="0.55" transform="rotate(-40 362 406)"'))

    return document(defs, body)


# ---------------------------------------------------------------------------
# Option 3: the sunrise through an arched window


def option_window():
    rng = random.Random(37)
    defs, body = [], []
    ax, ay = 512, 446           # center of the arch
    outer_r, inner_r = 334, 304
    left, right = ax - inner_r, ax + inner_r
    bottom = 812                # bottom of the glass
    horizon = 742
    sun_x, sun_y, sun_r = 512, 650, 112

    # The room: a dark wall lit by the window.
    defs.append(linear("wall", 0, 0, 0, W, (0, "#2a2357"), (0.6, "#231c4b"), (1, "#160f33")))
    body.append(rect(0, 0, W, W, "url(#wall)"))
    defs.append(radial("spill", ax, 560, 640, (0, "#ff9f73", 0.55), (0.45, "#e0607a", 0.18), (1, "#e0607a", 0)))
    body.append(rect(0, 0, W, W, "url(#spill)"))

    # Sunbeams into the room.
    defs.append(blur("beamblur", 10))
    beams = []
    for i in range(14):
        a = math.radians(-180 + i * 360 / 14 + rng.uniform(-6, 6))
        spread = math.radians(rng.uniform(2.5, 4.5))
        far = 1100
        p1 = (sun_x + far * math.cos(a - spread), sun_y + far * math.sin(a - spread))
        p2 = (sun_x + far * math.cos(a + spread), sun_y + far * math.sin(a + spread))
        beams.append(path(poly([(sun_x, sun_y), p1, p2]), "#ffd9a8", f' opacity="{f(rng.uniform(0.05, 0.1))}"'))
    body.append(f'<g filter="url(#beamblur)" style="mix-blend-mode:screen">{"".join(beams)}</g>')

    window_shape = (f"M{left} {bottom} L{left} {ay} A{inner_r} {inner_r} 0 0 1 {right} {ay} "
                    f"L{right} {bottom} Z")
    defs.append(f'<clipPath id="glass"><path d="{window_shape}"/></clipPath>')

    # The view.
    scene = []
    defs.append(linear("winsky", 0, ay - inner_r, 0, horizon,
                       (0, "#25256a"), (0.3, "#4f3c8e"), (0.55, "#a7508a"), (0.75, "#ec7b74"), (0.9, "#ffb877"), (1, "#ffe0a6")))
    scene.append(rect(left, ay - inner_r, 2 * inner_r, horizon - ay + inner_r + 2, "url(#winsky)"))
    for _ in range(30):
        x, y = rng.uniform(left + 20, right - 20), rng.uniform(ay - inner_r + 30, ay - 120)
        scene.append(circle(x, y, rng.choice([1.2, 1.6, 2.1]), "#ffffff", f' opacity="{f(rng.uniform(0.3, 0.8))}"'))
    defs.append(radial("winglow", sun_x, sun_y, 560,
                       (0, "#fff3c8", 1), (0.14, "#ffd884", 0.8), (0.36, "#ff9c68", 0.35), (1, "#ff9c68", 0)))
    scene.append(rect(left, ay - inner_r, 2 * inner_r, horizon - ay + inner_r, "url(#winglow)"))
    defs.append(blur("wincloud", 2))
    for i, (cy, cx, span) in enumerate([(300, 370, 220), (392, 668, 250), (520, 300, 170)]):
        defs.append(linear(f"wcloud{i}", 0, cy - 18, 0, cy + 14, (0, "#6c4a8f"), (0.6, "#e48390"), (1, "#ffd0a0")))
        parts = []
        x = cx - span / 2
        while x < cx + span / 2:
            rx = rng.uniform(28, 56)
            parts.append(ellipse(x + rx, cy + rng.uniform(-7, 4), rx, rng.uniform(8, 13), f"url(#wcloud{i})"))
            x += rx * rng.uniform(1.0, 1.4)
        scene.append(f'<g filter="url(#wincloud)" opacity="0.9">{"".join(parts)}</g>')
    defs.append(radial("winsun", sun_x - 26, sun_y - 40, sun_r * 1.25, (0, "#fffef5"), (0.55, "#fff0b6"), (1, "#ffb75c")))
    defs.append(blur("winbloom", 30, 1))
    scene.append(circle(sun_x, sun_y, sun_r * 1.3, "#ffe2a0", ' opacity="0.8" filter="url(#winbloom)"'))
    scene.append(circle(sun_x, sun_y, sun_r, "url(#winsun)"))
    scene.append(birds([(640, 470, 1.1), (676, 494, 0.85), (608, 500, 0.7)], "#3a2558", 4.4))

    def profile_mid(x):
        return 40 + 230 * (abs(x - sun_x) / inner_r) ** 1.5

    def profile_near(x):
        return 24 + 300 * (abs(x - sun_x) / inner_r) ** 2

    mid = make_skyline(rng, left - 20, right + 20, profile_mid, 24, 46, ["flat", "spire", "antenna", "dome", "slant", "step"])
    near = make_skyline(rng, left - 20, right + 20, profile_near, 34, 64, ["flat", "step", "antenna", "tank", "flat"],
                        gap=(-3, 4))
    defs.append(linear("winmid", 0, horizon - 300, 0, horizon, (0, "#8c4a86"), (1, "#e3828a")))
    scene.append("".join(path(building_outline(b, horizon), "url(#winmid)") for b in mid))
    defs.append(linear("winhaze", 0, horizon - 120, 0, horizon, (0, "#ffc08a", 0), (1, "#ffd8a2", 0.6)))
    scene.append(rect(left, horizon - 120, 2 * inner_r, 122, "url(#winhaze)"))
    for b in near:
        scene.append(path(building_outline(b, horizon), "#221b4b"))
        scene.append(windows(rng, b, horizon, "#ffd894", None, 0.28, size=(5, 7), gap=(5, 6), margin=(7, 12)))
        scene.append(rim_light(b, horizon, sun_x, "#ffa46c", 2.5, 0.85))
    defs.append(linear("winwater", 0, horizon, 0, bottom, (0, "#e07e7c"), (0.4, "#6d3f78"), (1, "#2a1d52")))
    scene.append(rect(left, horizon, 2 * inner_r, bottom - horizon, "url(#winwater)"))
    for k in range(9):
        y = horizon + 5 + k * 8
        scene.append(ellipse(sun_x + rng.uniform(-6, 6), y, 26 + k * 9, 2 + k * 0.2, "#ffe4a8",
                             f' opacity="{f(0.9 - k * 0.08)}"'))
    # Reflections on the glass.
    defs.append(linear("glare3", left, ay - 200, right, bottom, (0, "#ffffff", 0.16), (0.5, "#ffffff", 0.02), (1, "#ffffff", 0.1)))
    scene.append(rect(left, ay - inner_r, 2 * inner_r, bottom - ay + inner_r, "url(#glare3)"))
    for x0, width in ((300, 70), (392, 26), (640, 46)):
        scene.append(path(poly([(x0, bottom), (x0 + width, bottom), (x0 + width + 300, ay - inner_r), (x0 + 300, ay - inner_r)]),
                          "#ffffff", ' opacity="0.07"'))
    body.append(f'<g clip-path="url(#glass)">{"".join(scene)}</g>')

    # Frame: painted wood with a bevel, a fanlight like the rays of the sun.
    frame_outer = (f"M{ax - outer_r} {bottom + 12} L{ax - outer_r} {ay} A{outer_r} {outer_r} 0 0 1 {ax + outer_r} {ay} "
                   f"L{ax + outer_r} {bottom + 12} Z")
    defs.append(linear("frame", 0, ay - outer_r, 0, bottom, (0, "#fff6e6"), (0.5, "#f4e2c6"), (1, "#d9bf9b")))
    defs.append(f'<mask id="framemask"><path d="{frame_outer}" fill="white"/><path d="{window_shape}" fill="black"/></mask>')
    defs.append('<filter id="frameshadow" x="-0.2" y="-0.2" width="1.4" height="1.4">'
                '<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#0c0824" flood-opacity="0.55"/></filter>')
    body.append(f'<g filter="url(#frameshadow)"><path d="{frame_outer}" fill="url(#frame)" mask="url(#framemask)"/></g>')
    body.append(f'<path d="{window_shape}" fill="none" stroke="#b89a74" stroke-width="5" opacity="0.8"/>')
    body.append(f'<path d="{frame_outer}" fill="none" stroke="#fffaf0" stroke-width="3" opacity="0.7"/>')

    bars = []
    bar_color = "url(#frame)"
    bars.append(rect(left, ay - 9, 2 * inner_r, 18, bar_color))
    for angle in (30, 60, 90, 120, 150):
        a = math.radians(180 + angle)
        x1, y1 = ax + inner_r * math.cos(a), ay + inner_r * math.sin(a)
        bars.append(f'<path d="M{ax} {ay} L{f(x1)} {f(y1)}" stroke="{bar_color}" stroke-width="13"/>')
    bars.append(f'<path d="M{ax - 74} {ay} A74 74 0 0 1 {ax + 74} {ay} Z" fill="{bar_color}"/>')
    bars.append(f'<path d="M{ax - 52} {ay - 9} A52 52 0 0 1 {ax + 52} {ay - 9} Z" fill="#ffd27e" opacity="0.85"/>')
    defs.append('<filter id="barshadow" x="-0.2" y="-0.2" width="1.4" height="1.4">'
                '<feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#2a1640" flood-opacity="0.45"/></filter>')
    body.append(f'<g clip-path="url(#glass)" filter="url(#barshadow)">{"".join(bars)}</g>')

    # Sill, with a plant and a cup of coffee.
    defs.append(linear("sill", 0, bottom + 8, 0, bottom + 64, (0, "#fff4e2"), (0.45, "#ead3b0"), (1, "#b99572")))
    body.append(f'<g filter="url(#frameshadow)"><rect x="{ax - outer_r - 44}" y="{bottom + 6}" width="{2 * outer_r + 88}" '
                f'height="40" rx="10" fill="url(#sill)"/></g>')
    body.append(rect(ax - outer_r - 40, bottom + 8, 2 * outer_r + 80, 6, "#ffffff", ' opacity="0.6" rx="3"'))

    px, py = 258, bottom + 8
    defs.append(linear("pot", px - 40, 0, px + 40, 0, (0, "#b6532f"), (0.45, "#e9875a"), (1, "#8f3a1f")))
    leaves = []
    for k, (angle, length) in enumerate([(-62, 96), (-90, 112), (-118, 92), (-40, 74), (-140, 72), (-76, 70), (-104, 78)]):
        a = math.radians(angle)
        tip = (px + length * math.cos(a), py - 70 + length * math.sin(a))
        mid = (px + length * 0.5 * math.cos(a), py - 70 + length * 0.5 * math.sin(a))
        nx, ny = -math.sin(a) * 18, math.cos(a) * 18
        d = (f"M{px} {py - 70} Q{f(mid[0] + nx)} {f(mid[1] + ny)} {f(tip[0])} {f(tip[1])} "
             f"Q{f(mid[0] - nx)} {f(mid[1] - ny)} {px} {py - 70} Z")
        leaves.append(path(d, "#2f8f5b" if k % 2 else "#3fb072"))
        leaves.append(f'<path d="M{px} {py - 70} L{f(tip[0])} {f(tip[1])}" stroke="#1f6b41" stroke-width="2" opacity="0.6"/>')
    body.append("".join(leaves))
    body.append(path(f"M{px - 44} {py - 74} L{px + 44} {py - 74} L{px + 34} {py} L{px - 34} {py} Z", "url(#pot)"))
    body.append(rect(px - 50, py - 84, 100, 18, "#d46a40", ' rx="5"'))

    mx, my = 770, bottom + 8
    defs.append(linear("mug", mx - 40, 0, mx + 40, 0, (0, "#e8e2f4"), (0.4, "#ffffff"), (1, "#b7aed0")))
    body.append(f'<path d="M{mx + 34} {my - 62} C{mx + 74} {my - 62} {mx + 74} {my - 18} {mx + 30} {my - 20}" '
                f'stroke="#cfc6e4" stroke-width="12" fill="none"/>')
    body.append(path(f"M{mx - 40} {my - 78} L{mx + 40} {my - 78} L{mx + 34} {my - 6} Q{mx} {my + 4} {mx - 34} {my - 6} Z", "url(#mug)"))
    body.append(ellipse(mx, my - 78, 40, 9, "#6b3a22"))
    body.append(ellipse(mx, my - 80, 36, 6, "#8a4c2c"))
    for k, offset in enumerate((-14, 6, 24)):
        body.append(f'<path d="M{mx + offset} {my - 96} c-14 -22 14 -34 0 -58 c-10 -16 6 -28 4 -38" stroke="#ffffff" '
                    f'stroke-width="7" fill="none" stroke-linecap="round" opacity="{f(0.45 - k * 0.08)}"/>')

    # Dust in the light.
    for _ in range(40):
        x, y = rng.gauss(512, 200), rng.gauss(560, 220)
        body.append(circle(x, y, rng.uniform(1, 2.6), "#fff1d6", f' opacity="{f(rng.uniform(0.15, 0.5))}"'))

    body.append(vignette(defs, "#0a0720", 0.4))
    return document(defs, body)


# ---------------------------------------------------------------------------
# Option 4: an isometric city block at sunrise


ISO_ORIGIN = (512, 616)
ISO_UNIT = 62


def iso(x, y, z=0.0):
    ox, oy = ISO_ORIGIN
    return (ox + (x - y) * 0.8660254 * ISO_UNIT, oy + (x + y) * 0.5 * ISO_UNIT - z * ISO_UNIT)


def iso_poly(points):
    return poly([iso(*p) for p in points])


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def iso_face_windows(rng, corner, along, height, length, color_fn, cols_step=0.3, rows_step=0.32,
                     size=(0.15, 0.17), margin=(0.16, 0.22), z0=0.0):
    """Windows on a vertical face that starts at `corner` and runs along `along` (a unit vector)."""
    out = []
    ww, wh = size
    cols = int((length - 2 * margin[0] + (cols_step - ww)) // cols_step)
    rows = int((height - margin[1] - 0.18 + (rows_step - wh)) // rows_step)
    if cols <= 0 or rows <= 0:
        return ""
    start = (length - (cols * cols_step - (cols_step - ww))) / 2
    for r in range(rows):
        z = z0 + 0.18 + r * rows_step
        for c in range(cols):
            color = color_fn()
            if color is None:
                continue
            fill, opacity = color
            u0 = start + c * cols_step
            p = [(corner[0] + along[0] * (u0 + du), corner[1] + along[1] * (u0 + du), z + dz)
                 for du, dz in ((0, 0), (ww, 0), (ww, wh), (0, wh))]
            out.append(path(iso_poly(p), fill, f' opacity="{f(opacity)}"'))
    return "".join(out)


def option_isometric():
    rng = random.Random(41)
    defs, body = [], []
    sun_x, sun_y, sun_r = 236, 300, 112

    defs.append(linear("isosky", 0, 0, 0, W,
                       (0, "#1d2463"), (0.32, "#4b3b8e"), (0.58, "#b65a8e"), (0.8, "#f59082"), (1, "#ffcf98")))
    body.append(rect(0, 0, W, W, "url(#isosky)"))
    for _ in range(36):
        x, y = rng.uniform(380, W - 20), rng.uniform(16, 260)
        body.append(circle(x, y, rng.choice([1.2, 1.6, 2.1]), "#ffffff", f' opacity="{f(rng.uniform(0.25, 0.75))}"'))
    defs.append(radial("isoglow", sun_x, sun_y, 720,
                       (0, "#fff2c6", 1), (0.12, "#ffd98c", 0.75), (0.34, "#ff9f73", 0.32), (1, "#ff9f73", 0)))
    body.append(rect(0, 0, W, W, "url(#isoglow)"))
    defs.append(radial("isosun", sun_x - 24, sun_y - 34, sun_r * 1.25, (0, "#fffef5"), (0.55, "#fff0b8"), (1, "#ffb95e")))
    defs.append(blur("isobloom", 32, 1))
    body.append(circle(sun_x, sun_y, sun_r * 1.3, "#ffe4a6", ' opacity="0.8" filter="url(#isobloom)"'))
    body.append(circle(sun_x, sun_y, sun_r, "url(#isosun)"))

    # Clouds behind the island.
    defs.append(blur("isocloud", 3))
    defs.append(linear("cloudfill", 0, 0, 0, 1, (0, "#ffe9e4"), (1, "#e9a4b8")))

    def cloud(x, y, scale, opacity):
        defs_id = f"cl{len(defs)}"
        defs.append(linear(defs_id, 0, y - 60 * scale, 0, y + 30 * scale, (0, "#fff4ee"), (0.7, "#f6c1c6"), (1, "#d98ba8")))
        blobs = [(-70, 0, 46), (-20, -26, 58), (40, -14, 50), (88, 4, 38), (10, 12, 52), (-110, 14, 30)]
        parts = "".join(circle(x + bx * scale, y + by * scale, r * scale, f"url(#{defs_id})") for bx, by, r in blobs)
        return f'<g filter="url(#isocloud)" opacity="{f(opacity)}">{parts}</g>'

    body.append(cloud(840, 330, 0.9, 0.85))
    body.append(cloud(170, 560, 0.75, 0.6))

    # The island: a slab with the block on top.
    n = 3.0
    thick = 0.75
    corners = [(-n, -n), (n, -n), (n, n), (-n, n)]
    defs.append(blur("islandshadow", 30, 1))
    body.append(ellipse(512, 930, 300, 46, "#5b2559", ' opacity="0.35" filter="url(#islandshadow)"'))
    defs.append(linear("slableft", 0, 600, 0, 900, (0, "#e9978b"), (1, "#a8566f")))
    defs.append(linear("slabright", 0, 600, 0, 900, (0, "#4e3b86"), (1, "#2a1f55")))
    body.append(path(iso_poly([(-n, n, 0), (n, n, 0), (n, n, -thick), (-n, n, -thick)]), "url(#slableft)"))
    body.append(path(iso_poly([(n, -n, 0), (n, n, 0), (n, n, -thick), (n, -n, -thick)]), "url(#slabright)"))
    for z, color, opacity in ((-0.22, "#fff1e2", 0.35), (-0.24, "#1e1640", 0.25)):
        body.append(f'<path d="M{f(iso(-n, n, z)[0])} {f(iso(-n, n, z)[1])} L{f(iso(n, n, z)[0])} {f(iso(n, n, z)[1])} '
                    f'L{f(iso(n, -n, z)[0])} {f(iso(n, -n, z)[1])}" stroke="{color}" stroke-width="3" fill="none" opacity="{opacity}"/>')
    defs.append(linear("ground", 0, 420, 0, 820, (0, "#e7b3bd"), (1, "#c98ea9")))
    body.append(path(iso_poly([(x, y, 0) for x, y in corners]), "url(#ground)"))
    defs.append(f'<clipPath id="tile"><path d="{iso_poly([(x, y, 0) for x, y in corners])}"/></clipPath>')

    # Streets: a crossroads with lane marks and zebra crossings.
    ground = []
    road = 0.36
    ground.append(path(iso_poly([(-n, -road, 0), (n, -road, 0), (n, road, 0), (-n, road, 0)]), "#5d4b88"))
    ground.append(path(iso_poly([(-road, -n, 0), (road, -n, 0), (road, n, 0), (-road, n, 0)]), "#5d4b88"))
    for k in range(-5, 6):
        a, b = k * 0.55 - 0.14, k * 0.55 + 0.14
        if abs(k * 0.55) > road + 0.3:
            ground.append(path(iso_poly([(a, -0.03, 0), (b, -0.03, 0), (b, 0.03, 0), (a, 0.03, 0)]), "#f6e9ff", ' opacity="0.85"'))
            ground.append(path(iso_poly([(-0.03, a, 0), (0.03, a, 0), (0.03, b, 0), (-0.03, b, 0)]), "#f6e9ff", ' opacity="0.85"'))
    for side in (-1, 1):
        for k in range(5):
            c = -road + 0.1 + k * 0.14
            d0, d1 = side * (road + 0.06), side * (road + 0.3)
            ground.append(path(iso_poly([(c, d0, 0), (c + 0.07, d0, 0), (c + 0.07, d1, 0), (c, d1, 0)]), "#ffffff", ' opacity="0.8"'))
            ground.append(path(iso_poly([(d0, c, 0), (d1, c, 0), (d1, c + 0.07, 0), (d0, c + 0.07, 0)]), "#ffffff", ' opacity="0.8"'))
    # A park in front.
    ground.append(path(iso_poly([(road + 0.12, road + 0.12, 0), (n - 0.12, road + 0.12, 0), (n - 0.12, n - 0.12, 0),
                                 (road + 0.12, n - 0.12, 0)]), "#79c48f"))
    ground.append(f'<path d="{iso_poly([(1.05, 1.0, 0), (2.4, 1.0, 0), (2.4, 1.18, 0), (1.05, 1.18, 0)])}" fill="#f2d7b8" opacity="0.9"/>')
    ground.append(f'<path d="{iso_poly([(1.5, 0.55, 0), (1.68, 0.55, 0), (1.68, 2.85, 0), (1.5, 2.85, 0)])}" fill="#f2d7b8" opacity="0.9"/>')

    # Buildings: (x, y, width, depth, height, palette).
    palettes = {
        "peach": ("#ffe3c8", "#f7a07f", "#56418e"),
        "lilac": ("#f6e0ff", "#d29ce4", "#45367f"),
        "glass": ("#dbe8ff", "#97b5f2", "#2f3a7c"),
        "cream": ("#fff3dc", "#f4c690", "#5b468b"),
    }
    buildings = [
        (-2.85, -2.85, 1.15, 1.15, 4.6, "glass"), (-1.5, -2.8, 0.95, 1.0, 3.2, "peach"), (-2.8, -1.45, 1.0, 0.9, 2.7, "lilac"),
        (-1.45, -1.4, 0.9, 0.88, 1.9, "cream"),
        (0.62, -2.8, 1.0, 1.05, 2.4, "lilac"), (1.85, -2.75, 1.0, 0.95, 3.6, "peach"), (0.62, -1.5, 1.05, 0.95, 1.4, "cream"),
        (1.95, -1.5, 0.9, 0.95, 1.9, "glass"),
        (-2.8, 0.62, 0.95, 1.0, 2.2, "cream"), (-2.75, 1.85, 0.95, 1.0, 1.5, "peach"), (-1.55, 0.6, 1.0, 1.1, 3.0, "glass"),
        (-1.5, 1.95, 0.9, 0.9, 1.1, "lilac"),
        (2.2, 1.9, 0.68, 0.7, 0.75, "peach"),
    ]
    light_dir = (0.62, -0.62)   # where the shadows fall

    shadows = []
    for x, y, w, d, h, _ in buildings:
        foot = [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]
        reach = h * 0.55
        swept = foot + [(px + light_dir[0] * reach, py + light_dir[1] * reach) for px, py in foot]
        shadows.append(path(iso_poly([(px, py, 0) for px, py in convex_hull(swept)]), "#3a2462", ' opacity="0.3"'))
    trees = [(0.95, 2.1), (1.25, 2.6), (2.0, 2.45), (2.6, 2.6), (2.65, 1.45), (0.95, 0.9), (2.1, 0.75)]
    for tx, ty in trees:
        shadows.append(path(iso_poly([(tx + dx * 0.22 + light_dir[0] * 0.3, ty + dy * 0.22 + light_dir[1] * 0.3, 0)
                                      for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]), "#2f5a46", ' opacity="0.35"'))
    body.append(f'<g clip-path="url(#tile)">{"".join(ground)}{"".join(shadows)}</g>')

    # Draw from back to front.
    items = [(x + y + w + d, "building", (x, y, w, d, h, pal)) for x, y, w, d, h, pal in buildings]
    items += [(tx + ty + 0.4, "tree", (tx, ty)) for tx, ty in trees]
    items.append((2.0, "car", (1.9, -0.3, "#ff6b5a")))
    items.append((1.4, "car", (0.85, 0.06, "#ffd166")))
    items.append((1.6, "car", (-0.3, 1.45, "#7fd1ff")))
    for _, kind, data in sorted(items, key=lambda item: item[0]):
        if kind == "tree":
            tx, ty = data
            base = iso(tx, ty, 0)
            body.append(rect(base[0] - 3.5, base[1] - 30, 7, 30, "#7a4a3a", ' rx="3"'))
            gid = f"tree{len(defs)}"
            defs.append(radial(gid, base[0] - 12, base[1] - 52, 34, (0, "#b9f0a6"), (0.55, "#58b878"), (1, "#2e7a55")))
            body.append(circle(base[0], base[1] - 42, 23, f"url(#{gid})"))
            continue
        if kind == "car":
            cx0, cy0, color = data
            alongx = abs(cy0) < 0.4
            w, d = (0.5, 0.24) if alongx else (0.24, 0.5)
            pts = lambda z: [(cx0, cy0, z), (cx0 + w, cy0, z), (cx0 + w, cy0 + d, z), (cx0, cy0 + d, z)]
            body.append(path(iso_poly([(cx0, cy0 + d, 0), (cx0 + w, cy0 + d, 0), (cx0 + w, cy0 + d, 0.18), (cx0, cy0 + d, 0.18)]), color))
            body.append(path(iso_poly([(cx0 + w, cy0, 0), (cx0 + w, cy0 + d, 0), (cx0 + w, cy0 + d, 0.18), (cx0 + w, cy0, 0.18)]),
                             color, ' opacity="0.75"'))
            body.append(path(iso_poly(pts(0.18)), "#ffffff", ' opacity="0.85"'))
            continue
        x, y, w, d, h, pal = data
        top, lit, dark = palettes[pal]
        x1, y1 = x + w, y + d
        gid = f"lit{len(defs)}"
        a, b = iso(x, y1, 0), iso(x, y1, h)
        defs.append(linear(gid, a[0], a[1], b[0], b[1], (0, lit), (1, "#ffe6cf")))
        body.append(path(iso_poly([(x, y1, 0), (x1, y1, 0), (x1, y1, h), (x, y1, h)]), f"url(#{gid})"))
        body.append(path(iso_poly([(x1, y, 0), (x1, y1, 0), (x1, y1, h), (x1, y, h)]), dark))
        body.append(path(iso_poly([(x, y, h), (x1, y, h), (x1, y1, h), (x, y1, h)]), top))
        inset = 0.08
        body.append(path(iso_poly([(x + inset, y + inset, h), (x1 - inset, y + inset, h), (x1 - inset, y1 - inset, h),
                                   (x + inset, y1 - inset, h)]), lit, ' opacity="0.35"'))
        if pal == "glass":
            for k in range(1, int(w / 0.2)):
                u = x + k * 0.2
                body.append(f'<path d="{iso_poly([(u, y1, 0.1), (u + 0.02, y1, 0.1), (u + 0.02, y1, h - 0.1), (u, y1, h - 0.1)])}" '
                            f'fill="#ffffff" opacity="0.35"/>')
            body.append(iso_face_windows(rng, (x1, y), (0, 1), h, d,
                                         lambda: ("#ffd27e", rng.uniform(0.6, 1)) if rng.random() < 0.45 else ("#1f2560", 0.6),
                                         cols_step=0.22, size=(0.12, 0.2)))
        else:
            body.append(iso_face_windows(rng, (x, y1), (1, 0), h, w,
                                         lambda: ("#fff6e4", rng.uniform(0.5, 0.9))))
            body.append(iso_face_windows(rng, (x1, y), (0, 1), h, d,
                                         lambda: ("#ffd27e", rng.uniform(0.6, 1)) if rng.random() < 0.4 else ("#2b2163", 0.55)))
        # Sunlit edge.
        body.append(f'<path d="M{f(iso(x, y1, h)[0])} {f(iso(x, y1, h)[1])} L{f(iso(x, y1, 0)[0])} {f(iso(x, y1, 0)[1])}" '
                    f'stroke="#fff3df" stroke-width="2.5" opacity="0.8"/>')
        if h > 4:
            tip = iso(x + w / 2, y + d / 2, h + 1.0)
            foot_ = iso(x + w / 2, y + d / 2, h)
            body.append(f'<path d="M{f(foot_[0])} {f(foot_[1])} L{f(tip[0])} {f(tip[1])}" stroke="#d8d4ff" stroke-width="5" stroke-linecap="round"/>')
            body.append(circle(tip[0], tip[1], 12, "#ff5a5a", ' opacity="0.35" filter="url(#isocloud)"'))
            body.append(circle(tip[0], tip[1], 5, "#ff6b6b"))
        elif h > 2.5:
            tank = iso(x + w * 0.3, y + d * 0.35, h)
            body.append(rect(tank[0] - 11, tank[1] - 26, 22, 22, "#9a7fb8", ' rx="3"'))
            body.append(ellipse(tank[0], tank[1] - 26, 11, 5, "#d9c6f0"))

    # Clouds in front, so the island floats.
    body.append(cloud(250, 840, 1.05, 0.95))
    body.append(cloud(800, 860, 1.15, 0.95))
    body.append(birds([(700, 200, 1.2), (742, 226, 0.9), (664, 236, 0.75)], "#2b2056", 4.4))
    body.append(vignette(defs, "#0a0720", 0.35))
    return document(defs, body)


OPTIONS = {
    1: ("horizonte", "Horizonte", option_skyline),
    2: ("despertador", "Despertador", option_clock),
    3: ("ventana", "Ventana", option_window),
    4: ("isometrica", "Isométrica", option_isometric),
}


def preview(names):
    """The four options side by side, masked like on the home screen."""
    size, gap, pad = 280, 56, 48
    width = pad * 2 + 4 * size + 3 * gap
    height = pad + size + 92
    parts = [f'<rect width="{width}" height="{height}" fill="#f2f2f7"/>',
             f'<defs><filter id="lift" x="-0.2" y="-0.2" width="1.4" height="1.4">'
             f'<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#1c1c3c" flood-opacity="0.25"/></filter></defs>']
    for i, (number, file_name, title) in enumerate(names):
        x = pad + i * (size + gap)
        radius = size * 0.2237
        parts.append(f'<clipPath id="c{i}"><rect x="{x}" y="{pad}" width="{size}" height="{size}" rx="{f(radius)}"/></clipPath>')
        parts.append(f'<rect x="{x}" y="{pad}" width="{size}" height="{size}" rx="{f(radius)}" fill="#000" filter="url(#lift)"/>')
        parts.append(f'<image href="{file_name}" x="{x}" y="{pad}" width="{size}" height="{size}" clip-path="url(#c{i})"/>')
        parts.append(f'<text x="{x + size / 2}" y="{pad + size + 52}" text-anchor="middle" '
                     f'font-family="-apple-system, Helvetica Neue, Segoe UI, Arial, sans-serif" font-size="28" '
                     f'font-weight="600" fill="#1c1c1e">{number}. {title}</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}">{"".join(parts)}</svg>\n')
    return svg, width, height


# ---------------------------------------------------------------------------
# Rendering


def find_chrome():
    candidates = [os.environ.get("CHROME")]
    candidates += sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-*/headless_shell")))
    candidates += sorted(glob.glob("/opt/pw-browsers/chromium_headless_shell-*/chrome-*/headless_shell"))
    candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                   "/Applications/Chromium.app/Contents/MacOS/Chromium",
                   r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    candidates += [shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser", "chrome")]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def render(chrome, svg_path, png_path, width=W, height=W):
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        shot = os.path.join(tmp, "shot.png")
        # Taller than the image: some Chrome builds take the window's toolbar out of
        # the viewport. The image is cropped from the top-left corner.
        subprocess.run(
            [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--allow-file-access-from-files", "--force-device-scale-factor=1",
             f"--window-size={width},{height + 200}", f"--user-data-dir={tmp}", f"--screenshot={shot}",
             pathlib.Path(svg_path).resolve().as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        image = Image.open(shot).convert("RGB").crop((0, 0, width, height))
        image.save(png_path, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--use", type=int, choices=sorted(OPTIONS), help="render this option as the app icon")
    parser.add_argument("--out", default=DESIGN_DIR, help="folder for the SVG files and the preview")
    parser.add_argument("--svg-only", action="store_true", help="write the SVG files without rendering anything")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    names = []
    for number, (name, title, draw) in sorted(OPTIONS.items()):
        file_name = f"{number}-{name}.svg"
        with open(os.path.join(args.out, file_name), "w") as handle:
            handle.write(draw())
        names.append((number, file_name, title))
        print("wrote", os.path.relpath(os.path.join(args.out, file_name)))
    sheet, width, height = preview(names)
    with open(os.path.join(args.out, "preview.svg"), "w") as handle:
        handle.write(sheet)
    if args.svg_only:
        return

    chrome = find_chrome()
    if chrome is None:
        sys.exit("error: Chrome or Chromium not found; set CHROME=/path/to/chrome or pass --svg-only")
    render(chrome, os.path.join(args.out, "preview.svg"), os.path.join(args.out, "preview.png"), width, height)
    print("wrote", os.path.relpath(os.path.join(args.out, "preview.png")))
    if args.use:
        name = OPTIONS[args.use][0]
        render(chrome, os.path.join(args.out, f"{args.use}-{name}.svg"), APP_ICON)
        print("app icon:", os.path.relpath(APP_ICON))


if __name__ == "__main__":
    main()
