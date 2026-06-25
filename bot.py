"""CPU aiming: a shared shot solver plus the practice-mode Bot.

solve_shot() finds a (angle, power, weapon) that lands near the target by
flying virtual shells against the current wind and terrain. It is used by the
practice Bot and by Typing Duel mode (which auto-aims, since the keyboard is
busy typing). `scatter` adds aim error in pixels — higher = easier to dodge.
"""
import math
import random

from game import (W, GRAVITY, BODY_H, BARREL_LEN, POWER_MIN, POWER_MAX,
                  AIM_DEG, WEAPONS)

_NEUTRAL = {"left": False, "right": False, "up": False, "down": False, "fire": False, "weapon": 0}


def _simulate(world, me, angle, power, speed):
    """Fly a virtual shell from `me` and return where it lands (x)."""
    rad = math.radians(angle)
    cos, sin = math.cos(rad), math.sin(rad)
    x = me.x + me.facing * cos * (BARREL_LEN + 6)
    y = (me.y - BODY_H) - sin * (BARREL_LEN + 6)
    vx = me.facing * cos * power * speed
    vy = -sin * power * speed
    for _ in range(700):
        vx += world.wind
        vy += GRAVITY
        x += vx
        y += vy
        if x < -60 or x > W + 60:
            return x
        if y >= world.terrain.height_at(x):
            return x
    return x


def solve_shot(world, me, tgt, scatter=45.0, weapon=None):
    """Return (angle, power, weapon) aiming `me` at `tgt`."""
    if weapon is None:
        weapon = random.choice([0, 0, 0, 0, 1])      # mostly Shell, sometimes Big Bomb
    speed = WEAPONS[weapon]["speed"]
    target_x = tgt.x + random.uniform(-scatter, scatter)
    powers = [POWER_MIN + (POWER_MAX - POWER_MIN) * k / 12.0 for k in range(1, 13)]
    best = None
    for angle in range(28, 78, 4):
        for power in powers:
            d = abs(_simulate(world, me, angle, power, speed) - target_x)
            if best is None or d < best[2]:
                best = (angle, power, d)
    return float(best[0]), float(best[1]), weapon


class Bot:
    def __init__(self, index, scatter=45.0):
        self.i = index
        self.tgt = 1 - index
        self.scatter = scatter      # aim error in px — higher = easier
        self.plan = None            # (angle, power, weapon)
        self.phase = "aim"
        self.weapon = 0

    def input(self, world):
        me, tgt = world.tanks[self.i], world.tanks[self.tgt]
        inp = dict(_NEUTRAL)
        if me.reload > 0 or me.hp <= 0 or tgt.hp <= 0:
            self.plan, self.phase = None, "aim"
            inp["weapon"] = self.weapon
            return inp

        if self.plan is None:
            self.plan = solve_shot(world, me, tgt, self.scatter)
            self.weapon = self.plan[2]
            self.phase = "aim"
        target_angle, target_power, _ = self.plan
        inp["weapon"] = self.weapon

        if self.phase == "aim":
            if me.angle < target_angle - AIM_DEG:
                inp["up"] = True
            elif me.angle > target_angle + AIM_DEG:
                inp["down"] = True
            else:
                self.phase = "charge"
        if self.phase == "charge":
            inp["fire"] = True
            if me.charge >= target_power:
                inp["fire"] = False          # release -> the world launches the shot
                self.plan, self.phase = None, "aim"
        return inp
