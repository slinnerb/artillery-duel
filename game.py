"""Core game: world simulation + rendering for a real-time artillery duel.

The host runs a single authoritative World and sends snapshots to the client.
Both sides use render() to draw a snapshot, so there is exactly one draw path.
Terrain is generated deterministically from a seed, so the host and client
build an identical battlefield without sending it over the wire.
"""

import math
import random

import pygame
from pygame.locals import *  # noqa: F401,F403 (K_*, QUIT, etc.)

import resources

# ---------------------------------------------------------------------------
# Tunables — tweak these to change game feel.
# ---------------------------------------------------------------------------
W, H = 1000, 600
FPS = 60

SKY = (28, 32, 46)
GROUND_COLOR = (84, 104, 72)
GROUND_EDGE = (120, 150, 100)

GRAVITY = 0.35              # px / frame^2
POWER_MIN = 6.0            # shot speed for a quick tap
POWER_MAX = 18.0           # shot speed at full charge
CHARGE_PER_FRAME = (POWER_MAX - POWER_MIN) / 72.0  # ~1.2s to full charge
AIM_DEG = 1.3              # barrel degrees per frame
MOVE_PX = 1.1             # tank pixels per frame
RELOAD_FRAMES = 55        # cooldown after firing (~0.9s)

WIND_MAX = 0.05            # max horizontal accel applied to shells
WIND_MIN_FRAMES = 180     # how long a wind value lasts (min)
WIND_MAX_FRAMES = 360     # how long a wind value lasts (max)

BLAST_RADIUS = 60
CRATER_RADIUS = 40         # how big a bite each shell takes out of the ground
MAX_DAMAGE = 32
TANK_HP = 100
BODY_H = 16
BARREL_LEN = 26
TANK_RADIUS = 22

# sprite anchoring (must match the generated PNGs in assets/sprites)
SPRITE_TURRET_DY = 27      # turret-centre height above tank.y in the tank png
BARREL_TIP = 30            # muzzle distance from the turret pivot
BARREL_PIVOT = (2, 5)      # breech point inside barrel_*.png (rotation origin)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def read_input(keys):
    """Turn the pygame pressed-key state into a small JSON-friendly dict."""
    return {
        "left": bool(keys[K_LEFT] or keys[K_a]),
        "right": bool(keys[K_RIGHT] or keys[K_d]),
        "up": bool(keys[K_UP] or keys[K_w]),
        "down": bool(keys[K_DOWN] or keys[K_s]),
        "fire": bool(keys[K_SPACE]),
    }


NEUTRAL_INPUT = {"left": False, "right": False, "up": False, "down": False, "fire": False}


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------
class Terrain:
    """A static hill silhouette built deterministically from a seed."""

    def __init__(self, seed, width=W, height=H):
        self.width = width
        self.height = height
        rng = random.Random(seed)
        base = height * 0.66
        comps = [
            (rng.uniform(14, 52), rng.uniform(0.5, 2.6), rng.uniform(0, 2 * math.pi))
            for _ in range(4)
        ]
        self.ground = []
        for x in range(width):
            y = base
            for amp, freq, phase in comps:
                y -= amp * math.sin(2 * math.pi * freq * x / width + phase)
            y = clamp(y, height * 0.38, height - 24)
            self.ground.append(y)

    def height_at(self, x):
        xi = int(clamp(x, 0, self.width - 1))
        return self.ground[xi]

    def apply_crater(self, cx, cy, r):
        """Carve a circular bite out of the ground (lowers the surface)."""
        left = max(0, int(cx - r))
        right = min(self.width - 1, int(cx + r))
        for x in range(left, right + 1):
            inside = r * r - (x - cx) ** 2
            if inside <= 0:
                continue
            bottom = cy + math.sqrt(inside)   # the lower arc of the removed circle
            if bottom > self.ground[x]:        # only ever removes ground, never adds
                self.ground[x] = min(self.height - 2, bottom)

    def draw(self, screen):
        pts = [(0, self.height)]
        pts += [(x, self.ground[x]) for x in range(0, self.width, 2)]
        pts += [(self.width, self.ground[-1]), (self.width, self.height)]
        pygame.draw.polygon(screen, GROUND_COLOR, pts)
        pygame.draw.lines(screen, GROUND_EDGE, False,
                          [(x, self.ground[x]) for x in range(0, self.width, 2)], 2)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Tank:
    def __init__(self, x, facing, color, name):
        self.x = float(x)
        self.facing = facing          # +1 = aims right, -1 = aims left
        self.color = color
        self.name = name
        self.y = 0.0
        self.angle = 50.0             # barrel angle from horizontal, degrees
        self.hp = float(TANK_HP)
        self.charging = False
        self.charge = 0.0
        self.reload = 0


