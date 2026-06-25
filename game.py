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
W, H = 1000, 600           # the on-screen viewport
WORLD_W = 2200             # the playfield is wider than the screen; camera scrolls
FPS = 60

SKY = (28, 32, 46)
GROUND_COLOR = (84, 104, 72)
GROUND_EDGE = (120, 150, 100)

GRAVITY = 0.35              # px / frame^2
POWER_MIN = 6.0            # shot speed for a quick tap
POWER_MAX = 18.0           # shot speed at full charge
CHARGE_PER_FRAME = (POWER_MAX - POWER_MIN) / 72.0  # ~1.2s to full charge
AIM_DEG = 1.3              # barrel degrees per frame
MOVE_PX = 2.0             # tank pixels per frame (bigger world -> faster drive)
RELOAD_FRAMES = 55        # cooldown after firing (~0.9s)

# Lava: a molten sea at the bottom of a wide world. Touch it and you die.
LAVA_BAND = 46             # how tall the lava strip is, in pixels
LAVA_Y = H - LAVA_BAND     # world y of the lava surface
LAVA_DEATH_Y = LAVA_Y - 8  # a tank at/below this y is in the lava

# Ammo: shells are limited; you reload by typing sentences (see ReloadTyper).
START_AMMO = 5             # shells each tank begins a round with
AMMO_MAX = 12              # most shells you can stockpile

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

# Selectable weapons (number keys 1-4). 'kind': normal / cluster / bounce.
WEAPONS = [
    {"name": "Shell",    "blast": 60, "crater": 40, "dmg": 32, "reload": 55,  "speed": 1.00, "kind": "normal",  "bounces": 0},
    {"name": "Big Bomb", "blast": 94, "crater": 64, "dmg": 52, "reload": 100, "speed": 0.95, "kind": "normal",  "bounces": 0},
    {"name": "Cluster",  "blast": 44, "crater": 28, "dmg": 20, "reload": 85,  "speed": 1.00, "kind": "cluster", "bounces": 0},
    {"name": "Bouncer",  "blast": 58, "crater": 38, "dmg": 28, "reload": 70,  "speed": 1.05, "kind": "bounce",  "bounces": 2},
]
ROUNDS_TO_WIN = 3          # best of 5


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


NEUTRAL_INPUT = {"left": False, "right": False, "up": False, "down": False, "fire": False, "weapon": 0}


def weapon_from_keys(keys, current):
    """Number keys 1-4 pick a weapon; otherwise keep the current one."""
    for key, idx in ((K_1, 0), (K_2, 1), (K_3, 2), (K_4, 3)):
        if keys[key]:
            return idx
    return current


# ---------------------------------------------------------------------------
# Typing-to-reload: type sentences to earn shells, in the middle of a fight.
# ---------------------------------------------------------------------------
SENTENCES = [
    "the quick brown fox", "load the cannon now", "aim for the hills",
    "fire when ready", "wind from the east", "incoming round",
    "steady your hands", "type fast to win", "another shell loaded",
    "watch the trajectory", "left a little more", "boom goes the tank",
    "keep on firing", "practice makes perfect", "the enemy is close",
    "reload and repeat", "high arc shot", "low and fast", "mind the wind",
    "direct hit", "almost got them", "hold the line", "one more round",
    "victory is near", "stay on target", "quick fingers win",
    "blast the bunker", "over the ridge", "adjust your aim", "perfect shot",
    "the gun is hot", "shells away", "raining fire", "no time to waste",
    "type it clean", "speed and accuracy", "lock and load", "down they go",
    "final blow", "well aimed shot", "keep calm and type", "beat the clock",
    "rapid fire mode", "earn your ammo", "words become shells",
    "clear and concise", "tap the keys", "ready aim type", "long range strike",
]


