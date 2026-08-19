"""Dedicated entry point for the authoritative Kill Zone multiplayer service."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import random
import secrets
import sys
import time
from dataclasses import dataclass, field
from typing import Any


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("KILLZONE_DISABLE_ASSET_DOWNLOADS", "1")
os.environ.setdefault("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "1")

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent if (HERE.parent / "kill_zone.py").is_file() else HERE
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import kill_zone as kz  # noqa: E402
from src.multiplayer_net import (  # noqa: E402
    MAX_PACKET_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    encode_packet,
)


SERVICE_VERSION = "0.1.0"
MAX_CLIENTS = 32
MAX_ROOMS = 12
COMMAND_RATE = 80


async def read_packet(reader: asyncio.StreamReader) -> dict[str, Any]:
    header = await reader.readexactly(4)
    size = int.from_bytes(header, "big")
    if size <= 0 or size > MAX_PACKET_BYTES:
        raise ProtocolError(f"invalid packet size {size}")
    payload = await reader.readexactly(size)
    import json

    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON packet") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("packet must contain a string type")
    return message


@dataclass(eq=False)
class ClientConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connection_id: str = field(default_factory=lambda: secrets.token_hex(6))
    name: str = "Player"
    greeted: bool = False
    room_id: str | None = None
    slot: int | None = None
    command_times: list[float] = field(default_factory=list)

    @property
    def peer(self) -> str:
        address = self.writer.get_extra_info("peername")
        return str(address[0]) if address else "unknown"

    async def send(self, message_type: str, **payload: Any) -> None:
        message = {"type": message_type}
        message.update(payload)
        self.writer.write(encode_packet(message))
        await self.writer.drain()


@dataclass
class Room:
    room_id: str
    name: str
    password: str
    seed: int
    roster: list[str]
    battlefield: str
    players: list[ClientConnection] = field(default_factory=list)
    ready: set[str] = field(default_factory=set)
    status: str = "lobby"
    game: Any = None
    winner: str | None = None
    task: asyncio.Task | None = None
    pending_events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.room_id,
            "name": self.name,
            "players": len(self.players),
            "capacity": 2,
            "locked": bool(self.password),
            "status": self.status,
            "battlefield": self.battlefield,
        }

    def lobby_state(self) -> dict[str, Any]:
        return {
            "id": self.room_id,
            "name": self.name,
            "status": self.status,
            "seed": self.seed,
            "battlefield": self.battlefield,
            "players": [
                {
                    "id": player.connection_id,
                    "name": player.name,
                    "slot": player.slot,
                    "side": "BLUE" if player.slot == 0 else "RED",
                    "ready": player.connection_id in self.ready,
                }
                for player in self.players
            ],
        }


class KillZoneServer:
    def __init__(self):
        self.clients: set[ClientConnection] = set()
        self.rooms: dict[str, Room] = {}

    async def send_error(self, client: ClientConnection, code: str, message: str) -> None:
        await client.send("error", code=code, message=message[:180])

    async def broadcast(self, clients, message_type: str, **payload: Any) -> None:
        await asyncio.gather(
            *(client.send(message_type, **payload) for client in list(clients)),
            return_exceptions=True,
        )

    async def broadcast_room_list(self) -> None:
        rooms = [room.summary() for room in self.rooms.values() if room.status != "closed"]
        await self.broadcast(
            [client for client in self.clients if client.greeted],
            "server_list",
            rooms=rooms,
            online=len(self.clients),
        )

    async def broadcast_lobby(self, room: Room) -> None:
        await self.broadcast(room.players, "lobby_state", room=room.lobby_state())
        await self.broadcast_room_list()

    def new_room_id(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while True:
            room_id = "".join(secrets.choice(alphabet) for _ in range(6))
            if room_id not in self.rooms:
                return room_id

    async def join_room(self, client: ClientConnection, room: Room, password: str = "") -> None:
        if client.room_id:
            await self.send_error(client, "already_in_room", "Leave the current lobby first")
            return
        if room.status != "lobby" or len(room.players) >= 2:
            await self.send_error(client, "room_unavailable", "That room is full or already playing")
            return
        if room.password and room.password != password:
            await self.send_error(client, "wrong_password", "Incorrect room password")
            return
        client.room_id = room.room_id
        client.slot = 0 if not room.players else 1
        room.players.append(client)
        await client.send("room_joined", room_id=room.room_id, slot=client.slot)
        await self.broadcast_lobby(room)

    async def leave_room(self, client: ClientConnection, disconnected: bool = False) -> None:
        room = self.rooms.get(client.room_id or "")
        if room is None:
            client.room_id = None
            client.slot = None
            return
        old_slot = client.slot
        if client in room.players:
            room.players.remove(client)
        room.ready.discard(client.connection_id)
        client.room_id = None
        client.slot = None
        if room.status == "match" and room.winner is None:
            room.winner = "enemy" if old_slot == 0 else "player"
            await self.finish_match(room, "opponent disconnected")
        elif not room.players:
            room.status = "closed"
            if room.task:
                room.task.cancel()
            self.rooms.pop(room.room_id, None)
        else:
            # The remaining player becomes the room owner/blue side in a lobby.
            if room.status == "lobby":
                room.players[0].slot = 0
                await self.broadcast_lobby(room)
        if not disconnected:
            await client.send("room_left")
        await self.broadcast_room_list()

    async def start_match(self, room: Room) -> None:
        if room.status != "lobby" or len(room.players) != 2:
            return
        if any(player.connection_id not in room.ready for player in room.players):
            return
        room.status = "match"
        room.winner = None
        room.game = kz.create_network_pvp_game(
            seed=room.seed,
            roster=room.roster,
            battlefield=room.battlefield,
        )
        room.game.drain_events()
        room.pending_events.clear()
        for player in room.players:
            faction = "player" if player.slot == 0 else "enemy"
            snapshot = kz.serialize_network_snapshot(room.game, faction)
            await player.send(
                "match_start",
                room_id=room.room_id,
                side=faction,
                seed=room.seed,
                roster=room.roster,
                battlefield=room.battlefield,
                snapshot=snapshot,
            )
        await self.broadcast_room_list()
        room.task = asyncio.create_task(self.match_loop(room), name=f"match-{room.room_id}")

    async def match_loop(self, room: Room) -> None:
        tick = float(kz.SIM_DT)
        next_tick = time.monotonic()
        next_snapshot = next_tick
        try:
            while room.status == "match" and room.winner is None:
                now = time.monotonic()
                updates = 0
                while now >= next_tick and updates < 5:
                    room.game.update(tick)
                    room.pending_events.extend(room.game.drain_events())
                    room.pending_events = room.pending_events[-128:]
                    next_tick += tick
                    updates += 1
                if now >= next_snapshot:
                    for player in list(room.players):
                        faction = "player" if player.slot == 0 else "enemy"
                        state = kz.serialize_network_snapshot(room.game, faction)
                        state["events"] = kz.filter_network_events(
                            room.game,
                            faction,
                            room.pending_events,
                        )
                        await player.send(
                            "snapshot",
                            state=state,
                        )
                    room.pending_events.clear()
                    next_snapshot = now + 0.1
                winner = kz.network_pvp_winner(room.game)
                if winner:
                    room.winner = winner
                    await self.finish_match(room, "force eliminated")
                    break
                await asyncio.sleep(max(0.001, min(0.02, next_tick - time.monotonic())))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[match {room.room_id}] fatal simulation error: {exc}", flush=True)
            await self.broadcast(room.players, "error", code="match_crash", message="Match simulation stopped")
            room.status = "closed"

    async def finish_match(self, room: Room, reason: str) -> None:
        if room.status == "finished":
            return
        room.status = "finished"
        for player in list(room.players):
            faction = "player" if player.slot == 0 else "enemy"
            await player.send(
                "match_end",
                result="victory" if faction == room.winner else "defeat",
                reason=reason,
            )
        await self.broadcast_room_list()

    def command_allowed(self, client: ClientConnection) -> bool:
        now = time.monotonic()
        client.command_times = [stamp for stamp in client.command_times if now - stamp < 1.0]
        if len(client.command_times) >= COMMAND_RATE:
            return False
        client.command_times.append(now)
        return True

    async def handle_message(self, client: ClientConnection, message: dict[str, Any]) -> None:
        message_type = message["type"]
        if message_type == "hello":
            if client.greeted:
                raise ProtocolError("duplicate hello")
            if int(message.get("protocol", -1)) != PROTOCOL_VERSION:
                await self.send_error(client, "protocol_mismatch", "Client and server versions differ")
                raise ProtocolError("protocol mismatch")
            client.name = str(message.get("name", "Player")).strip()[:24] or "Player"
            client.greeted = True
            await client.send(
                "hello_ack",
                protocol=PROTOCOL_VERSION,
                service_version=SERVICE_VERSION,
                connection_id=client.connection_id,
            )
            await client.send("server_list", rooms=[room.summary() for room in self.rooms.values()])
            return
        if not client.greeted:
            raise ProtocolError("hello required")
        if message_type == "ping":
            await client.send("pong", time=message.get("time"), server_time=time.time())
        elif message_type == "list_rooms":
            await client.send(
                "server_list",
                rooms=[room.summary() for room in self.rooms.values() if room.status != "closed"],
                online=len(self.clients),
            )
        elif message_type == "create_room":
            if len(self.rooms) >= MAX_ROOMS:
                await self.send_error(client, "room_limit", "The server has reached its room limit")
                return
            if client.room_id:
                await self.send_error(client, "already_in_room", "Leave the current lobby first")
                return
            room = Room(
                room_id=self.new_room_id(),
                name=str(message.get("name", f"{client.name}'s battle")).strip()[:36]
                or f"{client.name}'s battle",
                password=str(message.get("password", ""))[:32],
                seed=int(message.get("seed", random.randint(1, 999_999_999))) % 1_000_000_000,
                roster=kz.sanitize_network_roster(message.get("roster")),
                battlefield=kz.sanitize_network_battlefield(message.get("battlefield")),
            )
            self.rooms[room.room_id] = room
            await self.join_room(client, room)
        elif message_type == "join_room":
            room = self.rooms.get(str(message.get("room_id", "")).upper())
            if room is None:
                await self.send_error(client, "room_missing", "That room no longer exists")
                return
            await self.join_room(client, room, str(message.get("password", "")))
        elif message_type == "leave_room":
            await self.leave_room(client)
        elif message_type == "ready":
            room = self.rooms.get(client.room_id or "")
            if room is None or room.status != "lobby":
                return
            if bool(message.get("ready", True)):
                room.ready.add(client.connection_id)
            else:
                room.ready.discard(client.connection_id)
            await self.broadcast_lobby(room)
            await self.start_match(room)
        elif message_type == "command":
            room = self.rooms.get(client.room_id or "")
            if room is None or room.status != "match" or room.game is None:
                return
            if not self.command_allowed(client):
                await self.send_error(client, "rate_limit", "Too many commands")
                return
            faction = "player" if client.slot == 0 else "enemy"
            accepted, reason = kz.apply_network_command(room.game, faction, message)
            if not accepted:
                await client.send("command_rejected", sequence=message.get("sequence"), reason=reason)
        elif message_type == "disconnect":
            raise ConnectionAbortedError(str(message.get("reason", "client closed")))

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = ClientConnection(reader, writer)
        if len(self.clients) >= MAX_CLIENTS:
            writer.write(encode_packet({"type": "error", "code": "server_full", "message": "Server full"}))
            await writer.drain()
            writer.close()
            return
        self.clients.add(client)
        print(f"[connect] {client.peer} ({len(self.clients)} online)", flush=True)
        try:
            while True:
                message = await asyncio.wait_for(read_packet(reader), timeout=20.0)
                await self.handle_message(client, message)
        except (asyncio.IncompleteReadError, ConnectionError, ConnectionAbortedError, TimeoutError):
            pass
        except ProtocolError as exc:
            print(f"[protocol] {client.peer}: {exc}", flush=True)
        except Exception as exc:
            print(f"[client] {client.peer}: {exc}", flush=True)
        finally:
            await self.leave_room(client, disconnected=True)
            self.clients.discard(client)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            print(f"[disconnect] {client.peer} ({len(self.clients)} online)", flush=True)


async def main() -> None:
    host = os.environ.get("KILLZONE_BIND", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", os.environ.get("KILLZONE_PORT", "25503")))
    service = KillZoneServer()
    server = await asyncio.start_server(service.handle_client, host=host, port=port, limit=MAX_PACKET_BYTES + 4)
    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"KILL ZONE PVP SERVER {SERVICE_VERSION}", flush=True)
    print(f"Protocol {PROTOCOL_VERSION} listening on {addresses}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
