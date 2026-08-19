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


def test_battlefield_status_badges_prioritize_critical_states():
    game = fresh(1019)
    unit = game.add_unit("player", "Rifleman", 2, 2)
    unit.casualty = "wounded"
    unit.hp = 48
    assert kz.battlefield_status_badge(unit, game.time) == ("WND", "danger")

    unit.suppression = 86
    unit.morale_state = "PINNED"
    assert kz.battlefield_status_badge(unit, game.time) == ("PIN", "suppression")

    unit.suppression = 0
    unit.morale_state = "STEADY"
    unit.casualty = "healthy"
    unit.hp = unit.max_hp
    unit.ammo = 0
    unit.magazines = []
    assert kz.battlefield_status_badge(unit, game.time) == ("NO AMMO", "danger")


def test_offscreen_indicator_intersects_the_viewport_edge():
    rect = kz.pygame.Rect(10, 20, 100, 80)
    point, angle = kz.offscreen_indicator_point(rect, (220, 60), margin=14)
    assert point[0] == rect.right - 14
    assert rect.top < point[1] < rect.bottom
    assert abs(angle) < 0.001
    assert kz.offscreen_indicator_point(rect, rect.center) is None


def test_tactical_events_have_distinct_audio_and_visual_feedback():
    player_loss = {"kind": "casualty", "text": "player Rifleman incapacitated"}
    enemy_loss = {"kind": "casualty", "text": "enemy Rifleman incapacitated"}
    counterattack = {"kind": "counterattack", "text": "Enemy counterattack"}
    objective = {"kind": "objective", "text": "Objective complete"}
    friendly_surrender = {"kind": "surrender", "text": "player Rifleman surrendered"}

    assert kz.battle_audio_cue_for_event(player_loss) == "casualty"
    assert kz.battle_audio_cue_for_event(enemy_loss) is None
    assert kz.battle_audio_cue_for_event(counterattack) == "warning"
    assert kz.battle_audio_cue_for_event(objective) == "objective"
    assert kz.battle_audio_cue_for_event(friendly_surrender) == "casualty"
    assert kz.battlefield_event_style(player_loss) == ("CASUALTY", "danger")
    assert kz.battlefield_event_style(enemy_loss) is None


def test_moving_troops_fire_with_an_accuracy_penalty():
    game = fresh(1020)
    mover = game.add_unit("player", "Rifleman", 2, 2)
    target = game.add_unit("enemy", "Rifleman", 6, 2)
    target.spotted_player_until = 99

    stationary_chance = game.hit_chance(mover, target)
    mover.order = "move"
    mover.path = [(3, 2)]
    mover.waypoints = [(9, 2)]
    moving_chance = game.hit_chance(mover, target)
    assert math.isclose(
        moving_chance,
        max(2, stationary_chance - kz.MOVING_FIRE_ACCURACY_PENALTY),
    )
    assert ("firing while moving", -kz.MOVING_FIRE_ACCURACY_PENALTY) in game.shot_breakdown(mover, target)["mods"]

    ammunition_before = mover.ammo
    position_before = mover.pos
    game.update_unit(mover, kz.SIM_DT)
    assert mover.pos != position_before
    assert mover.ammo == ammunition_before - 1
    assert mover.order == "move" and mover.path

    mover.next_shot = game.time
    mover.fire_discipline = "hold"
    ammunition_before = mover.ammo
    assert not game.try_moving_fire(mover)
    assert mover.ammo == ammunition_before


def test_advanced_operation_options_are_applied_deterministically():
    config = {
        "mission": "assault",
        "variant": "ruined_village",
        "weather": "fog",
        "enemy_strength": 1.25,
        "defense_duration": 180,
    }
    first = kz.RealTimeGame(seed=1021, difficulty="Easy", operation_config=config)
    second = kz.RealTimeGame(seed=1021, difficulty="Easy", operation_config=config)

    assert first.battle_variant == second.battle_variant == "ruined_village"
    assert first.weather == second.weather == "fog"
    assert first.operation_enemy_strength == 1.25
    assert len(first.living("enemy")) == len(second.living("enemy")) == 10
    assert first.seed == second.seed == 1021


