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
from game import (World, Terrain, render, draw_world, draw_match_overlay, camera_x,
                  ReloadTyper, NEUTRAL_INPUT, WEAPONS, TANK_HP, W, H, WORLD_W,
                  START_AMMO, AMMO_MAX, LAVA_DEATH_Y)
from bot import Bot, solve_shot
import typing_mode
from updater import _parse

# Check the named sprites specifically — NOT len(_SPRITES), because drop-in
# backgrounds also live in that dict (under "bg:" keys) and would inflate it.
assert all(resources.has(n) for n in resources._SPRITE_NAMES), "sprites failed to load"
print(f"[ok] assets loaded ({len(resources._SPRITE_NAMES)} sprites, "
      f"{len(resources.backgrounds())} backgrounds, audio_ok={resources.audio_ok})")

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

# 2b) an actually-aimed shot can hit the enemy once you've closed to fire range
#     (tanks now spawn far apart and drive together, so park them in range first)
hit_with = None
for angle in range(40, 64, 3):
    for p10 in range(120, 181, 5):          # power 12.0 .. 18.0
        w = World(777)
        w.wind = 0.0
        w.wind_timer = 10 ** 9              # freeze wind for a deterministic shot
        blue, red = w.tanks[0], w.tanks[1]
        red.x = blue.x + 450                # both on the safe left flank, in range
        red.y = w.terrain.height_at(red.x)
        blue.angle = float(angle)
        blue.charge = p10 / 10.0
        w._launch(0)
        start_hp = red.hp
        for _ in range(600):
            w.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
            if not w.projectiles:
                break
        if red.hp < start_hp:
            hit_with = (angle, p10 / 10.0)
            break
    if hit_with:
        break
assert hit_with, "no angle/power combo ever hit the enemy in range — the game isn't winnable"
print(f"[ok] a fired shot reaches and damages an in-range enemy (angle={hit_with[0]}, power={hit_with[1]})")

# 2c) destructible terrain: a blast lowers the ground, and the client can rebuild
#     the identical terrain from the snapshot's crater log.
w = World(777)
x0 = 500
before = w.terrain.height_at(x0)
w._explode(x0, before)                       # blast on the surface
after = w.terrain.height_at(x0)
assert after > before, f"ground should drop (y grows down): before={before}, after={after}"
assert len(w.snapshot()["craters"]) == 1, "crater not recorded in snapshot"
client_terrain = Terrain(777, WORLD_W, H)    # fresh terrain from same seed...
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
wbot.tanks[1].x = wbot.tanks[0].x + 460       # close to fire range (player drives in)
wbot.tanks[1].y = wbot.terrain.height_at(wbot.tanks[1].x)
wbot.tanks[1].ammo = 999                       # CPU doesn't reload in practice
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

# 2l) special weapons cost ammo; the basic Shell (index 0) is unlimited
wa = World(50)
wa.tanks[0].ammo = 1
wa.tanks[0].weapon = 1                               # Big Bomb (a special)
wa.tanks[0].charge = 15.0; wa._launch(0)
assert wa.tanks[0].ammo == 0, f"a special shot should spend a shell: {wa.tanks[0].ammo}"
n = len(wa.projectiles)
wa.tanks[0].charge = 15.0; wa._launch(0)            # special + empty -> no fire
assert len(wa.projectiles) == n, "a special weapon must not fire when empty"
wa.tanks[0].weapon = 0                               # basic Shell: unlimited
wa.tanks[0].charge = 15.0; wa._launch(0)
assert len(wa.projectiles) == n + 1 and wa.tanks[0].ammo == 0, "basic Shell should fire free"
print("[ok] special weapons cost ammo; the basic Shell is unlimited")

# 2m) reload-by-typing: a rising 'typed' counter in input adds shells, idempotently
wr = World(51)
wr.tanks[1].ammo = 0
inp = dict(NEUTRAL_INPUT); inp["typed"] = 3
wr.step([NEUTRAL_INPUT, inp])                        # 3 sentences typed -> +3
assert wr.tanks[1].ammo == 3, wr.tanks[1].ammo
wr.step([NEUTRAL_INPUT, inp])                        # same counter -> no double credit
assert wr.tanks[1].ammo == 3, "typed credit must be idempotent"
inp["typed"] = 999
wr.step([NEUTRAL_INPUT, inp])                        # huge -> capped at AMMO_MAX
assert wr.tanks[1].ammo == AMMO_MAX, wr.tanks[1].ammo
print(f"[ok] typing reloads ammo (idempotent, capped at {AMMO_MAX})")

# 2n) lava: a tank standing in a chasm carved to the lava line dies
wl = World(52)
assert wl.terrain.lava_y, "a wide world should have a lava sea"
lethal_x = next((x for x in range(wl.world_w) if wl.terrain.ground[x] >= LAVA_DEATH_Y), None)
assert lethal_x is not None, "expected at least one lava chasm"
wl.tanks[0].x = float(lethal_x)
wl.step([NEUTRAL_INPUT, NEUTRAL_INPUT])              # settles into the lava
assert wl.tanks[0].hp == 0 and wl.phase == "over" and wl.winner == 1, "lava should kill + end round"
print("[ok] lava chasm kills a tank that stands in it")

# 2o) camera follows the local tank and clamps to the world edges
csnap = World(60).snapshot()
csnap["tanks"][0]["x"] = 0
assert camera_x(csnap, 0, WORLD_W) == 0
csnap["tanks"][0]["x"] = WORLD_W
assert camera_x(csnap, 0, WORLD_W) == WORLD_W - W
csnap["tanks"][0]["x"] = WORLD_W / 2
assert camera_x(csnap, 0, WORLD_W) == WORLD_W / 2 - W / 2
assert camera_x(csnap, 0, W) == 0, "a screen-sized world should never scroll"
print("[ok] camera follows local tank and clamps to world edges")

# 2p) drop-in backgrounds: a registered backdrop can be picked and rendered, and
#     it rides along in the snapshot so the client paints the same one
import resources as _res
_fake = pygame.Surface((1500, 1000)); _fake.fill((90, 40, 60))
_res._SPRITES["bg:_test"] = _res._cover_scale(_fake, _res.SCREEN_W, _res.SCREEN_H)
_res._BACKGROUNDS.append("bg:_test")
assert _res.has("bg:_test") and _res.random_background(chance=1.0) == "bg:_test"
assert _res.random_background(chance=0.0) is None, "chance 0 should never pick a backdrop"
wbg = World(7)
sbg = wbg.snapshot(); sbg.update({"bg": "bg:_test"})
import json as _json
_json.dumps(sbg)                                     # bg key must stay JSON-safe
render(screen, fonts, wbg.terrain, sbg, local_index=0, version="test")   # photo-bg path
_res._BACKGROUNDS.remove("bg:_test"); del _res._SPRITES["bg:_test"]
print("[ok] drop-in background loads, is chosen by chance, and renders + syncs")

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
