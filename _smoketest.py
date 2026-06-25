"""Headless smoke test — no window. Verifies sim, render, terrain sync, netcode."""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import time
import pygame
pygame.init()
screen = pygame.display.set_mode((1000, 600))
fonts = (pygame.font.SysFont("consolas", 16),
         pygame.font.SysFont("consolas", 22),
         pygame.font.SysFont("consolas", 54, bold=True))

import resources
resources.load()
import effects
from game import World, Terrain, render, draw_world, draw_match_overlay, NEUTRAL_INPUT, WEAPONS, TANK_HP, W, H
from bot import Bot, solve_shot
import typing_mode
from updater import _parse

assert len(resources._SPRITES) == 13, "sprites failed to load"
print(f"[ok] assets loaded ({len(resources._SPRITES)} sprites, audio_ok={resources.audio_ok})")

# 1) terrain determinism: same seed -> identical ground
t1 = Terrain(12345); t2 = Terrain(12345)
assert t1.ground == t2.ground, "terrain not deterministic"
assert Terrain(1).ground != Terrain(2).ground, "different seeds gave same terrain"
print("[ok] terrain is deterministic from seed")

# 2a) blast damage near a tank hurts it; enough blasts end the match
world = World(777)
render(screen, fonts, world.terrain, world.snapshot(), local_index=0, version="test")  # render path
red = world.tanks[1]
for _ in range(12):
    world._explode(red.x, red.y - 8)
assert red.hp == 0, f"Red should be dead, hp={red.hp}"
assert world.phase == "over" and world.winner == 0, "match should end with Blue winning"
print("[ok] blast damage + win condition work")

# 2b) an actually-aimed shot can fly across the map and hit the far tank
hit_with = None
for angle in (42, 45, 48, 50):
    for p10 in range(130, 181, 5):          # power 13.0 .. 18.0
        w = World(777)
        w.wind = 0.0
        w.wind_timer = 10 ** 9              # freeze wind for a deterministic shot
        w.tanks[0].angle = float(angle)
        w.tanks[0].charge = p10 / 10.0
        w._launch(0)
        start_hp = w.tanks[1].hp
        for _ in range(600):
            w.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
            if not w.projectiles:
                break
        if w.tanks[1].hp < start_hp:
            hit_with = (angle, p10 / 10.0)
            break
    if hit_with:
        break
assert hit_with, "no angle/power combo ever hit the far tank — the game isn't winnable"
print(f"[ok] a fired shot reaches and damages the far tank (angle={hit_with[0]}, power={hit_with[1]})")

# 2c) destructible terrain: a blast lowers the ground, and the client can rebuild
#     the identical terrain from the snapshot's crater log.
w = World(777)
x0 = 500
before = w.terrain.height_at(x0)
w._explode(x0, before)                       # blast on the surface
after = w.terrain.height_at(x0)
assert after > before, f"ground should drop (y grows down): before={before}, after={after}"
assert len(w.snapshot()["craters"]) == 1, "crater not recorded in snapshot"
client_terrain = Terrain(777, W, H)          # fresh terrain from same seed...
for c in w.snapshot()["craters"]:            # ...plus the crater log...
    client_terrain.apply_crater(c["x"], c["y"], c["r"])
assert client_terrain.ground == w.terrain.ground, "client terrain diverged from host"
print("[ok] destructible terrain digs craters and stays in sync host<->client")

# 2d) juice layer: FX observes snapshots, spawns particles on a blast, renders
fx = effects.FX()
w = World(777)
fx.observe(w.snapshot(), 0)
fx.update()
w._explode(w.tanks[1].x, w.tanks[1].y - 8)        # crater -> explosion event
fx.observe(w.snapshot(), 0)
assert len(fx.particles) > 0, "explosion should spawn particles"
fx.update()
render(screen, fonts, w.terrain, w.snapshot(), local_index=0, version="test", fx=fx)
print(f"[ok] FX layer spawns particles and renders ({len(fx.particles)} live)")

# 2e) a rising edge on the very first frame still fires its sound (charge)
fx2 = effects.FX()
w2 = World(5)
w2.tanks[0].charging = True                  # already charging on frame 0
plays = []
_orig_play = resources.play
resources.play = lambda n: plays.append(n)
try:
    fx2.observe(w2.snapshot(), 0)
finally:
    resources.play = _orig_play
assert "charge" in plays, f"charge sound should fire on a frame-0 charge, got {plays}"
print("[ok] first-frame rising edge triggers its sound (charge)")


def _launch_weapon(seed, widx, angle=45, power=15.0):
    world = World(seed)
    world.wind = 0.0
    world.wind_timer = 10 ** 9
    t = world.tanks[0]
    t.weapon, t.angle, t.charge = widx, float(angle), power
    world._launch(0)
    return world

# 2f) each weapon launches the right kind of projectile
assert _launch_weapon(99, 0).projectiles[-1].crater == 40, "shell"
big = _launch_weapon(99, 1).projectiles[-1]
assert big.crater == 64 and big.blast == 94, "big bomb should be bigger"
assert _launch_weapon(99, 2).projectiles[-1].kind == "cluster", "cluster"
bnc = _launch_weapon(99, 3).projectiles[-1]
assert bnc.kind == "bounce" and bnc.bounces == 2, "bouncer"
print("[ok] weapons launch the correct projectile types")

