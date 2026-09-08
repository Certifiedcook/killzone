"""Definitions for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict
from typing import Tuple

APP_TITLE = "KILL ZONE — Realtime Tactical Infantry"
TILE = 28
MAP_W, MAP_H = (56, 36)
MAP_X, MAP_Y = (18, 66)
MAP_VIEW_W_PX, MAP_VIEW_H_PX = (39 * TILE, 20 * TILE)
SIDEBAR_X = MAP_X + MAP_VIEW_W_PX + 18
WINDOW_W, WINDOW_H = (SIDEBAR_X + 320, 790)
FPS = 0
SIM_DT = 1 / 30
Coord = Tuple[int, int]
COLORS = {
    "bg": (25, 29, 25),
    "panel": (42, 47, 40),
    "panel2": (55, 60, 51),
    "text": (222, 222, 198),
    "muted": (153, 157, 141),
    "white": (242, 242, 225),
    "black": (16, 17, 15),
    "select": (229, 210, 119),
    "player": (89, 145, 91),
    "enemy": (170, 73, 65),
    "objective": (212, 167, 74),
    "danger": (217, 91, 80),
    "good": (132, 175, 112),
    "contact": (220, 187, 107),
    "blue": (104, 145, 177),
    "open": (115, 102, 78),
    "road": (127, 114, 91),
    "trench": (72, 62, 49),
    "woods": (51, 76, 48),
    "wall": (102, 104, 96),
    "bunker": (69, 73, 65),
    "crater": (91, 77, 59),
    "mud": (78, 65, 49),
    "rubble": (102, 95, 83),
    "wire": (111, 107, 97),
    "sandbags": (122, 105, 73),
    "foxhole": (83, 70, 52),
    "hill": (137, 123, 91),
    "water": (57, 83, 91),
    "bridge": (110, 91, 62),
    "building": (86, 82, 73),
    "woodwall": (105, 82, 57),
    "window": (105, 113, 110),
    "door": (113, 84, 57),
    "mine": (134, 76, 57),
    "dugout": (58, 54, 46),
    "firing_step": (79, 68, 51),
    "smoke": (182, 184, 177),
    "fire": (222, 125, 55),
    "nato_friend": (92, 190, 232),
    "nato_hostile": (240, 96, 86),
    "blood": (111, 19, 18),
    "blood_dark": (63, 12, 12),
    "impact": (228, 205, 151),
    "suppression": (220, 165, 84),
    "status": (194, 211, 174),
}
TERRAIN: Dict[str, dict] = {
    "open": {
        "cover": 0,
        "move": 1.0,
        "blocks": False,
        "conceal": 0,
        "height": 0,
        "hp": None,
        "pen": 0,
    },
    "road": {
        "cover": 0,
        "move": 0.82,
        "blocks": False,
        "conceal": 0,
        "height": 0,
        "hp": None,
        "pen": 0,
    },
    "trench": {
        "cover": 4,
        "move": 0.72,
        "blocks": False,
        "conceal": 10,
        "height": -1,
        "hp": None,
        "pen": 0,
    },
    "woods": {
        "cover": 2,
        "move": 1.5,
        "blocks": False,
        "conceal": 26,
        "height": 0,
        "hp": 45,
        "pen": 1,
    },
    "wall": {
        "cover": 5,
        "move": 999,
        "blocks": True,
        "conceal": 0,
        "height": 1,
        "hp": 80,
        "pen": 4,
    },
    "bunker": {
        "cover": 5,
        "move": 1.35,
        "blocks": False,
        "conceal": 15,
        "height": 0,
        "hp": 150,
        "pen": 3,
    },
    "crater": {
        "cover": 2,
        "move": 1.35,
        "blocks": False,
        "conceal": 7,
        "height": -1,
        "hp": None,
        "pen": 0,
    },
    "mud": {
        "cover": 0,
        "move": 1.65,
        "blocks": False,
        "conceal": 0,
        "height": 0,
        "hp": None,
        "pen": 0,
    },
    "rubble": {
        "cover": 2,
        "move": 1.4,
        "blocks": False,
        "conceal": 6,
        "height": 0,
        "hp": None,
        "pen": 0,
    },
    "wire": {
        "cover": 0,
        "move": 2.8,
        "blocks": False,
        "conceal": 0,
        "height": 0,
        "hp": 30,
        "pen": 0,
    },
    "sandbags": {
        "cover": 3,
        "move": 1.35,
        "blocks": False,
        "conceal": 4,
        "height": 0,
        "hp": 55,
        "pen": 1,
    },
    "foxhole": {
        "cover": 3,
        "move": 0.9,
        "blocks": False,
        "conceal": 11,
        "height": -1,
        "hp": None,
        "pen": 0,
    },
    "hill": {
        "cover": 1,
        "move": 1.3,
        "blocks": False,
        "conceal": 0,
        "height": 1,
        "hp": None,
        "pen": 0,
    },
    "water": {
        "cover": 0,
        "move": 999,
        "blocks": True,
        "conceal": 0,
        "height": -1,
        "hp": None,
        "pen": 0,
    },
    "bridge": {
        "cover": 0,
        "move": 0.95,
        "blocks": False,
        "conceal": 0,
        "height": 0,
        "hp": 70,
        "pen": 1,
    },
    "building": {
        "cover": 5,
        "move": 999,
        "blocks": True,
        "conceal": 0,
        "height": 1,
        "hp": 105,
        "pen": 4,
    },
    "woodwall": {
        "cover": 4,
        "move": 999,
        "blocks": False,
        "conceal": 0,
        "height": 1,
        "hp": 55,
        "pen": 3,
    },
    "window": {
        "cover": 4,
        "move": 999,
        "blocks": False,
        "conceal": 2,
        "height": 1,
        "hp": 30,
        "pen": 1,
    },
    "door": {
        "cover": 2,
        "move": 1.0,
        "blocks": False,
        "conceal": 2,
        "height": 0,
        "hp": 35,
        "pen": 1,
    },
    "dugout": {
        "cover": 5,
        "move": 0.82,
        "blocks": False,
        "conceal": 22,
        "height": -1,
        "hp": 110,
        "pen": 3,
    },
    "firing_step": {
        "cover": 4,
        "move": 0.74,
        "blocks": False,
        "conceal": 8,
        "height": -1,
        "hp": None,
        "pen": 0,
    },
}
WEAPONS: Dict[str, dict] = {
    "Service Rifle": {
        "range": 11.0,
        "damage": 32,
        "acc": 62,
        "supp": 16,
        "rpm": 190,
        "mag": 20,
        "reload": 2.5,
        "heat": 2,
        "cool": 18,
        "pen": 2,
    },
    "SMG": {
        "range": 6.5,
        "damage": 23,
        "acc": 56,
        "supp": 18,
        "rpm": 520,
        "mag": 30,
        "reload": 2.2,
        "heat": 2,
        "cool": 19,
        "pen": 1,
    },
    "Automatic Rifle": {
        "range": 9.0,
        "damage": 27,
        "acc": 55,
        "supp": 27,
        "rpm": 430,
        "mag": 20,
        "reload": 2.6,
        "heat": 4,
        "cool": 17,
        "pen": 2,
    },
    "Light Machine Gun": {
        "range": 12.0,
        "damage": 28,
        "acc": 53,
        "supp": 46,
        "rpm": 600,
        "mag": 50,
        "reload": 4.6,
        "heat": 7,
        "cool": 12,
        "pen": 2,
    },
    "Heavy Machine Gun": {
        "range": 15.0,
        "damage": 38,
        "acc": 58,
        "supp": 65,
        "rpm": 520,
        "mag": 100,
        "reload": 6.0,
        "heat": 9,
        "cool": 10,
        "pen": 4,
    },
    "Scoped Rifle": {
        "range": 17.0,
        "damage": 84,
        "acc": 79,
        "supp": 34,
        "rpm": 45,
        "mag": 5,
        "reload": 3.0,
        "heat": 1,
        "cool": 25,
        "pen": 3,
    },
    "Marksman Rifle": {
        "range": 14.0,
        "damage": 48,
        "acc": 72,
        "supp": 23,
        "rpm": 120,
        "mag": 10,
        "reload": 2.8,
        "heat": 2,
        "cool": 22,
        "pen": 3,
    },
    "Carbine": {
        "range": 8.0,
        "damage": 28,
        "acc": 61,
        "supp": 17,
        "rpm": 300,
        "mag": 20,
        "reload": 2.2,
        "heat": 2,
        "cool": 20,
        "pen": 2,
    },
}
ROLES: Dict[str, dict] = {
    "Rifleman": {
        "hp": 100,
        "weapon": "Service Rifle",
        "speed": 2.55,
        "spot": 10.5,
        "mags": 5,
        "grenades": 2,
        "smoke": 1,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "Machine Gunner": {
        "hp": 120,
        "weapon": "Light Machine Gun",
        "speed": 2.15,
        "spot": 9.5,
        "mags": 4,
        "grenades": 0,
        "smoke": 0,
        "rifle_grenades": 0,
        "satchel": 0,
        "crew": 2,
    },
    "Sniper": {
        "hp": 75,
        "weapon": "Scoped Rifle",
        "speed": 2.4,
        "spot": 16.0,
        "mags": 6,
        "grenades": 0,
        "smoke": 1,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "Medic": {
        "hp": 90,
        "weapon": "Carbine",
        "speed": 2.55,
        "spot": 10.0,
        "mags": 4,
        "grenades": 0,
        "smoke": 2,
        "rifle_grenades": 0,
        "satchel": 0,
        "med": 5,
    },
    "Engineer": {
        "hp": 105,
        "weapon": "Carbine",
        "speed": 2.35,
        "spot": 10.0,
        "mags": 4,
        "grenades": 1,
        "smoke": 1,
        "rifle_grenades": 0,
        "satchel": 2,
        "tools": 5,
    },
    "Recon": {
        "hp": 80,
        "weapon": "Carbine",
        "speed": 3.1,
        "spot": 17.0,
        "mags": 4,
        "grenades": 0,
        "smoke": 2,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "Grenadier": {
        "hp": 95,
        "weapon": "Service Rifle",
        "speed": 2.45,
        "spot": 10.0,
        "mags": 4,
        "grenades": 3,
        "smoke": 1,
        "rifle_grenades": 4,
        "satchel": 0,
    },
    "Assault": {
        "hp": 105,
        "weapon": "SMG",
        "speed": 2.75,
        "spot": 9.0,
        "mags": 5,
        "grenades": 3,
        "smoke": 1,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "Automatic Rifleman": {
        "hp": 105,
        "weapon": "Automatic Rifle",
        "speed": 2.35,
        "spot": 9.5,
        "mags": 5,
        "grenades": 1,
        "smoke": 0,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "Marksman": {
        "hp": 90,
        "weapon": "Marksman Rifle",
        "speed": 2.45,
        "spot": 13.5,
        "mags": 5,
        "grenades": 1,
        "smoke": 1,
        "rifle_grenades": 0,
        "satchel": 0,
    },
    "HMG Crew": {
        "hp": 135,
        "weapon": "Heavy Machine Gun",
        "speed": 1.45,
        "spot": 10.5,
        "mags": 3,
        "grenades": 0,
        "smoke": 0,
        "rifle_grenades": 0,
        "satchel": 0,
        "crew": 2,
    },
    "Mortar Team": {
        "hp": 95,
        "weapon": "Carbine",
        "speed": 1.9,
        "spot": 9.0,
        "mags": 3,
        "grenades": 0,
        "smoke": 0,
        "rifle_grenades": 0,
        "satchel": 0,
        "mortar": 8,
    },
}
STANCE = {
    "standing": {"speed": 1.0, "hit": 0, "acc": 0, "spot": 0},
    "crouched": {"speed": 0.72, "hit": -8, "acc": 3, "spot": -1},
    "prone": {"speed": 0.38, "hit": -17, "acc": 7, "spot": -3},
}
DIFFICULTY = {
    "Easy": {"enemy": 8, "acc": 0, "ai": 0.72, "tactics": 0.55},
    "Hard": {"enemy": 11, "acc": 0, "ai": 0.42, "tactics": 1.0},
    "Veteran": {"enemy": 14, "acc": 0, "ai": 0.25, "tactics": 1.3},
}
PLAYER_ROLE_ORDER = [
    "Rifleman",
    "Machine Gunner",
    "Sniper",
    "Medic",
    "Engineer",
    "Recon",
    "Grenadier",
    "Assault",
    "Automatic Rifleman",
    "Marksman",
    "HMG Crew",
    "Mortar Team",
]
DEFAULT_PLAYER_ROSTER = [
    "Rifleman",
    "Rifleman",
    "Machine Gunner",
    "Sniper",
    "Medic",
    "Engineer",
    "Recon",
    "Grenadier",
    "Assault",
    "Automatic Rifleman",
    "Marksman",
    "HMG Crew",
    "Mortar Team",
]
MAX_PLAYER_UNITS = 16
MAX_ROLE_COUNT = 8
BASE_DIR = Path(__file__).resolve().parents[1]
ASSET_DIR = BASE_DIR / "assets"
AUDIO_DIR = ASSET_DIR / "audio"
FX_DIR = ASSET_DIR / "fx"
ASSET_MANIFEST = {
    "rifle_556.mp3": "https://raw.githubusercontent.com/euuuuuuan/fatal-funnel-public/main/apps/game/public/sfx/rifle_556.mp3",
    "rifle_762.mp3": "https://raw.githubusercontent.com/euuuuuuan/fatal-funnel-public/main/apps/game/public/sfx/rifle_762.mp3",
    "smg_9mm.mp3": "https://raw.githubusercontent.com/euuuuuuan/fatal-funnel-public/main/apps/game/public/sfx/smg_9mm.mp3",
    "explosion1.ogg": "https://opengameart.org/sites/default/files/explosion1_0.ogg",
    "explosion2.ogg": "https://opengameart.org/sites/default/files/explosion2.ogg",
    "hurt_01.mp3": "https://opengameart.org/sites/default/files/hurt_01_0.mp3",
    "hurt_03.mp3": "https://opengameart.org/sites/default/files/hurt_03.mp3",
    "scream_horror1.mp3": "https://opengameart.org/sites/default/files/scream_horror1_0.mp3",
    "blood_red.png": "https://opengameart.org/sites/default/files/blood_red_0.png",
}
MISSION_VARIANTS = {
    "farmland": {
        "name": "OPEN FARMLAND",
        "brief": "Prepared trench line across open agricultural ground. Smoke and support-by-fire are essential.",
    },
    "wooded_ridge": {
        "name": "WOODED RIDGE",
        "brief": "Broken woodland and folds in the ground provide covered approaches, but fields of fire open suddenly.",
    },
    "ruined_village": {
        "name": "RUINED VILLAGE",
        "brief": "A damaged settlement sits astride the approach. Expect short sight lines and strongpoint fighting.",
    },
    "hill_line": {
        "name": "RIDGELINE",
        "brief": "The defensive line sits on rising ground. Reverse slopes and dead ground matter more than raw distance.",
    },
}
ROLE_CONTACT = {
    "Rifleman": "INFANTRY",
    "Machine Gunner": "MACHINE GUN",
    "Sniper": "SNIPER",
    "Medic": "MEDIC",
    "Engineer": "ENGINEER",
    "Recon": "RECON",
    "Grenadier": "GRENADIER",
    "Assault": "ASSAULT INFANTRY",
    "Automatic Rifleman": "AUTOMATIC RIFLE",
    "Marksman": "MARKSMAN",
    "HMG Crew": "HEAVY MG",
    "Mortar Team": "MORTAR",
}
PLAYER_SURNAMES = [
    "Murphy",
    "Byrne",
    "Kelly",
    "Ryan",
    "Doyle",
    "Walsh",
    "Nolan",
    "Keane",
    "Moran",
    "Hayes",
    "Reilly",
    "Flynn",
    "Carroll",
    "Quinn",
    "Brennan",
    "Kavanagh",
    "Daly",
    "Foley",
    "Casey",
    "Murray",
    "OBrien",
    "Sullivan",
    "Lynch",
    "Power",
]
_vs_prev_draw_los = None
SQUAD_ROLE_GROUPS = {
    "assault": frozenset(("Rifleman", "Grenadier", "Assault")),
    "fire_support": frozenset(
        ("Machine Gunner", "Automatic Rifleman", "HMG Crew", "Mortar Team")
    ),
    "recon": frozenset(("Recon", "Marksman", "Sniper")),
    "support": frozenset(("Medic", "Engineer")),
}
_SQUAD_GROUP_BY_ROLE = {
    role: group for group, roles in SQUAD_ROLE_GROUPS.items() for role in roles
}
_SQUAD_FALLBACK_AFFINITY = {
    "assault": ("fire_support", "support", "recon"),
    "fire_support": ("assault", "support", "recon"),
    "recon": ("support", "fire_support", "assault"),
    "support": ("recon", "assault", "fire_support"),
}
AUTO_SQUAD_SIZE = 4
AUTO_SQUAD_LIMIT = 5
SQUAD_VISUAL_COLORS = (
    (226, 190, 92),
    (91, 171, 222),
    (126, 190, 126),
    (211, 132, 157),
    (174, 144, 220),
    (225, 146, 91),
    (91, 186, 174),
    (188, 193, 184),
    (218, 207, 117),
)
_SQUAD_TACTICAL_LABELS = {
    "assault": "ASSAULT",
    "fire_support": "FIRE SUP",
    "recon": "RECON",
    "support": "SUPPORT",
}
COMMAND_BAR_HELP_COLUMNS = (
    (
        (
            "ASSAULT",
            "TARGET",
            "Coordinates support fire, smoke and an assault toward the objective.",
        ),
        (
            "SUPPRESS",
            "TARGET",
            "Orders capable automatic weapons to suppress the chosen area.",
        ),
        (
            "OVERWATCH",
            "TARGET",
            "Establishes reaction-fire arcs facing the right-clicked point.",
        ),
        (
            "GRENADE",
            "TARGET",
            "Throws fragmentation grenades from selected troops that carry them.",
        ),
        (
            "SMOKE",
            "TARGET",
            "Throws smoke grenades to block observation and incoming fire.",
        ),
        (
            "BOUND",
            "TARGET",
            "Alternates moving and covering elements toward a destination.",
        ),
        (
            "FALLBACK",
            "TARGET",
            "Sets a rally point used when troops withdraw or recover.",
        ),
    ),
    (
        (
            "RELOAD",
            "INSTANT",
            "Starts reloading every selected troop that can currently reload.",
        ),
        (
            "STANCE",
            "CYCLE",
            "Cycles standing, crouched and prone for speed versus protection.",
        ),
        (
            "FORMATION",
            "WEDGE etc.",
            "The label is current formation; cycles wedge, line, column and spread.",
        ),
        (
            "DISCIPLINE",
            "FREE etc.",
            "Controls hold/return/free/confident fire, including less-accurate moving shots.",
        ),
        (
            "PRIORITY",
            "SPECIALIST etc.",
            "Cycles nearest, exposed, specialist and suppressed targets.",
        ),
        (
            "AUTO",
            "ON / OFF",
            "Toggles automatic reload, cover reaction, smoke and medic assistance.",
        ),
        (
            "HOLD",
            "TOGGLE",
            "Delays breaking and prevents automatic survival movement while enabled.",
        ),
    ),
)
QOL_TARGET_MODES = {
    "ASSAULT": "assault",
    "SUPPRESS": "suppress",
    "OVERWATCH": "overwatch",
    "GRENADE": "grenade",
    "SMOKE": "smoke",
    "BOUND": "bound",
    "FALLBACK": "fallback",
}
COMMAND_BAR_TOOLTIPS = {
    button: description
    for column in COMMAND_BAR_HELP_COLUMNS
    for button, _gesture, description in column
}
UI_SCALE_CHOICES = (0.9, 1.0, 1.1)
PERSISTED_SETTING_DEFAULTS = {
    "display_mode": "windowed",
    "last_fullscreen_mode": "borderless",
    "menu_speed": 1.0,
    "menu_show_help": True,
    "audio_enabled": True,
    "show_fps": False,
    "show_perf": False,
    "fps_cap": 0,
    "ui_scale": 1.0,
    "large_text": False,
}
_FULLSCREEN_LOGICAL_EVENT_FLAG = "_killzone_logical_position"
TACTICAL_AUDIO_VOLUMES = {
    "select": 0.1,
    "command": 0.14,
    "deny": 0.15,
    "contact": 0.16,
    "warning": 0.19,
    "casualty": 0.18,
    "objective": 0.18,
}
MOVING_FIRE_ACCURACY_PENALTY = 28.0
MOVING_FIRE_EXCLUDED_ROLES = frozenset(("HMG Crew", "Mortar Team"))
OPERATION_MISSIONS = ("assault", "defense")
OPERATION_VARIANTS = ("auto", "farmland", "wooded_ridge", "ruined_village", "hill_line")
OPERATION_WEATHER = ("auto", "clear", "rain", "fog")
OPERATION_ENEMY_STRENGTHS = (0.8, 1.0, 1.25)
OPERATION_DEFENSE_DURATIONS = (180, 300, 420)
SQUAD_DOCTRINES = ("cautious", "balanced", "aggressive")
STATIC_WEAPON_ROLES = frozenset(("MG Emplacement", "Field Gun", "Artillery Battery"))
DEFENSE_ATTACK_SECTORS = ("NORTH", "CENTRE", "SOUTH")
DEFENSE_FIRE_SUPPORT_ROLES = frozenset(
    ("Machine Gunner", "HMG Crew", "Mortar Team", "Marksman", "Sniper")
)
DEFENSE_BREACH_ROLES = frozenset(("Assault", "Grenadier"))
DEFENSE_SUSTAINMENT_ROLES = frozenset(("Medic", "Engineer"))
EMPLACEMENT_VISUALS = {
    "MG Emplacement": {"label": "MG", "silhouette": "bunker_mount"},
    "Field Gun": {"label": "GUN", "silhouette": "wheeled_gun"},
    "Artillery Battery": {"label": "ART", "silhouette": "heavy_howitzer"},
}
WEAPONS.update(
    {
        "Emplaced Machine Gun": {
            "range": 17.0,
            "damage": 36,
            "acc": 64,
            "supp": 72,
            "rpm": 470,
            "mag": 160,
            "reload": 7.0,
            "heat": 7,
            "cool": 13,
            "pen": 4,
        },
        "Field Gun": {
            "range": 21.0,
            "damage": 118,
            "acc": 69,
            "supp": 82,
            "rpm": 13,
            "mag": 8,
            "reload": 6.5,
            "heat": 5,
            "cool": 18,
            "pen": 9,
        },
    }
)
ROLES.update(
    {
        "MG Emplacement": {
            "hp": 185,
            "weapon": "Emplaced Machine Gun",
            "speed": 0.01,
            "spot": 12.0,
            "mags": 3,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 2,
        },
        "Field Gun": {
            "hp": 220,
            "weapon": "Field Gun",
            "speed": 0.01,
            "spot": 12.5,
            "mags": 3,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 3,
        },
        "Artillery Battery": {
            "hp": 195,
            "weapon": "Carbine",
            "speed": 0.01,
            "spot": 8.0,
            "mags": 2,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 4,
        },
    }
)
ROLE_CONTACT.update(
    {
        "MG Emplacement": "MG NEST",
        "Field Gun": "FIELD GUN",
        "Artillery Battery": "ARTILLERY",
    }
)
ENGINEER_BUILD_TYPES = {
    "sandbags": {
        "label": "SANDBAGS",
        "description": "Protected firing position · 4 sec",
        "seconds": 4.0,
        "terrain": "sandbags",
    },
    "wire": {
        "label": "WIRE",
        "description": "Slows an assault and marks a barrier · 4 sec",
        "seconds": 4.0,
        "terrain": "wire",
    },
    "trench": {
        "label": "TRENCH",
        "description": "Durable infantry cover · 7 sec",
        "seconds": 7.0,
        "terrain": "trench",
    },
    "mg_nest": {
        "label": "MG TURRET",
        "description": "Direct-fire suppression emplacement · 8 sec",
        "seconds": 8.0,
        "role": "MG Emplacement",
    },
    "field_gun": {
        "label": "FIELD GUN",
        "description": "Slow, powerful direct-fire weapon · 10 sec",
        "seconds": 10.0,
        "role": "Field Gun",
    },
    "artillery": {
        "label": "ARTILLERY",
        "description": "Long-range indirect HE battery · 12 sec",
        "seconds": 12.0,
        "role": "Artillery Battery",
    },
}
NETWORK_PVP_BATTLEFIELDS = ("farmland", "wooded_ridge", "ruined_village", "hill_line")
NETWORK_PVP_DEFAULT_ROSTER = (
    "Rifleman",
    "Rifleman",
    "Machine Gunner",
    "Marksman",
    "Medic",
    "Engineer",
    "Recon",
    "Grenadier",
    "Assault",
    "Automatic Rifleman",
)
NETWORK_UNIT_FIELDS = (
    "x",
    "y",
    "hp",
    "max_hp",
    "casualty",
    "bleed",
    "suppression",
    "morale",
    "morale_state",
    "cohesion",
    "squad_morale",
    "ammo",
    "magazines",
    "grenades",
    "smoke_grenades",
    "rifle_grenades",
    "satchel",
    "med_supplies",
    "tools",
    "mortar_shells",
    "artillery_shells",
    "order",
    "stance",
    "move_mode",
    "fire_mode",
    "fire_discipline",
    "target_priority",
    "facing",
    "deployed",
    "overwatch",
    "fire_lane",
    "fire_lane_center",
    "arc_width",
    "arc_range",
    "hold_position",
    "target_uid",
    "target_pos",
    "path",
    "waypoints",
    "action_timer",
    "reload_timer",
    "heat",
    "jammed",
    "stamina",
    "momentum",
    "prepared",
    "bayonet",
    "assistant_alive",
    "crew",
    "squad_id",
    "display_name",
    "is_emplacement",
)
PRESENTATION_AUDIO_DURATIONS = {
    "rifle": 0.16,
    "heavy": 0.22,
    "smg": 0.11,
    "distant": 0.3,
    "crack": 0.075,
    "mechanical": 0.09,
    "blast": 0.42,
    "rumble": 0.82,
    "debris": 0.32,
    "wind": 2.3,
    "rain": 1.8,
    "fire": 1.25,
    "heartbeat": 0.72,
}
COMBAT2_FIRST_NAMES = (
    "Aidan",
    "Alex",
    "Arthur",
    "Ben",
    "Callum",
    "Charlie",
    "Conor",
    "Daniel",
    "Darragh",
    "Declan",
    "Elliot",
    "Eoin",
    "Evan",
    "Finn",
    "George",
    "Harry",
    "Hugo",
    "Isaac",
    "Jack",
    "James",
    "Jamie",
    "Joseph",
    "Kieran",
    "Leo",
    "Liam",
    "Lucas",
    "Max",
    "Michael",
    "Nathan",
    "Noah",
    "Oliver",
    "Oscar",
    "Patrick",
    "Ronan",
    "Sam",
    "Sean",
    "Theo",
    "Thomas",
    "William",
    "Zach",
)
COMBAT2_SURNAMES = (
    "Adams",
    "Baker",
    "Bell",
    "Bennett",
    "Brennan",
    "Brown",
    "Burke",
    "Byrne",
    "Campbell",
    "Clarke",
    "Collins",
    "Cooper",
    "Daly",
    "Doyle",
    "Duffy",
    "Evans",
    "Farrell",
    "Fitzgerald",
    "Flynn",
    "Foster",
    "Gallagher",
    "Graham",
    "Grant",
    "Hayes",
    "Hughes",
    "Kelly",
    "Kennedy",
    "Lynch",
    "Martin",
    "McCarthy",
    "McDonnell",
    "Miller",
    "Moore",
    "Morgan",
    "Murphy",
    "Murray",
    "Nolan",
    "O'Brien",
    "O'Connor",
    "O'Neill",
)
COMBAT2_CALLSIGNS = (
    "Badger",
    "Bishop",
    "Bolt",
    "Brass",
    "Comet",
    "Crow",
    "Echo",
    "Flint",
    "Fox",
    "Ghost",
    "Hawkeye",
    "Iceman",
    "Kestrel",
    "Mako",
    "Nomad",
    "Rook",
    "Scout",
    "Slate",
    "Sparrow",
    "Torch",
    "Viper",
    "Wolf",
    "Wren",
    "Zero",
)
SOLDIER_IDENTITY_COMBINATIONS = len(COMBAT2_FIRST_NAMES) * len(COMBAT2_SURNAMES)
COMBAT2_STATIC_ROLES = frozenset(STATIC_WEAPON_ROLES)
COMBAT2_SUPPORT_ROLES = frozenset(
    (
        "Machine Gunner",
        "HMG Crew",
        "Automatic Rifleman",
        "Marksman",
        "Sniper",
        "Mortar Team",
    )
)
COMBAT2_ASSAULT_ROLES = frozenset(("Assault", "Rifleman", "Grenadier", "Recon"))
COMBAT2_SUSTAINMENT_ROLES = frozenset(("Medic", "Engineer"))
COMBAT2_WOUND_LABELS = {
    "head": "head trauma",
    "torso": "torso wound",
    "arm": "arm wound",
    "leg": "leg wound",
}
NETWORK_UNIT_FIELDS = tuple(NETWORK_UNIT_FIELDS) + tuple(
    (
        field_name
        for field_name in (
            "identity_index",
            "first_name",
            "surname",
            "full_name",
            "callsign",
            "wound_head",
            "wound_torso",
            "wound_arm",
            "wound_leg",
            "wound_treated",
            "combat2_exposed_until",
            "combat2_settle_until",
            "combat2_assignment",
            "combat2_phase",
            "combat2_plan_target",
            "combat2_decision_reason",
        )
        if field_name not in NETWORK_UNIT_FIELDS
    )
)
COMBAT_POLISH_WEAPON_PROFILES = {
    "SMG": {"burst": (3, 5), "pause": (0.22, 0.42), "recoil": 3.0, "cadence": 0.92},
    "Carbine": {"burst": (2, 4), "pause": (0.26, 0.48), "recoil": 2.7, "cadence": 0.96},
    "Service Rifle": {
        "burst": (2, 3),
        "pause": (0.32, 0.58),
        "recoil": 3.1,
        "cadence": 1.02,
    },
    "Automatic Rifle": {
        "burst": (3, 5),
        "pause": (0.3, 0.52),
        "recoil": 3.2,
        "cadence": 0.96,
    },
    "Light Machine Gun": {
        "burst": (5, 8),
        "pause": (0.42, 0.72),
        "recoil": 2.4,
        "cadence": 0.94,
    },
    "Heavy Machine Gun": {
        "burst": (6, 10),
        "pause": (0.48, 0.82),
        "recoil": 1.9,
        "cadence": 0.94,
    },
    "Marksman Rifle": {
        "burst": (1, 2),
        "pause": (0.46, 0.78),
        "recoil": 4.0,
        "cadence": 1.06,
    },
    "Scoped Rifle": {
        "burst": (1, 1),
        "pause": (0.7, 1.05),
        "recoil": 4.8,
        "cadence": 1.08,
    },
}
COMBAT_POLISH_DEFAULT_PROFILE = {
    "burst": (2, 3),
    "pause": (0.3, 0.55),
    "recoil": 3.0,
    "cadence": 1.0,
}
COMBAT_POLISH_STATIC_ROLES = frozenset(STATIC_WEAPON_ROLES)
COMBAT_POLISH_COMMIT_ORDERS = frozenset(
    ("move", "fire", "suppress", "overwatch", "fire_lane", "deploy", "pack", "build")
)
NETWORK_UNIT_FIELDS = tuple(NETWORK_UNIT_FIELDS) + tuple(
    (
        field_name
        for field_name in (
            "polish_recoil",
            "polish_reaction_until",
            "polish_reaction_kind",
            "polish_order_state",
            "polish_order_state_until",
            "polish_lane_reason",
            "polish_lane_blocked_until",
            "polish_wait_reason",
            "polish_arrival_facing",
        )
        if field_name not in NETWORK_UNIT_FIELDS
    )
)
PERSISTED_SETTING_DEFAULTS.update(
    {"camera_shake_enabled": True, "edge_scroll_enabled": True}
)
