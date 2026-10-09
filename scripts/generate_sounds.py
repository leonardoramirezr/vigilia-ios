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
