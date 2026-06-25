"""Artillery Duel — entry point: menu, match loops, and the update flow."""

import random
import sys
import threading

import pygame
from pygame.locals import *  # noqa: F401,F403

from version import __version__
from game import (W, H, FPS, SKY, World, Terrain, render, read_input,
                  weapon_from_keys, NEUTRAL_INPUT, ROUNDS_TO_WIN)
from netcode import Server, Client, PORT, local_ips
from updater import check_for_update, apply_update, cleanup_old, is_frozen
import resources
import effects
from bot import Bot


# ---------------------------------------------------------------------------
# Small shared UI helpers
# ---------------------------------------------------------------------------
def _quit():
    pygame.quit()
    sys.exit()


def _text_block(screen, fonts, lines, top=H // 2 - 70, color=(235, 235, 245)):
    _small, font, _big = fonts
    y = top
    for ln in lines:
        t = font.render(ln, True, color)
        screen.blit(t, (W // 2 - t.get_width() // 2, y))
        y += 34


def message_screen(screen, clock, fonts, text, sub="Press any key to continue"):
    small = fonts[0]
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type in (KEYDOWN, MOUSEBUTTONDOWN):
                return
        screen.fill(SKY)
        _text_block(screen, fonts, text.split("\n"))
        s = small.render(sub, True, (150, 160, 180))
        screen.blit(s, (W // 2 - s.get_width() // 2, H // 2 + 90))
        pygame.display.flip()
        clock.tick(60)


def confirm_screen(screen, clock, fonts, text):
    small = fonts[0]
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN:
                if e.key in (K_y, K_RETURN):
                    return True
                if e.key in (K_n, K_ESCAPE):
                    return False
        screen.fill(SKY)
        _text_block(screen, fonts, text.split("\n"))
        s = small.render("Y = yes        N = no", True, (170, 180, 200))
        screen.blit(s, (W // 2 - s.get_width() // 2, H // 2 + 90))
        pygame.display.flip()
        clock.tick(60)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
def menu_screen(screen, clock, fonts):
    small, font, big = fonts
    items = [("Host Game", "host"), ("Join Game", "join"),
             ("Practice vs CPU", "practice"),
             ("Check for Updates", "update"), ("Quit", "quit")]
    sel = 0
    while True:
        rects = [pygame.Rect(W // 2 - 165, 196 + i * 64, 330, 54) for i in range(len(items))]
        mouse = pygame.mouse.get_pos()
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN:
                if e.key in (K_DOWN, K_s):
                    sel = (sel + 1) % len(items)
                elif e.key in (K_UP, K_w):
                    sel = (sel - 1) % len(items)
                elif e.key in (K_RETURN, K_SPACE):
                    return items[sel][1]
                elif K_1 <= e.key < K_1 + len(items):
                    return items[e.key - K_1][1]
            if e.type == MOUSEBUTTONDOWN and e.button == 1:
                for i, r in enumerate(rects):
                    if r.collidepoint(e.pos):
                        return items[i][1]
        for i, r in enumerate(rects):
            if r.collidepoint(mouse):
                sel = i

        screen.fill(SKY)
        title = big.render("ARTILLERY DUEL", True, (235, 235, 245))
        screen.blit(title, (W // 2 - title.get_width() // 2, 120))
        for i, (label, _) in enumerate(items):
            r = rects[i]
            pygame.draw.rect(screen, (70, 90, 140) if i == sel else (45, 55, 80), r, border_radius=10)
            pygame.draw.rect(screen, (120, 140, 190), r, 2, border_radius=10)
            t = font.render(label, True, (232, 232, 242))
            screen.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
        tip = small.render("Tip: play over the internet with Tailscale — see README.md", True, (125, 135, 158))
        screen.blit(tip, (W // 2 - tip.get_width() // 2, H - 48))
        ver = small.render(f"v{__version__}", True, (135, 145, 165))
        screen.blit(ver, (12, H - 26))
        pygame.display.flip()
        clock.tick(60)


def join_input_screen(screen, clock, fonts):
    small, font, _big = fonts
    text = ""
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN:
                if e.key == K_ESCAPE:
                    return None
                if e.key == K_RETURN:
                    return text.strip() or None
                if e.key == K_BACKSPACE:
                    text = text[:-1]
                elif e.unicode in "0123456789.:":
                    text += e.unicode
        screen.fill(SKY)
        prompt = font.render("Enter the host's IP, then press ENTER:", True, (232, 232, 242))
        screen.blit(prompt, (W // 2 - prompt.get_width() // 2, 200))
        box = pygame.Rect(W // 2 - 220, 250, 440, 50)
        pygame.draw.rect(screen, (30, 38, 58), box, border_radius=8)
        pygame.draw.rect(screen, (120, 140, 190), box, 2, border_radius=8)
        caret = "_" if (pygame.time.get_ticks() // 500) % 2 else " "
        shown = (text + caret) if text else "100.x.y.z"
        color = (235, 235, 245) if text else (110, 120, 140)
        screen.blit(font.render(shown, True, color), (box.x + 12, box.centery - 12))
        hint = small.render("Use your friend's Tailscale IP (starts with 100.).  ESC to cancel.",
                            True, (140, 150, 170))
        screen.blit(hint, (W // 2 - hint.get_width() // 2, 320))
        pygame.display.flip()
        clock.tick(60)


# ---------------------------------------------------------------------------
# Hosting / joining a match
# ---------------------------------------------------------------------------
def do_host(screen, clock, fonts):
    small, font, _big = fonts
    server = Server()
    try:
        server.start_listening()
    except OSError as e:
        message_screen(screen, clock, fonts, f"Could not start host:\n{e}")
        return

    ips = local_ips()
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                server.close(); _quit()
            if e.type == KEYDOWN and e.key == K_ESCAPE:
                server.close(); return
        if server.error:
            message_screen(screen, clock, fonts, f"Host error:\n{server.error}")
            server.close(); return
        if server.connected:
            break

        screen.fill(SKY)
        _text_block(screen, fonts, ["Waiting for your opponent to join...",
                                    f"Share one of these addresses (port {PORT}):"], top=120)
        y = 210
        for ip in ips:
            tag = "  (Tailscale)" if ip.startswith("100.") else ""
            t = font.render(ip + tag, True, (160, 210, 255) if tag else (210, 210, 225))
            screen.blit(t, (W // 2 - t.get_width() // 2, y)); y += 34
        if not ips:
            t = font.render("(no network address found — is Tailscale running?)", True, (220, 160, 160))
            screen.blit(t, (W // 2 - t.get_width() // 2, y))
        esc = small.render("ESC to cancel", True, (150, 160, 180))
        screen.blit(esc, (W // 2 - esc.get_width() // 2, H - 60))
        pygame.display.flip()
        clock.tick(30)

    run_host(screen, clock, fonts, server)
    server.close()


def do_join(screen, clock, fonts, address):
    host, port = address, PORT
    if ":" in address:
        host, _, p = address.partition(":")
        if p.isdigit():
            port = int(p)

    screen.fill(SKY)
    _text_block(screen, fonts, [f"Connecting to {host}:{port} ..."])
    pygame.display.flip()

    client = Client()
    if not client.connect(host, port):
        message_screen(screen, clock, fonts,
                       f"Could not connect to {host}:{port}\n{client.error or ''}")
        return
    run_client(screen, clock, fonts, client)
    client.close()


def run_host(screen, clock, fonts, server):
    seed = server.seed
    world = World(seed)
    fx = effects.FX()
    scores = [0, 0]
    rnd = 1
    mphase = "playing"            # playing -> round_over -> (next round) | match_over
    round_winner = None
    timer = 0
    weapon = 0
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN and e.key == K_ESCAPE:
                return
            if e.type == KEYDOWN and e.key == K_RETURN and mphase == "match_over":
                return
        if not server.connected:
            message_screen(screen, clock, fonts, "Opponent left the game.")
            return

        keys = pygame.key.get_pressed()
        weapon = weapon_from_keys(keys, weapon)

        if mphase == "playing":
            inp = read_input(keys)
            inp["weapon"] = weapon
            world.step([inp, server.get_input()])
            if world.phase == "over":
                round_winner = world.winner
                if round_winner is not None:
                    scores[round_winner] += 1
                mphase = "match_over" if max(scores) >= ROUNDS_TO_WIN else "round_over"
                timer = int(FPS * 2.6)
        else:
            world.step([NEUTRAL_INPUT, NEUTRAL_INPUT])    # frozen; let FX fade
            if mphase == "round_over":
                timer -= 1
                if timer <= 0:                            # start the next round
                    rnd += 1
                    seed = (server.seed * 1103515245 + rnd * 12345) & 0x7FFFFFFF
                    world = World(seed)
                    fx = effects.FX()
                    mphase = "playing"
                    round_winner = None

        snap = world.snapshot()
        snap.update({"scores": scores, "round": rnd, "seed": seed,
                     "needed": ROUNDS_TO_WIN, "match_phase": mphase,
                     "round_winner": round_winner})
        server.send_state(snap)
        fx.observe(snap, 0)
        fx.update()
        render(screen, fonts, world.terrain, snap, local_index=0, version=__version__, fx=fx)
        pygame.display.flip()
        clock.tick(FPS)


def run_client(screen, clock, fonts, client):
    terrain = Terrain(client.seed, W, H)
    craters_applied = 0
    fx = effects.FX()
    my_round = None
    weapon = 0
    while True:
        snap = client.get_state()
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN and e.key == K_ESCAPE:
                return
            if e.type == KEYDOWN and e.key == K_RETURN and snap and snap.get("match_phase") == "match_over":
                return
        if not client.connected:
            message_screen(screen, clock, fonts, "Disconnected from host.")
            return

        keys = pygame.key.get_pressed()
        weapon = weapon_from_keys(keys, weapon)
        inp = read_input(keys)
        inp["weapon"] = weapon
        client.send_input(inp)

        if snap is None:
            screen.fill(SKY)
            _text_block(screen, fonts, ["Connected! Waiting for the host..."])
        else:
            if snap.get("round") != my_round:             # new round -> fresh terrain
                terrain = Terrain(snap.get("seed", client.seed), W, H)
                craters_applied = 0
                fx = effects.FX()
                my_round = snap.get("round")
            craters = snap.get("craters", [])
            if len(craters) > craters_applied:            # reproduce host's terrain damage
                for c in craters[craters_applied:]:
                    terrain.apply_crater(c["x"], c["y"], c["r"])
                craters_applied = len(craters)
            fx.observe(snap, client.index)
            fx.update()
            render(screen, fonts, terrain, snap, local_index=client.index, version=__version__, fx=fx)
        pygame.display.flip()
        clock.tick(FPS)


def run_practice(screen, clock, fonts):
    seed = random.randrange(1, 1_000_000)
    world = World(seed)
    world.tanks[1].name = "CPU"
    fx = effects.FX()
    bot = Bot(1)
    scores = [0, 0]
    rnd = 1
    mphase = "playing"
    round_winner = None
    timer = 0
    weapon = 0
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
            if e.type == KEYDOWN and e.key == K_ESCAPE:
                return
            if e.type == KEYDOWN and e.key == K_RETURN and mphase == "match_over":
                return

        keys = pygame.key.get_pressed()
        weapon = weapon_from_keys(keys, weapon)

        if mphase == "playing":
            inp = read_input(keys)
            inp["weapon"] = weapon
            world.step([inp, bot.input(world)])
            if world.phase == "over":
                round_winner = world.winner
                if round_winner is not None:
                    scores[round_winner] += 1
                mphase = "match_over" if max(scores) >= ROUNDS_TO_WIN else "round_over"
                timer = int(FPS * 2.6)
        else:
            world.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
            if mphase == "round_over":
                timer -= 1
                if timer <= 0:
                    rnd += 1
                    seed = random.randrange(1, 1_000_000)
                    world = World(seed)
                    world.tanks[1].name = "CPU"
                    fx = effects.FX()
                    bot = Bot(1)
                    mphase = "playing"
                    round_winner = None

        snap = world.snapshot()
        snap.update({"scores": scores, "round": rnd, "seed": seed,
                     "needed": ROUNDS_TO_WIN, "match_phase": mphase,
                     "round_winner": round_winner})
        fx.observe(snap, 0)
        fx.update()
        render(screen, fonts, world.terrain, snap, local_index=0, version=__version__, fx=fx)
        pygame.display.flip()
        clock.tick(FPS)


# ---------------------------------------------------------------------------
# Update flow
# ---------------------------------------------------------------------------
def do_update(screen, clock, fonts):
    screen.fill(SKY)
    _text_block(screen, fonts, ["Checking for updates..."])
    pygame.display.flip()

    try:
        info = check_for_update()
    except Exception as e:  # noqa: BLE001 — show any network/parse error to the user
        message_screen(screen, clock, fonts, f"Update check failed:\n{e}")
        return

    if not info:
        message_screen(screen, clock, fonts, f"You're up to date!  (v{__version__})")
        return

    if not is_frozen():
        message_screen(screen, clock, fonts,
                       f"Update available: v{info['latest']}  (you have v{__version__})\n"
                       "Running from source — git pull / re-download to update.")
        return

    if not confirm_screen(screen, clock, fonts,
                          f"Update available: v{info['latest']}\n"
                          f"You have v{__version__}.\n\nDownload and install now?"):
        return

    prog = {"v": 0.0, "err": None, "done": False}

    def worker():
        try:
            apply_update(info["url"], lambda p: prog.__setitem__("v", p))
        except Exception as e:  # noqa: BLE001
            prog["err"] = str(e)
            prog["done"] = True

    threading.Thread(target=worker, daemon=True).start()

    small, font, _big = fonts
    while not prog["done"]:
        for e in pygame.event.get():
            if e.type == QUIT:
                _quit()
        screen.fill(SKY)
        t = font.render(f"Downloading update...  {int(prog['v'] * 100)}%", True, (235, 235, 245))
        screen.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 40))
        bar = pygame.Rect(W // 2 - 200, H // 2, 400, 24)
        pygame.draw.rect(screen, (40, 50, 70), bar, border_radius=6)
        pygame.draw.rect(screen, (90, 170, 120),
                         pygame.Rect(bar.x, bar.y, int(bar.width * prog["v"]), bar.height), border_radius=6)
        pygame.draw.rect(screen, (120, 140, 190), bar, 2, border_radius=6)
        note = small.render("The game will restart automatically when done.", True, (150, 160, 180))
        screen.blit(note, (W // 2 - note.get_width() // 2, H // 2 + 50))
        pygame.display.flip()
        clock.tick(30)

    # On success apply_update() relaunched a new process and exited; we only
    # reach here on failure.
    if prog["err"]:
        message_screen(screen, clock, fonts, f"Update failed:\n{prog['err']}")


# ---------------------------------------------------------------------------
def main():
    cleanup_old()
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption(f"Artillery Duel v{__version__}")
    clock = pygame.time.Clock()
    fonts = (
        pygame.font.SysFont("consolas", 16),
        pygame.font.SysFont("consolas", 22),
        pygame.font.SysFont("consolas", 54, bold=True),
    )
    resources.load()

    while True:
        choice = menu_screen(screen, clock, fonts)
        if choice == "host":
            do_host(screen, clock, fonts)
        elif choice == "join":
            addr = join_input_screen(screen, clock, fonts)
            if addr:
                do_join(screen, clock, fonts, addr)
        elif choice == "practice":
            run_practice(screen, clock, fonts)
        elif choice == "update":
            do_update(screen, clock, fonts)
        elif choice == "quit":
            break

    _quit()


if __name__ == "__main__":
    main()
