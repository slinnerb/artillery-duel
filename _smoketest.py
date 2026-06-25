"""Headless smoke test — no window. Verifies sim, render, terrain sync, netcode."""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import time
import pygame
pygame.init()
screen = pygame.Surface((1000, 600))
fonts = (pygame.font.SysFont("consolas", 16),
         pygame.font.SysFont("consolas", 22),
         pygame.font.SysFont("consolas", 54, bold=True))

from game import World, Terrain, render, NEUTRAL_INPUT, W, H
from updater import _parse

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
# host sends a state, client should receive it
srv.send_state({"hello": 42})
time.sleep(0.2)
assert cli.get_state() == {"hello": 42}, f"client did not get state: {cli.get_state()}"
cli.close(); srv.close()
print("[ok] netcode loopback: seed, input, and state all crossed the wire")

print("\nALL SMOKE TESTS PASSED")
