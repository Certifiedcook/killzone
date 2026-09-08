from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

import kill_zone as kz
import multiplayer_server.app as server_module
import src.multiplayer_net as transport
from multiplayer_server.app import ClientConnection, KillZoneServer, Room, read_packet
from src.multiplayer_net import PROTOCOL_VERSION, ProtocolError, decode_packets, encode_packet


def test_framed_json_handles_fragmented_packets():
    first = encode_packet({"type": "alpha", "value": 1})
    second = encode_packet({"type": "beta", "value": 2})
    buffer = bytearray(first[:3])
    assert decode_packets(buffer) == []
    buffer.extend(first[3:] + second)
    assert [message["type"] for message in decode_packets(buffer)] == ["alpha", "beta"]
    assert not buffer


def test_framed_json_preserves_partial_frame_after_packet_batch():
    packets = [encode_packet({"type": "command", "sequence": index}) for index in range(500)]
    buffer = bytearray(b"".join(packets[:-1]) + packets[-1][:7])
    assert [item["sequence"] for item in decode_packets(buffer)] == list(range(499))
    assert buffer == packets[-1][:7]
    buffer.extend(packets[-1][7:])
    assert decode_packets(buffer) == [{"type": "command", "sequence": 499}]
    assert not buffer


def test_client_and_server_reject_nonfinite_and_malformed_json():
    async def check():
        for payload in (
            b'{"type":"command","value":NaN}',
            b'{"type":"command","value":Infinity}',
            b'{"type":"command","value":1e400}',
            b'{"type":"command","value":-1e400}',
            b'{"type":3}',
        ):
            frame = len(payload).to_bytes(4, "big") + payload
            try:
                decode_packets(bytearray(frame))
            except ProtocolError:
                pass
            else:
                raise AssertionError("desktop accepted invalid JSON")
            reader = asyncio.StreamReader()
            reader.feed_data(frame)
            try:
                await read_packet(reader)
            except ProtocolError:
                pass
            else:
                raise AssertionError("server accepted invalid JSON")

    asyncio.run(check())


def test_encoding_rejects_nonfinite_values_and_invalid_envelopes():
    for message in (
        {"type": "command", "value": float("nan")},
        {"type": "command", "value": float("inf")},
        {"value": "missing type"},
        {"type": "command", "value": object()},
    ):
        try:
            encode_packet(message)
        except ProtocolError:
            pass
        else:
            raise AssertionError("encoder accepted invalid message")


def test_client_handshake_precedes_commands_queued_while_connecting():
    client = transport.NetworkClient()
    client.send("list_rooms")
    frames = bytearray()

    class Socket:
        def setblocking(self, value):
            pass

        def send(self, data):
            frames.extend(data)
            client.close()
            return len(data)

        def close(self):
            pass

    sock = Socket()
    with patch.object(transport.socket, "create_connection", return_value=sock), patch.object(
        transport.select, "select", return_value=([], [sock], [])
    ):
        client._network_loop(1.0)
    assert [message["type"] for message in decode_packets(frames)] == ["hello", "list_rooms"]


def test_cancelled_connection_does_not_report_connected():
    client = transport.NetworkClient()
    client.connecting = True
    sock = SimpleNamespace(setblocking=lambda value: None, close=lambda: None)

    def connect(*args, **kwargs):
        client.close()
        return sock

    with patch.object(transport.socket, "create_connection", side_effect=connect):
        client._network_loop(1.0)
    assert not client.connected and not client.connecting
    assert client.poll() == []


def test_client_cannot_replace_a_worker_that_is_still_exiting():
    client = transport.NetworkClient()
    client._thread = SimpleNamespace(is_alive=lambda: True)
    with patch.object(transport.threading, "Thread") as new_thread:
        assert not client.connect("127.0.0.1", 1, "Test")
    new_thread.assert_not_called()


class RecordingWriter:
    def __init__(self, failure=None, stalled=False):
        self.packets = bytearray()
        self.failure = failure
        self.stalled = stalled
        self.closed = False

    def get_extra_info(self, name):
        return ("127.0.0.1", 1) if name == "peername" else None

    def is_closing(self):
        return self.closed

    def write(self, data):
        self.packets.extend(data)

    async def drain(self):
        if self.failure:
            raise self.failure
        if self.stalled:
            await asyncio.Future()

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def messages(self):
        return decode_packets(self.packets)


def test_password_room_creator_joins_and_guests_still_need_password():
    async def check():
        service = KillZoneServer()
        owner = ClientConnection(asyncio.StreamReader(), RecordingWriter(), greeted=True)
        guest = ClientConnection(asyncio.StreamReader(), RecordingWriter(), greeted=True)
        await service.handle_message(
            owner, {"type": "create_room", "password": "private", "seed": 9404}
        )
        assert owner.room_id in service.rooms
        room = service.rooms[owner.room_id]
        assert room.players == [owner] and owner.slot == 0
        assert any(message["type"] == "room_joined" for message in owner.writer.messages())
        await service.join_room(guest, room, "incorrect")
        assert guest.room_id is None and room.players == [owner]
        assert guest.writer.messages()[-1]["code"] == "wrong_password"
        await service.join_room(guest, room, "private")
        assert room.players == [owner, guest] and guest.slot == 1

    asyncio.run(check())


