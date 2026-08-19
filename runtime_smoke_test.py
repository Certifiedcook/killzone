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
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)

    for state in ("menu", "setup", "settings", "help"):
        app.state = state
        app.draw()

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

    app.mouse = (0, 0)
    app.draw()

    screenshot = output_dir / "runtime_smoke.png"
    pygame.image.save(app.screen, screenshot)
    assert screenshot.stat().st_size > 1_000
    pygame.quit()
    print(f"REAL PYGAME SMOKE PASS ({screenshot})")


if __name__ == "__main__":
    main()
