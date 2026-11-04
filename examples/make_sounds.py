"""Synthesize seamless placeholder loops for the Timberjack example (stand-ins for real
recordings): wind through a forest (an ambience bed) and a diesel idling (an emitter).
Noise is made in the frequency domain over the whole loop, so it repeats without a seam."""
import os
import wave
import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")


def periodic_noise(n, shape, rng):
    f = np.fft.rfftfreq(n, 1 / SR)
    spec = shape(np.maximum(f, 1.0)) * np.exp(2j * np.pi * rng.random(len(f)))
    spec[0] = 0
    x = np.fft.irfft(spec, n)
    return x / np.abs(x).max()


def save(name, x):
    x = (x / np.abs(x).max() * 0.7 * 32767).astype(np.int16)
    with wave.open(os.path.join(OUT, name), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(x.tobytes())


def wind(seconds=40, seed=1):
    rng = np.random.default_rng(seed)
    n = SR * seconds
    t = np.arange(n) / SR
    # Leaves: a hiss with a broad hump round 600 Hz; trunks and air: a low roar.
    leaves = periodic_noise(n, lambda f: np.exp(-((np.log(f / 700)) ** 2) / 1.2) / np.sqrt(f / 200 + 1), rng)
    roar = periodic_noise(n, lambda f: 1 / (1 + (f / 120) ** 2), rng)
    # Gusts: slow swells that repeat exactly over the loop.
    g = sum(a * np.sin(2 * np.pi * k * t / seconds + p)
            for k, a, p in ((1, 0.5, 0.3), (3, 0.35, 1.7), (7, 0.2, 4.1), (13, 0.12, 2.2)))
    gust = 0.55 + 0.45 * (g - g.min()) / (g.max() - g.min())
    return (0.6 * leaves * gust ** 1.6 + 0.5 * roar * gust)


def diesel(seconds=12, seed=2, rpm=780, cylinders=6):
    rng = np.random.default_rng(seed)
    n = SR * seconds
    t = np.arange(n) / SR
    fire = rpm / 60 * cylinders / 2                     # firing pulses per second (39 Hz)
    fire = round(fire * seconds) / seconds              # a whole number of pulses per loop
    x = np.zeros(n)
    for k, a in ((1, 1.0), (2, 0.6), (3, 0.45), (4, 0.25), (6, 0.15), (8, 0.08)):
        x += a * np.sin(2 * np.pi * k * fire * t + rng.random() * 6.28)
    half = round(fire / 2 * seconds) / seconds          # a slight lope at half firing
    x *= 1 + 0.12 * np.sin(2 * np.pi * half * t)
    clatter = periodic_noise(n, lambda f: np.exp(-((np.log(f / 1800)) ** 2) / 0.5), rng)
    x += 0.25 * clatter * (0.5 + 0.5 * np.sin(2 * np.pi * fire * t) ** 8)
    x += 0.2 * periodic_noise(n, lambda f: 1 / (1 + (f / 300) ** 2), rng)    # exhaust breath
    return x


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    save("forest_wind.wav", wind())
    save("diesel_idle.wav", diesel())
    print("wrote", os.listdir(OUT))