class ReloadTyper:
    """Local, per-player typing state used to refill ammo during a fight.

    Each completed sentence bumps `typed` (a monotonic counter). The match loop
    feeds `typed` into the player's input dict; the authoritative World turns the
    increase into +1 shell. That keeps reloads in perfect sync over the network
    without sending any new message types.
    """

    def __init__(self):
        self.active = False
        self.typed = 0                       # sentences finished this match
        self.pos = 0
        self.target = random.choice(SENTENCES)

    def open(self):
        if not self.active:
            self.active = True
            self.pos = 0
            self.target = random.choice(SENTENCES)

    def toggle(self, can_close):
        """TAB pressed. Closes only if allowed (you must have a shell to leave)."""
        if self.active:
            if can_close:
                self.active = False
        else:
            self.open()

    def handle_key(self, e):
        """Feed a KEYDOWN to the sentence. Returns True if a sentence completed."""
        if e.key == K_BACKSPACE:
            self.pos = max(0, self.pos - 1)
            return False
        ch = e.unicode
        if ch and len(ch) == 1 and ch.isprintable():
            if self.pos < len(self.target) and ch == self.target[self.pos]:
                self.pos += 1
                if self.pos >= len(self.target):
                    self.typed += 1
                    self.target = random.choice(SENTENCES)
                    self.pos = 0
                    return True
        return False


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------
class Terrain:
    """A static hill silhouette built deterministically from a seed."""

    def __init__(self, seed, width=WORLD_W, height=H):
        self.width = width
        self.height = height
        # A world wider than the screen gets a lava sea + chasms; a screen-sized
        # world (Typing Duel) keeps the classic solid-ground arena.
        self.lava_y = LAVA_Y if width > W else None
        floor = (LAVA_Y - 70) if self.lava_y else (height - 24)
        rng = random.Random(seed)
        base = height * 0.60
        comps = [
            (rng.uniform(14, 46), rng.uniform(0.5, 2.6), rng.uniform(0, 2 * math.pi))
            for _ in range(4)
        ]
        self.ground = []
        for x in range(width):
            y = base
            for amp, freq, phase in comps:
                y -= amp * math.sin(2 * math.pi * freq * x / width + phase)
            y = clamp(y, height * 0.34, floor)
            self.ground.append(y)
        if self.lava_y:
            self._carve_chasms(rng)

    def _carve_chasms(self, rng):
        """Cut a single central chasm down to the lava — the no-man's-land both
        players drive up to and fire across. One gap (not several) guarantees the
        two tanks can always reach firing range at its edges."""
        cx = rng.randint(int(self.width * 0.44), int(self.width * 0.56))
        half = rng.randint(70, 115)
        for x in range(max(0, cx - half), min(self.width, cx + half)):
            self.ground[x] = max(self.ground[x], self.lava_y)

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
        self.weapon = 0              # index into WEAPONS
        self.ammo = START_AMMO       # shells in the magazine (reload by typing)


class Projectile:
    def __init__(self, x, y, vx, vy, owner, kind="normal",
                 blast=BLAST_RADIUS, crater=CRATER_RADIUS, dmg=MAX_DAMAGE, bounces=0):
        self.x, self.y, self.vx, self.vy, self.owner = x, y, vx, vy, owner
        self.kind = kind
        self.blast, self.crater, self.dmg = blast, crater, dmg
        self.bounces = bounces
        self.split = False           # cluster: has it burst yet?

    def update(self, wind):
        self.vx += wind
        self.vy += GRAVITY
        self.x += self.vx
        self.y += self.vy