# 2g) cluster shell airbursts into several submunitions
wc = _launch_weapon(99, 2, angle=72, power=17.0)
maxn = 1
for _ in range(400):
    wc.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
    maxn = max(maxn, len(wc.projectiles))
    if not wc.projectiles:
        break
assert maxn >= 4, f"cluster should burst into multiple submunitions, saw max {maxn}"
print(f"[ok] cluster shell airbursts (max {maxn} projectiles in flight)")

# 2h) bouncer skips off the terrain at least once before exploding
wb = _launch_weapon(99, 3, angle=22, power=15.0)
prev_b = wb.projectiles[0].bounces
bounced = False
for _ in range(400):
    wb.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
    if wb.projectiles and wb.projectiles[0].bounces < prev_b:
        bounced = True
        prev_b = wb.projectiles[0].bounces
    if not wb.projectiles:
        break
assert bounced, "bouncer should bounce before exploding"
print("[ok] bouncer skips off the terrain")

# 2i) host clamps a malformed remote weapon index (no crash on fire)
wsafe = World(99)
for badval in (99, -1, "x", None):
    inp = dict(NEUTRAL_INPUT)
    inp["weapon"] = badval
    wsafe.step([NEUTRAL_INPUT, inp])           # red tank fed a bad weapon index
    assert 0 <= wsafe.tanks[1].weapon < len(WEAPONS), f"weapon not clamped: {wsafe.tanks[1].weapon}"
wsafe.tanks[1].charge = 15.0
wsafe._launch(1)                               # must not raise IndexError
print("[ok] host clamps malformed remote weapon index")

# 2j) the CPU bot (practice mode) aims, fires, and actually lands hits
wbot = World(123)
b = Bot(1)
fired = False
for _ in range(60 * 40):                       # up to ~40 simulated seconds
    wbot.step([NEUTRAL_INPUT, b.input(wbot)])  # bot is tank 1; tank 0 sits still
    fired = fired or bool(wbot.projectiles)
    if wbot.phase == "over":
        break
assert fired, "bot never fired a shot"
assert wbot.tanks[0].hp < TANK_HP, f"bot dealt no damage in 40s (hp={wbot.tanks[0].hp})"
print(f"[ok] CPU bot aims and lands hits (target down to {wbot.tanks[0].hp:.0f} hp)")

# 2k) typing mode: sentences are clean, the refactored draws work, and a
#     completed sentence fires a shell
assert typing_mode.SENTENCES and all(s == s.lower() and s.isprintable() for s in typing_mode.SENTENCES)
wt = World(50)
angle, power, wk = solve_shot(wt, wt.tanks[0], wt.tanks[1], scatter=5.0, weapon=0)
assert 8 <= angle <= 89 and power > 0 and wk == 0, (angle, power, wk)
n0 = len(wt.projectiles)
typing_mode._fire(wt, 0, 1, scatter=5.0, weapon=0)
assert len(wt.projectiles) == n0 + 1, "completing a sentence should launch a shell"
draw_world(screen, wt.terrain, wt.snapshot(), None)       # refactored scene path
draw_match_overlay(screen, fonts, {"match_phase": "match_over", "scores": [3, 1],
                                   "tanks": wt.snapshot()["tanks"], "round_winner": 0})
print(f"[ok] typing mode: {len(typing_mode.SENTENCES)} sentences, auto-fire + draw split work")

# 3) snapshot is JSON-serialisable (it crosses the network)
import json
json.dumps(world.snapshot())
print("[ok] snapshot serialises to JSON")

# 4) version parsing / comparison
assert _parse("v1.0.10") > _parse("v1.0.9"), "1.0.10 should beat 1.0.9"
assert _parse("v1.2.0") > _parse("1.1.9")
assert not (_parse("1.0.0") > _parse("v1.0.0"))
print("[ok] version comparison works (1.0.10 > 1.0.9)")

# 5) loopback netcode: host + client over localhost
from netcode import Server, Client, PORT
srv = Server()
srv.start_listening()
cli = Client()
assert cli.connect("127.0.0.1", PORT, timeout=4), "client failed to connect"
# client should have learned the seed and its player index
assert cli.seed == srv.seed, "seed mismatch across the wire"
assert cli.index == 1
# client sends input, host should receive it
cli.send_input({"left": True, "right": False, "up": False, "down": False, "fire": True})
time.sleep(0.2)
got = srv.get_input()
assert got["left"] is True and got["fire"] is True, f"host did not get client input: {got}"
# host sends state; client reconstructs the full crater list from deltas
srv.send_state({"hp": 99, "craters": [{"x": 1, "y": 2, "r": 40}]})
time.sleep(0.2)
st = cli.get_state()
assert st["hp"] == 99 and st["craters"] == [{"x": 1, "y": 2, "r": 40}], st
srv.send_state({"hp": 98, "craters": [{"x": 1, "y": 2, "r": 40}, {"x": 3, "y": 4, "r": 40}]})
time.sleep(0.2)
st = cli.get_state()
assert len(st["craters"]) == 2, f"client should have accumulated 2 craters: {st}"
# a new round resets the crater accumulator on both sides
srv.send_state({"round": 2, "craters": [{"x": 9, "y": 9, "r": 40}]})
time.sleep(0.2)
st = cli.get_state()
assert st["round"] == 2 and len(st["craters"]) == 1, f"round change should reset craters: {st}"
cli.close(); srv.close()
print("[ok] netcode loopback: input, crater-delta, and round-reset all crossed the wire")

print("\nALL SMOKE TESTS PASSED")
