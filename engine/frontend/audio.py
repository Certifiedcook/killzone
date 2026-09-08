"""Frontend / audio for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.frontend.support import battle_audio_cue_for_event
from engine.frontend.support import presentation_audio_mix
from engine.rules import clamp
from engine.rules import dist
from engine.definitions import AUDIO_DIR
from engine.definitions import FX_DIR
from engine.definitions import PRESENTATION_AUDIO_DURATIONS
from engine.definitions import TACTICAL_AUDIO_VOLUMES
from engine.frontend.backend import pygame
import math
import random
import time


class AudioSystem:
    def init_presentation_assets(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            self.audio_enabled = False
        self.audio = {}
        self.refresh_assets()

    def refresh_assets(self):
        if self.audio_enabled:
            for name in (
                "rifle_556.mp3",
                "rifle_762.mp3",
                "smg_9mm.mp3",
                "explosion1.ogg",
                "explosion2.ogg",
                "hurt_01.mp3",
                "hurt_03.mp3",
                "scream_horror1.mp3",
            ):
                path = AUDIO_DIR / name
                if path.exists() and name not in self.audio:
                    try:
                        self.audio[name] = pygame.mixer.Sound(str(path))
                    except Exception:
                        pass
        b = FX_DIR / "blood_red.png"
        if b.exists() and self.blood_sprite is None:
            try:
                self.blood_sprite = pygame.image.load(str(b)).convert_alpha()
            except Exception:
                pass

    def _base_play_event(self, ev):
        if not self.audio_enabled:
            return
        typ = ev.get("type")
        names = []
        vol = 0.45
        if typ == "shot":
            w = ev.get("weapon", "")
            if w in ("Scoped Rifle", "Marksman Rifle", "Heavy Machine Gun"):
                names = ["rifle_762.mp3"]
            elif w in ("SMG",):
                names = ["smg_9mm.mp3"]
            else:
                names = ["rifle_556.mp3"]
            vol = 0.3 if w not in ("Heavy Machine Gun",) else 0.38
        elif typ == "explosion":
            names = ["explosion1.ogg", "explosion2.ogg"]
            vol = 0.6
        elif typ == "hurt":
            if ev.get("damage", 0) < 20:
                return
            names = ["hurt_01.mp3", "hurt_03.mp3"]
            vol = 0.24
        elif typ == "death":
            names = ["scream_horror1.mp3", "hurt_03.mp3"]
            vol = 0.22
        avail = [n for n in names if n in self.audio]
        if avail:
            snd = self.audio[random.choice(avail)]
            snd.set_volume(vol)
            snd.play()

    def _kz_play_event(self, ev):
        now = time.perf_counter()
        if now - self._audio_window_start > 0.05:
            self._audio_window_start = now
            self._audio_count = 0
        typ = ev.get("type", "")
        minimum = 0.025 if typ == "shot" else 0.05
        if now - self._audio_last.get(typ, -99) < minimum:
            return
        if self._audio_count >= 5:
            return
        self._audio_last[typ] = now
        self._audio_count += 1
        if typ == "explosion":
            pos = ev.get("pos")
            if pos:
                sx, sy = self.world_to_screen(*pos)
                near = self.map_view_rect().inflate(180, 180).collidepoint((sx, sy))
            else:
                near = True
            if near:
                self.shake_until = time.time() + 0.22
                self.shake_strength = max(self.shake_strength, 4.0)
        self._base_play_event(ev)

    def _vs_make_pcm_sound(self, kind, duration=0.14):
        try:
            init = pygame.mixer.get_init()
            if not init:
                return None
            rate, bits, channels = init
            rate = int(rate)
            channels = int(channels)
            samples = max(1, int(rate * duration))
            buf = bytearray()
            rr = random.Random(hash(kind) & 4294967295)
            lp = 0.0
            import struct

            for i in range(samples):
                t = i / max(1, samples - 1)
                env = (1 - t) ** 2
                if kind == "snap":
                    v = (
                        (rr.random() * 2 - 1)
                        * env
                        * (0.9 if i < samples * 0.3 else 0.35)
                    )
                elif kind == "impact":
                    lp = lp * 0.82 + (rr.random() * 2 - 1) * 0.18
                    v = lp * env * 0.75
                elif kind == "thump":
                    v = (
                        math.sin(2 * math.pi * (58 + 24 * t) * (i / rate)) * env * 0.75
                        + (rr.random() * 2 - 1) * env * 0.08
                    )
                else:
                    lp = lp * 0.97 + (rr.random() * 2 - 1) * 0.03
                    v = lp * 0.38 * (0.5 + 0.5 * math.sin(t * math.pi))
                n = int(clamp(v, -1, 1) * 22000)
                if abs(bits) == 16:
                    packed = struct.pack("<h", n)
                else:
                    packed = bytes([int(clamp(128 + n / 256, 0, 255))])
                buf.extend(packed * channels)
            return pygame.mixer.Sound(buffer=bytes(buf))
        except Exception:
            return None

    def _vs_init_procedural_audio(self):
        if not self.audio_enabled:
            return
        try:
            pygame.mixer.set_num_channels(max(12, pygame.mixer.get_num_channels()))
            for kind, dur in [
                ("snap", 0.07),
                ("impact", 0.12),
                ("thump", 0.28),
                ("wind", 1.8),
            ]:
                snd = self._vs_make_pcm_sound(kind, dur)
                if snd:
                    self._procedural_audio[kind] = snd
        except Exception:
            pass

    def _vs_play_event2(self, ev):
        if not self.audio_enabled:
            return
        typ = ev.get("type")
        pos = ev.get("pos")
        listener = self._vs_listener()
        d = dist(listener, pos) if pos else 0
        attenuation = clamp(1 - d / 32, 0.08, 1)
        now = time.perf_counter()
        minimum = {"shot": 0.025, "explosion": 0.05, "hurt": 0.08, "death": 0.15}.get(
            typ, 0.03
        )
        if now - self._audio_last.get(typ, -99) < minimum:
            return
        if now - self._audio_window_start > 0.05:
            self._audio_window_start = now
            self._audio_count = 0
        if self._audio_count >= 6:
            return
        self._audio_last[typ] = now
        self._audio_count += 1
        if typ == "shot":
            w = ev.get("weapon", "")
            name = (
                "rifle_762.mp3"
                if w in ("Scoped Rifle", "Marksman Rifle", "Heavy Machine Gun")
                else "smg_9mm.mp3"
                if w == "SMG"
                else "rifle_556.mp3"
            )
            self._vs_play_channel(
                self.audio.get(name),
                (0.32 if d < 9 else 0.2 if d < 18 else 0.1) * attenuation,
            )
            if 3 < d < 15:
                self._vs_play_channel(
                    self._procedural_audio.get("snap"), 0.1 * attenuation
                )
        elif typ == "explosion":
            names = [n for n in ("explosion1.ogg", "explosion2.ogg") if n in self.audio]
            if names:
                self._vs_play_channel(
                    self.audio[random.choice(names)], 0.58 * attenuation
                )
            self._vs_play_channel(
                self._procedural_audio.get("thump"), 0.25 * attenuation
            )
            self._vs_play_channel(
                self._procedural_audio.get("impact"), 0.12 * attenuation
            )
            if d < 17:
                self.shake_until = time.time() + 0.22
                self.shake_strength = max(self.shake_strength, 4.0 * attenuation)
        elif typ == "hurt" and ev.get("damage", 0) >= 20 and (d < 16):
            names = [n for n in ("hurt_01.mp3", "hurt_03.mp3") if n in self.audio]
            if names:
                self._vs_play_channel(
                    self.audio[random.choice(names)], 0.16 * attenuation
                )
        elif typ == "death" and d < 18:
            names = [
                n for n in ("scream_horror1.mp3", "hurt_03.mp3") if n in self.audio
            ]
            if names:
                self._vs_play_channel(
                    self.audio[random.choice(names)], 0.14 * attenuation
                )

    def _vs_update_ambience(self):
        if not self.audio_enabled or self.state != "game":
            return
        now = time.perf_counter()
        if now >= self._ambience_next:
            intensity = getattr(self.game, "combat_intensity", 0)
            stage = getattr(self.game, "battle_stage", "APPROACH")
            gap = (
                random.uniform(2.2, 4.8) if intensity < 8 else random.uniform(1.0, 2.4)
            )
            self._ambience_next = now + gap
            self._vs_play_channel(
                self._procedural_audio.get("wind"),
                0.025 if self.game.weather == "clear" else 0.045,
            )
            if random.random() < (
                0.22 if stage == "APPROACH" else 0.45 if stage == "CONTACT" else 0.62
            ):
                if random.random() < 0.72:
                    n = random.choice(
                        [
                            n
                            for n in ("rifle_556.mp3", "rifle_762.mp3")
                            if n in self.audio
                        ]
                        or [""]
                    )
                    self._vs_play_channel(self.audio.get(n), 0.035)
                else:
                    n = random.choice(
                        [
                            n
                            for n in ("explosion1.ogg", "explosion2.ogg")
                            if n in self.audio
                        ]
                        or [""]
                    )
                    self._vs_play_channel(self.audio.get(n), 0.045)

    def make_tactical_pcm_sound(self, kind):
        """Build short non-verbal tactical cues without requiring new assets."""
        try:
            mixer_init = pygame.mixer.get_init()
            if not mixer_init:
                return None
            import struct

            rate, bits, channels = mixer_init
            durations = {
                "select": 0.045,
                "command": 0.13,
                "deny": 0.18,
                "contact": 0.24,
                "warning": 0.38,
                "casualty": 0.34,
                "objective": 0.52,
            }
            duration = durations[kind]
            sample_count = max(1, int(rate * duration))
            randomizer = random.Random(
                8100 + sum((ord(character) for character in kind))
            )
            buffer = bytearray()
            filtered_noise = 0.0
            for index in range(sample_count):
                seconds = index / rate
                progress = index / max(1, sample_count - 1)
                envelope = (1.0 - progress) ** 1.6
                if kind == "select":
                    value = math.sin(math.tau * 920 * seconds) * envelope
                elif kind == "command":
                    frequency = 610 if progress < 0.42 else 880
                    gate = 1.0 if progress < 0.34 or progress > 0.5 else 0.0
                    value = math.sin(math.tau * frequency * seconds) * envelope * gate
                elif kind == "deny":
                    frequency = 280 - 105 * progress
                    value = math.sin(math.tau * frequency * seconds) * envelope
                elif kind == "contact":
                    filtered_noise = (
                        filtered_noise * 0.72 + (randomizer.random() * 2 - 1) * 0.28
                    )
                    tone = math.sin(math.tau * 430 * seconds) * (
                        1.0 if 0.18 < progress < 0.72 else 0.0
                    )
                    value = (filtered_noise * 0.52 + tone * 0.28) * envelope
                elif kind == "warning":
                    gate = 1.0 if int(progress * 5) % 2 == 0 else 0.22
                    value = math.sin(math.tau * 235 * seconds) * envelope * gate
                elif kind == "casualty":
                    frequency = 330 if progress < 0.45 else 205
                    gate = 1.0 if progress < 0.34 or progress > 0.52 else 0.12
                    value = math.sin(math.tau * frequency * seconds) * envelope * gate
                else:
                    frequency = 420 + 430 * progress
                    harmonic = math.sin(math.tau * frequency * seconds)
                    value = (
                        harmonic + 0.35 * math.sin(math.tau * frequency * 1.5 * seconds)
                    ) * envelope
                sample = int(clamp(value, -1, 1) * 20000)
                if abs(bits) == 16:
                    packed = struct.pack("<h", sample)
                else:
                    packed = bytes([int(clamp(128 + sample / 256, 0, 255))])
                buffer.extend(packed * channels)
            return pygame.mixer.Sound(buffer=bytes(buffer))
        except Exception:
            return None

    def ensure_tactical_audio(self):
        if not getattr(self, "audio_enabled", False):
            return
        if not hasattr(self, "_tactical_audio"):
            self._tactical_audio = {}
        for kind in TACTICAL_AUDIO_VOLUMES:
            if kind not in self._tactical_audio:
                sound = self.make_tactical_pcm_sound(kind)
                if sound is not None:
                    self._tactical_audio[kind] = sound

    def play_tactical_sound(self, kind):
        if not getattr(self, "audio_enabled", False):
            return False
        self.ensure_tactical_audio()
        sound = getattr(self, "_tactical_audio", {}).get(kind)
        if sound is None:
            return False
        now = time.perf_counter()
        cooldown = 0.7 if kind in ("warning", "casualty", "objective") else 0.09
        last_played = getattr(self, "_tactical_audio_last", {}).get(kind, -99.0)
        if now - last_played < cooldown:
            return False
        self._tactical_audio_last[kind] = now
        try:
            channel = sound.play()
            if channel:
                channel.set_volume(TACTICAL_AUDIO_VOLUMES[kind])
            return channel is not None
        except pygame.error:
            return False

    def poll_tactical_audio(self):
        game_identity = id(self.game)
        events = getattr(self.game, "battle_events", [])
        if game_identity != getattr(self, "_tactical_audio_game", None):
            self._tactical_audio_game = game_identity
            self._tactical_audio_last_event = None
            self._tactical_audio_last_event_time = -99.0
            self._tactical_audio_stage = getattr(self.game, "battle_stage", "APPROACH")
        last_event = getattr(self, "_tactical_audio_last_event", None)
        start = 0
        found_last_event = last_event is None
        if last_event is not None:
            for index, event in enumerate(events):
                if event is last_event:
                    start = index + 1
                    found_last_event = True
                    break
        if not found_last_event:
            last_event_time = getattr(self, "_tactical_audio_last_event_time", -99.0)
            start = next(
                (
                    index
                    for index, event in enumerate(events)
                    if event.get("time", -99.0) > last_event_time
                ),
                len(events),
            )
        for event in events[start:]:
            cue = battle_audio_cue_for_event(event)
            if cue:
                self.play_tactical_sound(cue)
        if events:
            self._tactical_audio_last_event = events[-1]
            self._tactical_audio_last_event_time = events[-1].get("time", -99.0)
        stage = getattr(self.game, "battle_stage", "APPROACH")
        previous_stage = getattr(self, "_tactical_audio_stage", stage)
        if stage != previous_stage:
            cue = {
                "CONTACT": "contact",
                "ASSAULT": "command",
                "COLLAPSE": "objective",
            }.get(stage)
            if cue:
                self.play_tactical_sound(cue)
            self._tactical_audio_stage = stage

    def _feedback_update_ambience(self):
        result = self._vs_update_ambience()
        if self.state in ("deployment", "game"):
            self.poll_tactical_audio()
        return result

    def make_presentation_pcm_sound(self, kind):
        try:
            mixer_init = pygame.mixer.get_init()
            if not mixer_init:
                return None
            import struct

            rate, bits, channels = mixer_init
            rate = int(rate)
            channels = int(channels)
            duration = PRESENTATION_AUDIO_DURATIONS[kind]
            samples = max(1, int(rate * duration))
            rng = random.Random(51700 + sum((ord(character) for character in kind)))
            buffer = bytearray()
            low_pass = 0.0
            high_pass_previous = 0.0
            for index in range(samples):
                seconds = index / rate
                progress = index / max(1, samples - 1)
                attack = clamp(progress / 0.025, 0.0, 1.0)
                release = (1.0 - progress) ** 1.8
                noise = rng.random() * 2.0 - 1.0
                low_pass = low_pass * 0.92 + noise * 0.08
                high_pass = noise - high_pass_previous * 0.72
                high_pass_previous = noise
                if kind == "rifle":
                    transient = high_pass * math.exp(-progress * 38.0)
                    body = (
                        math.sin(math.tau * (118 - 48 * progress) * seconds) * release
                    )
                    value = transient * 0.78 + body * 0.52
                elif kind == "heavy":
                    transient = high_pass * math.exp(-progress * 24.0)
                    body = math.sin(math.tau * (82 - 28 * progress) * seconds) * release
                    value = transient * 0.62 + body * 0.76
                elif kind == "smg":
                    transient = high_pass * math.exp(-progress * 48.0)
                    body = (
                        math.sin(math.tau * (155 - 60 * progress) * seconds) * release
                    )
                    value = transient * 0.72 + body * 0.36
                elif kind == "distant":
                    value = (
                        low_pass * 0.55 + math.sin(math.tau * 72 * seconds) * 0.25
                    ) * release
                elif kind == "crack":
                    value = high_pass * math.exp(-progress * 55.0) * 0.86
                elif kind == "mechanical":
                    frequency = 1180 - 620 * progress
                    gate = 1.0 if int(progress * 7) in (0, 2, 4) else 0.15
                    value = (
                        math.sin(math.tau * frequency * seconds) * release * gate * 0.43
                    )
                elif kind == "blast":
                    transient = high_pass * math.exp(-progress * 19.0)
                    body = math.sin(math.tau * (64 - 28 * progress) * seconds) * release
                    value = transient * 0.68 + body * 0.82
                elif kind == "rumble":
                    swell = math.sin(math.pi * clamp(progress * 2.4, 0.0, 1.0))
                    value = (
                        (math.sin(math.tau * 41 * seconds) * 0.68 + low_pass * 0.28)
                        * swell
                        * release
                    )
                elif kind == "debris":
                    click = (
                        1.0 if rng.random() < 0.035 + (1.0 - progress) * 0.05 else 0.0
                    )
                    value = (high_pass * click * 0.8 + low_pass * 0.28) * release
                elif kind == "rain":
                    drop = high_pass * (0.55 if rng.random() < 0.08 else 0.12)
                    value = (drop + low_pass * 0.16) * (
                        0.72 + math.sin(math.tau * 0.7 * seconds) * 0.12
                    )
                elif kind == "fire":
                    crack = high_pass * (0.65 if rng.random() < 0.025 else 0.05)
                    value = crack + low_pass * 0.13
                elif kind == "heartbeat":
                    beat_phase = progress * 2.0
                    pulse = math.exp(-(beat_phase % 1.0 * 15.0))
                    value = (
                        math.sin(math.tau * 54 * seconds)
                        * pulse
                        * (0.52 if beat_phase < 1 else 0.36)
                    )
                else:
                    swell = 0.42 + 0.3 * math.sin(math.tau * 0.35 * seconds)
                    value = low_pass * swell * 0.72
                value *= attack if kind not in ("wind", "rain", "fire") else 0.72
                sample = int(clamp(value, -1.0, 1.0) * 22500)
                packed = (
                    struct.pack("<h", sample)
                    if abs(bits) == 16
                    else bytes([int(clamp(128 + sample / 256, 0, 255))])
                )
                buffer.extend(packed * channels)
            return pygame.mixer.Sound(buffer=bytes(buffer))
        except Exception:
            return None

    def ensure_presentation_audio(self):
        if not getattr(self, "audio_enabled", False) or not pygame.mixer.get_init():
            return
        if not hasattr(self, "_presentation_audio"):
            self._presentation_audio = {}
        try:
            pygame.mixer.set_num_channels(max(24, pygame.mixer.get_num_channels()))
        except pygame.error:
            return
        for kind in PRESENTATION_AUDIO_DURATIONS:
            if kind not in self._presentation_audio:
                sound = self.make_presentation_pcm_sound(kind)
                if sound is not None:
                    self._presentation_audio[kind] = sound

    def _presentation_play_event(self, event):
        now = time.perf_counter()
        if not event.get("audible_only"):
            event_copy = dict(event)
            event_copy["presented_at"] = now
            self._presentation_events.append(event_copy)
            self._presentation_events = self._presentation_events[-72:]
        if not getattr(self, "audio_enabled", False):
            return
        self.ensure_presentation_audio()
        kind = str(event.get("type", ""))
        minimum = {"shot": 0.018, "explosion": 0.045, "hurt": 0.08, "death": 0.14}.get(
            kind, 0.04
        )
        if now - self._presentation_audio_last.get(kind, -99.0) < minimum:
            return
        if now - self._presentation_audio_window > 0.055:
            self._presentation_audio_window = now
            self._presentation_audio_count = 0
        if self._presentation_audio_count >= 8:
            return
        self._presentation_audio_last[kind] = now
        self._presentation_audio_count += 1
        position = event.get("pos")
        listener = self.presentation_listener()
        distance = dist(listener, position) if position else 0.0
        pan = (
            clamp((float(position[0]) - listener[0]) / 20.0, -0.78, 0.78)
            if position
            else 0.0
        )
        intensity = getattr(self.game, "combat_intensity", 0.0)
        layers = presentation_audio_mix(event, distance, intensity)
        procedural = getattr(self, "_presentation_audio", {})
        sample = None
        sample_volume = 0.0
        if kind == "shot":
            weapon = str(event.get("weapon", ""))
            filename = (
                "rifle_762.mp3"
                if weapon in ("Heavy Machine Gun", "Scoped Rifle", "Marksman Rifle")
                else "smg_9mm.mp3"
                if weapon == "SMG"
                else "rifle_556.mp3"
            )
            sample = self.audio.get(filename)
            sample_volume = 0.15 * clamp(1.0 - distance / 38.0, 0.06, 1.0)
        elif kind == "explosion":
            available = [
                self.audio[name]
                for name in ("explosion1.ogg", "explosion2.ogg")
                if name in self.audio
            ]
            sample = random.choice(available) if available else None
            sample_volume = 0.24 * clamp(1.0 - distance / 48.0, 0.08, 1.0)
            self._presentation_duck_until = now + 0.55
            if distance < 19:
                attenuation = clamp(1.0 - distance / 23.0, 0.15, 1.0)
                self.shake_until = time.time() + 0.26
                self.shake_strength = max(self.shake_strength, 5.5 * attenuation)
        elif kind in ("hurt", "death") and distance < 17:
            names = (
                ("hurt_01.mp3", "hurt_03.mp3")
                if kind == "hurt"
                else ("scream_horror1.mp3", "hurt_03.mp3")
            )
            available = [self.audio[name] for name in names if name in self.audio]
            sample = random.choice(available) if available else None
            sample_volume = 0.11 if kind == "hurt" else 0.13
        if sample is not None:
            self.play_presentation_layer(sample, sample_volume, pan)
        for layer, volume in layers:
            self.play_presentation_layer(procedural.get(layer), volume, pan)

    def update_ambience(self):
        if self.state in ("deployment", "game") and hasattr(
            self, "poll_tactical_audio"
        ):
            self.poll_tactical_audio()
        if not getattr(self, "audio_enabled", False) or self.state != "game":
            return
        self.ensure_presentation_audio()
        now = time.perf_counter()
        intensity = clamp(getattr(self.game, "combat_intensity", 0.0), 0.0, 100.0)
        duck = 0.42 if now < self._presentation_duck_until else 1.0
        procedural = getattr(self, "_presentation_audio", {})
        if now >= self._presentation_ambience_next:
            weather = getattr(self.game, "weather", "clear")
            layer = "rain" if weather == "rain" else "wind"
            volume = (
                0.038 if weather == "rain" else 0.024 if weather == "clear" else 0.034
            ) * duck
            self.play_presentation_layer(
                procedural.get(layer), volume, random.uniform(-0.2, 0.2)
            )
            if any(
                (
                    fire > 0
                    for _x, _y, _supp, _smoke, fire in getattr(
                        self, "_dynamic_tiles", []
                    )
                )
            ):
                self.play_presentation_layer(
                    procedural.get("fire"), 0.022 * duck, random.uniform(-0.5, 0.5)
                )
            self._presentation_ambience_next = now + random.uniform(1.25, 2.4)
        if now >= self._presentation_action_next:
            stage = getattr(self.game, "battle_stage", "APPROACH")
            chance = (
                0.12 if stage == "APPROACH" else 0.3 if stage == "CONTACT" else 0.48
            )
            if random.random() < chance + intensity / 320.0:
                layer = "distant" if random.random() < 0.72 else "rumble"
                volume = (0.022 + intensity * 0.00018) * duck
                self.play_presentation_layer(
                    procedural.get(layer), volume, random.uniform(-0.72, 0.72)
                )
            self._presentation_action_next = now + random.uniform(0.85, 2.2)
        selected = self.selected_units()
        stress = max((unit.suppression for unit in selected), default=0.0)
        if stress >= 72 and now >= self._presentation_heartbeat_next:
            self.play_presentation_layer(
                procedural.get("heartbeat"), 0.035 * clamp(stress / 100.0, 0.0, 1.0)
            )
            self._presentation_heartbeat_next = now + 0.68

    def play_event(self, event):
        previous_shake = (self.shake_until, self.shake_strength)
        result = self._presentation_play_event(event)
        if not self.camera_shake_enabled:
            self.shake_until, self.shake_strength = previous_shake
        now = time.perf_counter()
        if event.get("type") == "shot":
            self._polish_shot_window.append(now)
            self._polish_shot_window = [
                stamp for stamp in self._polish_shot_window if now - stamp <= 0.8
            ]
            if len(self._polish_shot_window) >= 11:
                self._presentation_duck_until = max(
                    self._presentation_duck_until, now + 0.16
                )
        return result
