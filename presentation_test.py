from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz


def test_audio_mix_changes_by_weapon_and_distance():
    rifle_near = dict(kz.presentation_audio_mix({"type": "shot", "weapon": "Rifle"}, 2, 20))
    rifle_far = dict(kz.presentation_audio_mix({"type": "shot", "weapon": "Rifle"}, 28, 20))
    heavy = dict(
        kz.presentation_audio_mix({"type": "shot", "weapon": "Heavy Machine Gun"}, 2, 20)
    )
    explosion = dict(
        kz.presentation_audio_mix({"type": "explosion", "radius": 3.5}, 4, 70)
    )
    assert "rifle" in rifle_near and rifle_near["rifle"] > rifle_far["rifle"]
    assert "distant" in rifle_far and "heavy" in heavy
    assert {"blast", "rumble", "debris"}.issubset(explosion)


def test_weather_particles_are_stable_but_animate():
    first = kz.presentation_weather_particles("rain", 901, 2.0, 640, 360, 24)
    same = kz.presentation_weather_particles("rain", 901, 2.0, 640, 360, 24)
    later = kz.presentation_weather_particles("rain", 901, 2.2, 640, 360, 24)
    assert first == same
    assert first != later
    assert all(0 <= x < 640 and 0 <= y < 360 and length >= 7 for x, y, length, _ in first)


def test_terrain_marks_are_seeded_and_bounded():
    first = kz.presentation_terrain_marks("rubble", 8, 12, 4421, 6)
    same = kz.presentation_terrain_marks("rubble", 8, 12, 4421, 6)
    other = kz.presentation_terrain_marks("rubble", 9, 12, 4421, 6)
    assert first == same
    assert first != other
    assert all(0 <= value <= 1 for mark in first for value in mark)


def test_network_snapshot_round_trips_battlefield_effects():
    game = kz.create_network_pvp_game(seed=5531)
    game.tracers.append(kz.Tracer((4, 5), (11, 8), 0.17, 0.20))
    game.impacts.append(kz.Impact(11, 8, "cover", 0.19))
    game.explosions.append(kz.Explosion(13, 9, 0.35, 2.5, 80, 95, "HE", "player"))
    snapshot = kz.serialize_network_snapshot(game, "player")
    replica = kz.create_network_pvp_game(seed=5531)
    kz.apply_network_snapshot(replica, snapshot)
    assert replica.tracers[-1].a == (4, 5)
    assert replica.tracers[-1].b == (11, 8)
    assert replica.impacts[-1].kind == "cover"
    assert replica.explosions[-1].radius == 2.5


def test_multiplayer_audio_does_not_reveal_exact_hidden_shooter():
    game = kz.create_network_pvp_game(seed=5532)
    hidden = {"type": "shot", "weapon": "Rifle", "pos": (30, 10), "faction": "enemy"}
    filtered = kz.filter_network_events(game, "player", [hidden])
    assert filtered and filtered[0]["audible_only"]
    assert filtered[0]["pos"] != hidden["pos"]
    local = {"type": "shot", "weapon": "Rifle", "pos": (4, 8), "faction": "player"}
    assert kz.filter_network_events(game, "player", [local])[0] == local


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(TESTS)} PRESENTATION TESTS PASSED")
