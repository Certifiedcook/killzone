# =============================================================================
# AUDIO + VISUAL PRESENTATION OVERHAUL
# =============================================================================

PRESENTATION_AUDIO_DURATIONS = {
    "rifle": 0.16,
    "heavy": 0.22,
    "smg": 0.11,
    "distant": 0.30,
    "crack": 0.075,
    "mechanical": 0.09,
    "blast": 0.42,
    "rumble": 0.82,
    "debris": 0.32,
    "wind": 2.3,
    "rain": 1.8,
    "fire": 1.25,
    "heartbeat": 0.72,
}


def presentation_audio_mix(event, distance, intensity=0.0):
    """Return deterministic procedural mix layers for a simulation event."""
    kind = str(event.get("type", ""))
    distance = max(0.0, float(distance))
    intensity = clamp(float(intensity), 0.0, 100.0)
    near = clamp(1.0 - (distance / 38.0) ** 1.25, 0.0, 1.0)
    far = clamp(1.0 - distance / 58.0, 0.04, 1.0)
    layers = []
    if kind == "shot":
        weapon = str(event.get("weapon", ""))
        if weapon == "artillery":
            layers.extend((("blast", 0.42 * far), ("rumble", 0.28 * far)))
        else:
            voice = (
                "heavy"
                if weapon in ("Heavy Machine Gun", "Scoped Rifle", "Marksman Rifle")
                else "smg"
                if weapon == "SMG"
                else "rifle"
            )
            layers.append((voice, (0.16 + 0.24 * near) * far))
            layers.append(("mechanical", 0.075 * near))
            if distance > 9:
                layers.append(("distant", 0.10 * far))
            elif distance > 2.5:
                layers.append(("crack", 0.09 * near))
    elif kind == "explosion":
        radius = clamp(float(event.get("radius", 2.0)), 0.5, 6.0)
        scale = 0.75 + radius * 0.10
        layers.extend(
            (
                ("blast", 0.46 * far * scale),
                ("rumble", 0.34 * far * scale),
                ("debris", 0.16 * near),
            )
        )
    elif kind in ("hurt", "death"):
        layers.append(("debris", (0.07 if kind == "hurt" else 0.11) * near))
    if intensity > 65 and kind in ("shot", "explosion"):
        layers = [(name, volume * 0.92) for name, volume in layers]
    return [(name, clamp(volume, 0.0, 0.75)) for name, volume in layers if volume > 0.005]


def presentation_weather_particles(weather, seed, clock, width, height, count=32):
    """Produce a deterministic frame of map-space atmospheric particles."""
    weather = str(weather)
    width = max(1, int(width))
    height = max(1, int(height))
    count = max(0, int(count))
    cadence = 11 if weather == "rain" else 3 if weather == "fog" else 2
    frame = int(max(0.0, float(clock)) * cadence)
    rng = random.Random((int(seed) * 1_000_003) ^ (frame * 97_409) ^ sum(map(ord, weather)))
    output = []
    for _ in range(count):
        x = rng.randrange(width)
        y = rng.randrange(height)
        if weather == "rain":
            length = rng.randint(7, 16)
            alpha = rng.randint(36, 94)
        elif weather == "fog":
            length = rng.randint(30, 92)
            alpha = rng.randint(9, 26)
        else:
            length = rng.randint(1, 3)
            alpha = rng.randint(14, 34)
        output.append((x, y, length, alpha))
    return output


def presentation_terrain_marks(terrain, x, y, seed, count=4):
    """Return stable normalized detail marks used by the terrain cache."""
    rng = random.Random(
        int(seed) * 83_492_791 ^ int(x) * 73_856_093 ^ int(y) * 19_349_663 ^ sum(map(ord, str(terrain)))
    )
    return [(rng.random(), rng.random(), rng.random()) for _ in range(max(0, int(count)))]


