"""Typing Duel — a single-player mode where typing is your trigger.

A sentence appears; type it correctly and a shell launches at the CPU
(auto-aimed, since your hands are on the keyboard). Type faster than the CPU
reloads and you win. Reuses the battlefield, weapons, explosions, and the
best-of-5 round machinery.
"""
import random
import sys

import pygame
from pygame.locals import *  # noqa: F401,F403

from game import (World, NEUTRAL_INPUT, ROUNDS_TO_WIN, FPS, W, H,
                  draw_world, draw_match_overlay, _draw_hp, _draw_scoreboard, _draw_wind)
from bot import solve_shot
import effects

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

CPU_MIN, CPU_MAX = 330, 470     # frames between CPU shots (~5.5-7.8s); higher = easier


def _fire(world, i, target_i, scatter, weapon):
    """Auto-aim and launch a shell from tank i at tank target_i."""
    me, tgt = world.tanks[i], world.tanks[target_i]
    angle, power, wep = solve_shot(world, me, tgt, scatter=scatter, weapon=weapon)
    me.angle, me.weapon, me.charge = angle, wep, power
    world._launch(i)


def _draw_cpu_loading(screen, small, timer, interval):
    x, y, w, h = W - 216, 58, 200, 10
    frac = max(0.0, min(1.0, 1 - timer / interval))
    pygame.draw.rect(screen, (40, 40, 52), (x, y, w, h), border_radius=4)
    pygame.draw.rect(screen, (230, 150, 90), (x, y, int(w * frac), h), border_radius=4)
    lbl = small.render("CPU loading", True, (205, 175, 150))
    screen.blit(lbl, (x + w - lbl.get_width(), y - 17))


def _draw_typing_panel(screen, fonts, type_font, cw, target, pos, wpm, shells):
    small, _font, _big = fonts
    panel = pygame.Rect(40, H - 120, W - 80, 100)
    surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    surf.fill((12, 14, 24, 205))
    screen.blit(surf, (panel.x, panel.y))
    pygame.draw.rect(screen, (92, 112, 152), panel, 1, border_radius=8)

    lbl = small.render("TYPE TO FIRE", True, (182, 202, 232))
    screen.blit(lbl, (W // 2 - lbl.get_width() // 2, panel.y + 8))

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

    stats = small.render(f"WPM {wpm}     Shells fired {shells}     ESC: menu", True, (178, 188, 208))
    screen.blit(stats, (W // 2 - stats.get_width() // 2, panel.y + 74))


def run_typing(screen, clock, fonts):
    small, font, big = fonts
    type_font = pygame.font.SysFont("consolas", 30, bold=True)
    cw = type_font.size("X")[0]

    def new_world():
        s = random.randrange(1, 1_000_000)
        w = World(s)
        w.tanks[1].name = "CPU"
        return s, w

    seed, world = new_world()
    fx = effects.FX()
    target = random.choice(SENTENCES)
    pos = 0
    shells = total_chars = 0
    start_ticks = pygame.time.get_ticks()
    cpu_interval = random.randint(CPU_MIN, CPU_MAX)
    cpu_timer = cpu_interval

    scores = [0, 0]
    rnd = 1
    mphase = "playing"
    round_winner = None
    rtimer = 0

    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                pygame.quit()
                sys.exit()
            elif e.type == KEYDOWN:
                if e.key == K_ESCAPE:
                    return
                if mphase == "match_over" and e.key == K_RETURN:
                    return
                if mphase == "playing":
                    if e.key == K_BACKSPACE:
                        pos = max(0, pos - 1)
                    elif e.key not in (K_RETURN, K_TAB):
                        ch = e.unicode
                        if ch and len(ch) == 1 and ch.isprintable():
                            if pos < len(target) and ch == target[pos]:
                                pos += 1
                                total_chars += 1
                                if pos >= len(target):       # sentence done -> fire!
                                    _fire(world, 0, 1, scatter=8.0, weapon=0)
                                    shells += 1
                                    target = random.choice(SENTENCES)
                                    pos = 0

        if mphase == "playing":
            cpu_timer -= 1
            if cpu_timer <= 0:
                if world.phase == "playing" and world.tanks[1].hp > 0:
                    _fire(world, 1, 0, scatter=38.0, weapon=None)
                cpu_interval = random.randint(CPU_MIN, CPU_MAX)
                cpu_timer = cpu_interval
            world.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
            if world.phase == "over":
                round_winner = world.winner
                if round_winner is not None:
                    scores[round_winner] += 1
                mphase = "match_over" if max(scores) >= ROUNDS_TO_WIN else "round_over"
                rtimer = int(FPS * 2.6)
        else:
            world.step([NEUTRAL_INPUT, NEUTRAL_INPUT])
            if mphase == "round_over":
                rtimer -= 1
                if rtimer <= 0:
                    rnd += 1
                    seed, world = new_world()
                    fx = effects.FX()
                    target = random.choice(SENTENCES)
                    pos = 0
                    cpu_interval = random.randint(CPU_MIN, CPU_MAX)
                    cpu_timer = cpu_interval
                    mphase = "playing"
                    round_winner = None

        snap = world.snapshot()
        snap.update({"scores": scores, "round": rnd, "seed": seed,
                     "needed": ROUNDS_TO_WIN, "match_phase": mphase,
                     "round_winner": round_winner})
        fx.observe(snap, 0)
        fx.update()

        draw_world(screen, world.terrain, snap, fx)
        _draw_hp(screen, font, snap["tanks"][0], 16, 14)
        _draw_hp(screen, font, snap["tanks"][1], W - 16, 14, right=True)
        _draw_wind(screen, small, snap["wind"])
        _draw_scoreboard(screen, fonts, snap)
        if mphase == "playing":
            _draw_cpu_loading(screen, small, cpu_timer, cpu_interval)
            elapsed_min = max(1e-6, (pygame.time.get_ticks() - start_ticks) / 60000.0)
            wpm = int((total_chars / 5) / elapsed_min)
            _draw_typing_panel(screen, fonts, type_font, cw, target, pos, wpm, shells)
        draw_match_overlay(screen, fonts, snap)
        pygame.display.flip()
        clock.tick(FPS)