class Projectile:
    def __init__(self, x, y, vx, vy, owner):
        self.x, self.y, self.vx, self.vy, self.owner = x, y, vx, vy, owner

    def update(self, wind):
        self.vx += wind
        self.vy += GRAVITY
        self.x += self.vx
        self.y += self.vy


# ---------------------------------------------------------------------------
# World (host-authoritative simulation)
# ---------------------------------------------------------------------------
class World:
    def __init__(self, seed):
        self.seed = seed
        self._rng = random.Random((seed ^ 0x9E3779B9) & 0xFFFFFFFF)
        self.terrain = Terrain(seed, W, H)

        blue = Tank(110, +1, (90, 160, 245), "Blue")
        red = Tank(W - 110, -1, (245, 110, 95), "Red")
        for t in (blue, red):
            t.y = self.terrain.height_at(t.x)
        self.tanks = [blue, red]

        self.projectiles = []
        self.explosions = []          # [{x, y, age}] — transient blast flashes
        self.craters = []             # [{x, y, r}] — permanent terrain damage (synced)
        self.wind = self._rng.uniform(-WIND_MAX, WIND_MAX)
        self.wind_timer = self._rng.randint(WIND_MIN_FRAMES, WIND_MAX_FRAMES)
        self.phase = "playing"        # or "over"
        self.winner = None

    # -- one simulation tick ------------------------------------------------
    def step(self, inputs):
        if self.phase != "playing":
            # keep explosions fading even after the match ends
            self._age_explosions()
            return

        for i, tank in enumerate(self.tanks):
            inp = inputs[i] or NEUTRAL_INPUT

            if inp["up"]:
                tank.angle = min(89.0, tank.angle + AIM_DEG)
            if inp["down"]:
                tank.angle = max(8.0, tank.angle - AIM_DEG)

            dx = (1 if inp["right"] else 0) - (1 if inp["left"] else 0)
            if dx:
                tank.x = clamp(tank.x + dx * MOVE_PX, 40, W - 40)
                tank.y = self.terrain.height_at(tank.x)

            if tank.reload > 0:
                tank.reload -= 1

            if tank.reload <= 0 and inp["fire"]:
                tank.charging = True
                tank.charge = min(POWER_MAX, tank.charge + CHARGE_PER_FRAME)
                if tank.charge >= POWER_MAX:
                    self._launch(i)
            elif tank.charging and not inp["fire"]:
                self._launch(i)

        for p in self.projectiles:
            p.update(self.wind)
        self._handle_collisions()
        for tank in self.tanks:        # tanks settle into freshly-dug craters
            tank.y = self.terrain.height_at(tank.x)
        self._age_explosions()

        self.wind_timer -= 1
        if self.wind_timer <= 0:
            self.wind = self._rng.uniform(-WIND_MAX, WIND_MAX)
            self.wind_timer = self._rng.randint(WIND_MIN_FRAMES, WIND_MAX_FRAMES)

    def _launch(self, i):
        tank = self.tanks[i]
        power = max(POWER_MIN, tank.charge)
        rad = math.radians(tank.angle)
        cos, sin = math.cos(rad), math.sin(rad)
        turret_y = tank.y - BODY_H
        tip_x = tank.x + tank.facing * cos * (BARREL_LEN + 6)
        tip_y = turret_y - sin * (BARREL_LEN + 6)
        vx = tank.facing * cos * power
        vy = -sin * power
        self.projectiles.append(Projectile(tip_x, tip_y, vx, vy, owner=i))
        tank.charging = False
        tank.charge = 0.0
        tank.reload = RELOAD_FRAMES

    def _handle_collisions(self):
        remaining = []
        for p in self.projectiles:
            if p.x < -60 or p.x > W + 60 or p.y > H + 300:
                continue  # left the battlefield
            exploded = False
            if p.y >= self.terrain.height_at(p.x):
                self._explode(p.x, self.terrain.height_at(p.x))
                exploded = True
            else:
                for t in self.tanks:
                    cy = t.y - BODY_H * 0.5
                    if (p.x - t.x) ** 2 + (p.y - cy) ** 2 <= TANK_RADIUS ** 2:
                        self._explode(p.x, p.y)
                        exploded = True
                        break
            if not exploded:
                remaining.append(p)
        self.projectiles = remaining

    def _explode(self, x, y):
        for t in self.tanks:
            d = math.hypot(x - t.x, y - (t.y - BODY_H * 0.5))
            if d < BLAST_RADIUS:
                t.hp = max(0.0, t.hp - MAX_DAMAGE * (1 - d / BLAST_RADIUS))
        self.explosions.append({"x": x, "y": y, "age": 0})

        # carve the terrain and log the crater so the client reproduces it exactly
        self.terrain.apply_crater(x, y, CRATER_RADIUS)
        # log the EXACT values used so the client carves an identical crater
        # (JSON round-trips Python floats losslessly)
        self.craters.append({"x": x, "y": y, "r": CRATER_RADIUS})

        alive = [i for i, t in enumerate(self.tanks) if t.hp > 0]
        if len(alive) <= 1:
            self.phase = "over"
            self.winner = alive[0] if alive else None

    def _age_explosions(self):
        for e in self.explosions:
            e["age"] += 1
        self.explosions = [e for e in self.explosions if e["age"] <= 14]

    # -- serialise for the network / renderer -------------------------------
    def snapshot(self):
        return {
            "tanks": [
                {
                    "x": t.x, "y": t.y, "angle": t.angle, "facing": t.facing,
                    "hp": t.hp, "charging": t.charging, "charge": t.charge,
                    "name": t.name, "color": list(t.color),
                }
                for t in self.tanks
            ],
            "projectiles": [{"x": p.x, "y": p.y} for p in self.projectiles],
            "explosions": [dict(e) for e in self.explosions],
            "craters": [dict(c) for c in self.craters],
            "wind": self.wind,
            "phase": self.phase,
            "winner": self.winner,
        }


