"""Generates the game's art as real .png files in assets/sprites/.

Run once (or whenever you want to restyle):  py tools/make_sprites.py
Everything is drawn with pygame + numpy and saved as PNG -- no copyrighted art.
The files are committed and bundled into the .exe. To use nicer artwork later,
just replace the matching .png in assets/sprites/.
"""
import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

pygame.init()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sprites")
os.makedirs(OUT, exist_ok=True)


def save(surf, name):
    pygame.image.save(surf, os.path.join(OUT, name))
    print("wrote", name, surf.get_size())


def lerp_stops(stops, p):
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= p <= p1:
            f = (p - p0) / (p1 - p0) if p1 > p0 else 0
            return [c0[k] + (c1[k] - c0[k]) * f for k in range(3)]
    return list(stops[-1][1])


def radial(size, inner, outer, a_center=255, a_edge=0, color_power=1.0, alpha_power=1.6):
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = (size - 1) / 2.0
    xx, yy = np.mgrid[0:size, 0:size]
    r = np.clip(np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (size / 2.0), 0.0, 1.0)
    tc = r ** color_power
    rgb = np.empty((size, size, 3))
    for k in range(3):
        rgb[..., k] = inner[k] * (1 - tc) + outer[k] * tc
    alpha = np.clip(a_center * (1 - r) ** alpha_power + a_edge * r, 0, 255)
    p3 = pygame.surfarray.pixels3d(surf)
    p3[...] = rgb.astype(np.uint8)
    del p3
    pa = pygame.surfarray.pixels_alpha(surf)
    pa[...] = alpha.astype(np.uint8)
    del pa
    return surf


def make_sky(w=1000, h=600):
    stops = [(0.0, (36, 58, 114)), (0.5, (96, 84, 140)), (0.78, (170, 120, 130)), (1.0, (236, 150, 92))]
    cols = np.array([lerp_stops(stops, p) for p in np.linspace(0, 1, h)])
    arr = np.repeat(cols[None, :, :], w, axis=0)
    save(pygame.surfarray.make_surface(arr.astype(np.uint8)), "sky.png")


def make_hills(name, w, h, color, base_y, comps):
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    xx = np.arange(w)
    crest = np.full(w, float(base_y))
    for amp, freq, phase in comps:
        crest -= amp * np.sin(2 * np.pi * freq * xx / w + phase)
    yy = np.arange(h)
    mask = yy[None, :] >= crest[:, None]
    rgb = np.zeros((w, h, 3))
    for k in range(3):
        rgb[..., k] = color[k]
    p3 = pygame.surfarray.pixels3d(surf)
    p3[...] = rgb.astype(np.uint8)
    del p3
    pa = pygame.surfarray.pixels_alpha(surf)
    pa[...] = (mask * 255).astype(np.uint8)
    del pa
    save(surf, name)


def make_ground(w=1000, h=600):
    base = np.array([107, 79, 58], float)
    rng = np.random.default_rng(11)
    arr = np.empty((w, h, 3))
    noise = rng.uniform(-12, 12, (w, h))
    depth = (np.linspace(0, 1, h) * 26)[None, :]
    for k in range(3):
        arr[..., k] = base[k] + noise - depth
    arr = np.clip(arr, 0, 255)
    surf = pygame.surfarray.make_surface(arr.astype(np.uint8))
    for _ in range(700):                       # scattered stones
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        shade = int(np.clip(base.mean() + rng.uniform(-34, 30), 20, 220))
        pygame.draw.circle(surf, (shade, max(0, shade - 12), max(0, shade - 22)), (x, y), int(rng.integers(1, 3)))
    save(surf, "ground.png")


def lighten(c, f=0.35):
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)


def make_tank(name, color):
    w, h = 64, 40
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    hi = lighten(color, 0.4)
    pygame.draw.rect(s, (38, 38, 44), (8, 26, 48, 11), border_radius=5)      # tread
    for wx in range(14, 53, 8):
        pygame.draw.circle(s, (64, 64, 72), (wx, 31), 3)                      # wheels
    pygame.draw.rect(s, color, (12, 15, 40, 13), border_radius=4)            # hull
    pygame.draw.polygon(s, hi, [(15, 15), (49, 15), (45, 10), (19, 10)])     # sloped lit top
    pygame.draw.circle(s, color, (32, 13), 8)                                # turret
    pygame.draw.circle(s, hi, (30, 11), 4)                                   # turret highlight
    save(s, name)


def make_barrel(name, color):
    w, h = 32, 10
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, (44, 44, 50), (2, 3, 25, 4), border_radius=2)
    pygame.draw.rect(s, (78, 78, 88), (2, 3, 25, 2))                          # top highlight
    pygame.draw.circle(s, (30, 30, 36), (28, 5), 4)                          # muzzle
    save(s, name)


def make_dirt():
    s = pygame.Surface((14, 14), pygame.SRCALPHA)
    for dx, dy, r, c in [(6, 8, 5, (94, 67, 41)), (9, 6, 3, (112, 82, 54)), (5, 9, 3, (78, 55, 34))]:
        pygame.draw.circle(s, c, (dx, dy), r)
    save(s, "dirt.png")


def make_flash():
    s = radial(56, (255, 250, 215), (255, 170, 60), a_center=255, a_edge=0, alpha_power=2.4)
    c = 28
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        pygame.draw.line(s, (255, 236, 175), (c, c), (c + math.cos(rad) * 26, c + math.sin(rad) * 26), 2)
    save(s, "flash.png")


if __name__ == "__main__":
    make_sky()
    make_hills("hills_far.png", 1000, 360, (70, 86, 138), 150,
               [(34, 1.1, 0.4), (18, 2.3, 1.7), (10, 0.6, 3.0)])
    make_hills("hills_near.png", 1000, 380, (58, 78, 70), 150,
               [(46, 0.9, 2.1), (22, 1.7, 0.3), (12, 3.1, 1.2)])
    make_ground()
    make_tank("tank_blue.png", (90, 160, 245))
    make_tank("tank_red.png", (236, 96, 86))
    make_barrel("barrel_blue.png", (90, 160, 245))
    make_barrel("barrel_red.png", (236, 96, 86))
    save(radial(64, (160, 160, 168), (88, 88, 98), a_center=200, alpha_power=2.2), "smoke.png")
    save(radial(64, (255, 246, 205), (255, 92, 30), a_center=255, alpha_power=1.7), "fireball.png")
    save(radial(16, (255, 246, 205), (255, 170, 70), a_center=255, alpha_power=1.4), "spark.png")
    make_dirt()
    make_flash()
    print("done.")
