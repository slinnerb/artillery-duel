"""A simple CPU opponent for practice mode.

The bot reads the local world (practice mode runs the simulation locally, no
networking) and returns an input dict each frame, exactly like a human player:
it aims its barrel toward a computed angle, holds fire to charge to a target
power, then releases to shoot. It finds a firing solution by simulating candidate
shots against the current terrain and wind, so it adapts as the ground gets
blown apart. A bit of scatter keeps it beatable.
"""
import math
import random

from game import (W, GRAVITY, BODY_H, BARREL_LEN, POWER_MIN, POWER_MAX,
                  AIM_DEG, WEAPONS)

_NEUTRAL = {"left": False, "right": False, "up": False, "down": False, "fire": False, "weapon": 0}


class Bot:
    def __init__(self, index, scatter=45.0):
        self.i = index
        self.tgt = 1 - index
        self.scatter = scatter      # aim error in px — higher = easier
        self.plan = None            # (angle, power, weapon)
        self.phase = "aim"
        self.weapon = 0

    def _simulate(self, world, me, angle, power, speed):
        """Fly a virtual shell and return where it lands (x)."""
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

    def _plan_shot(self, world, me, tgt):
        weapon = random.choice([0, 0, 0, 0, 1])      # mostly Shell, sometimes Big Bomb
        speed = WEAPONS[weapon]["speed"]
        target_x = tgt.x + random.uniform(-self.scatter, self.scatter)
        powers = [POWER_MIN + (POWER_MAX - POWER_MIN) * k / 12.0 for k in range(1, 13)]
        best = None
        for angle in range(28, 78, 4):
            for power in powers:
                land = self._simulate(world, me, angle, power, speed)
                d = abs(land - target_x)
                if best is None or d < best[2]:
                    best = (angle, power, d)
        return float(best[0]), float(best[1]), weapon

    def input(self, world):
        me, tgt = world.tanks[self.i], world.tanks[self.tgt]
        inp = dict(_NEUTRAL)
        if me.reload > 0 or me.hp <= 0 or tgt.hp <= 0:
            self.plan, self.phase = None, "aim"
            inp["weapon"] = self.weapon
            return inp

        if self.plan is None:
            self.plan = self._plan_shot(world, me, tgt)
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
