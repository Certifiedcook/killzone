"""Shared framed-JSON networking for Kill Zone multiplayer.

The transport intentionally uses only the Python standard library, so the
dedicated service needs no networking framework and the desktop client can
keep all socket work off Pygame's render/input thread.
"""

from __future__ import annotations

import json
import queue
import select
import socket
import struct
import threading
import time
from typing import Any


PROTOCOL_VERSION = 1
DEFAULT_SERVER_HOST = "88.99.98.156"
DEFAULT_SERVER_PORT = 25503
MAX_PACKET_BYTES = 2 * 1024 * 1024
HEADER = struct.Struct("!I")


class ProtocolError(RuntimeError):
    """Raised when a peer sends a malformed or unsupported packet."""


def encode_packet(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_PACKET_BYTES:
        raise ProtocolError(f"packet exceeds {MAX_PACKET_BYTES} bytes")
    return HEADER.pack(len(payload)) + payload


def decode_packets(buffer: bytearray) -> list[dict[str, Any]]:
    messages = []
    while len(buffer) >= HEADER.size:
        (size,) = HEADER.unpack_from(buffer)
        if size <= 0 or size > MAX_PACKET_BYTES:
            raise ProtocolError(f"invalid packet size {size}")
        frame_end = HEADER.size + size
        if len(buffer) < frame_end:
            break
        payload = bytes(buffer[HEADER.size:frame_end])
        del buffer[:frame_end]
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("invalid JSON packet") from exc
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise ProtocolError("packet must be an object with a string type")
        messages.append(message)
    return messages


class NetworkClient:
    """Background TCP client with thread-safe queues for the Pygame frontend."""

    def __init__(self):
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.outgoing: queue.Queue[dict[str, Any]] = queue.Queue()
        self.connected = False
        self.connecting = False
        self.host = ""
        self.port = 0
        self.player_name = "Player"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def connect(self, host: str, port: int, player_name: str, timeout: float = 6.0) -> bool:
        if self.connected or self.connecting:
            return False
        while True:
            try:
                self.outgoing.get_nowait()
            except queue.Empty:
                break
        self.host = str(host).strip()
        self.port = int(port)
        self.player_name = str(player_name).strip()[:24] or "Player"
        self._stop.clear()
        self.connecting = True
        self._thread = threading.Thread(
            target=self._network_loop,
            args=(float(timeout),),
            name="killzone-network",
            daemon=True,
        )
        self._thread.start()
        return True

    def send(self, message_type: str, **payload: Any) -> None:
        message = {"type": message_type}
        message.update(payload)
        self.outgoing.put(message)

    def poll(self, limit: int = 128) -> list[dict[str, Any]]:
        messages = []
        for _ in range(max(1, limit)):
            try:
                messages.append(self.events.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self, reason: str = "client closed") -> None:
        self._stop.set()

    def _network_loop(self, timeout: float) -> None:
        sock = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            sock.setblocking(False)
            self.connected = True
            self.connecting = False
            self.events.put({"type": "network_connected", "host": self.host, "port": self.port})
            self.outgoing.put(
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "name": self.player_name,
                    "client": "kill-zone-desktop",
                }
            )
            incoming = bytearray()
            pending = bytearray()
            last_ping = time.monotonic()
            while not self._stop.is_set():
                while True:
                    try:
                        pending.extend(encode_packet(self.outgoing.get_nowait()))
                    except queue.Empty:
                        break
                if time.monotonic() - last_ping >= 5.0:
                    pending.extend(encode_packet({"type": "ping", "time": time.time()}))
                    last_ping = time.monotonic()
                readable, writable, exceptional = select.select(
                    [sock], [sock] if pending else [], [sock], 0.05
                )
                if exceptional:
                    raise ConnectionError("socket exception")
                if writable and pending:
                    sent = sock.send(pending)
                    if sent <= 0:
                        raise ConnectionError("connection closed while sending")
                    del pending[:sent]
                if readable:
                    chunk = sock.recv(64 * 1024)
                    if not chunk:
                        raise ConnectionError("server closed the connection")
                    incoming.extend(chunk)
                    for message in decode_packets(incoming):
                        self.events.put(message)
        except Exception as exc:
            self.events.put({"type": "network_error", "message": str(exc)[:240]})
        finally:
            self.connecting = False
            was_connected = self.connected
            self.connected = False
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if was_connected:
                self.events.put({"type": "network_disconnected"})