def _presentation_pcm_sound(self, kind):
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
        rng = random.Random(51_700 + sum(ord(character) for character in kind))
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
                body = math.sin(math.tau * (118 - 48 * progress) * seconds) * release
                value = transient * 0.78 + body * 0.52
            elif kind == "heavy":
                transient = high_pass * math.exp(-progress * 24.0)
                body = math.sin(math.tau * (82 - 28 * progress) * seconds) * release
                value = transient * 0.62 + body * 0.76
            elif kind == "smg":
                transient = high_pass * math.exp(-progress * 48.0)
                body = math.sin(math.tau * (155 - 60 * progress) * seconds) * release
                value = transient * 0.72 + body * 0.36
            elif kind == "distant":
                value = (low_pass * 0.55 + math.sin(math.tau * 72 * seconds) * 0.25) * release
            elif kind == "crack":
                value = high_pass * math.exp(-progress * 55.0) * 0.86
            elif kind == "mechanical":
                frequency = 1180 - 620 * progress
                gate = 1.0 if int(progress * 7) in (0, 2, 4) else 0.15
                value = math.sin(math.tau * frequency * seconds) * release * gate * 0.43
            elif kind == "blast":
                transient = high_pass * math.exp(-progress * 19.0)
                body = math.sin(math.tau * (64 - 28 * progress) * seconds) * release
                value = transient * 0.68 + body * 0.82
            elif kind == "rumble":
                swell = math.sin(math.pi * clamp(progress * 2.4, 0.0, 1.0))
                value = (math.sin(math.tau * 41 * seconds) * 0.68 + low_pass * 0.28) * swell * release
            elif kind == "debris":
                click = 1.0 if rng.random() < 0.035 + (1.0 - progress) * 0.05 else 0.0
                value = (high_pass * click * 0.8 + low_pass * 0.28) * release
            elif kind == "rain":
                drop = high_pass * (0.55 if rng.random() < 0.08 else 0.12)
                value = (drop + low_pass * 0.16) * (0.72 + math.sin(math.tau * 0.7 * seconds) * 0.12)
            elif kind == "fire":
                crack = high_pass * (0.65 if rng.random() < 0.025 else 0.05)
                value = crack + low_pass * 0.13
            elif kind == "heartbeat":
                beat_phase = progress * 2.0
                pulse = math.exp(-((beat_phase % 1.0) * 15.0))
                value = math.sin(math.tau * 54 * seconds) * pulse * (0.52 if beat_phase < 1 else 0.36)
            else:  # wind
                swell = 0.42 + 0.30 * math.sin(math.tau * 0.35 * seconds)
                value = low_pass * swell * 0.72

            value *= attack if kind not in ("wind", "rain", "fire") else 0.72
            sample = int(clamp(value, -1.0, 1.0) * 22_500)
            packed = struct.pack("<h", sample) if abs(bits) == 16 else bytes([int(clamp(128 + sample / 256, 0, 255))])
            buffer.extend(packed * channels)
        return pygame.mixer.Sound(buffer=bytes(buffer))
    except Exception:
        return None


KillZoneApp.make_presentation_pcm_sound = _presentation_pcm_sound


def _presentation_ensure_audio(self):
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


KillZoneApp.ensure_presentation_audio = _presentation_ensure_audio


def _presentation_play_layer(self, sound, volume, pan=0.0):
    if sound is None or volume <= 0.005 or not pygame.mixer.get_init():
        return False
    try:
        channel = pygame.mixer.find_channel(True)
        if channel is None:
            return False
        channel.play(sound)
        pan = clamp(float(pan), -0.82, 0.82)
        if int(pygame.mixer.get_init()[2]) >= 2:
            channel.set_volume(volume * (1.0 - max(0.0, pan)), volume * (1.0 + min(0.0, pan)))
        else:
            channel.set_volume(volume)
        return True
    except pygame.error:
        return False


KillZoneApp.play_presentation_layer = _presentation_play_layer


_presentation_previous_app_init = KillZoneApp.__init__


def _presentation_app_init(self):
    _presentation_previous_app_init(self)
    self._presentation_audio = {}
    self._presentation_audio_last = {}
    self._presentation_audio_window = 0.0
    self._presentation_audio_count = 0
    self._presentation_ambience_next = 0.0
    self._presentation_action_next = 0.0
    self._presentation_heartbeat_next = 0.0
    self._presentation_duck_until = 0.0
    self._presentation_events = []
    self._presentation_menu_overlay = None
    self._presentation_vignette = None
    self.ensure_presentation_audio()


