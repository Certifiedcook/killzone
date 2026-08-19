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
        ("DISCIPLINE", "FREE etc.", "Cycles hold, return fire, free fire and confident-shot rules."),
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
        "Shortcuts: F2 Assault · F3 Bound · F4 Formation · F7 Discipline · F8 Priority · F10 Auto",
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
