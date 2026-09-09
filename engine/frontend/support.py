"""Frontend / support for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations

from engine.definitions import ASSET_MANIFEST
from engine.definitions import AUDIO_DIR
from engine.definitions import COLORS
from engine.definitions import COMBAT2_STATIC_ROLES
from engine.definitions import FX_DIR
from engine.definitions import MAP_Y
from engine.definitions import PERSISTED_SETTING_DEFAULTS
from engine.definitions import UI_SCALE_CHOICES
from engine.definitions import WINDOW_H
from engine.definitions import WINDOW_W
from engine.frontend.backend import pygame
from pathlib import Path
import json
import math
import os
import threading
import urllib.request


def _base_bootstrap_assets_async():
    """Fetch optional CC0 presentation assets without blocking startup."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    FX_DIR.mkdir(parents=True, exist_ok=True)

    def worker():
        for name, url in ASSET_MANIFEST.items():
            dest = (FX_DIR if name.endswith(".png") else AUDIO_DIR) / name
            if dest.exists() and dest.stat().st_size > 128:
                continue
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "KillZone/0.4"}
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read()
                if len(data) > 128:
                    dest.write_bytes(data)
            except Exception:
                pass

    threading.Thread(target=worker, name="killzone-assets", daemon=True).start()


def main():
    from engine.frontend.app import KillZoneApp

    if pygame is None:
        print(
            "Kill Zone Realtime requires pygame. Install with: py -m pip install pygame"
        )
        raise SystemExit(1)
    app = KillZoneApp()
    app.run()


def bootstrap_assets_async():
    """Start optional downloads unless explicitly disabled for tests/offline use."""
    if os.environ.get("KILLZONE_DISABLE_ASSET_DOWNLOADS", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return None
    return _base_bootstrap_assets_async()


def _base__qol_notify(app, text, kind="info", duration=1.8):
    app.message = text
    game = getattr(app, "game", None)
    if game is not None and hasattr(game, "notify"):
        game.notify(text, kind=kind, duration=duration)


def command_button_status(app, button, units=None):
    """Return (enabled, reason) for a command-bar button."""
    units = list(app.selected_units() if units is None else units)
    if not units:
        return (False, "Select one or more troops first")
    if button == "SUPPRESS":
        capable = [
            unit
            for unit in units
            if unit.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman")
            and unit.ammo > 0
            and (not unit.jammed)
        ]
        return (True, "") if capable else (False, "Requires an armed automatic weapon")
    if button == "OVERWATCH":
        capable = [unit for unit in units if unit.ammo > 0 and (not unit.jammed)]
        return (
            (True, "")
            if capable
            else (False, "No selected weapon can provide overwatch")
        )
    if button == "GRENADE":
        return (
            (True, "")
            if any((unit.grenades > 0 for unit in units))
            else (False, "No fragmentation grenades available")
        )
    if button == "SMOKE":
        return (
            (True, "")
            if any((unit.smoke_grenades > 0 for unit in units))
            else (False, "No smoke grenades available")
        )
    if button == "RELOAD":
        ready = any(
            (
                unit.reload_timer <= 0
                and bool(unit.magazines)
                and (unit.ammo < unit.weapon["mag"])
                for unit in units
            )
        )
        return (
            (True, "")
            if ready
            else (False, "All selected weapons are full or out of spare magazines")
        )
    if button == "BOUND":
        return (
            (True, "")
            if len(units) >= 2
            else (False, "Bounding advance requires at least two troops")
        )
    return (True, "")


def _qol_command_label(app, button, units):
    if button == "FORMATION":
        return app.formation.upper()
    if button == "DISCIPLINE" and units:
        return units[0].fire_discipline.upper()
    if button == "PRIORITY" and units:
        return units[0].target_priority.upper()
    if button == "AUTO":
        enabled = bool(units) and all(
            (
                unit.auto_reload
                and unit.auto_cover
                and unit.auto_smoke
                and unit.auto_medic
                for unit in units
            )
        )
        return "AUTO ON" if enabled else "AUTO OFF"
    return button


def _base_unit_card_tooltip_lines(unit):
    spare_rounds = sum((max(0, int(rounds)) for rounds in unit.magazines))
    condition = "WOUNDED" if unit.casualty == "wounded" else "COMBAT EFFECTIVE"
    morale_state = getattr(unit, "morale_state", "STEADY")
    return (
        f"{getattr(unit, 'display_name', unit.role)} — {unit.role}",
        f"HEALTH {unit.hp:.0f}/{unit.max_hp:.0f}  ·  {condition}",
        f"AMMO {unit.ammo} loaded + {spare_rounds} reserve  ·  {len(unit.magazines)} magazines",
        f"SUPPRESSION {unit.suppression:.0f}/100  ·  MORALE {unit.morale:.0f} ({morale_state})",
    )


def _qol_draw_tooltip(app, lines, anchor_x, anchor_y, accent="select", width=430):
    from engine.rules import clamp

    height = 16 + len(lines) * 16
    x = int(clamp(anchor_x, 8, WINDOW_W - width - 8))
    y = int(clamp(anchor_y - height, MAP_Y + 4, WINDOW_H - height - 8))
    pygame.draw.rect(app.screen, (25, 28, 24), (x, y, width, height), border_radius=3)
    pygame.draw.rect(
        app.screen, COLORS[accent], (x, y, width, height), 1, border_radius=3
    )
    for index, line in enumerate(lines):
        color = "white" if index == 0 else "muted"
        app.text(line, (x + 10, y + 8 + index * 16), 9 if index else 10, color)


def settings_file_path():
    override = os.environ.get("KILLZONE_SETTINGS_PATH")
    if override:
        return Path(override)
    local_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_data) if local_data else Path.home() / ".config"
    return base / "KillZone" / "settings.json"