KillZoneApp.__init__ = _presentation_app_init


def _presentation_listener(self):
    selected = self.selected_units()
    if selected:
        return (
            sum(unit.x for unit in selected) / len(selected),
            sum(unit.y for unit in selected) / len(selected),
        )
    return (
        self.camera_x + MAP_VIEW_W_PX / self.tile_px / 2,
        self.camera_y + MAP_VIEW_H_PX / self.tile_px / 2,
    )


KillZoneApp.presentation_listener = _presentation_listener


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
    minimum = {"shot": 0.018, "explosion": 0.045, "hurt": 0.08, "death": 0.14}.get(kind, 0.04)
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
    pan = clamp((float(position[0]) - listener[0]) / 20.0, -0.78, 0.78) if position else 0.0
    intensity = getattr(self.game, "combat_intensity", 0.0)
    layers = presentation_audio_mix(event, distance, intensity)
    procedural = getattr(self, "_presentation_audio", {})

    # Retain optional external recordings as a restrained foreground layer;
    # the procedural body/tail keeps the mix complete when assets are absent.
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
        available = [self.audio[name] for name in ("explosion1.ogg", "explosion2.ogg") if name in self.audio]
        sample = random.choice(available) if available else None
        sample_volume = 0.24 * clamp(1.0 - distance / 48.0, 0.08, 1.0)
        self._presentation_duck_until = now + 0.55
        if distance < 19:
            attenuation = clamp(1.0 - distance / 23.0, 0.15, 1.0)
            self.shake_until = time.time() + 0.26
            self.shake_strength = max(self.shake_strength, 5.5 * attenuation)
    elif kind in ("hurt", "death") and distance < 17:
        names = ("hurt_01.mp3", "hurt_03.mp3") if kind == "hurt" else ("scream_horror1.mp3", "hurt_03.mp3")
        available = [self.audio[name] for name in names if name in self.audio]
        sample = random.choice(available) if available else None
        sample_volume = 0.11 if kind == "hurt" else 0.13

    if sample is not None:
        self.play_presentation_layer(sample, sample_volume, pan)
    for layer, volume in layers:
        self.play_presentation_layer(procedural.get(layer), volume, pan)


KillZoneApp.play_event = _presentation_play_event


def _presentation_update_ambience(self):
    if self.state in ("deployment", "game") and hasattr(self, "poll_tactical_audio"):
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
        volume = (0.038 if weather == "rain" else 0.024 if weather == "clear" else 0.034) * duck
        self.play_presentation_layer(procedural.get(layer), volume, random.uniform(-0.2, 0.2))
        if any(fire > 0 for _x, _y, _supp, _smoke, fire in getattr(self, "_dynamic_tiles", [])):
            self.play_presentation_layer(procedural.get("fire"), 0.022 * duck, random.uniform(-0.5, 0.5))
        self._presentation_ambience_next = now + random.uniform(1.25, 2.4)

    if now >= self._presentation_action_next:
        stage = getattr(self.game, "battle_stage", "APPROACH")
        chance = 0.12 if stage == "APPROACH" else 0.30 if stage == "CONTACT" else 0.48
        if random.random() < chance + intensity / 320.0:
            layer = "distant" if random.random() < 0.72 else "rumble"
            volume = (0.022 + intensity * 0.00018) * duck
            self.play_presentation_layer(procedural.get(layer), volume, random.uniform(-0.72, 0.72))
        self._presentation_action_next = now + random.uniform(0.85, 2.2)

    selected = self.selected_units()
    stress = max((unit.suppression for unit in selected), default=0.0)
    if stress >= 72 and now >= self._presentation_heartbeat_next:
        self.play_presentation_layer(procedural.get("heartbeat"), 0.035 * clamp(stress / 100.0, 0.0, 1.0))
        self._presentation_heartbeat_next = now + 0.68


KillZoneApp.update_ambience = _presentation_update_ambience


_presentation_previous_draw_terrain = KillZoneApp.draw_terrain


