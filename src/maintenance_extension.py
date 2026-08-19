# ruff: noqa: F821
# This extension is compiled after the historical game source and intentionally
# uses names supplied by that execution context.

# =============================================================================
# KILL ZONE — MAINTENANCE / RELEASE HARDENING
# =============================================================================
# This file is intentionally plain Python.  The older source is preserved in
# compressed historical payloads, while current fixes remain easy to review.

_maintenance_previous_init = RealTimeGame.__init__


def _maintenance_init(
    self,
    seed: Optional[int] = None,
    difficulty: str = "Hard",
    player_roster: Optional[List[str]] = None,
    reserve_count: int = 0,
):
    if difficulty not in DIFFICULTY:
        choices = ", ".join(DIFFICULTY)
        raise ValueError(f"Unknown difficulty {difficulty!r}; choose one of: {choices}")
    _maintenance_previous_init(
        self,
        seed=seed,
        difficulty=difficulty,
        player_roster=player_roster,
        reserve_count=reserve_count,
    )
    self._maintenance_visual_revision = _KZ_VISUAL_TERRAIN_REV


RealTimeGame.__init__ = _maintenance_init


SQUAD_ROLE_GROUPS = {
    "assault": frozenset(("Rifleman", "Grenadier", "Assault")),
    "fire_support": frozenset(("Machine Gunner", "Automatic Rifleman", "HMG Crew", "Mortar Team")),
    "recon": frozenset(("Recon", "Marksman", "Sniper")),
    "support": frozenset(("Medic", "Engineer")),
}
_SQUAD_GROUP_BY_ROLE = {
    role: group
    for group, roles in SQUAD_ROLE_GROUPS.items()
    for role in roles
}
_SQUAD_FALLBACK_AFFINITY = {
    "assault": ("fire_support", "support", "recon"),
    "fire_support": ("assault", "support", "recon"),
    "recon": ("support", "fire_support", "assault"),
    "support": ("recon", "assault", "fire_support"),
}
AUTO_SQUAD_SIZE = 4
AUTO_SQUAD_LIMIT = 5


def squad_role_group(role):
    """Return the tactical group used only for automatic squad placement."""
    return _SQUAD_GROUP_BY_ROLE.get(role, "assault")


def _maintenance_auto_squad(self, faction, role):
    desired = squad_role_group(role)
    existing = [unit for unit in self.units if unit.faction == faction]
    history = {squad_id: [] for squad_id in range(1, AUTO_SQUAD_LIMIT + 1)}
    active = {squad_id: [] for squad_id in range(1, AUTO_SQUAD_LIMIT + 1)}
    for unit in existing:
        squad_id = getattr(unit, "squad_id", 0)
        if squad_id not in history:
            continue
        history[squad_id].append(unit)
        if unit.combat_effective:
            active[squad_id].append(unit)

    available = [
        squad_id
        for squad_id in history
        if len(active[squad_id]) < AUTO_SQUAD_SIZE
    ]

    # Reinforce an existing squad of the same tactical kind first.  Historical
    # members retain a depleted squad's identity, so reserves can replace its
    # losses instead of creating a new, unrelated fireteam.
    matching = []
    for squad_id in available:
        same = sum(squad_role_group(unit.role) == desired for unit in history[squad_id])
        if same:
            foreign = len(history[squad_id]) - same
            matching.append((same - foreign, len(active[squad_id]), -squad_id, squad_id))
    if matching:
        return max(matching)[-1]

    # Give a new tactical kind its own squad while a visible squad slot remains.
    unused = [squad_id for squad_id in available if not history[squad_id]]
    if unused:
        return unused[0]

    # Highly unusual rosters can need more role-specific groups than the five
    # squad tabs can display.  Keep the four-soldier cap and choose the closest
    # tactical neighbour rather than creating a hidden sixth squad.
    affinity = _SQUAD_FALLBACK_AFFINITY[desired]
    fallback = []
    for squad_id in available:
        group_counts = {}
        for unit in history[squad_id]:
            group = squad_role_group(unit.role)
            group_counts[group] = group_counts.get(group, 0) + 1
        dominant = max(group_counts, key=group_counts.get)
        priority = len(affinity) - affinity.index(dominant) if dominant in affinity else 0
        fallback.append((priority, -len(active[squad_id]), -squad_id, squad_id))
    if fallback:
        return max(fallback)[-1]

    # Manual reassignment can overfill all five squads.  Preserve the old
    # behaviour in that edge case by opening the next numbered squad.
    return max((getattr(unit, "squad_id", 0) for unit in existing), default=0) + 1


RealTimeGame.auto_squad_for = _maintenance_auto_squad


_maintenance_previous_add_unit = RealTimeGame.add_unit


def _maintenance_add_unit(self, faction, role, x, y):
    squad_id = self.auto_squad_for(faction, role)
    unit = _maintenance_previous_add_unit(self, faction, role, x, y)
    unit.squad_id = squad_id

    # The vertical-slice identity pass has already generated the surname.  Keep
    # it while correcting the letter/slot prefix to match smart allocation.
    if faction == "player" and hasattr(unit, "display_name"):
        surname = unit.display_name.split(" ", 1)[-1]
        slot = sum(
            other.faction == faction and getattr(other, "squad_id", 0) == squad_id
            for other in self.units
        )
        unit.display_name = f"{chr(64 + min(26, squad_id))}{slot} {surname}"
    return unit


RealTimeGame.add_unit = _maintenance_add_unit


_maintenance_previous_cleanup = RealTimeGame.cleanup_unit_state


def _maintenance_cleanup_unit_state(self, unit, reason="combat exit"):
    # Cleanup is inexpensive and must run for every separate combat exit.  The
    # old state sentinel was never reset after a medic revived a casualty, so a
    # second incapacitation with the same casualty state could be skipped.
    unit._cleanup_state = None
    return _maintenance_previous_cleanup(self, unit, reason)


RealTimeGame.cleanup_unit_state = _maintenance_cleanup_unit_state


def _maintenance_find_path(self, unit, dest, mode=None):
    started = time.perf_counter()
    mode = mode or unit.move_mode
    start = unit.tile
    dest = (int(dest[0]), int(dest[1]))

    # Terrain may change between simulation ticks (door controls, destruction,
    # engineer actions).  Invalidate immediately instead of waiting for the
    # next fixed update to notice the global visual revision.
    visual_revision = _KZ_VISUAL_TERRAIN_REV
    if getattr(self, "_maintenance_visual_revision", None) != visual_revision:
        self._maintenance_visual_revision = visual_revision
        self._path_cache.clear()

    occupied = {
        other.tile
        for other in self.units
        if other.uid != unit.uid and other.combat_effective
    }
    key = (start, dest, mode, unit.faction, self._terrain_revision)
    cached = self._path_cache.get(key)
    if cached is not None and all(tile not in occupied for tile in cached):
        path = list(cached)
        self._perf["path_ms"] += (time.perf_counter() - started) * 1_000
        return path

    def terrain_passable(x, y):
        if not (0 <= x < MAP_W and 0 <= y < MAP_H) or (x, y) in occupied:
            return False
        cell = self.grid[y][x]
        return not (cell.terrain == "door" and not cell.door_open) and TERRAIN[cell.terrain]["move"] < 999

    if not terrain_passable(*dest):
        return []

    # Safe routing reads the already-cached threat grid directly instead of
    # calling tile_threat for every A* edge.  This removes thousands of Python
    # function calls from each group order while preserving the same costs.
    threat_grid = None
    if mode == "safe":
        self.tile_threat(unit.faction, start[0], start[1])
        threat_grid = self._threat_grids[unit.faction]

    queue = [(0.0, 0.0, start)]
    came = {start: None}
    costs = {start: 0.0}
    closed = set()
    grid = self.grid
    terrain_data = TERRAIN
    # Weighted A*: routing is a real-time command preview, so a modestly greedy
    # heuristic is preferable to exploring half the battlefield for a path that
    # differs by only a few tenths of a movement-cost point.
    heuristic_scale = 1.5

    while queue:
        _, queued_cost, current = heapq.heappop(queue)
        if current in closed or queued_cost != costs.get(current):
            continue
        if current == dest:
            break
        closed.add(current)
        x, y = current
        current_terrain = grid[y][x].terrain
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not terrain_passable(nx, ny):
                continue
            cell = grid[ny][nx]
            step_cost = terrain_data[cell.terrain]["move"]
            if cell.terrain == "trench" and current_terrain == "trench":
                step_cost *= 0.62
            if mode == "safe":
                step_cost += threat_grid[ny][nx] * 2.25 + cell.ground_suppression * 0.022
                step_cost = max(0.18, step_cost - min(0.68, terrain_data[cell.terrain]["cover"] * 0.11))
            elif mode == "fast":
                step_cost *= 0.8
            new_cost = queued_cost + step_cost
            position = (nx, ny)
            if new_cost >= costs.get(position, float("inf")):
                continue
            costs[position] = new_cost
            came[position] = current
            heuristic = (abs(dest[0] - nx) + abs(dest[1] - ny)) * heuristic_scale
            heapq.heappush(queue, (new_cost + heuristic, new_cost, position))

    if dest not in came:
        path = []
    else:
        path = []
        current = dest
        while current != start:
            path.append(current)
            current = came[current]
        path.reverse()

    # Do not cache failures: a temporary unit blockade may disappear without a
    # terrain revision and should be retried on the next path budget slot.
    if path:
        if len(self._path_cache) > 512:
            self._path_cache.clear()
        self._path_cache[key] = tuple(path)
    self._perf["paths"] += 1
    self._perf["path_ms"] += (time.perf_counter() - started) * 1_000
    return path


RealTimeGame.find_path = _maintenance_find_path


_maintenance_previous_update_movement = RealTimeGame.update_movement


def _maintenance_update_movement(self, unit, dt):
    needs_path = (
        not unit.path
        and bool(unit.waypoints)
        and self.time >= getattr(unit, "path_ready_at", 0)
        and self.time >= getattr(unit, "wait_until", 0)
        and not (unit.deployed and unit.role in ("Machine Gunner", "HMG Crew", "Mortar Team"))
    )
    if needs_path:
        if getattr(self, "_maintenance_paths_started", 0) >= 1:
            return
        self._maintenance_paths_started = getattr(self, "_maintenance_paths_started", 0) + 1
    return _maintenance_previous_update_movement(self, unit, dt)


RealTimeGame.update_movement = _maintenance_update_movement


_maintenance_previous_update = RealTimeGame.update


def _maintenance_update(self, dt):
    # Spread group-order A* work across fixed ticks.  Sixteen paths are still
    # ready in roughly half a second, while a single rendered frame never pays
    # for three full battlefield searches at once.
    self._maintenance_paths_started = 0
    return _maintenance_previous_update(self, dt)


RealTimeGame.update = _maintenance_update


def _maintenance_update_spotting(self):
    # Build faction lists once and reject obviously out-of-range pairs before
    # entering LOS.  The previous target/faction nesting rebuilt the same lists
    # for every soldier and made the 6 Hz spotting pulse a frame-time spike.
    active = [unit for unit in self.units if unit.alive]
    by_faction = {
        "player": [unit for unit in active if unit.faction == "player" and unit.combat_effective],
        "enemy": [unit for unit in active if unit.faction == "enemy" and unit.combat_effective],
    }
    targets_by_faction = {
        "player": [unit for unit in active if unit.faction == "player"],
        "enemy": [unit for unit in active if unit.faction == "enemy"],
    }
    for faction, targets in (("player", targets_by_faction["enemy"]), ("enemy", targets_by_faction["player"])):
        observers = by_faction[faction]
        spotted_attribute = "spotted_player_until" if faction == "player" else "spotted_enemy_until"
        for target in targets:
            seen = False
            for observer in observers:
                maximum = ROLES[observer.role]["spot"] + 8.0
                dx = observer.x - target.x
                dy = observer.y - target.y
                if dx * dx + dy * dy > maximum * maximum:
                    continue
                if self.can_see(observer, target):
                    seen = True
                    break
            if seen:
                setattr(target, spotted_attribute, self.time + 2.2)
                self.intel[faction][target.uid] = {
                    "pos": (target.x, target.y),
                    "seen": self.time,
                    "role": target.role,
                }

    for unit in active:
        if not unit.combat_effective or unit.role not in ("Engineer", "Recon"):
            continue
        ux, uy = unit.tile
        radius = 3 if unit.role == "Engineer" else 2
        seen_attribute = "mine_seen_player" if unit.faction == "player" else "mine_seen_enemy"
        for y in range(max(0, uy - radius), min(MAP_H, uy + radius + 1)):
            for x in range(max(0, ux - radius), min(MAP_W, ux + radius + 1)):
                if self.grid[y][x].mine and math.hypot(x - ux, y - uy) <= radius:
                    setattr(self.grid[y][x], seen_attribute, True)

    # Preserve vertical-slice contact reporting without a second spotting pass.
    for uid, info, age in self.known_contacts("player", memory=10):
        if age > 0.08:
            continue
        last = self._contact_last_report.get(uid, -999)
        if self.time - last < 8:
            continue
        self._contact_last_report[uid] = self.time
        role = ROLE_CONTACT.get(info.get("role", ""), "INFANTRY")
        sector = _vs_sector_name(info["pos"][1])
        self.notify(f"CONTACT — {role}, {sector}", kind="danger", duration=3.8)
        self._vs_event("contact", f"Contact: {role}, {sector}", info["pos"])


RealTimeGame.update_spotting = _maintenance_update_spotting


def _maintenance_select_squad_number(self, squad_id):
    members = [
        unit.uid
        for unit in self.game.living("player")
        if unit.combat_effective and getattr(unit, "squad_id", 0) == squad_id
    ]
    if members:
        self.selected = members
        return True
    return False


KillZoneApp.select_squad_number = _maintenance_select_squad_number


_maintenance_previous_handle_key = KillZoneApp.handle_key


def _maintenance_handle_key(self, key, mods):
    if pygame.K_1 <= key <= pygame.K_9:
        number = key - pygame.K_0
        if not (mods & (pygame.KMOD_ALT | pygame.KMOD_CTRL | pygame.KMOD_SHIFT)):
            self.select_squad_number(number)
            return
        # Keep the established modified shortcuts: Alt reassigns squads,
        # Ctrl saves control groups, and Shift recalls control groups.
        if mods & pygame.KMOD_ALT and number > 5:
            return
    return _maintenance_previous_handle_key(self, key, mods)


KillZoneApp.handle_key = _maintenance_handle_key


_maintenance_previous_deployment_event = KillZoneApp.handle_deployment_event


def _maintenance_deployment_event(self, event):
    if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9:
        mods = getattr(event, "mod", 0)
        if not (mods & (pygame.KMOD_ALT | pygame.KMOD_CTRL | pygame.KMOD_SHIFT)):
            self.select_squad_number(event.key - pygame.K_0)
            return
    return _maintenance_previous_deployment_event(self, event)


KillZoneApp.handle_deployment_event = _maintenance_deployment_event


SQUAD_VISUAL_COLORS = (
    (226, 190, 92),
    (91, 171, 222),
    (126, 190, 126),
    (211, 132, 157),
    (174, 144, 220),
    (225, 146, 91),
    (91, 186, 174),
    (188, 193, 184),
    (218, 207, 117),
)
_SQUAD_TACTICAL_LABELS = {
    "assault": "ASSAULT",
    "fire_support": "FIRE SUP",
    "recon": "RECON",
    "support": "SUPPORT",
}


def squad_visual_color(squad_id):
    """Return the stable accent color for Squad A–I."""
    index = max(1, int(squad_id)) - 1
    return SQUAD_VISUAL_COLORS[index % len(SQUAD_VISUAL_COLORS)]


def squad_tactical_label(game, squad_id):
    counts = {}
    for unit in game.living("player"):
        if not unit.combat_effective or getattr(unit, "squad_id", 0) != squad_id:
            continue
        group = squad_role_group(unit.role)
        counts[group] = counts.get(group, 0) + 1
    if not counts:
        return "EMPTY"
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return "MIXED"
    return _SQUAD_TACTICAL_LABELS[ordered[0][0]]


_maintenance_previous_draw_unit = KillZoneApp.draw_unit