def _qol_settings_disabled():
    return os.environ.get("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "").lower() in (
        "1",
        "true",
        "yes",
    )


def serialized_user_settings(app):
    return {
        key: getattr(app, key, default)
        for key, default in PERSISTED_SETTING_DEFAULTS.items()
    }


def _base_apply_user_settings(app, values):
    if not isinstance(values, dict):
        return False
    changed = False
    display_mode = values.get("display_mode")
    if display_mode in ("windowed", "borderless", "exclusive"):
        app.display_mode = display_mode
        changed = True
    fullscreen_mode = values.get("last_fullscreen_mode")
    if fullscreen_mode in ("borderless", "exclusive"):
        app.last_fullscreen_mode = fullscreen_mode
        changed = True
    if values.get("menu_speed") in (0.5, 1.0, 2.0):
        app.menu_speed = float(values["menu_speed"])
        changed = True
    for key in (
        "menu_show_help",
        "audio_enabled",
        "show_fps",
        "show_perf",
        "large_text",
    ):
        if isinstance(values.get(key), bool):
            setattr(app, key, values[key])
            changed = True
    if values.get("fps_cap") in (0, 60, 120, 240):
        app.fps_cap = int(values["fps_cap"])
        changed = True
    scale = values.get("ui_scale")
    if isinstance(scale, (int, float)) and any(
        (abs(float(scale) - choice) < 0.001 for choice in UI_SCALE_CHOICES)
    ):
        app.ui_scale = float(scale)
        changed = True
    return changed