def _presentation_draw_terrain(self, cell, rect, x, y):
    _presentation_previous_draw_terrain(self, cell, rect, x, y)
    marks = presentation_terrain_marks(cell.terrain, x, y, self.game.seed, 5)
    width = max(1, rect.w)
    height = max(1, rect.h)

    def pixel(mark):
        return (
            rect.left + 2 + int(mark[0] * max(1, width - 5)),
            rect.top + 2 + int(mark[1] * max(1, height - 5)),
        )

    if cell.terrain in ("open", "hill"):
        color = (83, 91, 64) if cell.terrain == "open" else (97, 91, 63)
        for mark in marks[:3]:
            px, py = pixel(mark)
            pygame.draw.line(self.screen, color, (px, py + 2), (px + (1 if mark[2] > 0.5 else -1), py - 1), 1)
        if cell.terrain == "hill":
            pygame.draw.line(
                self.screen,
                (104, 96, 68),
                (rect.left + 4, rect.centery + 2),
                (rect.centerx, rect.centery - 2),
                1,
            )
            pygame.draw.line(
                self.screen,
                (104, 96, 68),
                (rect.centerx, rect.centery - 2),
                (rect.right - 4, rect.centery + 2),
                1,
            )
    elif cell.terrain == "mud":
        for mark in marks[:2]:
            px, py = pixel(mark)
            pygame.draw.ellipse(self.screen, (78, 70, 56), (px - 3, py - 1, 7, 3), 1)
            pygame.draw.line(self.screen, (111, 102, 83), (px - 1, py), (px + 2, py), 1)
    elif cell.terrain == "road":
        for mark in marks[:2]:
            _px, py = pixel(mark)
            pygame.draw.line(self.screen, (103, 96, 78), (rect.left + 3, py), (rect.right - 4, py), 1)
    elif cell.terrain == "rubble":
        for mark in marks[:4]:
            px, py = pixel(mark)
            pygame.draw.polygon(self.screen, (91, 88, 78), ((px, py - 2), (px + 3, py + 2), (px - 2, py + 2)))
            pygame.draw.polygon(self.screen, (48, 49, 45), ((px, py - 2), (px + 3, py + 2), (px - 2, py + 2)), 1)
    elif cell.terrain == "water":
        for mark in marks[:2]:
            _px, py = pixel(mark)
            inset = 4 + int(mark[2] * 5)
            pygame.draw.line(self.screen, (85, 111, 112), (rect.left + inset, py), (rect.right - inset, py), 1)
    elif cell.terrain in ("building", "wall", "woodwall"):
        for mark in marks[:2]:
            px, py = pixel(mark)
            pygame.draw.line(self.screen, (43, 44, 41), (px - 2, py - 1), (px + 3, py + 2), 1)


KillZoneApp.draw_terrain = _presentation_draw_terrain


_presentation_previous_draw_unit = KillZoneApp.draw_unit


def _presentation_draw_unit(self, unit):
    _presentation_previous_draw_unit(self, unit)
    if not unit.alive or unit.casualty in ("dead", "surrendered"):
        return
    center = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(40, 40).collidepoint(center):
        return
    cx, cy = center
    scale = max(0.8, self.tile_px / 26.0)
    if unit.faction == "player":
        squad_color = squad_visual_color(getattr(unit, "squad_id", 1))
        pip = pygame.Rect(cx - 11, cy - max(13, int(14 * scale)), 22, 3)
        pygame.draw.rect(self.screen, COLORS["black"], pip.inflate(2, 2))
        pygame.draw.rect(self.screen, squad_color, pip)

    if unit.uid in self.selected:
        radius = max(17, int(self.tile_px * 0.68))
        pulse = 2 + int((math.sin(time.perf_counter() * 5.5) + 1.0) * 1.5)
        color = COLORS["select"]
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corner = (cx + sx * radius, cy + sy * radius)
            pygame.draw.line(self.screen, color, corner, (corner[0] - sx * (5 + pulse), corner[1]), 2)
            pygame.draw.line(self.screen, color, corner, (corner[0], corner[1] - sy * (5 + pulse)), 2)

    stance = getattr(unit, "stance", "stand")
    stance_color = COLORS["good"] if stance == "prone" else COLORS["contact"] if stance == "crouch" else COLORS["muted"]
    pygame.draw.circle(self.screen, stance_color, (cx - max(12, int(14 * scale)), cy + max(9, int(10 * scale))), 2)
    if unit.suppression >= 50:
        arc_color = COLORS["danger"] if unit.suppression >= 80 else COLORS["suppression"]
        radius = max(18, int(self.tile_px * 0.72))
        if hasattr(pygame.draw, "arc"):
            pygame.draw.arc(
                self.screen,
                arc_color,
                pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2),
                math.pi,
                math.tau,
                2,
            )
        else:
            pygame.draw.circle(self.screen, arc_color, (cx, cy), radius, 2)