def test_stalled_peer_send_times_out_and_closes_connection():
    async def check():
        writer = RecordingWriter(stalled=True)
        client = ClientConnection(asyncio.StreamReader(), writer)
        with patch.object(server_module, "SEND_TIMEOUT", 0.01, create=True):
            try:
                await asyncio.wait_for(client.send("snapshot", state={}), timeout=0.25)
            except TimeoutError:
                pass
            else:
                raise AssertionError("stalled write did not time out")
        assert writer.closed

    asyncio.run(check())


def test_failed_peer_does_not_prevent_opponent_match_result():
    async def check():
        service = KillZoneServer()
        broken = ClientConnection(
            asyncio.StreamReader(), RecordingWriter(failure=ConnectionResetError()), slot=0
        )
        healthy = ClientConnection(asyncio.StreamReader(), RecordingWriter(), slot=1)
        room = Room("TEST", "Test", "", 1, [], "farmland", players=[broken, healthy],
                    status="match", winner="enemy")
        await service.finish_match(room, "force eliminated")
        assert room.status == "finished" and broken.writer.closed
        assert healthy.writer.messages() == [
            {"type": "match_end", "result": "victory", "reason": "force eliminated"}
        ]

    asyncio.run(check())


def test_broadcast_does_not_silently_swallow_invalid_server_messages():
    async def check():
        service = KillZoneServer()
        client = ClientConnection(asyncio.StreamReader(), RecordingWriter())
        try:
            await service.broadcast([client], "snapshot", state={"time": float("nan")})
        except ProtocolError:
            pass
        else:
            raise AssertionError("invalid server state was silently swallowed")

    asyncio.run(check())


def test_failed_snapshot_peer_does_not_crash_simulation():
    async def check():
        service = KillZoneServer()
        broken = ClientConnection(
            asyncio.StreamReader(), RecordingWriter(failure=ConnectionResetError()), slot=0
        )
        healthy = ClientConnection(asyncio.StreamReader(), RecordingWriter(), slot=1)
        game = SimpleNamespace(update=lambda dt: None, drain_events=lambda: [])
        room = Room("TEST", "Test", "", 1, [], "farmland", players=[broken, healthy],
                    status="match", game=game)
        with patch.object(kz, "serialize_network_snapshot", return_value={}), patch.object(
            kz, "filter_network_events", return_value=[]
        ), patch.object(kz, "network_pvp_winner", return_value="enemy"):
            await service.match_loop(room)
        assert room.status == "finished"
        assert [message["type"] for message in healthy.writer.messages()] == ["snapshot", "match_end"]

    asyncio.run(check())


def test_failed_room_cleanup_still_releases_client_socket():
    async def check():
        service = KillZoneServer()
        reader = asyncio.StreamReader()
        reader.feed_eof()
        writer = RecordingWriter()
        with patch.object(service, "leave_room", AsyncMock(side_effect=RuntimeError("cleanup failed"))):
            try:
                await service.handle_client(reader, writer)
            except RuntimeError:
                pass
        assert not service.clients and writer.closed

    asyncio.run(check())


def test_last_match_player_leaving_removes_empty_room():
    async def check():
        service = KillZoneServer()
        player = ClientConnection(asyncio.StreamReader(), RecordingWriter(), room_id="TEST", slot=0)
        room = Room("TEST", "Test", "", 1, [], "farmland", players=[player], status="match")
        service.rooms[room.room_id] = room
        await service.leave_room(player, disconnected=True)
        assert player.room_id is None and not service.rooms

    asyncio.run(check())


def test_malformed_command_is_rejected_without_disconnect():
    async def check():
        service = KillZoneServer()
        game = kz.create_network_pvp_game(seed=9405)
        player = ClientConnection(
            asyncio.StreamReader(), RecordingWriter(), greeted=True, room_id="TEST", slot=0
        )
        room = Room("TEST", "Test", "", 1, [], "farmland", players=[player],
                    status="match", game=game)
        service.rooms[room.room_id] = room
        uid = game.living("player")[0].uid
        for sequence, payload in enumerate((
            {"units": [[uid]], "position": [1, 1]},
            {"units": [uid], "position": [{}, 1]},
            {"units": [uid], "position": [1, 1], "action": "fire", "target": []},
        )):
            await service.handle_message(
                player, {"type": "command", "action": "move", "sequence": sequence, **payload}
            )
            rejected = player.writer.messages()[-1]
            assert rejected["type"] == "command_rejected" and rejected["sequence"] == sequence
        assert room.status == "match" and not player.writer.closed
        await service.handle_message(player, {"type": "ping", "time": 1})
        assert player.writer.messages()[-1]["type"] == "pong"

    asyncio.run(check())


