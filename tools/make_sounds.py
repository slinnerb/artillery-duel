"""Generates the game's sound effects as real .wav files in assets/sounds/.

Run once (or whenever you want to retune the sounds):  py tools/make_sounds.py
Everything is synthesized with numpy + the stdlib wave module -- no external
sound libraries, no copyrighted audio. The .wav files are committed and bundled
into the .exe; swap in nicer audio later by replacing the files.
"""
import os
import wave

import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sounds")


def _write(name, samples):
    samples = np.asarray(samples, dtype=np.float32)
    peak = np.max(np.abs(samples)) or 1.0
    samples = (samples / peak) * 0.92
    pcm = (samples * 32767).astype("<i2")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("wrote", path, f"({len(samples)/SR:.2f}s)")


def _t(dur):
    return np.linspace(0, dur, int(SR * dur), endpoint=False)


def _noise(n):
    return np.random.uniform(-1, 1, n)


def fire():
    t = _t(0.38)
    env = np.exp(-t * 13)
    body = np.sin(2 * np.pi * 72 * t) * env                       # low thump
    body += 0.6 * np.sin(2 * np.pi * 120 * t) * np.exp(-t * 22)   # mid punch
    crack = _noise(len(t)) * np.exp(-t * 38) * 0.7                # attack crack
    return body + crack


def explosion():
    t = _t(0.85)
    rumble = np.sin(2 * np.pi * (48 - 20 * t) * t) * np.exp(-t * 4.5)  # falling sub
    boom = _noise(len(t)) * np.exp(-t * 6) * 0.9
    # cheap low-pass on the noise so it's a boom, not a hiss
    boom = np.convolve(boom, np.ones(40) / 40, mode="same")
    tail = _noise(len(t)) * np.exp(-t * 2.2) * 0.25
    return rumble + boom + tail


def charge():
    t = _t(1.05)
    f = 150 + 520 * (t / t[-1]) ** 1.4                  # rising pitch
    vib = 1 + 0.02 * np.sin(2 * np.pi * 6 * t)
    swell = np.clip(t / 0.15, 0, 1) * (0.5 + 0.5 * t / t[-1])
    tone = np.sin(2 * np.pi * f * t * vib) * swell
    tone += 0.3 * np.sin(4 * np.pi * f * t) * swell      # a little buzz
    return tone


def hit():
    t = _t(0.2)
    env = np.exp(-t * 26)
    clank = sum(np.sin(2 * np.pi * fq * t) for fq in (900, 1500, 2300)) * env
    tick = _noise(len(t)) * np.exp(-t * 80) * 0.6
    return clank + tick


def win():
    notes = [523.25, 659.25, 783.99, 1046.5]            # C major arpeggio
    out = np.zeros(int(SR * 0.92))
    for i, fq in enumerate(notes):
        start = int(SR * 0.16 * i)
        t = _t(0.5)
        env = np.clip(t / 0.02, 0, 1) * np.exp(-t * 4.5)
        note = (np.sin(2 * np.pi * fq * t) + 0.4 * np.sin(4 * np.pi * fq * t)) * env
        end = min(start + len(note), len(out))
        out[start:end] += note[: end - start]
    return out


if __name__ == "__main__":
    np.random.seed(7)  # reproducible noise so the committed files are stable
    _write("fire.wav", fire())
    _write("explosion.wav", explosion())
    _write("charge.wav", charge())
    _write("hit.wav", hit())
    _write("win.wav", win())
    print("done.")