KillZoneApp.draw_unit = _presentation_draw_unit


def _presentation_draw_transient(self, event, now):
    position = event.get("pos")
    if not position:
        return
    center = self.world_to_screen(*position)
    if not self.map_view_rect().inflate(60, 60).collidepoint(center):
        return
    age = now - float(event.get("presented_at", now))
    kind = event.get("type")
    if kind == "shot" and age <= 0.11:
        radius = max(2, int((1.0 - age / 0.11) * 7))
        color = (255, 225, 142)
        pygame.draw.circle(self.screen, color, center, radius)
        pygame.draw.line(self.screen, color, (center[0] - radius * 2, center[1]), (center[0] + radius * 2, center[1]), 1)
        pygame.draw.line(self.screen, color, (center[0], center[1] - radius * 2), (center[0], center[1] + radius * 2), 1)
    elif kind == "explosion" and age <= 0.72:
        progress = clamp(age / 0.72, 0.0, 1.0)
        radius = max(4, int((8 + float(event.get("radius", 2.0)) * self.tile_px * 0.62) * (0.35 + progress)))
        alpha = int(165 * (1.0 - progress))
        surface = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
        local = (radius + 3, radius + 3)
        pygame.draw.circle(surface, (235, 126, 50, alpha), local, radius)
        pygame.draw.circle(surface, (255, 222, 145, min(210, alpha + 35)), local, max(2, radius // 3))
        pygame.draw.circle(surface, (76, 68, 57, alpha), local, radius, 2)
        self.screen.blit(surface, (center[0] - radius - 3, center[1] - radius - 3))
    elif kind in ("hurt", "death") and age <= 0.42:
        progress = clamp(age / 0.42, 0.0, 1.0)
        radius = 5 + int(progress * 12)
        pygame.draw.circle(self.screen, COLORS["danger"], center, radius, 2 if kind == "death" else 1)


KillZoneApp.draw_presentation_transient = _presentation_draw_transient


def _presentation_draw_weather(self, clock):
    rect = self.map_view_rect()
    weather = getattr(self.game, "weather", "clear")
    count = 48 if weather == "rain" else 12 if weather == "fog" else 9
    particles = presentation_weather_particles(weather, self.game.seed, clock, rect.w, rect.h, count)
    if weather == "rain":
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        wind_x = int(clamp(getattr(self.game, "wind", (0, 0))[0] * 3, -4, 4))
        for x, y, length, alpha in particles:
            pygame.draw.line(layer, (166, 187, 190, alpha), (x, y), (x + wind_x, y + length), 1)
        self.screen.blit(layer, rect.topleft)
    elif weather == "fog":
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        for x, y, length, alpha in particles:
            pygame.draw.ellipse(layer, (202, 203, 190, alpha), (x - length // 2, y - 8, length, 16))
        self.screen.blit(layer, rect.topleft)
    else:
        for x, y, _length, alpha in particles:
            color = (164, 150, 112) if alpha > 23 else (106, 103, 84)
            pygame.draw.circle(self.screen, color, (rect.left + x, rect.top + y), 1)


KillZoneApp.draw_presentation_weather = _presentation_draw_weather


def _presentation_draw_vignette(self):
    rect = self.map_view_rect()
    if self._presentation_vignette is None or self._presentation_vignette.get_size() != rect.size:
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        steps = 14
        for index in range(steps):
            alpha = int(4 + index * 1.35)
            inset = index * 3
            pygame.draw.rect(surface, (8, 10, 8, alpha), pygame.Rect(inset, inset, rect.w - inset * 2, rect.h - inset * 2), 3)
        self._presentation_vignette = surface
    self.screen.blit(self._presentation_vignette, rect.topleft)
    pygame.draw.rect(self.screen, (121, 116, 91), rect, 1)


KillZoneApp.draw_presentation_vignette = _presentation_draw_vignette


_presentation_previous_draw_map = KillZoneApp.draw_map


def _presentation_draw_map(self):
    _presentation_previous_draw_map(self)
    if self.state not in ("deployment", "game"):
        return
    now = time.perf_counter()
    supports_clip = hasattr(self.screen, "get_clip") and hasattr(self.screen, "set_clip")
    old_clip = self.screen.get_clip() if supports_clip else None
    if supports_clip:
        self.screen.set_clip(self.map_view_rect())
    try:
        # Existing simulation objects receive a brighter second pass, producing
        # readable streaks and shock fronts without touching authoritative state.
        for tracer in self.game.tracers:
            start = self.world_to_screen(*tracer.a)
            end = self.world_to_screen(*tracer.b)
            if self.map_view_rect().clipline(start, end):
                pygame.draw.line(self.screen, (255, 232, 157), start, end, 2)
                pygame.draw.line(self.screen, (255, 249, 220), start, end, 1)
        for impact in self.game.impacts:
            center = self.world_to_screen(impact.x, impact.y)
            if self.map_view_rect().collidepoint(center):
                life = clamp(impact.life / 0.22, 0.0, 1.0)
                radius = 2 + int((1.0 - life) * 6)
                pygame.draw.circle(self.screen, (203, 189, 157), center, radius, 1)

        for x, y, _suppression, _smoke, fire in getattr(self, "_dynamic_tiles", []):
            if fire <= 0:
                continue
            center = self.world_to_screen(x + 0.5, y + 0.5)
            if not self.map_view_rect().collidepoint(center):
                continue
            rng = random.Random(self.game.seed ^ x * 9137 ^ y * 193 ^ int(self.game.time * 8))
            for _ in range(min(4, 1 + int(fire))):
                ex = center[0] + rng.randint(-5, 5)
                ey = center[1] - rng.randint(4, 14)
                pygame.draw.circle(self.screen, (242, 137 + rng.randint(0, 60), 62), (ex, ey), 1)

        self._presentation_events = [
            event for event in self._presentation_events if now - float(event.get("presented_at", now)) <= 0.75
        ]
        for event in self._presentation_events:
            self.draw_presentation_transient(event, now)
        self.draw_presentation_weather(getattr(self.game, "time", 0.0))
        self.draw_presentation_vignette()
    finally:
        if supports_clip:
            self.screen.set_clip(old_clip)


KillZoneApp.draw_map = _presentation_draw_map


_presentation_previous_draw_menu_background = KillZoneApp.draw_menu_background


def _presentation_draw_menu_background(self):
    _presentation_previous_draw_menu_background(self)
    if self._presentation_menu_overlay is None or self._presentation_menu_overlay.get_size() != (WINDOW_W, WINDOW_H):
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        for y in range(0, WINDOW_H, 4):
            progress = y / max(1, WINDOW_H - 1)
            alpha = int(5 + 26 * abs(progress - 0.42))
            pygame.draw.rect(overlay, (7, 10, 8, alpha), (0, y, WINDOW_W, 4))
        pygame.draw.polygon(
            overlay,
            (188, 169, 112, 12),
            ((0, 150), (WINDOW_W, 105), (WINDOW_W, 260), (0, 300)),
        )
        for x in range(40, WINDOW_W, 130):
            pygame.draw.line(overlay, (195, 185, 146, 13), (x, 220), (x + 170, 650), 1)
        self._presentation_menu_overlay = overlay
    self.screen.blit(self._presentation_menu_overlay, (0, 0))


KillZoneApp.draw_menu_background = _presentation_draw_menu_background
