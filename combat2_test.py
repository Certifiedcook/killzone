"""Focused deterministic coverage for the Combat 2.0 simulation layer."""

from __future__ import annotations

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz


def fresh(seed=8801):
    game = kz.RealTimeGame(seed=seed, difficulty="Hard")
    game.units = []
    game.next_uid = 1
    game._uid_index = {}
    game._occupancy = {}
    game.ballistic_rounds = []
    game.tracers = []
    game.impacts = []
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


def round_toward(game, shooter, target, y_offset=0.0, damage=36.0, penetration=2.0):
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
        damage,
        penetration,
        shooter.weapon["supp"],
        target.uid,
    )
    game.next_ballistic_round_id += 1
    game.ballistic_rounds.append(projectile)
    return projectile


def test_shots_spawn_physical_rounds_before_damage_resolves():
    game = fresh()
    shooter = game.add_unit("player", "Marksman", 2, 8)
    target = game.add_unit("enemy", "Rifleman", 7, 8)
    shooter.combat2_acquired_uid = target.uid
    shooter.combat2_ready_at = 0
    shooter.fire_mode = "aimed"
    shooter.aim_progress = 1
    hp_before = target.hp
    ammo_before = shooter.ammo
    game.perform_shot(shooter, target)
    assert shooter.ammo == ammo_before - 1
    assert target.hp == hp_before
    assert len(game.ballistic_rounds) == 1
    for _ in range(12):
        game.update_ballistic_rounds(kz.SIM_DT)
    assert not game.ballistic_rounds
    assert game.tracers


def test_direct_round_creates_a_localized_wound():
    game = fresh(8802)
    shooter = game.add_unit("player", "Rifleman", 2, 9)
    target = game.add_unit("enemy", "Rifleman", 6, 9)
    round_toward(game, shooter, target)
    game.update_ballistic_rounds(0.2)
    assert target.hp < target.max_hp
    assert target.casualty in ("wounded", "incapacitated", "dead")
    assert max(target.wound_head, target.wound_torso, target.wound_arm, target.wound_leg) > 0


def test_near_miss_suppresses_along_the_real_trajectory():
    game = fresh(8803)
    shooter = game.add_unit("player", "Machine Gunner", 2, 10)
    target = game.add_unit("enemy", "Rifleman", 6, 10)
    hp_before = target.hp
    round_toward(game, shooter, target, y_offset=0.72)
    game.update_ballistic_rounds(0.2)
    assert target.hp == hp_before
    assert target.suppression > 0
    assert target.under_fire_until > game.time
    assert game.grid[target.tile[1]][target.tile[0]].ground_suppression > 0


def test_friendly_soldier_can_intercept_a_round():
    game = fresh(8804)
    shooter = game.add_unit("player", "Rifleman", 2, 11)
    friendly = game.add_unit("player", "Rifleman", 5, 11)
    target = game.add_unit("enemy", "Rifleman", 8, 11)
    round_toward(game, shooter, target)
    game.update_ballistic_rounds(0.25)
    assert friendly.hp < friendly.max_hp
    assert target.hp == target.max_hp


def test_hard_cover_stops_underpowered_rounds():
    game = fresh(8805)
    shooter = game.add_unit("player", "Rifleman", 2, 12)
    target = game.add_unit("enemy", "Rifleman", 7, 12)
    game.set_cell(4, 12, "wall")
    round_toward(game, shooter, target, penetration=1)
    game.update_ballistic_rounds(0.25)
    assert target.hp == target.max_hp
    assert not game.ballistic_rounds
    assert any(impact.kind in ("metal", "cover") for impact in game.impacts)


def test_localized_wounds_change_weapon_handling_and_movement():
    game = fresh(8806)
    shooter = game.add_unit("player", "Rifleman", 2, 13)
    target = game.add_unit("enemy", "Rifleman", 7, 13)
    baseline = game.hit_chance(shooter, target)
    shooter.wound_arm = 48
    wounded = game.hit_chance(shooter, target)
    breakdown = game.shot_breakdown(shooter, target)
    assert wounded < baseline
    assert breakdown["chance"] == wounded
    assert any(label == "localized wounds" for label, _value in breakdown["mods"])
    shooter.wound_leg = 70
    assert kz._combat2_wound_penalties(shooter)["move"] < 0.6


def test_identity_pool_is_large_unique_and_deterministic():
    assert kz.SOLDIER_IDENTITY_COMBINATIONS >= 1000
    first = [kz.generate_soldier_identity(991, uid)["full_name"] for uid in range(1, 1001)]
    second = [kz.generate_soldier_identity(991, uid)["full_name"] for uid in range(1, 1001)]
    assert first == second
    assert len(set(first)) == 1000
    game = fresh(8807)
    units = [game.add_unit("player", "Rifleman", 2, 2 + index) for index in range(4)]
    assert all(unit.full_name in unit.display_name for unit in units)
    assert len({unit.callsign for unit in units}) > 1


def test_squad_planner_assigns_offensive_and_defensive_jobs():
    attack = kz.RealTimeGame(
        seed=8808,
        difficulty="Hard",
        operation_config={"mission": "defense", "defense_duration": 180},
    )
    attack.plan_combat2_squads(force=True)
    active_attackers = [unit for unit in attack.living("enemy") if unit.reserve_active]
    assignments = {unit.combat2_assignment for unit in active_attackers}
    assert "support_by_fire" in assignments and "maneuver" in assignments
    assert all(plan["offensive"] for plan in attack.combat2_tactical_plans.values())

    defence = kz.RealTimeGame(seed=8809, difficulty="Hard")
    defence.plan_combat2_squads(force=True)
    assignments = {unit.combat2_assignment for unit in defence.living("enemy")}
    assert "covered_lane" in assignments
    assert assignments.intersection({"screen", "reserve"})
    assert not any(plan["offensive"] for plan in defence.combat2_tactical_plans.values())


def test_wounds_and_identities_round_trip_through_multiplayer_state():
    game = kz.create_network_pvp_game(seed=8810)
    unit = game.living("player")[0]
    unit.wound_arm = 31
    unit.wound_leg = 12
    snapshot = kz.serialize_network_snapshot(game, "player")
    record = next(item for item in snapshot["units"] if item["uid"] == unit.uid)
    assert record["full_name"] == unit.full_name
    assert record["wound_arm"] == 31
    replica = kz.create_network_pvp_game(seed=8810)
    kz.apply_network_snapshot(replica, snapshot)
    copied = replica.get_unit(unit.uid)
    assert copied.full_name == unit.full_name
    assert copied.wound_arm == 31 and copied.wound_leg == 12


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(TESTS)} COMBAT 2.0 TESTS PASSED")
