"""Local 'juice' layer: particles, screen shake, and sound triggers.

This is purely cosmetic and runs on BOTH host and client. It works by diffing
successive snapshots (which already cross the network) to detect events:
  - a new crater  -> explosion (fireball, sparks, smoke, dirt) + shake + boom
  - a tank's charging flag going true->false -> it fired -> muzzle flash + bang
  - a tank's hp dropping -> hit sound
  - phase entering 'over' -> win sting
Because it only reads snapshot fields, it can never cause a desync.
"""
import math
import random

import pygame

import resources
from game import W, H, SPRITE_TURRET_DY, BARREL_TIP


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "grav", "life", "maxlife", "sprite", "s0", "s1", "spin", "ang", "fadepow")

    def __init__(self, x, y, vx, vy, grav, life, sprite, s0, s1, spin=0.0, fadepow=1.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.grav = grav
        self.life = self.maxlife = life
        self.sprite = sprite
        self.s0, self.s1 = s0, s1     # scale at spawn (f=1) and at death (f=0)
        self.spin = spin
        self.ang = 0.0
        self.fadepow = fadepow

    def update(self):
        self.vy += self.grav
        self.x += self.vx
        self.y += self.vy
        self.ang += self.spin
        self.life -= 1

    def draw(self, dest, ox=0, oy=0):
        f = self.life / self.maxlife
        scale = self.s1 + (self.s0 - self.s1) * f
        img = pygame.transform.rotozoom(resources.img(self.sprite), self.ang, max(0.05, scale))
        img.set_alpha(int(255 * max(0.0, f) ** self.fadepow))
        dest.blit(img, (self.x + ox - img.get_width() / 2, self.y + oy - img.get_height() / 2))


class FX:
    def __init__(self):
        self.particles = []
        self.shake = 0.0
        self.prev = None
        self.prev_craters = 0
        self._tick = 0

    # -- spawning -----------------------------------------------------------
    def spawn_explosion(self, x, y, r=40):
        s = max(0.6, min(2.2, r / 40.0))                     # scale with crater size
        self.particles.append(Particle(x, y, 0, 0, 0, 18, "fireball", 0.9 * s, 2.5 * s, fadepow=1.2))
        self.particles.append(Particle(x, y, 0, 0, 0, 9, "flash", 2.1 * s, 1.0 * s, fadepow=1.5))
        for _ in range(int(13 * s)):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(3.0, 8.0)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, 0.18,
                                           random.randint(16, 30), "spark", 1.1, 0.4))
        for _ in range(int(7 * s)):
            self.particles.append(Particle(x, y, random.uniform(-0.9, 0.9), random.uniform(-1.6, -0.5),
                                           0.0, random.randint(45, 80), "smoke", 0.6 * s, 1.9 * s,
                                           spin=random.uniform(-2, 2), fadepow=1.4))
        for _ in range(int(9 * s)):
            a = random.uniform(math.pi, 2 * math.pi)         # upward arc
            sp = random.uniform(2.2, 5.5)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, 0.35,
                                           random.randint(28, 52), "dirt", 1.0, 0.8,
                                           spin=random.uniform(-12, 12)))
        self.shake = min(16.0, self.shake + 9.0 * s)

    def spawn_muzzle(self, x, y, dx, dy):
        self.particles.append(Particle(x, y, 0, 0, 0, 6, "flash", 1.0, 0.4, fadepow=1.4))
        for _ in range(2):
            self.particles.append(Particle(x, y, dx * 0.6 + random.uniform(-0.3, 0.3),
                                           dy * 0.6 + random.uniform(-0.3, 0.3), -0.01,
                                           random.randint(18, 28), "smoke", 0.3, 0.9, fadepow=1.3))

    def spawn_trail(self, x, y):
        self.particles.append(Particle(x, y, 0, 0.05, 0, 14, "smoke", 0.25, 0.6, fadepow=1.2))

    # -- event detection (diff snapshots) -----------------------------------
    def observe(self, snap, local_index):
        if self.prev is None:
            # synthesise a quiet baseline so a rising edge on the very first
            # frame (e.g. the player is already holding fire) still fires
            self.prev = {
                "tanks": [{"charging": False, "hp": t["hp"]} for t in snap["tanks"]],
                "phase": "playing",
            }
        prev = self.prev
        craters = snap.get("craters", [])
        if len(craters) > self.prev_craters:
            for c in craters[self.prev_craters:]:
                self.spawn_explosion(c["x"], c["y"], c.get("r", 40))
                resources.play("explosion")
        for i, t in enumerate(snap["tanks"]):
            pt = prev["tanks"][i]
            if pt["charging"] and not t["charging"]:              # this tank just fired
                a = math.radians(t["angle"])
                dx, dy = t["facing"] * math.cos(a), -math.sin(a)
                tipx = t["x"] + dx * BARREL_TIP
                tipy = (t["y"] - SPRITE_TURRET_DY) + dy * BARREL_TIP
                self.spawn_muzzle(tipx, tipy, dx, dy)
                resources.play("fire")
            if i == local_index and not pt["charging"] and t["charging"]:
                resources.play("charge")
            if t["hp"] < pt["hp"] - 0.5:
                resources.play("hit")
        if prev["phase"] != "over" and snap["phase"] == "over":
            resources.play("win")

        if self._tick % 2 == 0:                                   # shell smoke trails
            for p in snap.get("projectiles", []):
                self.spawn_trail(p["x"], p["y"])
        self._tick += 1
        self.prev = snap
        self.prev_craters = len(craters)

    # -- per-frame update + draw -------------------------------------------
    def update(self):
        self.particles = [p for p in self.particles if (p.update() or p.life > 0)]
        self.shake *= 0.85
        if self.shake < 0.3:
            self.shake = 0.0

    def shake_offset(self):
        if self.shake <= 0:
            return (0, 0)
        return (random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake))

    def draw(self, dest, ox=0, oy=0):
        for p in self.particles:
            p.draw(dest, ox, oy)