def test_command_rate_limit_recovers_after_one_second():
    async def check():
        service = KillZoneServer()
        client = ClientConnection(asyncio.StreamReader(), RecordingWriter())
        with patch.object(server_module.time, "monotonic", return_value=100.0) as monotonic:
            assert all(service.command_allowed(client) for _ in range(server_module.COMMAND_RATE))
            assert not service.command_allowed(client)
            monotonic.return_value = 100.999
            assert not service.command_allowed(client)
            monotonic.return_value = 101.0
            assert service.command_allowed(client)

    asyncio.run(check())


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


def test_pvp_uses_explicit_game_rules_through_sustained_updates():
    from engine.networking import NetworkGame
    from engine.simulation import RealTimeGame

    game = kz.create_network_pvp_game(seed=9410)
    assert isinstance(game, NetworkGame) and isinstance(game, RealTimeGame)
    assert all(name not in vars(game) for name in (
        "update_ai", "update_enemy_builders", "update_objectives", "check_end"
    ))
    game.notifications.append({"until": 0.1, "text": "expired"})
    for _ in range(40):
        game.update(kz.SIM_DT)
    assert game.time >= 1.0
    assert game.mission_type == "pvp" and game.battle_stage == "PLAYER VERSUS PLAYER"
    assert len(game.objectives) == 1 and game.objectives[0]["state"] == "active"
    assert not game._reserves_activated
    assert all(item["until"] > game.time for item in game.notifications)
    game.update_objectives()  # The lifecycle callback takes no timestep argument.


def test_command_validation_rejects_bad_fields_before_mutating_game():
    from engine.networking import apply_network_command

    game = kz.create_network_pvp_game(seed=9411)
    unit = game.living("player")[0]
    base = {"type": "command", "action": "move", "units": [unit.uid], "position": [8, 8]}
    invalid = [
        None, [], "command", {},
        base | {"action": {}},
        base | {"units": []},
        base | {"units": [unit.uid] * (kz.MAX_PLAYER_UNITS + 1)},
        base | {"units": [[unit.uid]]},
        base | {"units": [str(unit.uid)]},
        base | {"units": [True]},
        base | {"units": [-1]},
        base | {"position": [float("nan"), 8]},
        base | {"position": [float("inf"), 8]},
        base | {"position": [-0.1, 8]},
        base | {"position": [kz.MAP_W, 8]},
        base | {"position": [10 ** 500, 8]},
        base | {"position": ["8", 8]},
        base | {"position": [True, 8]},
        base | {"position": [8]},
        base | {"position": None},
        base | {"cook": float("nan")},
        base | {"cook": float("inf")},
        base | {"cook": -0.1},
        base | {"cook": 1.81},
        base | {"cook": "0.5"},
        base | {"mode": "teleport"},
        base | {"mode": []},
        base | {"formation": []},
        base | {"append": "false"},
        base | {"emergency": 1},
        base | {"enabled": "true"},
        base | {"smoke": None},
        base | {"sequence": True},
        base | {"sequence": -1},
        base | {"sequence": "1"},
        base | {"action": "fire", "target": []},
        base | {"action": "fire", "target": True},
        base | {"action": "fire_mode", "mode": "safe"},
        base | {"action": "build", "kind": {}},
        base | {"action": "build", "kind": "unknown"},
    ]
    before = (unit.order, unit.move_mode, list(unit.path), list(unit.waypoints), game.rng.getstate())
    for message in invalid:
        accepted, reason = apply_network_command(game, "player", message)
        assert not accepted and reason, message
        assert (unit.order, unit.move_mode, unit.path, unit.waypoints, game.rng.getstate()) == before
    accepted, reason = apply_network_command(game, "spectator", base)
    assert not accepted and reason == "Invalid faction"
    accepted, reason = apply_network_command(game, "player", base | {"position": [8.5, 8.5]})
    assert accepted, reason


def test_replicated_terrain_invalidates_only_its_world_when_changed():
    game = kz.create_network_pvp_game(seed=9412)
    other = kz.create_network_pvp_game(seed=9413)
    original = game.terrain_revision
    other_original = other.terrain_revision
    cell = game.grid[8][8]
    changed = "woods" if cell.terrain != "woods" else "open"
    state = {"cells": [[8, 8, changed, None, None, 0.0, 0.0, False]]}
    kz.apply_network_snapshot(game, state)
    assert game.grid[8][8] is cell
    assert game.terrain_revision == original + 1
    assert other.terrain_revision == other_original
    kz.apply_network_snapshot(game, state)
    assert game.terrain_revision == original + 1
    kz.apply_network_snapshot(game, {"cells": []})
    assert cell.terrain == game.network_initial_cells[8][8][0]
    assert game.terrain_revision == original + 2


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
        for room in list(service.rooms.values()):
            if room.task:
                room.task.cancel()
        # Server callbacks outlive the listening socket; let their cleanup finish.
        async def clients_closed():
            while service.clients:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(clients_closed(), timeout=2.0)


def test_two_player_lobby_starts_authoritative_match():
    asyncio.run(exercise_two_player_lobby())


TESTS = [value for name, value in list(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL {len(TESTS)} MULTIPLAYER TESTS PASSED")