# ---------------------------------------------------------------------------
# World (host-authoritative simulation)
# ---------------------------------------------------------------------------
class World:
    def __init__(self, seed, world_w=WORLD_W, ammo=None, typed=(0, 0)):
        self.seed = seed
        self.world_w = world_w
        self._rng = random.Random((seed ^ 0x9E3779B9) & 0xFFFFFFFF)
        self.terrain = Terrain(seed, world_w, H)

        blue = Tank(140, +1, (90, 160, 245), "Blue")
        red = Tank(world_w - 140, -1, (245, 110, 95), "Red")
        if ammo is None:
            ammo = (START_AMMO, START_AMMO)
        for t, a in zip((blue, red), ammo):
            t.y = self.terrain.height_at(t.x)
            t.ammo = a
        self.tanks = [blue, red]
        self._last_typed = list(typed)   # per-tank reload counter already credited

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
            # the remote peer's input is untrusted — clamp the weapon index so a
            # bad/hostile value can never crash the authoritative host
            w = inp.get("weapon", tank.weapon)
            tank.weapon = w if isinstance(w, int) and 0 <= w < len(WEAPONS) else tank.weapon

            # Reload-by-typing: a higher 'typed' counter means the player finished
            # more sentences; turn each new one into a shell (idempotent, so lost
            # frames never miscount).
            typed = inp.get("typed")
            if isinstance(typed, int) and typed > self._last_typed[i]:
                tank.ammo = min(AMMO_MAX, tank.ammo + (typed - self._last_typed[i]))
                self._last_typed[i] = typed

            if inp["up"]:
                tank.angle = min(89.0, tank.angle + AIM_DEG)
            if inp["down"]:
                tank.angle = max(8.0, tank.angle - AIM_DEG)

            dx = (1 if inp["right"] else 0) - (1 if inp["left"] else 0)
            if dx:
                tank.x = clamp(tank.x + dx * MOVE_PX, 40, self.world_w - 40)
                tank.y = self.terrain.height_at(tank.x)

            if tank.reload > 0:
                tank.reload -= 1

            can_fire = tank.weapon == 0 or tank.ammo > 0   # basic Shell is unlimited
            if tank.reload <= 0 and inp["fire"] and can_fire:
                tank.charging = True
                tank.charge = min(POWER_MAX, tank.charge + CHARGE_PER_FRAME)
                if tank.charge >= POWER_MAX:
                    self._launch(i)
            elif tank.charging and not inp["fire"]:
                self._launch(i)

        for p in self.projectiles:
            p.update(self.wind)
        self._split_clusters()
        self._handle_collisions()
        for tank in self.tanks:        # tanks settle into freshly-dug craters
            tank.y = self.terrain.height_at(tank.x)
        self._check_lava()
        self._age_explosions()

        self.wind_timer -= 1
        if self.wind_timer <= 0:
            self.wind = self._rng.uniform(-WIND_MAX, WIND_MAX)
            self.wind_timer = self._rng.randint(WIND_MIN_FRAMES, WIND_MAX_FRAMES)

    def _launch(self, i):
        tank = self.tanks[i]
        needs_ammo = tank.weapon != 0          # the basic Shell is unlimited
        if needs_ammo and tank.ammo <= 0:      # out of special shells — can't fire
            tank.charging = False
            tank.charge = 0.0
            return
        wep = WEAPONS[tank.weapon]
        power = max(POWER_MIN, tank.charge) * wep["speed"]
        rad = math.radians(tank.angle)
        cos, sin = math.cos(rad), math.sin(rad)
        turret_y = tank.y - BODY_H
        tip_x = tank.x + tank.facing * cos * (BARREL_LEN + 6)
        tip_y = turret_y - sin * (BARREL_LEN + 6)
        self.projectiles.append(Projectile(
            tip_x, tip_y, tank.facing * cos * power, -sin * power, owner=i,
            kind=wep["kind"], blast=wep["blast"], crater=wep["crater"],
            dmg=wep["dmg"], bounces=wep["bounces"]))
        tank.charging = False
        tank.charge = 0.0
        tank.reload = wep["reload"]
        if needs_ammo:
            tank.ammo -= 1

    def _split_clusters(self):
        out = []
        for p in self.projectiles:
            if p.kind == "cluster" and not p.split and p.vy >= 0:
                for k in range(5):           # airburst at the top of the arc
                    out.append(Projectile(
                        p.x, p.y, p.vx * 0.5 + (k - 2) * 1.7, p.vy - 1.2, owner=p.owner,
                        kind="normal", blast=40, crater=24, dmg=15))
            else:
                out.append(p)
        self.projectiles = out

    def _handle_collisions(self):
        remaining = []
        for p in self.projectiles:
            if p.x < -60 or p.x > self.world_w + 60 or p.y > H + 300:
                continue  # left the battlefield
            gy = self.terrain.height_at(p.x)
            if p.y >= gy:                                    # hit the ground
                if p.kind == "bounce" and p.bounces > 0:
                    p.bounces -= 1
                    p.y = gy - 3
                    p.vy = -abs(p.vy) * 0.6
                    p.vx *= 0.82
                    remaining.append(p)
                    continue
                self._explode(p.x, gy, p.blast, p.crater, p.dmg)
                continue
            hit = False
            for t in self.tanks:                             # hit a tank
                cy = t.y - BODY_H * 0.5
                if (p.x - t.x) ** 2 + (p.y - cy) ** 2 <= TANK_RADIUS ** 2:
                    self._explode(p.x, p.y, p.blast, p.crater, p.dmg)
                    hit = True
                    break
            if not hit:
                remaining.append(p)
        self.projectiles = remaining

    def _explode(self, x, y, blast=BLAST_RADIUS, crater=CRATER_RADIUS, dmg=MAX_DAMAGE):
        for t in self.tanks:
            d = math.hypot(x - t.x, y - (t.y - BODY_H * 0.5))
            if d < blast:
                t.hp = max(0.0, t.hp - dmg * (1 - d / blast))
        self.explosions.append({"x": x, "y": y, "age": 0})
        # carve the terrain and log the EXACT crater so the client reproduces it
        self.terrain.apply_crater(x, y, crater)
        self.craters.append({"x": x, "y": y, "r": crater})
        self._check_over()

    def _check_lava(self):
        """A tank standing in the lava (a chasm, or a crater dug down to it) dies."""
        if not self.terrain.lava_y:
            return
        died = False
        for t in self.tanks:
            if t.hp > 0 and t.y >= LAVA_DEATH_Y:
                t.hp = 0.0
                self.explosions.append({"x": t.x, "y": LAVA_Y, "age": 0})
                died = True
        if died:
            self._check_over()

    def _check_over(self):
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
                    "name": t.name, "color": list(t.color), "weapon": t.weapon,
                    "ammo": t.ammo,
                }
                for t in self.tanks
            ],
            "projectiles": [{"x": p.x, "y": p.y} for p in self.projectiles],
            "explosions": [dict(e) for e in self.explosions],
            "craters": [dict(c) for c in self.craters],
            "wind": self.wind,
            "phase": self.phase,
            "winner": self.winner,
            "world_w": self.world_w,
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