# ---------------------------------------------------------------------------
# Rendering (works on any snapshot dict, host or client)
# ---------------------------------------------------------------------------
_scene = _textured = _mask = None


def _surfaces():
    global _scene, _textured, _mask
    if _scene is None:
        _scene = pygame.Surface((W, H)).convert()
        _textured = pygame.Surface((W, H), pygame.SRCALPHA).convert_alpha()
        _mask = pygame.Surface((W, H), pygame.SRCALPHA).convert_alpha()
    return _scene, _textured, _mask


def _blit_pivot(dest, image, pos, origin, angle):
    """Blit image rotated by angle so that image-point `origin` lands on `pos`."""
    rect = image.get_rect(topleft=(pos[0] - origin[0], pos[1] - origin[1]))
    offset = pygame.math.Vector2(pos) - rect.center
    offset.rotate_ip(-angle)
    rotated = pygame.transform.rotate(image, angle)
    dest.blit(rotated, rotated.get_rect(center=(pos[0] - offset.x, pos[1] - offset.y)))


def _draw_terrain(scene, terrain):
    _, textured, mask = _surfaces()
    pts = [(0, H)] + [(x, terrain.ground[x]) for x in range(0, W, 2)] + [(W, terrain.ground[-1]), (W, H)]
    mask.fill((0, 0, 0, 0))
    pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
    textured.blit(resources.img("ground"), (0, 0))
    textured.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    scene.blit(textured, (0, 0))
    rim = [(x, terrain.ground[x]) for x in range(0, W, 2)]
    pygame.draw.lines(scene, (126, 172, 98), False, rim, 3)


def _draw_tank(scene, t, index):
    x, y = t["x"], t["y"]
    color = "blue" if index == 0 else "red"
    angle = t["angle"] if t["facing"] > 0 else 180 - t["angle"]
    _blit_pivot(scene, resources.img("barrel_" + color), (x, y - SPRITE_TURRET_DY), BARREL_PIVOT, angle)
    body = resources.img("tank_" + color)
    scene.blit(body, (x - body.get_width() / 2, y - body.get_height()))


