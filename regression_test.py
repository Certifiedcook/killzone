"""Focused regressions for maintenance fixes that are kept as plain source."""

from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz


def fresh(seed=1001):
    game = kz.RealTimeGame(seed=seed, difficulty="Hard")
    game.units = []
    game.next_uid = 1
    game.explosions = []
    game.tracers = []
    game.check_end = lambda: None
    for y in range(kz.MAP_H):
        for x in range(kz.MAP_W):
            game.set_cell(x, y, "open")
            cell = game.grid[y][x]
            cell.mine = False
            cell.smoke = 0
            cell.fire = 0
            cell.ground_suppression = 0
    return game


def step(game, seconds):
    for _ in range(round(seconds / kz.SIM_DT)):
        game.update(kz.SIM_DT)


def test_repeated_combat_exit_is_fully_cleaned():
    game = fresh()
    casualty = game.add_unit("player", "Rifleman", 3, 3)
    observer = game.add_unit("enemy", "Rifleman", 7, 3)

    casualty.casualty = "incapacitated"
    casualty.hp = 0
    game.cleanup_unit_state(casualty, "first incapacitation")

    casualty.casualty = "wounded"
    casualty.hp = 30
    game.set_overwatch(casualty, 0, 90)
    casualty.target_uid = observer.uid
    casualty.reaction_target_uid = observer.uid
    observer.target_uid = casualty.uid
    observer.order = "fire"

    casualty.casualty = "incapacitated"
    casualty.hp = 0
    game.cleanup_unit_state(casualty, "second incapacitation")

    assert not casualty.overwatch
    assert casualty.target_uid is None
    assert casualty.reaction_target_uid is None
    assert observer.target_uid is None and observer.order == "idle"


def test_cached_path_revalidates_dynamic_occupancy():
    game = fresh(1002)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    destination = (7, 2)
    original = game.find_path(mover, destination, "fast")
    assert (3, 2) in original

    game.add_unit("player", "Rifleman", 3, 2)
    alternate = game.find_path(mover, destination, "fast")
    assert alternate and (3, 2) not in alternate
    assert all(game.passable(x, y, mover) for x, y in alternate)


def test_cached_path_revalidates_closed_door_immediately():
    game = fresh(1003)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    game.set_cell(3, 2, "door")
    game.toggle_door(mover, (3, 2))
    through_open_door = game.find_path(mover, (7, 2), "fast")
    assert (3, 2) in through_open_door

    game.toggle_door(mover, (3, 2))
    around_closed_door = game.find_path(mover, (7, 2), "fast")
    assert around_closed_door and (3, 2) not in around_closed_door


def test_weighted_safe_path_still_avoids_known_threat():
    game = fresh(1004)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    threat = [[0.0 for _ in range(kz.MAP_W)] for _ in range(kz.MAP_H)]
    for x in range(3, 7):
        threat[2][x] = 8.0

    def fixed_threat(faction, x, y):
        game._threat_grids[faction] = threat
        game._threat_cache_time = game.time
        return threat[y][x]

    game.tile_threat = fixed_threat
    fast = game.find_path(mover, (7, 2), "fast")
    safe = game.find_path(mover, (7, 2), "safe")
    assert all(y == 2 for _, y in fast)
    assert any(y != 2 for _, y in safe)
    assert sum(threat[y][x] for x, y in safe) < sum(threat[y][x] for x, y in fast)


def test_sector_stability_colors_match_meaning():
    assert kz.sector_stability_color(100) == "good"
    assert kz.sector_stability_color(50) == "contact"
    assert kz.sector_stability_color(10) == "danger"


def test_invalid_difficulty_has_a_clear_error():
    try:
        kz.RealTimeGame(seed=1005, difficulty="Impossible")
    except ValueError as exc:
        assert "Easy" in str(exc) and "Hard" in str(exc) and "Veteran" in str(exc)
    else:
        raise AssertionError("invalid difficulty was accepted")