def test_defense_mode_reverses_deployment_and_commits_three_waves():
    game = kz.RealTimeGame(
        seed=1022,
        difficulty="Easy",
        operation_config={"mission": "defense", "defense_duration": 180},
    )
    players = [unit for unit in game.living("player") if unit.combat_effective]
    enemies = [unit for unit in game.living("enemy") if unit.combat_effective]

    assert game.deployment_zone_side == "east"
    assert min(unit.x for unit in players) >= game.defense_deployment_x
    assert max(unit.x for unit in enemies) < game.primary_line_x
    assert {getattr(unit, "attack_wave", 0) for unit in enemies} == {1, 2, 3}
    assert all(unit.reserve_active for unit in enemies if unit.attack_wave == 1)
    assert not any(unit.reserve_active for unit in enemies if unit.attack_wave in (2, 3))

    game.update_defense_mission(55)
    assert 2 in game.defense_wave_announced
    game.update_defense_mission(60)
    assert 3 in game.defense_wave_announced
    assert game.objective_index == 1


def test_defense_attackers_advance_toward_open_assault_waypoints():
    game = kz.RealTimeGame(
        seed=1026,
        difficulty="Hard",
        operation_config={"mission": "defense", "defense_duration": 180},
    )
    attackers = [
        unit
        for unit in game.living("enemy")
        if unit.combat_effective and unit.reserve_active
    ]
    initial_average_x = sum(unit.x for unit in attackers) / len(attackers)
    step(game, 8)
    surviving_attackers = [unit for unit in attackers if unit.combat_effective]
    advanced_average_x = sum(unit.x for unit in surviving_attackers) / len(surviving_attackers)
    assert advanced_average_x > initial_average_x + 5
    assert any(unit.order in ("move", "fire", "suppress") for unit in surviving_attackers)


def test_defense_planner_assigns_roles_and_reacts_to_observed_resistance():
    game = kz.RealTimeGame(
        seed=1028,
        difficulty="Hard",
        operation_config={"mission": "defense", "defense_duration": 180},
    )
    active = [unit for unit in game.living("enemy") if unit.reserve_active]
    assert len(game.defense_attack_plan) == len(active)
    assert all(
        unit.attack_assignment == "breach"
        for unit in active
        if unit.role in ("Assault", "Grenadier")
    )
    assert all(
        unit.attack_assignment == "fire_support"
        for unit in active
        if unit.role in ("Machine Gunner", "Marksman", "Sniper", "HMG Crew")
    )
    assault_units = [unit for unit in active if unit.attack_assignment == "assault"]
    assert any(unit.attack_sector != game.defense_main_effort for unit in assault_units)

    previous_effort = game.defense_main_effort
    contact_y = kz.MAP_H // 6 if previous_effort == "NORTH" else kz.MAP_H // 2 if previous_effort == "CENTRE" else kz.MAP_H * 5 // 6
    for index in range(6):
        game.intel["enemy"][10_000 + index] = {
            "pos": (game.primary_line_x, contact_y),
            "seen": game.time,
            "role": "MG Emplacement",
        }
    game.plan_defense_attack(force=True)
    assert game.defense_main_effort != previous_effort
    assert game.defense_sector_pressure[previous_effort] == max(game.defense_sector_pressure.values())

    game.activate_defense_wave(2)
    sustainment = [
        unit
        for unit in game.living("enemy")
        if unit.reserve_active and unit.role in ("Medic", "Engineer")
    ]
    assert sustainment and all(unit.attack_assignment == "sustainment" for unit in sustainment)
    assert all(not game.enemy_builder_ready(unit) for unit in sustainment if unit.role == "Engineer")


