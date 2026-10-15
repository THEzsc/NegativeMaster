"""Deterministic, bounded light-exposure fields in continuous roll coordinates.

These are authored visual simulations, not measured film response curves. The
same coordinates/seed drive preview and export; no source photograph is edited.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

EXPOSURE_STYLES = ("leak", "burn", "radial", "fog", "edge-burn", "ribbon")


def exposure_field(size, start, end, aspect, style, strength, softness=.55, seed=17):
    """Return RGB screen-blend light, fading out at the end of the affected span."""
    w, h = min(size[0], 1600), min(size[1], 320)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    p = start + (xx+.5)/w * (end-start)
    y = (yy+.5)/h
    x = p*aspect
    rng = np.random.default_rng(seed)
    phases = rng.uniform(0, 2*np.pi, 12)
    # A sum of spatial frequencies avoids tiled noise and scan-size-dependent RNG.
    cloud = (.48*np.sin(x*3.7+y*5.1+phases[0]) +
             .29*np.sin(x*9.3-y*11.7+phases[1]) +
             .15*np.sin(x*24.1+y*31.3+phases[2]) +
             .08*np.sin(x*67.3-y*79.1+phases[3]))
    rough = (.74*np.sin(y*12+phases[4])+.21*np.sin(y*43+phases[5])+
             .05*np.sin(y*117+phases[6]))
    fade = np.maximum(0, 1-p)**2.1
    soft = .025 + softness*.13
    if style == "fog":
        veil = np.exp(-((y-.29-.035*cloud)/(.20+softness*.3))**2)
        fine = np.exp(-((y-.12-.018*cloud)/(.018+softness*.04))**2)
        energy = (veil*.58+fine*.20+.06)*(1+.13*cloud)*fade*strength
        tint = np.array([1.8, .48, 1.05], dtype=np.float32)
    elif style == "edge-burn":
        # Irregular intrusion depth; a warm fringe surrounds the broad white core.
        top = .10+.14*np.sin(x*1.6+phases[0])+.055*cloud
        bottom = .17+.14*np.sin(x*2.1+phases[1])+.065*cloud
        intrusion = np.maximum(top-y, bottom-(1-y))
        heat = 1/(1+np.exp(np.clip(-intrusion/soft, -30, 30)))
        energy = (heat*4.8 + np.maximum(0,cloud)*.18)*fade*strength
        tint = np.array([3.6, .95, .26], dtype=np.float32)
    elif style == "ribbon":
        center = .13 + .018*rough + .012*np.sin(y*5+phases[7])
        width = .025 + softness*.045
        ribbon = np.exp(-((p-center)/width)**2)
        ghost = np.exp(-((p-center-.12)/(.018+softness*.03))**2)*.35
        # Fainter secondary seams make extended exposure visible in photographs,
        # without resetting the pattern at each frame or creating hard dividers.
        seams = (2.8*np.exp(-((p-.43-.012*rough)/(.012+softness*.022))**2)+
                 2.2*np.exp(-((p-.70-.016*rough)/(.018+softness*.026))**2)+
                 1.6*np.exp(-((p-.87-.006*rough)/(.009+softness*.014))**2))
        left = np.exp(-p/(.045+softness*.06))*.8
        energy = (ribbon*3.8+ghost+seams+left)*(1+.26*cloud)*fade*strength
        tint = np.array([4.4, .73, .16], dtype=np.float32)
    elif style == "radial":
        def fan(origin, distance, phase):
            dx = x-origin
            angle = np.arctan2(dx,distance)
            # Unequal, soft lobes instead of evenly spaced hard laser rays.
            rays = (.58+.22*np.cos(angle*6.4+phase)+.12*np.cos(angle*11.3-phase))
            return rays*np.exp(-np.sqrt(dx*dx+distance*distance)/(1.35+softness*.6))
        heat = fan(aspect*.035,y+.12,phases[8])+fan(aspect*.12,1.12-y,phases[9])
        energy = heat*(1+.16*cloud)*fade*strength*2.5
        tint = np.array([3.5, .9, .24], dtype=np.float32)
    elif style == "burn":
        energy = (1.9+(.24-.16*softness)*cloud)*fade**(.55+softness*.55)*strength*3
        tint = np.array([2.7, 1.15, .4], dtype=np.float32)
    else:
        edge = np.exp(-((y-.18)/(.18+softness*.35))**2)
        energy = (1+.35*edge)*(1+.10*cloud)*fade*strength
        tint = np.array([3.1, .55, .12], dtype=np.float32)
    energy = np.maximum(0, energy)
    # High exposures lose saturation into a warm white core, low ones stay red.
    white = np.maximum(0, energy-1.5)[...,None]*.85
    rgb = 255*(1-np.exp(-(energy[...,None]*tint+white)))
    grain = np.sin(x*211+y*427+phases[10])*np.sin(x*337-y*263+phases[11])
    rgb += grain[...,None]*np.minimum(energy,1)[...,None]*1.6
    return Image.fromarray(np.clip(np.rint(rgb),0,255).astype("uint8")).resize(size,Image.Resampling.BICUBIC)
