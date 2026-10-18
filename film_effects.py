"""Deterministic, bounded light-exposure fields in continuous roll coordinates.

These are authored visual simulations, not measured film response curves. The
same coordinates/seed drive preview and export; no source photograph is edited.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

EXPOSURE_STYLES = ("leak", "burn", "radial", "fog", "edge-burn", "ribbon")


def ivory_leader_field(size, start, end, aspect, strength=.75, softness=.55, seed=17):
    """Cream film base with a localized chromatic development boundary.

    The reference is a transmitted-light contact sheet: pale honey film, subtle
    emulsion variation and a pink/yellow/violet fringe at the photograph end.
    This is a material replacement confined to blank leader cells, not a light
    overlay on photographs. Coordinates stay continuous across row breaks.
    """
    w, h = min(size[0],1600), min(size[1],320)
    yy, xx = np.mgrid[0:h,0:w].astype(np.float32)
    p = start+(xx+.5)/w*(end-start)
    y = (yy+.5)/h
    x = p*aspect
    phases = np.random.default_rng(seed).uniform(0,2*np.pi,10)
    cloud = (.58*np.sin(x*1.7+y*3.1+phases[0])+
             .27*np.sin(x*5.3-y*7.9+phases[1])+
             .15*np.sin(x*15.7+y*13.1+phases[2]))
    grain = (np.sin(x*173+y*211+phases[3])*np.sin(x*251-y*137+phases[4])+
             .45*np.sin(x*397+y*353+phases[5]))
    # Thin longitudinal density variations are quiet enough to read as film,
    # not a dirty-paper filter. No simulated writing, barcode or brand is added.
    density = cloud*2.7+grain*.65+np.cos(y*np.pi)*2.2
    rgb = np.empty((h,w,3),dtype=np.float32)
    rgb[:] = (235,216,177)
    rgb += density[...,None]*np.array([.55,.85,1.05])
    rgb += (np.exp(-((y-.51)/.46)**2)*3)[...,None]
    # Work in film-height units so a six-frame leader doesn't grow a huge stripe.
    remaining = (1-p)*aspect
    undulation = .010*np.sin(y*8+phases[6])+.006*np.sin(y*27+phases[7])
    center = .24+undulation
    lower = .16+.84/(1+np.exp(-(y-.53)*9))
    width = .018+softness*.07
    yellow = np.exp(-((remaining-center-.13)/(width*1.35))**2)*lower
    pink = np.exp(-((remaining-center)/(width*.95))**2)*lower
    violet = np.exp(-((remaining-center+.075)/(width*.75))**2)*lower
    # Subtractive color absorption retains the translucent milky base, while a
    # narrow bright core reads like the burned emulsion edge in the reference.
    rgb -= strength*(yellow[...,None]*np.array([0,10,123])+
                     pink[...,None]*np.array([0,89,10])+
                     violet[...,None]*np.array([67,56,0]))
    core = np.exp(-((remaining-center-.055)/(.012+softness*.018))**2)*lower*strength*.38
    rgb = rgb*(1-core[...,None])+np.array([255,244,217])*core[...,None]
    # A very short, irregular dark tail joins the pale base to the dark strip.
    join_width = .012+softness*.025
    join = 1/(1+np.exp(np.clip((remaining-.025-undulation*.45)/join_width,-30,30)))
    rgb = rgb*(1-join[...,None]*.92)+np.array([28,23,33])*join[...,None]*.92
    return Image.fromarray(np.clip(np.rint(rgb),0,255).astype("uint8")).resize(size,Image.Resampling.BICUBIC)


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