def camera_x(snap, local_index, world_w):
    """Left edge (world x) of the viewport, centred on the local tank, clamped."""
    if world_w <= W:
        return 0
    tanks = snap.get("tanks", [])
    cx = tanks[local_index]["x"] if 0 <= local_index < len(tanks) else world_w / 2
    return clamp(cx - W / 2, 0, world_w - W)


def _draw_lava(scene, terrain, cam_x):
    """Animated molten band along the bottom of the world."""
    ly = terrain.lava_y
    if not ly:
        return
    pygame.draw.rect(scene, (78, 14, 8), pygame.Rect(0, ly, W, H - ly))
    t = pygame.time.get_ticks() * 0.004
    for k in range(0, W + 24, 24):                 # wobbling bright crest
        sx = k
        wy = ly + 4 + 3 * math.sin(t + (k + cam_x) * 0.03)
        pygame.draw.line(scene, (255, 150, 40), (sx, wy), (sx + 24, wy), 3)
    pygame.draw.line(scene, (255, 210, 120), (0, ly), (W, ly), 2)


def _draw_terrain(scene, terrain, cam_x):
    _, textured, mask = _surfaces()
    floor = terrain.lava_y or H                    # draw ground only down to the lava
    cols = list(range(0, W + 2, 2))
    silhouette = [(sx, min(terrain.height_at(sx + cam_x), floor)) for sx in cols]
    mask.fill((0, 0, 0, 0))
    pygame.draw.polygon(mask, (255, 255, 255, 255),
                        [(0, H)] + silhouette + [(W, H)])
    textured.fill((0, 0, 0, 0))
    ox = -(int(cam_x) % W)                          # scroll the ground texture
    textured.blit(resources.img("ground"), (ox, 0))
    textured.blit(resources.img("ground"), (ox + W, 0))
    textured.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    scene.blit(textured, (0, 0))
    pygame.draw.lines(scene, (126, 172, 98), False, silhouette, 3)