def test_player_reserves_deploy_only_once():
    game = kz.RealTimeGame(
        seed=1006,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Engineer"],
        reserve_count=2,
    )
    before = len(game.units)
    first = game.deploy_player_reserves()
    after_first = len(game.units)
    second = game.deploy_player_reserves()
    assert len(first) == 2 and after_first == before + 2
    assert second == [] and len(game.units) == after_first
    assert game.stats["player"]["reserves"] == 2


def test_mixed_roles_auto_allocate_into_tactical_squads():
    roster = [
        "Medic",
        "Rifleman",
        "Recon",
        "Machine Gunner",
        "Engineer",
        "Assault",
        "Sniper",
        "Mortar Team",
        "Grenadier",
        "Automatic Rifleman",
        "Marksman",
        "HMG Crew",
    ]
    game = kz.RealTimeGame(seed=1007, difficulty="Easy", player_roster=roster)
    squads = {}
    for unit in game.living("player"):
        squads.setdefault(unit.squad_id, set()).add(kz.squad_role_group(unit.role))

    assert len(squads) == 4
    assert all(len(groups) == 1 for groups in squads.values())
    assert {next(iter(groups)) for groups in squads.values()} == set(kz.SQUAD_ROLE_GROUPS)


def test_auto_squad_overflow_stays_visible_and_within_capacity():
    roster = (
        ["Rifleman"] * 5
        + ["Medic"] * 5
        + ["Recon"] * 5
        + ["Machine Gunner"]
    )
    game = kz.RealTimeGame(seed=1008, difficulty="Easy", player_roster=roster)
    counts = {}
    for unit in game.living("player"):
        counts[unit.squad_id] = counts.get(unit.squad_id, 0) + 1

    assert max(counts) <= kz.AUTO_SQUAD_LIMIT
    assert len(counts) <= kz.AUTO_SQUAD_LIMIT
    assert max(counts.values()) <= kz.AUTO_SQUAD_SIZE


def test_reserves_reinforce_matching_tactical_squads():
    game = kz.RealTimeGame(
        seed=1009,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Machine Gunner", "Assault", "Recon"],
        reserve_count=2,
    )
    rifleman = next(unit for unit in game.living("player") if unit.role == "Rifleman")
    occupied_before = {unit.squad_id for unit in game.living("player")}

    reserves = game.deploy_player_reserves()
    assault = next(unit for unit in reserves if unit.role == "Assault")
    recon = next(unit for unit in reserves if unit.role == "Recon")

    assert assault.squad_id == rifleman.squad_id
    assert recon.squad_id not in occupied_before


def test_number_keys_select_squads_without_stealing_modified_bindings():
    game = kz.RealTimeGame(
        seed=1010,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Recon", "Machine Gunner"],
    )
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = []
    app.control_groups = {number: [] for number in range(1, 10)}
    app.message = ""
    app.show_perf = False

    app.handle_key(kz.pygame.K_2, 0)
    squad_two = [unit.uid for unit in game.living("player") if unit.squad_id == 2]
    assert squad_two and app.selected == squad_two

    app.handle_key(kz.pygame.K_7, kz.pygame.KMOD_CTRL)
    app.selected = []
    app.handle_key(kz.pygame.K_7, kz.pygame.KMOD_SHIFT)
    assert app.selected == squad_two

    reassigned = game.get_unit(squad_two[0])
    app.selected = [reassigned.uid]
    app.handle_key(kz.pygame.K_5, kz.pygame.KMOD_ALT)
    assert reassigned.squad_id == 5
    app.selected = []
    app.handle_key(kz.pygame.K_5, 0)
    assert app.selected == [reassigned.uid]


def test_number_keys_select_squads_during_deployment():
    game = kz.RealTimeGame(
        seed=1011,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Recon", "Machine Gunner"],
    )
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = []
    event = SimpleNamespace(type=kz.pygame.KEYDOWN, key=kz.pygame.K_3, mod=0)

    app.handle_deployment_event(event)

    squad_three = [unit.uid for unit in game.living("player") if unit.squad_id == 3]
    assert squad_three and app.selected == squad_three