def _maintenance_draw_unit(self, unit):
    _maintenance_previous_draw_unit(self, unit)
    if unit.faction != "player" or not unit.combat_effective:
        return
    center_x, center_y = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(30, 30).collidepoint((center_x, center_y)):
        return

    tile_size = self.tile_px
    symbol_width = max(16, int(tile_size * 0.85))
    symbol_height = max(12, int(tile_size * 0.56))
    squad_id = max(1, int(getattr(unit, "squad_id", 1)))
    color = squad_visual_color(squad_id)
    symbol_top = center_y - symbol_height // 2

    # A colored cap and numbered badge make squad identity readable without
    # replacing the familiar blue NATO friendly marker.
    pygame.draw.line(
        self.screen,
        color,
        (center_x - symbol_width // 2 + 2, symbol_top + 2),
        (center_x + symbol_width // 2 - 2, symbol_top + 2),
        3,
    )
    badge_radius = max(5, min(7, int(tile_size * 0.24)))
    badge_center = (center_x - symbol_width // 2, symbol_top)
    pygame.draw.circle(self.screen, color, badge_center, badge_radius)
    pygame.draw.circle(self.screen, COLORS["black"], badge_center, badge_radius, 1)
    badge = self.cached_text_surface(str(squad_id), 8, "black")
    self.screen.blit(
        badge,
        (badge_center[0] - badge.get_width() // 2, badge_center[1] - badge.get_height() // 2),
    )

    if unit.uid in self.selected:
        selection_radius = max(17, int(tile_size * 0.68))
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            start = (
                center_x + dx * (selection_radius - 3),
                center_y + dy * (selection_radius - 3),
            )
            end = (
                center_x + dx * (selection_radius + 3),
                center_y + dy * (selection_radius + 3),
            )
            pygame.draw.line(self.screen, color, start, end, 2)


KillZoneApp.draw_unit = _maintenance_draw_unit


_maintenance_previous_draw_command_bar = KillZoneApp.draw_command_bar


def _maintenance_draw_command_bar(self):
    _maintenance_previous_draw_command_bar(self)
    active_units = [unit for unit in self.game.living("player") if unit.combat_effective]
    active_ids = {unit.uid for unit in active_units}
    selected_ids = set(self.selected) & active_ids

    # Redraw only the squad-tab layer with hotkey, type and color identity.
    for squad_id, rect in self.squad_rects().items():
        if squad_id == "ALL":
            active = bool(active_ids) and selected_ids == active_ids
            pygame.draw.rect(self.screen, COLORS["panel2"], rect, border_radius=3)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if active else COLORS["muted"],
                rect,
                2 if active else 1,
                border_radius=3,
            )
            label = self.cached_text_surface("ALL UNITS", 10, "white")
            self.screen.blit(
                label,
                (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2),
            )
            continue

        members = [unit for unit in active_units if getattr(unit, "squad_id", 0) == squad_id]
        member_ids = {unit.uid for unit in members}
        active = bool(member_ids) and selected_ids == member_ids
        color = squad_visual_color(squad_id)
        pygame.draw.rect(self.screen, COLORS["panel2"], rect, border_radius=3)
        pygame.draw.rect(
            self.screen,
            COLORS["select"] if active else color,
            rect,
            2 if active else 1,
            border_radius=3,
        )
        pygame.draw.rect(self.screen, color, (rect.x + 5, rect.y + 5, 17, 18), border_radius=3)
        hotkey = self.cached_text_surface(str(squad_id), 10, "black")
        self.screen.blit(
            hotkey,
            (rect.x + 13 - hotkey.get_width() // 2, rect.y + 14 - hotkey.get_height() // 2),
        )
        letter = chr(64 + min(26, int(squad_id)))
        title = self.cached_text_surface(f"SQUAD {letter}", 8, "white")
        kind = self.cached_text_surface(squad_tactical_label(self.game, squad_id), 7, "muted")
        self.screen.blit(title, (rect.x + 27, rect.y + 4))
        self.screen.blit(kind, (rect.x + 27, rect.y + 15))

    # Unit cards inherit the same squad stripe and key badge, so the map,
    # cards and number-key selection all share one visual language.
    for unit, rect in self.unit_card_rects():
        squad_id = max(1, int(getattr(unit, "squad_id", 1)))
        color = squad_visual_color(squad_id)
        selected = unit.uid in selected_ids
        pygame.draw.rect(self.screen, color, (rect.x + 2, rect.y + 2, rect.w - 4, 3))
        pygame.draw.rect(
            self.screen,
            COLORS["select"] if selected else color,
            rect,
            2 if selected else 1,
            border_radius=2,
        )
        badge_rect = pygame.Rect(rect.right - 16, rect.y + 5, 12, 12)
        pygame.draw.rect(self.screen, color, badge_rect, border_radius=2)
        number = self.cached_text_surface(str(squad_id), 8, "black")
        self.screen.blit(
            number,
            (badge_rect.centerx - number.get_width() // 2, badge_rect.centery - number.get_height() // 2),
        )

    mode_button = {
        "assault": "ASSAULT",
        "suppress": "SUPPRESS",
        "overwatch": "OVERWATCH",
        "grenade": "GRENADE",
        "smoke": "SMOKE",
        "bound": "BOUND",
        "fallback": "FALLBACK",
    }.get(self.command_mode)
    if mode_button:
        rect = self.command_bar_rects().get(mode_button)
        if rect:
            pygame.draw.rect(self.screen, COLORS["select"], rect, 2, border_radius=3)


KillZoneApp.draw_command_bar = _maintenance_draw_command_bar


_maintenance_previous_handle_command_bar = KillZoneApp.handle_command_bar


def _maintenance_handle_command_bar(self, pos):
    overwatch = self.command_bar_rects().get("OVERWATCH")
    if overwatch and overwatch.collidepoint(pos):
        if self.selected_units():
            self.command_mode = "overwatch"
            self.message = "OVERWATCH — right-click a facing point"
        return True
    return _maintenance_previous_handle_command_bar(self, pos)


KillZoneApp.handle_command_bar = _maintenance_handle_command_bar


_maintenance_previous_issue_context = KillZoneApp.issue_context_command


def _maintenance_issue_context(self, cell, append=False):
    if self.command_mode == "overwatch":
        units = self.selected_units()
        if units and cell and self.game.in_bounds(*cell):
            for unit in units:
                self.game.set_overwatch(unit, angle_to(unit, cell), 100)
            self.message = "Overwatch arc established"
        self.command_mode = "normal"
        return
    return _maintenance_previous_issue_context(self, cell, append=append)


KillZoneApp.issue_context_command = _maintenance_issue_context


COMMAND_BAR_HELP_COLUMNS = (
    (
        ("ASSAULT", "TARGET", "Coordinates support fire, smoke and an assault toward the objective."),
        ("SUPPRESS", "TARGET", "Orders capable automatic weapons to suppress the chosen area."),
        ("OVERWATCH", "TARGET", "Establishes reaction-fire arcs facing the right-clicked point."),
        ("GRENADE", "TARGET", "Throws fragmentation grenades from selected troops that carry them."),
        ("SMOKE", "TARGET", "Throws smoke grenades to block observation and incoming fire."),
        ("BOUND", "TARGET", "Alternates moving and covering elements toward a destination."),
        ("FALLBACK", "TARGET", "Sets a rally point used when troops withdraw or recover."),
    ),
    (
        ("RELOAD", "INSTANT", "Starts reloading every selected troop that can currently reload."),
        ("STANCE", "CYCLE", "Cycles standing, crouched and prone for speed versus protection."),
        ("FORMATION", "WEDGE etc.", "The label is current formation; cycles wedge, line, column and spread."),
        ("DISCIPLINE", "FREE etc.", "Controls hold/return/free/confident fire, including less-accurate moving shots."),
        ("PRIORITY", "SPECIALIST etc.", "Cycles nearest, exposed, specialist and suppressed targets."),
        ("AUTO", "ON / OFF", "Toggles automatic reload, cover reaction, smoke and medic assistance."),
        ("HOLD", "TOGGLE", "Delays breaking and prevents automatic survival movement while enabled."),
    ),
)


def _maintenance_draw_command_guide(self, standalone=False):
    if standalone:
        self.draw_menu_background()

    width, height = 1160, 650
    x = (WINDOW_W - width) // 2
    y = 40
    if standalone:
        pygame.draw.rect(self.screen, COLORS["panel"], (x, y, width, height), border_radius=4)
    else:
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((20, 23, 20, 247))
        self.screen.blit(overlay, (x, y))
    pygame.draw.rect(self.screen, COLORS["select"], (x, y, width, height), 2, border_radius=4)

    self.text("FIELD MANUAL · COMMAND BAR", (x + 24, y + 16), 23, "white")
    self.text(
        "Select troops first. TARGET commands wait for a right-click on the battlefield.",
        (x + 24, y + 48),
        11,
        "muted",
    )
    close_hint = "Use BACK to return to the menu." if standalone else "Press F1 to close this guide."
    self.text(close_hint, (x + width - 300, y + 24), 10, "select")

    headings = ("TARGETED / TACTICAL ORDERS", "INSTANT / BEHAVIOUR SETTINGS")
    column_width = (width - 70) // 2
    for column_index, entries in enumerate(COMMAND_BAR_HELP_COLUMNS):
        column_x = x + 24 + column_index * (column_width + 22)
        self.text(headings[column_index], (column_x, y + 82), 13, "select")
        row_y = y + 108
        accent = COLORS["objective"] if column_index == 0 else COLORS["blue"]
        for button, gesture, description in entries:
            row = pygame.Rect(column_x, row_y, column_width, 47)
            pygame.draw.rect(self.screen, COLORS["panel2"], row, border_radius=3)
            pygame.draw.rect(self.screen, accent, (row.x, row.y, 4, row.h), border_radius=2)
            self.text(button, (row.x + 13, row.y + 7), 10, "white")
            self.text(gesture, (row.x + 13, row.y + 25), 8, "contact" if column_index == 0 else "muted")
            self.text(description, (row.x + 116, row.y + 17), 9, "text")
            row_y += 52

    footer_y = y + 492
    pygame.draw.line(
        self.screen,
        COLORS["muted"],
        (x + 24, footer_y),
        (x + width - 24, footer_y),
        1,
    )
    self.text("READING THE CHANGING LABELS", (x + 24, footer_y + 15), 12, "select")
    self.text(
        "WEDGE = formation · FREE = fire discipline · SPECIALIST = target priority · AUTO ON = autonomy state",
        (x + 24, footer_y + 36),
        10,
        "text",
    )
    self.text(
        "Typical targeted order: select squad → click command → right-click map. The active MODE appears in the top bar.",
        (x + 24, footer_y + 58),
        10,
        "muted",
    )
    self.text(
        "Squads: 1–9 select · double-tap to focus · Alt+1–5 reassign · Ctrl save · Shift recall",
        (x + 24, footer_y + 80),
        10,
        "muted",
    )
    self.text(
        "Shortcuts: F2 Assault · F3 Bound · Shift+D Doctrine · Shift+B Engineer Build · F10 Auto",
        (x + 24, footer_y + 102),
        10,
        "muted",
    )
    self.text(
        "Quick selection: Shift+W wounded · Shift+P pinned/breaking · Shift+I idle",
        (x + 24, footer_y + 124),
        10,
        "muted",
    )
    self.text(
        "Map status: BREAK/PIN · WND/AID/CASEVAC · JAM/RLD/EMPTY · edge arrows track selected off-screen troops",
        (x + 24, footer_y + 143),
        8,
        "contact",
    )

    if standalone:
        self.button(self.help_menu_rects()["back"], "BACK", self.mouse, accent=True)


def _maintenance_draw_help(self):
    _maintenance_draw_command_guide(self, standalone=False)


def _maintenance_draw_help_menu(self):
    _maintenance_draw_command_guide(self, standalone=True)


KillZoneApp.draw_help = _maintenance_draw_help
KillZoneApp.draw_help_menu = _maintenance_draw_help_menu


def sector_stability_color(stability):
    """Return the UI color key for defensive line stability."""
    return "good" if stability > 65 else "contact" if stability > 30 else "danger"


_maintenance_previous_text = KillZoneApp.text


def _maintenance_text(self, value, pos, size=14, color="text"):
    # The existing sidebar emits these three rows through the shared text helper.
    # Correct their inverted semantic color without replacing the dense sidebar.
    text_value = str(value)
    help_replacements = {
        "Ctrl+1..9 save groups; 1..9 recall them.":
            "1..9 select squads; Ctrl+1..9 save groups; Shift+1..9 recall groups.",
        "Alt+1..5 assign persistent Squad A–E | click squad tabs to select | Ctrl+1..9 control groups":
            "1..9 select Squad A–I | Alt+1..5 reassign | Ctrl+1..9 save groups | Shift+1..9 recall",
    }
    if text_value in help_replacements:
        value = help_replacements[text_value]
        text_value = value
    stripped = text_value.lstrip()
    if size == 8 and stripped.startswith(("NORTH", "CENTRE", "SOUTH")) and "%" in stripped:
        try:
            stability = float(stripped.split("%", 1)[0].split()[-1])
        except (ValueError, IndexError):
            pass
        else:
            color = sector_stability_color(stability)
    return _maintenance_previous_text(self, value, pos, size, color)


KillZoneApp.text = _maintenance_text


_maintenance_original_asset_bootstrap = bootstrap_assets_async


def bootstrap_assets_async():
    """Start optional downloads unless explicitly disabled for tests/offline use."""
    if os.environ.get("KILLZONE_DISABLE_ASSET_DOWNLOADS", "").lower() in ("1", "true", "yes"):
        return None
    return _maintenance_original_asset_bootstrap()


# =============================================================================
# QUICK QOL — COMMAND FEEDBACK / SELECTION / PLANNING READABILITY
# =============================================================================

QOL_TARGET_MODES = {
    "ASSAULT": "assault",
    "SUPPRESS": "suppress",
    "OVERWATCH": "overwatch",
    "GRENADE": "grenade",
    "SMOKE": "smoke",
    "BOUND": "bound",
    "FALLBACK": "fallback",
}
COMMAND_BAR_TOOLTIPS = {
    button: description
    for column in COMMAND_BAR_HELP_COLUMNS
    for button, _gesture, description in column
}


def _qol_notify(app, text, kind="info", duration=1.8):
    app.message = text
    game = getattr(app, "game", None)
    if game is not None and hasattr(game, "notify"):
        game.notify(text, kind=kind, duration=duration)


def command_button_status(app, button, units=None):
    """Return (enabled, reason) for a command-bar button."""
    units = list(app.selected_units() if units is None else units)
    if not units:
        return False, "Select one or more troops first"
    if button == "SUPPRESS":
        capable = [
            unit
            for unit in units
            if unit.role in ("Machine Gunner", "HMG Crew", "Automatic Rifleman")
            and unit.ammo > 0
            and not unit.jammed
        ]
        return (True, "") if capable else (False, "Requires an armed automatic weapon")
    if button == "OVERWATCH":
        capable = [unit for unit in units if unit.ammo > 0 and not unit.jammed]
        return (True, "") if capable else (False, "No selected weapon can provide overwatch")
    if button == "GRENADE":
        return (True, "") if any(unit.grenades > 0 for unit in units) else (False, "No fragmentation grenades available")
    if button == "SMOKE":
        return (True, "") if any(unit.smoke_grenades > 0 for unit in units) else (False, "No smoke grenades available")
    if button == "RELOAD":
        ready = any(
            unit.reload_timer <= 0
            and bool(unit.magazines)
            and unit.ammo < unit.weapon["mag"]
            for unit in units
        )
        return (True, "") if ready else (False, "All selected weapons are full or out of spare magazines")
    if button == "BOUND":
        return (True, "") if len(units) >= 2 else (False, "Bounding advance requires at least two troops")
    return True, ""


def _qol_command_label(app, button, units):
    if button == "FORMATION":
        return app.formation.upper()
    if button == "DISCIPLINE" and units:
        return units[0].fire_discipline.upper()
    if button == "PRIORITY" and units:
        return units[0].target_priority.upper()
    if button == "AUTO":
        enabled = bool(units) and all(
            unit.auto_reload and unit.auto_cover and unit.auto_smoke and unit.auto_medic
            for unit in units
        )
        return "AUTO ON" if enabled else "AUTO OFF"
    return button


def unit_card_tooltip_lines(unit):
    spare_rounds = sum(max(0, int(rounds)) for rounds in unit.magazines)
    condition = "WOUNDED" if unit.casualty == "wounded" else "COMBAT EFFECTIVE"
    morale_state = getattr(unit, "morale_state", "STEADY")
    return (
        f"{getattr(unit, 'display_name', unit.role)} — {unit.role}",
        f"HEALTH {unit.hp:.0f}/{unit.max_hp:.0f}  ·  {condition}",
        f"AMMO {unit.ammo} loaded + {spare_rounds} reserve  ·  {len(unit.magazines)} magazines",
        f"SUPPRESSION {unit.suppression:.0f}/100  ·  MORALE {unit.morale:.0f} ({morale_state})",
    )


def _qol_draw_tooltip(app, lines, anchor_x, anchor_y, accent="select", width=430):
    height = 16 + len(lines) * 16
    x = int(clamp(anchor_x, 8, WINDOW_W - width - 8))
    y = int(clamp(anchor_y - height, MAP_Y + 4, WINDOW_H - height - 8))
    pygame.draw.rect(app.screen, (25, 28, 24), (x, y, width, height), border_radius=3)
    pygame.draw.rect(app.screen, COLORS[accent], (x, y, width, height), 1, border_radius=3)
    for index, line in enumerate(lines):
        color = "white" if index == 0 else "muted"
        app.text(line, (x + 10, y + 8 + index * 16), 9 if index else 10, color)


_qol_previous_draw_command_bar = KillZoneApp.draw_command_bar


def _qol_draw_command_bar(self):
    _qol_previous_draw_command_bar(self)
    units = self.selected_units()
    rects = self.command_bar_rects()

    # Keep the whole command strip present and legible even with no selection,
    # and visually mute actions that cannot do useful work right now.
    for button, rect in rects.items():
        enabled, _reason = command_button_status(self, button, units)
        if enabled:
            continue
        pygame.draw.rect(self.screen, (33, 36, 32), rect, border_radius=3)
        pygame.draw.rect(self.screen, (73, 78, 69), rect, 1, border_radius=3)
        label = self.cached_text_surface(_qol_command_label(self, button, units), 9, "muted")
        self.screen.blit(
            label,
            (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2),
        )

    hovered_command = next(
        ((button, rect) for button, rect in rects.items() if rect.collidepoint(self.mouse)),
        None,
    )
    hovered_card = next(
        ((unit, rect) for unit, rect in self.unit_card_rects() if rect.collidepoint(self.mouse)),
        None,
    )
    if hovered_card:
        unit, rect = hovered_card
        _qol_draw_tooltip(
            self,
            unit_card_tooltip_lines(unit),
            rect.centerx - 210,
            rect.y - 7,
            accent="good" if unit.hp > unit.max_hp * 0.5 else "danger",
        )
    elif hovered_command:
        button, rect = hovered_command
        enabled, reason = command_button_status(self, button, units)
        mode = "TARGET — click, then right-click the battlefield" if button in QOL_TARGET_MODES else "INSTANT / SETTING"
        lines = [f"{button}  ·  {mode}", COMMAND_BAR_TOOLTIPS[button]]
        if not enabled:
            lines.append(f"Unavailable: {reason}")
        _qol_draw_tooltip(
            self,
            lines,
            rect.centerx - 215,
            rect.y - 7,
            accent="select" if enabled else "danger",
        )


KillZoneApp.draw_command_bar = _qol_draw_command_bar


_qol_previous_handle_command_bar = KillZoneApp.handle_command_bar


def _qol_handle_command_bar(self, pos):
    clicked = next(
        (button for button, rect in self.command_bar_rects().items() if rect.collidepoint(pos)),
        None,
    )
    if clicked is None:
        return _qol_previous_handle_command_bar(self, pos)
    enabled, reason = command_button_status(self, clicked)
    if not enabled:
        _qol_notify(self, reason, kind="danger", duration=2.2)
        return True

    handled = _qol_previous_handle_command_bar(self, pos)
    if not handled:
        return False
    if clicked in QOL_TARGET_MODES:
        _qol_notify(self, f"{clicked} ready — right-click the battlefield", duration=2.0)
    else:
        label = _qol_command_label(self, clicked, self.selected_units())
        _qol_notify(self, f"{clicked}: {label}", duration=1.5)
    return True


KillZoneApp.handle_command_bar = _qol_handle_command_bar


_qol_previous_issue_context = KillZoneApp.issue_context_command


def _qol_issue_context(self, cell, append=False):
    previous_mode = self.command_mode
    result = _qol_previous_issue_context(self, cell, append=append)
    if previous_mode in QOL_TARGET_MODES.values() and self.command_mode == "normal":
        label = next(
            (button for button, mode in QOL_TARGET_MODES.items() if mode == previous_mode),
            previous_mode.upper(),
        )
        _qol_notify(self, f"{label} order confirmed", duration=1.5)
    elif previous_mode == "normal" and self.selected_units():
        _qol_notify(self, "Order confirmed", duration=1.2)
    return result


KillZoneApp.issue_context_command = _qol_issue_context


_qol_previous_draw_map = KillZoneApp.draw_map


def _qol_draw_map(self):
    _qol_previous_draw_map(self)
    if self.command_mode not in QOL_TARGET_MODES.values():
        return
    cell = self.map_cell_from_mouse(self.mouse)
    if cell is None:
        return
    rect = self.cell_rect(*cell)
    if not rect.colliderect(self.map_view_rect()):
        return
    color_key = {
        "grenade": "danger",
        "smoke": "white",
        "suppress": "suppression",
        "fallback": "blue",
    }.get(self.command_mode, "select")
    color = COLORS[color_key]
    center = rect.center
    radius = max(8, int(min(rect.w, rect.h) * 0.38))
    pygame.draw.rect(self.screen, color, rect, 2)
    pygame.draw.circle(self.screen, color, center, radius, 1)
    pygame.draw.line(self.screen, color, (center[0] - radius - 4, center[1]), (center[0] + radius + 4, center[1]), 1)
    pygame.draw.line(self.screen, color, (center[0], center[1] - radius - 4), (center[0], center[1] + radius + 4), 1)
    label = self.cached_text_surface(f"{self.command_mode.upper()} · RMB", 9, color_key)
    label_x = int(clamp(center[0] + 12, MAP_X + 4, MAP_X + MAP_VIEW_W_PX - label.get_width() - 4))
    self.screen.blit(label, (label_x, center[1] - 18))


KillZoneApp.draw_map = _qol_draw_map


_qol_previous_select_squad_number = KillZoneApp.select_squad_number


def _qol_select_squad_number(self, squad_id):
    now = time.perf_counter()
    double_tap = (
        getattr(self, "_qol_last_squad_key", None) == squad_id
        and now - getattr(self, "_qol_last_squad_at", -99.0) <= 0.42
    )
    selected = _qol_previous_select_squad_number(self, squad_id)
    if selected:
        self._qol_last_squad_key = squad_id
        self._qol_last_squad_at = now
        letter = chr(64 + min(26, int(squad_id)))
        if double_tap:
            self.focus_selected()
            _qol_notify(self, f"Squad {letter} selected and focused", duration=1.4)
        else:
            _qol_notify(self, f"Squad {letter} selected — tap {squad_id} again to focus", duration=1.4)
    else:
        _qol_notify(self, f"Squad {squad_id} is not deployed", kind="danger", duration=1.5)
    return selected


KillZoneApp.select_squad_number = _qol_select_squad_number


def _qol_select_status(self, status):
    active = [unit for unit in self.game.living("player") if unit.combat_effective]
    if status == "wounded":
        matches = [unit for unit in active if unit.casualty == "wounded" or unit.hp < unit.max_hp]
    elif status == "pinned":
        matches = [
            unit
            for unit in active
            if getattr(unit, "morale_state", "") in ("PINNED", "BREAKING", "ROUTING")
            or unit.suppression >= 80
        ]
    else:
        matches = [
            unit
            for unit in active
            if unit.order == "idle" and unit.action_timer <= 0 and unit.reload_timer <= 0
        ]
    if matches:
        self.selected = [unit.uid for unit in matches]
        _qol_notify(self, f"Selected {len(matches)} {status} troop(s)", duration=1.5)
        return True
    _qol_notify(self, f"No {status} troops available", kind="danger", duration=1.5)
    return False


KillZoneApp.select_units_by_status = _qol_select_status


_qol_previous_handle_key = KillZoneApp.handle_key


def _qol_handle_key(self, key, mods):
    if key == pygame.K_ESCAPE:
        if getattr(self, "show_help", False):
            self.show_help = False
            return
        if self.command_mode != "normal":
            cancelled = self.command_mode.upper()
            self.command_mode = "normal"
            _qol_notify(self, f"{cancelled} cancelled", duration=1.3)
            return
    if mods & pygame.KMOD_SHIFT:
        status = {
            pygame.K_w: "wounded",
            pygame.K_p: "pinned",
            pygame.K_i: "idle",
        }.get(key)
        if status:
            self.select_units_by_status(status)
            return
    return _qol_previous_handle_key(self, key, mods)


KillZoneApp.handle_key = _qol_handle_key


def _qol_marker(self, pos, label, color, shape="circle"):
    x, y = int(pos[0]), int(pos[1])
    if shape == "diamond":
        pygame.draw.polygon(self.screen, color, ((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)))
        pygame.draw.polygon(self.screen, COLORS["black"], ((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)), 1)
    else:
        pygame.draw.circle(self.screen, color, (x, y), 8)
        pygame.draw.circle(self.screen, COLORS["black"], (x, y), 8, 1)
    text_surface = self.cached_text_surface(label, 8, "black")
    self.screen.blit(
        text_surface,
        (x - text_surface.get_width() // 2, y - text_surface.get_height() // 2),
    )


def _qol_draw_planned_orders(self):
    map_rect = self.map_view_rect()
    for unit in self.selected_units()[:8]:
        color = squad_visual_color(getattr(unit, "squad_id", 1))
        last = self.world_to_screen(unit.x, unit.y)
        route = list(unit.path[:28])
        for tile in route:
            current = self.world_to_screen(*tile)
            if map_rect.clipline(last, current):
                pygame.draw.line(self.screen, color, last, current, 1)
            last = current

        order_number = 1
        for waypoint in unit.waypoints[:3]:
            current = self.world_to_screen(*waypoint)
            if map_rect.clipline(last, current):
                pygame.draw.line(self.screen, color, last, current, 1)
            if map_rect.collidepoint(current):
                _qol_marker(self, current, str(order_number), color, shape="diamond")
                self.text("MOVE", (current[0] + 10, current[1] - 7), 8, color)
            last = current
            order_number += 1

        for queue_index, (kind, data) in enumerate(unit.command_queue[:6], order_number):
            if kind == "move":
                current = self.world_to_screen(*data)
                if map_rect.clipline(last, current):
                    pygame.draw.line(self.screen, COLORS["select"], last, current, 1)
                if map_rect.collidepoint(current):
                    _qol_marker(self, current, str(queue_index), COLORS["select"])
                    self.text("QUEUED", (current[0] + 10, current[1] - 7), 8, "select")
                last = current
            elif kind == "fire":
                target_uid, _mode = data
                target = self.game.get_unit(target_uid)
                if target is None:
                    continue
                current = self.world_to_screen(target.x, target.y)
                if map_rect.collidepoint(current):
                    pygame.draw.circle(self.screen, COLORS["danger"], current, 10, 1)
                    pygame.draw.line(self.screen, COLORS["danger"], (current[0] - 12, current[1]), (current[0] + 12, current[1]), 1)
                    pygame.draw.line(self.screen, COLORS["danger"], (current[0], current[1] - 12), (current[0], current[1] + 12), 1)
                    self.text(f"F{queue_index}", (current[0] + 11, current[1] - 8), 8, "danger")


KillZoneApp.draw_planned_orders = _qol_draw_planned_orders


# =============================================================================
# QUICK QOL — ACCESSIBILITY / PERSISTENT SETTINGS
# =============================================================================

UI_SCALE_CHOICES = (0.9, 1.0, 1.1)
PERSISTED_SETTING_DEFAULTS = {
    "display_mode": "windowed",
    "last_fullscreen_mode": "borderless",
    "menu_speed": 1.0,
    "menu_show_help": True,
    "audio_enabled": True,
    "show_fps": False,
    "show_perf": False,
    "fps_cap": 0,
    "ui_scale": 1.0,
    "large_text": False,
}


def settings_file_path():
    override = os.environ.get("KILLZONE_SETTINGS_PATH")
    if override:
        return Path(override)
    local_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_data) if local_data else Path.home() / ".config"
    return base / "KillZone" / "settings.json"


def _qol_settings_disabled():
    return os.environ.get("KILLZONE_DISABLE_SETTINGS_PERSISTENCE", "").lower() in ("1", "true", "yes")


def serialized_user_settings(app):
    return {
        key: getattr(app, key, default)
        for key, default in PERSISTED_SETTING_DEFAULTS.items()
    }


def apply_user_settings(app, values):
    if not isinstance(values, dict):
        return False
    changed = False
    display_mode = values.get("display_mode")
    if display_mode in ("windowed", "borderless", "exclusive"):
        app.display_mode = display_mode
        changed = True
    fullscreen_mode = values.get("last_fullscreen_mode")
    if fullscreen_mode in ("borderless", "exclusive"):
        app.last_fullscreen_mode = fullscreen_mode
        changed = True
    if values.get("menu_speed") in (0.5, 1.0, 2.0):
        app.menu_speed = float(values["menu_speed"])
        changed = True
    for key in ("menu_show_help", "audio_enabled", "show_fps", "show_perf", "large_text"):
        if isinstance(values.get(key), bool):
            setattr(app, key, values[key])
            changed = True
    if values.get("fps_cap") in (0, 60, 120, 240):
        app.fps_cap = int(values["fps_cap"])
        changed = True
    scale = values.get("ui_scale")
    if isinstance(scale, (int, float)) and any(abs(float(scale) - choice) < 0.001 for choice in UI_SCALE_CHOICES):
        app.ui_scale = float(scale)
        changed = True
    return changed


def save_user_settings(app, path=None):
    if path is None and _qol_settings_disabled():
        return False
    destination = Path(path) if path is not None else settings_file_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(serialized_user_settings(app), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError:
        return False
    return True


def load_user_settings(app, path=None):
    if path is None and _qol_settings_disabled():
        return False
    source = Path(path) if path is not None else settings_file_path()
    try:
        values = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return apply_user_settings(app, values)


def effective_ui_font_size(app, requested_size):
    requested = max(6, int(requested_size))
    scale = getattr(app, "ui_scale", 1.0)
    scaled = int(round(requested * scale))
    if getattr(app, "large_text", False):
        scaled += 2 if requested <= 12 else 1 if requested <= 18 else 0
    return max(6, scaled)


def _qol_clear_text_caches(app):
    if hasattr(app, "_text_surface_cache"):
        app._text_surface_cache.clear()


_qol_previous_app_init = KillZoneApp.__init__


def _qol_app_init(self):
    self.ui_scale = 1.0
    self.large_text = False
    self._qol_last_squad_key = None
    self._qol_last_squad_at = -99.0
    _qol_previous_app_init(self)
    previous_mode = self.display_mode
    if load_user_settings(self):
        _qol_clear_text_caches(self)
        if self.display_mode != previous_mode:
            self.apply_display_mode()


KillZoneApp.__init__ = _qol_app_init


_qol_previous_get_font = KillZoneApp.get_font


def _qol_get_font(self, size):
    return _qol_previous_get_font(self, effective_ui_font_size(self, size))


KillZoneApp.get_font = _qol_get_font


def _qol_button(self, rect, label, mouse=None, enabled=True, accent=False):
    hover = bool(mouse and rect.collidepoint(mouse))
    fill = COLORS["panel2"] if hover and enabled else COLORS["panel"]
    if accent and enabled:
        fill = (68, 76, 58) if not hover else (82, 92, 69)
    if not enabled:
        fill = (36, 39, 35)
    pygame.draw.rect(self.screen, fill, rect, border_radius=4)
    pygame.draw.rect(
        self.screen,
        COLORS["select"] if hover and enabled else COLORS["muted"],
        rect,
        2 if hover and enabled else 1,
        border_radius=4,
    )
    surface = self.cached_text_surface(label, 12, "white" if enabled else "muted")
    self.screen.blit(
        surface,
        (rect.centerx - surface.get_width() // 2, rect.centery - surface.get_height() // 2),
    )


KillZoneApp.button = _qol_button


def _qol_settings_rects(self):
    center = WINDOW_W // 2
    speed_x = center - 330
    return {
        "speed05": pygame.Rect(speed_x, 168, 200, 38),
        "speed1": pygame.Rect(speed_x + 230, 168, 200, 38),
        "speed2": pygame.Rect(speed_x + 460, 168, 200, 38),
        "help": pygame.Rect(center - 190, 226, 380, 36),
        "audio": pygame.Rect(center - 190, 268, 380, 36),
        "fps": pygame.Rect(center - 190, 310, 380, 36),
        "perf": pygame.Rect(center - 190, 352, 380, 36),
        "fpscap": pygame.Rect(center - 190, 394, 380, 36),
        "fullscreen": pygame.Rect(center - 190, 436, 380, 36),
        "uiscale": pygame.Rect(center - 190, 478, 380, 36),
        "largetext": pygame.Rect(center - 190, 520, 380, 36),
        "back": pygame.Rect(center - 150, 584, 300, 42),
    }


KillZoneApp.settings_rects = _qol_settings_rects


def _qol_draw_settings(self):
    self.draw_menu_background()
    title = self.get_font(42).render("SETTINGS", True, COLORS["white"])
    self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 42))
    self.text("DEFAULT SIMULATION SPEED", (WINDOW_W // 2 - 330, 133), 14, "muted")
    for name, rect in self.settings_rects().items():
        if name.startswith("speed") and name != "fpscap":
            value = {"speed05": 0.5, "speed1": 1.0, "speed2": 2.0}[name]
            label = f"[ {value:g}× ]" if self.menu_speed == value else f"{value:g}×"
            self.button(rect, label, self.mouse, accent=self.menu_speed == value)
        elif name == "help":
            self.button(rect, f"HELP ON BATTLE START: {'ON' if self.menu_show_help else 'OFF'}", self.mouse, accent=self.menu_show_help)
        elif name == "audio":
            self.button(rect, f"COMBAT AUDIO: {'ON' if self.audio_enabled else 'OFF'}", self.mouse, accent=self.audio_enabled)
        elif name == "fps":
            self.button(rect, f"FPS COUNTER: {'ON' if self.show_fps else 'OFF'}", self.mouse, accent=self.show_fps)
        elif name == "perf":
            self.button(rect, f"PERFORMANCE PROFILER: {'ON' if self.show_perf else 'OFF'}", self.mouse, accent=self.show_perf)
        elif name == "fpscap":
            label = "RENDER FPS: UNCAPPED" if self.fps_cap == 0 else f"RENDER FPS: {self.fps_cap}"
            self.button(rect, label, self.mouse, accent=self.fps_cap == 0)
        elif name == "fullscreen":
            mode = {
                "windowed": "WINDOWED",
                "borderless": "BORDERLESS FULLSCREEN",
                "exclusive": "EXCLUSIVE FULLSCREEN",
            }.get(self.display_mode, self.display_mode.upper())
            self.button(rect, f"DISPLAY MODE: {mode}", self.mouse, accent=self.display_mode != "windowed")
        elif name == "uiscale":
            self.button(rect, f"UI SCALE: {self.ui_scale * 100:.0f}%", self.mouse, accent=self.ui_scale > 1.0)
        elif name == "largetext":
            self.button(rect, f"LARGER TEXT: {'ON' if self.large_text else 'OFF'}", self.mouse, accent=self.large_text)
        elif name == "back":
            self.button(rect, "BACK", self.mouse)
    self.text("Settings save automatically.", (WINDOW_W // 2 - 105, 648), 10, "muted")


KillZoneApp.draw_settings = _qol_draw_settings


def _qol_handle_settings_event(self, event):
    if event.type == pygame.QUIT:
        save_user_settings(self)
        self.running = False
        return
    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
        save_user_settings(self)
        self.state = "menu"
        return
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return
    clicked = next(
        (name for name, rect in self.settings_rects().items() if rect.collidepoint(event.pos)),
        None,
    )
    if clicked is None:
        return
    if clicked == "speed05":
        self.menu_speed = 0.5
    elif clicked == "speed1":
        self.menu_speed = 1.0
    elif clicked == "speed2":
        self.menu_speed = 2.0
    elif clicked == "help":
        self.menu_show_help = not self.menu_show_help
    elif clicked == "audio":
        self.audio_enabled = not self.audio_enabled
    elif clicked == "fps":
        self.show_fps = not self.show_fps
    elif clicked == "perf":
        self.show_perf = not self.show_perf
    elif clicked == "fpscap":
        caps = (0, 60, 120, 240)
        self.fps_cap = caps[(caps.index(self.fps_cap) + 1) % len(caps)]
    elif clicked == "fullscreen":
        self.cycle_display_mode()
    elif clicked == "uiscale":
        index = min(range(len(UI_SCALE_CHOICES)), key=lambda i: abs(UI_SCALE_CHOICES[i] - self.ui_scale))
        self.ui_scale = UI_SCALE_CHOICES[(index + 1) % len(UI_SCALE_CHOICES)]
        _qol_clear_text_caches(self)
    elif clicked == "largetext":
        self.large_text = not self.large_text
        _qol_clear_text_caches(self)
    elif clicked == "back":
        self.state = "menu"
    save_user_settings(self)


KillZoneApp.handle_settings_event = _qol_handle_settings_event


_qol_previous_set_display_mode = KillZoneApp.set_display_mode


def _qol_set_display_mode(self, mode):
    result = _qol_previous_set_display_mode(self, mode)
    save_user_settings(self)
    return result


KillZoneApp.set_display_mode = _qol_set_display_mode


_qol_accessibility_previous_handle_key = KillZoneApp.handle_key


def _qol_accessibility_handle_key(self, key, mods):
    result = _qol_accessibility_previous_handle_key(self, key, mods)
    if key == pygame.K_F9:
        save_user_settings(self)
    return result


KillZoneApp.handle_key = _qol_accessibility_handle_key


# -----------------------------------------------------------------------------
# Fullscreen input coordinates
# -----------------------------------------------------------------------------
# Mouse events are expressed in window coordinates, while the game always draws
# to its fixed logical canvas.  Keep the conversion at the outer input boundary
# and mark converted events so the historical run loop cannot scale them twice.

_FULLSCREEN_LOGICAL_EVENT_FLAG = "_killzone_logical_position"


def _fullscreen_input_display_size(self):
    """Return the coordinate extent used by SDL mouse events."""
    try:
        display_surface = pygame.display.get_surface()
        if display_surface is self.window:
            width, height = pygame.display.get_window_size()
            if width > 0 and height > 0:
                return width, height
    except (AttributeError, pygame.error):
        pass
    try:
        width, height = self.window.get_size()
    except (AttributeError, pygame.error):
        return WINDOW_W, WINDOW_H
    if width <= 0 or height <= 0:
        return WINDOW_W, WINDOW_H
    return width, height


KillZoneApp.input_display_size = _fullscreen_input_display_size


def _fullscreen_display_to_logical(self, pos):
    width, height = self.input_display_size()
    return (
        int(clamp(pos[0] * WINDOW_W / width, 0, WINDOW_W - 1)),
        int(clamp(pos[1] * WINDOW_H / height, 0, WINDOW_H - 1)),
    )


KillZoneApp.display_to_logical = _fullscreen_display_to_logical


def _fullscreen_normalize_event_pos(self, event):
    event_data = getattr(event, "dict", None)
    if isinstance(event_data, dict) and event_data.get(_FULLSCREEN_LOGICAL_EVENT_FLAG):
        return event
    if getattr(event, _FULLSCREEN_LOGICAL_EVENT_FLAG, False):
        return event
    if not hasattr(event, "pos"):
        return event

    logical_pos = self.display_to_logical(event.pos)
    try:
        event.pos = logical_pos
    except (AttributeError, TypeError):
        if isinstance(event_data, dict):
            event_data["pos"] = logical_pos

    if isinstance(event_data, dict):
        event_data[_FULLSCREEN_LOGICAL_EVENT_FLAG] = True
    else:
        try:
            setattr(event, _FULLSCREEN_LOGICAL_EVENT_FLAG, True)
        except (AttributeError, TypeError):
            pass
    return event


KillZoneApp.normalize_event_pos = _fullscreen_normalize_event_pos


_fullscreen_previous_handle_event = KillZoneApp.handle_event


def _fullscreen_handle_event(self, event):
    event = self.normalize_event_pos(event)
    if event.type == pygame.MOUSEMOTION:
        self.mouse = event.pos
    return _fullscreen_previous_handle_event(self, event)


KillZoneApp.handle_event = _fullscreen_handle_event


# =============================================================================
# BATTLEFIELD AUDIO / READABILITY PASS
# =============================================================================

TACTICAL_AUDIO_VOLUMES = {
    "select": 0.10,
    "command": 0.14,
    "deny": 0.15,
    "contact": 0.16,
    "warning": 0.19,
    "casualty": 0.18,
    "objective": 0.18,
}


def battlefield_status_badge(unit, game_time=0.0):
    """Return the highest-priority compact battlefield status for a unit."""
    morale_state = getattr(unit, "morale_state", "STEADY")
    if unit.order == "rout" or morale_state in ("BREAKING", "ROUTING"):
        return "BREAK", "danger"
    if morale_state == "PINNED" or unit.suppression >= 80:
        return "PIN", "suppression"
    if unit.order == "medic":
        return "AID", "good"
    if unit.carrying_uid is not None or unit.dragging_uid is not None:
        return "CASEVAC", "objective"
    if unit.casualty == "wounded" or unit.hp < unit.max_hp * 0.6:
        return "WND", "danger"
    if unit.jammed:
        return "JAM", "danger"
    if unit.ammo <= 0 and not unit.magazines:
        return "NO AMMO", "danger"
    if unit.reload_timer > 0:
        return "RLD", "blue"
    if unit.ammo <= 0:
        return "EMPTY", "objective"
    if game_time < getattr(unit, "disoriented_until", 0.0):
        return "CON", "contact"
    return None


def offscreen_indicator_point(rect, point, margin=14):
    """Intersect a direction from the viewport centre with its inset edge."""
    if rect.collidepoint(point):
        return None
    inner = rect.inflate(-margin * 2, -margin * 2)
    center_x, center_y = rect.center
    delta_x = point[0] - center_x
    delta_y = point[1] - center_y
    scales = []
    if delta_x > 0:
        scales.append((inner.right - center_x) / delta_x)
    elif delta_x < 0:
        scales.append((inner.left - center_x) / delta_x)
    if delta_y > 0:
        scales.append((inner.bottom - center_y) / delta_y)
    elif delta_y < 0:
        scales.append((inner.top - center_y) / delta_y)
    positive = [scale for scale in scales if scale >= 0]
    if not positive:
        return inner.center, 0.0
    scale = min(positive)
    return (
        (round(center_x + delta_x * scale), round(center_y + delta_y * scale)),
        math.atan2(delta_y, delta_x),
    )


def battle_audio_cue_for_event(event):
    kind = event.get("kind", "")
    text = event.get("text", "").lower()
    if kind == "casualty":
        return "casualty" if text.startswith("player ") else None
    if kind in ("counterattack",):
        return "warning"
    if kind == "reserve":
        return "warning" if "enemy" in text else "command"
    if kind == "surrender":
        return "casualty" if "player" in text else "objective"
    if kind in ("objective", "collapse", "victory"):
        return "objective"
    if kind == "mission":
        return "contact"
    return None


def battlefield_event_style(event):
    kind = event.get("kind", "")
    text = event.get("text", "").lower()
    if kind == "casualty" and text.startswith("player "):
        return "CASUALTY", "danger"
    if kind == "counterattack":
        return "COUNTERATTACK", "danger"
    if kind == "reserve":
        return ("ENEMY RESERVE", "danger") if "enemy" in text else ("RESERVES", "select")
    if kind == "objective":
        return "OBJECTIVE", "good"
    if kind == "collapse":
        return "LINE BREAK", "good"
    if kind == "victory":
        return "VICTORY", "good"
    if kind == "surrender" and "player" not in text:
        return "SURRENDER", "good"
    return None


def _feedback_make_pcm_sound(self, kind):
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
        randomizer = random.Random(8100 + sum(ord(character) for character in kind))
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
                gate = 1.0 if progress < 0.34 or progress > 0.50 else 0.0
                value = math.sin(math.tau * frequency * seconds) * envelope * gate
            elif kind == "deny":
                frequency = 280 - 105 * progress
                value = math.sin(math.tau * frequency * seconds) * envelope
            elif kind == "contact":
                filtered_noise = filtered_noise * 0.72 + (randomizer.random() * 2 - 1) * 0.28
                tone = math.sin(math.tau * 430 * seconds) * (1.0 if 0.18 < progress < 0.72 else 0.0)
                value = (filtered_noise * 0.52 + tone * 0.28) * envelope
            elif kind == "warning":
                gate = 1.0 if int(progress * 5) % 2 == 0 else 0.22
                value = math.sin(math.tau * 235 * seconds) * envelope * gate
            elif kind == "casualty":
                frequency = 330 if progress < 0.45 else 205
                gate = 1.0 if progress < 0.34 or progress > 0.52 else 0.12
                value = math.sin(math.tau * frequency * seconds) * envelope * gate
            else:  # objective
                frequency = 420 + 430 * progress
                harmonic = math.sin(math.tau * frequency * seconds)
                value = (harmonic + 0.35 * math.sin(math.tau * frequency * 1.5 * seconds)) * envelope
            sample = int(clamp(value, -1, 1) * 20000)
            if abs(bits) == 16:
                packed = struct.pack("<h", sample)
            else:
                packed = bytes([int(clamp(128 + sample / 256, 0, 255))])
            buffer.extend(packed * channels)
        return pygame.mixer.Sound(buffer=bytes(buffer))
    except Exception:
        return None


KillZoneApp.make_tactical_pcm_sound = _feedback_make_pcm_sound


def _feedback_ensure_audio(self):
    if not getattr(self, "audio_enabled", False):
        return
    if not hasattr(self, "_tactical_audio"):
        self._tactical_audio = {}
    for kind in TACTICAL_AUDIO_VOLUMES:
        if kind not in self._tactical_audio:
            sound = self.make_tactical_pcm_sound(kind)
            if sound is not None:
                self._tactical_audio[kind] = sound


KillZoneApp.ensure_tactical_audio = _feedback_ensure_audio


def _feedback_play_sound(self, kind):
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


KillZoneApp.play_tactical_sound = _feedback_play_sound


_feedback_previous_app_init = KillZoneApp.__init__


def _feedback_app_init(self):
    _feedback_previous_app_init(self)
    self._tactical_audio = {}
    self._tactical_audio_last = {}
    self._tactical_audio_game = id(self.game)
    self._tactical_audio_last_event = self.game.battle_events[-1] if self.game.battle_events else None
    self._tactical_audio_last_event_time = (
        self.game.battle_events[-1].get("time", -99.0) if self.game.battle_events else -99.0
    )
    self._tactical_audio_stage = getattr(self.game, "battle_stage", "APPROACH")
    self.ensure_tactical_audio()


KillZoneApp.__init__ = _feedback_app_init


def _feedback_poll_battle_audio(self):
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
            (index for index, event in enumerate(events) if event.get("time", -99.0) > last_event_time),
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
        cue = {"CONTACT": "contact", "ASSAULT": "command", "COLLAPSE": "objective"}.get(stage)
        if cue:
            self.play_tactical_sound(cue)
        self._tactical_audio_stage = stage


KillZoneApp.poll_tactical_audio = _feedback_poll_battle_audio


_feedback_previous_update_ambience = KillZoneApp.update_ambience


def _feedback_update_ambience(self):
    result = _feedback_previous_update_ambience(self)
    if self.state in ("deployment", "game"):
        self.poll_tactical_audio()
    return result


KillZoneApp.update_ambience = _feedback_update_ambience


_feedback_previous_notify = _qol_notify


def _qol_notify(app, text, kind="info", duration=1.8):
    _feedback_previous_notify(app, text, kind=kind, duration=duration)
    if not hasattr(app, "play_tactical_sound"):
        return
    lowered = text.lower()
    if kind == "danger":
        cue = "deny"
    elif "selected" in lowered:
        cue = "select"
    elif any(word in lowered for word in ("confirmed", "ready", "assigned", "cancelled")) or ":" in text:
        cue = "command"
    else:
        return
    app.play_tactical_sound(cue)


_feedback_previous_draw_unit = KillZoneApp.draw_unit


def _feedback_draw_unit(self, unit):
    _feedback_previous_draw_unit(self, unit)
    if unit.faction != "player" or not unit.combat_effective:
        return
    badge = battlefield_status_badge(unit, self.game.time)
    if badge is None:
        return
    center_x, center_y = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(40, 40).collidepoint((center_x, center_y)):
        return
    label, color_key = badge
    surface = self.cached_text_surface(label, 8, "black")
    width = max(25, surface.get_width() + 10)
    height = 13
    y = center_y - max(33, int(self.tile_px * 1.08))
    rect = pygame.Rect(center_x - width // 2, y - height // 2, width, height)
    pygame.draw.rect(self.screen, COLORS[color_key], rect, border_radius=3)
    pygame.draw.rect(self.screen, COLORS["black"], rect, 1, border_radius=3)
    self.screen.blit(surface, (rect.centerx - surface.get_width() // 2, rect.centery - surface.get_height() // 2))


KillZoneApp.draw_unit = _feedback_draw_unit


def _feedback_draw_edge_arrow(self, world_screen_pos, color, label=None):
    indicator = offscreen_indicator_point(self.map_view_rect(), world_screen_pos)
    if indicator is None:
        return False
    (center_x, center_y), angle = indicator
    direction_x, direction_y = math.cos(angle), math.sin(angle)
    perpendicular_x, perpendicular_y = -direction_y, direction_x
    tip = (round(center_x + direction_x * 8), round(center_y + direction_y * 8))
    back_x, back_y = center_x - direction_x * 6, center_y - direction_y * 6
    left = (round(back_x + perpendicular_x * 5), round(back_y + perpendicular_y * 5))
    right = (round(back_x - perpendicular_x * 5), round(back_y - perpendicular_y * 5))
    pygame.draw.polygon(self.screen, color, (tip, left, right))
    pygame.draw.polygon(self.screen, COLORS["black"], (tip, left, right), 1)
    if label:
        surface = self.cached_text_surface(label, 8, "white")
        label_x = round(center_x - direction_x * 17 - surface.get_width() / 2)
        label_y = round(center_y - direction_y * 17 - surface.get_height() / 2)
        self.screen.blit(surface, (label_x, label_y))
    return True


KillZoneApp.draw_edge_arrow = _feedback_draw_edge_arrow


def _feedback_draw_readability(self):
    map_rect = self.map_view_rect()
    active_badges = []
    for unit in self.selected_units()[:16]:
        status = battlefield_status_badge(unit, self.game.time)
        if status and status[0] not in active_badges:
            active_badges.append(status[0])
        screen_pos = self.world_to_screen(unit.x, unit.y)
        if not map_rect.collidepoint(screen_pos):
            color = squad_visual_color(getattr(unit, "squad_id", 1))
            self.draw_edge_arrow(screen_pos, color, str(getattr(unit, "squad_id", 1)))

    for event in getattr(self.game, "battle_events", [])[-20:]:
        style = battlefield_event_style(event)
        position = event.get("pos")
        age = self.game.time - event.get("time", -99.0)
        if style is None or position is None or not 0 <= age <= 4.0:
            continue
        label, color_key = style
        color = COLORS[color_key]
        screen_pos = self.world_to_screen(*position)
        if not map_rect.collidepoint(screen_pos):
            self.draw_edge_arrow(screen_pos, color, "!")
            continue
        radius = 12 + int(age * 3)
        pygame.draw.circle(self.screen, color, screen_pos, radius, 2 if age < 1.5 else 1)
        text_surface = self.cached_text_surface(label, 8, color_key)
        text_x = int(clamp(screen_pos[0] + 12, map_rect.left + 4, map_rect.right - text_surface.get_width() - 4))
        text_y = int(clamp(screen_pos[1] - 18, map_rect.top + 4, map_rect.bottom - 14))
        self.screen.blit(text_surface, (text_x, text_y))

    if active_badges:
        legend = "STATUS  " + " · ".join(active_badges[:5])
        surface = self.cached_text_surface(legend, 8, "white")
        rect = pygame.Rect(map_rect.left + 7, map_rect.bottom - 22, surface.get_width() + 14, 16)
        pygame.draw.rect(self.screen, (25, 28, 24), rect, border_radius=3)
        pygame.draw.rect(self.screen, COLORS["muted"], rect, 1, border_radius=3)
        self.screen.blit(surface, (rect.x + 7, rect.y + 3))


KillZoneApp.draw_battlefield_readability = _feedback_draw_readability


_feedback_previous_draw_map = KillZoneApp.draw_map


def _feedback_draw_map(self):
    _feedback_previous_draw_map(self)
    if self.state in ("deployment", "game"):
        self.draw_battlefield_readability()


KillZoneApp.draw_map = _feedback_draw_map


# =============================================================================
# FIRE WHILE MOVING
# =============================================================================

MOVING_FIRE_ACCURACY_PENALTY = 28.0
MOVING_FIRE_EXCLUDED_ROLES = frozenset(("HMG Crew", "Mortar Team"))


def unit_is_firing_while_moving(unit):
    return bool(
        getattr(unit, "_moving_fire_active", False)
        or (unit.order == "move" and (unit.path or unit.waypoints))
    )


def _moving_fire_can_attempt(self, unit):
    morale_state = getattr(unit, "morale_state", "STEADY")
    return bool(
        unit.combat_effective
        and unit.order == "move"
        and unit.role not in MOVING_FIRE_EXCLUDED_ROLES
        and unit.fire_discipline != "hold"
        and unit.ammo > 0
        and not unit.jammed
        and unit.reload_timer <= 0
        and unit.action_timer <= 0
        and unit.carrying_uid is None
        and unit.dragging_uid is None
        and unit.suppression < 80
        and morale_state not in ("PINNED", "BREAKING", "ROUTING")
        and unit.heat < 100
        and self.time >= unit.next_shot
        and self.time >= unit.command_delay_until
    )


RealTimeGame.can_attempt_moving_fire = _moving_fire_can_attempt


def _moving_fire_target(self, unit):
    if unit.fire_discipline == "return":
        if unit.under_fire_until <= self.time or not unit.last_attacker_uid:
            return None
        candidate = self.get_unit(unit.last_attacker_uid)
        enemy_faction = "enemy" if unit.faction == "player" else "player"
        if (
            candidate is not None
            and candidate.faction == enemy_faction
            and candidate.combat_effective
            and self.visible_to(unit.faction, candidate)
            and self.can_see(unit, candidate)
            and dist(unit, candidate) <= unit.weapon["range"]
        ):
            return candidate
        return None
    if unit.fire_discipline in ("free", "confident"):
        return self.choose_auto_target(unit)
    return None


RealTimeGame.moving_fire_target = _moving_fire_target


def _moving_fire_attempt(self, unit):
    if not self.can_attempt_moving_fire(unit):
        return False
    unit._moving_fire_active = True
    previous_mode = unit.fire_mode
    try:
        target = self.moving_fire_target(unit)
        if target is None:
            return False
        # A previous aimed/rapid order must not leak into a maneuvering shot.
        # Moving fire uses the normal cadence and pays its own explicit penalty.
        unit.fire_mode = "normal"
        if unit.fire_discipline == "confident" and self.hit_chance(unit, target) < 60:
            return False
        ammunition_before = unit.ammo
        self.perform_shot(unit, target)
        return unit.ammo < ammunition_before
    finally:
        unit.fire_mode = previous_mode
        unit._moving_fire_active = False


RealTimeGame.try_moving_fire = _moving_fire_attempt


_moving_fire_previous_hit_chance = RealTimeGame.hit_chance


def _moving_fire_hit_chance(self, attacker, target, mode=None, reaction=False):
    chance = _moving_fire_previous_hit_chance(self, attacker, target, mode=mode, reaction=reaction)
    if chance <= 0 or not unit_is_firing_while_moving(attacker):
        return chance
    return clamp(chance - MOVING_FIRE_ACCURACY_PENALTY, 2, 96)


RealTimeGame.hit_chance = _moving_fire_hit_chance


_moving_fire_previous_shot_breakdown = RealTimeGame.shot_breakdown


def _moving_fire_shot_breakdown(self, attacker, target, mode=None, reaction=False):
    breakdown = _moving_fire_previous_shot_breakdown(
        self,
        attacker,
        target,
        mode=mode,
        reaction=reaction,
    )
    if unit_is_firing_while_moving(attacker) and breakdown.get("chance", 0) > 0:
        breakdown.setdefault("mods", []).append(
            ("firing while moving", -MOVING_FIRE_ACCURACY_PENALTY)
        )
    return breakdown


RealTimeGame.shot_breakdown = _moving_fire_shot_breakdown


_moving_fire_previous_update_unit = RealTimeGame.update_unit


def _moving_fire_update_unit(self, unit, dt):
    moving_before = unit.order == "move"
    position_before = unit.pos
    _moving_fire_previous_update_unit(self, unit, dt)

    # A jam affects the weapon, not the soldier's legs. The older unit loop
    # returns before movement when jammed, so preserve an existing move order.
    if (
        moving_before
        and unit.order == "move"
        and unit.jammed
        and unit.combat_effective
        and unit.pos == position_before
    ):
        self.update_movement(unit, dt)

    moved = dist(position_before, unit.pos) > 1e-6
    if moving_before and moved and unit.order == "move":
        self.try_moving_fire(unit)


RealTimeGame.update_unit = _moving_fire_update_unit


# =============================================================================
# OPERATIONS & ENGINEERING EXPANSION
# =============================================================================

# Construction is intentionally free in this update.  Build times, emplacement
# caps and enemy cooldowns are temporary guardrails until supplies/logistics can
# become the single source of construction cost in the next balance pass.
OPERATION_MISSIONS = ("assault", "defense")
OPERATION_VARIANTS = ("auto", "farmland", "wooded_ridge", "ruined_village", "hill_line")
OPERATION_WEATHER = ("auto", "clear", "rain", "fog")
OPERATION_ENEMY_STRENGTHS = (0.8, 1.0, 1.25)
OPERATION_DEFENSE_DURATIONS = (180, 300, 420)
SQUAD_DOCTRINES = ("cautious", "balanced", "aggressive")
STATIC_WEAPON_ROLES = frozenset(("MG Emplacement", "Field Gun", "Artillery Battery"))

WEAPONS.update(
    {
        "Emplaced Machine Gun": {
            "range": 17.0,
            "damage": 36,
            "acc": 64,
            "supp": 72,
            "rpm": 470,
            "mag": 160,
            "reload": 7.0,
            "heat": 7,
            "cool": 13,
            "pen": 4,
        },
        "Field Gun": {
            "range": 21.0,
            "damage": 118,
            "acc": 69,
            "supp": 82,
            "rpm": 13,
            "mag": 8,
            "reload": 6.5,
            "heat": 5,
            "cool": 18,
            "pen": 9,
        },
    }
)
ROLES.update(
    {
        "MG Emplacement": {
            "hp": 185,
            "weapon": "Emplaced Machine Gun",
            "speed": 0.01,
            "spot": 12.0,
            "mags": 3,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 2,
        },
        "Field Gun": {
            "hp": 220,
            "weapon": "Field Gun",
            "speed": 0.01,
            "spot": 12.5,
            "mags": 3,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 3,
        },
        "Artillery Battery": {
            "hp": 195,
            "weapon": "Carbine",
            "speed": 0.01,
            "spot": 8.0,
            "mags": 2,
            "grenades": 0,
            "smoke": 0,
            "rifle_grenades": 0,
            "satchel": 0,
            "crew": 4,
        },
    }
)
ROLE_CONTACT.update(
    {
        "MG Emplacement": "MG NEST",
        "Field Gun": "FIELD GUN",
        "Artillery Battery": "ARTILLERY",
    }
)

ENGINEER_BUILD_TYPES = {
    "sandbags": {
        "label": "SANDBAGS",
        "description": "Protected firing position · 4 sec",
        "seconds": 4.0,
        "terrain": "sandbags",
    },
    "wire": {
        "label": "WIRE",
        "description": "Slows an assault and marks a barrier · 4 sec",
        "seconds": 4.0,
        "terrain": "wire",
    },
    "trench": {
        "label": "TRENCH",
        "description": "Durable infantry cover · 7 sec",
        "seconds": 7.0,
        "terrain": "trench",
    },
    "mg_nest": {
        "label": "MG TURRET",
        "description": "Direct-fire suppression emplacement · 8 sec",
        "seconds": 8.0,
        "role": "MG Emplacement",
    },
    "field_gun": {
        "label": "FIELD GUN",
        "description": "Slow, powerful direct-fire weapon · 10 sec",
        "seconds": 10.0,
        "role": "Field Gun",
    },
    "artillery": {
        "label": "ARTILLERY",
        "description": "Long-range indirect HE battery · 12 sec",
        "seconds": 12.0,
        "role": "Artillery Battery",
    },
}


def default_operation_config():
    return {
        "mission": "assault",
        "variant": "auto",
        "weather": "auto",
        "enemy_strength": 1.0,
        "defense_duration": 300,
    }


def sanitize_operation_config(config=None):
    cleaned = default_operation_config()
    if config:
        cleaned.update(config)
    if cleaned["mission"] not in OPERATION_MISSIONS:
        cleaned["mission"] = "assault"
    if cleaned["variant"] not in OPERATION_VARIANTS:
        cleaned["variant"] = "auto"
    if cleaned["weather"] not in OPERATION_WEATHER:
        cleaned["weather"] = "auto"
    cleaned["enemy_strength"] = min(
        OPERATION_ENEMY_STRENGTHS,
        key=lambda value: abs(value - float(cleaned["enemy_strength"])),
    )
    cleaned["defense_duration"] = min(
        OPERATION_DEFENSE_DURATIONS,
        key=lambda value: abs(value - int(cleaned["defense_duration"])),
    )
    return cleaned


_operation_previous_generate_map = RealTimeGame.generate_map


def _operation_generate_map(self):
    requested = getattr(self, "operation_variant", "auto")
    if requested == "auto":
        return _operation_previous_generate_map(self)

    # The established generator selects its variant from seed modulo four.
    # Temporarily adjust only that selector while retaining the user's seed as
    # the battle/replay identity shown in the UI and AAR.
    original_seed = self.seed
    variants = list(MISSION_VARIANTS)
    self.seed = original_seed - original_seed % len(variants) + variants.index(requested)
    try:
        _operation_previous_generate_map(self)
    finally:
        self.seed = original_seed
    self.battle_variant = requested
    self.map_features["variant"] = requested


RealTimeGame.generate_map = _operation_generate_map


def _operation_open_position(game, desired_x, desired_y, unit, radius=8):
    desired_x = int(clamp(desired_x, 1, MAP_W - 2))
    desired_y = int(clamp(desired_y, 1, MAP_H - 2))
    occupied = {other.tile for other in game.units if other.alive and other.uid != unit.uid}
    choices = []
    for radius_now in range(radius + 1):
        for y in range(max(1, desired_y - radius_now), min(MAP_H - 1, desired_y + radius_now + 1)):
            for x in range(max(1, desired_x - radius_now), min(MAP_W - 1, desired_x + radius_now + 1)):
                if max(abs(x - desired_x), abs(y - desired_y)) != radius_now:
                    continue
                if (x, y) in occupied or not game.passable(x, y, unit):
                    continue
                cover = TERRAIN[game.grid[y][x].terrain]["cover"]
                choices.append((-cover, abs(x - desired_x) + abs(y - desired_y), x, y))
        if choices:
            break
    if not choices:
        return None
    choices.sort()
    return choices[0][2], choices[0][3]


def _operation_scale_enemy_force(self):
    enemies = [unit for unit in self.units if unit.faction == "enemy"]
    target = max(4, int(round(len(enemies) * self.operation_enemy_strength)))
    if target < len(enemies):
        remove_ids = {unit.uid for unit in sorted(enemies, key=lambda item: item.uid, reverse=True)[: len(enemies) - target]}
        self.units = [unit for unit in self.units if unit.uid not in remove_ids]
    elif target > len(enemies):
        pool = (
            "Rifleman",
            "Assault",
            "Automatic Rifleman",
            "Grenadier",
            "Machine Gunner",
            "Engineer",
            "Medic",
            "Marksman",
        )
        for index in range(target - len(enemies)):
            role = pool[(len(enemies) + index) % len(pool)]
            self.add_unit("enemy", role, self.primary_line_x, 3 + index % (MAP_H - 6))
    _kz_rebuild_indexes(self)


def _operation_place_force(self, units, x_values, facing):
    for index, unit in enumerate(units):
        desired_x = x_values[index % len(x_values)]
        desired_y = 2 + ((index * 5 + index // 3) % (MAP_H - 4))
        placed = _operation_open_position(self, desired_x, desired_y, unit)
        if placed:
            unit.x, unit.y = placed
        unit.facing = facing
        unit.path = []
        unit.waypoints = []
        unit.command_queue = []
        unit.order = "idle"
        unit.overwatch = False
        unit.fire_lane = False


def _operation_configure_defense(self):
    players = [unit for unit in self.units if unit.faction == "player"]
    enemies = [unit for unit in self.units if unit.faction == "enemy"]
    self.deployment_zone_side = "east"
    self.defense_deployment_x = max(self.primary_line_x - 3, MAP_W - 18)
    self.rally_points = {
        "player": self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2)),
        "enemy": (2, MAP_H // 2),
    }
    _operation_place_force(self, players, (self.primary_line_x, self.primary_line_x + 1, self.secondary_line_x), 180)
    _operation_place_force(self, enemies, (3, 5, 7, 9), 0)

    ordered = sorted(enemies, key=lambda unit: unit.uid)
    first = max(1, int(math.ceil(len(ordered) * 0.46)))
    second = max(first + 1, int(math.ceil(len(ordered) * 0.74)))
    for index, unit in enumerate(ordered):
        wave = 1 if index < first else 2 if index < second else 3
        unit.attack_wave = wave
        unit.initial_battle_role = f"wave{wave}"
        unit.battle_role = "assault"
        unit.plan_state = "attack" if wave == 1 else "reserve"
        unit.reserve_active = wave == 1
        unit.battle_sector = _vs_sector_name(unit.y)
        unit.fallback_point = (2, int(clamp(round(unit.y), 2, MAP_H - 3)))

    command_post = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
    strongpoint = self.map_features.get("strongpoint", (self.primary_line_x + 2, MAP_H // 2))
    self.objectives = [
        {
            "title": "HOLD THE FORWARD LINE",
            "desc": "Deny the eastern trench line through the opening assault.",
            "pos": (self.primary_line_x, MAP_H // 2),
            "progress": 0.0,
            "state": "active",
        },
        {
            "title": "HOLD THE STRONGPOINT",
            "desc": "Prevent the second wave from overrunning the central bunker.",
            "pos": strongpoint,
            "progress": 0.0,
            "state": "locked",
        },
        {
            "title": "PROTECT THE COMMAND POST",
            "desc": "Survive the final assault and retain the rear command bunker.",
            "pos": command_post,
            "progress": 0.0,
            "state": "locked",
        },
    ]
    self.objective_index = 0
    self.defense_elapsed = 0.0
    self.defense_capture_progress = 0.0
    self.defense_wave_announced = {1}
    self._defense_last_minute = int(math.ceil(self.defense_time_limit / 60))
    self.battle_stage = "PREPARATION"
    self.mission_title = f"DEFENSE — {MISSION_VARIANTS[self.battle_variant]['name']}"
    self.mission_brief = (
        "Hold the eastern defensive system against three escalating enemy waves. "
        "Engineers can improve the position before and during contact."
    )
    # Remove the assault mission banner/event installed by the shared vertical
    # slice before replacing it with the defense-specific operation.
    self.notifications = []
    self.battle_events = [event for event in self.battle_events if event.get("kind") != "mission"]
    self.notify("MISSION — Hold the defensive line", kind="objective", duration=5.0)
    self._vs_event("mission", self.mission_title, (self.primary_line_x, MAP_H // 2))
    _kz_rebuild_indexes(self)


def _operation_refresh_force_counts(self):
    enemies = [unit for unit in self.units if unit.faction == "enemy"]
    self.initial_enemy_total = max(1, len(enemies))
    self.initial_mobile_enemy_total = max(
        1,
        len([unit for unit in enemies if unit.role not in STATIC_WEAPON_ROLES]),
    )
    self.initial_role_counts = {
        role: max(1, len([unit for unit in enemies if getattr(unit, "initial_battle_role", "") == role]))
        for role in ("forward", "reserve", "command", "wave1", "wave2", "wave3")
    }
    self.initial_sector_counts = {
        sector: max(
            1,
            len(
                [
                    unit
                    for unit in enemies
                    if getattr(unit, "battle_sector", "") == sector
                    and (
                        self.mission_type == "defense"
                        or getattr(unit, "initial_battle_role", "") == "forward"
                    )
                ]
            ),
        )
        for sector in ("NORTH", "CENTRE", "SOUTH")
    }
    estimate = len(enemies)
    self.enemy_estimate = (max(1, estimate - 2), estimate + 2)


_operation_previous_init = RealTimeGame.__init__


def _operation_init(
    self,
    seed: Optional[int] = None,
    difficulty: str = "Hard",
    player_roster: Optional[List[str]] = None,
    reserve_count: int = 0,
    operation_config=None,
):
    config = sanitize_operation_config(operation_config)
    self.operation_config = config
    self.mission_type = config["mission"]
    self.operation_variant = config["variant"]
    self.operation_weather = config["weather"]
    self.operation_enemy_strength = config["enemy_strength"]
    self.defense_time_limit = float(config["defense_duration"])
    self.deployment_zone_side = "west"
    self.squad_doctrine = {}
    self._engineer_builder_timer = 0.0
    self._last_engineer_builder_update = 0.0
    self.construction_reservations = {}
    self._defense_attack_order_timer = 0.0
    _operation_previous_init(
        self,
        seed=seed,
        difficulty=difficulty,
        player_roster=player_roster,
        reserve_count=reserve_count,
    )
    if self.operation_weather != "auto":
        self.weather = self.operation_weather
        for index in range(len(self.log) - 1, -1, -1):
            if self.log[index].startswith("Realtime battle started."):
                self.log[index] = f"Realtime battle started. Seed {self.seed}. Weather: {self.weather}."
                break
    self._operation_scale_enemy_force()
    if self.mission_type == "defense":
        self._operation_configure_defense()
    self._operation_refresh_force_counts()
    for unit in self.units:
        squad = max(1, int(getattr(unit, "squad_id", 1)))
        key = (unit.faction, squad)
        if unit.faction == "enemy":
            role = getattr(unit, "initial_battle_role", "")
            default = "aggressive" if role.startswith("wave") else "cautious" if role in ("command", "reserve") else "balanced"
        else:
            default = "balanced"
        self.squad_doctrine.setdefault(key, default)


RealTimeGame.__init__ = _operation_init
RealTimeGame._operation_scale_enemy_force = _operation_scale_enemy_force
RealTimeGame._operation_configure_defense = _operation_configure_defense
RealTimeGame._operation_refresh_force_counts = _operation_refresh_force_counts
RealTimeGame._operation_place_force = _operation_place_force


def _operation_doctrine_for(self, unit):
    key = (unit.faction, max(1, int(getattr(unit, "squad_id", 1))))
    return self.squad_doctrine.get(key, "balanced")


def _operation_cycle_squad_doctrine(self, units):
    squads = sorted(
        {
            (unit.faction, max(1, int(getattr(unit, "squad_id", 1))))
            for unit in units
            if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
        }
    )
    if not squads:
        return None
    current = self.squad_doctrine.get(squads[0], "balanced")
    new_value = SQUAD_DOCTRINES[(SQUAD_DOCTRINES.index(current) + 1) % len(SQUAD_DOCTRINES)]
    for key in squads:
        self.squad_doctrine[key] = new_value
    self.add_log(f"Squad doctrine changed to {new_value}.")
    return new_value


RealTimeGame.doctrine_for = _operation_doctrine_for
RealTimeGame.cycle_squad_doctrine = _operation_cycle_squad_doctrine


_operation_previous_issue_move = RealTimeGame.issue_move


def _operation_issue_move(self, units, dest, append=False, mode=None, formation="spread"):
    movable = [unit for unit in units if unit.role not in STATIC_WEAPON_ROLES]
    if mode is None and movable:
        doctrines = {self.doctrine_for(unit) for unit in movable}
        if doctrines == {"cautious"}:
            mode = "safe"
        elif doctrines == {"aggressive"}:
            mode = "fast"
    return _operation_previous_issue_move(
        self,
        movable,
        dest,
        append=append,
        mode=mode,
        formation=formation,
    )


RealTimeGame.issue_move = _operation_issue_move


_operation_previous_can_moving_fire = RealTimeGame.can_attempt_moving_fire


def _operation_can_moving_fire(self, unit):
    if not _operation_previous_can_moving_fire(self, unit):
        return False
    doctrine = self.doctrine_for(unit)
    if doctrine == "cautious":
        return unit.under_fire_until > self.time
    if doctrine == "aggressive" and unit.suppression < 86:
        return True
    return unit.suppression < 80


RealTimeGame.can_attempt_moving_fire = _operation_can_moving_fire


_operation_previous_auto_behaviors = RealTimeGame.update_auto_behaviors


def _operation_auto_behaviors(self):
    aggressive = []
    for unit in self.living("player"):
        if self.doctrine_for(unit) == "aggressive" and unit.auto_cover:
            aggressive.append(unit)
            unit.auto_cover = False
    try:
        _operation_previous_auto_behaviors(self)
    finally:
        for unit in aggressive:
            unit.auto_cover = True

    for unit in self.living("player"):
        if not unit.combat_effective or self.doctrine_for(unit) != "cautious":
            continue
        if unit.order not in ("idle", "overwatch", "fire_lane", "fire"):
            continue
        if unit.auto_smoke and unit.smoke_grenades > 0 and unit.suppression > 62:
            if self.grid[unit.tile[1]][unit.tile[0]].smoke < 1.0:
                self.throw_grenade(unit, unit.pos, smoke=True)
                continue
        if unit.auto_cover and unit.suppression > 66:
            destination = self.find_nearby_cover(unit, 4)
            if destination and destination != unit.tile:
                self.issue_move([unit], destination, mode="safe", formation="column")


RealTimeGame.update_auto_behaviors = _operation_auto_behaviors


def _operation_static_count(self, faction):
    return sum(
        unit.faction == faction and unit.combat_effective and unit.role in STATIC_WEAPON_ROLES
        for unit in self.units
    )


def _operation_validate_build_site(self, faction, kind, pos, include_reservations=True):
    if kind not in ENGINEER_BUILD_TYPES:
        return False, "Unknown construction"
    if not self.in_bounds(*pos):
        return False, "Choose a tile inside the battlefield"
    pos = (int(pos[0]), int(pos[1]))
    if include_reservations and pos in self.construction_reservations:
        return False, "Another construction is already planned there"
    cell = self.grid[pos[1]][pos[0]]
    if self.unit_at(*pos) is not None:
        return False, "Construction tile is occupied"
    definition = ENGINEER_BUILD_TYPES[kind]
    queued_emplacements = sum(
        ENGINEER_BUILD_TYPES[reservation[1]].get("role") is not None
        for reservation in self.construction_reservations.values()
        if reservation[2] == faction
    )
    if (
        "role" in definition
        and self.static_emplacement_count(faction) + queued_emplacements >= 6
    ):
        return False, "Temporary emplacement cap reached (6)"
    if "role" in definition and cell.terrain not in (
        "open",
        "mud",
        "rubble",
        "crater",
        "foxhole",
        "trench",
        "sandbags",
        "hill",
    ):
        return False, "Static weapons require firm, open ground"
    if "terrain" in definition and cell.terrain not in (
        "open",
        "mud",
        "rubble",
        "crater",
        "foxhole",
    ):
        return False, "Defenses require clear ground"
    return True, ""


def _operation_can_build(self, engineer, kind, pos):
    if engineer.role != "Engineer" or not engineer.combat_effective:
        return False, "No combat-effective engineer is available"
    if engineer.action_timer > 0 or engineer.order == "build":
        return False, "Engineer is already occupied"
    if not self.in_bounds(*pos) or dist(engineer.pos, pos) > 2.2:
        return False, "Engineer has not reached the construction site"
    return self.validate_build_site(engineer.faction, kind, pos, include_reservations=False)


def _operation_builder_staging_position(self, engineer, pos):
    choices = []
    px, py = pos
    for radius in (1, 2):
        for y in range(max(1, py - radius), min(MAP_H - 1, py + radius + 1)):
            for x in range(max(1, px - radius), min(MAP_W - 1, px + radius + 1)):
                if max(abs(x - px), abs(y - py)) != radius:
                    continue
                if not self.passable(x, y, engineer):
                    continue
                choices.append((math.hypot(x - engineer.x, y - engineer.y), x, y))
        if choices:
            break
    if not choices:
        return None
    choices.sort()
    return choices[0][1], choices[0][2]


def _operation_queue_construction(self, faction, kind, pos, preferred_engineers=None):
    pos = (int(pos[0]), int(pos[1]))
    valid, reason = self.validate_build_site(faction, kind, pos)
    if not valid:
        return None, reason
    engineers = [
        unit
        for unit in self.living(faction)
        if unit.role == "Engineer"
        and unit.combat_effective
        and unit.action_timer <= 0
        and not getattr(unit, "_construction_queued", False)
        and unit.order != "build"
    ]
    if not engineers:
        return None, "No available engineer can take this project"
    preferred_ids = {unit.uid for unit in (preferred_engineers or [])}
    engineers.sort(key=lambda unit: (0 if unit.uid in preferred_ids else 1, dist(unit.pos, pos)))
    assignment = None
    for engineer in engineers:
        staging = self.builder_staging_position(engineer, pos)
        if staging is None:
            continue
        path = self.find_path(engineer, staging, "safe") if engineer.tile != staging else []
        if engineer.tile != staging and not path:
            continue
        assignment = engineer, staging
        break
    if assignment is None:
        return None, "No engineer can reach an adjacent build position"

    engineer, staging = assignment
    engineer._construction_queued = True
    engineer._construction_kind = kind
    engineer._construction_pos = pos
    engineer._construction_staging = staging
    engineer.target_pos = pos
    engineer.command_queue = []
    self.construction_reservations[pos] = (engineer.uid, kind, faction)
    self.issue_move([engineer], staging, mode="safe", formation="column")
    self.notify(
        f"ENGINEER EN ROUTE — {ENGINEER_BUILD_TYPES[kind]['label']}",
        kind="good" if faction == "player" else "danger",
        duration=3.0,
    )
    return engineer, ""


def _operation_cancel_construction_assignment(self, engineer, reason=None):
    pos = getattr(engineer, "_construction_pos", None)
    if pos is not None:
        reservation = self.construction_reservations.get(pos)
        if reservation and reservation[0] == engineer.uid:
            self.construction_reservations.pop(pos, None)
    engineer._construction_queued = False
    engineer._construction_kind = None
    engineer._construction_pos = None
    engineer._construction_staging = None
    engineer.target_pos = None
    if reason and engineer.faction == "player":
        self.notify(reason, kind="danger", duration=2.5)


def _operation_update_engineer_assignments(self):
    for engineer in list(self.units):
        if not getattr(engineer, "_construction_queued", False):
            continue
        if not engineer.combat_effective:
            self.cancel_construction_assignment(engineer, "Construction cancelled — engineer unavailable")
            continue
        kind = getattr(engineer, "_construction_kind", None)
        pos = getattr(engineer, "_construction_pos", None)
        if kind not in ENGINEER_BUILD_TYPES or pos is None:
            self.cancel_construction_assignment(engineer)
            continue
        valid, reason = self.validate_build_site(
            engineer.faction,
            kind,
            pos,
            include_reservations=False,
        )
        if not valid:
            self.cancel_construction_assignment(engineer, f"Construction cancelled — {reason.lower()}")
            continue
        if dist(engineer.pos, pos) <= 2.2:
            engineer._construction_queued = False
            started, reason = self.begin_construction(engineer, kind, pos)
            if not started:
                self.cancel_construction_assignment(engineer, f"Construction delayed — {reason.lower()}")
            continue
        if engineer.order == "move" and (engineer.path or engineer.waypoints):
            continue
        staging = self.builder_staging_position(engineer, pos)
        if staging is None:
            self.cancel_construction_assignment(engineer, "Construction cancelled — site cannot be approached")
            continue
        engineer._construction_staging = staging
        self.issue_move([engineer], staging, mode="safe", formation="column")


def _operation_begin_construction(self, engineer, kind, pos):
    valid, reason = self.can_build(engineer, kind, pos)
    if not valid:
        return False, reason
    definition = ENGINEER_BUILD_TYPES[kind]
    engineer._construction_kind = kind
    engineer._construction_pos = (int(pos[0]), int(pos[1]))
    engineer.action_timer = float(definition["seconds"])
    engineer.order = "build"
    engineer.target_pos = engineer._construction_pos
    engineer.path = []
    engineer.waypoints = []
    self.notify(
        f"{engineer.faction.upper()} ENGINEER — building {definition['label']}",
        kind="info" if engineer.faction == "player" else "danger",
        duration=2.5,
    )
    return True, ""


def _operation_finish_construction(self, engineer):
    kind = getattr(engineer, "_construction_kind", None)
    pos = getattr(engineer, "_construction_pos", None)
    if kind not in ENGINEER_BUILD_TYPES or pos is None:
        self.cancel_construction_assignment(engineer)
        engineer.order = "idle"
        return None
    definition = ENGINEER_BUILD_TYPES[kind]
    built = None
    if self.unit_at(*pos) is None:
        if "terrain" in definition:
            self.set_cell(pos[0], pos[1], definition["terrain"], "H" if kind == "trench" else None)
            built = pos
        else:
            built = self.add_unit(engineer.faction, definition["role"], pos[0], pos[1])
            built.is_emplacement = True
            built.built_by_uid = engineer.uid
            # Emplacements remain separately clickable assets rather than
            # silently occupying one of a squad's four personnel slots.
            built.squad_id = 0
            built.display_name = definition["label"]
            built.deployed = True
            built.order = "emplaced"
            built.hold_position = True
            built.facing = engineer.facing
            built.artillery_shells = 12 if built.role == "Artillery Battery" else 0
            built.next_artillery_shot = self.time + 3.0
            _kz_rebuild_indexes(self)
    engineer.order = "idle"
    engineer.target_pos = None
    reservation = self.construction_reservations.get(pos)
    if reservation and reservation[0] == engineer.uid:
        self.construction_reservations.pop(pos, None)
    engineer._construction_queued = False
    engineer._construction_kind = None
    engineer._construction_pos = None
    engineer._construction_staging = None
    if built is not None:
        self.notify(
            f"{definition['label']} COMPLETE",
            kind="good" if engineer.faction == "player" else "danger",
            duration=3.2,
        )
        self._vs_event("construction", f"{engineer.faction.title()} built {definition['label']}", pos)
    return built


RealTimeGame.static_emplacement_count = _operation_static_count
RealTimeGame.validate_build_site = _operation_validate_build_site
RealTimeGame.can_build = _operation_can_build
RealTimeGame.builder_staging_position = _operation_builder_staging_position
RealTimeGame.queue_construction = _operation_queue_construction
RealTimeGame.cancel_construction_assignment = _operation_cancel_construction_assignment
RealTimeGame.update_engineer_assignments = _operation_update_engineer_assignments
RealTimeGame.begin_construction = _operation_begin_construction
RealTimeGame.finish_construction = _operation_finish_construction


_operation_previous_complete_action = RealTimeGame.complete_action


def _operation_complete_action(self, unit):
    finishing_build = unit.order == "build"
    _operation_previous_complete_action(self, unit)
    if finishing_build:
        self.finish_construction(unit)


RealTimeGame.complete_action = _operation_complete_action


def _operation_update_emplacements(self):
    for unit in list(self.living()):
        if unit.role not in STATIC_WEAPON_ROLES or not unit.combat_effective:
            continue
        unit.is_emplacement = True
        unit.deployed = True
        unit.hold_position = True
        if unit.jammed and unit.action_timer <= 0:
            self.clear_jam(unit)
            continue
        if unit.action_timer > 0 or unit.reload_timer > 0 or unit.jammed:
            continue
        unit.order = "emplaced"
        if unit.role == "Artillery Battery":
            if getattr(unit, "artillery_shells", 0) <= 0 or self.time < getattr(unit, "next_artillery_shot", 0):
                continue
            enemy_faction = "enemy" if unit.faction == "player" else "player"
            targets = [
                target
                for target in self.living(enemy_faction)
                if target.combat_effective
                and target.role not in STATIC_WEAPON_ROLES
                and self.visible_to(unit.faction, target)
                and 5.0 <= dist(unit, target) <= 30.0
            ]
            if not targets:
                continue
            target = max(targets, key=lambda item: (item.role in ("Machine Gunner", "HMG Crew", "Engineer"), -dist(unit, item)))
            scatter = 0.75 if unit.suppression < 35 else 1.6
            impact = (
                clamp(target.x + self.rng.gauss(0, scatter), 0, MAP_W - 1),
                clamp(target.y + self.rng.gauss(0, scatter), 0, MAP_H - 1),
            )
            self.explosions.append(Explosion(impact[0], impact[1], 2.4, 3.0, 112, 92, "HE", unit.faction))
            unit.artillery_shells -= 1
            unit.next_artillery_shot = self.time + self.rng.uniform(9.0, 12.5)
            unit.signature = max(unit.signature, 18)
            self.emit("shot", pos=unit.pos, weapon="artillery")
            continue
        if self.time < unit.next_shot:
            continue
        target = self.choose_auto_target(unit)
        if target is not None:
            self.perform_shot(unit, target)


RealTimeGame.update_emplacements = _operation_update_emplacements


def _operation_enemy_builder_position(self, engineer):
    candidates = []
    ex, ey = engineer.tile
    for y in range(max(1, ey - 2), min(MAP_H - 1, ey + 3)):
        for x in range(max(1, ex - 2), min(MAP_W - 1, ex + 3)):
            if (x, y) == engineer.tile or self.unit_at(x, y) is not None:
                continue
            if self.grid[y][x].terrain not in ("open", "mud", "rubble", "crater", "foxhole", "hill"):
                continue
            candidates.append((abs(y - MAP_H / 2), abs(x - ex) + abs(y - ey), x, y))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2], candidates[0][3]


def _operation_update_enemy_builders(self):
    if self.time - self._last_engineer_builder_update < 0.75:
        return
    self._last_engineer_builder_update = self.time
    if self.static_emplacement_count("enemy") >= 4:
        return
    engineers = [
        unit
        for unit in self.living("enemy")
        if unit.role == "Engineer"
        and unit.combat_effective
        and getattr(unit, "reserve_active", True)
        and unit.order in ("idle", "overwatch")
        and unit.action_timer <= 0
        and self.time >= getattr(unit, "next_builder_decision", 8.0)
    ]
    for engineer in engineers[:1]:
        position = self.enemy_builder_position(engineer)
        if position is None:
            engineer.next_builder_decision = self.time + 12.0
            continue
        existing = self.static_emplacement_count("enemy")
        if self.mission_type == "defense":
            kind = "field_gun" if existing % 3 == 0 else "artillery" if existing % 3 == 1 else "mg_nest"
        else:
            kind = "mg_nest" if existing % 3 != 2 else "field_gun"
        built, _reason = self.begin_construction(engineer, kind, position)
        engineer.next_builder_decision = self.time + (24.0 if built else 10.0)


RealTimeGame.enemy_builder_position = _operation_enemy_builder_position
RealTimeGame.update_enemy_builders = _operation_update_enemy_builders


def _operation_activate_defense_wave(self, wave):
    units = [
        unit
        for unit in self.living("enemy")
        if getattr(unit, "attack_wave", 1) == wave and not getattr(unit, "reserve_active", True)
    ]
    if not units:
        return
    for unit in units:
        unit.reserve_active = True
        unit.plan_state = "attack"
        unit.order = "idle"
    self.defense_wave_announced.add(wave)
    self.notify(f"ENEMY WAVE {wave} COMMITTED", kind="danger", duration=5.0)
    self._vs_event("reserve", f"Enemy assault wave {wave} committed", (5, MAP_H // 2))


RealTimeGame.activate_defense_wave = _operation_activate_defense_wave


_operation_previous_ai_decide = RealTimeGame.ai_decide


def _operation_defense_attack_destination(self, unit):
    """Return an open, distributed waypoint that keeps an assault moving east."""
    primary = self.primary_line_x
    secondary = self.secondary_line_x
    command = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
    if unit.x < primary - 4.5:
        target_x = primary - 4
    elif unit.x < primary + 1.5:
        target_x = primary + 1
    elif unit.x < secondary - 2.5:
        target_x = secondary - 2
    else:
        target_x = command[0]

    sector_center = {
        "NORTH": max(4, MAP_H // 6),
        "CENTRE": MAP_H // 2,
        "SOUTH": min(MAP_H - 5, MAP_H * 5 // 6),
    }.get(getattr(unit, "battle_sector", "CENTRE"), MAP_H // 2)
    lane_offset = ((unit.uid * 3) % 9) - 4
    target_y = int(clamp(sector_center + lane_offset, 2, MAP_H - 3))
    if target_x >= command[0] - 1:
        target_y = int(clamp(command[1] + lane_offset // 2, 2, MAP_H - 3))
    destination = _operation_open_position(self, target_x, target_y, unit, radius=5)
    return destination or (int(clamp(target_x, 1, MAP_W - 2)), target_y)


def _operation_ai_decide(self, unit):
    if unit.role in STATIC_WEAPON_ROLES:
        return
    if self.mission_type != "defense" or unit.faction != "enemy":
        return _operation_previous_ai_decide(self, unit)
    if not getattr(unit, "reserve_active", True):
        if unit.order not in ("idle", "overwatch"):
            unit.order = "idle"
        return
    if unit.jammed:
        self.clear_jam(unit)
        return
    if unit.ammo <= 0 and unit.magazines:
        self.start_reload(unit)
        return
    if unit.role == "Engineer" and unit.order == "build":
        return
    if (
        unit.role == "Engineer"
        and self.static_emplacement_count("enemy") < 4
        and self.time >= getattr(unit, "next_builder_decision", 8.0)
    ):
        # Leave the engineer idle for the shared builder pass that runs after
        # AI decisions; it will select and validate adjacent construction.
        unit.order = "idle"
        unit.path = []
        unit.waypoints = []
        return
    visible = [
        target
        for target in self.living("player")
        if target.combat_effective and self.can_see(unit, target)
    ]
    if visible:
        target = min(
            visible,
            key=lambda item: (
                0 if item.role in ("MG Emplacement", "Field Gun", "Artillery Battery", "Machine Gunner", "Engineer") else 1,
                dist(unit, item),
            ),
        )
        distance = dist(unit, target)
        if unit.smoke_grenades > 0 and unit.suppression > 58 and distance < 8:
            self.throw_grenade(unit, unit.pos, smoke=True)
            return
        if unit.grenades > 0 and distance < 4.2:
            self.throw_grenade(unit, target.pos, cook=0.6)
            return
        if unit.role in ("Machine Gunner", "HMG Crew"):
            if not unit.deployed:
                self.toggle_deploy(unit)
            elif distance <= unit.weapon["range"]:
                self.suppress_area(unit, target.pos)
            return
        if distance <= unit.weapon["range"]:
            mode = "rapid" if self.doctrine_for(unit) == "aggressive" and distance < 7 else "normal"
            self.issue_fire(unit, target, mode)
            return
    destination = self.defense_attack_destination(unit)
    if unit.role in ("Machine Gunner", "HMG Crew") and unit.deployed:
        self.toggle_deploy(unit)
        return
    if unit.order in ("idle", "overwatch", "fire_lane") and dist(unit.pos, destination) > 2.5:
        self.issue_move([unit], destination, mode="safe" if unit.role in ("Medic", "Engineer") else "fast", formation="column")
    elif dist(unit.pos, destination) <= 3.5:
        self.set_overwatch(unit, 0, 110)


RealTimeGame.ai_decide = _operation_ai_decide
RealTimeGame.defense_attack_destination = _operation_defense_attack_destination


def _operation_update_defense_attack_orders(self, dt):
    if self.mission_type != "defense":
        return
    self._defense_attack_order_timer += dt
    if self._defense_attack_order_timer < 0.75:
        return
    self._defense_attack_order_timer = 0.0
    for unit in self.living("enemy"):
        if (
            not unit.combat_effective
            or unit.role in STATIC_WEAPON_ROLES
            or not getattr(unit, "reserve_active", True)
            or unit.action_timer > 0
            or unit.order in ("build", "rout", "medic", "deploy", "pack", "clear_jam")
            or getattr(unit, "_construction_queued", False)
        ):
            continue
        visible = any(
            target.combat_effective and self.can_see(unit, target)
            for target in self.living("player")
        )
        if visible:
            continue
        stalled = unit.order in ("idle", "overwatch", "fire_lane") or (
            unit.order == "move" and not unit.path and not unit.waypoints
        )
        if not stalled:
            continue
        if unit.role in ("Machine Gunner", "HMG Crew") and unit.deployed:
            self.toggle_deploy(unit)
            continue
        destination = self.defense_attack_destination(unit)
        self.issue_move(
            [unit],
            destination,
            mode="safe" if unit.role in ("Medic", "Engineer") else "fast",
            formation="column",
        )


RealTimeGame.update_defense_attack_orders = _operation_update_defense_attack_orders


def _operation_update_defense_stage(self):
    remaining = max(0.0, self.defense_time_limit - self.defense_elapsed)
    if remaining <= 60:
        stage = "FINAL ASSAULT"
    elif self.defense_elapsed >= self.defense_time_limit / 3:
        stage = "HOLD"
    elif self.combat_intensity > 4 or any(self.visible_to("player", unit) for unit in self.living("enemy")):
        stage = "CONTACT"
    else:
        stage = "PREPARATION"
    if stage != self.battle_stage:
        self.battle_stage = stage
        self.notify(stage, kind="danger" if stage in ("CONTACT", "FINAL ASSAULT") else "objective", duration=4.0)


def _operation_update_defense_objectives(self, dt):
    self.defense_elapsed += dt
    self._mission_timer += dt
    self._stability_timer += dt
    self._operation_update_defense_stage()
    if self.defense_elapsed >= self.defense_time_limit * 0.28 and 2 not in self.defense_wave_announced:
        self.activate_defense_wave(2)
    if self.defense_elapsed >= self.defense_time_limit * 0.62 and 3 not in self.defense_wave_announced:
        self.activate_defense_wave(3)

    segment = self.defense_time_limit / len(self.objectives)
    active_index = min(len(self.objectives) - 1, int(self.defense_elapsed / max(1.0, segment)))
    for index, objective in enumerate(self.objectives):
        if index < active_index:
            objective["progress"] = 1.0
            objective["state"] = "complete"
        elif index == active_index:
            objective["progress"] = clamp((self.defense_elapsed - index * segment) / segment, 0, 1)
            objective["state"] = "active"
        else:
            objective["progress"] = 0.0
            objective["state"] = "locked"
    if active_index != self.objective_index:
        self.objective_index = active_index
        self.notify(f"NEW OBJECTIVE — {self.objectives[active_index]['title']}", kind="objective", duration=5.0)

    if self._stability_timer >= 0.5:
        self._stability_timer = 0.0
        for sector in ("NORTH", "CENTRE", "SOUTH"):
            defenders = [
                unit
                for unit in self.living("player")
                if unit.combat_effective
                and unit.role not in STATIC_WEAPON_ROLES
                and _vs_sector_name(unit.y) == sector
            ]
            attackers = [
                unit
                for unit in self.living("enemy")
                if unit.combat_effective
                and getattr(unit, "reserve_active", True)
                and _vs_sector_name(unit.y) == sector
                and unit.x >= self.primary_line_x - 6
            ]
            average_suppression = sum(unit.suppression for unit in defenders) / max(1, len(defenders))
            self.sector_stability[sector] = clamp(
                100 - len(attackers) * 14 - average_suppression * 0.38 - max(0, 2 - len(defenders)) * 13,
                0,
                100,
            )

    command = self.map_features.get("command_post", (MAP_W - 4, MAP_H // 2))
    attackers = [
        unit
        for unit in self.living("enemy")
        if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES and dist(unit.pos, command) <= 2.7
    ]
    defenders = [
        unit
        for unit in self.living("player")
        if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES and dist(unit.pos, command) <= 4.2
    ]
    if attackers and not defenders:
        self.defense_capture_progress = min(18.0, self.defense_capture_progress + dt)
    else:
        self.defense_capture_progress = max(0.0, self.defense_capture_progress - dt * 1.7)

    mobile_player = [
        unit for unit in self.living("player") if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    mobile_enemy = [
        unit for unit in self.living("enemy") if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    if not mobile_player or self.defense_capture_progress >= 18.0:
        self.defeat = True
        self._vs_event("defeat", "The defensive position was overrun", command)
    elif self.defense_elapsed >= self.defense_time_limit or (
        self.defense_elapsed >= 60 and len(mobile_enemy) <= max(1, int(self.initial_mobile_enemy_total * 0.12))
    ):
        for objective in self.objectives:
            objective["progress"] = 1.0
            objective["state"] = "complete"
        self.objective_index = len(self.objectives)
        self.victory = True
        self._vs_event("victory", "The defensive line held", command)

    remaining_seconds = max(0, int(math.ceil(self.defense_time_limit - self.defense_elapsed)))
    remaining_minutes = int(math.ceil(remaining_seconds / 60))
    if remaining_seconds > 0 and remaining_minutes != self._defense_last_minute:
        self._defense_last_minute = remaining_minutes
        self.notify(f"HOLD FOR {remaining_minutes} MORE MINUTE{'S' if remaining_minutes != 1 else ''}", kind="objective", duration=3.0)
    self.notifications = [item for item in self.notifications if item["until"] > self.time]


RealTimeGame._operation_update_defense_stage = _operation_update_defense_stage
RealTimeGame.update_defense_mission = _operation_update_defense_objectives


_operation_previous_update_mission = RealTimeGame.update_mission_state


def _operation_update_mission(self, dt):
    if self.mission_type == "defense":
        return self.update_defense_mission(dt)
    return _operation_previous_update_mission(self, dt)


RealTimeGame.update_mission_state = _operation_update_mission


_operation_previous_check_end = RealTimeGame.check_end


def _operation_check_end(self):
    if self.mission_type != "defense":
        return _operation_previous_check_end(self)
    players = [
        unit for unit in self.living("player") if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    enemies = [
        unit for unit in self.living("enemy") if unit.combat_effective and unit.role not in STATIC_WEAPON_ROLES
    ]
    if not enemies:
        self.victory = True
    if not players:
        self.defeat = True


RealTimeGame.check_end = _operation_check_end


_operation_previous_deploy_reserves = RealTimeGame.deploy_player_reserves


def _operation_deploy_reserves(self):
    if self.mission_type != "defense":
        return _operation_previous_deploy_reserves(self)
    if not self.player_reserves:
        return []
    roles = list(self.player_reserves)
    self.player_reserves = []
    new_units = []
    base_y = int(clamp(self.rally_points["player"][1], 3, MAP_H - 4))
    for index, role in enumerate(roles):
        unit = self.add_unit("player", role, MAP_W - 3, base_y)
        desired_y = int(clamp(base_y + (index // 3) * 2 - (len(roles) // 3), 2, MAP_H - 3))
        position = _operation_open_position(self, MAP_W - 3 - index % 3, desired_y, unit, radius=6)
        if position:
            unit.x, unit.y = position
        unit.facing = 180
        unit.reserve = True
        new_units.append(unit)
        key = ("player", max(1, int(getattr(unit, "squad_id", 1))))
        self.squad_doctrine.setdefault(key, "balanced")
    self.stats["player"]["reserves"] += len(new_units)
    _kz_rebuild_indexes(self)
    self.add_log(f"{len(new_units)} reserve unit(s) entered from the east.")
    self._kz_event_record(
        "reserve",
        f"{len(new_units)} reserves committed",
        (MAP_W - 3, base_y),
    )
    return new_units


RealTimeGame.deploy_player_reserves = _operation_deploy_reserves


_operation_previous_update = RealTimeGame.update


def _operation_update(self, dt):
    _operation_previous_update(self, dt)
    if self.paused or self.victory or self.defeat:
        return
    self.update_engineer_assignments()
    self.update_emplacements()
    self.update_enemy_builders()
    self.update_defense_attack_orders(dt)


RealTimeGame.update = _operation_update


# ----------------------------- operations user interface --------------------
_operation_previous_app_init = KillZoneApp.__init__


def _operation_app_init(self):
    _operation_previous_app_init(self)
    self.setup_mission = "assault"
    self.setup_variant = "auto"
    self.setup_weather = "auto"
    self.setup_enemy_strength = 1.0
    self.setup_defense_duration = 300
    self.build_menu_open = False


KillZoneApp.__init__ = _operation_app_init


def _operation_current_config(self):
    return sanitize_operation_config(
        {
            "mission": self.setup_mission,
            "variant": self.setup_variant,
            "weather": self.setup_weather,
            "enemy_strength": self.setup_enemy_strength,
            "defense_duration": self.setup_defense_duration,
        }
    )


KillZoneApp.current_operation_config = _operation_current_config


def _operation_setup_button_rect(self):
    return pygame.Rect(WINDOW_W - 314, 714, 260, 40)


KillZoneApp.operation_setup_button_rect = _operation_setup_button_rect


def _operation_option_rects(self):
    center = WINDOW_W // 2
    rects = {
        "mission": {},
        "variant": {},
        "weather": {},
        "strength": {},
        "duration": {},
    }
    width = 220
    gap = 18
    start = center - (width * 2 + gap) // 2
    rects["mission"] = {
        "assault": pygame.Rect(start, 150, width, 44),
        "defense": pygame.Rect(start + width + gap, 150, width, 44),
    }
    variant_width = 224
    variant_gap = 12
    variant_start = center - (variant_width * 5 + variant_gap * 4) // 2
    for index, value in enumerate(OPERATION_VARIANTS):
        rects["variant"][value] = pygame.Rect(
            variant_start + index * (variant_width + variant_gap),
            262,
            variant_width,
            42,
        )
    weather_width = 220
    weather_start = center - (weather_width * 4 + gap * 3) // 2
    for index, value in enumerate(OPERATION_WEATHER):
        rects["weather"][value] = pygame.Rect(
            weather_start + index * (weather_width + gap),
            370,
            weather_width,
            42,
        )
    strength_width = 260
    strength_start = center - (strength_width * 3 + gap * 2) // 2
    for index, value in enumerate(OPERATION_ENEMY_STRENGTHS):
        rects["strength"][value] = pygame.Rect(
            strength_start + index * (strength_width + gap),
            478,
            strength_width,
            42,
        )
    duration_width = 260
    duration_start = center - (duration_width * 3 + gap * 2) // 2
    for index, value in enumerate(OPERATION_DEFENSE_DURATIONS):
        rects["duration"][value] = pygame.Rect(
            duration_start + index * (duration_width + gap),
            586,
            duration_width,
            42,
        )
    rects["done"] = pygame.Rect(center - 150, 692, 300, 46)
    return rects


KillZoneApp.operation_option_rects = _operation_option_rects


def _operation_draw_setup_options(self):
    self.draw_menu_background()
    self.text("ADVANCED OPERATIONS", (WINDOW_W // 2 - 250, 48), 38, "white")
    self.text(
        "Choose the battle problem. Roster, reserves, difficulty and seed remain on the previous screen.",
        (WINDOW_W // 2 - 420, 94),
        12,
        "muted",
    )
    rects = self.operation_option_rects()

    rows = (
        ("MISSION", "mission", self.setup_mission),
        ("BATTLEFIELD", "variant", self.setup_variant),
        ("WEATHER", "weather", self.setup_weather),
        ("ENEMY FORCE", "strength", self.setup_enemy_strength),
        ("DEFENSE HOLD TIME", "duration", self.setup_defense_duration),
    )
    labels = {
        "assault": "ASSAULT",
        "defense": "DEFENSE",
        "auto": "AUTO",
        "farmland": "FARMLAND",
        "wooded_ridge": "WOODED RIDGE",
        "ruined_village": "RUINED VILLAGE",
        "hill_line": "RIDGELINE",
        "clear": "CLEAR",
        "rain": "RAIN",
        "fog": "FOG",
        0.8: "LIGHT · 80%",
        1.0: "STANDARD · 100%",
        1.25: "REINFORCED · 125%",
        180: "3 MINUTES",
        300: "5 MINUTES",
        420: "7 MINUTES",
    }
    title_y = {"mission": 121, "variant": 233, "weather": 341, "strength": 449, "duration": 557}
    for heading, group, selected in rows:
        self.text(heading, (min(rect.x for rect in rects[group].values()), title_y[group]), 13, "select")
        for value, rect in rects[group].items():
            enabled = group != "duration" or self.setup_mission == "defense"
            self.button(
                rect,
                labels[value],
                self.mouse,
                enabled=enabled,
                accent=enabled and value == selected,
            )
    description = (
        "DEFENSE reverses deployment: your force starts inside the eastern trench system and holds against three waves."
        if self.setup_mission == "defense"
        else "ASSAULT uses the established staged advance through the enemy forward line, strongpoint and command post."
    )
    self.text(description, (WINDOW_W // 2 - 520, 642), 11, "text")
    self.text(
        "ENGINEERING PREVIEW · construction is free this update; supplies and logistics will set costs next update.",
        (WINDOW_W // 2 - 470, 665),
        10,
        "contact",
    )
    self.button(rects["done"], "SAVE OPERATION", self.mouse, accent=True)


KillZoneApp.draw_operation_setup = _operation_draw_setup_options


def _operation_handle_setup_options(self, event):
    if event.type == pygame.QUIT:
        self.running = False
        return
    if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
        self.toggle_fullscreen()
        return
    if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
        self.state = "setup"
        return
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return
    rects = self.operation_option_rects()
    if rects["done"].collidepoint(event.pos):
        self.state = "setup"
        return
    for value, rect in rects["mission"].items():
        if rect.collidepoint(event.pos):
            self.setup_mission = value
            return
    for value, rect in rects["variant"].items():
        if rect.collidepoint(event.pos):
            self.setup_variant = value
            return
    for value, rect in rects["weather"].items():
        if rect.collidepoint(event.pos):
            self.setup_weather = value
            return
    for value, rect in rects["strength"].items():
        if rect.collidepoint(event.pos):
            self.setup_enemy_strength = value
            return
    if self.setup_mission == "defense":
        for value, rect in rects["duration"].items():
            if rect.collidepoint(event.pos):
                self.setup_defense_duration = value
                return


KillZoneApp.handle_operation_setup = _operation_handle_setup_options


_operation_previous_draw_setup = KillZoneApp.draw_setup


def _operation_draw_setup(self):
    _operation_previous_draw_setup(self)
    rect = self.operation_setup_button_rect()
    mission = "DEFENSE" if self.setup_mission == "defense" else "ASSAULT"
    self.button(rect, f"ADVANCED · {mission}", self.mouse, accent=self.setup_mission == "defense")


KillZoneApp.draw_setup = _operation_draw_setup


def _operation_prepare_briefing(self):
    roster = self.current_setup_roster()
    if not roster:
        return
    seed = int(self.seed_text) if self.seed_text.isdigit() else None
    self.battle_roster = list(roster)
    self.game = RealTimeGame(
        seed=seed,
        difficulty=self.setup_difficulty,
        player_roster=roster,
        reserve_count=self.setup_reserves,
        operation_config=self.current_operation_config(),
    )
    self.selected = []
    self.command_mode = "normal"
    self.show_threat = False
    self.show_help = False
    self.control_groups = {index: [] for index in range(1, 10)}
    self.deployment_active = False
    self.battle_active = False
    self.briefing_ready = True
    self.build_menu_open = False
    self.state = "briefing"
    if self.game.deployment_zone_side == "east":
        self.camera_x = max(0, MAP_W - MAP_VIEW_W_PX / self.tile_px)
    else:
        self.camera_x = 0
    self.camera_y = max(0, MAP_H / 2 - 10)
    self.clamp_camera()


KillZoneApp.start_battle = _operation_prepare_briefing


def _operation_draw_briefing(self):
    self.draw_menu_background()
    self.text("MISSION BRIEFING", (70, 55), 38, "white")
    self.text(self.game.mission_title, (70, 112), 22, "select")
    low, high = self.game.enemy_estimate
    strength = int(round(self.game.operation_enemy_strength * 100))
    self.text(
        f"Seed {self.game.seed}  ·  {self.game.weather.upper()}  ·  enemy force {strength}%  ·  estimated {low}–{high}",
        (70, 151),
        13,
        "muted",
    )
    self.text(self.game.mission_brief, (70, 188), 14, "text")
    self.text("TASK", (70, 242), 16, "select")
    y = 274
    for index, objective in enumerate(self.game.objectives, 1):
        self.text(f"{index}. {objective['title']}", (88, y), 16, "white")
        y += 24
        self.text(objective["desc"], (112, y), 12, "muted")
        y += 39
    self.text("COMMANDER'S NOTES", (790, 242), 16, "select")
    if self.game.mission_type == "defense":
        notes = (
            "• Deploy inside the eastern marked zone; the enemy attacks from the west.",
            "• Shift+B or ENGINEER BUILD opens sandbags, wire, trenches and weapons.",
            "• Emplaced MGs and field guns fire automatically when they can see a target.",
            "• Artillery needs friendly observation and cannot engage within five tiles.",
            "• The command post falls after 18 uncontested seconds; retain a mobile force.",
        )
    else:
        notes = (
            "• Recon before committing the whole force.",
            "• Suppression, smoke and crossfire are the intended tools for cracking Line 1.",
            "• Shift+D cycles selected squads between cautious, balanced and aggressive doctrine.",
            "• Enemy engineers can improve the defense; destroy or bypass their emplacements.",
            "• The final objective is the rear command bunker, not extermination of every defender.",
        )
    y = 278
    for line in notes:
        self.text(line, (806, y), 12, "muted")
        y += 32
    self.text(
        "ENGINEERING PREVIEW — no supply cost yet; build time and emplacement caps are temporary safeguards.",
        (70, 636),
        10,
        "contact",
    )
    self.button(pygame.Rect(WINDOW_W // 2 - 150, 690, 300, 46), "BEGIN DEPLOYMENT", self.mouse, accent=True)
    self.button(pygame.Rect(34, 690, 180, 42), "BACK", self.mouse)


KillZoneApp.draw_briefing = _operation_draw_briefing


_operation_previous_deploy_click = KillZoneApp.deploy_click


def _operation_deploy_click(self, cell):
    if self.game.deployment_zone_side != "east":
        return _operation_previous_deploy_click(self, cell)
    if not cell or cell[0] < self.game.defense_deployment_x:
        return
    units = [unit for unit in self.selected_units() if unit.role not in STATIC_WEAPON_ROLES]
    if not units:
        return
    offsets = self.game.formation_offsets(len(units), self.formation)
    moving_ids = {unit.uid for unit in units}
    occupied = {unit.tile for unit in self.game.living("player") if unit.uid not in moving_ids}
    for unit, (offset_x, offset_y) in zip(units, offsets):
        x = int(clamp(round(cell[0] + offset_x), self.game.defense_deployment_x, MAP_W - 2))
        y = int(clamp(round(cell[1] + offset_y), 1, MAP_H - 2))
        if (x, y) in occupied or not self.game.passable(x, y, unit):
            continue
        unit.x, unit.y = x, y
        unit.path = []
        unit.waypoints = []
        unit.order = "idle"
        unit.facing = 180
        occupied.add((x, y))
    _kz_rebuild_indexes(self.game)


KillZoneApp.deploy_click = _operation_deploy_click


_operation_previous_draw_deployment = KillZoneApp.draw_deployment


def _operation_draw_deployment(self):
    if self.game.deployment_zone_side != "east":
        return _operation_previous_draw_deployment(self)
    self.draw_topbar()
    self.draw_map()
    self.draw_sidebar()
    self.draw_command_bar()
    overlay = pygame.Rect(MAP_X + 190, MAP_Y + 12, 735, 60)
    pygame.draw.rect(self.screen, COLORS["panel"], overlay)
    pygame.draw.rect(self.screen, COLORS["select"], overlay, 2)
    self.text("DEFENSIVE DEPLOYMENT", (overlay.x + 12, overlay.y + 8), 16, "white")
    self.text(
        "Select troops/squads, RMB inside the east deployment zone to place. Enter/Space starts battle.",
        (overlay.x + 12, overlay.y + 31),
        11,
        "muted",
    )
    x = int(MAP_X + (self.game.defense_deployment_x - self.camera_x) * self.tile_px)
    pygame.draw.line(self.screen, COLORS["select"], (x, MAP_Y), (x, MAP_Y + MAP_VIEW_H_PX), 2)


KillZoneApp.draw_deployment = _operation_draw_deployment


def _operation_build_button_rect(self):
    return pygame.Rect(SIDEBAR_X + 10, MAP_Y + MAP_VIEW_H_PX - 36, WINDOW_W - SIDEBAR_X - 32, 28)


def _operation_build_menu_rects(self):
    width = 760
    height = 330
    x = MAP_X + (MAP_VIEW_W_PX - width) // 2
    y = MAP_Y + (MAP_VIEW_H_PX - height) // 2
    rects = {}
    cell_width = 226
    cell_height = 72
    for index, kind in enumerate(ENGINEER_BUILD_TYPES):
        column = index % 3
        row = index // 3
        rects[kind] = pygame.Rect(x + 28 + column * (cell_width + 13), y + 85 + row * 88, cell_width, cell_height)
    rects["cancel"] = pygame.Rect(x + width - 132, y + 18, 104, 32)
    rects["panel"] = pygame.Rect(x, y, width, height)
    return rects


KillZoneApp.build_button_rect = _operation_build_button_rect
KillZoneApp.build_menu_rects = _operation_build_menu_rects


def _operation_draw_build_menu(self):
    rects = self.build_menu_rects()
    panel = rects["panel"]
    shade = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
    shade.fill((8, 10, 8, 155))
    self.screen.blit(shade, (0, 0))
    pygame.draw.rect(self.screen, COLORS["panel"], panel, border_radius=5)
    pygame.draw.rect(self.screen, COLORS["select"], panel, 2, border_radius=5)
    self.text("ENGINEER CONSTRUCTION", (panel.x + 26, panel.y + 18), 20, "white")
    self.text(
        "Choose a project, then place it anywhere reachable. The nearest available engineer responds.",
        (panel.x + 27, panel.y + 51),
        10,
        "muted",
    )
    for kind, definition in ENGINEER_BUILD_TYPES.items():
        rect = rects[kind]
        pygame.draw.rect(self.screen, COLORS["panel2"], rect, border_radius=4)
        pygame.draw.rect(self.screen, COLORS["objective"] if "role" in definition else COLORS["blue"], rect, 1, border_radius=4)
        self.text(definition["label"], (rect.x + 12, rect.y + 11), 12, "white")
        self.text(definition["description"], (rect.x + 12, rect.y + 38), 8, "muted")
    self.button(rects["cancel"], "CLOSE", self.mouse)
    self.text(
        "FREE BUILD PREVIEW · static weapon cap 6 per side · supply/logistics costs follow next update",
        (panel.x + 27, panel.bottom - 29),
        9,
        "contact",
    )


KillZoneApp.draw_build_menu = _operation_draw_build_menu


_operation_previous_draw_command_bar = KillZoneApp.draw_command_bar


def _operation_draw_command_bar(self):
    _operation_previous_draw_command_bar(self)
    if self.state not in ("game", "deployment"):
        return
    units = self.selected_units()
    engineers = [
        unit
        for unit in self.game.living("player")
        if unit.role == "Engineer" and unit.combat_effective
    ]
    rect = self.build_button_rect()
    pygame.draw.rect(self.screen, COLORS["panel2"], rect, border_radius=3)
    pygame.draw.rect(
        self.screen,
        COLORS["select"] if engineers else COLORS["muted"],
        rect,
        2 if engineers else 1,
        border_radius=3,
    )
    label = "ENGINEER BUILD [SHIFT+B]" if engineers else "NO ENGINEER AVAILABLE"
    surface = self.cached_text_surface(label, 9, "select" if engineers else "muted")
    self.screen.blit(surface, (rect.centerx - surface.get_width() // 2, rect.centery - surface.get_height() // 2))
    mobile = [unit for unit in units if unit.role not in STATIC_WEAPON_ROLES]
    if mobile:
        doctrine = self.game.doctrine_for(mobile[0]).upper()
        self.text(f"DOCTRINE  {doctrine}  [SHIFT+D]", (rect.x, rect.y - 20), 9, "contact")
    if self.build_menu_open:
        self.draw_build_menu()


KillZoneApp.draw_command_bar = _operation_draw_command_bar


_operation_previous_unit_cards = KillZoneApp.unit_card_rects


def _operation_unit_cards(self):
    return [
        (unit, rect)
        for unit, rect in _operation_previous_unit_cards(self)
        if unit.role not in STATIC_WEAPON_ROLES
    ]


KillZoneApp.unit_card_rects = _operation_unit_cards


def _operation_squad_rects(self):
    x = MAP_X
    y = MAP_Y + MAP_VIEW_H_PX + 5
    output = {"ALL": pygame.Rect(x, y, 78, 28)}
    squads = sorted(
        {
            getattr(unit, "squad_id", 0)
            for unit in self.game.living("player")
            if unit.combat_effective
            and unit.role not in STATIC_WEAPON_ROLES
            and getattr(unit, "squad_id", 0) > 0
        }
    )
    for index, squad in enumerate(squads[:5]):
        output[squad] = pygame.Rect(x + 86 + index * 88, y, 80, 28)
    return output


KillZoneApp.squad_rects = _operation_squad_rects


_operation_previous_draw_topbar = KillZoneApp.draw_topbar


def _operation_draw_topbar(self):
    _operation_previous_draw_topbar(self)
    if getattr(self.game, "mission_type", "assault") != "defense" or self.state not in ("game", "deployment"):
        return
    if self.state == "deployment":
        label = "DEFENSE · DEPLOY EAST"
        color = "select"
    else:
        remaining = max(0, int(math.ceil(self.game.defense_time_limit - self.game.defense_elapsed)))
        wave = max(getattr(self.game, "defense_wave_announced", {1}))
        capture = getattr(self.game, "defense_capture_progress", 0.0)
        command = "COMMAND CONTESTED" if capture > 0 else "COMMAND SECURE"
        label = f"HOLD {remaining // 60:02d}:{remaining % 60:02d}  ·  WAVE {wave}/3  ·  {command}"
        color = "danger" if capture > 0 else "objective"
    surface = self.cached_text_surface(label, 10, color)
    panel = pygame.Rect(WINDOW_W - surface.get_width() - 32, 28, surface.get_width() + 20, 22)
    pygame.draw.rect(self.screen, COLORS["panel2"], panel, border_radius=3)
    pygame.draw.rect(self.screen, COLORS[color], panel, 1, border_radius=3)
    self.screen.blit(surface, (panel.x + 10, panel.y + 5))


KillZoneApp.draw_topbar = _operation_draw_topbar


_operation_previous_draw_map = KillZoneApp.draw_map


def _operation_draw_map(self):
    _operation_previous_draw_map(self)
    for pos, reservation in self.game.construction_reservations.items():
        engineer_uid, kind, faction = reservation
        if faction != "player":
            continue
        rect = self.cell_rect(*pos)
        if not rect.colliderect(self.map_view_rect()):
            continue
        pygame.draw.rect(self.screen, COLORS["blue"], rect, 2)
        pygame.draw.line(self.screen, COLORS["blue"], rect.topleft, rect.bottomright, 1)
        pygame.draw.line(self.screen, COLORS["blue"], rect.topright, rect.bottomleft, 1)
        label = self.cached_text_surface(f"BUILD {ENGINEER_BUILD_TYPES[kind]['label']}", 7, "white")
        self.screen.blit(label, (rect.centerx - label.get_width() // 2, rect.y - 11))
        engineer = self.game.get_unit(engineer_uid)
        if engineer and engineer.combat_effective:
            start = self.world_to_screen(engineer.x, engineer.y)
            if self.map_view_rect().collidepoint(start):
                pygame.draw.line(self.screen, COLORS["blue"], start, rect.center, 1)
    if not self.command_mode.startswith("build:"):
        return
    cell = self.map_cell_from_mouse(self.mouse)
    if cell is None:
        return
    rect = self.cell_rect(*cell)
    if rect.colliderect(self.map_view_rect()):
        kind = self.command_mode.split(":", 1)[1]
        valid, _reason = self.game.validate_build_site("player", kind, cell)
        color = COLORS["objective"] if valid else COLORS["danger"]
        pygame.draw.rect(self.screen, color, rect, 3)
        pygame.draw.line(self.screen, color, rect.topleft, rect.bottomright, 1)
        pygame.draw.line(self.screen, color, rect.topright, rect.bottomleft, 1)


KillZoneApp.draw_map = _operation_draw_map


_operation_previous_draw_unit = KillZoneApp.draw_unit


def _operation_draw_unit(self, unit):
    _operation_previous_draw_unit(self, unit)
    if unit.role not in STATIC_WEAPON_ROLES or not unit.alive:
        return
    center_x, center_y = self.world_to_screen(unit.x, unit.y)
    if not self.map_view_rect().inflate(35, 35).collidepoint((center_x, center_y)):
        return
    color = COLORS["nato_friend"] if unit.faction == "player" else COLORS["nato_hostile"]
    radius = max(10, int(self.tile_px * 0.48))
    pygame.draw.circle(self.screen, color, (center_x, center_y), radius, 2)
    label = {"MG Emplacement": "MG", "Field Gun": "GUN", "Artillery Battery": "ART"}[unit.role]
    surface = self.cached_text_surface(label, 8, "white")
    self.screen.blit(surface, (center_x - surface.get_width() // 2, center_y - radius - 12))


KillZoneApp.draw_unit = _operation_draw_unit


_operation_previous_issue_context = KillZoneApp.issue_context_command


def _operation_issue_context(self, cell, append=False):
    if not self.command_mode.startswith("build:"):
        return _operation_previous_issue_context(self, cell, append=append)
    kind = self.command_mode.split(":", 1)[1]
    preferred = [
        unit
        for unit in self.selected_units()
        if unit.role == "Engineer" and unit.combat_effective
    ]
    engineer, reason = self.game.queue_construction(
        "player",
        kind,
        cell,
        preferred_engineers=preferred,
    )
    if engineer is None:
        _qol_notify(self, reason, kind="danger", duration=2.4)
        return
    _qol_notify(
        self,
        f"{getattr(engineer, 'display_name', 'Engineer')} assigned — moving to {ENGINEER_BUILD_TYPES[kind]['label']}",
        kind="good",
        duration=2.6,
    )
    self.command_mode = "normal"


KillZoneApp.issue_context_command = _operation_issue_context


def _operation_cycle_selected_doctrine(self, units=None):
    units = self.selected_units() if units is None else units
    doctrine = self.game.cycle_squad_doctrine(units)
    if doctrine is None:
        _qol_notify(self, "Select a mobile squad to change doctrine", kind="danger", duration=1.8)
        return None
    _qol_notify(self, f"Squad doctrine: {doctrine.upper()}", kind="good", duration=2.0)
    return doctrine


KillZoneApp.cycle_selected_doctrine = _operation_cycle_selected_doctrine


def _operation_handle_build_menu(self, event):
    if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
        self.toggle_fullscreen()
        return True
    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
        self.build_menu_open = False
        return True
    if event.type != pygame.MOUSEBUTTONDOWN:
        return True
    if event.button != 1:
        return True
    rects = self.build_menu_rects()
    if rects["cancel"].collidepoint(event.pos) or not rects["panel"].collidepoint(event.pos):
        self.build_menu_open = False
        return True
    for kind in ENGINEER_BUILD_TYPES:
        if rects[kind].collidepoint(event.pos):
            if not any(
                unit.role == "Engineer" and unit.combat_effective
                for unit in self.game.living("player")
            ):
                _qol_notify(self, "No engineer is available", kind="danger", duration=1.8)
                self.build_menu_open = False
                return True
            self.command_mode = f"build:{kind}"
            self.build_menu_open = False
            _qol_notify(
                self,
                f"{ENGINEER_BUILD_TYPES[kind]['label']} ready — click a build site",
                duration=2.3,
            )
            return True
    return True


KillZoneApp.handle_build_menu = _operation_handle_build_menu


_operation_previous_handle_event = KillZoneApp.handle_event


def _operation_handle_event(self, event):
    event = self.normalize_event_pos(event)
    if event.type == pygame.MOUSEMOTION:
        self.mouse = event.pos
    if self.state == "operation_setup":
        return self.handle_operation_setup(event)
    if (
        self.state == "setup"
        and event.type == pygame.MOUSEBUTTONDOWN
        and event.button == 1
        and self.operation_setup_button_rect().collidepoint(event.pos)
    ):
        self.seed_active = False
        self.state = "operation_setup"
        return
    if self.state in ("game", "deployment"):
        if self.build_menu_open:
            return self.handle_build_menu(event)
        if event.type == pygame.KEYDOWN:
            mods = getattr(event, "mod", pygame.key.get_mods())
            if event.key == pygame.K_b and mods & pygame.KMOD_SHIFT:
                if self.state == "deployment":
                    _qol_notify(self, "Construction begins after deployment", kind="danger", duration=1.8)
                    return
                self.show_help = False
                self.build_menu_open = not self.build_menu_open
                return
            if event.key == pygame.K_d and mods & pygame.KMOD_SHIFT:
                self.cycle_selected_doctrine()
                return
            if event.key == pygame.K_F5:
                self.start_battle()
                return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.state == "game" and self.command_mode.startswith("build:"):
                cell = self.map_cell_from_mouse(event.pos)
                if cell is not None:
                    self.issue_context_command(cell)
                    return
            if event.button == 1 and self.build_button_rect().collidepoint(event.pos):
                if self.state == "deployment":
                    _qol_notify(self, "Construction begins after deployment", kind="danger", duration=1.8)
                elif any(
                    unit.role == "Engineer" and unit.combat_effective
                    for unit in self.game.living("player")
                ):
                    self.show_help = False
                    self.build_menu_open = True
                else:
                    _qol_notify(self, "No engineer is available", kind="danger", duration=1.8)
                return
            if event.button == 3:
                for squad_id, rect in self.squad_rects().items():
                    if squad_id != "ALL" and rect.collidepoint(event.pos):
                        members = [
                            unit
                            for unit in self.game.living("player")
                            if unit.combat_effective and getattr(unit, "squad_id", 0) == squad_id
                        ]
                        self.cycle_selected_doctrine(members)
                        return
    return _operation_previous_handle_event(self, event)


KillZoneApp.handle_event = _operation_handle_event


_operation_previous_draw = KillZoneApp.draw


def _operation_draw(self):
    if self.state == "operation_setup":
        self.screen.fill(COLORS["bg"])
        self.draw_operation_setup()
        self.present()
        return
    return _operation_previous_draw(self)


KillZoneApp.draw = _operation_draw
