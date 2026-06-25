Drop-in match backgrounds
=========================

Any image you put in this folder (.png .jpg .jpeg .webp .bmp) becomes a possible
full-screen backdrop. The game randomly uses one in roughly 1 in 3 matches
(across Host, Join, Practice, and Typing Duel); the rest use the painted sky.
Each image is auto-scaled to cover the screen (1000x600), so any size works —
landscape shots look best.

- Add as many as you like; one is picked at random per match.
- Remove them all and the game just uses its normal sky again.
- These are bundled into the .exe at build time, so rebuild (build.bat /
  build_installer.bat) after adding art if you're shipping to a friend.

To tune how often a backdrop appears, change the `chance=` default in
resources.random_background() (0.0 = never, 1.0 = every match).
