#!/usr/bin/env python3
"""Compose the original 120 BPM synth score and UI sounds using only Python's stdlib."""
from array import array
from math import sin, pi, exp, tanh
from pathlib import Path
import random
import wave

RATE = 44100
MEDIA = Path(__file__).resolve().parent / 'media'
TAU = 2 * pi
random.seed(20261004)

def write(name, data):
    pcm = array('h', (int(max(-1, min(1, x)) * 32767) for x in data))
    import sys
    if sys.byteorder != 'little':
        pcm.byteswap()
    with wave.open(str(MEDIA / name), 'wb') as wav:
        wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm.tobytes())

def midi(n):
    return 440 * 2 ** ((n - 69) / 12)

def place(data, start, duration, fn, gain=1):
    offset = round(start * RATE)
    for i in range(min(round(duration * RATE), len(data) - offset)):
        t = i / RATE
        data[offset + i] += gain * fn(t, duration)

def pluck(freq):
    return lambda t, d: (sin(TAU * freq * t) + .28 * sin(TAU * freq * 2 * t)) * (1 - exp(-t * 400)) * exp(-t * 8)

music = [0.] * (34 * RATE)
# Cmaj7 - Am7 - Fmaj7 - G6, a light groove with a sparse pentatonic melody.
chords = [(48, 60, 64, 67, 71), (45, 57, 60, 64, 67), (41, 57, 60, 64, 69), (43, 55, 59, 62, 67)]
for bar in range(17):
    base, *chord = chords[bar % 4]
    at = bar * 2
    for beat in range(4):
        b = at + beat * .5
        place(music, b, .3, lambda t,d: sin(TAU*(47*t + 10*(1-exp(-t*32))/32))*exp(-t*16), .36)
        place(music, b, .35, pluck(midi(base)), .23)
        if beat % 2:
            place(music, b, .14, lambda t,d: random.uniform(-1,1)*exp(-t*32), .12)
        for half in (0, .25):
            place(music, b+half, .055, lambda t,d: random.uniform(-1,1)*exp(-t*95), .055 if half else .035)
    for k in range(8):
        n = chord[k % 4] + (12 if k in (3,7) else 0)
        place(music, at + k*.25 + .125, .4, pluck(midi(n)), .14)
    for n in chord:
        place(music, at+.5, 1.25, lambda t,d,f=midi(n): sin(TAU*f*t)*min(t/.1,1)*min((d-t)/.3,1), .026)
# A short melodic motif, with breathing space around the explanation.
for start in (0., 8., 16., 24., 28.):
    for off,n in [(0.,76),(.5,79),(.75,81),(1.5,79),(2.,74),(2.75,72)]:
        if start+off<33:
            place(music,start+off,.5,pluck(midi(n)),.16)
for i in range(len(music)):
    music[i] = tanh(music[i]*1.15)*.9
write('music.wav',music)

pop=[0.]*int(.16*RATE)
place(pop,0,.16,lambda t,d: sin(TAU*(750*t-1500*t*t))*exp(-t*32)*(1-exp(-t*900)),.55)
write('pop.wav',pop)
tick=[0.]*int(.045*RATE)
place(tick,0,.045,lambda t,d: (sin(TAU*1450*t)*.4+random.uniform(-1,1)*.6)*exp(-t*110)*(1-exp(-t*1300)),.4)
write('tick.wav',tick)
whoosh=[0.]*int(.3*RATE)
place(whoosh,0,.3,lambda t,d: (random.uniform(-1,1)*.5+sin(TAU*(280*t+900*t*t))*.12)*sin(pi*t/d)**2,.28)
write('whoosh.wav',whoosh)
success=[0.]*int(1.1*RATE)
for at,n in [(0.,72),(.10,76),(.20,79),(.30,84)]:
    place(success,at,.7,pluck(midi(n)),.35)
write('success.wav',success)
print('Wrote original score and four sound effects.')
