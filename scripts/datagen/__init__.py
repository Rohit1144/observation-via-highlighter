"""Mock Highlighter dataset generator.

config.py        fixed seed, date range, taxonomy (types, severities, resolve times)
sites.py         the 12 site profiles and the planted stories/traps
observations.py  how a single observation is sampled (severity, confidence, status)
build.py         the day-by-day generation loop and final formatting
"""

from .build import generate

__all__ = ["generate"]
