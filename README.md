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
| Back to menu | `ESC` |

Watch the **wind** arrow at the top — it pushes your shells sideways. After
each shot there's a short reload before you can fire again.

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
4. **Host:** open the game → **Host Game**. It shows your addresses; the one
   starting with `100.` is your Tailscale IP.
5. **Joiner:** open the game → **Join Game** → type the host's `100.x.y.z` IP →
   Enter.

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
- **v1.0.1 — Destructible terrain.** Shells blow craters in the ground and
  tanks settle into them. The host carves the terrain and sends a crater log so
  the client reproduces identical damage.

## Ideas for future updates (great excuses to use the update button)
- New weapons (cluster shell, big bomb, bouncing shot) — pick a weapon before firing
- Best-of-5 rounds and a score counter
- Sound effects and an explosion particle burst
- Client-side prediction so the joiner's own aim feels instant
