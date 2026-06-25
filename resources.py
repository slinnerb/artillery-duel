"""Loads bundled image/sound assets and plays sounds.

resource_path() resolves files both when running from source AND when frozen by
PyInstaller (which unpacks bundled data into sys._MEIPASS at runtime). Audio is
optional: if a machine has no sound device, the game still runs silently.
"""
import os
import sys

import pygame


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


_SPRITES = {}
_SOUNDS = {}
audio_ok = False

_SPRITE_NAMES = [
    "sky", "hills_far", "hills_near", "ground",
    "tank_blue", "tank_red", "barrel_blue", "barrel_red",
    "smoke", "fireball", "spark", "dirt", "flash",
]
_SOUND_VOL = {"fire": 0.5, "explosion": 0.75, "charge": 0.4, "hit": 0.55, "win": 0.65}


def load(master_volume=0.8):
    """Load every sprite and sound. Call after the display is created."""
    global audio_ok
    for name in _SPRITE_NAMES:
        surf = pygame.image.load(resource_path("assets", "sprites", name + ".png"))
        _SPRITES[name] = surf.convert_alpha()
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
