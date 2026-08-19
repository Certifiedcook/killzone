"""Exercise the real Pygame renderer with SDL's headless drivers."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")

import pygame

import kill_zone as kz


def main():
    app = kz.KillZoneApp()
    assert app.screen.get_size() == (kz.WINDOW_W, kz.WINDOW_H)

    for state in ("menu", "setup", "settings", "help"):
        app.state = state
        app.draw()

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

    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    screenshot = output_dir / "runtime_smoke.png"
    pygame.image.save(app.screen, screenshot)
    assert screenshot.stat().st_size > 1_000
    pygame.quit()
    print(f"REAL PYGAME SMOKE PASS ({screenshot})")


if __name__ == "__main__":
    main()