def test_squad_visual_palette_is_stable_and_distinct():
    colors = [kz.squad_visual_color(number) for number in range(1, 10)]
    assert len(set(colors)) == 9
    assert all(len(color) == 3 and all(0 <= channel <= 255 for channel in color) for color in colors)
    assert kz.squad_visual_color(1) == colors[0]
    assert kz.squad_visual_color(10) == colors[0]


def test_squad_visual_labels_match_tactical_allocation():
    game = kz.RealTimeGame(seed=1012, difficulty="Easy")
    labels = {
        kz.squad_tactical_label(game, squad_id)
        for squad_id in {unit.squad_id for unit in game.living("player")}
    }
    assert labels == {"ASSAULT", "FIRE SUP", "RECON", "SUPPORT"}


def test_command_bar_help_documents_every_button():
    documented = {
        button
        for column in kz.COMMAND_BAR_HELP_COLUMNS
        for button, gesture, description in column
        if gesture and description
    }
    assert documented == {
        "ASSAULT",
        "SUPPRESS",
        "OVERWATCH",
        "GRENADE",
        "SMOKE",
        "RELOAD",
        "STANCE",
        "FORMATION",
        "DISCIPLINE",
        "PRIORITY",
        "BOUND",
        "AUTO",
        "HOLD",
        "FALLBACK",
    }


def test_overwatch_button_uses_a_map_facing_point():
    game = fresh(1013)
    unit = game.add_unit("player", "Rifleman", 2, 2)
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = [unit.uid]
    app.command_mode = "normal"
    app.message = ""

    overwatch = app.command_bar_rects()["OVERWATCH"]
    assert app.handle_command_bar(overwatch.center)
    assert app.command_mode == "overwatch" and not unit.overwatch

    app.issue_context_command((2, 7))
    assert app.command_mode == "normal" and unit.overwatch
    assert 89 <= unit.fire_lane_center <= 91


def test_command_buttons_report_capability_and_reason():
    game = fresh(1014)
    rifleman = game.add_unit("player", "Rifleman", 2, 2)
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = [rifleman.uid]

    enabled, reason = kz.command_button_status(app, "SUPPRESS")
    assert not enabled and "automatic" in reason
    rifleman.grenades = 0
    enabled, reason = kz.command_button_status(app, "GRENADE")
    assert not enabled and "grenades" in reason
    rifleman.ammo = rifleman.weapon["mag"]
    enabled, reason = kz.command_button_status(app, "RELOAD")
    assert not enabled and "full" in reason
    rifleman.ammo -= 1
    assert kz.command_button_status(app, "RELOAD") == (True, "")


def test_unit_card_tooltip_explains_health_ammo_and_suppression():
    game = fresh(1015)
    unit = game.add_unit("player", "Medic", 2, 2)
    unit.hp = 54
    unit.casualty = "wounded"
    unit.suppression = 63
    lines = kz.unit_card_tooltip_lines(unit)
    combined = " ".join(lines)
    assert "HEALTH 54" in combined
    assert "AMMO" in combined and "magazines" in combined
    assert "SUPPRESSION 63" in combined and "WOUNDED" in combined


def test_status_selection_finds_wounded_pinned_and_idle_troops():
    game = fresh(1016)
    wounded = game.add_unit("player", "Rifleman", 2, 2)
    wounded.casualty = "wounded"
    wounded.hp = 60
    wounded.order = "fire"
    pinned = game.add_unit("player", "Rifleman", 3, 2)
    pinned.suppression = 90
    pinned.morale_state = "PINNED"
    pinned.order = "move"
    idle = game.add_unit("player", "Rifleman", 4, 2)
    idle.order = "idle"
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = []
    app.message = ""

    assert app.select_units_by_status("wounded") and app.selected == [wounded.uid]
    assert app.select_units_by_status("pinned") and app.selected == [pinned.uid]
    assert app.select_units_by_status("idle") and app.selected == [idle.uid]