def test_defense_reserves_enter_from_the_east_only_once():
    game = kz.RealTimeGame(
        seed=1025,
        difficulty="Easy",
        player_roster=["Rifleman", "Medic", "Engineer", "Assault"],
        reserve_count=2,
        operation_config={"mission": "defense"},
    )
    first = game.deploy_player_reserves()
    second = game.deploy_player_reserves()
    assert len(first) == 2 and not second
    assert min(unit.x for unit in first) >= game.defense_deployment_x
    assert all(unit.facing == 180 for unit in first)


def test_squad_doctrine_changes_movement_and_moving_fire_policy():
    game = fresh(1023)
    unit = game.add_unit("player", "Rifleman", 2, 2)
    target = game.add_unit("enemy", "Rifleman", 6, 2)
    target.spotted_player_until = 99

    assert game.doctrine_for(unit) == "balanced"
    assert game.cycle_squad_doctrine([unit]) == "aggressive"
    game.issue_move([unit], (8, 2))
    assert unit.move_mode == "fast"

    assert game.cycle_squad_doctrine([unit]) == "cautious"
    unit.order = "move"
    unit.path = [(3, 2)]
    unit.waypoints = [(8, 2)]
    unit.fire_discipline = "free"
    unit.next_shot = game.time
    assert not game.can_attempt_moving_fire(unit)
    unit.under_fire_until = game.time + 2
    assert game.can_attempt_moving_fire(unit)


def test_engineers_construct_defenses_and_static_weapons_for_both_sides():
    game = fresh(1024)
    player_engineer = game.add_unit("player", "Engineer", 4, 4)
    enemy_engineer = game.add_unit("enemy", "Engineer", 12, 4)

    started, reason = game.begin_construction(player_engineer, "sandbags", (5, 4))
    assert started, reason
    player_engineer.action_timer = 0
    game.complete_action(player_engineer)
    assert game.grid[4][5].terrain == "sandbags"

    started, reason = game.begin_construction(player_engineer, "mg_nest", (4, 5))
    assert started, reason
    player_engineer.action_timer = 0
    game.complete_action(player_engineer)

    started, reason = game.begin_construction(enemy_engineer, "artillery", (12, 5))
    assert started, reason
    enemy_engineer.action_timer = 0
    game.complete_action(enemy_engineer)

    player_emplacement = next(unit for unit in game.living("player") if unit.role == "MG Emplacement")
    enemy_artillery = next(unit for unit in game.living("enemy") if unit.role == "Artillery Battery")
    assert player_emplacement.is_emplacement and player_emplacement.deployed
    assert enemy_artillery.is_emplacement and enemy_artillery.artillery_shells == 12
    assert game.static_emplacement_count("player") == 1
    assert game.static_emplacement_count("enemy") == 1

    app = object.__new__(kz.KillZoneApp)
    app.game = game
    assert 0 not in app.squad_rects()


def test_engineer_emplacements_have_unique_non_infantry_visuals():
    assert set(kz.EMPLACEMENT_VISUALS) == set(kz.STATIC_WEAPON_ROLES)
    silhouettes = {
        definition["silhouette"]
        for definition in kz.EMPLACEMENT_VISUALS.values()
    }
    labels = {definition["label"] for definition in kz.EMPLACEMENT_VISUALS.values()}
    assert len(silhouettes) == len(kz.STATIC_WEAPON_ROLES)
    assert len(labels) == len(kz.STATIC_WEAPON_ROLES)
    assert not silhouettes & {"infantry", "rifleman"}


def test_rts_construction_moves_an_available_engineer_to_the_blueprint():
    game = fresh(1027)
    engineer = game.add_unit("player", "Engineer", 2, 2)
    game.add_unit("player", "Rifleman", 3, 2)
    site = (14, 10)

    assigned, reason = game.queue_construction("player", "sandbags", site)
    assert assigned is engineer, reason
    assert site in game.construction_reservations
    assert engineer.order == "move" and engineer.waypoints

    step(game, 18)
    assert game.grid[site[1]][site[0]].terrain == "sandbags"
    assert site not in game.construction_reservations
    assert engineer.order == "idle"


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
