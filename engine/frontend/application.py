"""Frontend / application for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.clock import FixedStepClock
from engine.frontend.support import _qol_clear_text_caches
from engine.frontend.support import _qol_notify
from engine.frontend.support import bootstrap_assets_async
from engine.frontend.support import effective_ui_font_size
from engine.frontend.support import load_user_settings
from engine.frontend.support import save_user_settings
from engine.rules import clamp
from engine.rules import sanitize_operation_config
from engine.definitions import APP_TITLE
from engine.definitions import COLORS
from engine.definitions import DEFAULT_PLAYER_ROSTER
from engine.definitions import ENGINEER_BUILD_TYPES
from engine.definitions import FPS
from engine.definitions import MAP_H
from engine.definitions import MAP_VIEW_H_PX
from engine.definitions import MAP_VIEW_W_PX
from engine.definitions import MAP_W
from engine.definitions import MAP_X
from engine.definitions import MAP_Y
from engine.definitions import MAX_PLAYER_UNITS
from engine.definitions import NETWORK_PVP_BATTLEFIELDS
from engine.definitions import NETWORK_PVP_DEFAULT_ROSTER
from engine.definitions import OPERATION_DEFENSE_DURATIONS
from engine.definitions import OPERATION_ENEMY_STRENGTHS
from engine.definitions import OPERATION_VARIANTS
from engine.definitions import OPERATION_WEATHER
from engine.definitions import PLAYER_ROLE_ORDER
from engine.definitions import ROLES
from engine.definitions import SIDEBAR_X
from engine.definitions import SIM_DT
from engine.definitions import STANCE
from engine.definitions import STATIC_WEAPON_ROLES
from engine.definitions import TERRAIN
from engine.definitions import TILE
from engine.definitions import WINDOW_H
from engine.definitions import WINDOW_W
from engine.frontend.backend import pygame
from engine.models import Unit
from src.multiplayer_net import DEFAULT_SERVER_HOST
from src.multiplayer_net import DEFAULT_SERVER_PORT
from src.multiplayer_net import NetworkClient
from src.multiplayer_net import PROTOCOL_VERSION
from typing import List
from typing import Optional
from typing import Tuple
import math
import random
import socket
import time


class ApplicationSystem:
    def _base_init(self):
        from engine.simulation import RealTimeGame

        pygame.init()
        pygame.display.set_caption(APP_TITLE)
        self.display_mode = "windowed"
        self.last_fullscreen_mode = "borderless"
        self.fullscreen = False
        self.window = None
        self.screen = pygame.Surface((WINDOW_W, WINDOW_H))
        self.apply_display_mode()
        self.clock = pygame.time.Clock()
        self.fonts = {
            s: pygame.font.SysFont("consolas", s, bold=s >= 20)
            for s in (12, 14, 16, 20, 26, 36, 48, 60)
        }
        bootstrap_assets_async()
        self.game = RealTimeGame()
        self.state = "menu"
        self.battle_active = False
        self.setup_difficulty = "Hard"
        self.setup_roster = {
            role: DEFAULT_PLAYER_ROSTER.count(role) for role in PLAYER_ROLE_ORDER
        }
        self.battle_roster = list(DEFAULT_PLAYER_ROSTER)
        self.menu_speed = 1.0
        self.menu_show_help = True
        self.show_fps = False
        self.selected: List[int] = []
        self.drag_start: Optional[Tuple[int, int]] = None
        self.drag_additive = False
        self.mouse = (0, 0)
        self.running = True
        self.accum = 0.0
        self.simulation_clock = FixedStepClock(step=SIM_DT, max_steps=8, max_frame=0.25)
        self.speed = 1.0
        self.command_mode = "normal"
        self.cook = 0.0
        self.show_threat = False
        self.show_help = True
        self.formation = "wedge"
        self.control_groups = {i: [] for i in range(1, 10)}
        self.audio_enabled = True
        self.audio = None
        self.blood_sprite = None
        self.asset_refresh_at = 0.0
        self.message = "LMB select • RMB order • ` tactical slow • F1 help"
        self.init_presentation_assets()

    def desktop_size(self):
        try:
            info = pygame.display.Info()
            w = int(getattr(info, "current_w", 0) or 0)
            h = int(getattr(info, "current_h", 0) or 0)
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
        return (WINDOW_W, WINDOW_H)

    def apply_display_mode(self):
        mode = getattr(self, "display_mode", "windowed")
        try:
            if mode == "borderless":
                size = self.desktop_size()
                self.window = pygame.display.set_mode(
                    size, getattr(pygame, "NOFRAME", 0)
                )
            elif mode == "exclusive":
                self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.display_mode = "windowed"
                self.window = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        except pygame.error:
            self.display_mode = "windowed"
            self.window = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.fullscreen = self.display_mode != "windowed"
        if self.fullscreen:
            self.last_fullscreen_mode = self.display_mode

    def _base_set_display_mode(self, mode):
        if mode not in ("windowed", "borderless", "exclusive"):
            return
        self.display_mode = mode
        self.apply_display_mode()

    def cycle_display_mode(self):
        modes = ["windowed", "borderless", "exclusive"]
        self.set_display_mode(modes[(modes.index(self.display_mode) + 1) % len(modes)])

    def toggle_fullscreen(self):
        if self.display_mode == "windowed":
            self.set_display_mode(self.last_fullscreen_mode)
        else:
            self.set_display_mode("windowed")

    def present(self):
        if self.window is None:
            return
        try:
            size = self.window.get_size()
        except Exception:
            size = (WINDOW_W, WINDOW_H)
        if size == (WINDOW_W, WINDOW_H):
            self.window.blit(self.screen, (0, 0))
        else:
            pygame.transform.scale(self.screen, size, self.window)
        pygame.display.flip()

    def current_setup_roster(self) -> List[str]:
        roster = []
        for role in PLAYER_ROLE_ORDER:
            roster.extend([role] * self.setup_roster.get(role, 0))
        return roster[:MAX_PLAYER_UNITS]

    def _base_get_font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.SysFont("consolas", size, bold=size >= 20)
        return self.fonts[size]

    def _base_button(self, rect, label, mouse=None, enabled=True, accent=False):
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
            2,
            border_radius=4,
        )
        surf = self.fonts[20].render(
            label, True, COLORS["white"] if enabled else COLORS["muted"]
        )
        self.screen.blit(
            surf,
            (
                rect.centerx - surf.get_width() // 2,
                rect.centery - surf.get_height() // 2,
            ),
        )

    def main_menu_rects(self):
        w, h = (300, 54)
        x = WINDOW_W // 2 - w // 2
        y = 292
        rects = {}
        if self.battle_active:
            rects["continue"] = pygame.Rect(x, y, w, h)
            y += 64
        rects["play"] = pygame.Rect(x, y, w, h)
        y += 64
        rects["settings"] = pygame.Rect(x, y, w, h)
        y += 64
        rects["help"] = pygame.Rect(x, y, w, h)
        y += 64
        rects["quit"] = pygame.Rect(x, y, w, h)
        return rects

    def _base_setup_rects(self):
        x = WINDOW_W // 2 - 330
        return {
            "easy": pygame.Rect(x, 170, 200, 48),
            "hard": pygame.Rect(x + 230, 170, 200, 48),
            "veteran": pygame.Rect(x + 460, 170, 200, 48),
            "balanced": pygame.Rect(WINDOW_W // 2 - 310, 650, 190, 44),
            "clear": pygame.Rect(WINDOW_W // 2 - 95, 650, 190, 44),
            "start": pygame.Rect(WINDOW_W // 2 + 120, 650, 190, 44),
            "back": pygame.Rect(WINDOW_W // 2 - 95, 708, 190, 42),
        }

    def _base_roster_rects(self):
        rects = {}
        left = 84
        right = WINDOW_W // 2 + 30
        top = 282
        row_h = 55
        for i, role in enumerate(PLAYER_ROLE_ORDER):
            col = 0 if i < 6 else 1
            row = i if i < 6 else i - 6
            x = left if col == 0 else right
            y = top + row * row_h
            rects[role, "minus"] = pygame.Rect(x + 440, y + 6, 36, 34)
            rects[role, "plus"] = pygame.Rect(x + 526, y + 6, 36, 34)
        return rects

    def _base_settings_rects(self):
        x = WINDOW_W // 2 - 330
        return {
            "speed05": pygame.Rect(x, 275, 200, 48),
            "speed1": pygame.Rect(x + 230, 275, 200, 48),
            "speed2": pygame.Rect(x + 460, 275, 200, 48),
            "help": pygame.Rect(WINDOW_W // 2 - 165, 365, 330, 46),
            "audio": pygame.Rect(WINDOW_W // 2 - 165, 423, 330, 46),
            "fps": pygame.Rect(WINDOW_W // 2 - 165, 481, 330, 46),
            "fullscreen": pygame.Rect(WINDOW_W // 2 - 165, 539, 330, 46),
            "back": pygame.Rect(WINDOW_W // 2 - 150, 620, 300, 48),
        }

    def help_menu_rects(self):
        return {"back": pygame.Rect(WINDOW_W // 2 - 150, 710, 300, 46)}

    def _base_start_battle(self):
        from engine.simulation import RealTimeGame

        roster = self.current_setup_roster()
        if not roster:
            self.message = "Choose at least one unit before starting."
            return
        self.battle_roster = list(roster)
        self.game = RealTimeGame(difficulty=self.setup_difficulty, player_roster=roster)
        self.selected = []
        self.command_mode = "normal"
        self.cook = 0.0
        self.show_threat = False
        self.show_help = self.menu_show_help
        self.speed = self.menu_speed
        self.control_groups = {i: [] for i in range(1, 10)}
        self.battle_active = True
        self.state = "game"

    def _base_unit_at_pixel(self, pos) -> Optional[Unit]:
        cell = self.map_cell_from_mouse(pos)
        if not cell:
            return None
        return self.game.unit_at(*cell)

    def cycle_formation(self):
        fs = ["wedge", "line", "column", "spread"]
        self.formation = fs[(fs.index(self.formation) + 1) % len(fs)]

    def cycle_discipline(self, units):
        ds = ["hold", "return", "free", "confident"]
        for u in units:
            u.fire_discipline = ds[(ds.index(u.fire_discipline) + 1) % len(ds)]

    def cycle_priority(self, units):
        ps = ["nearest", "exposed", "specialist", "suppressed"]
        for u in units:
            u.target_priority = ps[(ps.index(u.target_priority) + 1) % len(ps)]

    def _base_command_bar_rects(self):
        labels = [
            "SUPPRESS",
            "OVERWATCH",
            "GRENADE",
            "SMOKE",
            "RELOAD",
            "STANCE",
            "FORMATION",
            "DISCIPLINE",
            "PRIORITY",
            "BOUND",
            "AUTO",
        ]
        w = 104
        gap = 4
        x = MAP_X
        y = MAP_Y + MAP_H * TILE + 8
        return {
            lab: pygame.Rect(x + i * (w + gap), y, w, 32)
            for i, lab in enumerate(labels)
        }

    def _base_cell_rect(self, x, y):
        return pygame.Rect(MAP_X + x * TILE, MAP_Y + y * TILE, TILE, TILE)

    def end_banner(self, text):
        r = pygame.Rect(MAP_X + 300, MAP_Y + 250, 480, 100)
        pygame.draw.rect(self.screen, COLORS["panel"], r)
        pygame.draw.rect(self.screen, COLORS["select"], r, 3)
        self.text(text, (r.x + 160, r.y + 28), 36, "white")

    def _base_run(self):
        while self.running:
            real_dt = min(0.05, self.clock.tick(FPS) / 1000.0)
            for e in pygame.event.get():
                self.handle_event(self.normalize_event_pos(e))
            if self.state == "game" and (not self.game.paused):
                slow = 0.25 if pygame.key.get_pressed()[pygame.K_BACKQUOTE] else 1.0
                self.accum += real_dt * self.speed * slow
                while self.accum >= SIM_DT:
                    self.game.update(SIM_DT)
                    self.accum -= SIM_DT
                for ev in self.game.drain_events():
                    self.play_event(ev)
            if time.time() >= self.asset_refresh_at:
                self.refresh_assets()
                self.asset_refresh_at = time.time() + 2.0
            self.draw()
        pygame.quit()

    def _kz_app_init(self):
        self._base_init()
        self.camera_x = 0.0
        self.camera_y = max(0.0, MAP_H / 2 - 10)
        self.zoom = 1.0
        self.zoom_levels = [0.72, 0.85, 1.0, 1.18, 1.35]
        self.camera_drag = None
        self.preview_cell = None
        self.preview_path = []
        self.preview_at = 0.0
        self.preview_eta = 0.0
        self.seed_text = ""
        self.seed_active = False
        self.setup_reserves = 0
        self.deployment_active = False
        self.show_perf = False
        self.fps_cap = 0
        self.shake_until = 0.0
        self.shake_strength = 0.0
        self.shake_offset = (0, 0)
        self._audio_last = {}
        self._audio_window_start = 0.0
        self._audio_count = 0
        self.after_action_open = False
        self._overlay_cache = {}

    @property
    def tile_px(self):
        return max(14, int(TILE * self.zoom))

    def map_view_rect(self):
        return pygame.Rect(MAP_X, MAP_Y, MAP_VIEW_W_PX, MAP_VIEW_H_PX)

    def world_to_screen(self, x, y):
        tp = self.tile_px
        ox, oy = self.shake_offset
        return (
            int(MAP_X + (x - self.camera_x) * tp + tp / 2 + ox),
            int(MAP_Y + (y - self.camera_y) * tp + tp / 2 + oy),
        )

    def screen_to_world(self, pos):
        if not self.map_view_rect().collidepoint(pos):
            return None
        tp = self.tile_px
        x = self.camera_x + (pos[0] - MAP_X) / tp
        y = self.camera_y + (pos[1] - MAP_Y) / tp
        return (x, y)

    def unit_at_pixel(self, pos):
        best = None
        bd = 999
        for u in self.game.units:
            if not u.alive:
                continue
            if u.faction == "enemy" and (not self.game.visible_to("player", u)):
                continue
            sx, sy = self.world_to_screen(u.x, u.y)
            d = math.hypot(pos[0] - sx, pos[1] - sy)
            if d < max(10, self.tile_px * 0.55) and d < bd:
                best = u
                bd = d
        return best

    def cell_rect(self, x, y):
        tp = self.tile_px
        ox, oy = self.shake_offset
        return pygame.Rect(
            int(MAP_X + (x - self.camera_x) * tp + ox),
            int(MAP_Y + (y - self.camera_y) * tp + oy),
            tp,
            tp,
        )

    def visible_bounds(self):
        tp = self.tile_px
        x0 = max(0, int(math.floor(self.camera_x)) - 1)
        y0 = max(0, int(math.floor(self.camera_y)) - 1)
        x1 = min(MAP_W, int(math.ceil(self.camera_x + MAP_VIEW_W_PX / tp)) + 1)
        y1 = min(MAP_H, int(math.ceil(self.camera_y + MAP_VIEW_H_PX / tp)) + 1)
        return (x0, y0, x1, y1)

    def change_zoom(self, delta, anchor=None):
        old = self.zoom
        idx = min(
            range(len(self.zoom_levels)), key=lambda i: abs(self.zoom_levels[i] - old)
        )
        idx = int(clamp(idx + delta, 0, len(self.zoom_levels) - 1))
        new = self.zoom_levels[idx]
        if new == old:
            return
        anchor = anchor or (MAP_X + MAP_VIEW_W_PX // 2, MAP_Y + MAP_VIEW_H_PX // 2)
        before = self.screen_to_world(anchor)
        self.zoom = new
        if before:
            tp = self.tile_px
            self.camera_x = before[0] - (anchor[0] - MAP_X) / tp
            self.camera_y = before[1] - (anchor[1] - MAP_Y) / tp
        self.clamp_camera()
        self.preview_cell = None

    def setup_rects(self):
        x = WINDOW_W // 2 - 330
        return {
            "easy": pygame.Rect(x, 158, 200, 44),
            "hard": pygame.Rect(x + 230, 158, 200, 44),
            "veteran": pygame.Rect(x + 460, 158, 200, 44),
            "seed": pygame.Rect(x, 226, 300, 38),
            "reserve_minus": pygame.Rect(x + 430, 226, 38, 38),
            "reserve_plus": pygame.Rect(x + 565, 226, 38, 38),
            "balanced": pygame.Rect(WINDOW_W // 2 - 310, 660, 190, 42),
            "clear": pygame.Rect(WINDOW_W // 2 - 95, 660, 190, 42),
            "start": pygame.Rect(WINDOW_W // 2 + 120, 660, 190, 42),
            "back": pygame.Rect(WINDOW_W // 2 - 95, 714, 190, 40),
        }

    def roster_rects(self):
        rects = {}
        left = 74
        right = WINDOW_W // 2 + 25
        top = 286
        row_h = 57
        for i, role in enumerate(PLAYER_ROLE_ORDER):
            col = 0 if i < 6 else 1
            row = i if i < 6 else i - 6
            x = left if col == 0 else right
            y = top + row * row_h
            rects[role, "minus"] = pygame.Rect(x + 438, y + 6, 34, 32)
            rects[role, "plus"] = pygame.Rect(x + 522, y + 6, 34, 32)
        return rects

    def _kz_begin_deployment(self):
        from engine.simulation import RealTimeGame

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
        )
        self.selected = []
        self.command_mode = "normal"
        self.show_threat = False
        self.show_help = False
        self.control_groups = {i: [] for i in range(1, 10)}
        self.deployment_active = True
        self.battle_active = False
        self.state = "deployment"
        self.camera_x = 0
        self.camera_y = max(0, MAP_H / 2 - 10)
        self.clamp_camera()

    def finalize_deployment(self):
        self.deployment_active = False
        self.battle_active = True
        self.state = "game"
        self.game.time = 0
        self.speed = self.menu_speed
        self.show_help = self.menu_show_help
        self.game.add_log("Deployment complete. Battle started.")

    def _kz_deploy_click(self, cell):
        from engine.simulation import RealTimeGame

        if not cell or cell[0] > self.game.deployment_zone_x:
            return
        us = self.selected_units()
        if not us:
            return
        offs = self.game.formation_offsets(len(us), self.formation)
        occupied = {
            u.tile
            for u in self.game.living("player")
            if u.uid not in {x.uid for x in us}
        }
        for u, (ox, oy) in zip(us, offs):
            x = int(clamp(round(cell[0] + ox), 1, self.game.deployment_zone_x))
            y = int(clamp(round(cell[1] + oy), 1, MAP_H - 2))
            if (x, y) in occupied or not self.game.passable(x, y, u):
                continue
            u.x, u.y = (x, y)
            u.path = []
            u.waypoints = []
            u.order = "idle"
            occupied.add((x, y))
        RealTimeGame._kz_rebuild_indexes(self.game)

    def _kz_unit_cards(self):
        units = [u for u in self.game.living("player") if u.combat_effective]
        x = MAP_X
        y = MAP_Y + MAP_VIEW_H_PX + 39
        w = 65
        h = 39
        return [
            (u, pygame.Rect(x + i * (w + 3), y, w, h)) for i, u in enumerate(units[:16])
        ]

    def _kz_squad_rects(self):
        x = MAP_X
        y = MAP_Y + MAP_VIEW_H_PX + 5
        out = {"ALL": pygame.Rect(x, y, 78, 28)}
        squads = sorted(
            set(
                (
                    getattr(u, "squad_id", 0)
                    for u in self.game.living("player")
                    if u.combat_effective
                )
            )
        )
        for i, sq in enumerate(squads[:5]):
            out[sq] = pygame.Rect(x + 86 + i * 88, y, 80, 28)
        return out

    def _kz_command_rects(self):
        labels = [
            "ASSAULT",
            "SUPPRESS",
            "OVERWATCH",
            "GRENADE",
            "SMOKE",
            "RELOAD",
            "STANCE",
            "FORMATION",
            "DISCIPLINE",
            "PRIORITY",
            "BOUND",
            "AUTO",
        ]
        gap = 3
        x = MAP_X
        y = MAP_Y + MAP_VIEW_H_PX + 84
        w = (WINDOW_W - MAP_X * 2 - gap * (len(labels) - 1)) // len(labels)
        return {
            lab: pygame.Rect(x + i * (w + gap), y, w, 31)
            for i, lab in enumerate(labels)
        }

    def update_preview(self):
        if self.state != "game" or not self.selected:
            return
        cell = self.map_cell_from_mouse(self.mouse)
        if not cell:
            return
        now = time.time()
        if cell == self.preview_cell and now - self.preview_at < 0.12:
            return
        self.preview_cell = cell
        self.preview_at = now
        self.preview_path = []
        self.preview_eta = 0
        u = self.selected_units()[0] if self.selected_units() else None
        t = self.game.unit_at(*cell)
        if u and (not t or t.faction != "enemy"):
            self.game._path_budget = max(1, self.game._path_budget)
            path = self.game.find_path(u, cell, u.move_mode)
            self.preview_path = path
            if path:
                cost = 0
                prev = u.tile
                for x, y in path:
                    cost += TERRAIN[self.game.grid[y][x].terrain]["move"]
                    prev = (x, y)
                self.preview_eta = cost / max(
                    0.1, ROLES[u.role]["speed"] * STANCE[u.stance]["speed"]
                )

    def overlay_surface(self, size, color, alpha):
        key = (size, color, int(alpha) // 8)
        surf = self._overlay_cache.get(key)
        if surf is None:
            surf = pygame.Surface(size, pygame.SRCALPHA)
            surf.fill((*color, int(clamp(alpha, 0, 255))))
            self._overlay_cache[key] = surf
            if len(self._overlay_cache) > 96:
                self._overlay_cache.clear()
                self._overlay_cache[key] = surf
        return surf

    def _kz_settings_rects(self):
        x = WINDOW_W // 2 - 330
        return {
            "speed05": pygame.Rect(x, 230, 200, 42),
            "speed1": pygame.Rect(x + 230, 230, 200, 42),
            "speed2": pygame.Rect(x + 460, 230, 200, 42),
            "help": pygame.Rect(WINDOW_W // 2 - 165, 305, 330, 40),
            "audio": pygame.Rect(WINDOW_W // 2 - 165, 353, 330, 40),
            "fps": pygame.Rect(WINDOW_W // 2 - 165, 401, 330, 40),
            "perf": pygame.Rect(WINDOW_W // 2 - 165, 449, 330, 40),
            "fpscap": pygame.Rect(WINDOW_W // 2 - 165, 497, 330, 40),
            "fullscreen": pygame.Rect(WINDOW_W // 2 - 165, 545, 330, 40),
            "back": pygame.Rect(WINDOW_W // 2 - 150, 610, 300, 46),
        }

    def run(self):
        while self.running:
            elapsed = self.clock.tick(self.fps_cap or 0) / 1000.0
            real_dt = min(0.05, elapsed)
            self.mouse = self.display_to_logical(pygame.mouse.get_pos())
            self.update_camera(real_dt)
            if time.time() < self.shake_until:
                self.shake_offset = (
                    random.randint(-int(self.shake_strength), int(self.shake_strength)),
                    random.randint(-int(self.shake_strength), int(self.shake_strength)),
                )
                self.shake_strength = max(1, self.shake_strength * 0.92)
            else:
                self.shake_offset = (0, 0)
                self.shake_strength = 0
            for e in pygame.event.get():
                self.handle_event(e)
            if self.state == "game" and (not self.game.paused):
                slow = 0.25 if pygame.key.get_pressed()[pygame.K_BACKQUOTE] else 1.0
                self.simulation_clock.advance(
                    elapsed, self.game.update, speed=self.speed * slow
                )
                self.accum = self.simulation_clock.accumulator
                for ev in self.game.drain_events():
                    self.play_event(ev)
            else:
                self.simulation_clock.reset()
                self.accum = 0.0
            if time.time() >= self.asset_refresh_at:
                self.refresh_assets()
                self.asset_refresh_at = time.time() + 2.0
            self.draw()
        pygame.quit()

    def _vs_app_init(self):
        self._kz_app_init()
        self.briefing_ready = False
        self._ambience_next = 0.0
        self._ambience_clock = time.perf_counter()
        self._ambient_channel = None
        self._procedural_audio = {}
        self._vs_init_procedural_audio()

    def _vs_prepare_briefing(self):
        from engine.simulation import RealTimeGame

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
        )
        self.selected = []
        self.command_mode = "normal"
        self.show_threat = False
        self.show_help = False
        self.control_groups = {i: [] for i in range(1, 10)}
        self.deployment_active = False
        self.battle_active = False
        self.briefing_ready = True
        self.state = "briefing"
        self.camera_x = 0
        self.camera_y = max(0, MAP_H / 2 - 10)
        self.clamp_camera()

    def begin_deployment_from_briefing(self):
        self.state = "deployment"
        self.deployment_active = True
        self.battle_active = False
        self.briefing_ready = False

    def _vs_listener(self):
        us = self.selected_units()
        if us:
            return (sum((u.x for u in us)) / len(us), sum((u.y for u in us)) / len(us))
        return (
            self.camera_x + MAP_VIEW_W_PX / self.tile_px / 2,
            self.camera_y + MAP_VIEW_H_PX / self.tile_px / 2,
        )

    def _vs_play_channel(self, snd, vol):
        if not snd or vol <= 0.005:
            return
        try:
            ch = snd.play()
            if ch:
                ch.set_volume(clamp(vol, 0, 1))
        except Exception:
            pass

    def _perf_app_init2(self):
        self._vs_app_init()
        self._terrain_cache_surface = None
        self._terrain_cache_key = None
        self._terrain_cache_build_ms = 0.0
        self._dynamic_tiles = []
        self._dynamic_tiles_at = -99.0
        self._text_surface_cache = {}
        self._dust_surface_cache = {}
        self._render_perf = {
            "frame_ms": 0.0,
            "map_ms": 0.0,
            "terrain_ms": 0.0,
            "dynamic_ms": 0.0,
            "units_ms": 0.0,
            "ui_ms": 0.0,
            "visible_units": 0,
            "dynamic_tiles": 0,
        }

    def dust_surface(self, rad, alpha):
        rad = max(2, int(rad))
        a = max(0, min(255, int(alpha) // 16 * 16))
        key = (rad, a)
        surf = self._dust_surface_cache.get(key)
        if surf is None:
            surf = pygame.Surface((rad * 2 + 2, rad * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(surf, (135, 118, 91, a), (rad + 1, rad + 1), rad)
            self._dust_surface_cache[key] = surf
            if len(self._dust_surface_cache) > 160:
                self._dust_surface_cache.clear()
                self._dust_surface_cache[key] = surf
        return surf

    def command_bar_rects(self):
        labels = [
            "ASSAULT",
            "SUPPRESS",
            "OVERWATCH",
            "GRENADE",
            "SMOKE",
            "RELOAD",
            "STANCE",
            "FORMATION",
            "DISCIPLINE",
            "PRIORITY",
            "BOUND",
            "AUTO",
            "HOLD",
            "FALLBACK",
        ]
        gap = 3
        x = MAP_X
        y = MAP_Y + MAP_VIEW_H_PX + 84
        w = (WINDOW_W - MAP_X * 2 - gap * (len(labels) - 1)) // len(labels)
        return {
            lab: pygame.Rect(x + i * (w + gap), y, w, 31)
            for i, lab in enumerate(labels)
        }

    def _qol_marker(self, pos, label, color, shape="circle"):
        x, y = (int(pos[0]), int(pos[1]))
        if shape == "diamond":
            pygame.draw.polygon(
                self.screen, color, ((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y))
            )
            pygame.draw.polygon(
                self.screen,
                COLORS["black"],
                ((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)),
                1,
            )
        else:
            pygame.draw.circle(self.screen, color, (x, y), 8)
            pygame.draw.circle(self.screen, COLORS["black"], (x, y), 8, 1)
        text_surface = self.cached_text_surface(label, 8, "black")
        self.screen.blit(
            text_surface,
            (x - text_surface.get_width() // 2, y - text_surface.get_height() // 2),
        )

    def _qol_app_init(self):
        self.ui_scale = 1.0
        self.large_text = False
        self._qol_last_squad_key = None
        self._qol_last_squad_at = -99.0
        self._perf_app_init2()
        previous_mode = self.display_mode
        if load_user_settings(self):
            _qol_clear_text_caches(self)
            if self.display_mode != previous_mode:
                self.apply_display_mode()

    def get_font(self, size):
        return self._base_get_font(effective_ui_font_size(self, size))

    def button(self, rect, label, mouse=None, enabled=True, accent=False):
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
            (
                rect.centerx - surface.get_width() // 2,
                rect.centery - surface.get_height() // 2,
            ),
        )

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

    def set_display_mode(self, mode):
        result = self._base_set_display_mode(mode)
        save_user_settings(self)
        return result

    def input_display_size(self):
        """Return the coordinate extent used by SDL mouse events."""
        try:
            display_surface = pygame.display.get_surface()
            if display_surface is self.window:
                width, height = pygame.display.get_window_size()
                if width > 0 and height > 0:
                    return (width, height)
        except (AttributeError, pygame.error):
            pass
        try:
            width, height = self.window.get_size()
        except (AttributeError, pygame.error):
            return (WINDOW_W, WINDOW_H)
        if width <= 0 or height <= 0:
            return (WINDOW_W, WINDOW_H)
        return (width, height)

    def _feedback_app_init(self):
        self._qol_app_init()
        self._tactical_audio = {}
        self._tactical_audio_last = {}
        self._tactical_audio_game = id(self.game)
        self._tactical_audio_last_event = (
            self.game.battle_events[-1] if self.game.battle_events else None
        )
        self._tactical_audio_last_event_time = (
            self.game.battle_events[-1].get("time", -99.0)
            if self.game.battle_events
            else -99.0
        )
        self._tactical_audio_stage = getattr(self.game, "battle_stage", "APPROACH")
        self.ensure_tactical_audio()

    def _operation_app_init(self):
        self._feedback_app_init()
        self.setup_mission = "assault"
        self.setup_variant = "auto"
        self.setup_weather = "auto"
        self.setup_enemy_strength = 1.0
        self.setup_defense_duration = 300
        self.build_menu_open = False

    def current_operation_config(self):
        return sanitize_operation_config(
            {
                "mission": self.setup_mission,
                "variant": self.setup_variant,
                "weather": self.setup_weather,
                "enemy_strength": self.setup_enemy_strength,
                "defense_duration": self.setup_defense_duration,
            }
        )

    def operation_setup_button_rect(self):
        return pygame.Rect(WINDOW_W - 314, 714, 260, 40)

    def operation_option_rects(self):
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
                weather_start + index * (weather_width + gap), 370, weather_width, 42
            )
        strength_width = 260
        strength_start = center - (strength_width * 3 + gap * 2) // 2
        for index, value in enumerate(OPERATION_ENEMY_STRENGTHS):
            rects["strength"][value] = pygame.Rect(
                strength_start + index * (strength_width + gap), 478, strength_width, 42
            )
        duration_width = 260
        duration_start = center - (duration_width * 3 + gap * 2) // 2
        for index, value in enumerate(OPERATION_DEFENSE_DURATIONS):
            rects["duration"][value] = pygame.Rect(
                duration_start + index * (duration_width + gap), 586, duration_width, 42
            )
        rects["done"] = pygame.Rect(center - 150, 692, 300, 46)
        return rects

    def _operation_prepare_briefing(self):
        from engine.simulation import RealTimeGame

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

    def deploy_click(self, cell):
        from engine.simulation import RealTimeGame

        if self.game.deployment_zone_side != "east":
            return self._kz_deploy_click(cell)
        if not cell or cell[0] < self.game.defense_deployment_x:
            return
        units = [
            unit
            for unit in self.selected_units()
            if unit.role not in STATIC_WEAPON_ROLES
        ]
        if not units:
            return
        offsets = self.game.formation_offsets(len(units), self.formation)
        moving_ids = {unit.uid for unit in units}
        occupied = {
            unit.tile
            for unit in self.game.living("player")
            if unit.uid not in moving_ids
        }
        for unit, (offset_x, offset_y) in zip(units, offsets):
            x = int(
                clamp(
                    round(cell[0] + offset_x), self.game.defense_deployment_x, MAP_W - 2
                )
            )
            y = int(clamp(round(cell[1] + offset_y), 1, MAP_H - 2))
            if (x, y) in occupied or not self.game.passable(x, y, unit):
                continue
            unit.x, unit.y = (x, y)
            unit.path = []
            unit.waypoints = []
            unit.order = "idle"
            unit.facing = 180
            occupied.add((x, y))
        RealTimeGame._kz_rebuild_indexes(self.game)

    def build_button_rect(self):
        return pygame.Rect(
            SIDEBAR_X + 10, MAP_Y + MAP_VIEW_H_PX - 36, WINDOW_W - SIDEBAR_X - 32, 28
        )

    def build_menu_rects(self):
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
            rects[kind] = pygame.Rect(
                x + 28 + column * (cell_width + 13),
                y + 85 + row * 88,
                cell_width,
                cell_height,
            )
        rects["cancel"] = pygame.Rect(x + width - 132, y + 18, 104, 32)
        rects["panel"] = pygame.Rect(x, y, width, height)
        return rects

    def unit_card_rects(self):
        return [
            (unit, rect)
            for unit, rect in self._kz_unit_cards()
            if unit.role not in STATIC_WEAPON_ROLES
        ]

    def squad_rects(self):
        x = MAP_X
        y = MAP_Y + MAP_VIEW_H_PX + 5
        output = {"ALL": pygame.Rect(x, y, 78, 28)}
        squads = sorted(
            {
                getattr(unit, "squad_id", 0)
                for unit in self.game.living("player")
                if unit.combat_effective
                and unit.role not in STATIC_WEAPON_ROLES
                and (getattr(unit, "squad_id", 0) > 0)
            }
        )
        for index, squad in enumerate(squads[:5]):
            output[squad] = pygame.Rect(x + 86 + index * 88, y, 80, 28)
        return output

    def _network_app_init(self):
        self._operation_app_init()
        self.network = NetworkClient()
        self.network_server_address = f"{DEFAULT_SERVER_HOST}:{DEFAULT_SERVER_PORT}"
        hostname = socket.gethostname().split(".", 1)[0]
        self.network_player_name = (hostname or "Player")[:20]
        self.network_input = None
        self.network_status = "OFFLINE"
        self.network_rooms = []
        self.network_online = 0
        self.network_lobby = None
        self.network_connection_id = None
        self.network_pending_action = None
        self.network_side = None
        self.network_match_active = False
        self.network_match_result = None
        self.network_sequence = 0

    def multiplayer_menu_rect(self):
        return pygame.Rect(WINDOW_W // 2 + 180, 292, 270, 54)

    def network_browser_rects(self):
        left = 190
        width = WINDOW_W - left * 2
        rects = {
            "address": pygame.Rect(left, 145, 520, 44),
            "name": pygame.Rect(left, 209, 360, 44),
            "connect": pygame.Rect(left + 540, 145, 180, 44),
            "refresh": pygame.Rect(left + 740, 145, 180, 44),
            "create": pygame.Rect(left + width - 250, 209, 250, 44),
            "back": pygame.Rect(left, 705, 210, 44),
        }
        for index in range(6):
            rects[f"room:{index}"] = pygame.Rect(left, 310 + index * 58, width, 48)
        return rects

    def network_lobby_rects(self):
        return {
            "ready": pygame.Rect(WINDOW_W // 2 - 270, 635, 250, 50),
            "leave": pygame.Rect(WINDOW_W // 2 + 20, 635, 250, 50),
        }

    def connect_multiplayer(self, pending=None):
        from engine.networking import _network_parse_address

        try:
            host, port = _network_parse_address(self.network_server_address)
            if not 1 <= port <= 65535:
                raise ValueError("port must be between 1 and 65535")
        except (TypeError, ValueError) as exc:
            self.network_status = f"INVALID ADDRESS — {exc}"
            return False
        if self.network.connected:
            self.network.send("list_rooms")
            return True
        if self.network.connecting:
            return False
        self.network_pending_action = pending
        self.network_status = f"CONNECTING TO {host}:{port}..."
        return self.network.connect(host, port, self.network_player_name)

    def create_multiplayer_room(self):
        roster = self.current_setup_roster() or list(NETWORK_PVP_DEFAULT_ROSTER)
        battlefield = (
            self.setup_variant
            if self.setup_variant in NETWORK_PVP_BATTLEFIELDS
            else "farmland"
        )
        self.network.send(
            "create_room",
            name=f"{self.network_player_name}'s battle",
            seed=random.randint(1, 999999999),
            roster=roster,
            battlefield=battlefield,
        )

    def send_network_command(self, action, units=None, **payload):
        if not getattr(self, "network_match_active", False) or not getattr(
            getattr(self, "network", None), "connected", False
        ):
            return False
        unit_ids = [
            unit.uid for unit in (self.selected_units() if units is None else units)
        ]
        if not unit_ids:
            _qol_notify(
                self, "Select one or more units first", kind="danger", duration=1.5
            )
            return False
        self.network_sequence += 1
        self.network.send(
            "command",
            sequence=self.network_sequence,
            action=action,
            units=unit_ids,
            **payload,
        )
        return True

    def process_network_messages(self):
        from engine.networking import _network_normalize_client_factions
        from engine.networking import apply_network_snapshot
        from engine.networking import create_network_pvp_game

        if not hasattr(self, "network"):
            return
        for message in self.network.poll():
            message_type = message.get("type")
            if message_type == "network_connected":
                self.network_status = "CONNECTED — NEGOTIATING"
            elif message_type == "hello_ack":
                if int(message.get("protocol", -1)) != PROTOCOL_VERSION:
                    self.network_status = "PROTOCOL MISMATCH"
                    self.network.close("protocol mismatch")
                    continue
                self.network_connection_id = message.get("connection_id")
                self.network_status = (
                    f"ONLINE · SERVER {message.get('service_version', '?')}"
                )
                if self.network_pending_action == "create":
                    self.create_multiplayer_room()
                else:
                    self.network.send("list_rooms")
                self.network_pending_action = None
            elif message_type == "server_list":
                self.network_rooms = list(message.get("rooms", []))[:6]
                self.network_online = int(
                    message.get("online", self.network_online or 0)
                )
            elif message_type == "room_joined":
                self.state = "multiplayer_lobby"
                self.network_match_result = None
            elif message_type == "lobby_state":
                self.network_lobby = message.get("room")
                if self.network_lobby and self.network_lobby.get("status") == "lobby":
                    self.state = "multiplayer_lobby"
            elif message_type == "room_left":
                self.network_lobby = None
                self.network_match_active = False
                self.state = "multiplayer"
                self.network.send("list_rooms")
            elif message_type == "match_start":
                side = str(message.get("side", "player"))
                game = create_network_pvp_game(
                    seed=int(message.get("seed", 1)),
                    roster=message.get("roster"),
                    battlefield=message.get("battlefield", "farmland"),
                )
                _network_normalize_client_factions(game, side)
                game.network_replica = True
                initial_snapshot = message.get("snapshot", {})
                apply_network_snapshot(game, initial_snapshot)
                for event in initial_snapshot.get("events", []):
                    if isinstance(event, dict):
                        self.play_event(event)
                self.game = game
                self.network_side = side
                self.network_match_active = True
                self.network_match_result = None
                self.battle_active = True
                self.state = "game"
                self.selected = []
                self.command_mode = "normal"
                self.show_help = False
                self.build_menu_open = False
                self.control_groups = {index: [] for index in range(1, 10)}
                if side == "enemy":
                    self.camera_x = MAP_W
                    self.camera_y = MAP_H // 2
                    self.clamp_camera()
            elif message_type == "snapshot" and getattr(
                self, "network_match_active", False
            ):
                state = message.get("state", {})
                apply_network_snapshot(self.game, state)
                for event in state.get("events", []):
                    if isinstance(event, dict):
                        self.play_event(event)
            elif message_type == "match_end":
                self.network_match_active = False
                self.network_match_result = str(message.get("result", "defeat"))
                self.game.victory = self.network_match_result == "victory"
                self.game.defeat = self.network_match_result != "victory"
                _qol_notify(
                    self,
                    f"PVP {self.network_match_result.upper()} — {message.get('reason', 'match ended')}",
                    kind="good" if self.game.victory else "danger",
                    duration=6.0,
                )
            elif message_type == "command_rejected":
                _qol_notify(
                    self,
                    str(message.get("reason", "Command rejected")),
                    kind="danger",
                    duration=1.8,
                )
            elif message_type == "error":
                self.network_status = (
                    f"ERROR — {message.get('message', 'server error')}"
                )
                _qol_notify(
                    self,
                    str(message.get("message", "Server error")),
                    kind="danger",
                    duration=2.5,
                )
            elif message_type == "network_error":
                self.network_status = (
                    f"CONNECTION FAILED — {message.get('message', 'unknown error')}"
                )
            elif message_type == "network_disconnected":
                self.network_status = "DISCONNECTED"
                if getattr(self, "network_match_active", False):
                    self.network_match_active = False
                    self.network_match_result = "disconnected"

    def _edit_network_input(self, event):
        if event.key == pygame.K_BACKSPACE:
            if self.network_input == "address":
                self.network_server_address = self.network_server_address[:-1]
            elif self.network_input == "name":
                self.network_player_name = self.network_player_name[:-1]
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.network_input = None
            return
        text = getattr(event, "unicode", "")
        if not text or not text.isprintable():
            return
        if self.network_input == "address" and len(self.network_server_address) < 64:
            if text.isalnum() or text in ".:-_":
                self.network_server_address += text
        elif self.network_input == "name" and len(self.network_player_name) < 24:
            self.network_player_name += text

    def play_presentation_layer(self, sound, volume, pan=0.0):
        if sound is None or volume <= 0.005 or (not pygame.mixer.get_init()):
            return False
        try:
            channel = pygame.mixer.find_channel(True)
            if channel is None:
                return False
            channel.play(sound)
            pan = clamp(float(pan), -0.82, 0.82)
            if int(pygame.mixer.get_init()[2]) >= 2:
                channel.set_volume(
                    volume * (1.0 - max(0.0, pan)), volume * (1.0 + min(0.0, pan))
                )
            else:
                channel.set_volume(volume)
            return True
        except pygame.error:
            return False

    def _presentation_app_init(self):
        self._network_app_init()
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

    def presentation_listener(self):
        selected = self.selected_units()
        if selected:
            return (
                sum((unit.x for unit in selected)) / len(selected),
                sum((unit.y for unit in selected)) / len(selected),
            )
        return (
            self.camera_x + MAP_VIEW_W_PX / self.tile_px / 2,
            self.camera_y + MAP_VIEW_H_PX / self.tile_px / 2,
        )

    def __init__(self):
        self.camera_shake_enabled = True
        self.edge_scroll_enabled = True
        self.polish_camera_target = None
        self.polish_result_seen_at = None
        self.polish_result_game = None
        self.polish_last_frame_at = time.perf_counter()
        self._polish_shot_window = []
        self._presentation_app_init()

    def start_battle(self, *args, **kwargs):
        self.polish_camera_target = None
        self.polish_result_seen_at = None
        self.polish_result_game = None
        return self._operation_prepare_briefing(*args, **kwargs)

    def settings_rects(self):
        rects = dict(self._qol_settings_rects())
        center = WINDOW_W // 2
        rects["shake"] = pygame.Rect(center - 190, 562, 380, 34)
        rects["edge"] = pygame.Rect(center - 190, 602, 380, 34)
        rects["back"] = pygame.Rect(center - 150, 676, 300, 42)
        return rects
