#!/usr/bin/env python3
"""Generates Vigilia's pool of alarm sounds.

Every sound is synthesized from scratch (no samples, no third-party audio), so the
whole pool is license-free and reproducible: the same script always produces the
same files. Each sound has its own rhythm, timbre and pitch so that the alarm you
hear today is never the one you heard yesterday.

Only the Python standard library is used. Output: one 16-bit mono WAV per sound
plus Sounds.json (file name + Spanish title). build.sh converts the WAVs to CAF
(IMA4) with afconvert and copies everything into the app bundle.

AlarmKit ignores custom sounds of 30 seconds or more, so every sound lasts 28 s.
"""

import argparse
import array
import bisect
import json
import math
import os
import random
import sys
import wave

SR = 22050
DURATION = 28.0
TABLE_SIZE = 4096
MASK = TABLE_SIZE - 1
TWO_PI = 2.0 * math.pi

_tables = {}
_notes = {}


def table(kind, harmonics_limit):
    key = (kind, harmonics_limit)
    cached = _tables.get(key)
    if cached is not None:
        return cached
    n = max(1, harmonics_limit)
    if kind == "sine":
        partials = [(1, 1.0)]
    elif kind == "square":
        partials = [(k, 1.0 / k) for k in range(1, n + 1, 2)]
    elif kind == "saw":
        partials = [(k, 1.0 / k) for k in range(1, n + 1)]
    elif kind == "triangle":
        partials = [(k, (-1.0) ** ((k - 1) // 2) / (k * k)) for k in range(1, n + 1, 2)]
    elif kind == "pulse":
        partials = [(k, math.sin(math.pi * k * 0.25) / k) for k in range(1, n + 1)]
    elif kind == "organ":
        partials = [(k, a) for k, a in ((1, 1.0), (2, 0.7), (3, 0.5), (4, 0.35), (6, 0.25), (8, 0.18)) if k <= n]
    elif kind == "reed":
        partials = [(k, 1.0 / (k ** 0.7)) for k in range(1, n + 1) if k % 4 != 0]
    elif kind == "glass":
        partials = [(k, a) for k, a in ((1, 1.0), (2, 0.25), (3, 0.5), (5, 0.18)) if k <= n]
    else:
        raise ValueError(kind)
    values = [0.0] * TABLE_SIZE
    for i in range(TABLE_SIZE):
        x = TWO_PI * i / TABLE_SIZE
        values[i] = sum(a * math.sin(k * x) for k, a in partials)
    peak = max(abs(v) for v in values) or 1.0
    values = [v / peak for v in values]
    _tables[key] = values
    return values


def note(kind, f0, f1=None, dur=0.2, attack=0.004, release=0.02, decay=None,
         vib_rate=0.0, vib_depth=0.0, fm_ratio=0.0, fm_index=0.0, fm_decay=None,
         lowpass=None, seed=0):
    """Renders (and caches) a single note as a list of floats in [-1, 1]."""
    if f1 is None:
        f1 = f0
    key = (kind, round(f0, 3), round(f1, 3), round(dur, 4), attack, release, decay,
           vib_rate, vib_depth, fm_ratio, fm_index, fm_decay, lowpass, seed)
    cached = _notes.get(key)
    if cached is not None:
        return cached

    n = max(1, int(dur * SR))
    out = [0.0] * n
    sine = table("sine", 1)
    attack_n = max(1, int(attack * SR))
    release_n = max(1, int(release * SR))
    decay_mult = math.exp(-1.0 / (decay * SR)) if decay else 1.0
    glide = (f1 / f0) ** (1.0 / max(1, n - 1)) if f1 != f0 else 1.0

    if kind == "noise":
        rng = random.Random(seed)
        low = 0.0
        alpha = 1.0 - math.exp(-TWO_PI * (lowpass or 6000.0) / SR)
        level = 1.0
        for i in range(n):
            low += alpha * (rng.uniform(-1.0, 1.0) - low)
            env = i / attack_n if i < attack_n else 1.0
            if i > n - release_n:
                env *= (n - i) / release_n
            out[i] = low * env * level
            level *= decay_mult
    elif kind == "fm":
        carrier_phase = 0.0
        mod_phase = 0.0
        inc = f0 * TABLE_SIZE / SR
        index = fm_index * TABLE_SIZE / TWO_PI
        index_mult = math.exp(-1.0 / (fm_decay * SR)) if fm_decay else 1.0
        level = 1.0
        for i in range(n):
            modulator = sine[int(mod_phase) & MASK]
            value = sine[int(carrier_phase + index * modulator) & MASK]
            env = i / attack_n if i < attack_n else 1.0
            if i > n - release_n:
                env *= (n - i) / release_n
            out[i] = value * env * level
            carrier_phase += inc
            mod_phase += inc * fm_ratio
            inc *= glide
            index *= index_mult
            level *= decay_mult
    else:
        top = max(f0, f1) * (1.0 + vib_depth)
        harmonics = max(1, min(48, int(SR * 0.45 / top)))
        wave_table = table(kind, harmonics)
        phase = 0.0
        inc = f0 * TABLE_SIZE / SR
        lfo_phase = 0.0
        lfo_inc = vib_rate * TABLE_SIZE / SR
        level = 1.0
        if vib_depth:
            for i in range(n):
                env = i / attack_n if i < attack_n else 1.0
                if i > n - release_n:
                    env *= (n - i) / release_n
                out[i] = wave_table[int(phase) & MASK] * env * level
                phase += inc * (1.0 + vib_depth * sine[int(lfo_phase) & MASK])
                lfo_phase += lfo_inc
                inc *= glide
                level *= decay_mult
        else:
            for i in range(n):
                env = i / attack_n if i < attack_n else 1.0
                if i > n - release_n:
                    env *= (n - i) / release_n
                out[i] = wave_table[int(phase) & MASK] * env * level
                phase += inc
                inc *= glide
                level *= decay_mult

    _notes[key] = out
    return out


class Mix:
    def __init__(self):
        self.length = int(DURATION * SR)
        self.buffer = [0.0] * self.length

    def add(self, time, samples, gain=1.0):
        start = int(time * SR)
        if start >= self.length or start < 0:
            return
        end = min(self.length, start + len(samples))
        segment = self.buffer[start:end]
        self.buffer[start:end] = [a + gain * b for a, b in zip(segment, samples)]

    def finish(self):
        buf = self.buffer
        peak = max(abs(v) for v in buf) or 1.0
        rms = math.sqrt(sum(v * v for v in buf) / len(buf)) / peak
        # Sparse or percussive sounds get pushed harder into the soft clipper so
        # that every sound in the pool is roughly as loud as the others.
        target = 10 ** (-10.0 / 20)
        drive = 1.5 * min(2.5, max(1.0, target / max(rms, 1e-6)))
        norm = 0.93 / math.tanh(drive)
        scale = drive / peak
        buf = [math.tanh(v * scale) * norm for v in buf]
        # Starts a bit softer and reaches full level after 2.5 s.
        ramp = int(2.5 * SR)
        for i in range(min(ramp, len(buf))):
            x = i / ramp
            buf[i] *= 0.55 + 0.45 * x * x * (3.0 - 2.0 * x)
        fade = int(0.04 * SR)
        for i in range(fade):
            buf[-1 - i] *= i / fade
        return buf


def midi(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "whole": [0, 2, 4, 6, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "blues": [0, 3, 5, 6, 7, 10],
    "hirajoshi": [0, 2, 3, 7, 8],
    "insen": [0, 1, 5, 7, 10],
}


def scale_note(root, scale, degree):
    steps = SCALES[scale]
    octave, index = divmod(degree, len(steps))
    return midi(root + 12 * octave + steps[index])


# --- Patterns -----------------------------------------------------------------
# Every pattern receives its own seeded Random so that two sounds sharing a
# pattern still differ in pitch, rhythm and timbre.


def p_beeps(r, mix, wave_kind="square", pitch=(1800, 3000), group=(2, 5)):
    f = r.uniform(*pitch)
    count = r.randint(*group)
    beep = r.uniform(0.06, 0.13)
    gap = beep * r.uniform(0.5, 1.0)
    pause = r.uniform(0.3, 0.7)
    tone = note(wave_kind, f, dur=beep, attack=0.003, release=0.01)
    t = 0.0
    while t < DURATION:
        for _ in range(count):
            mix.add(t, tone)
            t += beep + gap
        t += pause


def p_siren(r, mix, wave_kind="saw", fast=False):
    low = r.uniform(500, 750)
    high = low * r.uniform(1.8, 2.6)
    period = r.uniform(0.18, 0.32) if fast else r.uniform(1.6, 2.6)
    t = 0.0
    while t < DURATION:
        up = note(wave_kind, low, high, dur=period * 0.55, attack=0.01, release=0.005)
        down = note(wave_kind, high, low, dur=period * 0.45, attack=0.005, release=0.01)
        mix.add(t, up, 0.8)
        mix.add(t + period * 0.55, down, 0.8)
        t += period


def p_hilo(r, mix, wave_kind="square"):
    a = r.uniform(420, 620)
    b = a * r.choice([1.26, 1.335, 1.5])
    length = r.uniform(0.35, 0.65)
    ta = note(wave_kind, a, dur=length, attack=0.01, release=0.01)
    tb = note(wave_kind, b, dur=length, attack=0.01, release=0.01)
    t = 0.0
    while t < DURATION:
        mix.add(t, tb, 0.8)
        mix.add(t + length, ta, 0.8)
        t += 2 * length


def p_trill(r, mix, kind="square", hammer=False):
    a = r.uniform(700, 1100) if not hammer else r.uniform(1400, 2200)
    b = a * r.uniform(1.12, 1.3)
    speed = r.uniform(0.022, 0.035) if not hammer else r.uniform(0.03, 0.045)
    burst = r.uniform(0.9, 1.6)
    silence = r.uniform(0.4, 1.0)
    if hammer:
        ta = note("fm", a, dur=speed * 3, decay=0.04, fm_ratio=2.76, fm_index=4.0, fm_decay=0.03)
        tb = note("fm", b, dur=speed * 3, decay=0.04, fm_ratio=3.1, fm_index=3.0, fm_decay=0.03)
    else:
        ta = note(kind, a, dur=speed, attack=0.002, release=0.004)
        tb = note(kind, b, dur=speed, attack=0.002, release=0.004)
    t = 0.0
    while t < DURATION:
        end = t + burst
        flip = False
        while t < end:
            mix.add(t, tb if flip else ta, 0.7)
            flip = not flip
            t += speed
        t += silence


def p_digital(r, mix):
    f = r.uniform(3200, 4200)
    beep = r.uniform(0.045, 0.07)
    tone = note("square", f, dur=beep, attack=0.002, release=0.006)
    pattern = r.choice([[0, 1], [0, 1, 2, 3], [0, 1, 3, 4]])
    step = beep * r.uniform(1.6, 2.2)
    cycle = r.uniform(0.75, 1.1)
    t = 0.0
    while t < DURATION:
        for p in pattern:
            mix.add(t + p * step, tone, 0.6)
        t += cycle


def p_arpeggio(r, mix, timbre="fm", scale="major"):
    root = r.randint(64, 72)
    progression = [[0, 2, 4, 7], [3, 5, 7, 10], [4, 6, 8, 11], [1, 3, 5, 8]]
    r.shuffle(progression)
    step = r.uniform(0.11, 0.17)
    t = 0.0
    bar = 0
    while t < DURATION:
        chord = progression[bar % len(progression)]
        shape = chord + chord[-2:0:-1]
        for degree in shape:
            f = scale_note(root, scale, degree)
            if timbre == "fm":
                tone = note("fm", f, dur=0.6, decay=0.18, fm_ratio=3.5, fm_index=2.5, fm_decay=0.12)
            else:
                tone = note("saw", f, dur=0.35, attack=0.002, release=0.05, decay=0.09)
            mix.add(t, tone, 0.55)
            t += step
        bar += 1


def p_melody(r, mix, timbre="marimba", scale="pentatonic", fast=True):
    root = r.randint(60, 70)
    step = r.uniform(0.09, 0.13) if fast else r.uniform(0.18, 0.26)
    motif = [r.randint(0, 9) for _ in range(r.randint(6, 9))]
    t = 0.0
    repeat = 0
    while t < DURATION:
        notes = motif if repeat % 3 != 2 else [d + r.randint(-2, 3) for d in motif]
        for degree in notes:
            f = scale_note(root, scale, max(0, degree))
            if timbre == "marimba":
                tone = note("fm", f, dur=0.35, decay=0.07, fm_ratio=4.0, fm_index=1.6, fm_decay=0.03)
            elif timbre == "musicbox":
                tone = note("glass", f * 2, dur=0.8, attack=0.002, release=0.05, decay=0.25)
            else:
                tone = note("triangle", f, dur=0.3, attack=0.003, release=0.04, decay=0.1)
            mix.add(t, tone, 0.6)
            t += step
        t += step * r.choice([1, 2, 3])
        repeat += 1


def p_chirps(r, mix):
    t = 0.0
    while t < DURATION:
        count = r.randint(2, 5)
        base = r.uniform(1800, 2600)
        for _ in range(count):
            length = r.uniform(0.05, 0.09)
            tone = note("sine", base, base * r.uniform(1.4, 1.9), dur=length, attack=0.004, release=0.015)
            mix.add(t, tone, 0.9)
            t += length + r.uniform(0.02, 0.05)
        t += r.uniform(0.25, 0.6)


def p_sonar(r, mix):
    f = r.uniform(900, 1400)
    ping = note("sine", f, f * 0.97, dur=1.4, attack=0.003, release=0.05, decay=0.35)
    period = r.uniform(1.2, 1.7)
    t = 0.0
    while t < DURATION:
        mix.add(t, ping, 1.0)
        mix.add(t + 0.32, ping, 0.35)
        mix.add(t + 0.64, ping, 0.15)
        t += period


def p_accelerating(r, mix):
    f = r.uniform(1300, 2000)
    t = 0.0
    interval = 0.6
    while t < DURATION:
        rise = 1.0 + 0.6 * (t / DURATION)
        tone = note("pulse", f * rise, dur=0.07, attack=0.002, release=0.01)
        mix.add(t, tone, 0.7)
        t += interval
        interval = max(0.08, interval * 0.93)
        if interval <= 0.08 and r.random() < 0.06:
            t += 0.6
            interval = 0.6


MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
}


def p_morse(r, mix, message="DESPIERTA"):
    f = r.uniform(700, 900)
    unit = r.uniform(0.06, 0.075)
    dot = note("sine", f, dur=unit, attack=0.004, release=0.006)
    dash = note("sine", f, dur=unit * 3, attack=0.004, release=0.006)
    t = 0.0
    while t < DURATION:
        for word in message.split():
            for letter in word:
                for symbol in MORSE[letter]:
                    mix.add(t, dot if symbol == "." else dash)
                    t += unit * (1 if symbol == "." else 3) + unit
                t += unit * 2
            t += unit * 4
        t += unit * 7


def p_klaxon(r, mix, low=False):
    f = r.uniform(180, 260) if low else r.uniform(320, 420)
    length = r.uniform(0.35, 0.6)
    a = note("square", f, dur=length, attack=0.01, release=0.02)
    b = note("saw", f * 1.012, dur=length, attack=0.01, release=0.02)
    gap = r.uniform(0.15, 0.3)
    t = 0.0
    while t < DURATION:
        mix.add(t, a, 0.6)
        mix.add(t, b, 0.5)
        t += length + gap


def p_fanfare(r, mix):
    root = r.randint(55, 62)
    t = 0.0
    while t < DURATION:
        for interval, length in ((0, 0.16), (4, 0.16), (7, 0.16), (12, 0.5)):
            tone = note("reed", midi(root + interval), dur=length, attack=0.02, release=0.04, vib_rate=5.5, vib_depth=0.006)
            mix.add(t, tone, 0.7)
            t += length + 0.03
        t += 0.35
        root += r.choice([0, 2, 5, 7]) if root < 66 else -7


def p_laser(r, mix):
    t = 0.0
    while t < DURATION:
        top = r.uniform(2500, 4000)
        length = r.uniform(0.12, 0.25)
        tone = note("square", top, top * r.uniform(0.15, 0.3), dur=length, attack=0.002, release=0.02)
        mix.add(t, tone, 0.6)
        t += length + r.uniform(0.05, 0.35)


def p_drums(r, mix):
    bpm = r.uniform(120, 150)
    beat = 60.0 / bpm / 2
    kick = note("sine", 140, 45, dur=0.25, attack=0.002, release=0.03, decay=0.12)
    snare = note("noise", 1, dur=0.18, attack=0.001, release=0.02, decay=0.06, lowpass=7000, seed=1)
    hat = note("noise", 1, dur=0.05, attack=0.001, release=0.01, decay=0.015, lowpass=10000, seed=2)
    gong = note("fm", r.uniform(180, 240), dur=2.5, decay=0.8, fm_ratio=1.41, fm_index=3.0, fm_decay=0.9)
    pattern = r.choice(["K.H.S.H.K.KHS.H.", "K.HKS.H.K.H.S.HH", "KKH.S.H.K.HKS.H."])
    t = 0.0
    step = 0
    while t < DURATION:
        symbol = pattern[step % len(pattern)]
        if symbol == "K":
            mix.add(t, kick, 1.0)
        elif symbol == "S":
            mix.add(t, snare, 0.7)
        if symbol == "H" or step % 2 == 0:
            mix.add(t, hat, 0.3)
        if step % 32 == 0:
            mix.add(t, gong, 0.6)
        t += beat
        step += 1


def p_cricket(r, mix):
    f = r.uniform(4000, 4800)
    pulse = note("sine", f, dur=0.018, attack=0.002, release=0.006)
    t = 0.0
    while t < DURATION:
        for _ in range(r.randint(3, 5)):
            mix.add(t, pulse, 0.9)
            t += 0.03
        t += r.uniform(0.18, 0.45)


def p_organ(r, mix):
    root = r.randint(52, 58)
    chords = [[0, 4, 7, 12], [5, 9, 12, 17], [7, 11, 14, 19], [9, 12, 16, 21]]
    t = 0.0
    while t < DURATION:
        for chord in chords:
            for _ in range(2):
                for interval in chord:
                    tone = note("organ", midi(root + interval), dur=0.32, attack=0.01, release=0.05)
                    mix.add(t, tone, 0.35)
                t += 0.42
        t += 0.3


def p_bounce(r, mix):
    f = r.uniform(1000, 1600)
    t = 0.0
    while t < DURATION:
        interval = r.uniform(0.45, 0.6)
        pitch = f
        while interval > 0.03 and t < DURATION:
            tone = note("triangle", pitch, dur=0.05, attack=0.002, release=0.015)
            mix.add(t, tone, 0.9)
            t += interval
            interval *= 0.78
            pitch *= 1.04
        t += 0.4


def p_scale_runs(r, mix):
    root = r.randint(60, 67)
    scale = r.choice(["major", "dorian", "whole"])
    step = r.uniform(0.07, 0.1)
    t = 0.0
    start = 0
    while t < DURATION:
        for degree in range(start, start + 10):
            tone = note("square", scale_note(root, scale, degree), dur=step * 0.9, attack=0.003, release=0.01)
            mix.add(t, tone, 0.45)
            t += step
        start = (start + 2) % 7
        t += step * 2


def p_robot(r, mix):
    t = 0.0
    while t < DURATION:
        for _ in range(r.randint(5, 12)):
            f = r.choice([300, 450, 600, 800, 1000, 1200]) * r.uniform(0.97, 1.03)
            length = r.choice([0.04, 0.06, 0.09])
            mix.add(t, note("pulse", round(f, 0), dur=length, attack=0.002, release=0.01), 0.6)
            t += length + 0.015
        t += r.uniform(0.2, 0.5)


def p_bells(r, mix):
    root = r.randint(50, 57)
    peal = [0, 7, 12, 4, 9, 16, 2, 14]
    r.shuffle(peal)
    t = 0.0
    while t < DURATION:
        for interval in peal:
            tone = note("fm", midi(root + interval), dur=2.4, decay=0.7, fm_ratio=1.4, fm_index=3.5, fm_decay=0.5)
            mix.add(t, tone, 0.5)
            t += r.choice([0.35, 0.35, 0.7])
        t += 0.5


def p_space_alert(r, mix):
    low = r.uniform(600, 800)
    t = 0.0
    while t < DURATION:
        mix.add(t, note("triangle", low, low * 2.2, dur=0.6, attack=0.01, release=0.02), 0.8)
        t += 0.65
        beep = note("square", low * 2.2, dur=0.08, attack=0.002, release=0.01)
        for _ in range(3):
            mix.add(t, beep, 0.5)
            t += 0.13
        t += 0.2


def p_teletype(r, mix):
    t = 0.0
    while t < DURATION:
        for _ in range(r.randint(10, 30)):
            f = r.uniform(1500, 3500)
            mix.add(t, note("square", round(f, -1), dur=0.012, attack=0.001, release=0.004), 0.5)
            t += r.choice([0.03, 0.045, 0.06])
        mix.add(t, note("sine", 2093.0, dur=0.25, attack=0.003, release=0.05), 0.6)
        t += r.uniform(0.3, 0.6)


def p_beep_storm(r, mix):
    t = 0.0
    while t < DURATION:
        density = 3 + int(14 * t / DURATION)
        for _ in range(density):
            f = r.choice([880, 1175, 1568, 2093, 2637, 3136]) * r.choice([1.0, 1.0, 0.5])
            length = r.uniform(0.05, 0.12)
            kind = r.choice(["sine", "square", "triangle"])
            mix.add(t + r.uniform(0, 0.5), note(kind, f, dur=round(length, 2), attack=0.003, release=0.01), 0.35)
        t += 0.5


# --- More building blocks -----------------------------------------------------
# Used by the second batch of sounds (31 onwards): pitch contours, struck and
# plucked tones, filters and filtered noise. The first 30 sounds don't use them.


def ramp(points, n):
    """Per-sample linear interpolation of [(time, value), ...], holding both ends."""
    out = [points[0][1]] * n
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        a, b = max(0, int(t0 * SR)), min(n, int(t1 * SR))
        if b > a:
            step = (v1 - v0) / (b - a)
            for i in range(a, b):
                out[i] = v0 + step * (i - a)
    for i in range(max(0, int(points[-1][0] * SR)), n):
        out[i] = points[-1][1]
    return out


def glide(kind, points, amp=None, vib_rate=0.0, vib_depth=0.0, attack=0.005, release=0.02, phase=0.0):
    """Renders (and caches) a tone whose pitch moves through [(time, hz), ...],
    exponentially between points. amp is an optional [(time, gain), ...] envelope."""
    points = tuple((round(t, 4), round(f, 3)) for t, f in points)
    amp = tuple((round(t, 4), round(g, 4)) for t, g in amp) if amp else None
    key = ("glide", kind, points, amp, vib_rate, vib_depth, attack, release, phase)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    n = max(1, int(points[-1][0] * SR))
    top = max(f for _, f in points) * (1.0 + vib_depth)
    wave_table = table(kind, max(1, min(48, int(SR * 0.45 / top))))
    sine = table("sine", 1)
    incs = [0.0] * n
    for (t0, f0), (t1, f1) in zip(points, points[1:]):
        a, b = int(t0 * SR), min(n, int(t1 * SR))
        if b > a:
            inc = f0 * TABLE_SIZE / SR
            mult = (f1 / f0) ** (1.0 / (b - a))
            for i in range(a, b):
                incs[i] = inc
                inc *= mult
    gains = ramp(amp, n) if amp else [1.0] * n
    attack_n = max(1, int(attack * SR))
    release_n = max(1, int(release * SR))
    for i in range(min(n, attack_n)):
        gains[i] *= i / attack_n
    for i in range(min(n, release_n)):
        gains[n - 1 - i] *= i / release_n
    out = [0.0] * n
    pos = phase * TABLE_SIZE
    if vib_depth:
        lfo = 0.0
        lfo_inc = vib_rate * TABLE_SIZE / SR
        for i in range(n):
            out[i] = wave_table[int(pos) & MASK] * gains[i]
            pos += incs[i] * (1.0 + vib_depth * sine[int(lfo) & MASK])
            lfo += lfo_inc
    else:
        for i in range(n):
            out[i] = wave_table[int(pos) & MASK] * gains[i]
            pos += incs[i]
    _notes[key] = out
    return out


def strike(f, partials, dur, attack=0.002):
    """Struck tone (cached): every (ratio, gain, decay) partial rings and dies away on its own."""
    key = ("strike", round(f, 3), partials, round(dur, 4), attack)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    n = max(1, int(dur * SR))
    out = [0.0] * n
    sine = table("sine", 1)
    for ratio, gain, decay in partials:
        if f * ratio >= SR * 0.45:
            continue
        inc = f * ratio * TABLE_SIZE / SR
        mult = math.exp(-1.0 / (decay * SR))
        level = gain
        pos = 0.0
        for i in range(min(n, int(decay * SR * 7))):
            out[i] += sine[int(pos) & MASK] * level
            pos += inc
            level *= mult
    attack_n = max(1, int(attack * SR))
    for i in range(min(n, attack_n)):
        out[i] *= i / attack_n
    fade = min(n, int(0.01 * SR))
    for i in range(fade):
        out[n - 1 - i] *= i / fade
    _notes[key] = out
    return out


def pluck(f, dur, t60=1.5, bright=0.7, seed=0):
    """Karplus-Strong plucked string (cached). t60: seconds to fade by 60 dB."""
    key = ("pluck", round(f, 3), round(dur, 4), t60, bright, seed)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    n = max(1, int(dur * SR))
    # Lighter averaging on high strings, which would otherwise die out at once.
    weight = 0.5 * min(1.0, (400.0 / f) ** 2)
    delay = SR / f - weight  # the averaging filter delays by `weight` samples
    size = max(2, int(delay - 0.1))
    coeff = (1.0 - (delay - size)) / (1.0 + (delay - size))  # all-pass for the fraction
    loss = min(0.99999, 0.001 ** (1.0 / (f * t60)))
    rng = random.Random(seed)
    line = [rng.uniform(-1.0, 1.0) for _ in range(size)]
    for _ in range(2):
        prev = line[-1]
        for i in range(size):
            prev += bright * (line[i] - prev)
            line[i] = prev
    mean = sum(line) / size
    peak = max(abs(v - mean) for v in line) or 1.0
    line = [(v - mean) / peak for v in line]
    out = [0.0] * n
    idx = 0
    last = ap_in = ap_out = 0.0
    for i in range(n):
        x = line[idx]
        out[i] = x
        y = loss * ((1.0 - weight) * x + weight * last)
        last = x
        ap_out = coeff * (y - ap_out) + ap_in
        ap_in = y
        line[idx] = ap_out
        idx += 1
        if idx == size:
            idx = 0
    fade = min(n, int(0.01 * SR))
    for i in range(fade):
        out[n - 1 - i] *= i / fade
    _notes[key] = out
    return out


def svf(samples, cutoff, q=0.707, mode="low"):
    """State-variable filter (zero-delay feedback). cutoff: Hz, or a function of time."""
    k = 1.0 / q
    cx, c1, c2 = {"low": (0.0, 0.0, 1.0), "band": (0.0, k, 0.0), "high": (1.0, -k, -1.0)}[mode]
    n = len(samples)
    out = [0.0] * n
    ic1 = ic2 = 0.0
    block = 32 if callable(cutoff) else max(1, n)
    for start in range(0, n, block):
        fc = cutoff(start / SR) if callable(cutoff) else cutoff
        g = math.tan(math.pi * min(max(fc, 20.0), SR * 0.45) / SR)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        for i in range(start, min(n, start + block)):
            v0 = samples[i]
            v3 = v0 - ic2
            v1 = a1 * ic1 + a2 * v3
            v2 = ic2 + a2 * ic1 + a3 * v3
            ic1 = 2.0 * v1 - ic1
            ic2 = 2.0 * v2 - ic2
            out[i] = cx * v0 + c1 * v1 + c2 * v2
    return out


def noise(dur, seed=0):
    rand = random.Random(seed).random
    return [2.0 * rand() - 1.0 for _ in range(max(1, int(dur * SR)))]


def burst(dur, center, q=1.0, decay=0.05, seed=0, mode="band", attack=0.001):
    """Filtered noise hit (cached), normalized to a peak of 1."""
    key = ("burst", round(dur, 4), round(center, 2), q, decay, seed, mode, attack)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    out = svf(noise(dur, seed), center, q, mode)
    attack_n = max(1, int(attack * SR))
    mult = math.exp(-1.0 / (decay * SR))
    level = 1.0
    for i in range(len(out)):
        out[i] *= level * min(1.0, i / attack_n)
        level *= mult
    peak = max(abs(v) for v in out) or 1.0
    out = [v / peak for v in out]
    _notes[key] = out
    return out


def saturate(samples, drive):
    norm = 1.0 / math.tanh(drive)
    return [math.tanh(drive * v) * norm for v in samples]


def layer(*parts):
    """Sums (samples, gain) pairs of any length."""
    out = [0.0] * max(len(samples) for samples, _ in parts)
    for samples, gain in parts:
        for i, v in enumerate(samples):
            out[i] += gain * v
    return out


def envelope(samples, points):
    return [v * g for v, g in zip(samples, ramp(points, len(samples)))]


def kick(drive=2.5):
    """Short punchy kick with a click and some saturation, so a phone speaker can play it."""
    body = glide("sine", [(0.0, 210.0), (0.03, 95.0), (0.22, 58.0)], amp=[(0.0, 1.0), (0.06, 0.7), (0.22, 0.0)],
                 attack=0.001)
    hit = saturate(layer((body, 1.0), (burst(0.015, 3000.0, 0.8, 0.004, seed=71), 0.4)), drive)
    return svf(hit, 70.0, 0.7, "high")


def snare(tone=200.0, center=4000.0, decay=0.09, seed=72):
    head = strike(tone, ((1.0, 1.0, 0.045), (1.58, 0.6, 0.03)), 0.2)
    return layer((head, 0.6), (burst(0.3, center, 0.6, decay, seed), 0.8))


def hat(decay=0.025, seed=73):
    return burst(decay * 5, 7500.0, 0.8, decay, seed, mode="high")


def scale_step(scale, degree):
    """Semitones from the root to a degree of the scale (any octave)."""
    steps = SCALES[scale]
    octave, index = divmod(degree, len(steps))
    return 12 * octave + steps[index]


def place(buffer, time, samples, gain=1.0):
    start = int(time * SR)
    for i, v in enumerate(samples[: max(0, len(buffer) - start)]):
        buffer[start + i] += gain * v


def clap(center=1800.0, seed=0):
    """Hand clap (cached): a few quick slaps of noise, then the main burst."""
    key = ("clap", center, seed)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    out = [0.0] * int(0.2 * SR)
    for k, (offset, gain) in enumerate(((0.0, 0.5), (0.009, 0.7), (0.018, 0.6))):
        place(out, offset, burst(0.012, center, 1.2, 0.003, seed=seed + k), gain)
    place(out, 0.027, burst(0.17, center, 1.0, 0.045, seed=seed + 3))
    _notes[key] = out
    return out


def drum(f0, f1, decay, slap, seed, drive=2.5):
    """Tuned drum (cached): the head's pitch drops after the hit, plus overtones and a slap of noise."""
    key = ("drum", f0, f1, decay, slap, seed, drive)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    body = glide("sine", [(0.0, f0), (0.04, f1 * 1.1), (decay * 4, f1)], amp=[(0.0, 1.0), (decay * 4, 0.0)], attack=0.001)
    overtones = strike(f1 * 1.5, ((1.0, 0.4, decay * 0.5), (1.6, 0.25, decay * 0.3)), decay * 2)
    out = saturate(layer((body, 1.0), (overtones, 0.5), (burst(0.06, slap, 1.0, 0.015, seed=seed), 0.5)), drive)
    _notes[key] = out
    return out


def trim_bass(mix, cutoff=150.0):
    """A phone speaker can't play the deepest bass of a drum, which would only eat headroom;
    the ear still hears the hit through its overtones."""
    mix.buffer = svf(mix.buffer, cutoff, 0.7, "high")


def brass(f, dur, vib=0.0, bright=5.0):
    """Brass note (cached): a small scoop up to pitch and a brightness that blooms with the attack."""
    key = ("brass", round(f, 3), round(dur, 4), vib, bright)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    tone = glide("saw", [(0.0, f * 0.95), (0.03, f), (dur, f)], vib_rate=5.5, vib_depth=vib, attack=0.012, release=0.035)
    out = svf(tone, lambda t: f * (1.2 + bright * min(1.0, t / 0.05)), 0.8)
    _notes[key] = out
    return out


def formant(samples, formants, q=6.0):
    """Parallel resonances [(hz or function of time, gain), ...]: vowels, bodies, horns."""
    out = [0.0] * len(samples)
    for center, gain in formants:
        band = svf(samples, center, q, "band")
        out = [a + gain * b for a, b in zip(out, band)]
    return out


def follow(steps, slide=0.06):
    """Turns [(time, value), ...] steps into a function of time that slides to each new value."""
    times = [when for when, _ in steps]

    def at(time):
        k = max(0, bisect.bisect_right(times, time) - 1)
        start, target = steps[k]
        before = steps[k - 1][1] if k else target
        return before + (target - before) * min(1.0, (time - start) / slide)
    return at


# --- Signals, sirens and horns --------------------------------------------------


def p_smoke_alarm(r, mix):
    # Like the temporal-3 fire alarm pattern: three half-second beeps, then a longer pause.
    f = r.uniform(3000, 3400)
    beep = note("square", f, dur=0.5, attack=0.003, release=0.008)
    t = 0.0
    while t < DURATION:
        for k in range(3):
            mix.add(t + k, beep, 0.8)
        t += 3.5


def p_reversing(r, mix):
    f = r.uniform(1000, 1250)
    beep = svf(note("square", f, dur=0.45, attack=0.004, release=0.01), f * 3.0, 0.7)
    # Diesel engine underneath: a fast train of low noise puffs that revs now and then.
    puffs = [burst(0.07, r.uniform(220, 420), 1.3, 0.02, seed=s) for s in range(4)]
    t = 0.0
    while t < DURATION:
        rev = 1.0 + 0.4 * max(0.0, math.sin(TWO_PI * t / 7.0))
        mix.add(t, r.choice(puffs), r.uniform(0.3, 0.45))
        t += r.uniform(0.95, 1.05) / (27.0 * rev)
    t = 0.2
    while t < DURATION:
        mix.add(t, beep, 0.8)
        t += 1.0


def p_air_raid(r, mix):
    # Two rotors a third apart, spinning up slowly, holding and winding down.
    top = r.uniform(520, 620)
    second = r.choice([1.19, 1.26])
    cycle = [(1.3, 0.62), (2.8, 0.9), (4.6, 1.0), (7.2, 0.985), (8.6, 0.74), (10.2, 0.42), (11.4, 0.3)]
    points = [(0.0, 0.25)]
    start = 0.0
    while start < DURATION:
        points += [(start + dt, level) for dt, level in cycle]
        start += 11.4
    track = layer(
        (glide("square", [(t, top * k) for t, k in points], vib_rate=0.7, vib_depth=0.004, attack=0.4), 0.6),
        (glide("square", [(t, top * second * k) for t, k in points], vib_rate=0.6, vib_depth=0.004, attack=0.4), 0.45))
    mix.add(0.0, svf(track, 3000, 0.7))


def p_dive_klaxon(r, mix):
    # "A-oo-ga": the motor spins up, so the pitch climbs, then sags.
    f = r.uniform(130, 165)
    honk = glide("saw", [(0.0, f), (0.12, f * 1.15), (0.45, f * 2.4), (0.75, f * 2.55), (0.95, f * 2.2), (1.1, f * 1.9)],
                 amp=[(0.0, 0.5), (0.15, 0.9), (0.5, 1.0), (0.95, 1.0), (1.1, 0.6)], attack=0.02, release=0.05)
    honk = saturate(honk, 3.0)
    honk = svf(layer((honk, 1.0), (svf(honk, 1100, 1.8, "band"), 1.2)), 250, 0.7, "high")
    gap = r.uniform(0.3, 0.45)
    t = 0.0
    while t < DURATION:
        mix.add(t, honk, 0.7)
        mix.add(t + 1.1 + gap, honk, 0.7)
        t += 2 * (1.1 + gap) + r.uniform(0.4, 0.7)


def p_car_alarm(r, mix):
    # Cycles through the classic modes, a few seconds each.
    k = r.uniform(0.9, 1.15)
    track = Mix()

    def whoop(t, end):
        tone = note("square", 650 * k, 2000 * k, dur=0.38, attack=0.005, release=0.01)
        while t < end:
            track.add(t, tone, 0.5)
            t += 0.42

    def hilo(t, end):
        hi = note("square", 1050 * k, dur=0.14, attack=0.003, release=0.006)
        lo = note("square", 780 * k, dur=0.14, attack=0.003, release=0.006)
        while t < end:
            track.add(t, hi, 0.5)
            track.add(t + 0.14, lo, 0.5)
            t += 0.28

    def chirp(t, end):
        beep = note("square", 1650 * k, dur=0.05, attack=0.002, release=0.006)
        while t < end:
            track.add(t, beep, 0.5)
            t += 0.1

    def warble(t, end):
        track.add(t, note("square", 1100 * k, dur=end - t, attack=0.005, release=0.02, vib_rate=7.0, vib_depth=0.22), 0.5)

    def wail(t, end):
        up = note("square", 900 * k, 1750 * k, dur=0.7, attack=0.005, release=0.005)
        down = note("square", 1750 * k, 900 * k, dur=0.7, attack=0.005, release=0.01)
        while t + 1.4 <= end + 0.3:
            track.add(t, up, 0.5)
            track.add(t + 0.7, down, 0.5)
            t += 1.4

    def pulse(t, end):
        tone = note("square", 1350 * k, 1250 * k, dur=0.22, attack=0.003, release=0.01)
        while t < end:
            track.add(t, tone, 0.5)
            t += 0.3

    modes = [whoop, hilo, chirp, warble, wail, pulse]
    r.shuffle(modes)
    t = 0.0
    for i in range(8):
        modes[i % len(modes)](t, min(DURATION, t + 3.4))
        t += 3.5
    mix.add(0.0, svf(track.buffer, 3500, 0.7))


def p_foghorn(r, mix):
    # Diaphone: a long low blast that ends in a grunt, echoing off the coast.
    f = r.uniform(150, 185)
    blast = r.uniform(2.4, 3.0)
    horn = glide("reed", [(0.0, f * 0.96), (0.2, f), (blast, f), (blast + 0.12, f * 0.74), (blast + 0.7, f * 0.7)],
                 amp=[(0.0, 0.2), (0.25, 1.0), (blast, 1.0), (blast + 0.15, 0.9), (blast + 0.7, 0.0)],
                 attack=0.05, release=0.08)
    horn = svf(svf(horn, 2200, 0.9), 180, 0.7, "high")
    period = blast + r.uniform(2.0, 2.6)
    t = 0.0
    while t < DURATION:
        mix.add(t, horn, 0.8)
        mix.add(t + 0.85, horn, 0.18)
        t += period


def p_crossing_bell(r, mix):
    f = r.uniform(650, 820)
    partials = ((1.0, 1.0, 0.45), (2.0, 0.45, 0.3), (2.76, 0.4, 0.22), (4.1, 0.25, 0.12), (5.4, 0.15, 0.08))
    bells = [strike(f, partials, 0.9), strike(f * 1.08, partials, 0.9)]
    clang = burst(0.02, 3200, 1.0, 0.004, seed=5)
    step = r.uniform(0.38, 0.46)
    t = 0.0
    k = 0
    while t < DURATION:
        mix.add(t, bells[k % 2], 0.8)
        mix.add(t, clang, 0.25)
        k += 1
        t += step


def p_train_horn(r, mix):
    # Chime horn: long, long, short, long, like a train approaching a crossing.
    chord = r.choice([[63, 66, 68, 71, 75], [61, 64, 68, 71], [62, 66, 69, 74]])
    shift = r.randint(-2, 2)
    freqs = [midi(m + shift) * r.uniform(0.996, 1.004) for m in chord]

    def blast(length):
        chimes = [(glide("reed", [(0.0, f * 0.97), (0.08, f), (length, f)], vib_rate=4.5, vib_depth=0.002,
                         attack=0.06, release=0.12), 0.3) for f in freqs]
        return svf(layer(*chimes), 3000, 0.7)

    long_blast, short_blast, final_blast = blast(1.7), blast(0.65), blast(2.6)
    t = 0.0
    while t < DURATION:
        for sound in (long_blast, long_blast, short_blast, final_blast):
            mix.add(t, sound, 0.8)
            t += len(sound) / SR + 0.35
        t += r.uniform(0.4, 0.8)


def whistle(f, dur, trill=35.0, depth=0.05, breath=0.25, seed=0):
    """Pea whistle (cached): the spinning pea chops the tone into a fast trill."""
    key = ("whistle", round(f, 3), round(dur, 4), trill, depth, breath, seed)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    n = max(1, int(dur * SR))
    rng = random.Random(seed)
    sine = table("sine", 1)
    hiss = svf(noise(dur, seed), f, 4.0, "band")
    peak = max(abs(v) for v in hiss) or 1.0
    attack_n = int(0.015 * SR)
    release_n = int(0.03 * SR)
    inc = f * TABLE_SIZE / SR
    pos = lfo = 0.0
    lfo_inc = trill * TABLE_SIZE / SR
    out = [0.0] * n
    for i in range(n):
        if i % 256 == 0:
            lfo_inc = trill * rng.uniform(0.85, 1.15) * TABLE_SIZE / SR
        m = sine[int(lfo) & MASK]
        env = min(1.0, i / attack_n, (n - i) / release_n)
        out[i] = (sine[int(pos) & MASK] * (0.75 + 0.25 * m) + breath * hiss[i] / peak) * env
        pos += inc * (1.0 + depth * m)
        lfo += lfo_inc
    _notes[key] = out
    return out


def p_referee(r, mix):
    f = r.uniform(2700, 3300)
    short = whistle(f, 0.2, seed=1)
    long_ = whistle(f * 0.99, 1.0, seed=2)
    t = 0.0
    while t < DURATION:
        call = r.choice([[short, short, long_], [short, short, long_], [short, short, short], [long_]])
        for blast in call:
            mix.add(t, blast, 0.8)
            t += len(blast) / SR + 0.12
        t += r.uniform(0.6, 1.0)


def p_walkie_talkie(r, mix):
    # Radio chatter: squelch, a garbled voice through a tiny speaker, the "roger" beep and static.
    squelch = burst(0.12, 1500, 0.5, 0.05, seed=3)
    tail = burst(0.3, 1800, 0.4, 0.07, seed=4)
    roger = [note("sine", 1000, dur=0.06, attack=0.003, release=0.008),
             note("sine", 1500, dur=0.07, attack=0.003, release=0.01)]
    vowels = [(730, 1090), (570, 840), (530, 1840), (300, 2300), (400, 800), (660, 1700)]

    def voice(length, low, high):
        # Syllables of a buzzy voice whose formants jump around like speech, then a radio's narrow, clipped sound.
        pitch, amp, first, second = [(0.0, low)], [(0.0, 0.0)], [(0.0, 500.0)], [(0.0, 1500.0)]
        t = 0.0
        while t < length:
            syllable = r.uniform(0.08, 0.2)
            f0 = r.uniform(low, high)
            pitch += [(t + 0.01, f0), (t + syllable, f0 * r.uniform(0.85, 1.1))]
            amp += [(t + 0.02, 1.0), (t + syllable - 0.03, 0.8), (t + syllable, 0.1 if r.random() < 0.7 else 0.0)]
            f1, f2 = r.choice(vowels)
            first.append((t + 0.03, f1))
            second.append((t + 0.03, f2))
            t += syllable
        buzz = glide("saw", pitch + [(t + 0.05, pitch[-1][1])], amp=amp + [(t + 0.05, 0.0)], vib_rate=5.0, vib_depth=0.02)
        speech = formant(buzz, [(follow(first), 1.0), (follow(second), 0.8), (2700, 0.3)], q=5.0)
        speech = svf(svf(speech, 400, 0.7, "high"), 3000, 0.7)
        peak = max(abs(v) for v in speech) or 1.0
        static = svf(noise(len(speech) / SR, int(length * 1000)), 2000, 0.6, "band")
        return layer((saturate([v / peak for v in speech], 3.0), 1.0), (static, 0.25))

    t = 0.0
    k = 0
    while t < DURATION:
        mix.add(t, squelch, 0.8)
        t += 0.08
        speaker = (100, 140) if k % 2 == 0 else (160, 220)
        said = voice(r.uniform(1.0, 2.2), *speaker)
        mix.add(t, said, 0.7)
        t += len(said) / SR
        mix.add(t, roger[0], 0.6)
        mix.add(t + 0.06, roger[1], 0.6)
        t += 0.14
        mix.add(t, tail, 0.8)
        t += 0.3 + r.uniform(0.2, 0.5)
        k += 1


# --- Instruments and styles -----------------------------------------------------


def p_chiptune(r, mix):
    # Like an 8-bit console: pulse lead, fast chord arpeggios, octave bass and noise drums.
    key = r.randint(60, 66)
    step = 60.0 / r.uniform(140, 160) / 4
    progression = r.choice([[0, 5, 3, 4], [0, 3, 4, 0], [5, 3, 0, 4], [0, 4, 5, 3]])
    rhythms = [[0, 2, 3, 4, 6, 8, 10, 11, 12, 14], [0, 3, 6, 8, 10, 12, 13, 14],
               [0, 2, 4, 6, 7, 8, 10, 12, 14, 15], [0, 1, 2, 4, 6, 8, 9, 10, 12]]

    def bar_melody(chord):
        degree = chord + r.choice([0, 2, 4])
        notes = []
        for s in r.choice(rhythms):
            degree += r.choice([-2, -1, 0, 1, 1, 2])
            if s % 4 == 0:
                degree = min((chord + d for d in (0, 2, 4, 7)), key=lambda d: abs(d - degree))
            degree = max(chord - 2, min(chord + 9, degree))
            notes.append((s, degree))
        return notes

    phrase_a = [bar_melody(c) for c in progression]
    phrase_b = phrase_a[:2] + [bar_melody(c) for c in progression[2:]]
    song = phrase_a + phrase_a + phrase_b + phrase_a + phrase_b
    kick_hit = layer((note("square", 180, 50, dur=0.08, attack=0.001, release=0.01), 0.6),
                     (note("noise", 1, dur=0.06, decay=0.02, lowpass=1200, seed=3), 0.8))
    snare_hit = note("noise", 1, dur=0.12, attack=0.001, release=0.02, decay=0.04, lowpass=7000, seed=4)
    hat_hit = note("noise", 1, dur=0.03, attack=0.001, release=0.005, decay=0.008, lowpass=11000, seed=5)
    t = 0.0
    for chord, melody in zip(progression * 5, song):
        if t >= DURATION:
            break
        for k, (s, degree) in enumerate(melody):
            end = melody[k + 1][0] if k + 1 < len(melody) else 16
            f = scale_note(key + 12, "major", degree)
            mix.add(t + s * step, note("pulse", f, dur=(end - s) * step * 0.9, attack=0.003, release=0.01), 0.45)
        tones = [scale_note(key, "major", chord + d) for d in (0, 2, 4, 7)]
        for i in range(32):
            mix.add(t + i * step / 2, note("square", tones[i % 4], dur=step / 2, attack=0.002, release=0.004), 0.15)
        bass = scale_note(key - 12, "major", chord)
        for i in range(8):
            tone = note("triangle", bass * (2 if i % 2 else 1), dur=step * 1.8, attack=0.003, release=0.01)
            mix.add(t + i * 2 * step, tone, 0.5)
        for s in range(16):
            if s in (0, 8, 10):
                mix.add(t + s * step, kick_hit, 0.6)
            if s in (4, 12):
                mix.add(t + s * step, snare_hit, 0.45)
            if s % 2:
                mix.add(t + s * step, hat_hit, 0.2)
        t += 16 * step


BUGLE_CALLS = [
    [(3, 2), (4, 1), (5, 1), (6, 4), (5, 2), (6, 2), (8, 6), (0, 2)],
    [(6, 1), (6, 1), (6, 2), (5, 2), (4, 2), (5, 1), (5, 1), (5, 2), (4, 2), (3, 2), (4, 6), (0, 2)],
    [(4, 2), (4, 1), (5, 1), (6, 2), (4, 2), (6, 2), (8, 4), (6, 2), (5, 2), (4, 4), (0, 2)],
    [(3, 1), (3, 1), (4, 2), (3, 1), (3, 1), (5, 2), (3, 1), (3, 1), (6, 2), (5, 2), (8, 6), (0, 2)],
]


def p_bugle(r, mix):
    # A bugle has no valves: it only plays the natural harmonics of its tube (G C E G C).
    fundamental = r.choice([116.54, 123.47, 130.81])
    unit = r.uniform(0.085, 0.1)
    order = list(range(len(BUGLE_CALLS)))
    t = 0.0
    while t < DURATION:
        r.shuffle(order)
        for call in order:
            for harmonic, length in BUGLE_CALLS[call]:
                if harmonic:
                    dur = length * unit * (0.9 if length < 4 else 0.97)
                    mix.add(t, brass(fundamental * harmonic, dur, vib=0.004 if length >= 4 else 0.0), 0.6)
                t += length * unit
            t += unit * 2


def pan_note(f, dur=0.8):
    return strike(f, ((1.0, 1.0, 0.32), (2.0, 0.6, 0.22), (3.0, 0.22, 0.12), (4.02, 0.1, 0.08), (5.9, 0.12, 0.02)), dur)


def p_steelpan(r, mix):
    # Calypso on steel drums; long notes are rolled, as pan players do.
    key = r.randint(70, 75)
    sixteenth = 60.0 / r.uniform(110, 122) / 4
    cells = [[3, 3, 2], [2, 2, 1, 1, 2], [1, 1, 2, 2, 2], [4, 2, 2], [3, 1, 2, 2], [2, 1, 2, 1, 2]]
    chords = r.choice([[0, 3, 4, 0], [0, 4, 3, 4], [0, 5, 3, 4]])
    t = 0.0
    bar = 0
    degree = 4
    while t < DURATION:
        chord = chords[bar % 4]
        for s, d in ((0, 0), (6, 4), (8, 0), (14, 4)):
            mix.add(t + s * sixteenth, pan_note(scale_note(key - 12, "major", chord + d)), 0.45)
        pos = 0
        for _ in range(2):
            for i, length in enumerate(r.choice(cells)):
                degree += r.choice([-2, -1, -1, 1, 1, 2])
                if i == 0:
                    degree = min((chord + c for c in (0, 2, 4, 7, 9)), key=lambda d: abs(d - degree))
                degree = max(0, min(10, degree))
                f = scale_note(key, "major", degree)
                start = t + pos * sixteenth
                k = 0
                while k == 0 or (length >= 4 and k * 0.065 < length * sixteenth - 0.04):
                    mix.add(start + k * 0.065, pan_note(f), 0.5 if k == 0 else 0.32)
                    k += 1
                pos += length
        t += 16 * sixteenth
        bar += 1


def p_handpan(r, mix):
    # Hand-played groove on a hang drum (minor "Kurd" scale): a deep central "ding",
    # notes around it, and slaps and ghost taps on the shell.
    ding = r.choice([50, 52, 53])
    field = [ding + i for i in (12, 14, 15, 17, 19, 20, 22, 24)]

    def tone(m):
        return strike(midi(m), ((1.0, 1.0, 0.8), (2.0, 0.5, 0.55), (3.0, 0.3, 0.3), (4.9, 0.08, 0.08)), 1.2, attack=0.004)

    slap = burst(0.06, 1500, 1.4, 0.014, seed=9)
    ghost = burst(0.03, 2600, 1.0, 0.006, seed=10)
    sixteenth = 60.0 / r.uniform(86, 96) / 4
    grooves = ["D.gT.ngTD.nT.nTn", "D.nTgnT.Dgn.TnTg", "DgnT.nTgD.ngTnnT", "D.gn.TnTDgnTgnT."]
    t = 0.0
    i = 3
    while t < DURATION:
        for k, c in enumerate(r.choice(grooves)):
            when = t + k * sixteenth
            if c == "D":
                mix.add(when, tone(ding), 0.75)
            elif c == "T":
                mix.add(when, slap, 0.45)
            elif c == "g":
                mix.add(when, ghost, 0.2)
            elif c == "n":
                i = max(0, min(len(field) - 1, i + r.choice([-2, -1, 1, 1, 2])))
                mix.add(when, tone(field[i]), 0.55)
        t += 16 * sixteenth


GUITAR_CHORDS = {
    "G": [43, 47, 50, 55, 59, 67],
    "C": [48, 52, 55, 60, 64],
    "D": [50, 57, 62, 66],
    "Em": [40, 47, 52, 55, 59, 64],
    "Am": [45, 52, 57, 60, 64],
    "F": [41, 48, 53, 57, 60, 65],
}


def p_strum(r, mix):
    progression = r.choice([["G", "C", "D", "G"], ["Am", "F", "C", "G"], ["C", "G", "Am", "F"], ["Em", "C", "G", "D"]])
    eighth = 60.0 / r.uniform(96, 112) / 2
    # D: down stroke, U: up stroke, X: muted "chuck" (the strumming hand slaps the strings).
    hits = [(k, c) for k, c in enumerate(r.choice(["D.XU.UXU", "DUXUDUXU", "D.XUDUXU"])) if c != "."]
    chuck = burst(0.25, 1200, 0.8, 0.035, seed=6)
    t = 0.0
    bar = 0
    while t < DURATION:
        chord = GUITAR_CHORDS[progression[bar % 4]]
        for j, (k, stroke) in enumerate(hits):
            start = t + k * eighth
            if stroke == "X":
                mix.add(start, chuck, 0.5)
                for s, m in enumerate(chord):
                    mix.add(start + s * 0.006, pluck(midi(m), 0.25, t60=0.18, bright=0.5, seed=m), 0.25)
                continue
            following = hits[j + 1][0] if j + 1 < len(hits) else 8
            length = (following - k) * eighth + 0.04
            # Down strokes sweep every string from the bass; up strokes catch the top four.
            strings = chord if stroke == "D" else chord[::-1][:4]
            spacing = 0.012 if stroke == "D" else 0.008
            for s, m in enumerate(strings):
                tone = pluck(midi(m), length, t60=1.6, bright=0.75 if stroke == "D" else 0.55, seed=m)
                mix.add(start + s * spacing, tone, 0.3 if stroke == "D" else 0.2)
        t += 8 * eighth
        bar += 1


POWER_RIFFS = [
    ["m", "m", 43, ".", "m", "m", 45, ".", "m", "m", 48, 47, "m", "m", 45, "."],
    ["m", "m", "m", 43, ".", 45, ".", "m", "m", "m", 50, ".", 48, ".", 45, "."],
    [45, ".", "m", "m", 48, ".", "m", "m", 50, ".", 48, ".", 45, ".", "m", "m"],
]


def p_power_chords(r, mix):
    # Distorted guitar: palm-muted chugs on low E between open power chords.
    eighth = 60.0 / r.uniform(132, 150) / 2
    riff = r.choice(POWER_RIFFS)
    track = Mix()
    t = 0.0
    step = 0
    while t < DURATION:
        token = riff[step % 16]
        if token == "m":
            for m in (40, 47):
                track.add(t, pluck(midi(m), 0.16, t60=0.12, bright=0.6, seed=m), 0.5)
        elif token != ".":
            length = 1
            while length < 4 and riff[(step + length) % 16] == ".":
                length += 1
            for m in (token, token + 7, token + 12):
                track.add(t, pluck(midi(m), length * eighth, t60=2.5, bright=0.9, seed=m), 0.4)
        t += eighth
        step += 1
    guitar = saturate(track.buffer, 8.0)
    mix.add(0.0, svf(svf(guitar, 3200, 0.8), 90, 0.7, "high"), 0.8)


def p_harp(r, mix):
    # Glissandos sweeping three octaves of strings, then a broken chord climbing slowly.
    root = r.randint(48, 53)
    scale = r.choice(["major", "lydian", "mixolydian"])
    chords = r.choice([[0, 3, 4, 0], [0, 5, 3, 4], [0, 4, 5, 3]])

    def string(degree):
        return pluck(scale_note(root, scale, degree), 1.8, t60=3.0, bright=0.3, seed=degree % 7)

    t = 0.0
    bar = 0
    while t < DURATION:
        c = chords[bar % 4]
        if bar % 2 == 0:
            run = list(range(c, c + 22)) + list(range(c + 20, c + 6, -1))
            spacing = 0.035
        else:
            run = [d for d in range(c, c + 22) if (d - c) % 7 in (0, 2, 4)]
            run += run[-2:2:-1]
            spacing = 0.05
        for k, d in enumerate(run):
            mix.add(t + k * spacing, string(d), 0.35)
        t += len(run) * spacing + 0.1
        for k, d in enumerate((c - 7, c - 3, c, c + 2, c + 4, c + 7)):
            mix.add(t + k * 0.13, string(d), 0.4)
        t += 6 * 0.13 + 0.45
        bar += 1


def bend(samples, points):
    """Re-reads samples at a varying speed [(time, ratio), ...]: a pitch bend."""
    n = len(samples)
    rates = ramp(points, n)
    out = [0.0] * n
    pos = 0.0
    for i in range(n):
        j = int(pos)
        if j + 1 >= n:
            break
        out[i] = samples[j] + (samples[j + 1] - samples[j]) * (pos - j)
        pos += rates[i]
    return out


def p_koto(r, mix):
    # Japanese pentatonic scale, with bends (pressing the string), tremolos and sweeps.
    root = r.randint(62, 66)
    scale = r.choice(["hirajoshi", "insen"])
    beat = r.uniform(0.3, 0.38)
    pick = burst(0.015, 3000, 1.0, 0.004, seed=8)

    def string(degree, dur=1.6):
        return pluck(scale_note(root, scale, degree), dur, t60=1.4, bright=0.9, seed=degree)

    t = 0.0
    degree = 5
    while t < DURATION:
        degree = max(0, min(10, degree + r.choice([-2, -1, -1, 1, 1, 2])))
        gesture = r.random()
        if gesture < 0.12:
            for k in range(11):
                mix.add(t + k * 0.03, string(k), 0.3)
            t += 2 * beat
        elif gesture < 0.35:
            semitones = r.choice([1, 2])
            tone = bend(string(degree, 2.0), [(0.0, 1.0), (0.18, 1.0), (0.32, 2 ** (semitones / 12.0))])
            mix.add(t, tone, 0.5)
            mix.add(t, pick, 0.15)
            t += 2 * beat
        elif gesture < 0.5:
            for k in range(3):
                mix.add(t + k * beat / 3, string(degree), 0.4)
            t += beat
        else:
            mix.add(t, string(degree), 0.5)
            mix.add(t, pick, 0.15)
            t += beat * r.choice([1, 1, 2])


def p_theremin(r, mix):
    # One continuous voice that slides between notes, with a wide vibrato.
    root = r.randint(67, 72)
    points = [(0.0, midi(root))]
    amp = [(0.0, 0.0), (0.4, 1.0)]
    t = 0.3
    degree = 0
    while t < DURATION + 1.0:
        degree = max(-3, min(10, degree + r.choice([-3, -2, -1, 1, 2, 3, 4])))
        f = scale_note(root, "harmonic_minor", degree)
        length = r.choice([0.3, 0.45, 0.6, 0.9, 1.2])
        points += [(t + r.uniform(0.06, 0.2), f), (t + length, f)]
        if r.random() < 0.15:
            amp += [(t + length - 0.12, 1.0), (t + length - 0.02, 0.1), (t + length + 0.1, 1.0)]
        t += length
    mix.add(0.0, glide("triangle", points, amp=amp, vib_rate=5.8, vib_depth=0.012, attack=0.2, release=0.3), 0.8)


def p_cumbia(r, mix):
    # Güiro (long-short-short scrapes), bass on the beat and accordion on the off-beats.
    key = r.randint(55, 62)
    beat = 60.0 / r.uniform(92, 100)
    click = burst(0.006, 4000, 1.5, 0.0015, seed=12)

    def scrape(length, rate):
        out = [0.0] * int(length * SR)
        count = int(length * rate)
        for k in range(count):
            start = int(k * SR / rate)
            gain = math.sin(math.pi * (k + 0.5) / count)
            for i, v in enumerate(click[: len(out) - start]):
                out[start + i] += gain * v
        return out

    long_scrape, short_scrape = scrape(beat * 0.42, 230), scrape(beat * 0.14, 260)
    chords = r.choice([[0, 4], [0, 3, 4, 0], [0, 0, 4, 4]])

    def accordion(f, dur):
        # Two reeds a little out of tune with each other: the "wet" musette sound.
        return layer((note("reed", f, dur=dur, attack=0.008, release=0.03), 0.5),
                     (note("reed", f * 1.006, dur=dur, attack=0.008, release=0.03), 0.5))

    t = 0.0
    bar = 0
    while t < DURATION:
        c = chords[bar % len(chords)]
        tones = [c, c + 2, c + 4] + ([c + 6] if c == 4 else [])
        for b in range(4):
            start = t + b * beat
            mix.add(start, long_scrape, 0.35)
            mix.add(start + beat * 0.5, short_scrape, 0.3)
            mix.add(start + beat * 0.75, short_scrape, 0.3)
            for d in tones:
                mix.add(start + beat * 0.5, accordion(scale_note(key, "major", d), beat * 0.28), 0.35)
        for when, d in ((0.0, 0), (1.5, 4), (2.0, 0), (3.5, 4)):
            f = scale_note(key - 24, "major", c + d)
            bass = note("saw", f, dur=beat * 0.45, attack=0.005, release=0.04, decay=0.25)
            mix.add(t + when * beat, bass, 0.5)
        if bar % 2:
            degree = c + 7
            for k in range(8):
                degree = max(c + 2, min(c + 11, degree + r.choice([-2, -1, -1, 1, 2])))
                mix.add(t + 2 * beat + k * beat / 4, accordion(scale_note(key + 12, "major", degree), beat * 0.22), 0.4)
        t += 4 * beat
        bar += 1


def p_bagpipe(r, mix):
    # Highland pipes: drones that never stop under a chanter melody full of grace notes.
    a = r.uniform(455, 480)
    steps = [-2, 0, 2, 4, 5, 7, 9, 10, 12]  # low G to high A
    beat = r.uniform(0.38, 0.44)
    rhythms = [[0.75, 0.25, 1.0], [0.5, 0.5, 0.5, 0.5], [0.75, 0.25, 0.75, 0.25], [1.5, 0.5], [1.0, 0.5, 0.5]]
    points = [(0.0, a)]

    def jump(time, f):
        points.append((time, points[-1][1]))
        points.append((time + 0.004, f))

    t = 0.3
    index = 1
    while t < DURATION + 0.5:
        for length in r.choice(rhythms):
            index = max(0, min(8, index + r.choice([-2, -1, -1, 1, 1, 2, 3])))
            start = t
            if index < 7 and r.random() < 0.6:
                jump(start, a * 2 ** (steps[7] / 12.0))  # high G grace note
                start += 0.035
            jump(start, a * 2 ** (steps[index] / 12.0))
            t += length * beat
    points.append((t + 0.3, points[-1][1]))
    drones = layer(
        (glide("saw", [(0.0, a / 2), (DURATION, a / 2)], attack=0.5), 0.35),
        (glide("saw", [(0.0, a / 2 * 1.003), (DURATION, a / 2 * 1.003)], attack=0.5, phase=0.3), 0.35),
        (glide("saw", [(0.0, a / 4), (DURATION, a / 4)], attack=0.5), 0.4))
    mix.add(0.0, svf(drones, 2500, 0.7), 0.6)
    mix.add(0.0, glide("reed", points, attack=0.3, release=0.3), 0.6)


VIBE_CHORDS = [[2, 5, 9, 12], [7, 11, 14, 17], [0, 4, 7, 11], [9, 13, 16, 19]]  # ii7 V7 Imaj7 VI7


def vibe_note(f, dur=1.6):
    return strike(f, ((1.0, 1.0, 0.9), (4.0, 0.3, 0.25), (10.0, 0.06, 0.05)), dur, attack=0.003)


def p_vibraphone(r, mix):
    # Jazz on the vibes: swung melody over comping chords, with the motor's tremolo.
    key = r.randint(55, 60)
    beat = 60.0 / r.uniform(112, 128)
    rhythms = [[0, 2 / 3, 1, 5 / 3, 2, 8 / 3, 3], [2 / 3, 1, 5 / 3, 2, 8 / 3, 3, 11 / 3], [0, 1, 5 / 3, 2, 8 / 3, 11 / 3],
               [0, 2 / 3, 1, 2, 2 + 2 / 3, 3, 3 + 2 / 3]]
    ride = layer((burst(0.6, 6500, 0.7, 0.18, seed=111, mode="high"), 0.5),
                 (strike(3400, ((1.0, 0.4, 0.3), (1.42, 0.3, 0.25)), 0.6), 0.25))
    track = Mix()
    t = 0.0
    bar = 0
    m = key + 19
    while t < DURATION:
        chord = VIBE_CHORDS[bar % 4]
        following = VIBE_CHORDS[(bar + 1) % 4][0]
        for k, d in enumerate(chord):
            track.add(t + k * 0.012, vibe_note(midi(key + d)), 0.16)
        tones = sorted({key + 12 + d + 12 * o for d in chord for o in (0, 1)})
        for when in r.choice(rhythms):
            # Walk along the chord tones, mostly by step.
            here = min(range(len(tones)), key=lambda i: abs(tones[i] - m))
            m = tones[max(0, min(len(tones) - 1, here + r.choice([-1, -1, 1, 1, 2, -2])))]
            track.add(t + when * beat, vibe_note(midi(m)), 0.45)
        # Walking bass: root, chord tones, then a half step into the next root.
        for b, d in enumerate((chord[0], r.choice(chord[1:3]), chord[2], following + r.choice([-1, 1]))):
            mix.add(t + b * beat, pluck(midi(key - 24 + d % 12), beat * 0.95, t60=0.8, bright=0.45, seed=d), 0.45)
        for when in (0, 1, 5 / 3, 2, 3, 11 / 3):
            mix.add(t + when * beat, ride, 0.12)
        t += 4 * beat
        bar += 1
    rate = r.uniform(4.5, 6.0)
    mix.add(0.0, [v * (0.75 + 0.25 * math.sin(TWO_PI * rate * i / SR)) for i, v in enumerate(track.buffer)])


def p_trance(r, mix):
    # Detuned "supersaw" chords chopped by a sixteenth-note gate, over a four-on-the-floor kick.
    key = r.randint(57, 62)
    step = 60.0 / r.uniform(134, 140) / 4
    bar = 16 * step
    # (root, third) of each chord, in semitones above the key.
    progression = r.choice([[(0, 3), (8, 4), (3, 4), (10, 4)], [(0, 3), (5, 3), (8, 4), (10, 4)],
                            [(0, 3), (10, 4), (8, 4), (7, 4)]])
    gate = r.choice(["x.xx.xx.x.xx.x.x", "xx.x.xx.xx.x.xx.", "x.x.xx.x.xx.xx.x"])
    env = [0.0] * int(bar * SR)
    for s, c in enumerate(gate):
        if c == "x":
            a, b = int(s * step * SR), int((s + 0.75) * step * SR)
            for i in range(a, b):
                env[i] = min(1.0, (i - a) / 66.0, (b - i) / 330.0)
    chords = []
    for root, third in progression:
        voices = []
        for m in (key + root, key + root + third, key + root + 7, key + root + 12):
            for v, cents in enumerate((-14, -7, 0, 7, 14)):
                f = midi(m) * 2 ** (cents / 1200.0)
                saw = glide("saw", [(0.0, f), (bar, f)], attack=0.002, release=0.002, phase=(v * 0.37) % 1.0)
                voices.append((saw, 0.1))
        chords.append([v * e for v, e in zip(layer(*voices), env)])
    track = Mix()
    t = 0.0
    k = 0
    while t < DURATION:
        track.add(t, chords[k % 4])
        t += bar
        k += 1
    mix.add(0.0, svf(track.buffer, lambda time: 1500 + 5500 * (time / DURATION) ** 1.5, 1.2))
    kick_hit, open_hat, hand_clap = kick(), hat(0.06, seed=74), clap(1500, seed=75)
    t = 0.0
    s = 0
    while t < DURATION:
        if s % 4 == 0:
            mix.add(t, kick_hit, 0.35)
        if s % 4 == 2:
            mix.add(t, open_hat, 0.25)
        if s % 8 == 4:
            mix.add(t, hand_clap, 0.35)
        t += step
        s += 1
    trim_bass(mix, 120.0)


def p_acid(r, mix):
    # A squelchy acid bassline: resonant filter, accents and slides.
    root = r.choice([45, 47, 48, 50])
    step = 60.0 / r.uniform(124, 132) / 4
    # Sixteen steps of (semitones, accent, slide), or None for a rest.
    pattern = [None if s and r.random() < 0.2 else
               (r.choice([0, 0, 0, 12, 3, 5, 7, 10, 12, 15]), r.random() < 0.3, r.random() < 0.25) for s in range(16)]
    points = [(0.0, midi(root))]
    amp = [(0.0, 0.0)]
    hits = []
    t = 0.0
    s = 0
    while t < DURATION + step:
        cell = pattern[s % 16]
        if cell:
            semitones, accent, slide = cell
            f = midi(root + semitones)
            level = 1.0 if accent else 0.7
            if slide and amp[-1][1] > 0:
                points += [(t, points[-1][1]), (t + step * 0.6, f)]
                amp += [(t + step * 0.85, level)]
            else:
                points += [(t, points[-1][1]), (t + 0.002, f)]
                amp += [(t, 0.0), (t + 0.003, level), (t + step * 0.85, level)]
                hits.append((t, accent))
            amp += [(t + step * 0.95, 0.0)] if pattern[(s + 1) % 16] is None or not pattern[(s + 1) % 16][2] else []
        t += step
        s += 1
    saw = glide("saw", points + [(t, points[-1][1])], amp=amp + [(t, 0.0)], attack=0.001, release=0.01)
    starts = [h[0] for h in hits]

    def cutoff(time):
        k = bisect.bisect_right(starts, time) - 1
        env = 0.0
        if k >= 0:
            start, accent = hits[k]
            env = math.exp(-(time - start) / (0.12 if accent else 0.2)) * (1.8 if accent else 1.0)
        return (220 + 1100 * (0.5 - 0.5 * math.cos(TWO_PI * time / 14.0))) * (1.0 + 3.0 * env)

    mix.add(0.0, saturate(svf(svf(saw, cutoff, 7.0), 80, 0.7, "high"), 2.0), 0.8)
    kick_hit, closed_hat = kick(), hat(0.02, seed=76)
    t = 0.0
    s = 0
    while t < DURATION:
        if s % 4 == 0:
            mix.add(t, kick_hit, 0.35)
        if s % 4 == 2:
            mix.add(t, closed_hat, 0.25)
        t += step
        s += 1
    trim_bass(mix, 120.0)


VOWELS = {"a": (730, 1090, 2440), "o": (570, 840, 2410), "e": (530, 1840, 2480)}


def p_choir(r, mix):
    # Four voices (formant-filtered) singing a slow progression, swelling on each chord.
    key = r.randint(57, 62)
    length = r.uniform(2.6, 3.2)
    progression = r.choice([[0, 5, 3, 4], [0, 3, 0, 4], [0, 4, 5, 3]])
    ranges = [(key - 17, key - 5), (key - 7, key + 5), (key, key + 10), (key + 5, key + 17)]
    current = [key - 12, key - 5, key + 4, key + 7]
    count = int(DURATION / length) + 1
    lines = [[(0.0, midi(m))] for m in current]
    amp = [(0.0, 0.0)]
    for c in range(count):
        chord = progression[c % len(progression)]
        classes = [scale_step("major", chord + d) % 12 for d in (0, 2, 4)]
        start = c * length
        for v, (low, high) in enumerate(ranges):
            wanted = classes[:1] if v == 0 else classes
            options = [m for m in range(low, high + 1) if (m - key) % 12 in wanted]
            current[v] = min(options, key=lambda m: abs(m - current[v]))
            lines[v] += [(start + 0.15, midi(current[v])), (start + length, midi(current[v]))]
        amp += [(start + 0.3, 0.65), (start + length * 0.6, 1.0), (start + length, 0.7)]
    # Every voice is doubled, slightly out of tune, like a section of singers.
    singers = []
    for v, line in enumerate(lines):
        singers.append((glide("saw", line, amp=amp, vib_rate=4.8 + 0.3 * v, vib_depth=0.006, attack=0.3), 0.25))
        doubled = [(t, f * 1.004) for t, f in line]
        singers.append((glide("saw", doubled, amp=amp, vib_rate=5.3 + 0.2 * v, vib_depth=0.006, attack=0.3, phase=0.5),
                        0.2))
    source = layer(*singers)
    sequence = [r.choice("aaoe") for _ in range(count)]

    def center(index):
        def at(time):
            c = min(count - 1, int(time / length))
            before = VOWELS[sequence[max(0, c - 1)]][index]
            return before + (VOWELS[sequence[c]][index] - before) * min(1.0, (time - c * length) / 0.4)
        return at

    mix.add(0.0, formant(source, [(center(0), 1.0), (center(1), 0.6), (center(2), 0.35)], q=5.0))


def p_wah_trumpet(r, mix):
    # Bluesy riff on a trumpet with a plunger mute opening and closing: wah-wah.
    key = r.randint(62, 67)
    beat = 60.0 / r.uniform(108, 124)

    def wah(f, dur, kind):
        cache = ("wah", round(f, 3), round(dur, 4), kind)
        if cache not in _notes:
            tone = glide("saw", [(0.0, f * 0.96), (0.04, f), (dur, f)], vib_rate=5.0, vib_depth=0.006 if dur > 0.4 else 0.0,
                         attack=0.015, release=0.04)

            def opening(t):
                if kind == "open":
                    return 450 + 1300 * min(1.0, t / 0.15)
                if kind == "close":
                    return 1750 - 1300 * min(1.0, t / dur)
                return 450 + 1300 * (0.5 - 0.5 * math.cos(TWO_PI * t / 0.3))

            _notes[cache] = layer((svf(tone, opening, 3.5, "band"), 1.0), (svf(tone, 1800, 0.7), 0.3))
        return _notes[cache]

    def riff():
        grid = [b + o for b in range(8) for o in (0.0, 2 / 3)]
        starts = sorted(r.sample(grid, 7))
        notes = []
        degree = 3
        for k, s in enumerate(starts):
            following = starts[k + 1] if k + 1 < len(starts) else 8.0
            degree = max(0, min(9, degree + r.choice([-2, -1, 1, 2])))
            notes.append((s, min(following - s, 2.5) * 0.9, degree, r.choice(["open", "open", "close", "wahwah"])))
        return notes

    a, b = riff(), riff()
    t = 0.0
    for notes in (a, a, b, a, a, b, a, b):
        if t >= DURATION:
            break
        for s, length, degree, kind in notes:
            mix.add(t + s * beat, wah(scale_note(key, "blues", degree), length * beat, kind), 0.7)
        t += 8 * beat


def p_kazoo(r, mix):
    # A march hummed through a buzzing membrane.
    key = r.randint(60, 65)
    beat = 60.0 / r.uniform(112, 126)
    rhythms = [[0.5, 0.5, 1.0], [0.75, 0.25, 0.5, 0.5], [1.0, 1.0], [0.5, 0.5, 0.5, 0.5], [1.5, 0.5]]
    points = [(0.0, midi(key))]
    amp = [(0.0, 0.0)]
    t = 0.1
    degree = 0
    bar = 0
    while t < DURATION + 0.5:
        lengths = r.choice(rhythms)
        for k, length in enumerate(lengths):
            degree = max(-3, min(9, degree + r.choice([-2, -1, -1, 1, 1, 2, 4])))
            if bar % 4 == 3 and k == len(lengths) - 1:
                degree = r.choice([0, 4, 7])
            f = scale_note(key, "major", degree)
            end = t + length * beat
            points += [(t, points[-1][1]), (t + 0.02, f)]
            amp += [(t, 0.2), (t + 0.02, 1.0), (end - 0.04, 0.9), (end - 0.005, 0.2)]
            t = end
        bar += 1
    points.append((t + 0.1, points[-1][1]))
    amp.append((t + 0.1, 0.0))
    hum = saturate(glide("saw", points, amp=amp, vib_rate=5.5, vib_depth=0.01), 4.0)
    rattle = [v * (1.0 + 0.25 * n) for v, n in zip(hum, svf(noise(len(hum) / SR, 3), 3000, 0.7))]
    mix.add(0.0, layer((svf(svf(rattle, 1300, 1.2, "band"), 350, 0.7, "high"), 1.0), (hum, 0.25)))


def p_barrel_organ(r, mix):
    # Organillero: a waltz on a hand-cranked organ, out of tune, wheezing and unsteady.
    key = r.randint(60, 65)
    beat = 60.0 / r.uniform(150, 168)
    progression = [0, 0, 4, 4, 4, 4, 0, 0, 0, 3, 0, 4, 0, 4, 0, 0]
    rhythms = [[3], [2, 1], [1, 1, 1], [1.5, 0.5, 1], [1, 0.5, 0.5, 1]]
    detune = {}

    def pipe(m, dur):
        if m not in detune:
            detune[m] = 2 ** (r.uniform(-25, 25) / 1200.0)
        f = midi(m) * detune[m]
        return layer((note("triangle", f, dur=dur, attack=0.02, release=0.04), 0.7),
                     (note("reed", f * 2.003, dur=dur, attack=0.03, release=0.04), 0.15))

    def crank(time):
        return time + 0.05 * math.sin(TWO_PI * time / 5.5)

    track = Mix()
    t = 0.0
    bar = 0
    degree = 4
    while t < DURATION:
        chord = progression[bar % 16]
        tones = [chord, chord + 2, chord + 4] + ([chord + 6] if chord == 4 else [])
        track.add(crank(t), pipe(key - 12 + scale_step("major", chord), beat * 0.9), 0.5)
        for b in (1, 2):
            for d in tones:
                track.add(crank(t + b * beat), pipe(key + scale_step("major", d), beat * 0.55), 0.16)
        pos = 0.0
        for length in r.choice(rhythms):
            degree += r.choice([-2, -1, 1, 2])
            if pos == 0:
                degree = min((chord + d for d in (0, 2, 4, 7)), key=lambda d: abs(d - degree))
            degree = max(0, min(9, degree))
            track.add(crank(t + pos * beat), pipe(key + 12 + scale_step("major", degree), length * beat * 0.92), 0.4)
            pos += length
        t += 3 * beat
        bar += 1
    mix.add(0.0, [v * (0.85 + 0.15 * math.sin(TWO_PI * 5.5 * i / SR)) for i, v in enumerate(track.buffer)])


def p_mariachi(r, mix):
    # Two trumpets in thirds over vihuela strums and guitarrón, alternating 6/8 and 3/4.
    key = r.randint(62, 67)
    eighth = 60.0 / r.uniform(400, 440)
    progression = r.choice([[0, 4, 4, 0], [0, 0, 4, 4], [0, 3, 4, 0]])
    rhythms = {False: [[3, 3], [2, 1, 3], [1, 1, 1, 3]], True: [[2, 2, 2], [2, 1, 1, 2], [4, 2]]}
    t = 0.0
    bar = 0
    degree = 4
    while t < DURATION:
        chord = progression[bar % 4]
        three_four = bar % 2 == 1
        accents = (0, 2, 4) if three_four else (0, 3)
        for k, a in enumerate(accents):
            m = key - 24 + scale_step("major", chord + (0 if k % 2 == 0 else 4))
            mix.add(t + a * eighth, pluck(midi(m), 2 * eighth, t60=0.8, bright=0.8, seed=m), 0.5)
        for e in range(6):
            for s, d in enumerate((chord, chord + 2, chord + 4, chord + 7)):
                m = key + scale_step("major", d)
                tone = pluck(midi(m), eighth, t60=0.25, bright=0.95, seed=d)
                mix.add(t + e * eighth + s * 0.005, tone, 0.16 if e in accents else 0.09)
        pos = 0
        for length in r.choice(rhythms[three_four]):
            degree += r.choice([-2, -1, 1, 1, 2])
            if pos == 0:
                degree = min((chord + d for d in (0, 2, 4, 7)), key=lambda d: abs(d - degree))
            degree = max(2, min(11, degree))
            dur = length * eighth * 0.92
            vib = 0.012 if length >= 3 else 0.0
            mix.add(t + pos * eighth, brass(scale_note(key, "major", degree), dur, vib=vib), 0.4)
            mix.add(t + pos * eighth, brass(scale_note(key, "major", degree - 2), dur, vib=vib), 0.3)
            pos += length
        t += 6 * eighth
        bar += 1


FIDDLE_FIGURES = [
    [0, 2, 4, 7, 4, 2, 0, 2],
    [0, 1, 2, 3, 4, 3, 2, 1],
    [4, 4, 5, 4, 3, 4, 2, 4],
    [0, 4, 7, 4, 9, 7, 4, 2],
    [7, 6, 4, 2, 4, 2, 1, 0],
]


def p_fiddle(r, mix):
    # A fast reel on the fiddle: bowed sawtooth through the violin body's resonances.
    key = r.choice([62, 64, 67])
    eighth = 60.0 / r.uniform(420, 470)
    chords = [0, 0, 3, 4, 0, 0, 4, 0]
    points = [(0.0, midi(key))]
    amp = [(0.0, 0.0)]
    t = 0.05
    bar = 0
    while t < DURATION + 0.3:
        figure = r.choice(FIDDLE_FIGURES)
        if r.random() < 0.4:
            figure = figure[:4] + r.choice(FIDDLE_FIGURES)[4:]
        for degree in figure:
            f = scale_note(key, "major", chords[bar % 8] + degree)
            points += [(t, points[-1][1]), (t + 0.012, f)]
            amp += [(t, 0.55), (t + 0.02, 1.0), (t + eighth - 0.01, 0.9)]
            t += eighth
        bar += 1
    points.append((t, points[-1][1]))
    amp.append((t, 0.0))
    tone = glide("saw", points, amp=amp, vib_rate=6.0, vib_depth=0.003)
    body = formant(tone, [(480, 0.8), (1150, 0.6), (2900, 0.5)], q=2.5)
    mix.add(0.0, layer((body, 1.0), (svf(tone, 5000, 0.7), 0.25)), 0.9)


# --- Rhythms and percussion -----------------------------------------------------


def p_dembow(r, mix):
    # Reggaetón: the "boom-ch-boom-chick" dembow beat under a minor-key synth hook.
    key = r.randint(57, 62)
    step = 60.0 / r.uniform(90, 98) / 4
    progression = r.choice([[0, 8, 3, 10], [0, 5, 8, 7], [0, 3, 8, 10]])
    kick_hit = kick(3.0)
    snap = layer((snare(230.0, 3500.0, 0.06, seed=77), 1.0), (clap(2200, seed=78), 0.5))
    closed = hat(0.02, seed=79)
    hook = r.choice([[0, 3, 6, 8, 11, 14], [0, 3, 6, 10, 12], [0, 2, 3, 6, 8, 11, 14]])

    def synth(m):
        cache = ("dembow", m)
        if cache not in _notes:
            _notes[cache] = svf(note("saw", midi(m), dur=0.3, attack=0.002, release=0.05, decay=0.1), 2500, 0.9)
        return _notes[cache]

    t = 0.0
    bar = 0
    while t < DURATION:
        root = progression[bar % 4]
        chord = [root, root + (3 if root in (0, 5) else 4), root + 7, root + 12]
        for s in range(16):
            when = t + s * step
            if s % 4 == 0:
                mix.add(when, kick_hit, 0.5)
            if s in (3, 6, 11, 14):
                mix.add(when, snap, 0.45)
            if s % 2 == 0:
                mix.add(when, closed, 0.15)
        for k, s in enumerate(hook):
            mix.add(t + s * step, synth(key + chord[k % 4]), 0.35)
        if bar % 4 == 3:
            for s in range(12, 16):
                mix.add(t + s * step, drum(480 - 30 * (s - 12), 400 - 30 * (s - 12), 0.05, 2200, 79), 0.35)
        t += 16 * step
        bar += 1
    trim_bass(mix)


def p_batucada(r, mix):
    # Samba school: surdos, snare, tamborim, agogô bells and shakers, with a break every few bars.
    sixteenth = 60.0 / r.uniform(98, 106) / 4
    surdo_low = drum(110.0, 66.0, 0.12, 900, 80)
    surdo_high = drum(140.0, 88.0, 0.1, 1100, 81)
    caixa = snare(330.0, 5000.0, 0.05, seed=82)
    tamborim = layer((strike(620, ((1.0, 1.0, 0.03), (1.7, 0.5, 0.02)), 0.08), 0.8),
                     (burst(0.03, 3500, 1.5, 0.006, seed=83), 0.5))
    bell = ((1.0, 1.0, 0.25), (2.4, 0.4, 0.08), (4.1, 0.2, 0.04))
    agogo = {"h": strike(1150, bell, 0.4), "l": strike(860, bell, 0.4)}
    shaker = burst(0.06, 7000, 0.8, 0.015, seed=84, mode="high", attack=0.008)
    tamborim_pattern = r.choice(["x.x.xx.x.x.xx.x.", "x.xx.x.xx.x.x.x."])
    agogo_pattern = r.choice(["h.l.hh.lh.l.h.l.", "hl.lh.l.hl.lh.hl"])
    cycle = 0
    t = 0.0
    while t < DURATION:
        breaking = cycle % 4 == 3
        for s in range(16):
            when = t + s * sixteenth
            if breaking and s >= 8:
                # Break: everybody stops, then hits together.
                if s in (12, 14):
                    for hit, gain in ((surdo_low, 0.6), (caixa, 0.5), (tamborim, 0.4), (agogo["h"], 0.3)):
                        mix.add(when, hit, gain)
                continue
            if s in (4, 12):
                mix.add(when, surdo_low, 0.6)
            if s in (0, 8):
                mix.add(when, surdo_high, 0.45)
            mix.add(when, caixa, 0.35 if s % 4 in (0, 3) else 0.15)
            if tamborim_pattern[s] == "x":
                mix.add(when, tamborim, 0.35)
            if agogo_pattern[s] != ".":
                mix.add(when, agogo[agogo_pattern[s]], 0.3)
            mix.add(when, shaker, 0.18 if s % 2 else 0.1)
        t += 16 * sixteenth
        cycle += 1
    trim_bass(mix)


def p_taiko(r, mix):
    # Japanese drums: a big o-daiko, nagado-daiko, the tight shime-daiko, rim clicks and a small gong.
    sixteenth = 60.0 / r.uniform(112, 126) / 4
    odaiko = svf(drum(95.0, 62.0, 0.25, 500, 85), 60, 0.7, "high")
    nagado = drum(170.0, 120.0, 0.12, 900, 86)
    shime = drum(700.0, 560.0, 0.03, 2500, 87)
    rim = burst(0.03, 1900, 2.0, 0.006, seed=88)
    kane = strike(2400, ((1.0, 1.0, 0.12), (1.47, 0.6, 0.08), (2.7, 0.4, 0.05)), 0.3)
    shime_pattern = r.choice(["x.xxx.xxx.xxx.x.", "xx.xx.x.xx.xx.x."])
    nagado_pattern = r.choice(["D...D.D.D...D.DD", "D..D..D.D.D.D..."])
    cycle = 0
    t = 0.0
    while t < DURATION:
        if cycle % 4 == 3:
            # Doro-doro: a roll that swells into one big unison hit.
            for s in range(12):
                mix.add(t + s * sixteenth, nagado, 0.2 + 0.04 * s)
                mix.add(t + (s + 0.5) * sixteenth, nagado, 0.18 + 0.04 * s)
            for hit in (odaiko, nagado, shime):
                mix.add(t + 12 * sixteenth, hit, 0.7)
            t += 16 * sixteenth
            cycle += 1
            continue
        if cycle % 2 == 0:
            mix.add(t, odaiko, 0.8)
        for s in range(16):
            when = t + s * sixteenth
            if shime_pattern[s] == "x":
                mix.add(when, shime, 0.4 if s % 4 == 0 else 0.25)
            if nagado_pattern[s] == "D":
                mix.add(when, nagado, 0.55)
            elif s % 4 == 2:
                mix.add(when, rim, 0.3)
            if s % 4 == 0:
                mix.add(when, kane, 0.15)
        t += 16 * sixteenth
        cycle += 1
    trim_bass(mix)


def cowbell(scale=1.0):
    """Two square waves through a band-pass, like the classic drum machine cowbell (cached)."""
    key = ("cowbell", scale)
    cached = _notes.get(key)
    if cached is not None:
        return cached
    tone = layer((note("square", 540 * scale, dur=0.4, attack=0.001, release=0.01), 0.5),
                 (note("square", 800 * scale, dur=0.4, attack=0.001, release=0.01), 0.5))
    tone = svf(tone, 1700 * scale, 1.0, "band")
    out = [v * (0.7 * math.exp(-i / (0.012 * SR)) + 0.3 * math.exp(-i / (0.12 * SR))) for i, v in enumerate(tone)]
    peak = max(abs(v) for v in out) or 1.0
    out = [v / peak for v in out]
    _notes[key] = out
    return out


def p_cowbell(r, mix):
    # Salsa bells: the mouth (low) on the beat and the neck (high) in between, with clave and conga.
    eighth = 60.0 / r.uniform(180, 200) / 2
    bells = {"L": cowbell(r.uniform(0.95, 1.05)), "H": cowbell(r.uniform(1.3, 1.4))}
    clave = strike(2500, ((1.0, 1.0, 0.03), (2.9, 0.3, 0.01)), 0.1)
    conga = drum(420.0, 330.0, 0.08, 1800, 89)
    bell_pattern = r.choice(["L.HLH.LHL.HLH.LH", "LHH.LHLHL.HLHHLH"])
    clave_pattern = r.choice(["x..x..x...x.x...", "..x.x...x..x..x."])
    t = 0.0
    while t < DURATION:
        for s in range(16):
            when = t + s * eighth
            if bell_pattern[s] != ".":
                mix.add(when, bells[bell_pattern[s]], 0.8 if bell_pattern[s] == "L" else 0.55)
            if clave_pattern[s] == "x":
                mix.add(when, clave, 0.4)
            if s % 8 in (6, 7):
                mix.add(when, conga, 0.2)
        t += 16 * eighth
    trim_bass(mix)


def p_palmas(r, mix):
    # Bulerías: a 12-beat cycle of bright and muted hand claps, a second clapper on the off-beats and footwork.
    beat = 60.0 / r.uniform(200, 230)
    bright = [clap(2400, seed=90 + k) for k in range(3)]
    muted = [clap(950, seed=95 + k) for k in range(3)]
    heel = layer((glide("sine", [(0.0, 160.0), (0.08, 90.0)], amp=[(0.0, 1.0), (0.08, 0.0)]), 0.8),
                 (burst(0.03, 1400, 1.0, 0.006, seed=99), 0.6))
    accents = (0, 3, 6, 8, 10)  # counting from 12: 12, 3, 6, 8, 10
    t = 0.0
    cycle = 0
    while t < DURATION:
        for b in range(12):
            when = t + b * beat
            mix.add(when, r.choice(bright) if b in accents else r.choice(muted), 0.8 if b in accents else 0.3)
            mix.add(when + beat / 2, r.choice(muted), 0.35)
            if cycle % 2 and b >= 8:
                mix.add(when, heel, 0.6)
                mix.add(when + beat / 2, heel, 0.5)
            elif b in (0, 6, 10):
                mix.add(when, heel, 0.5)
        t += 12 * beat
        cycle += 1
    trim_bass(mix)


SNARE_FIGURES = ["A.xxA.xxA.xxArrr", "AxxAxxAxAxxAxxAx", "rrrrrrrrrrrrA.A.", "f.x.f.x.fxfxA.A.", "AxAxxAxAxxAxrrrA"]


def p_snare_cadence(r, mix):
    # Marching snare: accents, flams and buzz rolls that swell into an accent, over a bass drum.
    sixteenth = 60.0 / r.uniform(112, 124) / 4
    hands = [snare(195.0, 4200.0, 0.11, seed=100), snare(200.0, 4400.0, 0.1, seed=101)]
    bass = drum(120.0, 74.0, 0.12, 700, 102, drive=2.0)
    t = 0.0
    hand = 0
    while t < DURATION:
        figure = r.choice(SNARE_FIGURES)
        roll = 0
        for s, token in enumerate(figure):
            when = t + s * sixteenth
            if s % 8 == 0:
                mix.add(when, bass, 0.5)
            if token == "r":
                roll += 1
                for k in range(4):
                    mix.add(when + k * sixteenth / 4, hands[(hand + k) % 2], min(0.6, 0.18 + 0.04 * roll))
                continue
            roll = 0
            if token == "f":
                mix.add(when - 0.025, hands[1 - hand], 0.3)
            if token in "Af":
                mix.add(when, hands[hand], 0.85)
            elif token == "x":
                mix.add(when, hands[hand], 0.35)
            hand = 1 - hand
        t += 16 * sixteenth
    trim_bass(mix)


def p_prehispanic(r, mix):
    # Conch-shell trumpet calls over a two-tongued slit drum (teponaztli), a deep drum (huéhuetl) and seed rattles.
    shell = r.uniform(250, 330)

    def conch(length):
        contour = [(0.0, shell * 0.85), (0.25, shell), (length - 0.3, shell * 1.01), (length, shell * 0.93)]
        shape = [(0.0, 0.0), (0.25, 1.0), (length - 0.3, 0.9), (length, 0.0)]
        tone = glide("triangle", contour, amp=shape, vib_rate=3.2, vib_depth=0.008)
        rasp = svf(glide("saw", contour, amp=shape, vib_rate=3.2, vib_depth=0.008), shell * 3, 2.0, "band")
        breath = envelope(svf(noise(length, 13), shell * 2, 2.0, "band"), shape)
        return layer((tone, 0.6), (rasp, 0.5), (breath, 0.4))

    low = r.uniform(380, 460)
    high = low * r.choice([1.25, 1.33, 1.5])
    wood = ((1.0, 1.0, 0.12), (2.83, 0.3, 0.04), (5.2, 0.1, 0.015))
    tongues = {"H": strike(high, wood, 0.3), "L": strike(low, wood, 0.3)}
    huehuetl = drum(130.0, 100.0, 0.15, 700, 104)
    rattle = [0.0] * int(0.08 * SR)
    for k in range(7):
        place(rattle, r.uniform(0.0, 0.05), burst(0.02, 5000, 1.0, 0.004, seed=105 + k), r.uniform(0.4, 1.0))
    eighth = 60.0 / r.uniform(100, 112) / 2
    patterns = ["HLLHLLHL", "HL.LHLHL", "HHLHLLHL", "H.LLH.LL"]
    calls = [(0.3, 2.4), (2.9, 1.2)]
    start = r.uniform(8.0, 9.5)
    while start < DURATION:
        calls += [(start, 2.4), (start + 2.6, 1.2)]
        start += r.uniform(8.0, 9.5)
    for when, length in calls:
        mix.add(when, conch(length), 0.7)
    t = 0.0
    while t < DURATION:
        pattern = r.choice(patterns)
        for k, c in enumerate(pattern):
            when = t + k * eighth
            if c != ".":
                mix.add(when, tongues[c], 0.5)
            if k in (0, 3, 6):
                mix.add(when, huehuetl, 0.45)
            if k % 2 == 0:
                mix.add(when, rattle, 0.2)
        t += 8 * eighth
    trim_bass(mix)


def p_scratch(r, mix):
    # Turntablism over a boom-bap beat: baby scratches, chirps and transformer cuts on an "ahh" sample.
    step = 60.0 / r.uniform(88, 96) / 4
    f = r.uniform(180, 240)
    voice = layer((glide("saw", [(0.0, f), (0.8, f * 0.97)], vib_rate=5.0, vib_depth=0.01, attack=0.01, release=0.2), 0.6),
                  (glide("saw", [(0.0, f * 1.5), (0.8, f * 1.455)], attack=0.01, release=0.2), 0.4))
    record = formant(voice, [(800, 1.0), (1200, 0.7), (2600, 0.3)], q=5.0)
    peak = max(abs(v) for v in record) or 1.0
    record = [v / peak for v in record]

    def play(moves):
        """moves: (seconds, from, to, fader); the needle moves along the record on a smooth curve."""
        out = []
        for dur, a, b, fader in moves:
            n = int(dur * SR)
            for i in range(n):
                u = i / n
                pos = (a + (b - a) * (0.5 - 0.5 * math.cos(math.pi * u))) * SR
                j = int(pos)
                v = record[j] + (record[j + 1] - record[j]) * (pos - j) if 0 <= j < len(record) - 1 else 0.0
                if fader == "cut" or (fader == "chirp" and u > 0.6):
                    v = 0.0
                elif fader == "transform":
                    v *= 0.5 + 0.5 * math.tanh(8.0 * math.sin(TWO_PI * 11.0 * i / SR))
                out.append(v)
        return out

    scratches = [
        play([(step * 2, 0.0, 0.18, "open"), (step * 2, 0.18, 0.0, "open")]),
        play([(step * 2, 0.0, 0.2, "chirp"), (step * 2, 0.2, 0.0, "cut")]),
        play([(step * 4, 0.0, 0.35, "transform")]),
        play([(step, 0.0, 0.1, "open"), (step, 0.1, 0.2, "open"), (step * 2, 0.2, 0.0, "open")]),
        play([(step, 0.0, 0.12, "open"), (step, 0.12, 0.0, "open"), (step, 0.0, 0.12, "open"), (step, 0.12, 0.0, "open")]),
    ]
    kick_hit, snap, closed = kick(), snare(210.0, 3800.0, 0.08, seed=106), hat(0.02, seed=107)
    t = 0.0
    beat = 0
    while t < DURATION:
        for s in range(4):
            when = t + s * step
            position = (beat % 4) * 4 + s
            if position in (0, 7, 10):
                mix.add(when, kick_hit, 0.5)
            if position in (4, 12):
                mix.add(when, snap, 0.5)
            if s % 2 == 0:
                mix.add(when, closed, 0.15)
        mix.add(t, record if beat % 8 == 0 else r.choice(scratches), 0.6)
        t += 4 * step
        beat += 1
    trim_bass(mix)


def piano(f, dur=0.9):
    """Hammered string: slightly stretched partials, the higher ones dying faster."""
    partials = tuple((k * math.sqrt(1 + 0.0004 * k * k), 1.0 / k ** 1.1, 1.2 / (1 + 0.5 * k)) for k in range(1, 9))
    return layer((strike(f, partials, dur), 1.0), (burst(0.02, 2500, 0.8, 0.004, seed=110), 0.12))


def p_piano(r, mix):
    # House-music piano: syncopated seventh-chord stabs with a bass note under each bar.
    key = r.randint(55, 60)
    step = 60.0 / r.uniform(120, 126) / 4
    shapes = {"m7": [0, 3, 7, 10], "maj7": [0, 4, 7, 11], "7": [0, 4, 7, 10]}
    progression = r.choice([[(0, "m7"), (5, "m7"), (8, "maj7"), (10, "7")], [(0, "m7"), (3, "maj7"), (8, "maj7"), (7, "7")],
                            [(0, "maj7"), (9, "m7"), (5, "maj7"), (7, "7")]])
    rhythm = r.choice([[0, 3, 6, 10, 12], [0, 3, 6, 8, 11, 14], [2, 5, 8, 11, 14]])
    t = 0.0
    bar = 0
    while t < DURATION:
        root, kind = progression[bar % 4]
        voicing = sorted((key + 12 + (root + d) % 12) for d in shapes[kind])
        for s in rhythm:
            for k, m in enumerate(voicing):
                mix.add(t + s * step + k * 0.004, piano(midi(m), step * 2.2), 0.3)
        mix.add(t, piano(midi(key - 12 + root), step * 8), 0.35)
        t += 16 * step
        bar += 1


def p_didgeridoo(r, mix):
    # A low drone shaped by the mouth: rhythmic "wa-wa-ou" formant sweeps, breath accents and barks.
    f = r.uniform(65, 78)
    sixteenth = 60.0 / r.uniform(104, 116) / 4
    shapes = {"w": (900, 1800), "o": (420, 850), "a": (700, 1300)}
    patterns = ["wo.owo.owo.oww.o", "w.owo.ow.awo.owo", "wowowo.aw.owowob", "w..ow.ow..oawo.b"]
    first, second, accents, toots = [], [], [], []
    t = 0.0
    while t < DURATION:
        for k, c in enumerate(r.choice(patterns)):
            when = t + k * sixteenth
            if c in shapes:
                first.append((when, shapes[c][0]))
                second.append((when, shapes[c][1]))
                if c == "a":
                    accents.append(when)
            elif c == "b":
                toots.append(when)
        t += 16 * sixteenth
    points = [(0.0, f)]
    for when in toots:
        points += [(when, f), (when + 0.03, f * 2.7), (when + 0.25, f * 2.7), (when + 0.28, f)]
    points.append((DURATION + 0.1, f))
    amp = [(0.0, 0.7)]
    for when in sorted(accents + toots):
        amp += [(when, 0.7), (when + 0.03, 1.0), (when + 0.25, 0.7)]
    amp.append((DURATION + 0.1, 0.7))
    source = glide("saw", points, amp=amp, vib_rate=0.3, vib_depth=0.005, attack=0.2)
    voiced = formant(source, [(follow(first), 1.0), (follow(second), 0.7), (2600, 0.2)], q=4.0)
    mix.add(0.0, svf(layer((voiced, 1.0), (saturate(source, 2.0), 0.08)), 120, 0.7, "high"))


# --- Things and machines ----------------------------------------------------------


def p_doorbell(r, mix):
    # A ding-dong door chime rung by an impatient visitor, who also knocks.
    high = r.uniform(640, 700)
    low = high / r.choice([1.25, 1.26])
    bar = ((1.0, 1.0, 0.9), (2.76, 0.15, 0.25), (5.4, 0.08, 0.1))
    ding, dong = strike(high, bar, 1.6), strike(low, bar, 1.9)
    plunger = burst(0.05, 600, 0.8, 0.01, seed=120)
    knock = layer((drum(180.0, 140.0, 0.03, 1200, 121, drive=1.5), 1.0), (burst(0.03, 2000, 1.2, 0.005, seed=122), 0.5))

    def ring(when, hold=0.55):
        mix.add(when, plunger, 0.2)
        mix.add(when, ding, 0.7)
        mix.add(when + hold, dong, 0.7)

    t = 0.2
    while t < DURATION:
        kind = r.choice(["one", "two", "many", "knock"])
        if kind == "one":
            ring(t)
            t += 2.6
        elif kind == "two":
            ring(t)
            ring(t + 1.3)
            t += 3.6
        elif kind == "many":
            for k in range(4):
                ring(t + k * 0.45, hold=0.22)
            t += 3.0
        else:
            for k in range(3):
                mix.add(t + k * 0.22, knock, 0.8)
            t += 1.4
    trim_bass(mix)


def p_cuckoo(r, mix):
    # Cuckoo clock: the pendulum ticking, the gears whirring, then the bird calls the hour.
    tick = burst(0.02, 3200, 3.0, 0.004, seed=123)
    tock = burst(0.02, 1900, 3.0, 0.005, seed=124)
    gear = burst(0.01, 2500, 2.0, 0.002, seed=125)
    bellows = burst(0.08, 900, 0.7, 0.02, seed=127)
    high = midi(r.choice([76, 77, 79]))
    low = high / 2 ** (r.choice([3, 4]) / 12.0)

    def pipe(f, dur):
        tone = glide("triangle", [(0.0, f * 0.98), (0.03, f), (dur, f * 0.995)], attack=0.03, release=0.05)
        breath = envelope(svf(noise(dur, 126), f, 3.0, "band"), [(0.0, 0.0), (0.03, 1.0), (dur, 0.3)])
        return layer((tone, 1.0), (breath, 0.6))

    cu, coo = pipe(high, 0.22), pipe(low, 0.34)
    hour = r.choice([6, 7, 8])
    t = 0.0
    k = 0
    while t < DURATION:
        mix.add(t, tick if k % 2 == 0 else tock, 0.45)
        t += 0.5
        k += 1
    t = 2.0
    while t < DURATION:
        for g in range(24):
            mix.add(t + g / 30.0, gear, 0.25)
        t += 0.9
        for _ in range(hour):
            mix.add(t, bellows, 0.3)
            mix.add(t, cu, 0.8)
            mix.add(t + 0.28, coo, 0.8)
            t += 0.85
        t += 3.0


def p_steam_train(r, mix):
    # A steam locomotive pulling out: chuffs speeding up, rail clicks and a three-chime whistle.
    chuffs = [burst(0.4, r.uniform(700, 1100), 0.7, 0.12, seed=130 + k, attack=0.015) for k in range(4)]
    clack = burst(0.03, 3500, 2.0, 0.006, seed=134)
    chord = r.choice([[74, 77, 81], [72, 76, 79], [71, 74, 79]])

    def whistle_blast(length):
        tones = [(glide("triangle", [(0.0, midi(m) * 0.96), (0.15, midi(m)), (length, midi(m) * 0.99)],
                        attack=0.1, release=0.15), 0.3) for m in chord]
        hiss = envelope(svf(noise(length, 135), 2500, 0.8, "band"),
                        [(0.0, 0.0), (0.1, 1.0), (length - 0.15, 1.0), (length, 0.0)])
        return layer(*tones, (hiss, 0.08))

    t = 0.0
    rate = 1.4
    beat = 0
    while t < DURATION:
        mix.add(t, chuffs[beat % 4], 0.55 if beat % 4 == 0 else 0.4)
        if rate > 2.5 and beat % 2 == 0:
            mix.add(t + 0.1, clack, 0.3)
            mix.add(t + 0.18, clack, 0.25)
        t += 1.0 / rate
        rate = min(6.0, rate * 1.04)
        beat += 1
    for when, length in ((2.0, 2.0), (12.0, 1.0), (13.4, 2.2), (22.0, 1.2), (23.5, 1.6)):
        mix.add(when, whistle_blast(length), 0.6)
    # Steam leaking all the time and the rumble of the wheels.
    mix.add(0.0, svf(noise(DURATION, 136), 1200, 0.5, "band"), 0.05)


def p_camotero(r, mix):
    # The sweet-potato cart's steam whistle: one shrill note that wavers with the pressure, and lots of hiss.
    f = r.uniform(1400, 1900)
    points = [(0.0, f * 0.9)]
    amp = [(0.0, 0.0)]
    t = 0.0
    while t < DURATION:
        length = r.uniform(4.0, 8.0)
        points.append((t + 0.25, f))
        amp.append((t + 0.15, 1.0))
        x = t + 0.25
        while x < t + length - 1.0:
            x += r.uniform(0.15, 0.4)
            points.append((x, f * r.uniform(0.975, 1.02)))
            amp.append((x, r.uniform(0.75, 1.0)))
        # The pressure runs out: the pitch sags as it dies.
        points.append((t + length, f * 0.88))
        amp += [(t + length - 0.3, 0.8), (t + length, 0.0)]
        t += length + r.uniform(0.4, 0.9)
        points.append((t, f * 0.9))
        amp.append((t, 0.0))
    tone = glide("sine", points, amp=amp, vib_rate=9.0, vib_depth=0.004)
    overtone = glide("sine", [(time, 2 * hz) for time, hz in points], amp=amp, vib_rate=9.0, vib_depth=0.004)
    steam = ramp(amp, len(tone))
    hiss = [v * (0.15 + 0.85 * g) for v, g in zip(svf(noise(len(tone) / SR, 140), 3000, 0.6, "high"), steam)]
    mix.add(0.0, layer((tone, 0.8), (overtone, 0.15), (hiss, 0.3)))


def p_helicopter(r, mix):
    # Rotor blades chopping the air, a turbine whine and the tail rotor's buzz, flying past and coming back.
    blades = r.uniform(10.5, 13.0)
    whine = r.uniform(2300, 3000)
    passes = [(0.0, 0.35), (5.0, 1.0), (9.0, 0.3), (13.0, 0.35), (17.5, 1.0), (21.5, 0.3), (25.0, 0.7), (28.5, 1.0)]
    # Doppler: a little higher while it approaches, lower once it has passed.
    doppler = [(0.0, 1.03)]
    for (t0, a), (t1, b) in zip(passes, passes[1:]):
        doppler += [(t0 + 0.3, 1.03 if b > a else 0.97), (t1 - 0.3, 1.03 if b > a else 0.97)]
    doppler.append((DURATION + 0.5, 1.03))
    level = ramp(passes, int(DURATION * SR) + 1)
    pitch = ramp(doppler, int(DURATION * SR) + 1)
    whup = burst(0.09, 500, 0.8, 0.025, seed=141, attack=0.004)
    t = 0.0
    while t < DURATION:
        i = int(t * SR)
        mix.add(t, whup, 0.8 * level[i])
        t += 1.0 / (blades * pitch[i])
    turbine = glide("sine", [(time, whine * k) for time, k in doppler], amp=passes)
    tail = glide("saw", [(time, 95.0 * k) for time, k in doppler], amp=passes)
    mix.add(0.0, layer((turbine, 0.08), (svf(tail, 900, 1.0, "band"), 0.35)))
    trim_bass(mix)


def p_race_cars(r, mix):
    # Race cars screaming past: each engine's pitch drops as it goes by (Doppler), with a gear change.
    t = 0.3
    while t < DURATION:
        cars = [(0.0, r.uniform(380, 520))]
        if r.random() < 0.35:
            cars.append((0.35, cars[0][1] * 1.05))
        span = r.uniform(2.6, 3.4)
        peak = span * 0.55
        for delay, base in cars:
            shift = r.uniform(0.3, peak - 0.4)
            points = [(0.0, base * 1.25), (shift, base * 1.32), (shift + 0.05, base * 1.12), (peak - 0.12, base * 1.28),
                      (peak + 0.12, base * 0.82), (span, base * 0.78)]
            amp = [(0.0, 0.05), (peak - 0.6, 0.35), (peak, 1.0), (peak + 0.5, 0.3), (span, 0.0)]
            # The cylinders don't fire evenly: a sub-harmonic and ragged noise make it growl.
            firing = glide("saw", points, amp=amp, attack=0.05, release=0.1)
            crank = glide("square", [(time, hz / 2) for time, hz in points], amp=amp, attack=0.05, release=0.1)
            grit = [v * (1.0 + 0.5 * n) for v, n in zip(layer((firing, 0.8), (crank, 0.35)), noise(span, 190))]
            engine = svf(saturate(grit, 3.0), 4500, 0.7)
            mix.add(t + delay, engine, 0.6)
        t += span * r.uniform(0.75, 1.05)


DTMF_ROWS = (697, 770, 852, 941)
DTMF_COLUMNS = (1209, 1336, 1477)


def p_modem(r, mix):
    # Dial-up: dial tone, keypad digits, ringing, the answer tone, then the handshake's screeches and hiss.
    def dual(f1, f2, dur):
        return layer((note("sine", f1, dur=dur, attack=0.005, release=0.005), 0.5),
                     (note("sine", f2, dur=dur, attack=0.005, release=0.005), 0.5))

    t = 0.0
    while t < DURATION:
        mix.add(t, dual(350, 440, 0.9), 0.6)
        t += 1.0
        for _ in range(r.randint(7, 10)):
            mix.add(t, dual(r.choice(DTMF_ROWS), r.choice(DTMF_COLUMNS), 0.09), 0.7)
            t += 0.16
        t += 0.3
        mix.add(t, dual(440, 480, 1.0), 0.5)
        t += 1.4
        # Answer tone; restarting it every 450 ms gives the phase-reversal clicks.
        for k in range(4):
            mix.add(t + k * 0.45, note("sine", 2100, dur=0.45, attack=0.002, release=0.002), 0.5)
        t += 1.8
        for k in range(10):
            mix.add(t + k * 0.07, note("square", 1200 if k % 2 else 2400, dur=0.07, attack=0.002, release=0.002), 0.25)
        t += 0.8
        for k in range(5):
            tones = [note("sine", r.uniform(600, 3000), dur=0.1, attack=0.004, release=0.01) for _ in range(3)]
            chord = layer(*[(tone, 0.3) for tone in tones])
            mix.add(t + k * 0.12, chord, 0.6)
        t += 0.7
        hiss = envelope(svf(noise(1.8, 150 + int(t)), 1800, 0.5, "band"), [(0.0, 0.0), (0.05, 1.0), (1.7, 1.0), (1.8, 0.0)])
        mix.add(t, hiss, 0.6)
        t += 1.9
        # Data: frequency-shift keying, jumping between tones 300 times a second.
        points = [(0.0, 1180.0)]
        for k in range(360):
            f = r.choice([980.0, 1180.0, 1650.0, 1850.0])
            points += [(k / 300.0, points[-1][1]), (k / 300.0 + 0.0005, f)]
        points.append((1.2, points[-1][1]))
        mix.add(t, glide("sine", points), 0.5)
        t += 2.0


def p_geiger(r, mix):
    # A Geiger counter near a radioactive source: random clicks whose rate rises and falls, and the meter's alarm.
    click = layer((burst(0.008, 3500, 1.5, 0.002, seed=160), 1.0),
                  (note("sine", 450, dur=0.008, attack=0.0005, release=0.003), 0.4))
    # Clicks per second over time.
    profile = [(0.0, 3.0), (4.0, 12.0), (8.0, 180.0), (10.0, 220.0), (12.5, 15.0), (15.0, 8.0), (19.0, 120.0),
               (22.0, 400.0), (25.0, 60.0), (28.0, 250.0)]
    times = [p[0] for p in profile]

    def rate(time):
        k = min(len(profile) - 2, bisect.bisect_right(times, time) - 1)
        (t0, a), (t1, b) = profile[k], profile[k + 1]
        return a * (b / a) ** ((time - t0) / (t1 - t0))

    t = 0.0
    while t < DURATION:
        t += r.expovariate(rate(t))
        mix.add(t, click, r.uniform(0.6, 1.0))
    beep = note("square", 2900, dur=0.07, attack=0.002, release=0.01)
    t = 0.0
    while t < DURATION:
        if rate(t) > 100:
            mix.add(t, beep, 0.35)
        t += 0.25


def p_knife_grinder(r, mix):
    # The knife grinder's pan pipes: a quick breathy run up the pipes and back down.
    root = r.randint(79, 84)
    pipes = [scale_note(root, "major", d) for d in range(12)]

    def run(order, spacing):
        end = len(order) * spacing
        points = [(0.0, pipes[order[0]])]
        for k, i in enumerate(order):
            points += [(k * spacing, points[-1][1]), (k * spacing + 0.008, pipes[i])]
        points.append((end, points[-1][1]))
        amp = [(0.0, 0.0), (0.03, 1.0), (end - 0.05, 0.9), (end, 0.0)]
        tone = glide("sine", points, amp=amp, attack=0.02, release=0.04)
        breath = svf(noise(end, 170), lambda time: pipes[order[min(len(order) - 1, int(time / spacing))]], 3.0, "band")
        peak = max(abs(v) for v in breath) or 1.0
        return layer((tone, 1.0), (envelope([v / peak for v in breath], amp), 0.3))

    up_down = run(list(range(12)) + list(range(10, -1, -1)), 0.04)
    up = run(list(range(12)), 0.045)
    t = 0.2
    while t < DURATION:
        for sound in r.choice([[up_down], [up_down, up_down], [up, up_down]]):
            mix.add(t, sound, 0.8)
            t += len(sound) / SR + 0.05
        t += r.uniform(0.5, 0.9)


def p_slot_machine(r, mix):
    # Slot machine: the lever, three reels clicking to a stop one by one, then jackpot bells and pouring coins.
    lever = [burst(0.012, 1500, 1.5, 0.003, seed=180 + k) for k in range(3)]
    reel = burst(0.015, 2600, 1.5, 0.003, seed=183)
    thunk = drum(220.0, 160.0, 0.04, 1500, 184, drive=1.5)
    coins = [strike(r.uniform(3200, 4800), ((1.0, 1.0, 0.12), (1.6, 0.6, 0.07), (2.7, 0.4, 0.04)), 0.4) for _ in range(5)]
    win = [scale_note(r.randint(72, 76), "major", d) for d in (0, 2, 4, 7, 9, 11, 14)]
    t = 0.0
    while t < DURATION:
        for k in range(6):
            mix.add(t + k * 0.05, lever[k % 3], 0.5)
        t += 0.4
        stops = [t + 1.0, t + 1.4, t + 1.8]
        x = t
        while x < stops[-1]:
            spinning = sum(1 for s in stops if x < s)
            mix.add(x, reel, 0.15 * spinning)
            x += 0.035 + 0.02 * (3 - spinning)
        for s in stops:
            mix.add(s, thunk, 0.6)
        t = stops[-1] + 0.25
        for _ in range(2):
            for k, f in enumerate(win):
                mix.add(t + k * 0.06, strike(f, ((1.0, 1.0, 0.3), (2.0, 0.4, 0.15), (3.0, 0.2, 0.08)), 0.5), 0.35)
            t += len(win) * 0.06 + 0.05
        x = t
        while x < t + 1.6:
            mix.add(x, r.choice(coins), r.uniform(0.15, 0.35))
            x += r.uniform(0.02, 0.07)
        t += 1.9


# --- Animals and silly sounds ---------------------------------------------------


def p_rooster(r, mix):
    # Two roosters crowing at each other: "qui-qui-ri-quííí".
    def crow(f):
        cache = ("crow", round(f, 2))
        if cache not in _notes:
            pitch = [(0.0, f), (0.11, f * 1.1), (0.16, f * 1.05), (0.27, f * 1.15), (0.32, f * 1.1), (0.46, f * 1.2),
                     (0.52, f * 1.2), (0.72, f * 1.55), (1.12, f * 1.5), (1.45, f)]
            amp = [(0.0, 0.0), (0.02, 0.8), (0.1, 0.7), (0.12, 0.0), (0.16, 0.0), (0.18, 0.85), (0.26, 0.7), (0.28, 0.0),
                   (0.32, 0.0), (0.34, 0.9), (0.45, 0.8), (0.47, 0.1), (0.52, 0.1), (0.56, 1.0), (1.2, 0.9), (1.45, 0.0)]
            # A fast, irregular wobble makes the voice hoarse.
            voice = glide("saw", pitch, amp=amp, vib_rate=31.0, vib_depth=0.025, attack=0.01, release=0.03)
            _notes[cache] = formant(voice, [(1100, 1.0), (2400, 0.8), (3600, 0.4)], q=4.0)
        return _notes[cache]

    first = r.uniform(500, 620)
    second = first * r.uniform(0.8, 0.88)
    t = 0.3
    while t < DURATION:
        mix.add(t, crow(first), 0.8)
        t += r.uniform(1.7, 2.3)
        mix.add(t, crow(second), 0.6)
        t += r.uniform(1.7, 2.3)


def p_drops(r, mix):
    # Water dripping in a cave: each drop is a tiny bubble whose pitch shoots up, with echoes.
    drops = []
    for _ in range(6):
        f = r.uniform(500, 1300)
        drop = note("sine", f, f * r.uniform(1.8, 2.8), dur=r.uniform(0.04, 0.07), attack=0.001, release=0.01, decay=0.03)
        drops.append(drop)
    plop = burst(0.03, 600, 1.0, 0.006, seed=200)
    echoes = ((0.0, 1.0), (0.19, 0.35), (0.41, 0.14))
    # A leaky tap drips steadily...
    tap = r.uniform(0.42, 0.5)
    t = 0.0
    while t < DURATION:
        for delay, gain in echoes:
            mix.add(t + delay, drops[0], 0.8 * gain)
        t += tap
    # ...while more and more drops fall around it.
    t = 0.3
    while t < DURATION:
        g = r.uniform(0.4, 0.8)
        drop = r.choice(drops[1:])
        for delay, gain in echoes:
            mix.add(t + delay, drop, g * gain)
        mix.add(t, plop, 0.1 * g)
        t += r.expovariate(1.0 + 7.0 * t / DURATION)


def p_woodpecker(r, mix):
    # A woodpecker drumming on a hollow trunk, its sharp call, and another one answering farther away.
    def knock(f, seed):
        return layer((strike(f, ((1.0, 1.0, 0.012), (2.3, 0.5, 0.006)), 0.05), 1.0),
                     (burst(0.02, 2000, 1.0, 0.003, seed=seed), 0.5))

    near, far = knock(r.uniform(900, 1300), 210), knock(r.uniform(700, 900), 211)
    call = svf(glide("square", [(0.0, 2600.0), (0.06, 2200.0)], attack=0.003, release=0.01), 2500, 2.0, "band")
    t = 0.3
    while t < DURATION:
        count = r.randint(12, 22)
        gap = r.uniform(0.045, 0.06)
        for k in range(count):
            u = k / count
            mix.add(t, near, 0.4 + 0.5 * math.sin(math.pi * u))
            t += gap * (1.0 + 0.3 * u)
        t += r.uniform(0.6, 1.2)
        if r.random() < 0.5:
            for k in range(r.randint(3, 6)):
                mix.add(t + k * 0.11, call, 0.5)
            t += 0.8
        if r.random() < 0.4:
            for k in range(r.randint(10, 16)):
                mix.add(t, far, 0.25)
                t += 0.055
            t += 0.5


def p_frogs(r, mix):
    # A chorus of frogs, each croaking "rib-bit" at its own pitch and pace, getting louder.
    t0 = 0.0
    for k in range(4):
        rate = r.uniform(90, 180)
        center = r.uniform(900, 2000)
        rib = note("pulse", rate, dur=0.07, attack=0.005, release=0.02)
        bit = note("pulse", rate * 1.15, dur=0.05, attack=0.005, release=0.015)
        croak = svf(layer((rib, 1.0), ([0.0] * int(0.1 * SR) + bit, 0.8)), center, 3.0, "band")
        period = r.uniform(0.6, 1.4)
        gain = r.uniform(0.5, 0.9)
        t = r.uniform(0.0, 1.0) + t0
        while t < DURATION:
            mix.add(t, croak, gain * (0.6 + 0.4 * t / DURATION))
            t += period * r.uniform(0.9, 1.1)
        t0 += r.uniform(0.5, 2.0)


def p_cat(r, mix):
    # A hungry cat meowing for breakfast, more and more insistently.
    def meow(f, length):
        pitch = [(0.0, f * 0.9), (length * 0.35, f * 1.25), (length, f * 0.8)]
        amp = [(0.0, 0.0), (0.06, 0.4), (length * 0.3, 1.0), (length * 0.8, 0.7), (length, 0.0)]
        voice = glide("saw", pitch, amp=amp, vib_rate=7.0, vib_depth=0.01, attack=0.03, release=0.05)

        # "m-i-a-u": the mouth opens, then rounds and closes.
        def opening(t):
            return 400 + 600 * math.sin(math.pi * min(1.0, t / length))

        def rounding(t):
            return 2300 - 1400 * min(1.0, t / length)

        return formant(voice, [(opening, 1.0), (rounding, 0.7), (3300, 0.25)], q=5.0)

    t = 0.3
    while t < DURATION:
        urgency = t / DURATION
        length = r.uniform(0.45, 0.8) + 0.3 * urgency
        mix.add(t, meow(r.uniform(520, 620) * (1 + 0.25 * urgency), length), 0.8)
        t += length + r.uniform(0.4, 1.0) * (1.2 - urgency)


def p_mosquito(r, mix):
    # The whine of a mosquito flying around your ear: closer, farther, and landing for a moment.
    f = r.uniform(520, 680)
    points = [(0.0, f)]
    amp = [(0.0, 0.3)]
    t = 0.0
    landed = 0.0
    while t < DURATION:
        if t - landed > 6.0 and r.random() < 0.08:
            amp += [(t + 0.1, 0.0), (t + r.uniform(0.6, 1.0), 0.0)]
            t = landed = amp[-1][0]
            points.append((t, f))
            continue
        t += r.uniform(0.15, 0.35)
        near = r.random() ** 2
        points.append((t, f * r.uniform(0.96, 1.04) * (1.0 + 0.03 * near)))
        amp.append((t, 0.15 + 0.85 * near))
    points.append((t + 0.2, f))
    amp.append((t + 0.2, 0.0))
    whine = glide("saw", points, amp=amp, vib_rate=r.uniform(17, 23), vib_depth=0.01, attack=0.05)
    mix.add(0.0, svf(whine, 350, 0.7, "high"), 0.8)


def p_rubber_duck(r, mix):
    # Squeezing a rubber duck: a squeak, then a wheezier one as it fills with air again.
    def squeak(f, length, squeeze, seed):
        pitch = [(0.0, f * 0.8), (length * 0.25, f * (1.15 if squeeze else 1.0)), (length, f * (0.9 if squeeze else 0.75))]
        amp = [(0.0, 0.0), (length * 0.15, 1.0), (length * 0.8, 0.8), (length, 0.0)]
        tone = glide("square", pitch, amp=amp, vib_rate=70.0, vib_depth=0.03)
        air = envelope(svf(noise(length, seed), f * 1.5, 1.5, "band"), amp)
        return layer((svf(tone, f * 1.8, 1.2, "band"), 1.0), (air, 0.4 if squeeze else 0.9))

    f = r.uniform(1500, 2200)
    squeezes = [(squeak(f, 0.2, True, 220), squeak(f * 0.8, 0.25, False, 221)),
                (squeak(f * 1.1, 0.14, True, 222), squeak(f * 0.85, 0.18, False, 223))]
    t = 0.2
    while t < DURATION:
        for _ in range(r.choice([1, 2, 2, 3])):
            press, release = r.choice(squeezes)
            mix.add(t, press, 0.8)
            t += len(press) / SR + r.uniform(0.04, 0.12)
            mix.add(t, release, 0.6)
            t += len(release) / SR + r.uniform(0.05, 0.2)
        t += r.uniform(0.3, 0.9)


def boing(f, rate):
    """A spring (cached): the pitch wobbles wildly, then settles while it dies away."""
    key = ("boing", round(f, 2), round(rate, 2))
    cached = _notes.get(key)
    if cached is not None:
        return cached
    n = int(0.8 * SR)
    wave_table = table("saw", max(1, min(48, int(SR * 0.45 / (f * 1.45)))))
    out = [0.0] * n
    pos = 0.0
    for i in range(n):
        t = i / SR
        out[i] = wave_table[int(pos) & MASK] * math.exp(-t / 0.25) * min(1.0, i / 40.0)
        pos += f * (1.0 + 0.45 * math.exp(-t / 0.15) * math.sin(TWO_PI * rate * t)) * TABLE_SIZE / SR
    out = layer((svf(out, 3000, 0.9), 1.0), (strike(f * 7.3, ((1.0, 1.0, 0.04),), 0.1), 0.3))
    _notes[key] = out
    return out


def p_springs(r, mix):
    # Cartoon springs: "boing!", bouncing lower and lower.
    springs = [boing(r.uniform(240, 380), r.uniform(9, 14)) for _ in range(3)]
    t = 0.2
    while t < DURATION:
        spring = r.choice(springs)
        interval = r.uniform(0.45, 0.6)
        gain = 0.9
        while interval > 0.12 and t < DURATION:
            mix.add(t, spring, gain)
            t += interval
            interval *= 0.7
            gain *= 0.8
        t += r.uniform(0.4, 0.8)
    trim_bass(mix)


def p_shepard(r, mix):
    # Shepard-Risset glissando: tones an octave apart that keep rising without ever getting higher.
    octave_time = r.uniform(6.0, 8.0)
    low = 40.0
    count = 8
    center = math.log2(r.uniform(600, 800))
    n = int(DURATION * SR)
    sine = table("sine", 1)
    out = [0.0] * n
    phases = [0.0] * count
    for start in range(0, n, 64):
        t = start / SR
        pulse = 0.75 + 0.25 * math.sin(TWO_PI * 4.0 * t)
        for k in range(count):
            f = low * 2 ** ((k + t / octave_time) % count)
            if f > SR * 0.45:
                continue
            gain = math.exp(-0.5 * ((math.log2(f) - center) / 1.1) ** 2) * pulse
            inc = f * TABLE_SIZE / SR
            pos = phases[k]
            for i in range(start, min(n, start + 64)):
                out[i] += sine[int(pos) & MASK] * gain
                pos += inc
            phases[k] = pos
    mix.add(0.0, out, 0.5)


def crush(samples, bits, hold):
    """Bit crusher: few amplitude levels, each sample held for a while."""
    levels = 2 ** bits
    out = []
    last = 0.0
    for i, v in enumerate(samples):
        if i % hold == 0:
            last = round(v * levels) / levels
        out.append(last)
    return out


def p_glitch(r, mix):
    # A computer crashing: stutters, bit-crushed bleeps, noise bursts and dying "tape stops", in loops that mutate.
    step = 60.0 / r.uniform(132, 148) / 4
    palette = [
        crush(note("square", r.uniform(2000, 5000), dur=0.05, attack=0.001, release=0.002), 3, 3),
        crush(note("saw", r.uniform(200, 600), dur=0.09, attack=0.001, release=0.005), 2, 8),
        crush(noise(0.03, 230), 2, 4),
        crush(note("sine", r.uniform(800, 1500), dur=0.06, attack=0.001, release=0.005), 4, 12),
        note("square", r.uniform(60, 120), dur=0.08, attack=0.001, release=0.005),
    ]
    tape_stop = glide("saw", [(0.0, 400.0), (0.35, 25.0)], amp=[(0.0, 1.0), (0.35, 0.0)])

    def bar_pattern():
        cells = []
        for _ in range(16):
            x = r.random()
            if x < 0.55:
                cells.append(r.choice(palette))
            elif x < 0.72:
                fragment = r.choice(palette)
                cells.append(fragment[: int(r.uniform(0.012, 0.03) * SR)] * r.randint(4, 10))
            else:
                cells.append(None)
        if r.random() < 0.5:
            cells[12:] = [tape_stop, None, None, None]
        return cells

    t = 0.0
    pattern = bar_pattern()
    bar = 0
    while t < DURATION:
        if bar % 2 == 0 and bar:
            pattern = [c if r.random() < 0.6 else r.choice(palette + [None]) for c in pattern]
        for s, cell in enumerate(pattern):
            if cell is not None:
                mix.add(t + s * step, cell, 0.5)
        t += 16 * step
        bar += 1


# A sound's file name and random seed come from its position in this list: add new
# sounds at the end so that the existing ones stay exactly the same.
SOUNDS = [
    ("Pitidos clásicos", lambda r, m: p_beeps(r, m, "square", (1900, 2300), (4, 4))),
    ("Sirena lenta", lambda r, m: p_siren(r, m, "saw")),
    ("Campanas de cristal", lambda r, m: p_arpeggio(r, m, "fm", "major")),
    ("Teléfono antiguo", lambda r, m: p_trill(r, m, "square")),
    ("Reloj digital", p_digital),
    ("Pájaros eléctricos", p_chirps),
    ("Morse: DESPIERTA", p_morse),
    ("Claxon", lambda r, m: p_klaxon(r, m, low=False)),
    ("Fanfarria", p_fanfare),
    ("Marimba nerviosa", lambda r, m: p_melody(r, m, "marimba", "pentatonic", True)),
    ("Sonar", p_sonar),
    ("Pulsos que aceleran", p_accelerating),
    ("Sirena europea", lambda r, m: p_hilo(r, m, "square")),
    ("Láseres", p_laser),
    ("Tambores y gong", p_drums),
    ("Grillos", p_cricket),
    ("Órgano", p_organ),
    ("Pelota que rebota", p_bounce),
    ("Escalera infinita", p_scale_runs),
    ("Sirena aullido", lambda r, m: p_siren(r, m, "square", fast=True)),
    ("Caja de música", lambda r, m: p_melody(r, m, "musicbox", "major", False)),
    ("Pitidos agudos", lambda r, m: p_beeps(r, m, "sine", (2800, 3600), (3, 3))),
    ("Arpegio menor", lambda r, m: p_arpeggio(r, m, "pluck", "minor")),
    ("Zumbador", lambda r, m: p_klaxon(r, m, low=True)),
    ("Robot parlanchín", p_robot),
    ("Campanario", p_bells),
    ("Alerta espacial", p_space_alert),
    ("Teletipo", p_teletype),
    ("Despertador de campana", lambda r, m: p_trill(r, m, hammer=True)),
    ("Tormenta de pitidos", p_beep_storm),
    ("Detector de humo", p_smoke_alarm),
    ("Marcha atrás", p_reversing),
    ("Sirena antiaérea", p_air_raid),
    ("Alarma de inmersión", p_dive_klaxon),
    ("Alarma de coche", p_car_alarm),
    ("Sirena de niebla", p_foghorn),
    ("Paso a nivel", p_crossing_bell),
    ("Bocina de tren", p_train_horn),
    ("Silbato de árbitro", p_referee),
    ("Walkie-talkie", p_walkie_talkie),
    ("Videojuego de 8 bits", p_chiptune),
    ("Toque de diana", p_bugle),
    ("Tambor metálico", p_steelpan),
    ("Handpan", p_handpan),
    ("Guitarra rasgueada", p_strum),
    ("Guitarra eléctrica", p_power_chords),
    ("Arpa", p_harp),
    ("Koto", p_koto),
    ("Theremin", p_theremin),
    ("Cumbia", p_cumbia),
    ("Gaita", p_bagpipe),
    ("Vibráfono", p_vibraphone),
    ("Trance", p_trance),
    ("Bajo ácido", p_acid),
    ("Coro", p_choir),
    ("Trompeta con sordina", p_wah_trumpet),
    ("Kazoo", p_kazoo),
    ("Organillero", p_barrel_organ),
    ("Mariachi", p_mariachi),
    ("Violín", p_fiddle),
    ("Dembow", p_dembow),
    ("Batucada", p_batucada),
    ("Taiko", p_taiko),
    ("Cencerro", p_cowbell),
    ("Palmas flamencas", p_palmas),
    ("Redoble militar", p_snare_cadence),
    ("Caracol y teponaztli", p_prehispanic),
    ("Scratch de DJ", p_scratch),
    ("Piano", p_piano),
    ("Didyeridú", p_didgeridoo),
    ("Timbre de la puerta", p_doorbell),
    ("Reloj cucú", p_cuckoo),
    ("Locomotora de vapor", p_steam_train),
    ("Carrito de camotes", p_camotero),
    ("Helicóptero", p_helicopter),
    ("Carrera de autos", p_race_cars),
    ("Módem", p_modem),
    ("Contador Geiger", p_geiger),
    ("Afilador", p_knife_grinder),
    ("Tragamonedas", p_slot_machine),
    ("Gallo", p_rooster),
    ("Gotas en la cueva", p_drops),
    ("Pájaro carpintero", p_woodpecker),
    ("Coro de ranas", p_frogs),
    ("Gato con hambre", p_cat),
    ("Mosquito", p_mosquito),
    ("Patito de hule", p_rubber_duck),
    ("Resortes", p_springs),
    ("Subida sin fin", p_shepard),
    ("Fallo del sistema", p_glitch),
]


def write_wav(path, samples):
    pcm = array.array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--count", type=int, default=len(SOUNDS), help="number of sounds (max %d)" % len(SOUNDS))
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for index, (title, pattern) in enumerate(SOUNDS[: args.count], start=1):
        name = "vigilia-%02d" % index
        _notes.clear()
        mix = Mix()
        pattern(random.Random(1000 + index), mix)
        write_wav(os.path.join(args.out, name + ".wav"), mix.finish())
        manifest.append({"file": name + ".caf", "title": title})
        print("  %s  %s" % (name, title))

    with open(os.path.join(args.out, "Sounds.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
