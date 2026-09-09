"""Optional presentation dependency; never imported by the simulation."""

try:
    import pygame
except ImportError:
    pygame = None