def test_double_tapping_squad_number_focuses_selection():
    game = fresh(1017)
    unit = game.add_unit("player", "Rifleman", 2, 2)
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = []
    app.message = ""
    app._qol_last_squad_key = None
    app._qol_last_squad_at = -99.0
    app.focused = False
    app.focus_selected = lambda: setattr(app, "focused", True)

    assert app.select_squad_number(unit.squad_id)
    assert not app.focused
    assert app.select_squad_number(unit.squad_id)
    assert app.focused


def test_escape_cancels_target_mode_before_opening_menu():
    game = fresh(1018)
    app = object.__new__(kz.KillZoneApp)
    app.game = game
    app.selected = []
    app.show_help = False
    app.command_mode = "grenade"
    app.message = ""
    app.handle_key(kz.pygame.K_ESCAPE, 0)
    assert app.command_mode == "normal"


def test_settings_round_trip_and_font_scaling():
    source = SimpleNamespace(
        display_mode="borderless",
        last_fullscreen_mode="exclusive",
        menu_speed=2.0,
        menu_show_help=False,
        audio_enabled=False,
        show_fps=True,
        show_perf=True,
        fps_cap=120,
        ui_scale=1.1,
        large_text=True,
    )
    target = SimpleNamespace(**kz.PERSISTED_SETTING_DEFAULTS)
    with tempfile.TemporaryDirectory(prefix="killzone_settings_") as directory:
        path = Path(directory) / "settings.json"
        assert kz.save_user_settings(source, path)
        assert kz.load_user_settings(target, path)

    assert target.display_mode == "borderless"
    assert target.menu_speed == 2.0 and target.fps_cap == 120
    assert target.ui_scale == 1.1 and target.large_text
    assert kz.effective_ui_font_size(target, 10) == 13


def test_fullscreen_clicks_are_scaled_once_at_the_input_boundary():
    class DoubleSizeWindow:
        @staticmethod
        def get_size():
            return kz.WINDOW_W * 2, kz.WINDOW_H * 2

    app = object.__new__(kz.KillZoneApp)
    app.window = DoubleSizeWindow()
    app.state = "settings"
    app.mouse = (0, 0)
    app.menu_show_help = True

    logical_pos = app.settings_rects()["help"].center
    event = SimpleNamespace(
        type=kz.pygame.MOUSEBUTTONDOWN,
        button=1,
        pos=(logical_pos[0] * 2, logical_pos[1] * 2),
        dict={},
    )

    app.normalize_event_pos(event)
    app.handle_settings_event(event)
    assert app.settings_rects()["help"].collidepoint(event.pos)
    assert app.menu_show_help is False
    assert event.dict[kz._FULLSCREEN_LOGICAL_EVENT_FLAG]

    app.normalize_event_pos(event)
    assert app.settings_rects()["help"].collidepoint(event.pos)


def test_multiseed_simulation_invariants():
    for difficulty, seed in zip(kz.DIFFICULTY, (1011, 1012, 1013), strict=True):
        game = kz.RealTimeGame(seed=seed, difficulty=difficulty, reserve_count=2)
        players = [unit for unit in game.living("player") if unit.combat_effective]
        game.issue_move(players, (game.primary_line_x - 2, kz.MAP_H // 2), mode="safe")
        step(game, 12)
        assert math.isfinite(game.time)
        assert len({unit.uid for unit in game.units}) == len(game.units)
        for unit in game.units:
            assert all(math.isfinite(value) for value in (unit.x, unit.y, unit.hp, unit.morale, unit.suppression, unit.cohesion))
            assert 0 <= unit.x < kz.MAP_W and 0 <= unit.y < kz.MAP_H
            assert 0 <= unit.morale <= 100 and 0 <= unit.suppression <= 100
            if not unit.combat_effective:
                assert not unit.overwatch and not unit.fire_lane
                assert unit.target_uid is None and unit.reaction_target_uid is None


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
    print(f"ALL {len(TESTS)} MAINTENANCE REGRESSIONS PASSED")
