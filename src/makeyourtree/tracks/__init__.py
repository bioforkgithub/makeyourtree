# SPDX-License-Identifier: MIT
"""Annotation tracks.

Importing this package registers every built-in track type.  See
:mod:`makeyourtree.tracks.base` for the contract a track implements, and note that
tracks draw exclusively in band space so that one implementation serves every
layout mode.
"""
from .base import (Legend, LegendItem, Track, TrackContext, TrackData,
                   get_track_class, register, track_types)

# Importing for the registration side effect; the registry is the public index.
from . import (bars, binary, boxplot, connections, domains, gradient, heatmap,  # noqa: F401
               line, pie, ranges, strip, symbols, text)

__all__ = ["Track", "TrackData", "TrackContext", "Legend", "LegendItem",
           "register", "get_track_class", "track_types"]