def _draw_tank(scene, t, index, cam_x):
    x, y = t["x"] - cam_x, t["y"]
    if x < -60 or x > W + 60:
        return
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


def _draw_scoreboard(screen, fonts, snap):
    small, font, _ = fonts
    scores = snap.get("scores")
    if scores is None:
        return
    blue, red = tuple(snap["tanks"][0]["color"]), tuple(snap["tanks"][1]["color"])
    a = font.render(str(scores[0]), True, blue)
    mid = font.render("  -  ", True, (210, 210, 220))
    b = font.render(str(scores[1]), True, red)
    x = W // 2 - (a.get_width() + mid.get_width() + b.get_width()) // 2
    screen.blit(a, (x, 6)); x += a.get_width()
    screen.blit(mid, (x, 6)); x += mid.get_width()
    screen.blit(b, (x, 6))
    info = small.render(f"Round {snap.get('round', 1)}  -  first to {snap.get('needed', ROUNDS_TO_WIN)}",
                        True, (175, 185, 205))
    screen.blit(info, (W // 2 - info.get_width() // 2, 6 + a.get_height()))


def _draw_weapons(screen, small, snap, local_index):
    if not (0 <= local_index < len(snap["tanks"])):
        return
    me = snap["tanks"][local_index]
    sel = me.get("weapon", 0)
    ammo = int(me.get("ammo", 0))
    # The basic Shell (index 0) is unlimited; the rest cost a special shell.
    labels = [f"{i + 1} {w['name']}" + (" ∞" if i == 0 else "")
              for i, w in enumerate(WEAPONS)]
    pad, gap, h = 12, 8, 26
    surfs = [small.render(t, True, (236, 238, 245)) for t in labels]
    widths = [s.get_width() + pad * 2 for s in surfs]
    x = W // 2 - (sum(widths) + gap * (len(surfs) - 1)) // 2
    y = H - 98
    for i, s in enumerate(surfs):
        rect = pygame.Rect(x, y, widths[i], h)
        unaffordable = i != 0 and ammo <= 0          # a special you can't fire yet
        if i == sel:
            pygame.draw.rect(screen, (120, 70, 70) if unaffordable else (70, 95, 140), rect, border_radius=6)
            pygame.draw.rect(screen, (210, 130, 130) if unaffordable else (150, 190, 240), rect, 2, border_radius=6)
        else:
            pygame.draw.rect(screen, (28, 34, 50), rect, border_radius=6)
            pygame.draw.rect(screen, (66, 76, 100), rect, 1, border_radius=6)
        if unaffordable and i != sel:
            s = small.render(labels[i], True, (120, 126, 140))   # dim the ones you can't afford
        screen.blit(s, (x + pad, y + (h - s.get_height()) // 2))
        x += widths[i] + gap


def _draw_wind(screen, small, wind):
    cx, cy = W // 2, 68
    lbl = small.render("WIND", True, (200, 200, 215))
    screen.blit(lbl, (cx - lbl.get_width() // 2, cy - 16))
    length = int(wind / WIND_MAX * 64)
    pygame.draw.line(screen, (225, 225, 240), (cx, cy), (cx + length, cy), 3)
    if abs(length) > 4:
        d = 1 if length > 0 else -1
        ex = cx + length
        pygame.draw.line(screen, (225, 225, 240), (ex, cy), (ex - 7 * d, cy - 5), 3)
        pygame.draw.line(screen, (225, 225, 240), (ex, cy), (ex - 7 * d, cy + 5), 3)


def _parallax(scene, img, y, cam_x, factor):
    """Tile a background layer so it scrolls slower than the world (depth)."""
    ox = -int(cam_x * factor) % W
    scene.blit(img, (ox - W, y))
    scene.blit(img, (ox, y))


def draw_world(screen, terrain, snap, fx=None, cam_x=0, bg=None):
    """Draw just the battlefield (sky, terrain, tanks, shells, particles, shake).

    `bg` optionally names a full-screen backdrop image (see resources.backgrounds)
    to use instead of the painted sky + parallax hills for this match.
    """
    scene, _, _ = _surfaces()
    if bg and resources.has(bg):
        scene.blit(resources.img(bg), (0, 0))      # special photo backdrop
    else:
        scene.blit(resources.img("sky"), (0, 0))
        _parallax(scene, resources.img("hills_far"), 80, cam_x, 0.3)
        _parallax(scene, resources.img("hills_near"), 135, cam_x, 0.6)
    _draw_lava(scene, terrain, cam_x)
    _draw_terrain(scene, terrain, cam_x)
    for i, t in enumerate(snap["tanks"]):
        _draw_tank(scene, t, i, cam_x)
    for p in snap["projectiles"]:
        px, py = int(p["x"] - cam_x), int(p["y"])
        if -20 <= px <= W + 20:
            pygame.draw.circle(scene, (24, 22, 26), (px, py), 5)
            pygame.draw.circle(scene, (255, 222, 120), (px, py), 3)
    if fx is not None:
        fx.draw(scene, -cam_x, 0)
    dx, dy = fx.shake_offset() if fx is not None else (0, 0)
    screen.fill((8, 9, 14))
    screen.blit(scene, (int(dx), int(dy)))


def draw_match_overlay(screen, fonts, snap):
    """The round/match end banner, shared by all modes."""
    small, font, big = fonts
    mphase = snap.get("match_phase", "playing")
    if mphase not in ("round_over", "match_over"):
        return
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((10, 12, 20, 180))
    screen.blit(overlay, (0, 0))
    scores = snap.get("scores", [0, 0])
    rw = snap.get("round_winner")
    if mphase == "round_over":
        title = "ROUND DRAW" if rw is None else f"{snap['tanks'][rw]['name'].upper()} WINS THE ROUND"
        sub = "next round starting..."
    else:
        mw = 0 if scores[0] >= scores[1] else 1
        title = f"{snap['tanks'][mw]['name'].upper()} WINS THE MATCH!"
        sub = "Press ENTER for menu"
    t = big.render(title, True, (255, 235, 160))
    screen.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 72))
    sc = font.render(f"{scores[0]}   -   {scores[1]}", True, (235, 235, 245))
    screen.blit(sc, (W // 2 - sc.get_width() // 2, H // 2 - 8))
    s = font.render(sub, True, (212, 218, 232))
    screen.blit(s, (W // 2 - s.get_width() // 2, H // 2 + 36))


def _draw_ammo(screen, fonts, snap, local_index):
    """The local player's special-shell magazine, bottom-left. (Basic Shell is
    unlimited, so this only tracks Big Bomb / Cluster / Bouncer ammo.)"""
    small, _font, _ = fonts
    if not (0 <= local_index < len(snap["tanks"])):
        return
    ammo = int(snap["tanks"][local_index].get("ammo", 0))
    x, y = 18, H - 132
    screen.blit(small.render("SPECIAL SHELLS", True, (214, 200, 150)), (x, y))
    bw, bh, gap = 16, 20, 5
    by = y + 20
    for i in range(min(AMMO_MAX, max(ammo, START_AMMO))):
        r = pygame.Rect(x + i * (bw + gap), by, bw, bh)
        if i < ammo:
            pygame.draw.rect(screen, (240, 180, 70), r, border_radius=3)
        pygame.draw.rect(screen, (120, 110, 80), r, 2, border_radius=3)
    if ammo <= 0:
        hint = small.render("TAB: type to reload", True, (170, 178, 196))
        screen.blit(hint, (x, by + bh + 4))


def _draw_offscreen_enemy(screen, small, snap, local_index, cam_x):
    """An edge arrow + distance pointing at the enemy when they're off-screen."""
    tanks = snap.get("tanks", [])
    if not (0 <= local_index < len(tanks)) or len(tanks) < 2:
        return
    enemy = tanks[1 - local_index]
    ex = enemy["x"] - cam_x
    if 0 <= ex <= W:
        return
    on_right = ex > W
    d = 1 if on_right else -1
    edge = (W - 22) if on_right else 22
    ey = clamp(enemy["y"] - 30, 72, H - 150)
    col = tuple(enemy["color"])
    pygame.draw.polygon(screen, col, [(edge + 14 * d, ey),
                                      (edge - 10 * d, ey - 13), (edge - 10 * d, ey + 13)])
    dist = int(abs(enemy["x"] - (cam_x + (W if on_right else 0))))
    lbl = small.render(f"{enemy['name']}  {dist}m", True, col)
    lx = (edge - 20 - lbl.get_width()) if on_right else (edge + 20)
    screen.blit(lbl, (lx, ey - 8))


def draw_reload_panel(screen, fonts, type_font, cw, typer, ammo):
    """The type-to-reload panel shown during a fight (bottom of the screen)."""
    small, _font, _big = fonts
    panel = pygame.Rect(40, H - 120, W - 80, 100)
    surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    surf.fill((12, 14, 24, 216))
    screen.blit(surf, (panel.x, panel.y))
    pygame.draw.rect(screen, (92, 112, 152), panel, 2, border_radius=8)
    head = "RELOAD — type sentences to load special shells    (TAB: back to fight)"
    lbl = small.render(head, True, (182, 202, 232))
    screen.blit(lbl, (W // 2 - lbl.get_width() // 2, panel.y + 8))
    target, pos = typer.target, typer.pos
    sx = W // 2 - (cw * len(target)) // 2
    ty = panel.y + 34
    for i, ch in enumerate(target):
        cx = sx + i * cw
        if i < pos:
            color = (120, 225, 135)
        elif i == pos:
            pygame.draw.rect(screen, (235, 235, 170), (cx, ty - 2, cw, type_font.get_height() + 2), border_radius=3)
            color = (20, 24, 34)
        else:
            color = (170, 180, 195)
        s = type_font.render(ch, True, color)
        screen.blit(s, (cx + (cw - s.get_width()) // 2, ty))
    stats = small.render(f"Special shells loaded: {ammo}     ESC: menu", True, (178, 188, 208))
    screen.blit(stats, (W // 2 - stats.get_width() // 2, panel.y + 74))


def render(screen, fonts, terrain, snap, local_index, version, fx=None):
    small, font, big = fonts
    cam = camera_x(snap, local_index, terrain.width)
    draw_world(screen, terrain, snap, fx, cam, bg=snap.get("bg"))

    _draw_hp(screen, font, snap["tanks"][0], 16, 14)
    _draw_hp(screen, font, snap["tanks"][1], W - 16, 14, right=True)
    _draw_wind(screen, small, snap["wind"])
    _draw_scoreboard(screen, fonts, snap)
    _draw_ammo(screen, fonts, snap, local_index)
    _draw_offscreen_enemy(screen, small, snap, local_index, cam)

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
        elif me.get("weapon", 0) != 0 and int(me.get("ammo", 0)) <= 0:
            cue = small.render(
                f"No {WEAPONS[me['weapon']]['name']} shells — press 1 for unlimited Shell, or TAB to reload",
                True, (236, 170, 120))
            screen.blit(cue, (W // 2 - cue.get_width() // 2, H - 62))

    _draw_weapons(screen, small, snap, local_index)
    hint = small.render(
        "Move: A/D   Aim: W/S   Weapon: 1-4   Fire: SPACE   Reload: TAB   ESC: menu",
        True, (185, 192, 208))
    screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 22))
    ver = small.render(f"v{version}", True, (130, 140, 160))
    screen.blit(ver, (12, H - 22))

    draw_match_overlay(screen, fonts, snap)
