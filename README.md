# Artillery Duel

A tiny real-time 1v1 artillery game for Windows. You and a friend connect over
the internet and lob shells at each other. One of you hosts, the other joins.
There's a **Check for Updates** button so when you ship a new version, your
friend just clicks it and gets the latest build automatically.

```
  Blue                                                   Red
   __                                                    __
  /  \___                          WIND ->              /  \___
 [tank ]\_____           .  *  .              ________/[tank ]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

## Controls

| Action | Keys |
| --- | --- |
| Move left / right | `A` / `D` or `←` / `→` |
| Aim barrel up / down | `W` / `S` or `↑` / `↓` |
| Charge & fire | Hold `SPACE` to build power, release to shoot |
| Switch weapon | `1` Shell · `2` Big Bomb · `3` Cluster · `4` Bouncer |
| Reload (type for shells) | `TAB` |
| Back to menu | `ESC` |

Watch the **wind** arrow at the top — it pushes your shells sideways. After
each shot there's a short reload before you can fire again.

**The battlefield scrolls.** It's wider than the screen, and the camera follows
your tank — drive toward your opponent to get in range. When they're off-screen,
a coloured arrow at the screen edge points to them with the distance.

**Mind the lava.** A molten sea sits at the bottom, with chasms cut down into it.
Drive into one — or get blasted into a deep crater — and you're dead. Use it: a
well-placed shell can drop a tank straight into the lava.

**The basic Shell is unlimited — special weapons aren't.** You can always fire
the `1` Shell (marked `∞`). Big Bomb, Cluster, and Bouncer each cost a **special
shell** (the pips bottom-left). You start a round with a few; to get more, hit
`TAB` to drop into reload mode and **type the sentences** — each one you finish
loads a special shell — then `TAB` back to fight. Pick a special with none left
and the game points you to `1` (the Shell) or `TAB` to reload. Reload while
you're safe; stopping to type leaves you a sitting duck.

**Backgrounds.** Drop image files into `assets/backgrounds/` and the game
randomly uses one as the backdrop in about 1 in 3 matches (see that folder's
README). Empty folder → the normal painted sky.

---

## Run it from source (during development)

You need Python 3.10+.

```powershell
cd C:\NewGameForCricket
pip install -r requirements.txt
python main.py
```

---

## Playing together over the internet (Tailscale)

Forwarding ports on a router is a pain, so we skip it. **Tailscale** makes both
PCs act like they're on the same home network.

1. Both of you install Tailscale: https://tailscale.com/download  (free)
2. Both sign in (you can use the same account, or share your network — either
   works for a 2-person game).
3. Find each PC's Tailscale IP — it starts with `100.` (Tailscale app → it's
   shown next to your machine, or run `tailscale ip -4`).
4. **Host:** open the game → **Host Game**. It shows the address to send and a
   **Copy** button (or press `C`); paste it to your friend in any chat.
5. **Joiner:** open the game → **Join Game** → paste the address with **Ctrl+V**
   (or type the host's `100.x.y.z` IP) → Enter.

That's it — you're in the same match. (On a real LAN you can skip Tailscale and
just use the `192.168.x.x` address instead.)

The game uses TCP port **50713**.

---

## Building what you ship

Your friend shouldn't need Python. There are two artifacts:

1. **`dist\ArtilleryDuel.exe`** — the raw game binary. This is what the in-game
   updater downloads to self-update.
2. **`dist\ArtilleryDuel-Setup.exe`** — the installer. This is what a *new*
   player downloads. It installs the game and offers to install Tailscale too,
   so your friend does zero manual networking setup.

```powershell
pip install -r requirements.txt pyinstaller
.\build.bat                 # -> dist\ArtilleryDuel.exe
.\build_installer.bat       # -> dist\ArtilleryDuel-Setup.exe (needs the exe above first)
```

**Why the installer puts the game in `%LocalAppData%`, not Program Files:** the
auto-updater replaces the `.exe` in place, which needs a user-writable folder.
Program Files would force an admin prompt on every update. Tailscale *does* need
admin, so the installer runs Tailscale's own installer, which shows a single
Windows permission prompt. After it's installed, your friend signs into
Tailscale once (it needs an account) and you're set.

---

## Shipping updates (the "Check for Updates" button)

The updater pulls the newest build from **GitHub Releases**. One-time setup,
then every update is three commands.

### One-time setup
1. Create a **public** GitHub repo and push this code to it.
2. Open `updater.py` and set:
   ```python
   GITHUB_OWNER = "your-github-username"
   GITHUB_REPO  = "your-repo-name"
   ```
3. Build once (`.\build.bat`) and send `dist\ArtilleryDuel.exe` to your friend
   as the starting version.

### Every time you want to push an update
1. Make your changes (new weapon, balance tweak, whatever).
2. Bump the version in `version.py`, e.g. `__version__ = "1.0.1"`.
3. Build: `.\build.bat`
4. On GitHub: **Releases → Draft a new release**
   - Tag: `v1.0.1`  (must match version.py, with a leading `v`)
   - Attach `dist\ArtilleryDuel.exe` as a release asset.
   - Publish.

Now anyone running the game clicks **Check for Updates**, it sees `v1.0.1` is
newer than what they have, downloads the new `.exe`, swaps it in, and restarts
on the new version. (Updates only auto-install in the built `.exe`; from source
it just tells you a newer release exists.)

> The version comparison is numeric per segment, so `1.0.10` > `1.0.9`. Always
> bump the number going forward.

---

## How it's wired (for when you want to extend it)

| File | Does |
| --- | --- |
| `main.py` | Menu, match loops, and the update UI flow |
| `game.py` | The `World` simulation + all rendering (one draw path) |
| `netcode.py` | Host (`Server`) / joiner (`Client`) over TCP |
| `updater.py` | Check GitHub, download, swap the exe, relaunch |
| `version.py` | The current version number |

**Netcode model:** the host runs the only real simulation and sends the client
a snapshot every frame; the client just sends its key presses and draws what it
receives. Simple and impossible to desync. The trade-off is the joiner sees a
few milliseconds of input lag — unnoticeable over Tailscale for a casual game.

## Shipped
- **v1.0.8 — Unlimited Shell, firewall on install, drop-in backgrounds.** The
  basic `1` Shell is now unlimited (marked `∞`); only the special weapons (Big
  Bomb / Cluster / Bouncer) cost a typed-reload shell, so you're never stuck
  unable to fire — there's always a fallback. The installer now opens Windows
  Firewall for the game (TCP 50713) via a self-elevating helper, so a friend can
  connect without you hand-adding a rule. And any image dropped in
  `assets/backgrounds/` becomes a random match backdrop (~1 in 3 games); the
  choice rides along in the snapshot so host and client see the same one.
- **v1.0.7 — Scrolling battlefield, lava & typed reloads.** The arena is now
  wider than the screen and the camera follows your tank (drive toward the enemy
  to get in range; an edge arrow points to them when they're off-screen). A lava
  sea with chasms runs along the bottom — fall in, or get blasted into a deep
  crater, and you die. Shells are now limited: you start each round with a few and
  reload by pressing `TAB` and **typing sentences** (each one = one shell), then
  `TAB` back to the fight. Run dry and you're forced to type. Works in Host, Join,
  and Practice; the reload counter syncs over the network the same idempotent way
  craters do. (Typing Duel is unchanged — there typing already *is* the trigger.)
- **v1.0.6 — One-click address sharing.** The Host screen now shows the single
  best address to send (your Tailscale `100.` IP, found via the Tailscale CLI so
  it's never missed) with a **Copy** button (or press `C`). The Join screen takes
  a paste with **Ctrl+V**, so your friend pastes exactly what you sent instead of
  hand-typing an IP — no more typos causing "socket error". Failed connections now
  explain the usual causes (wrong address, not on Tailscale, host firewall).
- **v1.0.5 — Typing Duel.** A solo mode where typing is your trigger: a sentence
  appears, and each one you finish correctly auto-fires a shell at the CPU (it
  aims for you, since your hands are on the keyboard). Out-type the CPU's reload
  to win. Live WPM + shells-fired counter, best-of-5.
- **v1.0.4 — Practice mode.** A "Practice vs CPU" option on the menu drops you
  into a best-of-5 match against an AI that aims for real — it simulates shots
  against the current wind and terrain to find a firing solution. Great for
  learning the weapons, or playing when your friend is offline.
- **v1.0.3 — Weapons & rounds.** Pick a weapon with `1`–`4` — Shell, Big Bomb
  (huge blast), Cluster (airbursts into 5 submunitions), or Bouncer (skips along
  the terrain). Matches are now best-of-5 with a live scoreboard, and every
  round gets a fresh battlefield.
- **v1.0.2 — Sound & visuals (game-feel pass).** Real bundled assets: sprite
  tanks with rotating barrels, textured destructible ground, a dawn sky with
  parallax hills, particle explosions, screen shake, and sound effects
  (fire / charge / explosion / hit / win). Assets live in `assets/`, authored by
  `tools/make_sounds.py` and `tools/make_sprites.py`, and are bundled inside the
  `.exe`. Want nicer art? Just replace the matching file in `assets/` and rebuild.
- **v1.0.1 — Destructible terrain.** Shells blow craters in the ground and
  tanks settle into them. The host carves the terrain and sends a crater log so
  the client reproduces identical damage.

## Ideas for future updates (great excuses to use the update button)
- Client-side prediction so the joiner's own aim feels instant
- Hand-drawn art dropped into `assets/` to replace the code-generated sprites
- A map/terrain-style picker, or power-ups that drop into the arena