def _draw_hp(screen, font, t, x, y, right=False):
    w, h = 200, 18
    if right:
        x -= w
    pygame.draw.rect(screen, (40, 40, 50), pygame.Rect(x, y + 22, w, h), border_radius=5)
    frac = max(0.0, t["hp"] / TANK_HP)
    pygame.draw.rect(screen, tuple(t["color"]), pygame.Rect(x, y + 22, int(w * frac), h), border_radius=5)
    pygame.draw.rect(screen, (205, 205, 215), pygame.Rect(x, y + 22, w, h), 2, border_radius=5)
    label = font.render(f"{t['name']}  {int(t['hp'])}", True, tuple(t["color"]))
    screen.blit(label, (x, y))


def _draw_wind(screen, small, wind):
    cx, cy = W // 2, 32
    lbl = small.render("WIND", True, (200, 200, 215))
    screen.blit(lbl, (cx - lbl.get_width() // 2, cy - 24))
    length = int(wind / WIND_MAX * 64)
    pygame.draw.line(screen, (225, 225, 240), (cx, cy), (cx + length, cy), 3)
    if abs(length) > 4:
        d = 1 if length > 0 else -1
        ex = cx + length
        pygame.draw.line(screen, (225, 225, 240), (ex, cy), (ex - 7 * d, cy - 5), 3)
        pygame.draw.line(screen, (225, 225, 240), (ex, cy), (ex - 7 * d, cy + 5), 3)


def render(screen, fonts, terrain, snap, local_index, version, fx=None):
    small, font, big = fonts
    scene, _, _ = _surfaces()

    scene.blit(resources.img("sky"), (0, 0))
    scene.blit(resources.img("hills_far"), (0, 80))
    scene.blit(resources.img("hills_near"), (0, 135))
    _draw_terrain(scene, terrain)

    for i, t in enumerate(snap["tanks"]):
        _draw_tank(scene, t, i)

    for p in snap["projectiles"]:
        pygame.draw.circle(scene, (24, 22, 26), (int(p["x"]), int(p["y"])), 5)
        pygame.draw.circle(scene, (255, 222, 120), (int(p["x"]), int(p["y"])), 3)

    if fx is not None:
        fx.draw(scene)

    dx, dy = fx.shake_offset() if fx is not None else (0, 0)
    screen.fill((8, 9, 14))
    screen.blit(scene, (int(dx), int(dy)))

    _draw_hp(screen, font, snap["tanks"][0], 16, 14)
    _draw_hp(screen, font, snap["tanks"][1], W - 16, 14, right=True)
    _draw_wind(screen, small, snap["wind"])

    if 0 <= local_index < len(snap["tanks"]):
        me = snap["tanks"][local_index]
        if me["charging"]:
            frac = clamp((me["charge"] - POWER_MIN) / (POWER_MAX - POWER_MIN), 0, 1)
            bar = pygame.Rect(W // 2 - 120, H - 44, 240, 18)
            pygame.draw.rect(screen, (40, 50, 70), bar, border_radius=6)
            col = (120, 200, 90) if frac < 0.7 else (230, 160, 60)
            pygame.draw.rect(screen, col, pygame.Rect(bar.x, bar.y, int(bar.width * frac), bar.height), border_radius=6)
            pygame.draw.rect(screen, (150, 170, 210), bar, 2, border_radius=6)
            lbl = small.render("POWER", True, (220, 220, 235))
            screen.blit(lbl, (W // 2 - lbl.get_width() // 2, H - 64))

    hint = small.render(
        "Move: A/D or arrows   Aim: W/S or arrows   Hold SPACE to charge, release to fire   ESC: menu",
        True, (170, 180, 200))
    screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 22))

    ver = small.render(f"v{version}", True, (130, 140, 160))
    screen.blit(ver, (12, H - 22))

    if snap["phase"] == "over":
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((10, 12, 20, 185))
        screen.blit(overlay, (0, 0))
        w = snap["winner"]
        msg = "DRAW!" if w is None else f"{snap['tanks'][w]['name'].upper()} WINS!"
        t = big.render(msg, True, (255, 235, 160))
        screen.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 60))
        s = font.render("Press ENTER for menu", True, (220, 220, 235))
        screen.blit(s, (W // 2 - s.get_width() // 2, H // 2 + 12))