def save_user_settings(app, path=None):
    if path is None and _qol_settings_disabled():
        return False
    destination = Path(path) if path is not None else settings_file_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(serialized_user_settings(app), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError:
        return False
    return True


def load_user_settings(app, path=None):
    if path is None and _qol_settings_disabled():
        return False
    source = Path(path) if path is not None else settings_file_path()
    try:
        values = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return apply_user_settings(app, values)


def effective_ui_font_size(app, requested_size):
    requested = max(6, int(requested_size))
    scale = getattr(app, "ui_scale", 1.0)
    scaled = int(round(requested * scale))
    if getattr(app, "large_text", False):
        scaled += 2 if requested <= 12 else 1 if requested <= 18 else 0
    return max(6, scaled)


def _qol_clear_text_caches(app):
    if hasattr(app, "_text_surface_cache"):
        app._text_surface_cache.clear()


def _base_battlefield_status_badge(unit, game_time=0.0):
    """Return the highest-priority compact battlefield status for a unit."""
    morale_state = getattr(unit, "morale_state", "STEADY")
    if unit.order == "rout" or morale_state in ("BREAKING", "ROUTING"):
        return ("BREAK", "danger")
    if morale_state == "PINNED" or unit.suppression >= 80:
        return ("PIN", "suppression")
    if unit.order == "medic":
        return ("AID", "good")
    if unit.carrying_uid is not None or unit.dragging_uid is not None:
        return ("CASEVAC", "objective")
    if unit.casualty == "wounded" or unit.hp < unit.max_hp * 0.6:
        return ("WND", "danger")
    if unit.jammed:
        return ("JAM", "danger")
    if unit.ammo <= 0 and (not unit.magazines):
        return ("NO AMMO", "danger")
    if unit.reload_timer > 0:
        return ("RLD", "blue")
    if unit.ammo <= 0:
        return ("EMPTY", "objective")
    if game_time < getattr(unit, "disoriented_until", 0.0):
        return ("CON", "contact")
    return None


def offscreen_indicator_point(rect, point, margin=14):
    """Intersect a direction from the viewport centre with its inset edge."""
    if rect.collidepoint(point):
        return None
    inner = rect.inflate(-margin * 2, -margin * 2)
    center_x, center_y = rect.center
    delta_x = point[0] - center_x
    delta_y = point[1] - center_y
    scales = []
    if delta_x > 0:
        scales.append((inner.right - center_x) / delta_x)
    elif delta_x < 0:
        scales.append((inner.left - center_x) / delta_x)
    if delta_y > 0:
        scales.append((inner.bottom - center_y) / delta_y)
    elif delta_y < 0:
        scales.append((inner.top - center_y) / delta_y)
    positive = [scale for scale in scales if scale >= 0]
    if not positive:
        return (inner.center, 0.0)
    scale = min(positive)
    return (
        (round(center_x + delta_x * scale), round(center_y + delta_y * scale)),
        math.atan2(delta_y, delta_x),
    )


def battle_audio_cue_for_event(event):
    kind = event.get("kind", "")
    text = event.get("text", "").lower()
    if kind == "casualty":
        return "casualty" if text.startswith("player ") else None
    if kind in ("counterattack",):
        return "warning"
    if kind == "reserve":
        return "warning" if "enemy" in text else "command"
    if kind == "surrender":
        return "casualty" if "player" in text else "objective"
    if kind in ("objective", "collapse", "victory"):
        return "objective"
    if kind == "mission":
        return "contact"
    return None


def battlefield_event_style(event):
    kind = event.get("kind", "")
    text = event.get("text", "").lower()
    if kind == "casualty" and text.startswith("player "):
        return ("CASUALTY", "danger")
    if kind == "counterattack":
        return ("COUNTERATTACK", "danger")
    if kind == "reserve":
        return (
            ("ENEMY RESERVE", "danger") if "enemy" in text else ("RESERVES", "select")
        )
    if kind == "objective":
        return ("OBJECTIVE", "good")
    if kind == "collapse":
        return ("LINE BREAK", "good")
    if kind == "victory":
        return ("VICTORY", "good")
    if kind == "surrender" and "player" not in text:
        return ("SURRENDER", "good")
    return None


def _qol_notify(app, text, kind="info", duration=1.8):
    _base__qol_notify(app, text, kind=kind, duration=duration)
    if not hasattr(app, "play_tactical_sound"):
        return
    lowered = text.lower()
    if kind == "danger":
        cue = "deny"
    elif "selected" in lowered:
        cue = "select"
    elif (
        any(
            (
                word in lowered
                for word in ("confirmed", "ready", "assigned", "cancelled")
            )
        )
        or ":" in text
    ):
        cue = "command"
    else:
        return
    app.play_tactical_sound(cue)


def _base_presentation_audio_mix(event, distance, intensity=0.0):
    """Return deterministic procedural mix layers for a simulation event."""
    from engine.rules import clamp

    kind = str(event.get("type", ""))
    distance = max(0.0, float(distance))
    intensity = clamp(float(intensity), 0.0, 100.0)
    near = clamp(1.0 - (distance / 38.0) ** 1.25, 0.0, 1.0)
    far = clamp(1.0 - distance / 58.0, 0.04, 1.0)
    layers = []
    if kind == "shot":
        weapon = str(event.get("weapon", ""))
        if weapon == "artillery":
            layers.extend((("blast", 0.42 * far), ("rumble", 0.28 * far)))
        else:
            voice = (
                "heavy"
                if weapon in ("Heavy Machine Gun", "Scoped Rifle", "Marksman Rifle")
                else "smg"
                if weapon == "SMG"
                else "rifle"
            )
            layers.append((voice, (0.16 + 0.24 * near) * far))
            layers.append(("mechanical", 0.075 * near))
            if distance > 9:
                layers.append(("distant", 0.1 * far))
            elif distance > 2.5:
                layers.append(("crack", 0.09 * near))
    elif kind == "explosion":
        radius = clamp(float(event.get("radius", 2.0)), 0.5, 6.0)
        scale = 0.75 + radius * 0.1
        layers.extend(
            (
                ("blast", 0.46 * far * scale),
                ("rumble", 0.34 * far * scale),
                ("debris", 0.16 * near),
            )
        )
    elif kind in ("hurt", "death"):
        layers.append(("debris", (0.07 if kind == "hurt" else 0.11) * near))
    if intensity > 65 and kind in ("shot", "explosion"):
        layers = [(name, volume * 0.92) for name, volume in layers]
    return [
        (name, clamp(volume, 0.0, 0.75)) for name, volume in layers if volume > 0.005
    ]


def _base_unit_card_tooltip_lines_2(unit):
    from engine.rules import combat2_wound_summary

    lines = list(_base_unit_card_tooltip_lines(unit))
    if unit.role not in COMBAT2_STATIC_ROLES:
        identity = f"{getattr(unit, 'full_name', getattr(unit, 'display_name', unit.role))}  ·  {unit.role}  ·  callsign {getattr(unit, 'callsign', '—')}"
        if lines:
            lines[0] = identity
        wounds = combat2_wound_summary(unit)
        if wounds != "no localized wounds":
            lines.append(f"TRAUMA  {wounds.upper()}")
        assignment = (
            str(getattr(unit, "combat2_assignment", "unassigned"))
            .replace("_", " ")
            .upper()
        )
        phase = str(getattr(unit, "combat2_phase", "contact")).replace("_", " ").upper()
        if unit.faction == "enemy" and assignment != "UNASSIGNED":
            lines.append(f"TACTICS  {assignment} · {phase}")
    return lines


def presentation_audio_mix(event, distance, intensity=0.0):
    from engine.rules import clamp

    layers = list(_base_presentation_audio_mix(event, distance, intensity))
    kind = str(event.get("type", ""))
    near = clamp(1.0 - float(distance) / 34.0, 0.0, 1.0)
    if kind == "near_miss":
        proximity = clamp(1.0 - float(event.get("proximity", 0.5)) / 0.92, 0.0, 1.0)
        layers.extend((("crack", 0.16 + proximity * 0.2), ("distant", 0.035 * near)))
    elif kind == "impact":
        material = str(event.get("material", "dirt"))
        if material == "metal":
            layers.extend((("mechanical", 0.13 * near), ("crack", 0.07 * near)))
        elif material in ("cover", "body"):
            layers.append(("debris", 0.12 * near))
        else:
            layers.append(("debris", 0.07 * near))
    position = event.get("pos") or (0.0, 0.0)
    variation = (
        0.94
        + abs(math.sin(float(position[0]) * 1.73 + float(position[1]) * 2.11)) * 0.1
    )
    combined = {}
    for name, volume in layers:
        combined[name] = clamp(combined.get(name, 0.0) + volume * variation, 0.0, 0.75)
    return [(name, volume) for name, volume in combined.items() if volume > 0.005]


def apply_user_settings(app, values):
    changed = _base_apply_user_settings(app, values)
    if isinstance(values, dict):
        for key in ("camera_shake_enabled", "edge_scroll_enabled"):
            if isinstance(values.get(key), bool):
                setattr(app, key, values[key])
                changed = True
    return changed


def battlefield_status_badge(unit, game_time=0.0):
    if game_time < getattr(unit, "polish_lane_blocked_until", 0.0):
        return ("LANE", "danger")
    reaction = getattr(unit, "polish_reaction_kind", "")
    if game_time < getattr(unit, "polish_reaction_until", 0.0) and reaction:
        return (
            "PIN" if reaction == "PINNED" else reaction,
            "suppression" if reaction != "HIT" else "danger",
        )
    return _base_battlefield_status_badge(unit, game_time)


def unit_card_tooltip_lines(unit):
    lines = list(_base_unit_card_tooltip_lines_2(unit))
    state = str(getattr(unit, "polish_order_state", "READY"))
    lines.append(f"ORDER  {state}")
    lane = str(getattr(unit, "polish_lane_reason", ""))
    wait = str(getattr(unit, "polish_wait_reason", ""))
    if lane:
        lines.append(f"SAFETY  {lane}")
    elif wait:
        lines.append(f"WAIT  {wait}")
    return lines
