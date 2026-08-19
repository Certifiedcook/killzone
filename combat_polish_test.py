"""Focused deterministic coverage for the Combat Feel 2.1 polish layer."""

from __future__ import annotations

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz


def fresh(seed=9901):
    game = kz.RealTimeGame(seed=seed, difficulty="Hard")
    game.units = []
    game.next_uid = 1
    game._uid_index = {}
    game._occupancy = {}
    game.ballistic_rounds = []
    game.tracers = []
    game.impacts = []
    game.events = []
    game.victory = False
    game.defeat = False
    game.check_end = lambda: None
    for row in game.grid:
        for cell in row:
            cell.reset_terrain("open")
            cell.smoke = 0
            cell.fire = 0
            cell.ground_suppression = 0
    return game


def round_toward(game, shooter, target, y_offset=0.0):
    dx, dy = target.x - shooter.x, target.y + y_offset - shooter.y
    length = math.hypot(dx, dy)
    projectile = kz.BallisticRound(
        game.next_ballistic_round_id,
        shooter.uid,
        shooter.faction,
        shooter.weapon_name,
        shooter.x + dx / length * 0.3,
        shooter.y + dy / length * 0.3,
        dx / length * 50,
        dy / length * 50,
        12,
        34,
        2,
        shooter.weapon["supp"],
        target.uid,
    )
    game.next_ballistic_round_id += 1
    game.ballistic_rounds.append(projectile)
    return projectile


def test_deliberate_fire_refuses_an_occupied_friendly_lane():
    game = fresh()
    shooter = game.add_unit("player", "Rifleman", 2, 8)
    friendly = game.add_unit("player", "Rifleman", 5, 8)
    target = game.add_unit("enemy", "Rifleman", 8, 8)
    ammo = shooter.ammo
    assert game.firing_lane_risk(shooter, target.pos, target.uid)[2] is friendly
    assert game.issue_fire(shooter, target) is False
    assert shooter.polish_order_state == "UNABLE: FRIENDLY LANE"
    game.perform_shot(shooter, target)
    assert shooter.ammo == ammo and not game.ballistic_rounds


def test_ai_selects_a_clear_alternative_target():
    game = fresh(9902)
    shooter = game.add_unit("enemy", "Rifleman", 2, 9)
    blocker = game.add_unit("enemy", "Rifleman", 5, 9)
    blocked = game.add_unit("player", "Rifleman", 8, 9)
    clear = game.add_unit("player", "Machine Gunner", 7, 12)
    assert game.firing_lane_risk(shooter, blocked.pos, blocked.uid)[2] is blocker
    assert game.issue_fire(shooter, blocked)
    assert shooter.target_uid == clear.uid


def test_weapon_profiles_create_bursts_and_recovery_pauses():
    game = fresh(9903)
    shooter = game.add_unit("player", "Rifleman", 2, 10)
    target = game.add_unit("enemy", "Rifleman", 8, 10)
    shooter.combat2_acquired_uid = target.uid
    shooter.combat2_ready_at = 0
    fired = []
    for index in range(8):
        game.time = index * 0.12
        shooter.next_shot = 0
        before = shooter.ammo
        game.perform_shot(shooter, target)
        fired.append(before - shooter.ammo)
    profile = kz.combat_polish_weapon_profile(shooter)
    assert profile["burst"] == (2, 3)
    assert sum(fired) >= 2 and 0 in fired[2:]
    assert shooter.polish_burst_pause_until > 0
    assert shooter.polish_recoil > 0


def test_near_miss_causes_a_protective_reaction_and_audio_event():
    game = fresh(9904)
    shooter = game.add_unit("player", "Machine Gunner", 2, 11)
    target = game.add_unit("enemy", "Rifleman", 6, 11)
    round_toward(game, shooter, target, y_offset=0.52)
    game.update_ballistic_rounds(0.2)
    assert target.polish_reaction_kind in ("FLINCH", "DUCK", "PINNED")
    if target.polish_reaction_kind in ("DUCK", "PINNED"):
        assert target.stance in ("crouched", "prone")
    assert target.polish_reaction_until > game.time
    assert any(event["type"] == "near_miss" for event in game.events)


def test_smoke_does_not_blind_an_active_support_lane():
    game = fresh(9905)
    support = game.add_unit("player", "Machine Gunner", 2, 12)
    engineer = game.add_unit("player", "Engineer", 3, 14)
    support.order = "suppress"
    support.target_pos = (10, 12)
    grenades = engineer.smoke_grenades
    assert game.smoke_blocks_support(engineer, (6, 12)) is support
    assert game.throw_grenade(engineer, (6, 12), smoke=True) is False
    assert engineer.smoke_grenades == grenades
    assert engineer.polish_order_state == "UNABLE: SUPPORT LANE"


def test_group_move_reserves_distinct_arrival_slots_and_avoids_reissue():
    game = fresh(9906)
    units = [game.add_unit("enemy", "Rifleman", 2, 4 + index) for index in range(3)]
    game.time = 4
    game.issue_move(units, (10, 8), mode="safe", formation="wedge")
    destinations = [unit.waypoints[-1] for unit in units]
    assert len(set(destinations)) == len(destinations)
    first_waypoint_lists = [list(unit.waypoints) for unit in units]
    game.issue_move(units, (10, 8), mode="safe", formation="wedge")
    assert [unit.waypoints for unit in units] == first_waypoint_lists


def test_ai_observes_the_preparation_beat_and_commits_to_orders():
    game = fresh(9907)
    enemy = game.add_unit("enemy", "Rifleman", 8, 8)
    player = game.add_unit("player", "Rifleman", 11, 8)
    game.time = 0.5
    game.ai_decide(enemy)
    assert enemy.order == "idle"
    assert "preparation" in enemy.combat2_decision_reason
    game.time = 2.2
    game.ai_decide(enemy)
    assert enemy.order in kz.COMBAT_POLISH_COMMIT_ORDERS
    assert enemy.polish_plan_commit_until > game.time or enemy.target_uid == player.uid


def test_new_audio_layers_cover_cracks_and_material_impacts():
    crack = dict(
        kz.presentation_audio_mix(
            {"type": "near_miss", "pos": (4, 5), "proximity": 0.1}, 1.0, 60
        )
    )
    metal = dict(
        kz.presentation_audio_mix(
            {"type": "impact", "pos": (4, 5), "material": "metal"}, 2.0, 60
        )
    )
    assert crack["crack"] > 0.2
    assert "mechanical" in metal and "crack" in metal


def test_polish_state_round_trips_through_authoritative_multiplayer():
    game = kz.create_network_pvp_game(seed=9908)
    unit = game.living("player")[0]
    unit.polish_order_state = "UNABLE: FRIENDLY LANE"
    unit.polish_lane_reason = "FRIENDLY IN LANE"
    unit.polish_reaction_kind = "DUCK"
    game.polish_recent_tracers = [
        (unit.x, unit.y, unit.x + 1, unit.y, "player", game.time + 0.1)
    ]
    snapshot = kz.serialize_network_snapshot(game, "player")
    replica = kz.create_network_pvp_game(seed=9908)
    kz.apply_network_snapshot(replica, snapshot)
    copied = replica.get_unit(unit.uid)
    assert copied.polish_order_state == unit.polish_order_state
    assert copied.polish_lane_reason == unit.polish_lane_reason
    assert copied.polish_reaction_kind == "DUCK"
    assert replica.polish_recent_tracers[-1][4] == "player"


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(TESTS)} COMBAT FEEL 2.1 TESTS PASSED")
