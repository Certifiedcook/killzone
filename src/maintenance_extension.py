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


def sector_stability_color(stability):
    """Return the UI color key for defensive line stability."""
    return "good" if stability > 65 else "contact" if stability > 30 else "danger"


_maintenance_previous_text = KillZoneApp.text


def _maintenance_text(self, value, pos, size=14, color="text"):
    # The existing sidebar emits these three rows through the shared text helper.
    # Correct their inverted semantic color without replacing the dense sidebar.
    text_value = str(value)
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
