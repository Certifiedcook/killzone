"""Exercise the real Pygame renderer with SDL's headless drivers."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import pygame

import kill_zone as kz


def main():
    app = kz.KillZoneApp()
    assert app.screen.get_size() == (kz.WINDOW_W, kz.WINDOW_H)
    if pygame.mixer.get_init():
        assert set(kz.TACTICAL_AUDIO_VOLUMES).issubset(app._tactical_audio)
        assert app.play_tactical_sound("command")
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)

    for state in ("menu", "setup", "settings", "help"):
        app.state = state
        app.draw()

    app.state = "operation_setup"
    app.draw()
    operations_setup = output_dir / "operations_setup.png"
    pygame.image.save(app.screen, operations_setup)
    assert operations_setup.stat().st_size > 1_000

    app.setup_mission = "defense"
    app.setup_variant = "ruined_village"
    app.setup_weather = "fog"
    app.setup_enemy_strength = 1.25
    app.setup_defense_duration = 180
    app.start_battle()
    assert app.game.mission_type == "defense"
    assert app.game.deployment_zone_side == "east"
    app.draw()
    defense_briefing = output_dir / "defense_briefing.png"
    pygame.image.save(app.screen, defense_briefing)
    assert defense_briefing.stat().st_size > 1_000

    # Return to the default Assault operation for the established rendering
    # and tactical-control smoke path below.
    app.setup_mission = "assault"
    app.setup_variant = "auto"
    app.setup_weather = "auto"
    app.setup_enemy_strength = 1.0
    app.setup_defense_duration = 300

    app.ui_scale = 1.1
    app.large_text = True
    app._text_surface_cache.clear()
    app.state = "settings"
    app.draw()
    accessibility = output_dir / "accessibility_settings.png"
    pygame.image.save(app.screen, accessibility)
    assert accessibility.stat().st_size > 1_000
    app.ui_scale = 1.0
    app.large_text = False
    app._text_surface_cache.clear()

    app.seed_text = "424242"
    app.setup_difficulty = "Veteran"
    app.setup_reserves = 3
    app.start_battle()
    assert app.state == "briefing"
    app.draw()

    app.begin_deployment_from_briefing()
    app.selected = [unit.uid for unit in app.game.living("player")[:4]]
    app.draw()
    app.finalize_deployment()

    engineer = next(unit for unit in app.game.living("player") if unit.role == "Engineer")

    # Exercise the complete RTS construction input path without preselecting
    # an engineer: hotkey, project choice, map placement, and assignment.
    app.selected = []
    app.handle_event(
        pygame.event.Event(
            pygame.KEYDOWN,
            {"key": pygame.K_b, "mod": pygame.KMOD_SHIFT, "unicode": "B"},
        )
    )
    assert app.build_menu_open
    app.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": app.build_menu_rects()["sandbags"].center},
        )
    )
    assert app.command_mode == "build:sandbags"
    build_site = next(
        (x, y)
        for y in range(1, kz.MAP_H - 1)
        for x in range(1, kz.MAP_W - 1)
        if app.map_view_rect().collidepoint(app.cell_rect(x, y).center)
        and app.game.validate_build_site("player", "sandbags", (x, y))[0]
        and app.game.builder_staging_position(engineer, (x, y)) is not None
    )
    app.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": app.cell_rect(*build_site).center},
        )
    )
    assert app.command_mode == "normal"
    assert build_site in app.game.construction_reservations
    assert getattr(engineer, "_construction_queued", False)

    app.selected = [engineer.uid]
    app.show_help = False
    app.build_menu_open = True
    app.draw()
    construction_menu = output_dir / "construction_menu.png"
    pygame.image.save(app.screen, construction_menu)
    assert construction_menu.stat().st_size > 1_000
    app.build_menu_open = False

    visual_sites = []
    for y in range(2, kz.MAP_H - 2):
        for x in range(2, kz.MAP_W - 2):
            if len(visual_sites) == len(kz.STATIC_WEAPON_ROLES):
                break
            if not app.map_view_rect().collidepoint(app.cell_rect(x, y).center):
                continue
            if app.game.unit_at(x, y) is not None:
                continue
            if app.game.grid[y][x].terrain not in ("open", "mud", "rubble", "crater", "foxhole", "hill"):
                continue
            if any(abs(x - sx) + abs(y - sy) < 5 for sx, sy in visual_sites):
                continue
            visual_sites.append((x, y))
        if len(visual_sites) == len(kz.STATIC_WEAPON_ROLES):
            break
    assert len(visual_sites) == len(kz.STATIC_WEAPON_ROLES)
    for role, site in zip(sorted(kz.STATIC_WEAPON_ROLES), visual_sites, strict=True):
        emplacement = app.game.add_unit("player", role, *site)
        emplacement.is_emplacement = True
        emplacement.squad_id = 0
        emplacement.deployed = True
        emplacement.hold_position = True
        emplacement.facing = 330
    app.draw()
    emplacement_designs = output_dir / "emplacement_designs.png"
    pygame.image.save(app.screen, emplacement_designs)
    assert emplacement_designs.stat().st_size > 1_000

    assert app.cycle_selected_doctrine() == "aggressive"
    app.selected = [unit.uid for unit in app.game.living("player")[:4]]

    # Exercise the in-battle command guide separately, then leave the final
    # screenshot focused on the battlefield/UI visual smoke target.
    app.show_help = True
    app.draw()
    command_help = output_dir / "command_help.png"
    pygame.image.save(app.screen, command_help)
    assert command_help.stat().st_size > 1_000
    app.show_help = False
    app.show_threat = True
    app.show_fps = True
    app.show_perf = True
    for zoom in app.zoom_levels:
        app.zoom = zoom
        for camera_x, camera_y in ((0, 0), (kz.MAP_W, kz.MAP_H)):
            app.camera_x = camera_x
            app.camera_y = camera_y
            app.clamp_camera()
            for _ in range(15):
                app.game.update(kz.SIM_DT)
            app.draw()

    for mode in ("borderless", "exclusive", "windowed"):
        app.set_display_mode(mode)
        assert app.display_mode in (mode, "windowed")
        app.draw()

    # Send a raw display-space click straight to the outer handler.  This
    # exercises the path that used to miss fullscreen-scaled UI buttons.
    app.state = "settings"
    app.set_display_mode("borderless")
    display_w, display_h = app.input_display_size()
    help_center = app.settings_rects()["help"].center
    display_pos = (
        round(help_center[0] * display_w / kz.WINDOW_W),
        round(help_center[1] * display_h / kz.WINDOW_H),
    )
    previous_help_setting = app.menu_show_help
    event = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        {"button": 1, "pos": display_pos},
    )
    app.handle_event(event)
    assert app.menu_show_help is not previous_help_setting
    assert app.settings_rects()["help"].collidepoint(event.pos)
    app.menu_show_help = previous_help_setting
    app.set_display_mode("windowed")
    app.state = "game"

    app.focus_selected()
    app.draw()

    app.mouse = app.unit_card_rects()[0][1].center
    app.draw()
    unit_tooltip = output_dir / "unit_card_tooltip.png"
    pygame.image.save(app.screen, unit_tooltip)
    assert unit_tooltip.stat().st_size > 1_000

    app.mouse = app.command_bar_rects()["ASSAULT"].center
    app.draw()
    tooltip = output_dir / "command_tooltip.png"
    pygame.image.save(app.screen, tooltip)
    assert tooltip.stat().st_size > 1_000

    app.command_mode = "smoke"
    app.mouse = app.cell_rect(8, 8).center
    app.draw()
    targeting = output_dir / "targeting_cursor.png"
    pygame.image.save(app.screen, targeting)
    assert targeting.stat().st_size > 1_000
    app.command_mode = "normal"

    planned_unit = app.selected_units()[0]
    app.game.issue_move([planned_unit], (8, 8), formation="column")
    app.game.issue_move([planned_unit], (11, 10), append=True, formation="column")
    app.mouse = (0, 0)
    app.draw()
    waypoints = output_dir / "queued_waypoints.png"
    pygame.image.save(app.screen, waypoints)
    assert waypoints.stat().st_size > 1_000
    planned_unit.path = []
    planned_unit.waypoints = []
    planned_unit.command_queue = []
    planned_unit.order = "idle"

    # Stage critical states, a recent friendly casualty ping, and one selected
    # off-screen squad member for a focused readability screenshot.
    readable_units = app.selected_units()[:4]
    snapshots = [
        {
            "x": unit.x,
            "y": unit.y,
            "hp": unit.hp,
            "casualty": unit.casualty,
            "suppression": unit.suppression,
            "morale_state": unit.morale_state,
            "ammo": unit.ammo,
            "magazines": list(unit.magazines),
        }
        for unit in readable_units
    ]
    readable_units[0].hp = 48
    readable_units[0].casualty = "wounded"
    readable_units[1].suppression = 88
    readable_units[1].morale_state = "PINNED"
    readable_units[2].ammo = 0
    readable_units[2].magazines = []
    readable_units[3].x = kz.MAP_W - 2
    app.game.battle_events.append(
        {
            "time": app.game.time,
            "kind": "casualty",
            "text": "player Rifleman wounded",
            "pos": readable_units[0].pos,
        }
    )
    app.draw()
    readability = output_dir / "battlefield_readability.png"
    pygame.image.save(app.screen, readability)
    assert readability.stat().st_size > 1_000
    app.game.battle_events.pop()
    for unit, snapshot in zip(readable_units, snapshots, strict=True):
        for field, value in snapshot.items():
            setattr(unit, field, value)

    app.mouse = (0, 0)
    app.draw()

    screenshot = output_dir / "runtime_smoke.png"
    pygame.image.save(app.screen, screenshot)
    assert screenshot.stat().st_size > 1_000
    pygame.quit()
    print(f"REAL PYGAME SMOKE PASS ({screenshot})")


if __name__ == "__main__":
    main()
