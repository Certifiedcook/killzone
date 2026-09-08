"""Frontend / controls for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.frontend.support import _qol_clear_text_caches
from engine.frontend.support import _qol_command_label
from engine.frontend.support import _qol_notify
from engine.frontend.support import command_button_status
from engine.frontend.support import save_user_settings
from engine.rules import angle_to
from engine.rules import clamp
from engine.definitions import Coord
from engine.definitions import DEFAULT_PLAYER_ROSTER
from engine.definitions import ENGINEER_BUILD_TYPES
from engine.definitions import MAP_H
from engine.definitions import MAP_VIEW_H_PX
from engine.definitions import MAP_VIEW_W_PX
from engine.definitions import MAP_W
from engine.definitions import MAP_X
from engine.definitions import MAP_Y
from engine.definitions import MAX_PLAYER_UNITS
from engine.definitions import MAX_ROLE_COUNT
from engine.definitions import PLAYER_ROLE_ORDER
from engine.definitions import QOL_TARGET_MODES
from engine.definitions import TILE
from engine.definitions import UI_SCALE_CHOICES
from engine.definitions import WINDOW_H
from engine.definitions import WINDOW_W
from engine.definitions import _FULLSCREEN_LOGICAL_EVENT_FLAG
from engine.frontend.backend import pygame
from engine.models import Unit
from typing import List
from typing import Optional
import math
import time


class ControlsSystem:
    def _base_display_to_logical(self, pos):
        if not self.window:
            return (int(pos[0]), int(pos[1]))
        try:
            w, h = self.window.get_size()
        except Exception:
            w, h = (WINDOW_W, WINDOW_H)
        if w <= 0 or h <= 0:
            return (int(pos[0]), int(pos[1]))
        return (
            int(clamp(pos[0] * WINDOW_W / w, 0, WINDOW_W - 1)),
            int(clamp(pos[1] * WINDOW_H / h, 0, WINDOW_H - 1)),
        )

    def _base_normalize_event_pos(self, e):
        if hasattr(e, "pos"):
            pos = self.display_to_logical(e.pos)
            try:
                e.pos = pos
            except Exception:
                try:
                    e.dict["pos"] = pos
                except Exception:
                    pass
        return e

    def handle_menu_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_RETURN:
                self.state = "setup"
            elif e.key == pygame.K_ESCAPE:
                return
            return
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return
        for name, r in self.main_menu_rects().items():
            if not r.collidepoint(e.pos):
                continue
            if name == "continue":
                self.state = "game"
            elif name == "play":
                self.state = "setup"
            elif name == "settings":
                self.state = "settings"
            elif name == "help":
                self.state = "help"
            elif name == "quit":
                self.running = False
            return

    def _base_handle_setup_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.state = "menu"
            return
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return
        total = sum(self.setup_roster.values())
        for (role, action), r in self.roster_rects().items():
            if not r.collidepoint(e.pos):
                continue
            count = self.setup_roster.get(role, 0)
            if action == "minus" and count > 0:
                self.setup_roster[role] = count - 1
            elif (
                action == "plus"
                and count < MAX_ROLE_COUNT
                and (total < MAX_PLAYER_UNITS)
            ):
                self.setup_roster[role] = count + 1
            return
        for name, r in self.setup_rects().items():
            if not r.collidepoint(e.pos):
                continue
            if name in ("easy", "hard", "veteran"):
                self.setup_difficulty = name.title()
            elif name == "balanced":
                self.setup_roster = {
                    role: DEFAULT_PLAYER_ROSTER.count(role)
                    for role in PLAYER_ROLE_ORDER
                }
            elif name == "clear":
                self.setup_roster = {role: 0 for role in PLAYER_ROLE_ORDER}
            elif name == "start":
                self.start_battle()
            elif name == "back":
                self.state = "menu"
            return

    def _base_handle_settings_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.state = "menu"
            return
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return
        for name, r in self.settings_rects().items():
            if not r.collidepoint(e.pos):
                continue
            if name == "speed05":
                self.menu_speed = 0.5
            elif name == "speed1":
                self.menu_speed = 1.0
            elif name == "speed2":
                self.menu_speed = 2.0
            elif name == "help":
                self.menu_show_help = not self.menu_show_help
            elif name == "audio":
                self.audio_enabled = not self.audio_enabled
            elif name == "fps":
                self.show_fps = not self.show_fps
            elif name == "fullscreen":
                self.toggle_fullscreen()
            elif name == "back":
                self.state = "menu"
            return

    def handle_help_menu_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_F1):
            self.state = "menu"
            return
        if (
            e.type == pygame.MOUSEBUTTONDOWN
            and e.button == 1
            and self.help_menu_rects()["back"].collidepoint(e.pos)
        ):
            self.state = "menu"

    def _base_map_cell_from_mouse(self, pos) -> Optional[Coord]:
        mx, my = pos
        x = (mx - MAP_X) // TILE
        y = (my - MAP_Y) // TILE
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return (int(x), int(y))
        return None

    def selected_units(self) -> List[Unit]:
        out = []
        for uid in self.selected:
            u = self.game.get_unit(uid)
            if u and u.faction == "player" and u.alive:
                out.append(u)
        return out

    def select(self, u: Optional[Unit], add=False):
        if not add:
            self.selected = []
        if u and u.faction == "player":
            if u.uid in self.selected and add:
                self.selected.remove(u.uid)
            elif u.uid not in self.selected:
                self.selected.append(u.uid)

    def _base_handle_command_bar(self, pos):
        us = self.selected_units()
        if not us:
            return False
        for name, r in self.command_bar_rects().items():
            if not r.collidepoint(pos):
                continue
            if name == "SUPPRESS":
                self.command_mode = "suppress"
            elif name == "OVERWATCH":
                cell = self.map_cell_from_mouse(self.mouse)
                if cell:
                    for u in us:
                        self.game.set_overwatch(u, angle_to(u, cell), 90)
            elif name == "GRENADE":
                self.command_mode = "grenade"
            elif name == "SMOKE":
                self.command_mode = "smoke"
            elif name == "RELOAD":
                for u in us:
                    self.game.start_reload(u)
            elif name == "STANCE":
                for u in us:
                    self.game.cycle_stance(u)
            elif name == "FORMATION":
                self.cycle_formation()
            elif name == "DISCIPLINE":
                self.cycle_discipline(us)
            elif name == "PRIORITY":
                self.cycle_priority(us)
            elif name == "BOUND":
                self.command_mode = "bound"
            elif name == "AUTO":
                enabled = not all(
                    (
                        u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic
                        for u in us
                    )
                )
                for u in us:
                    u.auto_reload = enabled
                    u.auto_cover = enabled
                    u.auto_smoke = enabled
                    u.auto_medic = enabled
                self.message = f"Selected-unit autonomy {('ON' if enabled else 'OFF')}"
            return True
        return False

    def _base_handle_key(self, key, mods):
        from engine.simulation import RealTimeGame

        us = self.selected_units()
        if key == pygame.K_ESCAPE:
            self.game.paused = True
            self.state = "menu"
            return
        if key == pygame.K_SPACE:
            self.game.paused = not self.game.paused
        elif key == pygame.K_F1:
            self.show_help = not self.show_help
        elif key == pygame.K_TAB:
            self.show_threat = not self.show_threat
        elif pygame.K_1 <= key <= pygame.K_9:
            num = key - pygame.K_0
            if mods & pygame.KMOD_CTRL:
                self.control_groups[num] = [u.uid for u in us]
            else:
                self.selected = [
                    uid
                    for uid in self.control_groups.get(num, [])
                    if self.game.get_unit(uid) and self.game.get_unit(uid).alive
                ]
        elif key == pygame.K_MINUS:
            self.speed = 0.5
        elif key == pygame.K_EQUALS:
            self.speed = 1.0
        elif key == pygame.K_RIGHTBRACKET:
            self.speed = 2.0
        elif key == pygame.K_F3:
            self.command_mode = "bound"
        elif key == pygame.K_F4:
            self.cycle_formation()
        elif key == pygame.K_F7:
            self.cycle_discipline(us)
        elif key == pygame.K_F8:
            self.cycle_priority(us)
        elif key == pygame.K_F10:
            enabled = (
                not all(
                    (
                        u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic
                        for u in us
                    )
                )
                if us
                else True
            )
            for u in us:
                u.auto_reload = enabled
                u.auto_cover = enabled
                u.auto_smoke = enabled
                u.auto_medic = enabled
        elif key == pygame.K_z:
            for u in us:
                self.game.cycle_stance(u)
        elif key == pygame.K_x:
            for u in us:
                self.game.cycle_move_mode(u)
        elif key == pygame.K_a:
            for u in us:
                u.fire_mode = "aimed"
                u.order = "idle"
                u.aim_progress = 0
        elif key == pygame.K_f:
            for u in us:
                u.fire_mode = "snap"
        elif key == pygame.K_w:
            for u in us:
                u.fire_mode = "rapid"
        elif key == pygame.K_r:
            for u in us:
                self.game.start_reload(u, emergency=bool(mods & pygame.KMOD_SHIFT))
        elif key == pygame.K_j:
            for u in us:
                self.game.clear_jam(u)
        elif key == pygame.K_b:
            for u in us:
                self.game.change_barrel(u)
        elif key == pygame.K_d:
            for u in us:
                self.game.toggle_deploy(u)
        elif key == pygame.K_v:
            for u in us:
                self.game.bayonet_toggle(u)
        elif key == pygame.K_p:
            for u in us:
                self.game.peek(u)
        elif key == pygame.K_g:
            self.command_mode = "grenade"
            self.cook = 0
        elif key == pygame.K_c and mods & pygame.KMOD_SHIFT:
            self.cook = min(1.8, self.cook + 0.6)
            self.command_mode = "grenade"
        elif key == pygame.K_c:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                self.game.coordinated_advance(us, cell)
        elif key == pygame.K_s:
            self.command_mode = "smoke"
        elif key == pygame.K_l:
            self.command_mode = "rifle_grenade"
        elif key == pygame.K_k:
            self.command_mode = "satchel"
        elif key == pygame.K_q:
            self.command_mode = "suppress"
        elif key == pygame.K_m:
            self.command_mode = "mortar"
        elif key == pygame.K_n:
            self.command_mode = "mortar_smoke"
        elif key == pygame.K_h:
            self.command_mode = "support_he"
        elif key == pygame.K_y:
            self.command_mode = "support_smoke"
        elif key == pygame.K_o:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.set_overwatch(u, angle_to(u, cell), 90)
        elif key == pygame.K_i:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.set_fire_lane(u, angle_to(u, cell), 45)
        elif key == pygame.K_e:
            if mods & pygame.KMOD_SHIFT:
                for u in us:
                    self.game.scan_mines(u)
            else:
                cell = self.map_cell_from_mouse(self.mouse)
                if cell:
                    c = self.game.grid[cell[1]][cell[0]]
                    kind = (
                        "cut"
                        if c.terrain == "wire"
                        else "clear_mine"
                        if c.mine
                        else "fortify"
                    )
                    for u in us:
                        self.game.engineer_action(u, cell, kind)
        elif key == pygame.K_t:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.engineer_action(u, cell, "trench")
        elif key == pygame.K_u:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.engineer_action(u, cell, "bangalore")
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.toggle_door(u, cell)
        elif key == pygame.K_F9:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                t = self.game.unit_at(*cell)
                if t and t.faction == "player":
                    for u in us:
                        if u.uid != t.uid:
                            self.game.share_ammo(u, t)
        elif key == pygame.K_4:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                for u in us:
                    self.game.engineer_action(u, cell, "wire")
        elif key == pygame.K_F5:
            self.game = RealTimeGame(
                difficulty=self.game.difficulty, player_roster=self.battle_roster
            )
            self.selected = []
        elif key == pygame.K_F6:
            ds = ["Easy", "Hard", "Veteran"]
            d = ds[(ds.index(self.game.difficulty) + 1) % 3]
            self.game = RealTimeGame(difficulty=d, player_roster=self.battle_roster)
            self.selected = []
        elif key == pygame.K_BACKSPACE:
            for u in us:
                u.order = "idle"
                u.path = []
                u.waypoints = []
                u.target_uid = None

    def _base_handle_event(self, e):
        if e.type == pygame.MOUSEMOTION:
            self.mouse = e.pos
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if self.state == "menu":
            self.handle_menu_event(e)
            return
        if self.state == "setup":
            self.handle_setup_event(e)
            return
        if self.state == "settings":
            self.handle_settings_event(e)
            return
        if self.state == "help":
            self.handle_help_menu_event(e)
            return
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 1:
                if self.handle_command_bar(e.pos):
                    return
                if self.map_cell_from_mouse(e.pos) is not None:
                    self.drag_start = e.pos
                    self.drag_additive = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                    u = self.unit_at_pixel(e.pos)
                    if u:
                        self.select(u, self.drag_additive)
                    elif not self.drag_additive:
                        self.selected = []
            elif e.button == 3:
                cell = self.map_cell_from_mouse(e.pos)
                if cell:
                    self.issue_context_command(
                        cell, pygame.key.get_mods() & pygame.KMOD_SHIFT
                    )
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if (
                self.drag_start
                and max(
                    abs(e.pos[0] - self.drag_start[0]),
                    abs(e.pos[1] - self.drag_start[1]),
                )
                > 8
            ):
                map_rect = pygame.Rect(MAP_X, MAP_Y, MAP_W * TILE, MAP_H * TILE)
                sx, sy = self.drag_start
                ex, ey = e.pos
                sx = int(clamp(sx, map_rect.left, map_rect.right))
                ex = int(clamp(ex, map_rect.left, map_rect.right))
                sy = int(clamp(sy, map_rect.top, map_rect.bottom))
                ey = int(clamp(ey, map_rect.top, map_rect.bottom))
                x1, x2 = sorted((sx, ex))
                y1, y2 = sorted((sy, ey))
                if not self.drag_additive:
                    self.selected = []
                for u in self.game.living("player"):
                    px = MAP_X + u.x * TILE + TILE / 2
                    py = MAP_Y + u.y * TILE + TILE / 2
                    if (
                        x1 <= px <= x2
                        and y1 <= py <= y2
                        and (u.uid not in self.selected)
                    ):
                        self.selected.append(u.uid)
            self.drag_start = None
            self.drag_additive = False
        elif e.type == pygame.KEYDOWN:
            self.handle_key(e.key, e.mod)

    def clamp_camera(self):
        tp = self.tile_px
        vw = MAP_VIEW_W_PX / tp
        vh = MAP_VIEW_H_PX / tp
        self.camera_x = clamp(self.camera_x, 0, max(0, MAP_W - vw))
        self.camera_y = clamp(self.camera_y, 0, max(0, MAP_H - vh))

    def map_cell_from_mouse(self, pos):
        w = self.screen_to_world(pos)
        if not w:
            return None
        x = int(math.floor(w[0]))
        y = int(math.floor(w[1]))
        return (x, y) if 0 <= x < MAP_W and 0 <= y < MAP_H else None

    def _kz_focus_selected(self):
        us = self.selected_units()
        if not us:
            return
        cx = sum((u.x for u in us)) / len(us)
        cy = sum((u.y for u in us)) / len(us)
        tp = self.tile_px
        self.camera_x = cx - MAP_VIEW_W_PX / tp / 2
        self.camera_y = cy - MAP_VIEW_H_PX / tp / 2
        self.clamp_camera()

    def _kz_update_camera(self, dt):
        if self.state not in ("game", "deployment"):
            return
        keys = pygame.key.get_pressed()
        speed = 13 * dt / max(0.72, self.zoom)
        if keys[pygame.K_LEFT]:
            self.camera_x -= speed
        if keys[pygame.K_RIGHT]:
            self.camera_x += speed
        if keys[pygame.K_UP]:
            self.camera_y -= speed
        if keys[pygame.K_DOWN]:
            self.camera_y += speed
        mx, my = self.mouse
        mr = self.map_view_rect()
        edge = 8
        if mr.collidepoint(self.mouse) and (not self.drag_start):
            if mx < mr.left + edge:
                self.camera_x -= speed * 0.7
            elif mx > mr.right - edge:
                self.camera_x += speed * 0.7
            if my < mr.top + edge:
                self.camera_y -= speed * 0.7
            elif my > mr.bottom - edge:
                self.camera_y += speed * 0.7
        self.clamp_camera()

    def handle_setup_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.state = "menu"
                self.seed_active = False
                return
            if self.seed_active:
                if e.key == pygame.K_BACKSPACE:
                    self.seed_text = self.seed_text[:-1]
                elif e.key == pygame.K_RETURN:
                    self.seed_active = False
                elif e.unicode.isdigit() and len(self.seed_text) < 9:
                    self.seed_text += e.unicode
                return
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return
        if self.setup_rects()["seed"].collidepoint(e.pos):
            self.seed_active = True
            return
        self.seed_active = False
        total = sum(self.setup_roster.values())
        for (role, action), r in self.roster_rects().items():
            if r.collidepoint(e.pos):
                cnt = self.setup_roster.get(role, 0)
                if action == "minus" and cnt > 0:
                    self.setup_roster[role] = cnt - 1
                    self.setup_reserves = min(self.setup_reserves, max(0, total - 2))
                elif (
                    action == "plus"
                    and cnt < MAX_ROLE_COUNT
                    and (total < MAX_PLAYER_UNITS)
                ):
                    self.setup_roster[role] = cnt + 1
                return
        for name, r in self.setup_rects().items():
            if not r.collidepoint(e.pos):
                continue
            if name in ("easy", "hard", "veteran"):
                self.setup_difficulty = name.title()
            elif name == "balanced":
                self.setup_roster = {
                    role: DEFAULT_PLAYER_ROSTER.count(role)
                    for role in PLAYER_ROLE_ORDER
                }
                self.setup_reserves = 0
            elif name == "clear":
                self.setup_roster = {role: 0 for role in PLAYER_ROLE_ORDER}
                self.setup_reserves = 0
            elif name == "reserve_minus":
                self.setup_reserves = max(0, self.setup_reserves - 1)
            elif name == "reserve_plus":
                self.setup_reserves = min(6, max(0, total - 1), self.setup_reserves + 1)
            elif name == "start":
                self.start_battle()
            elif name == "back":
                self.state = "menu"
            return

    def _kz_handle_command_bar(self, pos):
        us = self.selected_units()
        for name, r in self.command_bar_rects().items():
            if not r.collidepoint(pos):
                continue
            if name == "ASSAULT":
                self.command_mode = "assault"
            elif not us:
                return True
            elif name == "SUPPRESS":
                self.command_mode = "suppress"
            elif name == "OVERWATCH":
                for u in us:
                    self.game.set_overwatch(
                        u,
                        angle_to(u, self.map_cell_from_mouse(self.mouse) or u.tile),
                        100,
                    )
            elif name == "GRENADE":
                self.command_mode = "grenade"
            elif name == "SMOKE":
                self.command_mode = "smoke"
            elif name == "RELOAD":
                for u in us:
                    self.game.start_reload(u)
            elif name == "STANCE":
                for u in us:
                    self.game.cycle_stance(u)
            elif name == "FORMATION":
                self.cycle_formation()
            elif name == "DISCIPLINE":
                self.cycle_discipline(us)
            elif name == "PRIORITY":
                self.cycle_priority(us)
            elif name == "BOUND":
                self.command_mode = "bound"
            elif name == "AUTO":
                new = not all(
                    (
                        u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic
                        for u in us
                    )
                )
                for u in us:
                    u.auto_reload = u.auto_cover = u.auto_smoke = u.auto_medic = new
            return True
        return False

    def _kz_handle_deployment_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.finalize_deployment()
                return
            if e.key == pygame.K_ESCAPE:
                self.state = "setup"
                return
            if e.key == pygame.K_F11:
                self.toggle_fullscreen()
                return
            if e.key == pygame.K_F4:
                self.cycle_formation()
                return
        if e.type == pygame.MOUSEWHEEL:
            self.change_zoom(-1 if e.y < 0 else 1, self.mouse)
            return
        if e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 2:
                self.camera_drag = (e.pos, self.camera_x, self.camera_y)
                return
            if e.button == 1:
                for u, r in self.unit_card_rects():
                    if r.collidepoint(e.pos):
                        self.select(
                            u, add=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                        )
                        return
                for key, r in self.squad_rects().items():
                    if r.collidepoint(e.pos):
                        if key == "ALL":
                            self.selected = [
                                u.uid
                                for u in self.game.living("player")
                                if u.combat_effective
                            ]
                        else:
                            self.selected = [
                                u.uid
                                for u in self.game.living("player")
                                if u.combat_effective
                                and getattr(u, "squad_id", 0) == key
                            ]
                        return
                u = self.unit_at_pixel(e.pos)
                if u and u.faction == "player":
                    self.select(u, add=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
                    return
                self.drag_start = e.pos
                self.drag_additive = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            elif e.button == 3:
                self.deploy_click(self.map_cell_from_mouse(e.pos))
                return
        if e.type == pygame.MOUSEBUTTONUP:
            if e.button == 2:
                self.camera_drag = None
                return
            if e.button == 1 and self.drag_start:
                x1, x2 = sorted((self.drag_start[0], e.pos[0]))
                y1, y2 = sorted((self.drag_start[1], e.pos[1]))
                if max(x2 - x1, y2 - y1) > 5:
                    if not self.drag_additive:
                        self.selected = []
                    for u in self.game.living("player"):
                        sx, sy = self.world_to_screen(u.x, u.y)
                        if (
                            x1 <= sx <= x2
                            and y1 <= sy <= y2
                            and (u.uid not in self.selected)
                        ):
                            self.selected.append(u.uid)
                self.drag_start = None
                self.drag_additive = False
        if e.type == pygame.MOUSEMOTION and self.camera_drag:
            (sx, sy), cx, cy = self.camera_drag
            tp = self.tile_px
            self.camera_x = cx - (e.pos[0] - sx) / tp
            self.camera_y = cy - (e.pos[1] - sy) / tp
            self.clamp_camera()

    def _kz_handle_event(self, e):
        self.mouse = self.display_to_logical(pygame.mouse.get_pos())
        if self.state == "deployment":
            return self.handle_deployment_event(e)
        if self.state in ("menu", "setup", "settings", "help"):
            return self._base_handle_event(e)
        if e.type == pygame.MOUSEWHEEL:
            self.change_zoom(-1 if e.y < 0 else 1, self.mouse)
            return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.drag_start:
            if (
                max(
                    abs(e.pos[0] - self.drag_start[0]),
                    abs(e.pos[1] - self.drag_start[1]),
                )
                > 8
            ):
                mr = self.map_view_rect()
                sx = int(clamp(self.drag_start[0], mr.left, mr.right))
                sy = int(clamp(self.drag_start[1], mr.top, mr.bottom))
                ex = int(clamp(e.pos[0], mr.left, mr.right))
                ey = int(clamp(e.pos[1], mr.top, mr.bottom))
                x1, x2 = sorted((sx, ex))
                y1, y2 = sorted((sy, ey))
                if not self.drag_additive:
                    self.selected = []
                for u in self.game.living("player"):
                    px, py = self.world_to_screen(u.x, u.y)
                    if (
                        x1 <= px <= x2
                        and y1 <= py <= y2
                        and (u.uid not in self.selected)
                    ):
                        self.selected.append(u.uid)
            self.drag_start = None
            self.drag_additive = False
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 2:
            self.camera_drag = (e.pos, self.camera_x, self.camera_y)
            return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 2:
            self.camera_drag = None
            return
        if e.type == pygame.MOUSEMOTION and self.camera_drag:
            (sx, sy), cx, cy = self.camera_drag
            tp = self.tile_px
            self.camera_x = cx - (e.pos[0] - sx) / tp
            self.camera_y = cy - (e.pos[1] - sy) / tp
            self.clamp_camera()
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for u, r in self.unit_card_rects():
                if r.collidepoint(e.pos):
                    self.select(u, add=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
                    return
            for key, r in self.squad_rects().items():
                if r.collidepoint(e.pos):
                    if key == "ALL":
                        self.selected = [
                            u.uid
                            for u in self.game.living("player")
                            if u.combat_effective
                        ]
                    else:
                        self.selected = [
                            u.uid
                            for u in self.game.living("player")
                            if u.combat_effective and getattr(u, "squad_id", 0) == key
                        ]
                    return
        self._base_handle_event(e)

    def _kz_handle_key(self, key, mods):
        from engine.simulation import RealTimeGame

        if key == pygame.K_HOME:
            self.focus_selected()
            return
        if key == pygame.K_F2:
            self.command_mode = "assault"
            return
        if key == pygame.K_F12:
            new = self.game.deploy_player_reserves()
            self.selected = [u.uid for u in new]
            return
        if key == pygame.K_F9 and (not mods & pygame.KMOD_SHIFT):
            self.show_perf = not self.show_perf
            return
        if pygame.K_1 <= key <= pygame.K_5 and mods & pygame.KMOD_ALT:
            sq = key - pygame.K_0
            for u in self.selected_units():
                u.squad_id = sq
            self.message = f"Assigned selection to Squad {chr(64 + sq)}"
            return
        if key == pygame.K_F5:
            self.game = RealTimeGame(
                difficulty=self.game.difficulty,
                player_roster=self.battle_roster,
                reserve_count=self.setup_reserves,
            )
            self.selected = []
            self.camera_x = 0
            self.camera_y = max(0, MAP_H / 2 - 10)
            return
        if key == pygame.K_F6:
            ds = ["Easy", "Hard", "Veteran"]
            d = ds[(ds.index(self.game.difficulty) + 1) % 3]
            self.game = RealTimeGame(
                difficulty=d,
                player_roster=self.battle_roster,
                reserve_count=self.setup_reserves,
            )
            self.selected = []
            self.camera_x = 0
            self.camera_y = max(0, MAP_H / 2 - 10)
            return
        self._base_handle_key(key, mods)

    def _kz_handle_settings(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.state = "menu"
            return
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return
        for name, r in self.settings_rects().items():
            if not r.collidepoint(e.pos):
                continue
            if name == "speed05":
                self.menu_speed = 0.5
            elif name == "speed1":
                self.menu_speed = 1.0
            elif name == "speed2":
                self.menu_speed = 2.0
            elif name == "help":
                self.menu_show_help = not self.menu_show_help
            elif name == "audio":
                self.audio_enabled = not self.audio_enabled
            elif name == "fps":
                self.show_fps = not self.show_fps
            elif name == "perf":
                self.show_perf = not self.show_perf
            elif name == "fpscap":
                caps = [0, 60, 120, 240]
                self.fps_cap = caps[(caps.index(self.fps_cap) + 1) % len(caps)]
            elif name == "fullscreen":
                self.cycle_display_mode()
            elif name == "back":
                self.state = "menu"
            return

    def handle_briefing_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.state = "setup"
                return
            if e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.begin_deployment_from_briefing()
                return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            deploy = pygame.Rect(WINDOW_W // 2 - 150, 690, 300, 46)
            back = pygame.Rect(34, 690, 180, 42)
            if deploy.collidepoint(e.pos):
                self.begin_deployment_from_briefing()
            elif back.collidepoint(e.pos):
                self.state = "setup"

    def _vs_handle_event2(self, e):
        if self.state == "briefing":
            return self.handle_briefing_event(e)
        return self._kz_handle_event(e)

    def _perf_handle_command_bar2(self, pos):
        us = self.selected_units()
        for name, r in self.command_bar_rects().items():
            if not r.collidepoint(pos):
                continue
            if name == "ASSAULT":
                self.command_mode = "assault"
            elif not us:
                return True
            elif name == "SUPPRESS":
                self.command_mode = "suppress"
            elif name == "OVERWATCH":
                for u in us:
                    self.game.set_overwatch(
                        u,
                        angle_to(u, self.map_cell_from_mouse(self.mouse) or u.tile),
                        100,
                    )
            elif name == "GRENADE":
                self.command_mode = "grenade"
            elif name == "SMOKE":
                self.command_mode = "smoke"
            elif name == "RELOAD":
                for u in us:
                    self.game.start_reload(u)
            elif name == "STANCE":
                for u in us:
                    self.game.cycle_stance(u)
            elif name == "FORMATION":
                self.cycle_formation()
            elif name == "DISCIPLINE":
                self.cycle_discipline(us)
            elif name == "PRIORITY":
                self.cycle_priority(us)
            elif name == "BOUND":
                self.command_mode = "bound"
            elif name == "AUTO":
                new = not all(
                    (
                        u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic
                        for u in us
                    )
                )
                for u in us:
                    u.auto_reload = u.auto_cover = u.auto_smoke = u.auto_medic = new
            elif name == "HOLD":
                new = not all((getattr(u, "hold_position", False) for u in us))
                for u in us:
                    u.hold_position = new
                self.message = (
                    "Hold position enabled" if new else "Hold position released"
                )
            elif name == "FALLBACK":
                self.command_mode = "fallback"
            return True
        return False

    def _perf_handle_key2(self, key, mods):
        self._kz_handle_key(key, mods)
        if hasattr(self, "game"):
            self.game.profile_enabled = bool(self.show_perf)

    def _perf_settings_event2(self, e):
        self._kz_handle_settings(e)
        if hasattr(self, "game"):
            self.game.profile_enabled = bool(self.show_perf)

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

    def _maintenance_handle_key(self, key, mods):
        if pygame.K_1 <= key <= pygame.K_9:
            number = key - pygame.K_0
            if not mods & (pygame.KMOD_ALT | pygame.KMOD_CTRL | pygame.KMOD_SHIFT):
                self.select_squad_number(number)
                return
            if mods & pygame.KMOD_ALT and number > 5:
                return
        return self._perf_handle_key2(key, mods)

    def handle_deployment_event(self, event):
        if event.type == pygame.KEYDOWN and pygame.K_1 <= event.key <= pygame.K_9:
            mods = getattr(event, "mod", 0)
            if not mods & (pygame.KMOD_ALT | pygame.KMOD_CTRL | pygame.KMOD_SHIFT):
                self.select_squad_number(event.key - pygame.K_0)
                return
        return self._kz_handle_deployment_event(event)

    def _maintenance_handle_command_bar(self, pos):
        overwatch = self.command_bar_rects().get("OVERWATCH")
        if overwatch and overwatch.collidepoint(pos):
            if self.selected_units():
                self.command_mode = "overwatch"
                self.message = "OVERWATCH — right-click a facing point"
            return True
        return self._perf_handle_command_bar2(pos)

    def _qol_handle_command_bar(self, pos):
        clicked = next(
            (
                button
                for button, rect in self.command_bar_rects().items()
                if rect.collidepoint(pos)
            ),
            None,
        )
        if clicked is None:
            return self._maintenance_handle_command_bar(pos)
        enabled, reason = command_button_status(self, clicked)
        if not enabled:
            _qol_notify(self, reason, kind="danger", duration=2.2)
            return True
        handled = self._maintenance_handle_command_bar(pos)
        if not handled:
            return False
        if clicked in QOL_TARGET_MODES:
            _qol_notify(
                self, f"{clicked} ready — right-click the battlefield", duration=2.0
            )
        else:
            label = _qol_command_label(self, clicked, self.selected_units())
            _qol_notify(self, f"{clicked}: {label}", duration=1.5)
        return True

    def select_squad_number(self, squad_id):
        now = time.perf_counter()
        double_tap = (
            getattr(self, "_qol_last_squad_key", None) == squad_id
            and now - getattr(self, "_qol_last_squad_at", -99.0) <= 0.42
        )
        selected = self._maintenance_select_squad_number(squad_id)
        if selected:
            self._qol_last_squad_key = squad_id
            self._qol_last_squad_at = now
            letter = chr(64 + min(26, int(squad_id)))
            if double_tap:
                self.focus_selected()
                _qol_notify(self, f"Squad {letter} selected and focused", duration=1.4)
            else:
                _qol_notify(
                    self,
                    f"Squad {letter} selected — tap {squad_id} again to focus",
                    duration=1.4,
                )
        else:
            _qol_notify(
                self, f"Squad {squad_id} is not deployed", kind="danger", duration=1.5
            )
        return selected

    def select_units_by_status(self, status):
        active = [unit for unit in self.game.living("player") if unit.combat_effective]
        if status == "wounded":
            matches = [
                unit
                for unit in active
                if unit.casualty == "wounded" or unit.hp < unit.max_hp
            ]
        elif status == "pinned":
            matches = [
                unit
                for unit in active
                if getattr(unit, "morale_state", "")
                in ("PINNED", "BREAKING", "ROUTING")
                or unit.suppression >= 80
            ]
        else:
            matches = [
                unit
                for unit in active
                if unit.order == "idle"
                and unit.action_timer <= 0
                and (unit.reload_timer <= 0)
            ]
        if matches:
            self.selected = [unit.uid for unit in matches]
            _qol_notify(
                self, f"Selected {len(matches)} {status} troop(s)", duration=1.5
            )
            return True
        _qol_notify(self, f"No {status} troops available", kind="danger", duration=1.5)
        return False

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
        return self._maintenance_handle_key(key, mods)

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
            (
                name
                for name, rect in self.settings_rects().items()
                if rect.collidepoint(event.pos)
            ),
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
            index = min(
                range(len(UI_SCALE_CHOICES)),
                key=lambda i: abs(UI_SCALE_CHOICES[i] - self.ui_scale),
            )
            self.ui_scale = UI_SCALE_CHOICES[(index + 1) % len(UI_SCALE_CHOICES)]
            _qol_clear_text_caches(self)
        elif clicked == "largetext":
            self.large_text = not self.large_text
            _qol_clear_text_caches(self)
        elif clicked == "back":
            self.state = "menu"
        save_user_settings(self)

    def _qol_accessibility_handle_key(self, key, mods):
        result = self._qol_handle_key(key, mods)
        if key == pygame.K_F9:
            save_user_settings(self)
        return result

    def display_to_logical(self, pos):
        width, height = self.input_display_size()
        return (
            int(clamp(pos[0] * WINDOW_W / width, 0, WINDOW_W - 1)),
            int(clamp(pos[1] * WINDOW_H / height, 0, WINDOW_H - 1)),
        )

    def normalize_event_pos(self, event):
        event_data = getattr(event, "dict", None)
        if isinstance(event_data, dict) and event_data.get(
            _FULLSCREEN_LOGICAL_EVENT_FLAG
        ):
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

    def _fullscreen_handle_event(self, event):
        event = self.normalize_event_pos(event)
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
        return self._vs_handle_event2(event)

    def handle_operation_setup(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if event.type == pygame.KEYDOWN and event.key in (
            pygame.K_ESCAPE,
            pygame.K_RETURN,
        ):
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

    def cycle_selected_doctrine(self, units=None):
        units = self.selected_units() if units is None else units
        doctrine = self.game.cycle_squad_doctrine(units)
        if doctrine is None:
            _qol_notify(
                self,
                "Select a mobile squad to change doctrine",
                kind="danger",
                duration=1.8,
            )
            return None
        _qol_notify(
            self, f"Squad doctrine: {doctrine.upper()}", kind="good", duration=2.0
        )
        return doctrine

    def handle_build_menu(self, event):
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
        if rects["cancel"].collidepoint(event.pos) or not rects["panel"].collidepoint(
            event.pos
        ):
            self.build_menu_open = False
            return True
        for kind in ENGINEER_BUILD_TYPES:
            if rects[kind].collidepoint(event.pos):
                if not any(
                    (
                        unit.role == "Engineer" and unit.combat_effective
                        for unit in self.game.living("player")
                    )
                ):
                    _qol_notify(
                        self, "No engineer is available", kind="danger", duration=1.8
                    )
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

    def _operation_handle_event(self, event):
        event = self.normalize_event_pos(event)
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
        if self.state == "operation_setup":
            return self.handle_operation_setup(event)
        if (
            self.state == "setup"
            and event.type == pygame.MOUSEBUTTONDOWN
            and (event.button == 1)
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
                        _qol_notify(
                            self,
                            "Construction begins after deployment",
                            kind="danger",
                            duration=1.8,
                        )
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
                if (
                    event.button == 1
                    and self.state == "game"
                    and self.command_mode.startswith("build:")
                ):
                    cell = self.map_cell_from_mouse(event.pos)
                    if cell is not None:
                        self.issue_context_command(cell)
                        return
                if event.button == 1 and self.build_button_rect().collidepoint(
                    event.pos
                ):
                    if self.state == "deployment":
                        _qol_notify(
                            self,
                            "Construction begins after deployment",
                            kind="danger",
                            duration=1.8,
                        )
                    elif any(
                        (
                            unit.role == "Engineer" and unit.combat_effective
                            for unit in self.game.living("player")
                        )
                    ):
                        self.show_help = False
                        self.build_menu_open = True
                    else:
                        _qol_notify(
                            self,
                            "No engineer is available",
                            kind="danger",
                            duration=1.8,
                        )
                    return
                if event.button == 3:
                    for squad_id, rect in self.squad_rects().items():
                        if squad_id != "ALL" and rect.collidepoint(event.pos):
                            members = [
                                unit
                                for unit in self.game.living("player")
                                if unit.combat_effective
                                and getattr(unit, "squad_id", 0) == squad_id
                            ]
                            self.cycle_selected_doctrine(members)
                            return
        return self._fullscreen_handle_event(event)

    def handle_multiplayer_browser(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F11:
                self.toggle_fullscreen()
            elif event.key == pygame.K_ESCAPE:
                self.state = "menu"
                self.network_input = None
            elif self.network_input:
                self._edit_network_input(event)
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        rects = self.network_browser_rects()
        if rects["address"].collidepoint(event.pos):
            self.network_input = "address"
        elif rects["name"].collidepoint(event.pos):
            self.network_input = "name"
        else:
            self.network_input = None
        if rects["connect"].collidepoint(event.pos):
            self.connect_multiplayer()
        elif rects["refresh"].collidepoint(event.pos) and self.network.connected:
            self.network.send("list_rooms")
        elif rects["create"].collidepoint(event.pos):
            if self.network.connected:
                self.create_multiplayer_room()
            else:
                self.connect_multiplayer(pending="create")
        elif rects["back"].collidepoint(event.pos):
            self.state = "menu"
        for index, room in enumerate(self.network_rooms[:6]):
            rect = rects[f"room:{index}"]
            join_rect = pygame.Rect(rect.right - 138, rect.y + 7, 124, 34)
            if join_rect.collidepoint(event.pos) and room.get("status") == "lobby":
                self.network.send("join_room", room_id=room.get("id"), password="")
                return

    def handle_multiplayer_lobby(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,):
            self.network.send("leave_room")
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        rects = self.network_lobby_rects()
        if rects["leave"].collidepoint(event.pos):
            self.network.send("leave_room")
        elif rects["ready"].collidepoint(event.pos):
            players = (self.network_lobby or {}).get("players", [])
            me = next(
                (
                    item
                    for item in players
                    if item.get("id") == self.network_connection_id
                ),
                None,
            )
            self.network.send("ready", ready=not bool(me and me.get("ready")))

    def handle_event(self, event):
        event = self.normalize_event_pos(event)
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
        if event.type == pygame.QUIT:
            self.network.close("game closed")
        if (
            self.state == "menu"
            and event.type == pygame.MOUSEBUTTONDOWN
            and (event.button == 1)
        ):
            if self.multiplayer_menu_rect().collidepoint(event.pos):
                self.state = "multiplayer"
                self.network_status = "ONLINE" if self.network.connected else "OFFLINE"
                return
        if self.state == "multiplayer":
            return self.handle_multiplayer_browser(event)
        if self.state == "multiplayer_lobby":
            return self.handle_multiplayer_lobby(event)
        if (
            self.state == "game"
            and getattr(self, "network_match_result", None)
            and (event.type == pygame.KEYDOWN)
        ):
            if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                self.network.send("leave_room")
                self.network_lobby = None
                self.state = "multiplayer"
                return
        if (
            self.state == "game"
            and getattr(self, "network_match_active", False)
            and (event.type == pygame.KEYDOWN)
        ):
            mods = getattr(event, "mod", pygame.key.get_mods())
            if event.key == pygame.K_d and mods & pygame.KMOD_SHIFT:
                self.send_network_command("doctrine")
                return
        return self._operation_handle_event(event)

    def handle_command_bar(self, pos):
        if not getattr(self, "network_match_active", False):
            return self._qol_handle_command_bar(pos)
        clicked = next(
            (
                name
                for name, rect in self.command_bar_rects().items()
                if rect.collidepoint(pos)
            ),
            None,
        )
        if clicked is None:
            return False
        units = self.selected_units()
        if not units:
            return True
        if clicked in QOL_TARGET_MODES:
            self.command_mode = QOL_TARGET_MODES[clicked]
        elif clicked == "RELOAD":
            self.send_network_command("reload", units)
        elif clicked == "STANCE":
            self.send_network_command("stance", units)
        elif clicked == "FORMATION":
            self.cycle_formation()
        elif clicked == "DISCIPLINE":
            self.send_network_command("discipline", units)
        elif clicked == "PRIORITY":
            self.send_network_command("priority", units)
        elif clicked == "AUTO":
            enabled = not all(
                (
                    unit.auto_reload
                    and unit.auto_cover
                    and unit.auto_smoke
                    and unit.auto_medic
                    for unit in units
                )
            )
            self.send_network_command("autonomy", units, enabled=enabled)
        elif clicked == "HOLD":
            self.send_network_command(
                "hold", units, enabled=not all((unit.hold_position for unit in units))
            )
        else:
            return self._qol_handle_command_bar(pos)
        return True

    def handle_key(self, key, mods):
        if not getattr(self, "network_match_active", False):
            return self._qol_accessibility_handle_key(key, mods)
        units = self.selected_units()
        if key == pygame.K_SPACE:
            _qol_notify(
                self,
                "Multiplayer matches cannot be paused",
                kind="danger",
                duration=1.5,
            )
        elif key == pygame.K_F1:
            self.show_help = not self.show_help
        elif key == pygame.K_TAB:
            self.show_threat = not self.show_threat
        elif pygame.K_1 <= key <= pygame.K_9:
            return self._qol_accessibility_handle_key(key, mods)
        elif key == pygame.K_F4:
            self.cycle_formation()
        elif key == pygame.K_F7:
            self.send_network_command("discipline", units)
        elif key == pygame.K_F8:
            self.send_network_command("priority", units)
        elif key == pygame.K_z:
            self.send_network_command("stance", units)
        elif key == pygame.K_a:
            self.send_network_command("fire_mode", units, mode="aimed")
        elif key == pygame.K_f:
            self.send_network_command("fire_mode", units, mode="snap")
        elif key == pygame.K_w and (not mods & pygame.KMOD_SHIFT):
            self.send_network_command("fire_mode", units, mode="rapid")
        elif key == pygame.K_r:
            self.send_network_command(
                "reload", units, emergency=bool(mods & pygame.KMOD_SHIFT)
            )
        elif key == pygame.K_j:
            self.send_network_command("clear_jam", units)
        elif key == pygame.K_b and (not mods & pygame.KMOD_SHIFT):
            self.send_network_command("barrel", units)
        elif key == pygame.K_d and (not mods & pygame.KMOD_SHIFT):
            self.send_network_command("deploy", units)
        elif key == pygame.K_v:
            self.send_network_command("bayonet", units)
        elif key == pygame.K_g:
            self.command_mode = "grenade"
            self.cook = 0
        elif key == pygame.K_s:
            self.command_mode = "smoke"
        elif key == pygame.K_l:
            self.command_mode = "rifle_grenade"
        elif key == pygame.K_q:
            self.command_mode = "suppress"
        elif key == pygame.K_m:
            self.command_mode = "mortar"
        elif key == pygame.K_n:
            self.command_mode = "mortar_smoke"
        elif key == pygame.K_o:
            self.command_mode = "overwatch"
        elif key == pygame.K_c:
            self.command_mode = "assault"
        elif key == pygame.K_ESCAPE:
            if self.show_help:
                self.show_help = False
            elif self.command_mode != "normal":
                self.command_mode = "normal"
            else:
                _qol_notify(
                    self,
                    "Finish the match or disconnect from the PvP browser",
                    duration=1.6,
                )

    def handle_settings_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            rects = self.settings_rects()
            if rects["shake"].collidepoint(event.pos):
                self.camera_shake_enabled = not self.camera_shake_enabled
                save_user_settings(self)
                return
            if rects["edge"].collidepoint(event.pos):
                self.edge_scroll_enabled = not self.edge_scroll_enabled
                save_user_settings(self)
                return
        return self._qol_handle_settings_event(event)

    def focus_selected(self):
        units = self.selected_units()
        if not units:
            return
        center_x = sum((unit.x for unit in units)) / len(units)
        center_y = sum((unit.y for unit in units)) / len(units)
        self.polish_camera_target = (
            center_x - MAP_VIEW_W_PX / self.tile_px / 2,
            center_y - MAP_VIEW_H_PX / self.tile_px / 2,
        )

    def update_camera(self, dt):
        if self.state not in ("game", "deployment"):
            return
        keys = pygame.key.get_pressed()
        speed = 13 * dt / max(0.72, self.zoom)
        manual = False
        if keys[pygame.K_LEFT]:
            self.camera_x -= speed
            manual = True
        if keys[pygame.K_RIGHT]:
            self.camera_x += speed
            manual = True
        if keys[pygame.K_UP]:
            self.camera_y -= speed
            manual = True
        if keys[pygame.K_DOWN]:
            self.camera_y += speed
            manual = True
        mouse_x, mouse_y = self.mouse
        map_rect = self.map_view_rect()
        if (
            self.edge_scroll_enabled
            and map_rect.collidepoint(self.mouse)
            and (not self.drag_start)
        ):
            edge = 8
            if mouse_x < map_rect.left + edge:
                self.camera_x -= speed * 0.7
                manual = True
            elif mouse_x > map_rect.right - edge:
                self.camera_x += speed * 0.7
                manual = True
            if mouse_y < map_rect.top + edge:
                self.camera_y -= speed * 0.7
                manual = True
            elif mouse_y > map_rect.bottom - edge:
                self.camera_y += speed * 0.7
                manual = True
        if manual or self.camera_drag:
            self.polish_camera_target = None
        elif self.polish_camera_target is not None:
            target_x, target_y = self.polish_camera_target
            blend = 1.0 - math.exp(-max(0.0, dt) * 8.5)
            self.camera_x += (target_x - self.camera_x) * blend
            self.camera_y += (target_y - self.camera_y) * blend
            if abs(target_x - self.camera_x) + abs(target_y - self.camera_y) < 0.02:
                self.camera_x, self.camera_y = (target_x, target_y)
                self.polish_camera_target = None
        self.clamp_camera()
