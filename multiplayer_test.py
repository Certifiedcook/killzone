from __future__ import annotations

import asyncio
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz
from multiplayer_server.app import KillZoneServer, read_packet
from src.multiplayer_net import PROTOCOL_VERSION, decode_packets, encode_packet


def test_framed_json_handles_fragmented_packets():
    first = encode_packet({"type": "alpha", "value": 1})
    second = encode_packet({"type": "beta", "value": 2})
    buffer = bytearray(first[:3])
    assert decode_packets(buffer) == []
    buffer.extend(first[3:] + second)
    assert [message["type"] for message in decode_packets(buffer)] == ["alpha", "beta"]
    assert not buffer


def test_pvp_force_is_symmetric_and_commands_are_authorized():
    game = kz.create_network_pvp_game(seed=9401)
    player_roles = sorted(unit.role for unit in game.living("player"))
    enemy_roles = sorted(unit.role for unit in game.living("enemy"))
    assert player_roles == enemy_roles

    player = game.living("player")[0]
    enemy = game.living("enemy")[0]
    accepted, reason = kz.apply_network_command(
        game,
        "enemy",
        {"type": "command", "action": "move", "units": [player.uid], "position": [20, 10]},
    )
    assert not accepted and "owned" in reason
    accepted, reason = kz.apply_network_command(
        game,
        "enemy",
        {"type": "command", "action": "move", "units": [enemy.uid], "position": [35, 10]},
    )
    assert accepted, reason
    assert enemy.order == "move"


def test_snapshots_normalize_each_players_faction():
    game = kz.create_network_pvp_game(seed=9402)
    blue = kz.serialize_network_snapshot(game, "player")
    red = kz.serialize_network_snapshot(game, "enemy")
    blue_local = {item["uid"] for item in blue["units"] if item["faction"] == "player"}
    red_local = {item["uid"] for item in red["units"] if item["faction"] == "player"}
    assert blue_local and red_local and blue_local.isdisjoint(red_local)
    assert len(blue_local) == len(red_local)


async def send(writer, message_type, **payload):
    message = {"type": message_type}
    message.update(payload)
    writer.write(encode_packet(message))
    await writer.drain()


async def read_until(reader, wanted, timeout=4.0):
    async def receive():
        while True:
            message = await read_packet(reader)
            if message["type"] == wanted:
                return message

    return await asyncio.wait_for(receive(), timeout=timeout)


async def exercise_two_player_lobby():
    service = KillZoneServer()
    server = await asyncio.start_server(service.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    blue_reader, blue_writer = await asyncio.open_connection("127.0.0.1", port)
    red_reader, red_writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send(blue_writer, "hello", protocol=PROTOCOL_VERSION, name="Blue")
        await send(red_writer, "hello", protocol=PROTOCOL_VERSION, name="Red")
        await read_until(blue_reader, "hello_ack")
        await read_until(red_reader, "hello_ack")
        await send(blue_writer, "create_room", name="Test Battle", seed=9403)
        joined = await read_until(blue_reader, "room_joined")
        room_id = joined["room_id"]
        await send(red_writer, "join_room", room_id=room_id)
        await read_until(red_reader, "room_joined")
        await send(blue_writer, "ready", ready=True)
        await send(red_writer, "ready", ready=True)
        blue_start = await read_until(blue_reader, "match_start")
        red_start = await read_until(red_reader, "match_start")
        assert blue_start["side"] == "player"
        assert red_start["side"] == "enemy"
        red_unit = next(
            unit for unit in red_start["snapshot"]["units"] if unit["faction"] == "player"
        )
        await send(
            red_writer,
            "command",
            sequence=1,
            action="move",
            units=[red_unit["uid"]],
            position=[35, 18],
        )
        updated = None
        for _ in range(10):
            snapshot = await read_until(red_reader, "snapshot")
            updated = next(
                unit
                for unit in snapshot["state"]["units"]
                if unit["uid"] == red_unit["uid"]
            )
            if updated["order"] == "move":
                break
        assert updated is not None and updated["order"] == "move"
    finally:
        blue_writer.close()
        red_writer.close()
        await blue_writer.wait_closed()
        await red_writer.wait_closed()
        server.close()
        await server.wait_closed()
        for room in service.rooms.values():
            if room.task:
                room.task.cancel()


def test_two_player_lobby_starts_authoritative_match():
    asyncio.run(exercise_two_player_lobby())


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(TESTS)} MULTIPLAYER TESTS PASSED")
