"""Loads bundled image/sound assets and plays sounds.

resource_path() resolves files both when running from source AND when frozen by
PyInstaller (which unpacks bundled data into sys._MEIPASS at runtime). Audio is
optional: if a machine has no sound device, the game still runs silently.
"""
import os
import random
import sys

import pygame


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


_SPRITES = {}
_SOUNDS = {}
_BACKGROUNDS = []          # keys of optional full-screen backdrops (drop-in art)
audio_ok = False

SCREEN_W, SCREEN_H = 1000, 600   # matches game.W / game.H (kept here to avoid a cycle)
_BG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

_SPRITE_NAMES = [
    "sky", "hills_far", "hills_near", "ground",
    "tank_blue", "tank_red", "barrel_blue", "barrel_red",
    "smoke", "fireball", "spark", "dirt", "flash",
]
_SOUND_VOL = {"fire": 0.5, "explosion": 0.75, "charge": 0.4, "hit": 0.55, "win": 0.65}


def _cover_scale(surf, tw, th):
    """Scale `surf` to completely cover a tw x th area, then centre-crop to it."""
    sw, sh = surf.get_size()
    scale = max(tw / sw, th / sh)
    scaled = pygame.transform.smoothscale(surf, (round(sw * scale), round(sh * scale)))
    out = pygame.Surface((tw, th)).convert()
    out.blit(scaled, ((tw - scaled.get_width()) // 2, (th - scaled.get_height()) // 2))
    return out


def _load_backgrounds():
    """Load any images dropped in assets/backgrounds/ as full-screen backdrops.

    This folder is optional: with nothing in it the game just uses its painted
    sky. Add an image and it starts showing up in some matches automatically.
    """
    _BACKGROUNDS.clear()
    folder = resource_path("assets", "backgrounds")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return                                   # no backgrounds folder — that's fine
    for fn in names:
        if not fn.lower().endswith(_BG_EXTS):
            continue
        try:
            surf = pygame.image.load(os.path.join(folder, fn)).convert()
        except pygame.error:
            continue                             # skip anything unreadable
        key = "bg:" + fn
        _SPRITES[key] = _cover_scale(surf, SCREEN_W, SCREEN_H)
        _BACKGROUNDS.append(key)


def backgrounds():
    """Keys of all loaded drop-in backdrops (empty if none were added)."""
    return list(_BACKGROUNDS)


def random_background(chance=0.35):
    """Pick a drop-in backdrop for a match, or None to use the default sky.

    Returns a key with probability `chance` when any backdrops exist; otherwise
    None. Callers decide once per match so the backdrop stays put across rounds.
    """
    if _BACKGROUNDS and random.random() < chance:
        return random.choice(_BACKGROUNDS)
    return None


def has(name):
    return name in _SPRITES


def load(master_volume=0.8):
    """Load every sprite and sound. Call after the display is created."""
    global audio_ok
    for name in _SPRITE_NAMES:
        surf = pygame.image.load(resource_path("assets", "sprites", name + ".png"))
        _SPRITES[name] = surf.convert_alpha()
    _load_backgrounds()
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        for name, vol in _SOUND_VOL.items():
            snd = pygame.mixer.Sound(resource_path("assets", "sounds", name + ".wav"))
            snd.set_volume(vol * master_volume)
            _SOUNDS[name] = snd
        audio_ok = True
    except pygame.error:
        audio_ok = False  # no audio device — run silently


def img(name):
    return _SPRITES[name]


def play(name):
    if audio_ok:
        snd = _SOUNDS.get(name)
        if snd:
            snd.play()
