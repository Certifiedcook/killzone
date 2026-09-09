"""Frontend / rendering for the Kill Zone engine.

Ordinary Python source: edit this module directly and run validate.py --stress.
"""

from __future__ import annotations
from engine.frontend.support import _qol_command_label
from engine.frontend.support import _qol_draw_tooltip
from engine.frontend.support import _qol_notify
from engine.frontend.support import battlefield_event_style
from engine.frontend.support import battlefield_status_badge
from engine.frontend.support import command_button_status
from engine.frontend.support import offscreen_indicator_point
from engine.frontend.support import unit_card_tooltip_lines
from engine.rules import angle_to
from engine.rules import clamp
from engine.rules import dist
from engine.rules import presentation_terrain_marks
from engine.rules import presentation_weather_particles
from engine.rules import sector_stability_color
from engine.rules import squad_tactical_label
from engine.rules import squad_visual_color
from engine.definitions import COLORS
from engine.definitions import COMBAT2_STATIC_ROLES
from engine.definitions import COMMAND_BAR_HELP_COLUMNS
from engine.definitions import COMMAND_BAR_TOOLTIPS
from engine.definitions import Coord
from engine.definitions import EMPLACEMENT_VISUALS
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
from engine.definitions import ROLE_CONTACT
from engine.definitions import SIDEBAR_X
from engine.definitions import STATIC_WEAPON_ROLES
from engine.definitions import TERRAIN
from engine.definitions import TILE
from engine.definitions import WINDOW_H
from engine.definitions import WINDOW_W
from engine.frontend.backend import pygame
from engine.models import Cell
from engine.models import Unit
import math
import random
import time


class RenderingSystem:
    def _base_text(self, s, pos, size=14, color="text"):
        surf = self.get_font(size).render(
            str(s), True, COLORS[color] if isinstance(color, str) else color
        )
        self.screen.blit(surf, pos)

    def _base_issue_context_command(self, cell: Coord, append=False):
        units = self.selected_units()
        if not units:
            return
        target = self.game.unit_at(*cell)
        if target and target.faction == "player":
            mods = pygame.key.get_mods()
            for u in units:
                if u.uid == target.uid:
                    continue
                if mods & pygame.KMOD_CTRL:
                    self.game.share_ammo(u, target)
                elif mods & pygame.KMOD_ALT and target.casualty == "incapacitated":
                    self.game.carry_toggle(u, target)
                elif u.role == "Medic" and target.casualty in (
                    "wounded",
                    "incapacitated",
                ):
                    self.game.medic_action(u, target)
                elif target.casualty == "incapacitated":
                    self.game.drag_toggle(u, target)
            return
        if (
            target
            and target.faction == "enemy"
            and self.game.visible_to("player", target)
        ):
            for u in units:
                ux, uy = u.tile
                tx, ty = target.tile
                if append:
                    self.game.queue_fire(u, target.uid, u.fire_mode)
                    continue
                if (
                    u.bayonet
                    and dist(u, target) <= 1.5
                    and (self.game.grid[uy][ux].terrain in ("trench", "firing_step"))
                    and (self.game.grid[ty][tx].terrain in ("trench", "firing_step"))
                ):
                    self.game.trench_assault(u, target)
                else:
                    self.game.issue_fire(u, target, u.fire_mode)
            return
        if self.command_mode == "grenade":
            for u in units:
                self.game.throw_grenade(u, cell, cook=self.cook)
            self.command_mode = "normal"
            return
        if self.command_mode == "smoke":
            for u in units:
                self.game.throw_grenade(u, cell, smoke=True)
            self.command_mode = "normal"
            return
        if self.command_mode == "rifle_grenade":
            for u in units:
                self.game.throw_grenade(u, cell, rifle=True)
            self.command_mode = "normal"
            return
        if self.command_mode == "satchel":
            for u in units:
                self.game.place_satchel(u, cell)
            self.command_mode = "normal"
            return
        if self.command_mode == "suppress":
            for u in units:
                self.game.suppress_area(u, cell)
            self.command_mode = "normal"
            return
        if self.command_mode == "mortar":
            for u in units:
                self.game.mortar_fire(u, cell, False)
            self.command_mode = "normal"
            return
        if self.command_mode == "mortar_smoke":
            for u in units:
                self.game.mortar_fire(u, cell, True)
            self.command_mode = "normal"
            return
        if self.command_mode == "support_he":
            self.game.call_support("player", cell, False)
            self.command_mode = "normal"
            return
        if self.command_mode == "support_smoke":
            self.game.call_support("player", cell, True)
            self.command_mode = "normal"
            return
        if self.command_mode == "bound":
            self.game.bounding_advance(units, cell)
            self.command_mode = "normal"
            return
        if self.command_mode.startswith("eng_"):
            kind = self.command_mode.split("_", 1)[1]
            for u in units:
                self.game.engineer_action(u, cell, kind)
            self.command_mode = "normal"
            return
        self.game.issue_move(units, cell, append=append, formation=self.formation)

    def _base_draw(self):
        self.screen.fill(COLORS["bg"])
        if self.state == "menu":
            self.draw_main_menu()
        elif self.state == "setup":
            self.draw_setup()
        elif self.state == "settings":
            self.draw_settings()
        elif self.state == "help":
            self.draw_help_menu()
        else:
            self.draw_topbar()
            self.draw_map()
            self.draw_sidebar()
            self.draw_command_bar()
            if self.show_help:
                self.draw_help()
        self.present()

    def _base_draw_menu_background(self):
        self.screen.fill((22, 25, 22))
        horizon = 220
        pygame.draw.rect(
            self.screen, (66, 58, 45), (0, horizon, WINDOW_W, WINDOW_H - horizon)
        )
        for i in range(18):
            x = (i * 97 + 35) % WINDOW_W
            y = horizon + 70 + i * 43 % 420
            pygame.draw.ellipse(self.screen, (52, 47, 38), (x, y, 80, 30), 2)
        pygame.draw.line(self.screen, (42, 36, 30), (0, 650), (WINDOW_W, 610), 16)
        pygame.draw.line(self.screen, (42, 36, 30), (0, 690), (WINDOW_W, 650), 10)
        haze = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        haze.fill((15, 18, 15, 80))
        self.screen.blit(haze, (0, 0))

    def _base_draw_main_menu(self):
        self.draw_menu_background()
        title = self.fonts[60].render("KILL ZONE", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 105))
        sub = self.fonts[16].render("REALTIME TACTICAL INFANTRY", True, COLORS["muted"])
        self.screen.blit(sub, (WINDOW_W // 2 - sub.get_width() // 2, 182))
        for name, r in self.main_menu_rects().items():
            label = {
                "continue": "CONTINUE",
                "play": "PLAY",
                "settings": "SETTINGS",
                "help": "HELP",
                "quit": "QUIT",
            }[name]
            self.button(r, label, self.mouse, accent=name in ("continue", "play"))
        self.text(
            "F11 fullscreen • Esc is disabled on main menu • Enter opens Play",
            (18, WINDOW_H - 30),
            12,
            "muted",
        )
        self.text(
            "Suppression • positioning • trench assaults • combined infantry tactics",
            (WINDOW_W // 2 - 280, WINDOW_H - 44),
            14,
            "muted",
        )

    def _base_draw_setup(self):
        self.draw_menu_background()
        title = self.fonts[48].render("SKIRMISH SETUP", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 62))
        self.text("PROCEDURAL FRONTLINE", (WINDOW_W // 2 - 330, 120), 20, "white")
        self.text(
            "Choose difficulty and build the force you want to deploy.",
            (WINDOW_W // 2 - 330, 145),
            14,
            "muted",
        )
        self.text("DIFFICULTY", (WINDOW_W // 2 - 330, 150), 14, "muted")
        for name, r in self.setup_rects().items():
            if name in ("easy", "hard", "veteran"):
                selected = self.setup_difficulty.lower() == name
                self.button(
                    r,
                    "[ " + name.upper() + " ]" if selected else name.upper(),
                    self.mouse,
                    accent=selected,
                )
        desc = {
            "Easy": "Smaller enemy force and slower, less accurate reactions.",
            "Hard": "Baseline enemy numbers, reactions and accuracy.",
            "Veteran": "Larger force with faster decisions and better marksmanship.",
        }[self.setup_difficulty]
        self.text(desc, (WINDOW_W // 2 - 330, 228), 13, "text")
        total = sum(self.setup_roster.values())
        self.text(f"FORCE ROSTER  {total}/{MAX_PLAYER_UNITS}", (84, 252), 18, "white")
        self.text(
            "Use - / + to choose your deployment. At least one unit is required.",
            (315, 256),
            12,
            "muted",
        )
        role_rects = self.roster_rects()
        left = 84
        right = WINDOW_W // 2 + 30
        top = 282
        row_h = 55
        for i, role in enumerate(PLAYER_ROLE_ORDER):
            col = 0 if i < 6 else 1
            row = i if i < 6 else i - 6
            x = left if col == 0 else right
            y = top + row * row_h
            panel = pygame.Rect(x, y, 580, 46)
            pygame.draw.rect(self.screen, COLORS["panel"], panel, border_radius=4)
            pygame.draw.rect(self.screen, COLORS["muted"], panel, 1, border_radius=4)
            self.text(role, (x + 12, y + 13), 14, "white")
            count = self.setup_roster.get(role, 0)
            self.text(str(count), (x + 494, y + 13), 16, "select" if count else "muted")
            self.button(role_rects[role, "minus"], "-", self.mouse, enabled=count > 0)
            self.button(
                role_rects[role, "plus"],
                "+",
                self.mouse,
                enabled=count < MAX_ROLE_COUNT and total < MAX_PLAYER_UNITS,
            )
        rects = self.setup_rects()
        self.button(rects["balanced"], "BALANCED PRESET", self.mouse)
        self.button(rects["clear"], "CLEAR", self.mouse)
        self.button(
            rects["start"],
            "START BATTLE",
            self.mouse,
            enabled=total > 0,
            accent=total > 0,
        )
        self.button(rects["back"], "BACK", self.mouse)
        if total == 0:
            self.text(
                "Select at least one unit.", (WINDOW_W // 2 - 80, 695), 12, "danger"
            )

    def _base_draw_settings(self):
        self.draw_menu_background()
        title = self.fonts[48].render("SETTINGS", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 86))
        self.text("DEFAULT SIMULATION SPEED", (WINDOW_W // 2 - 330, 235), 16, "muted")
        for name, r in self.settings_rects().items():
            if name.startswith("speed"):
                value = {"speed05": 0.5, "speed1": 1.0, "speed2": 2.0}[name]
                label = f"{value:g}×"
                self.button(
                    r,
                    "[ " + label + " ]" if self.menu_speed == value else label,
                    self.mouse,
                    accent=self.menu_speed == value,
                )
            elif name == "help":
                self.button(
                    r,
                    f"HELP ON BATTLE START: {('ON' if self.menu_show_help else 'OFF')}",
                    self.mouse,
                    accent=self.menu_show_help,
                )
            elif name == "audio":
                self.button(
                    r,
                    f"COMBAT AUDIO: {('ON' if self.audio_enabled else 'OFF')}",
                    self.mouse,
                    accent=self.audio_enabled,
                )
            elif name == "fps":
                self.button(
                    r,
                    f"FPS COUNTER: {('ON' if self.show_fps else 'OFF')}",
                    self.mouse,
                    accent=self.show_fps,
                )
            elif name == "fullscreen":
                self.button(
                    r,
                    f"FULLSCREEN: {('ON' if self.fullscreen else 'OFF')}  (F11)",
                    self.mouse,
                    accent=self.fullscreen,
                )
            elif name == "back":
                self.button(r, "BACK", self.mouse)

    def _base_draw_help_menu(self):
        self.draw_menu_background()
        title = self.fonts[48].render("FIELD MANUAL", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 55))
        left = 78
        right = WINDOW_W // 2 + 35
        top = 135
        self.text("CONTROLS", (left, top), 20, "select")
        controls = [
            "LMB select; drag a visible box for multiple units.",
            "Shift+LMB / Shift-drag adds to the current selection.",
            "RMB orders movement or attacks; Shift+RMB queues orders.",
            "Hold Left Alt over terrain to inspect cover/exposure.",
            "` tactical slow motion; Space pause; - / = / ] time speed.",
            "Ctrl+1..9 save groups; 1..9 recall them.",
            "F4 formation; F7 fire discipline; F8 target priority.",
            "Tab known-threat overlay; F11 fullscreen.",
            "F1 toggles the in-battle quick-reference overlay.",
        ]
        yy = top + 34
        for line in controls:
            self.text(line, (left, yy), 13, "text")
            yy += 29
        self.text("TACTICAL BASICS", (left, yy + 8), 20, "select")
        yy += 42
        for line in [
            "Suppress before crossing open ground.",
            "Smoke blocks spotting and creates assault windows.",
            "Trenches protect across their face, not along their length.",
            "Use MGs for fire lanes; use recon to find defenders first.",
            "Pinned or isolated troops lose effectiveness quickly.",
        ]:
            self.text("• " + line, (left, yy), 13, "muted")
            yy += 27
        self.text("SPECIALISTS", (right, top), 20, "select")
        yy = top + 34
        for line in [
            "Rifleman — flexible infantry, grenades and smoke.",
            "Machine Gunner/HMG — suppression and area denial.",
            "Sniper/Marksman — long-range precision and spotting.",
            "Medic — stabilises incapacitated troops and treats wounds.",
            "Engineer — wire, mines, breaches and fortifications.",
            "Recon — best spotting and mobility.",
            "Grenadier — hand and rifle grenades.",
            "Assault — SMG and strong trench/CQB performance.",
            "Automatic Rifleman — mobile automatic fire support.",
            "Mortar Team — deploy for indirect HE or smoke.",
        ]:
            self.text(line, (right, yy), 13, "text")
            yy += 29
        self.text("READING THE MAP", (right, yy + 8), 20, "select")
        yy += 42
        for line in [
            "Blue rectangles are friendly units; red diamonds are hostile.",
            "? markers show last-known contacts, not live enemy positions.",
            "Blood remains where serious wounds or deaths occurred.",
            "Hold Left Alt for tile cover, concealment, movement and threat.",
        ]:
            self.text("• " + line, (right, yy), 13, "muted")
            yy += 27
        self.button(self.help_menu_rects()["back"], "BACK", self.mouse)

    def _base_draw_topbar(self):
        pygame.draw.rect(self.screen, COLORS["panel"], (0, 0, WINDOW_W, 52))
        self.text("KILL ZONE", (18, 10), 26, "white")
        slow = self.state == "game" and pygame.key.get_pressed()[pygame.K_BACKQUOTE]
        status = (
            "PAUSED"
            if self.game.paused
            else f"REALTIME ×{self.speed:g}{('  TACTICAL SLOW' if slow else '')}"
        )
        self.text(status, (190, 18), 14, "select" if self.game.paused else "good")
        self.text(
            f"Seed {self.game.seed}  |  {self.game.weather.upper()}  |  wind {self.game.wind}",
            (340, 18),
            14,
            "muted",
        )
        self.text(
            f"MODE: {self.command_mode.upper()}  FORM: {self.formation.upper()}",
            (850, 18),
            14,
            "contact",
        )
        if self.show_fps:
            self.text(
                f"{self.clock.get_fps():5.1f} FPS", (WINDOW_W - 105, 18), 12, "good"
            )

    def _base_draw_map(self):
        for y in range(MAP_H):
            for x in range(MAP_W):
                c = self.game.grid[y][x]
                r = self.cell_rect(x, y)
                pygame.draw.rect(self.screen, COLORS[c.terrain], r)
                pygame.draw.rect(self.screen, (35, 38, 33), r, 1)
                self.draw_terrain(c, r, x, y)
                if self.show_threat:
                    th = self.game.tile_threat("player", x, y)
                    if th > 0:
                        ov = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
                        ov.fill((210, 50, 40, min(110, int(th * 24))))
                        self.screen.blit(ov, r.topleft)
                if c.smoke > 0.05:
                    alpha = int(clamp(c.smoke / 2.4 * 180, 20, 190))
                    ov = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
                    ov.fill((185, 185, 180, alpha))
                    self.screen.blit(ov, r.topleft)
                if c.fire > 0:
                    pygame.draw.circle(
                        self.screen, COLORS["fire"], r.center, 5 + int(min(7, c.fire))
                    )
                if c.mine and c.mine_seen_player:
                    self.text("M", (r.x + 9, r.y + 7), 12, "danger")
        for u in self.selected_units():
            pts = [(MAP_X + u.x * TILE + TILE / 2, MAP_Y + u.y * TILE + TILE / 2)]
            for x, y in u.path + u.waypoints:
                pts.append((MAP_X + x * TILE + TILE / 2, MAP_Y + y * TILE + TILE / 2))
            if len(pts) > 1:
                pygame.draw.lines(self.screen, COLORS["select"], False, pts, 2)
        for b in self.game.blood:
            cx = int(MAP_X + b.x * TILE + TILE / 2)
            cy = int(MAP_Y + b.y * TILE + TILE / 2)
            rr = max(2, int(5 + b.size * 8))
            if self.blood_sprite:
                spr = pygame.transform.smoothscale(self.blood_sprite, (rr * 3, rr * 3))
                spr.set_alpha(145)
                self.screen.blit(
                    spr, (cx - spr.get_width() // 2, cy - spr.get_height() // 2)
                )
            else:
                rng = random.Random(b.seed)
                pygame.draw.ellipse(
                    self.screen,
                    COLORS["blood_dark"],
                    (cx - rr, cy - rr // 2, rr * 2, rr),
                )
                for _ in range(4):
                    ox = rng.randint(-rr, rr)
                    oy = rng.randint(-rr, rr)
                    pygame.draw.circle(
                        self.screen,
                        COLORS["blood"],
                        (cx + ox, cy + oy),
                        max(1, rr // 4),
                    )
        for uid, info, age in self.game.known_contacts("player", memory=10):
            t = self.game.get_unit(uid)
            if t and self.game.visible_to("player", t):
                continue
            x, y = info["pos"]
            cx = int(MAP_X + x * TILE + TILE / 2)
            cy = int(MAP_Y + y * TILE + TILE / 2)
            rad = int(5 + age * 1.6)
            pygame.draw.circle(self.screen, COLORS["contact"], (cx, cy), rad, 1)
            self.text("?", (cx - 4, cy - 8), 12, "contact")
        for u in self.game.living():
            if (u.overwatch or u.fire_lane) and (
                u.faction == "player" or self.game.visible_to("player", u)
            ):
                self.draw_arc(u)
        for u in self.game.units:
            if not u.alive and u.casualty != "dead":
                continue
            if u.faction == "enemy" and (not self.game.visible_to("player", u)):
                continue
            self.draw_unit(u)
        for t in self.game.tracers:
            a = (MAP_X + t.a[0] * TILE + TILE / 2, MAP_Y + t.a[1] * TILE + TILE / 2)
            b = (MAP_X + t.b[0] * TILE + TILE / 2, MAP_Y + t.b[1] * TILE + TILE / 2)
            q = clamp(1 - t.life / max(0.001, t.total), 0, 1)
            q0 = max(0, q - 0.18)
            p0 = (a[0] + (b[0] - a[0]) * q0, a[1] + (b[1] - a[1]) * q0)
            p1 = (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q)
            pygame.draw.line(self.screen, (245, 220, 135), p0, p1, 2)
        for im in self.game.impacts:
            px = int(MAP_X + im.x * TILE + TILE / 2)
            py = int(MAP_Y + im.y * TILE + TILE / 2)
            col = (
                (235, 225, 195)
                if im.kind == "body"
                else (195, 190, 174)
                if im.kind == "cover"
                else (220, 195, 135)
            )
            pygame.draw.circle(
                self.screen, col, (px, py), 3 if im.kind == "body" else 2
            )
        for e in self.game.explosions:
            cx = int(MAP_X + e.x * TILE + TILE / 2)
            cy = int(MAP_Y + e.y * TILE + TILE / 2)
            pygame.draw.circle(
                self.screen,
                COLORS["danger"] if e.kind == "HE" else COLORS["smoke"],
                (cx, cy),
                int(e.radius * TILE),
                1,
            )
            self.text(f"{e.timer:.1f}", (cx - 10, cy - 8), 12, "white")
        self.draw_selection_box()
        if self.game.victory:
            self.end_banner("VICTORY")
        elif self.game.defeat:
            self.end_banner("DEFEAT")

    def _base_draw_selection_box(self):
        if not self.drag_start:
            return
        if (
            max(
                abs(self.mouse[0] - self.drag_start[0]),
                abs(self.mouse[1] - self.drag_start[1]),
            )
            <= 5
        ):
            return
        map_rect = pygame.Rect(MAP_X, MAP_Y, MAP_W * TILE, MAP_H * TILE)
        sx = int(clamp(self.drag_start[0], map_rect.left, map_rect.right))
        sy = int(clamp(self.drag_start[1], map_rect.top, map_rect.bottom))
        ex = int(clamp(self.mouse[0], map_rect.left, map_rect.right))
        ey = int(clamp(self.mouse[1], map_rect.top, map_rect.bottom))
        x1, x2 = sorted((sx, ex))
        y1, y2 = sorted((sy, ey))
        rect = pygame.Rect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        fill = pygame.Surface(rect.size, pygame.SRCALPHA)
        fill.fill((229, 210, 119, 28))
        self.screen.blit(fill, rect.topleft)
        pygame.draw.rect(self.screen, COLORS["select"], rect, 2)

    def _base_draw_terrain(self, c: Cell, r: pygame.Rect, x: int, y: int):
        if c.terrain in ("trench", "firing_step"):
            if c.axis == "H":
                pygame.draw.line(
                    self.screen, (38, 34, 28), (r.x, r.centery), (r.right, r.centery), 4
                )
            else:
                pygame.draw.line(
                    self.screen,
                    (38, 34, 28),
                    (r.centerx, r.y),
                    (r.centerx, r.bottom),
                    4,
                )
            if c.terrain == "firing_step":
                pygame.draw.line(
                    self.screen,
                    (170, 145, 96),
                    (r.x + 4, r.y + 5),
                    (r.right - 4, r.y + 5),
                    2,
                )
        elif c.terrain == "dugout":
            pygame.draw.rect(self.screen, (44, 41, 35), r.inflate(-5, -5), 0)
            pygame.draw.rect(self.screen, (120, 103, 75), r.inflate(-5, -5), 2)
        elif c.terrain == "woods":
            pygame.draw.circle(self.screen, (39, 59, 37), (r.centerx - 5, r.centery), 5)
            pygame.draw.circle(
                self.screen, (44, 66, 41), (r.centerx + 5, r.centery - 3), 5
            )
        elif c.terrain == "wire":
            pygame.draw.line(
                self.screen,
                (180, 180, 168),
                (r.x + 3, r.y + 4),
                (r.right - 3, r.bottom - 4),
                1,
            )
            pygame.draw.line(
                self.screen,
                (180, 180, 168),
                (r.right - 3, r.y + 4),
                (r.x + 3, r.bottom - 4),
                1,
            )
        elif c.terrain == "crater":
            pygame.draw.ellipse(self.screen, (62, 54, 43), r.inflate(-7, -10), 2)
        elif c.terrain in ("wall", "building", "woodwall"):
            pygame.draw.rect(
                self.screen,
                (55, 56, 52) if c.terrain != "woodwall" else (84, 61, 40),
                r.inflate(-4, -4),
                2,
            )
        elif c.terrain == "window":
            pygame.draw.rect(self.screen, (60, 70, 72), r.inflate(-4, -4), 2)
            pygame.draw.line(
                self.screen,
                (160, 180, 180),
                (r.centerx, r.y + 4),
                (r.centerx, r.bottom - 4),
                1,
            )
        elif c.terrain == "door":
            if c.door_open:
                pygame.draw.line(
                    self.screen,
                    (170, 135, 90),
                    (r.x + 5, r.bottom - 5),
                    (r.right - 5, r.y + 5),
                    3,
                )
            else:
                pygame.draw.rect(self.screen, (145, 103, 65), r.inflate(-8, -3), 0)
        elif c.terrain == "sandbags":
            for i in range(3):
                pygame.draw.rect(
                    self.screen,
                    (156, 137, 94),
                    (r.x + 3 + i * 8, r.centery - 3, 7, 6),
                    1,
                )

    def _base_draw_arc(self, u: Unit):
        center = (
            int(MAP_X + u.x * TILE + TILE / 2),
            int(MAP_Y + u.y * TILE + TILE / 2),
        )
        radius = int(u.arc_range * TILE)
        a1 = math.radians(u.fire_lane_center - u.arc_width / 2)
        a2 = math.radians(u.fire_lane_center + u.arc_width / 2)
        p1 = (center[0] + math.cos(a1) * radius, center[1] + math.sin(a1) * radius)
        p2 = (center[0] + math.cos(a2) * radius, center[1] + math.sin(a2) * radius)
        col = COLORS["danger"] if u.faction == "enemy" else COLORS["contact"]
        pygame.draw.line(self.screen, col, center, p1, 1)
        pygame.draw.line(self.screen, col, center, p2, 1)

    def _base_draw_unit(self, u: Unit):
        cx = int(MAP_X + u.x * TILE + TILE / 2)
        cy = int(MAP_Y + u.y * TILE + TILE / 2)
        if u.casualty == "dead":
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx - 6, cy - 6), (cx + 6, cy + 6), 2
            )
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx + 6, cy - 6), (cx - 6, cy + 6), 2
            )
            return
        friend = u.faction == "player"
        fill = COLORS["nato_friend"] if friend else COLORS["nato_hostile"]
        ink = COLORS["black"]
        if friend:
            rect = pygame.Rect(cx - 12, cy - 8, 24, 16)
            pygame.draw.rect(self.screen, fill, rect)
            pygame.draw.rect(self.screen, ink, rect, 2)
            pygame.draw.line(
                self.screen,
                ink,
                (rect.left + 2, rect.top + 2),
                (rect.right - 2, rect.bottom - 2),
                2,
            )
            pygame.draw.line(
                self.screen,
                ink,
                (rect.right - 2, rect.top + 2),
                (rect.left + 2, rect.bottom - 2),
                2,
            )
        else:
            pts = [(cx, cy - 12), (cx + 12, cy), (cx, cy + 12), (cx - 12, cy)]
            pygame.draw.polygon(self.screen, fill, pts)
            pygame.draw.polygon(self.screen, ink, pts, 2)
            pygame.draw.line(self.screen, ink, (cx - 7, cy - 7), (cx + 7, cy + 7), 2)
            pygame.draw.line(self.screen, ink, (cx + 7, cy - 7), (cx - 7, cy + 7), 2)
        role = {
            "Rifleman": "RF",
            "Machine Gunner": "MG",
            "Sniper": "SN",
            "Medic": "MED",
            "Engineer": "ENG",
            "Recon": "REC",
            "Grenadier": "GRN",
            "Assault": "ASLT",
            "Automatic Rifleman": "AR",
            "Marksman": "DMR",
            "HMG Crew": "HMG",
            "Mortar Team": "MTR",
        }.get(u.role, "INF")
        surf = self.fonts[12].render(role, True, COLORS["white"])
        self.screen.blit(surf, (cx - surf.get_width() // 2, cy + 10))
        if u.uid in self.selected:
            pygame.draw.circle(self.screen, COLORS["select"], (cx, cy), 17, 2)
        ang = math.radians(u.facing)
        pygame.draw.line(
            self.screen,
            COLORS["white"],
            (cx, cy),
            (cx + math.cos(ang) * 15, cy + math.sin(ang) * 15),
            1,
        )
        pygame.draw.rect(self.screen, (30, 30, 28), (cx - 12, cy + 22, 24, 3))
        pygame.draw.rect(
            self.screen,
            COLORS["good"],
            (cx - 12, cy + 22, int(24 * clamp(u.hp / u.max_hp, 0, 1)), 3),
        )
        if u.suppression > 15:
            pygame.draw.rect(
                self.screen,
                COLORS["contact"],
                (cx - 12, cy + 26, int(24 * u.suppression / 100), 2),
            )
        status = ""
        if u.reload_timer > 0:
            status = "RLD"
        elif u.jammed:
            status = "JAM"
        elif u.order == "rout" or u.morale < 16:
            status = "BRK"
        elif u.suppression >= 80:
            status = "PIN"
        elif self.game.time < u.disoriented_until:
            status = "CON"
        elif u.order == "suppress":
            status = "SUP"
        elif u.overwatch:
            status = "OW"
        elif u.order == "move":
            status = "MOV"
        if status:
            ss = self.get_font(10).render(status, True, COLORS["status"])
            self.screen.blit(ss, (cx - ss.get_width() // 2, cy - 22))

    def _base_draw_sidebar(self):
        x = SIDEBAR_X
        pygame.draw.rect(
            self.screen, COLORS["panel"], (x, MAP_Y, WINDOW_W - x - 12, MAP_H * TILE)
        )
        self.text("SELECTED", (x + 14, MAP_Y + 12), 20, "white")
        us = self.selected_units()
        y = MAP_Y + 44
        if not us:
            self.text("No units selected", (x + 14, y), 14, "muted")
        else:
            firing = sum((1 for u in us if u.order == "fire"))
            reloading = sum((1 for u in us if u.reload_timer > 0))
            pinned = sum((1 for u in us if u.suppression >= 80))
            wounded = sum((1 for u in us if u.casualty == "wounded"))
            self.text(
                f"GROUP  fire {firing}  reload {reloading}  pinned {pinned}  wounded {wounded}",
                (x + 14, y),
                12,
                "status",
            )
            y += 20
            for u in us[:5]:
                self.text(f"{u.role} #{u.uid}", (x + 14, y), 14, "select")
                y += 19
                self.text(
                    f"HP {u.hp:.0f}/{u.max_hp:.0f}  {u.casualty}", (x + 14, y), 12
                )
                y += 16
                self.text(
                    f"Morale {u.morale:.0f}  Supp {u.suppression:.0f}  Coh {u.cohesion:.0f}",
                    (x + 14, y),
                    12,
                )
                y += 16
                self.text(
                    f"{u.weapon_name}  {u.ammo} | mags {len(u.magazines)}",
                    (x + 14, y),
                    12,
                )
                y += 16
                reserve = sum(u.magazines)
                ammo_col = (
                    "danger"
                    if u.ammo <= max(2, int(u.weapon["mag"] * 0.15))
                    and reserve <= u.weapon["mag"]
                    else "muted"
                )
                self.text(
                    f"Heat {u.heat:.0f}%  Stam {u.stamina:.0f}  {('JAM' if u.jammed else '')}",
                    (x + 14, y),
                    12,
                    "contact" if u.heat > 70 else "muted",
                )
                y += 16
                self.text(
                    f"{u.stance} / {u.move_mode} / {u.order}  reserve {reserve}",
                    (x + 14, y),
                    12,
                    ammo_col,
                )
                y += 16
                self.text(
                    f"Ready {u.prepared * 100:.0f}%  {('CONCUSSED' if self.game.time < u.disoriented_until else '')}",
                    (x + 14, y),
                    12,
                    "muted",
                )
                y += 16
                auto = (
                    "ON"
                    if u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic
                    else "MIX/OFF"
                )
                self.text(
                    f"Fire {u.fire_discipline} / Priority {u.target_priority} / Auto {auto}",
                    (x + 14, y),
                    12,
                    "muted",
                )
                y += 20
            if len(us) > 5:
                self.text(f"+ {len(us) - 5} more", (x + 14, y), 12, "muted")
                y += 20
        self.text("FIELD REPORT", (x + 14, max(y + 8, MAP_Y + 380)), 16, "white")
        yy = max(y + 32, MAP_Y + 405)
        for line in self.game.log[-9:]:
            self.text(line[:40], (x + 14, yy), 12, "muted")
            yy += 17
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LALT]:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                cx, cy = cell
                c = self.game.grid[cy][cx]
                td = TERRAIN[c.terrain]
                base_y = MAP_Y + MAP_H * TILE - 108
                pygame.draw.rect(
                    self.screen,
                    COLORS["panel2"],
                    (x + 8, base_y - 8, WINDOW_W - x - 28, 104),
                    border_radius=3,
                )
                self.text("TILE INTEL  [LALT]", (x + 14, base_y), 12, "select")
                self.text(
                    f"{cell}  {c.terrain.upper()}  cover {td['cover']}  conceal {td['conceal']}",
                    (x + 14, base_y + 18),
                    12,
                    "white",
                )
                self.text(
                    f"move ×{td['move']:.2f}  smoke {c.smoke:.1f}  height {td['height']}",
                    (x + 14, base_y + 36),
                    12,
                    "muted",
                )
                if c.terrain in ("trench", "firing_step") and c.axis:
                    dirs = (
                        "N/S heavy • E/W low"
                        if c.axis == "H"
                        else "E/W heavy • N/S low"
                    )
                else:
                    dirs = f"all directions cover {td['cover']}"
                self.text(f"Directional: {dirs}", (x + 14, base_y + 54), 12, "muted")
                self.text(
                    f"Known exposure threat {self.game.tile_threat('player', cx, cy):.1f}",
                    (x + 14, base_y + 72),
                    12,
                    "contact",
                )

    def _base_draw_command_bar(self):
        us = self.selected_units()
        if not us:
            return
        pygame.draw.rect(
            self.screen,
            COLORS["panel"],
            (
                0,
                MAP_Y + MAP_H * TILE + 3,
                WINDOW_W,
                WINDOW_H - (MAP_Y + MAP_H * TILE + 3),
            ),
        )
        for name, r in self.command_bar_rects().items():
            active = name == "FORMATION" or name == "DISCIPLINE" or name == "PRIORITY"
            pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=3)
            pygame.draw.rect(self.screen, COLORS["muted"], r, 1, border_radius=3)
            label = name
            if name == "FORMATION":
                label = self.formation.upper()
            elif name == "DISCIPLINE":
                label = us[0].fire_discipline.upper()
            elif name == "PRIORITY":
                label = us[0].target_priority.upper()
            elif name == "AUTO":
                label = (
                    "AUTO ON"
                    if all(
                        (
                            u.auto_reload
                            and u.auto_cover
                            and u.auto_smoke
                            and u.auto_medic
                            for u in us
                        )
                    )
                    else "AUTO OFF"
                )
            surf = self.fonts[12].render(
                label,
                True,
                COLORS["select"] if active or name == "AUTO" else COLORS["white"],
            )
            self.screen.blit(
                surf,
                (r.centerx - surf.get_width() // 2, r.centery - surf.get_height() // 2),
            )

    def _base_draw_help(self):
        w, h = (790, 620)
        x = (WINDOW_W - w) // 2
        y = (WINDOW_H - h) // 2
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((20, 23, 20, 242))
        self.screen.blit(ov, (x, y))
        pygame.draw.rect(self.screen, COLORS["select"], (x, y, w, h), 2)
        self.text("REALTIME CONTROLS", (x + 22, y + 18), 26, "white")
        lines = [
            "LMB select / visible drag box | Shift+LMB add/remove | RMB order | Shift+RMB queue order",
            "SPACE pause | hold ` tactical slow-motion | Left Alt tile intel | TAB threat overlay | F11 fullscreen",
            "Ctrl+1..9 assign control group | 1..9 recall group | F4 formation | F3 bounding overwatch",
            "F7 fire discipline | F8 target priority | F10 autonomy | bottom command bar mirrors key actions",
            "Z stance | X route mode (fast/safe/manual) | A aimed | F snap | W rapid fire",
            "R tactical reload | Shift+R emergency reload (drops partial mag) | J clear jam | B barrel",
            "O overwatch toward mouse | I MG fire lane toward mouse | Q suppress area then RMB",
            "G grenade then RMB | Shift+C cook grenade | S smoke | L rifle grenade | K satchel",
            "V fix/remove bayonet | P peek | C coordinated covering advance toward mouse",
            "RMB wounded ally: medic/drag | Alt+RMB incapacitated: carry | Ctrl+RMB: share ammo",
            "ENTER toggle door | Shift+E deliberate mine scan | 4 engineer places wire",
            "E engineer contextual action | T dig trench | U Bangalore breach",
            "M on-map mortar HE | N on-map mortar smoke | H off-map HE | Y off-map smoke",
            "BACKSPACE cancel orders | F5 new battle | F6 cycle difficulty + restart",
            "",
            "Implemented systems:",
            "• continuous movement/firing/reloads/suppression/bleeding • fog of war • facing/flanks",
            "• directional trench cover/enfilade • stances • MG heat/jams/barrel changes/fire lanes",
            "• tactical magazines + ammo sharing model • assistant-gunner reload bonuses • HMG teams",
            "• medics/stabilization/dragging • engineers/wire/mines/fortifications/trench digging",
            "• grenades/rifle grenades/satchels/Bangalore • grenade reactions • trench CQB/bayonets",
            "• buildings/doors • hills/reverse slopes • penetration • smoke density/wind • weather/fire",
            "• recon/grenadier/assault/automatic rifleman/marksman • on-map mortar teams/support",
            "• rout/surrender • combat momentum • coherent procedural battlefield • destructible terrain",
            "• control groups/formations • command queue • bounding overwatch • fire discipline/priority",
            "• APP-6 affiliation frames • shared fog/contact memory for AI • animated tracers/near-miss suppression",
            "• auto reload • stamina/fatigue • reaction/traverse delay • concussion • cover degradation",
            "• crossfire/sector overload • position suppression • fallback AI • morale contagion • assault momentum",
        ]
        yy = y + 62
        for line in lines:
            self.text(
                line, (x + 22, yy), 12, "text" if not line.startswith("•") else "muted"
            )
            yy += 22

    def _kz_draw_setup(self):
        self.draw_menu_background()
        title = self.get_font(46).render("SKIRMISH SETUP", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 45))
        x = WINDOW_W // 2 - 330
        self.text("DIFFICULTY", (x, 128), 14, "muted")
        for name, r in self.setup_rects().items():
            if name in ("easy", "hard", "veteran"):
                sel = self.setup_difficulty.lower() == name
                self.button(
                    r,
                    "[ " + name.upper() + " ]" if sel else name.upper(),
                    self.mouse,
                    accent=sel,
                )
        lo, hi = {"Easy": (6, 10), "Hard": (9, 13), "Veteran": (12, 16)}[
            self.setup_difficulty
        ]
        self.text(
            f"Estimated opposition: {lo}–{hi} troops. Difficulty changes tactics, not weapon accuracy.",
            (x, 207),
            12,
            "text",
        )
        seedr = self.setup_rects()["seed"]
        pygame.draw.rect(self.screen, COLORS["panel2"], seedr, border_radius=3)
        pygame.draw.rect(
            self.screen,
            COLORS["select"] if self.seed_active else COLORS["muted"],
            seedr,
            2,
            border_radius=3,
        )
        self.text(
            "MAP SEED: " + (self.seed_text or "RANDOM"),
            (seedr.x + 10, seedr.y + 10),
            13,
            "white",
        )
        self.text(f"RESERVES: {self.setup_reserves}", (x + 330, 237), 14, "white")
        self.button(
            self.setup_rects()["reserve_minus"],
            "-",
            self.mouse,
            enabled=self.setup_reserves > 0,
        )
        self.button(
            self.setup_rects()["reserve_plus"],
            "+",
            self.mouse,
            enabled=self.setup_reserves
            < min(6, max(0, sum(self.setup_roster.values()) - 1)),
        )
        total = sum(self.setup_roster.values())
        self.text(f"FORCE ROSTER  {total}/{MAX_PLAYER_UNITS}", (74, 260), 18, "white")
        rr = self.roster_rects()
        left = 74
        right = WINDOW_W // 2 + 25
        top = 286
        row_h = 57
        for i, role in enumerate(PLAYER_ROLE_ORDER):
            col = 0 if i < 6 else 1
            row = i if i < 6 else i - 6
            x0 = left if col == 0 else right
            y = top + row * row_h
            panel = pygame.Rect(x0, y, 570, 45)
            pygame.draw.rect(self.screen, COLORS["panel"], panel, border_radius=4)
            pygame.draw.rect(self.screen, COLORS["muted"], panel, 1, border_radius=4)
            self.text(role, (x0 + 12, y + 13), 14, "white")
            cnt = self.setup_roster.get(role, 0)
            self.text(str(cnt), (x0 + 486, y + 12), 16, "select" if cnt else "muted")
            self.button(rr[role, "minus"], "-", self.mouse, enabled=cnt > 0)
            self.button(
                rr[role, "plus"],
                "+",
                self.mouse,
                enabled=cnt < MAX_ROLE_COUNT and total < MAX_PLAYER_UNITS,
            )
        r = self.setup_rects()
        self.button(r["balanced"], "BALANCED PRESET", self.mouse)
        self.button(r["clear"], "CLEAR", self.mouse)
        self.button(
            r["start"], "DEPLOY FORCE", self.mouse, enabled=total > 0, accent=total > 0
        )
        self.button(r["back"], "BACK", self.mouse)

    def _kz_issue_context(self, cell, append=False):
        us = self.selected_units()
        if self.command_mode == "assault" and us:
            t = self.game.unit_at(*cell)
            uid = t.uid if t and t.faction == "enemy" else None
            self.game.assault_position(us, cell, uid)
            self.command_mode = "normal"
            return
        t = self.game.unit_at(*cell)
        if t and t.faction == "player" and us:
            for u in us:
                if u.uid != t.uid and self.game.recrew_weapon(u, t):
                    return
        self._base_issue_context_command(cell, append=append)

    def draw_selection_box(self):
        if not self.drag_start:
            return
        if (
            max(
                abs(self.mouse[0] - self.drag_start[0]),
                abs(self.mouse[1] - self.drag_start[1]),
            )
            <= 5
        ):
            return
        mr = self.map_view_rect()
        sx = int(clamp(self.drag_start[0], mr.left, mr.right))
        sy = int(clamp(self.drag_start[1], mr.top, mr.bottom))
        ex = int(clamp(self.mouse[0], mr.left, mr.right))
        ey = int(clamp(self.mouse[1], mr.top, mr.bottom))
        x1, x2 = sorted((sx, ex))
        y1, y2 = sorted((sy, ey))
        r = pygame.Rect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        fill = pygame.Surface(r.size, pygame.SRCALPHA)
        fill.fill((229, 210, 119, 28))
        self.screen.blit(fill, r.topleft)
        pygame.draw.rect(self.screen, COLORS["select"], r, 2)

    def _kz_draw_unit(self, u):
        cx, cy = self.world_to_screen(u.x, u.y)
        tp = self.tile_px
        if not self.map_view_rect().inflate(30, 30).collidepoint((cx, cy)):
            return
        if u.casualty == "dead":
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx - 6, cy - 6), (cx + 6, cy + 6), 2
            )
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx + 6, cy - 6), (cx - 6, cy + 6), 2
            )
            return
        friend = u.faction == "player"
        fill = COLORS["nato_friend"] if friend else COLORS["nato_hostile"]
        ink = COLORS["black"]
        sw = max(16, int(tp * 0.85))
        sh = max(12, int(tp * 0.56))
        if friend:
            r = pygame.Rect(cx - sw // 2, cy - sh // 2, sw, sh)
            pygame.draw.rect(self.screen, fill, r)
            pygame.draw.rect(self.screen, ink, r, 2)
            pygame.draw.line(
                self.screen,
                ink,
                (r.left + 2, r.top + 2),
                (r.right - 2, r.bottom - 2),
                2,
            )
            pygame.draw.line(
                self.screen,
                ink,
                (r.right - 2, r.top + 2),
                (r.left + 2, r.bottom - 2),
                2,
            )
        else:
            rad = max(9, int(tp * 0.42))
            pts = [(cx, cy - rad), (cx + rad, cy), (cx, cy + rad), (cx - rad, cy)]
            pygame.draw.polygon(self.screen, fill, pts)
            pygame.draw.polygon(self.screen, ink, pts, 2)
            pygame.draw.line(self.screen, ink, (cx - 6, cy - 6), (cx + 6, cy + 6), 2)
            pygame.draw.line(self.screen, ink, (cx + 6, cy - 6), (cx - 6, cy + 6), 2)
        role = {
            "Rifleman": "RF",
            "Machine Gunner": "MG",
            "Sniper": "SN",
            "Medic": "MED",
            "Engineer": "ENG",
            "Recon": "REC",
            "Grenadier": "GRN",
            "Assault": "ASLT",
            "Automatic Rifleman": "AR",
            "Marksman": "DMR",
            "HMG Crew": "HMG",
            "Mortar Team": "MTR",
        }.get(u.role, "INF")
        surf = self.get_font(10 if tp < 24 else 12).render(role, True, COLORS["white"])
        self.screen.blit(surf, (cx - surf.get_width() // 2, cy + max(8, sh // 2 + 2)))
        if u.uid in self.selected:
            pygame.draw.circle(
                self.screen, COLORS["select"], (cx, cy), max(14, int(tp * 0.6)), 2
            )
        ang = math.radians(u.facing)
        pygame.draw.line(
            self.screen,
            COLORS["white"],
            (cx, cy),
            (
                cx + math.cos(ang) * max(11, tp * 0.48),
                cy + math.sin(ang) * max(11, tp * 0.48),
            ),
            1,
        )
        bw = max(20, int(tp * 0.85))
        pygame.draw.rect(
            self.screen,
            (30, 30, 28),
            (cx - bw // 2, cy + max(17, int(tp * 0.78)), bw, 3),
        )
        pygame.draw.rect(
            self.screen,
            COLORS["good"],
            (
                cx - bw // 2,
                cy + max(17, int(tp * 0.78)),
                int(bw * clamp(u.hp / u.max_hp, 0, 1)),
                3,
            ),
        )
        if u.suppression > 12:
            col = (
                COLORS["contact"]
                if u.suppression < 55
                else COLORS["suppression"]
                if u.suppression < 80
                else COLORS["danger"]
            )
            pygame.draw.circle(
                self.screen,
                col,
                (cx, cy),
                max(15, int(tp * 0.64)),
                1 if u.suppression < 55 else 2,
            )
        status = ""
        if u.reload_timer > 0:
            status = "RLD"
        elif u.jammed:
            status = "JAM"
        elif u.order == "rout" or u.morale < 16:
            status = "BRK"
        elif u.suppression >= 80:
            status = "PIN"
        elif self.game.time < u.disoriented_until:
            status = "CON"
        elif u.order == "suppress":
            status = "SUP"
        elif u.overwatch:
            status = "OW"
        elif u.order == "move":
            status = "MOV"
        if status:
            ss = self.get_font(10).render(status, True, COLORS["status"])
            self.screen.blit(
                ss, (cx - ss.get_width() // 2, cy - max(21, int(tp * 0.8)))
            )

    def _kz_draw_arc(self, u):
        center = self.world_to_screen(u.x, u.y)
        radius = int(u.arc_range * self.tile_px)
        a1 = math.radians(u.fire_lane_center - u.arc_width / 2)
        a2 = math.radians(u.fire_lane_center + u.arc_width / 2)
        col = COLORS["danger"] if u.faction == "enemy" else COLORS["contact"]
        pygame.draw.line(
            self.screen,
            col,
            center,
            (center[0] + math.cos(a1) * radius, center[1] + math.sin(a1) * radius),
            1,
        )
        pygame.draw.line(
            self.screen,
            col,
            center,
            (center[0] + math.cos(a2) * radius, center[1] + math.sin(a2) * radius),
            1,
        )

    def draw_tactical_previews(self):
        us = self.selected_units()
        cell = self.map_cell_from_mouse(self.mouse)
        if not us or not cell:
            return
        u = us[0]
        target = self.game.unit_at(*cell)
        if (
            target
            and target.faction == "enemy"
            and self.game.visible_to("player", target)
        ):
            a = self.world_to_screen(u.x, u.y)
            b = self.world_to_screen(target.x, target.y)
            clear, smoke, soft, _ = self.game.line_info(u.pos, target.pos)
            hc = self.game.hit_chance(u, target)
            col = (
                COLORS["good"]
                if clear and hc >= 55
                else COLORS["contact"]
                if clear and hc > 0
                else COLORS["danger"]
            )
            pygame.draw.line(self.screen, col, a, b, 2)
            tx, ty = self.mouse
            box = pygame.Rect(
                min(tx + 14, WINDOW_W - 260), min(ty + 14, WINDOW_H - 92), 245, 78
            )
            pygame.draw.rect(self.screen, COLORS["panel"], box)
            pygame.draw.rect(self.screen, col, box, 2)
            self.text(
                f"HIT {hc:.0f}%   RANGE {dist(u, target):.1f}/{u.weapon['range']:.0f}",
                (box.x + 8, box.y + 8),
                12,
                "white",
            )
            self.text(
                f"cover {self.game.effective_cover(u, target):.1f}  smoke {smoke:.1f}  pen {soft}",
                (box.x + 8, box.y + 28),
                12,
                "muted",
            )
            self.text(
                f"target {target.role} — {('PINNED' if target.suppression >= 80 else 'SUPPRESSED' if target.suppression >= 50 else 'UNDER FIRE' if target.suppression >= 20 else 'CALM')}",
                (box.x + 8, box.y + 48),
                12,
                "contact",
            )
        elif self.preview_path:
            pts = [self.world_to_screen(u.x, u.y)] + [
                self.world_to_screen(x, y) for x, y in self.preview_path
            ]
            for i in range(1, len(pts)):
                x, y = self.preview_path[i - 1]
                th = self.game.tile_threat("player", x, y)
                col = (
                    COLORS["good"]
                    if th < 0.6
                    else COLORS["contact"]
                    if th < 1.4
                    else COLORS["danger"]
                )
                pygame.draw.line(self.screen, col, pts[i - 1], pts[i], 2)
            if pts:
                self.text(
                    f"{u.move_mode.upper()}  ETA {self.preview_eta:.1f}s",
                    (
                        min(self.mouse[0] + 12, WINDOW_W - 170),
                        max(MAP_Y, self.mouse[1] - 22),
                    ),
                    12,
                    "white",
                )

    def draw_directional_cover(self, cell):
        if not cell:
            return
        x, y = cell
        c = self.game.grid[y][x]
        r = self.cell_rect(x, y)
        base = max(0, TERRAIN[c.terrain]["cover"] - c.cover_wear * 2.2)
        vals = {"N": base, "S": base, "E": base, "W": base}
        if c.terrain in ("trench", "firing_step") and c.axis:
            if c.axis == "H":
                vals.update({"N": 5, "S": 5, "E": 1, "W": 1})
            else:
                vals.update({"E": 5, "W": 5, "N": 1, "S": 1})

        def col(v):
            return (
                COLORS["good"]
                if v >= 3
                else COLORS["contact"]
                if v >= 1
                else COLORS["danger"]
            )

        pygame.draw.line(
            self.screen,
            col(vals["N"]),
            (r.left + 2, r.top + 2),
            (r.right - 2, r.top + 2),
            3,
        )
        pygame.draw.line(
            self.screen,
            col(vals["S"]),
            (r.left + 2, r.bottom - 2),
            (r.right - 2, r.bottom - 2),
            3,
        )
        pygame.draw.line(
            self.screen,
            col(vals["W"]),
            (r.left + 2, r.top + 2),
            (r.left + 2, r.bottom - 2),
            3,
        )
        pygame.draw.line(
            self.screen,
            col(vals["E"]),
            (r.right - 2, r.top + 2),
            (r.right - 2, r.bottom - 2),
            3,
        )

    def _kz_draw_planned_orders(self):
        for u in self.selected_units()[:8]:
            pts = []
            if u.path:
                pts.extend(u.path)
            if u.waypoints:
                pts.extend(u.waypoints)
            last = self.world_to_screen(u.x, u.y)
            for i, (x, y) in enumerate(pts[:16], 1):
                cur = self.world_to_screen(x, y)
                pygame.draw.line(self.screen, COLORS["blue"], last, cur, 1)
                if i == len(pts) or i % 4 == 0:
                    ss = self.get_font(9).render(str(i), True, COLORS["white"])
                    self.screen.blit(ss, (cur[0] + 2, cur[1] - 8))
                last = cur
            for qi, (kind, data) in enumerate(u.command_queue[:5], 1):
                if kind == "move":
                    cur = self.world_to_screen(*data)
                    pygame.draw.circle(self.screen, COLORS["select"], cur, 6, 1)
                    self.text(f"Q{qi}", (cur[0] + 6, cur[1] - 7), 9, "select")

    def _kz_draw_map(self):
        mr = self.map_view_rect()
        pygame.draw.rect(self.screen, COLORS["black"], mr)
        pygame.draw.rect(self.screen, COLORS["muted"], mr, 1)
        self.update_preview()
        x0, y0, x1, y1 = self.visible_bounds()
        keys = pygame.key.get_pressed()
        for y in range(y0, y1):
            for x in range(x0, x1):
                r = self.cell_rect(x, y)
                if not r.colliderect(mr):
                    continue
                c = self.game.grid[y][x]
                pygame.draw.rect(self.screen, COLORS.get(c.terrain, COLORS["open"]), r)
                self.draw_terrain(c, r, x, y)
                if c.ground_suppression > 18:
                    alpha = int(clamp(c.ground_suppression * 1.1, 20, 105))
                    self.screen.blit(
                        self.overlay_surface((r.w, r.h), (190, 105, 45), alpha),
                        r.topleft,
                    )
                if c.smoke > 0.05:
                    self.screen.blit(
                        self.overlay_surface(
                            (r.w, r.h),
                            (190, 190, 185),
                            int(clamp(c.smoke * 38, 20, 165)),
                        ),
                        r.topleft,
                    )
                if c.fire > 0:
                    pygame.draw.circle(
                        self.screen,
                        COLORS["fire"],
                        r.center,
                        max(2, int(min(r.w, r.h) * 0.18)),
                    )
                if self.show_threat:
                    th = self.game.tile_threat("player", x, y)
                    if th > 0.25:
                        self.screen.blit(
                            self.overlay_surface(
                                (r.w, r.h), (210, 70, 55), int(clamp(th * 34, 12, 100))
                            ),
                            r.topleft,
                        )
        for b in self.game.blood:
            sx, sy = self.world_to_screen(b.x, b.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(
                    self.screen,
                    COLORS["blood_dark"],
                    (sx, sy),
                    max(2, int(b.size * self.tile_px * 0.45)),
                )
        for puff in self.game.dust:
            sx, sy = self.world_to_screen(puff.x, puff.y)
            if mr.collidepoint((sx, sy)):
                alpha = int(120 * clamp(puff.life / max(0.01, puff.total), 0, 1))
                rad = max(2, int(puff.size * self.tile_px))
                surf = pygame.Surface((rad * 2 + 2, rad * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(surf, (135, 118, 91, alpha), (rad + 1, rad + 1), rad)
                self.screen.blit(surf, (sx - rad - 1, sy - rad - 1))
        for t in self.game.tracers:
            a = self.world_to_screen(*t.a)
            b = self.world_to_screen(*t.b)
            if mr.clipline(a, b):
                pygame.draw.line(self.screen, (234, 215, 145), a, b, 1)
        for i in self.game.impacts:
            sx, sy = self.world_to_screen(i.x, i.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(self.screen, COLORS["impact"], (sx, sy), 2)
        for uid, info, age in self.game.known_contacts("player", memory=10):
            u = self.game.get_unit(uid)
            if u and self.game.visible_to("player", u):
                continue
            sx, sy = self.world_to_screen(*info["pos"])
            if mr.collidepoint((sx, sy)):
                rad = int(5 + age * 1.2)
                pygame.draw.circle(self.screen, COLORS["contact"], (sx, sy), rad, 1)
                self.text("?", (sx - 3, sy - 7), 12, "contact")
        for u in self.game.units:
            if (
                u.faction == "enemy"
                and u.alive
                and (not self.game.visible_to("player", u))
            ):
                continue
            if u.overwatch or u.fire_lane:
                self.draw_arc(u)
            self.draw_unit(u)
        for e in self.game.explosions:
            sx, sy = self.world_to_screen(e.x, e.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(
                    self.screen,
                    COLORS["danger"] if e.kind == "HE" else COLORS["smoke"],
                    (sx, sy),
                    int(e.radius * self.tile_px),
                    1,
                )
                self.text(f"{e.timer:.1f}", (sx - 10, sy - 8), 12, "white")
        self.draw_tactical_previews()
        self.draw_planned_orders()
        if keys[pygame.K_LALT]:
            self.draw_directional_cover(self.map_cell_from_mouse(self.mouse))
        self.draw_selection_box()
        if self.game.victory or self.game.defeat:
            self.draw_after_action()

    def _kz_draw_sidebar(self):
        x = SIDEBAR_X
        pygame.draw.rect(
            self.screen, COLORS["panel"], (x, MAP_Y, WINDOW_W - x - 12, MAP_VIEW_H_PX)
        )
        self.text("SELECTED", (x + 14, MAP_Y + 10), 18, "white")
        us = self.selected_units()
        y = MAP_Y + 38
        if not us:
            self.text("No units selected", (x + 14, y), 13, "muted")
        else:
            firing = sum((1 for u in us if u.order == "fire"))
            reloading = sum((1 for u in us if u.reload_timer > 0))
            pinned = sum((1 for u in us if u.suppression >= 80))
            wounded = sum((1 for u in us if u.casualty == "wounded"))
            self.text(
                f"{len(us)} troops | fire {firing} rld {reloading} pin {pinned} wnd {wounded}",
                (x + 14, y),
                11,
                "status",
            )
            y += 20
            for u in us[:4]:
                self.text(
                    f"SQ{getattr(u, 'squad_id', 0)} {u.role} #{u.uid}",
                    (x + 14, y),
                    13,
                    "select",
                )
                y += 17
                self.text(
                    f"HP {u.hp:.0f}  MOR {u.morale:.0f}  SUP {u.suppression:.0f}  STA {u.stamina:.0f}",
                    (x + 14, y),
                    11,
                )
                y += 15
                self.text(
                    f"{u.weapon_name} {u.ammo} | {u.order} | {u.fire_discipline}",
                    (x + 14, y),
                    11,
                    "muted",
                )
                y += 19
        self.text("FIELD REPORT", (x + 14, max(y + 4, MAP_Y + 300)), 15, "white")
        yy = max(y + 24, MAP_Y + 322)
        for line in self.game.log[-8:]:
            self.text(line[:42], (x + 14, yy), 11, "muted")
            yy += 16
        if pygame.key.get_pressed()[pygame.K_LALT]:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                cx, cy = cell
                c = self.game.grid[cy][cx]
                td = TERRAIN[c.terrain]
                base = MAP_Y + MAP_VIEW_H_PX - 96
                pygame.draw.rect(
                    self.screen,
                    COLORS["panel2"],
                    (x + 8, base - 5, WINDOW_W - x - 28, 88),
                    border_radius=3,
                )
                self.text("TILE INTEL [LALT]", (x + 14, base), 11, "select")
                self.text(
                    f"{cell} {c.terrain.upper()} cover {td['cover']} conceal {td['conceal']}",
                    (x + 14, base + 17),
                    11,
                    "white",
                )
                self.text(
                    f"move x{td['move']:.2f} smoke {c.smoke:.1f} suppression {c.ground_suppression:.0f}",
                    (x + 14, base + 34),
                    11,
                    "muted",
                )
                self.text(
                    f"known threat {self.game.tile_threat('player', cx, cy):.1f}",
                    (x + 14, base + 51),
                    11,
                    "contact",
                )
                self.text(
                    "edge colors: green strong / yellow partial / red open",
                    (x + 14, base + 68),
                    10,
                    "muted",
                )

    def _kz_draw_bottom_ui(self):
        y0 = MAP_Y + MAP_VIEW_H_PX + 2
        pygame.draw.rect(self.screen, COLORS["panel"], (0, y0, WINDOW_W, WINDOW_H - y0))
        for key, r in self.squad_rects().items():
            active = (
                key == "ALL"
                and len(self.selected)
                == len([u for u in self.game.living("player") if u.combat_effective])
                or (
                    key != "ALL"
                    and self.selected
                    and all(
                        (
                            getattr(self.game.get_unit(i), "squad_id", -1) == key
                            for i in self.selected
                            if self.game.get_unit(i)
                        )
                    )
                )
            )
            pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=3)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if active else COLORS["muted"],
                r,
                1,
                border_radius=3,
            )
            lab = "ALL" if key == "ALL" else f"SQUAD {chr(64 + int(key))}"
            ss = self.get_font(11).render(lab, True, COLORS["white"])
            self.screen.blit(
                ss, (r.centerx - ss.get_width() // 2, r.centery - ss.get_height() // 2)
            )
        for u, r in self.unit_card_rects():
            sel = u.uid in self.selected
            pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=2)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if sel else COLORS["muted"],
                r,
                2 if sel else 1,
                border_radius=2,
            )
            abbr = {
                "Rifleman": "RF",
                "Machine Gunner": "MG",
                "Sniper": "SN",
                "Medic": "MED",
                "Engineer": "ENG",
                "Recon": "REC",
                "Grenadier": "GRN",
                "Assault": "AS",
                "Automatic Rifleman": "AR",
                "Marksman": "DMR",
                "HMG Crew": "HMG",
                "Mortar Team": "MTR",
            }.get(u.role, "INF")
            self.text(abbr, (r.x + 4, r.y + 3), 10, "white")
            self.text(
                f"{u.hp:.0f}",
                (r.x + 4, r.y + 18),
                9,
                "good" if u.hp > u.max_hp * 0.5 else "danger",
            )
            pygame.draw.rect(self.screen, (30, 30, 28), (r.x + 30, r.y + 20, 30, 3))
            pygame.draw.rect(
                self.screen,
                COLORS["contact"],
                (r.x + 30, r.y + 20, int(30 * u.suppression / 100), 3),
            )
        us = self.selected_units()
        if us:
            for name, r in self.command_bar_rects().items():
                pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=3)
                pygame.draw.rect(self.screen, COLORS["muted"], r, 1, border_radius=3)
                label = name
                if name == "FORMATION":
                    label = self.formation.upper()
                elif name == "DISCIPLINE":
                    label = us[0].fire_discipline.upper()
                elif name == "PRIORITY":
                    label = us[0].target_priority.upper()
                elif name == "AUTO":
                    label = (
                        "AUTO ON"
                        if all(
                            (
                                u.auto_reload
                                and u.auto_cover
                                and u.auto_smoke
                                and u.auto_medic
                                for u in us
                            )
                        )
                        else "AUTO OFF"
                    )
                ss = self.get_font(10).render(
                    label,
                    True,
                    COLORS["select"]
                    if name in ("ASSAULT", "FORMATION")
                    else COLORS["white"],
                )
                self.screen.blit(
                    ss,
                    (r.centerx - ss.get_width() // 2, r.centery - ss.get_height() // 2),
                )

    def _kz_draw_topbar(self):
        pygame.draw.rect(self.screen, COLORS["panel"], (0, 0, WINDOW_W, 52))
        self.text("KILL ZONE", (18, 10), 26, "white")
        slow = self.state == "game" and pygame.key.get_pressed()[pygame.K_BACKQUOTE]
        status = (
            "DEPLOYMENT"
            if self.state == "deployment"
            else "PAUSED — ORDERS CAN BE PLANNED"
            if self.game.paused
            else f"REALTIME ×{self.speed:g}{(' TACTICAL SLOW' if slow else '')}"
        )
        self.text(
            status,
            (190, 18),
            13,
            "select" if self.game.paused or self.state == "deployment" else "good",
        )
        self.text(
            f"Seed {self.game.seed} | {self.game.weather.upper()} | zoom {self.zoom:.2f}x",
            (500, 18),
            12,
            "muted",
        )
        self.text(
            f"MODE {self.command_mode.upper()} | FORM {self.formation.upper()}",
            (820, 18),
            12,
            "contact",
        )
        if self.game.player_reserves:
            self.text(
                f"F12 RESERVES {len(self.game.player_reserves)}",
                (1100, 18),
                11,
                "select",
            )
        if self.show_fps:
            self.text(f"{self.clock.get_fps():.0f} FPS", (WINDOW_W - 92, 8), 10, "good")
        if self.show_perf:
            self.text(
                f"SIM {self.game._perf.get('sim_ms', 0):.2f}ms PATH {self.game._perf.get('path_ms', 0):.2f}ms/{self.game._perf.get('paths', 0)} AI {self.game._perf.get('ai_ms', 0):.2f}ms",
                (WINDOW_W - 350, 29),
                9,
                "muted",
            )

    def _kz_draw_after_action(self):
        w, h = (620, 420)
        x = MAP_X + (MAP_VIEW_W_PX - w) // 2
        y = MAP_Y + 55
        pygame.draw.rect(self.screen, COLORS["panel"], (x, y, w, h))
        pygame.draw.rect(self.screen, COLORS["select"], (x, y, w, h), 3)
        title = "VICTORY" if self.game.victory else "DEFEAT"
        self.text(title, (x + 25, y + 18), 32, "white")
        self.text(
            f"Battle duration {self.game.time:.1f}s   Seed {self.game.seed}",
            (x + 25, y + 58),
            13,
            "muted",
        )
        yy = y + 95
        for f, label in [("player", "YOUR FORCE"), ("enemy", "OPPOSITION")]:
            st = self.game.stats[f]
            alive = sum((1 for u in self.game.living(f) if u.combat_effective))
            self.text(label, (x + 25, yy), 16, "select")
            yy += 23
            self.text(
                f"alive {alive}  casualties {st['casualties']}  shots {st['shots']}  hits {st['hits']}  kills {st['kills']}",
                (x + 25, yy),
                12,
                "white",
            )
            yy += 19
            acc = 100 * st["hits"] / st["shots"] if st["shots"] else 0
            self.text(
                f"accuracy {acc:.1f}%  grenades {st['grenades']}  smoke {st['smoke']}  reserves {st['reserves']}",
                (x + 25, yy),
                12,
                "muted",
            )
            yy += 32
        self.text("RECENT TIMELINE", (x + 25, yy), 14, "select")
        yy += 22
        for ev in self.game.battle_events[-7:]:
            self.text(
                f"{ev['time']:5.1f}s  {ev['text']}"[:72], (x + 25, yy), 11, "muted"
            )
            yy += 17
        self.text("F5 new battle • Esc menu", (x + 25, y + h - 28), 11, "white")

    def _kz_draw_deployment(self):
        self.draw_topbar()
        self.draw_map()
        self.draw_sidebar()
        self.draw_command_bar()
        overlay = pygame.Rect(MAP_X + 220, MAP_Y + 12, 650, 60)
        pygame.draw.rect(self.screen, COLORS["panel"], overlay)
        pygame.draw.rect(self.screen, COLORS["select"], overlay, 2)
        self.text("PRE-BATTLE DEPLOYMENT", (overlay.x + 12, overlay.y + 8), 16, "white")
        self.text(
            "Select troops/squads, RMB inside west deployment zone to place. Enter/Space starts battle.",
            (overlay.x + 12, overlay.y + 31),
            11,
            "muted",
        )
        x = int(MAP_X + (self.game.deployment_zone_x - self.camera_x) * self.tile_px)
        pygame.draw.line(
            self.screen, COLORS["select"], (x, MAP_Y), (x, MAP_Y + MAP_VIEW_H_PX), 2
        )

    def _kz_draw(self):
        if self.state == "deployment":
            self.screen.fill(COLORS["bg"])
            self.draw_deployment()
            self.present()
            return
        if self.state == "game":
            self.screen.fill(COLORS["bg"])
            self.draw_topbar()
            self.draw_map()
            self.draw_sidebar()
            self.draw_command_bar()
            if self.show_help:
                self.draw_help()
            self.present()
            return
        self._base_draw()

    def _kz_draw_settings(self):
        self.draw_menu_background()
        title = self.get_font(48).render("SETTINGS", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 75))
        self.text("DEFAULT SIMULATION SPEED", (WINDOW_W // 2 - 330, 194), 16, "muted")
        for name, r in self.settings_rects().items():
            if name.startswith("speed") and name != "fpscap":
                val = {"speed05": 0.5, "speed1": 1.0, "speed2": 2.0}[name]
                lab = f"{val:g}×"
                self.button(
                    r,
                    "[ " + lab + " ]" if self.menu_speed == val else lab,
                    self.mouse,
                    accent=self.menu_speed == val,
                )
            elif name == "help":
                self.button(
                    r,
                    f"HELP ON BATTLE START: {('ON' if self.menu_show_help else 'OFF')}",
                    self.mouse,
                    accent=self.menu_show_help,
                )
            elif name == "audio":
                self.button(
                    r,
                    f"COMBAT AUDIO: {('ON' if self.audio_enabled else 'OFF')}",
                    self.mouse,
                    accent=self.audio_enabled,
                )
            elif name == "fps":
                self.button(
                    r,
                    f"FPS COUNTER: {('ON' if self.show_fps else 'OFF')}",
                    self.mouse,
                    accent=self.show_fps,
                )
            elif name == "perf":
                self.button(
                    r,
                    f"PERFORMANCE PROFILER: {('ON' if self.show_perf else 'OFF')}",
                    self.mouse,
                    accent=self.show_perf,
                )
            elif name == "fpscap":
                self.button(
                    r,
                    "RENDER FPS: UNCAPPED"
                    if self.fps_cap == 0
                    else f"RENDER FPS: {self.fps_cap}",
                    self.mouse,
                    accent=self.fps_cap == 0,
                )
            elif name == "fullscreen":
                mode = {
                    "windowed": "WINDOWED",
                    "borderless": "BORDERLESS FULLSCREEN",
                    "exclusive": "EXCLUSIVE FULLSCREEN",
                }.get(self.display_mode, self.display_mode.upper())
                self.button(
                    r,
                    f"DISPLAY MODE: {mode}  (F11 toggle)",
                    self.mouse,
                    accent=self.display_mode != "windowed",
                )
            elif name == "back":
                self.button(r, "BACK", self.mouse)

    def _kz_draw_help(self):
        w, h = (860, 650)
        x = (WINDOW_W - w) // 2
        y = (WINDOW_H - h) // 2
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((20, 23, 20, 244))
        self.screen.blit(ov, (x, y))
        pygame.draw.rect(self.screen, COLORS["select"], (x, y, w, h), 2)
        self.text("REALTIME FIELD MANUAL", (x + 22, y + 16), 24, "white")
        lines = [
            "LMB select / drag box | RMB move/attack | Shift+RMB queue | Space pause and plan orders",
            "Middle-drag camera | arrows/edge scroll | mouse wheel zoom | Home focus selection | F11 fullscreen toggle",
            "Alt+1..5 assign persistent Squad A–E | click squad tabs to select | Ctrl+1..9 control groups",
            "F2 ASSAULT then RMB objective: support-by-fire + smoke + assault movement | F3 bounding overwatch",
            "Left Alt directional cover intel | hover enemy for LOS/hit preview | hover ground for route/exposure/ETA",
            "Tab threat overlay | F4 formation | F7 fire discipline | F8 target priority | F10 autonomy",
            "F12 commits reserves | F9 performance profiler | renderer is uncapped by default",
            "MG/HMG suppression creates movement windows; crossfire and enfilade degrade defensive stability",
            "Mortars require 5–19 tile range and range-in; Recon/Marksman observation tightens dispersion",
            "Snipers gain concealment/first-shot benefits when settled; repeated fire increases signature",
            "Friendly troops locally avoid traffic jams; trench destinations compress formations into column",
            "Difficulty changes numbers and tactical coordination, not hidden accuracy bonuses",
            "",
            "ATTACKING PREPARED POSITIONS",
            "1. Recon the line and identify MG sectors.  2. Suppress or overload the position from two bearings.",
            "3. Layer smoke across the dangerous crossing.  4. Move assault troops while support keeps firing.",
            "5. Enter along a flank/enfilade angle; defenders may fall back to secondary positions instead of last-standing.",
            "",
            "PERFORMANCE",
            "Pathfinding and AI decisions are budgeted across ticks; threat/occupancy are cached and transient effects are capped.",
            "The F9 profiler shows simulation, path and AI milliseconds. Render FPS can be capped again in Settings if desired.",
        ]
        yy = y + 54
        for line in lines:
            self.text(
                line,
                (x + 22, yy),
                11,
                "select"
                if line in ("ATTACKING PREPARED POSITIONS", "PERFORMANCE")
                else "text"
                if line and line[0].isdigit()
                else "muted",
            )
            yy += 22

    def _vs_draw_briefing(self):
        self.draw_menu_background()
        self.text("MISSION BRIEFING", (70, 55), 38, "white")
        self.text(self.game.mission_title, (70, 112), 22, "select")
        lo, hi = self.game.enemy_estimate
        self.text(
            f"Seed {self.game.seed}  •  {self.game.weather.upper()}  •  estimated enemy strength {lo}–{hi}",
            (70, 151),
            13,
            "muted",
        )
        self.text(self.game.mission_brief, (70, 188), 14, "text")
        self.text("TASK", (70, 242), 16, "select")
        yy = 274
        for i, obj in enumerate(self.game.objectives, 1):
            self.text(f"{i}. {obj['title']}", (88, yy), 16, "white")
            yy += 24
            self.text(obj["desc"], (112, yy), 12, "muted")
            yy += 39
        self.text("COMMANDER'S NOTES", (790, 242), 16, "select")
        notes = [
            "• Recon before committing the whole force.",
            "• Suppression, smoke and crossfire are the intended tools for cracking Line 1.",
            "• Expect the enemy to fall back and commit a reserve rather than die in place.",
            "• A local breach can trigger a counterattack around the central strongpoint.",
            "• The final objective is the rear command bunker, not extermination of every defender.",
        ]
        yy2 = 278
        for line in notes:
            self.text(line, (806, yy2), 12, "muted")
            yy2 += 32
        self.button(
            pygame.Rect(WINDOW_W // 2 - 150, 690, 300, 46),
            "BEGIN DEPLOYMENT",
            self.mouse,
            accent=True,
        )
        self.button(pygame.Rect(34, 690, 180, 42), "BACK", self.mouse)

    def draw_objectives(self):
        for i, obj in enumerate(self.game.objectives):
            if obj["state"] == "locked" and i > self.game.objective_index + 1:
                continue
            sx, sy = self.world_to_screen(*obj["pos"])
            if not self.map_view_rect().inflate(40, 40).collidepoint((sx, sy)):
                continue
            col = (
                COLORS["good"]
                if obj["state"] == "complete"
                else COLORS["objective"]
                if obj["state"] == "active"
                else COLORS["muted"]
            )
            pygame.draw.circle(self.screen, col, (sx, sy), 14, 2)
            self.text(str(i + 1), (sx - 4, sy - 9), 12, col)
            if obj["state"] == "active":
                self.text(obj["title"], (sx + 18, sy - 8), 10, "white")

    def draw_assault_plan(self):
        for ao in getattr(self.game, "assault_orders", []):
            ds = self.world_to_screen(*ao.dest)
            support = [self.game.get_unit(uid) for uid in ao.support]
            assault = [self.game.get_unit(uid) for uid in ao.assault]
            support = [u for u in support if u and u.combat_effective]
            assault = [u for u in assault if u and u.combat_effective]
            for u in support:
                a = self.world_to_screen(u.x, u.y)
                pygame.draw.line(self.screen, COLORS["suppression"], a, ds, 2)
            for u in assault:
                a = self.world_to_screen(u.x, u.y)
                pygame.draw.line(self.screen, COLORS["select"], a, ds, 2)
            if support:
                self.text(
                    "SUPPORT / SUPPRESS", (ds[0] + 18, ds[1] - 28), 10, "suppression"
                )
            if assault:
                self.text("ASSAULT", (ds[0] + 18, ds[1] - 12), 10, "select")

    def draw_contact_intel(self):
        for uid, info, age in self.game.known_contacts("player", memory=10):
            u = self.game.get_unit(uid)
            if u and self.game.visible_to("player", u):
                continue
            sx, sy = self.world_to_screen(*info["pos"])
            if not self.map_view_rect().collidepoint((sx, sy)):
                continue
            rad = int(8 + age * 2.0)
            pygame.draw.circle(self.screen, COLORS["contact"], (sx, sy), rad, 1)
            ab = ROLE_CONTACT.get(info.get("role", ""), "CONTACT").split()[0][:4]
            self.text(f"{ab}? {age:.0f}s", (sx + rad + 3, sy - 7), 9, "contact")

    def draw_notifications(self):
        x = MAP_X + 12
        y = MAP_Y + 12
        for n in self.game.notifications[-4:]:
            col = (
                "danger"
                if n["kind"] == "danger"
                else "good"
                if n["kind"] == "good"
                else "objective"
                if n["kind"] == "objective"
                else "white"
            )
            surf = self.get_font(12).render(n["text"], True, COLORS[col])
            r = pygame.Rect(x, y, surf.get_width() + 16, 24)
            pygame.draw.rect(self.screen, (27, 30, 26), r)
            pygame.draw.rect(self.screen, COLORS[col], r, 1)
            self.screen.blit(surf, (x + 8, y + 5))
            y += 28

    def draw_objective_panel(self):
        obj = self.game.current_objective
        if not obj:
            return
        x = SIDEBAR_X + 8
        y = 70
        w = WINDOW_W - SIDEBAR_X - 18
        pygame.draw.rect(self.screen, COLORS["panel2"], (x, y, w, 82), border_radius=3)
        pygame.draw.rect(
            self.screen, COLORS["objective"], (x, y, w, 82), 1, border_radius=3
        )
        self.text(
            f"OBJECTIVE {self.game.objective_index + 1}/{len(self.game.objectives)}",
            (x + 10, y + 8),
            11,
            "objective",
        )
        self.text(obj["title"], (x + 10, y + 26), 12, "white")
        pygame.draw.rect(self.screen, (25, 27, 24), (x + 10, y + 52, w - 20, 8))
        pygame.draw.rect(
            self.screen,
            COLORS["objective"],
            (x + 10, y + 52, int((w - 20) * clamp(obj["progress"], 0, 1)), 8),
        )
        self.text(f"{obj['progress'] * 100:.0f}%", (x + w - 45, y + 64), 9, "muted")

    def _vs_draw_map2(self):
        self._kz_draw_map()
        if self.state in ("game", "deployment"):
            self.draw_objectives()
            self.draw_contact_intel()
            self.draw_assault_plan()
            self.draw_notifications()

    def _vs_draw_sidebar2(self):
        x = SIDEBAR_X
        w = WINDOW_W - x - 12
        pygame.draw.rect(self.screen, COLORS["panel"], (x, MAP_Y, w, MAP_VIEW_H_PX))
        obj = self.game.current_objective
        y = MAP_Y + 9
        if obj:
            pygame.draw.rect(
                self.screen, COLORS["panel2"], (x + 8, y, w - 16, 76), border_radius=3
            )
            pygame.draw.rect(
                self.screen,
                COLORS["objective"],
                (x + 8, y, w - 16, 76),
                1,
                border_radius=3,
            )
            self.text(
                f"OBJECTIVE {self.game.objective_index + 1}/{len(self.game.objectives)}",
                (x + 16, y + 7),
                10,
                "objective",
            )
            self.text(obj["title"][:34], (x + 16, y + 24), 11, "white")
            pygame.draw.rect(self.screen, (25, 27, 24), (x + 16, y + 48, w - 32, 7))
            pygame.draw.rect(
                self.screen,
                COLORS["objective"],
                (x + 16, y + 48, int((w - 32) * clamp(obj["progress"], 0, 1)), 7),
            )
            self.text(f"{obj['progress'] * 100:.0f}%", (x + w - 45, y + 59), 9, "muted")
            y += 88
        self.text("SELECTED", (x + 14, y), 15, "white")
        y += 22
        us = self.selected_units()
        if not us:
            self.text("No units selected", (x + 14, y), 12, "muted")
            y += 24
        else:
            firing = sum((1 for u in us if u.order == "fire"))
            reloading = sum((1 for u in us if u.reload_timer > 0))
            pinned = sum((1 for u in us if u.suppression >= 80))
            wounded = sum((1 for u in us if u.casualty == "wounded"))
            self.text(
                f"{len(us)} troops | fire {firing} rld {reloading} pin {pinned} wnd {wounded}",
                (x + 14, y),
                10,
                "status",
            )
            y += 18
            for u in us[:3]:
                name = getattr(
                    u, "display_name", f"SQ{getattr(u, 'squad_id', 0)} #{u.uid}"
                )
                self.text(f"{name} — {u.role}"[:39], (x + 14, y), 11, "select")
                y += 15
                self.text(
                    f"HP {u.hp:.0f} MOR {u.morale:.0f} SUP {u.suppression:.0f} STA {u.stamina:.0f}",
                    (x + 14, y),
                    10,
                    "text",
                )
                y += 14
                self.text(
                    f"{u.weapon_name} {u.ammo} | {u.order} | {u.fire_discipline}",
                    (x + 14, y),
                    9,
                    "muted",
                )
                y += 18
        report_y = max(y + 5, MAP_Y + 315)
        self.text("FIELD REPORT", (x + 14, report_y), 13, "white")
        yy = report_y + 20
        for line in self.game.log[-7:]:
            self.text(line[:43], (x + 14, yy), 10, "muted")
            yy += 15
        sec_y = min(MAP_Y + MAP_VIEW_H_PX - 145, yy + 7)
        self.text("ENEMY LINE STABILITY", (x + 14, sec_y), 10, "muted")
        sec_y += 15
        for sec in ("NORTH", "CENTRE", "SOUTH"):
            st = self.game.sector_stability.get(sec, 100)
            col = "danger" if st > 65 else "contact" if st > 30 else "good"
            self.text(
                f"{sec:6s} {st:3.0f}%"
                + ("  COLLAPSED" if sec in self.game.collapsed_sectors else ""),
                (x + 14, sec_y),
                9,
                col,
            )
            sec_y += 14
        if pygame.key.get_pressed()[pygame.K_LALT]:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                cx, cy = cell
                c = self.game.grid[cy][cx]
                td = TERRAIN[c.terrain]
                base = MAP_Y + MAP_VIEW_H_PX - 96
                pygame.draw.rect(
                    self.screen,
                    COLORS["panel2"],
                    (x + 8, base - 5, w - 16, 88),
                    border_radius=3,
                )
                self.text("TILE INTEL [LALT]", (x + 14, base), 11, "select")
                self.text(
                    f"{cell} {c.terrain.upper()} cover {td['cover']} conceal {td['conceal']}",
                    (x + 14, base + 17),
                    10,
                    "white",
                )
                self.text(
                    f"move x{td['move']:.2f} smoke {c.smoke:.1f} suppression {c.ground_suppression:.0f}",
                    (x + 14, base + 34),
                    10,
                    "muted",
                )
                self.text(
                    f"known threat {self.game.tile_threat('player', cx, cy):.1f}",
                    (x + 14, base + 51),
                    10,
                    "contact",
                )
                self.text(
                    "edges: green strong / yellow partial / red open",
                    (x + 14, base + 68),
                    9,
                    "muted",
                )

    def _vs_draw_topbar2(self):
        self._kz_draw_topbar()
        if self.state in ("game", "deployment"):
            col = (
                "good"
                if self.game.battle_stage == "COLLAPSE"
                else "danger"
                if self.game.battle_stage == "CONTACT"
                else "objective"
                if self.game.battle_stage == "ASSAULT"
                else "muted"
            )
            self.text(self.game.battle_stage, (710, 36), 10, col)

    def draw_los_preview(self):
        if not self.selected:
            return
        u = self.selected_units()[0] if self.selected_units() else None
        t = self.unit_at_pixel(self.mouse)
        if not u or not t or t.faction != "enemy":
            return
        a = self.world_to_screen(u.x, u.y)
        b = self.world_to_screen(t.x, t.y)
        bd = self.game.shot_breakdown(u, t)
        hc = bd["chance"]
        clear = hc > 0
        col = (
            COLORS["good"]
            if hc >= 55
            else COLORS["contact"]
            if clear
            else COLORS["danger"]
        )
        pygame.draw.line(self.screen, col, a, b, 2)
        box = pygame.Rect(MAP_X + 12, MAP_Y + MAP_VIEW_H_PX - 150, 365, 142)
        pygame.draw.rect(self.screen, COLORS["panel2"], box)
        pygame.draw.rect(self.screen, col, box, 1)
        self.text(
            f"HIT {hc:.0f}%   RANGE {bd.get('range', 0):.1f}/{u.weapon['range']:.0f}",
            (box.x + 8, box.y + 7),
            12,
            "white",
        )
        yy = box.y + 27
        mods = [m for m in bd.get("mods", []) if abs(m[1]) >= 2 and m[1] > -900]
        if mods:
            base = mods[0]
            self.text(f"{base[0]:22s} {base[1]:+5.0f}", (box.x + 8, yy), 10, "muted")
            yy += 16
            for name, val in sorted(mods[1:], key=lambda z: abs(z[1]), reverse=True)[
                :5
            ]:
                self.text(
                    f"{name:22s} {val:+5.0f}",
                    (box.x + 8, yy),
                    10,
                    "good" if val > 0 else "danger",
                )
                yy += 16
        status = (
            "PINNED"
            if t.suppression >= 80
            else "SUPPRESSED"
            if t.suppression >= 50
            else "UNDER FIRE"
            if t.suppression >= 20
            else "CALM"
        )
        self.text(
            f"target: {ROLE_CONTACT.get(t.role, t.role)} — {status}",
            (box.x + 8, box.bottom - 19),
            10,
            "contact",
        )

    def _vs_draw_terrain2(self, c, r, x, y):
        self._base_draw_terrain(c, r, x, y)
        tp = max(1, r.w)
        seed = x * 73856093 ^ y * 19349663 ^ self.game.seed * 83492791
        rr = random.Random(seed)
        ink = (38, 40, 34)
        if c.terrain in ("trench", "firing_step"):
            pygame.draw.line(
                self.screen,
                (48, 40, 31),
                (r.left + 2, r.top + 3),
                (r.right - 3, r.top + 3),
                1,
            )
            pygame.draw.line(
                self.screen,
                (48, 40, 31),
                (r.left + 2, r.bottom - 4),
                (r.right - 3, r.bottom - 4),
                1,
            )
        elif c.terrain == "crater":
            pygame.draw.ellipse(
                self.screen,
                (54, 47, 39),
                r.inflate(-max(4, tp // 4), -max(5, tp // 3)),
                1,
            )
        elif c.terrain == "woods":
            for _ in range(2):
                px = r.left + rr.randint(4, max(4, r.w - 4))
                py = r.top + rr.randint(4, max(4, r.h - 4))
                pygame.draw.circle(self.screen, (35, 58, 36), (px, py), max(2, tp // 8))
        elif c.terrain in ("building", "woodwall"):
            if rr.random() < 0.55:
                pygame.draw.line(
                    self.screen,
                    ink,
                    (r.left + 4, r.top + rr.randint(4, max(4, tp - 4))),
                    (r.right - 5, r.top + rr.randint(4, max(4, tp - 4))),
                    1,
                )
        elif c.terrain == "sandbags":
            for i in range(3):
                pygame.draw.circle(
                    self.screen,
                    (82, 70, 50),
                    (r.left + 5 + i * max(3, tp // 4), r.centery),
                    max(2, tp // 8),
                    1,
                )

    def _vs_draw_after_action(self):
        w, h = (760, 540)
        x = MAP_X + (MAP_VIEW_W_PX - w) // 2
        y = MAP_Y + 35
        pygame.draw.rect(self.screen, COLORS["panel"], (x, y, w, h))
        pygame.draw.rect(self.screen, COLORS["select"], (x, y, w, h), 3)
        title = (
            "VICTORY — DEFENSIVE SYSTEM COLLAPSED"
            if self.game.victory
            else "DEFEAT — ASSAULT BROKEN"
        )
        self.text(title, (x + 24, y + 18), 25, "white")
        self.text(
            f"{self.game.mission_title}   •   {self.game.time / 60:.1f} min   •   Seed {self.game.seed}",
            (x + 24, y + 54),
            12,
            "muted",
        )
        yy = y + 90
        for f, label in [("player", "YOUR FORCE"), ("enemy", "OPPOSITION")]:
            st = self.game.stats[f]
            alive = sum((1 for u in self.game.living(f) if u.combat_effective))
            acc = 100 * st["hits"] / st["shots"] if st["shots"] else 0
            self.text(label, (x + 24, yy), 15, "select")
            self.text(
                f"alive {alive}   casualties {st['casualties']}   surrendered {st['surrendered']}   kills {st['kills']}",
                (x + 150, yy + 2),
                11,
                "white",
            )
            yy += 23
            self.text(
                f"shots {st['shots']}   hits {st['hits']}   accuracy {acc:.1f}%   grenades {st['grenades']}   smoke {st['smoke']}   reserves {st['reserves']}",
                (x + 38, yy),
                11,
                "muted",
            )
            yy += 34
        self.text("OBJECTIVES", (x + 24, yy), 14, "select")
        yy += 23
        for i, obj in enumerate(self.game.objectives, 1):
            mark = "✓" if obj["state"] == "complete" else "—"
            self.text(
                f"{mark} {i}. {obj['title']}",
                (x + 38, yy),
                11,
                "good" if obj["state"] == "complete" else "muted",
            )
            yy += 18
        yy += 8
        self.text("KEY EVENTS", (x + 24, yy), 14, "select")
        yy += 22
        important = [
            e
            for e in self.game.battle_events
            if e["kind"]
            in (
                "objective",
                "collapse",
                "counterattack",
                "reserve",
                "surrender",
                "victory",
                "death",
            )
        ]
        for ev in important[-9:]:
            self.text(
                f"{ev['time'] / 60:4.1f}m  {ev['text']}"[:94], (x + 38, yy), 10, "muted"
            )
            yy += 17
        self.text(
            "F5 replay same force • Esc main menu", (x + 24, y + h - 27), 11, "white"
        )

    def _vs_draw2(self):
        self.update_ambience()
        if self.state == "briefing":
            self.screen.fill(COLORS["bg"])
            self.draw_briefing()
            self.present()
            return
        self._kz_draw()

    def _vs_draw_help2(self):
        self._kz_draw_help()
        self.text(
            "Battle flow: Briefing → Force → Deployment → staged objectives → After Action",
            (WINDOW_W // 2 - 330, WINDOW_H - 53),
            10,
            "objective",
        )

    def cached_text_surface(self, s, size, color):
        text = str(s)
        col = COLORS[color] if isinstance(color, str) else tuple(color)
        key = (text, int(size), tuple(col))
        surf = self._text_surface_cache.get(key)
        if surf is None:
            surf = self.get_font(size).render(text, True, col)
            self._text_surface_cache[key] = surf
            if len(self._text_surface_cache) > 1200:
                for _ in range(250):
                    self._text_surface_cache.pop(
                        next(iter(self._text_surface_cache)), None
                    )
        return surf

    def _perf_text(self, s, pos, size=14, color="text"):
        self.screen.blit(self.cached_text_surface(s, size, color), pos)

    def ensure_terrain_cache(self):
        tp = self.tile_px
        key = (id(self.game), self.game.seed, tp, self.game.terrain_revision)
        if self._terrain_cache_surface is not None and self._terrain_cache_key == key:
            return self._terrain_cache_surface
        t0 = time.perf_counter()
        surf = pygame.Surface((MAP_W * tp, MAP_H * tp))
        old = self.screen
        self.screen = surf
        try:
            for y in range(MAP_H):
                for x in range(MAP_W):
                    c = self.game.grid[y][x]
                    r = pygame.Rect(x * tp, y * tp, tp, tp)
                    pygame.draw.rect(surf, COLORS.get(c.terrain, COLORS["open"]), r)
                    self.draw_terrain(c, r, x, y)
        finally:
            self.screen = old
        self._terrain_cache_surface = surf
        self._terrain_cache_key = key
        self._terrain_cache_build_ms = (time.perf_counter() - t0) * 1000
        return surf

    def refresh_dynamic_tiles(self):
        now = time.perf_counter()
        if now - self._dynamic_tiles_at < 0.085:
            return
        self._dynamic_tiles_at = now
        out = []
        for y, row in enumerate(self.game.grid):
            for x, c in enumerate(row):
                if c.ground_suppression > 18 or c.smoke > 0.05 or c.fire > 0:
                    out.append((x, y, c.ground_suppression, c.smoke, c.fire))
        self._dynamic_tiles = out

    def _perf_draw_unit2(self, u):
        cx, cy = self.world_to_screen(u.x, u.y)
        tp = self.tile_px
        if not self.map_view_rect().inflate(30, 30).collidepoint((cx, cy)):
            return
        if u.casualty == "dead":
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx - 6, cy - 6), (cx + 6, cy + 6), 2
            )
            pygame.draw.line(
                self.screen, (65, 47, 42), (cx + 6, cy - 6), (cx - 6, cy + 6), 2
            )
            return
        if u.casualty == "surrendered":
            pygame.draw.rect(self.screen, COLORS["muted"], (cx - 8, cy - 5, 16, 10), 1)
            ss = self.cached_text_surface("SURR", 9, "muted")
            self.screen.blit(ss, (cx - ss.get_width() // 2, cy + 7))
            return
        friend = u.faction == "player"
        fill = COLORS["nato_friend"] if friend else COLORS["nato_hostile"]
        ink = COLORS["black"]
        sw = max(16, int(tp * 0.85))
        sh = max(12, int(tp * 0.56))
        if friend:
            r = pygame.Rect(cx - sw // 2, cy - sh // 2, sw, sh)
            pygame.draw.rect(self.screen, fill, r)
            pygame.draw.rect(self.screen, ink, r, 2)
            pygame.draw.line(
                self.screen,
                ink,
                (r.left + 2, r.top + 2),
                (r.right - 2, r.bottom - 2),
                2,
            )
            pygame.draw.line(
                self.screen,
                ink,
                (r.right - 2, r.top + 2),
                (r.left + 2, r.bottom - 2),
                2,
            )
        else:
            rad = max(9, int(tp * 0.42))
            pts = [(cx, cy - rad), (cx + rad, cy), (cx, cy + rad), (cx - rad, cy)]
            pygame.draw.polygon(self.screen, fill, pts)
            pygame.draw.polygon(self.screen, ink, pts, 2)
            pygame.draw.line(self.screen, ink, (cx - 6, cy - 6), (cx + 6, cy + 6), 2)
            pygame.draw.line(self.screen, ink, (cx + 6, cy - 6), (cx - 6, cy + 6), 2)
        role = {
            "Rifleman": "RF",
            "Machine Gunner": "MG",
            "Sniper": "SN",
            "Medic": "MED",
            "Engineer": "ENG",
            "Recon": "REC",
            "Grenadier": "GRN",
            "Assault": "ASLT",
            "Automatic Rifleman": "AR",
            "Marksman": "DMR",
            "HMG Crew": "HMG",
            "Mortar Team": "MTR",
        }.get(u.role, "INF")
        surf = self.cached_text_surface(role, 10 if tp < 24 else 12, "white")
        self.screen.blit(surf, (cx - surf.get_width() // 2, cy + max(8, sh // 2 + 2)))
        if u.uid in self.selected:
            pygame.draw.circle(
                self.screen, COLORS["select"], (cx, cy), max(14, int(tp * 0.6)), 2
            )
        ang = math.radians(u.facing)
        pygame.draw.line(
            self.screen,
            COLORS["white"],
            (cx, cy),
            (
                cx + math.cos(ang) * max(11, tp * 0.48),
                cy + math.sin(ang) * max(11, tp * 0.48),
            ),
            1,
        )
        bw = max(20, int(tp * 0.85))
        pygame.draw.rect(
            self.screen,
            (30, 30, 28),
            (cx - bw // 2, cy + max(17, int(tp * 0.78)), bw, 3),
        )
        pygame.draw.rect(
            self.screen,
            COLORS["good"],
            (
                cx - bw // 2,
                cy + max(17, int(tp * 0.78)),
                int(bw * clamp(u.hp / u.max_hp, 0, 1)),
                3,
            ),
        )
        if u.suppression > 12:
            col = (
                COLORS["contact"]
                if u.suppression < 55
                else COLORS["suppression"]
                if u.suppression < 80
                else COLORS["danger"]
            )
            pygame.draw.circle(
                self.screen,
                col,
                (cx, cy),
                max(15, int(tp * 0.64)),
                1 if u.suppression < 55 else 2,
            )
        state = getattr(u, "morale_state", "STEADY")
        status = ""
        if u.reload_timer > 0:
            status = "RLD"
        elif u.jammed:
            status = "JAM"
        elif u.order == "rout":
            status = "RTE"
        elif state == "BREAKING":
            status = "BRK"
        elif state == "PINNED" or u.suppression >= 80:
            status = "PIN"
        elif state == "RALLYING":
            status = "RLY"
        elif self.game.time < u.disoriented_until:
            status = "CON"
        elif u.order == "suppress":
            status = "SUP"
        elif u.overwatch:
            status = "OW"
        elif u.order == "move":
            status = "MOV"
        if status:
            ss = self.cached_text_surface(status, 10, "status")
            self.screen.blit(
                ss, (cx - ss.get_width() // 2, cy - max(21, int(tp * 0.8)))
            )

    def draw_arc(self, u):
        if not u.combat_effective or not u.alive or (not (u.overwatch or u.fire_lane)):
            return
        center = self.world_to_screen(u.x, u.y)
        if (
            not self.map_view_rect()
            .inflate(int(u.arc_range * self.tile_px), int(u.arc_range * self.tile_px))
            .collidepoint(center)
        ):
            return
        radius = int(u.arc_range * self.tile_px)
        a1 = math.radians(u.fire_lane_center - u.arc_width / 2)
        a2 = math.radians(u.fire_lane_center + u.arc_width / 2)
        col = COLORS["danger"] if u.faction == "enemy" else COLORS["contact"]
        pygame.draw.line(
            self.screen,
            col,
            center,
            (center[0] + math.cos(a1) * radius, center[1] + math.sin(a1) * radius),
            1,
        )
        pygame.draw.line(
            self.screen,
            col,
            center,
            (center[0] + math.cos(a2) * radius, center[1] + math.sin(a2) * radius),
            1,
        )

    def draw_profiler_panel(self):
        if not self.show_perf:
            return
        rp = self._render_perf
        gp = self.game._perf
        x = MAP_X + MAP_VIEW_W_PX - 286
        y = MAP_Y + 10
        w = 274
        h = 154
        pygame.draw.rect(self.screen, (24, 27, 23), (x, y, w, h))
        pygame.draw.rect(self.screen, COLORS["muted"], (x, y, w, h), 1)
        lines = [
            f"FPS {self.clock.get_fps():5.1f}   FRAME {rp.get('frame_ms', 0):5.2f} ms",
            f"MAP {rp.get('map_ms', 0):5.2f}  STATIC {rp.get('terrain_ms', 0):5.2f}  DYN {rp.get('dynamic_ms', 0):5.2f}",
            f"UNITS/FX {rp.get('units_ms', 0):5.2f}   UI {rp.get('ui_ms', 0):5.2f}",
            f"SIM {gp.get('sim_ms', 0):5.2f}  AI {gp.get('ai_ms', 0):5.2f}/{gp.get('ai_decisions', 0)}",
            f"PATH {gp.get('path_ms', 0):5.2f}/{gp.get('paths', 0)}  LOS {gp.get('los_ms', 0):5.2f}",
            f"LOS calls {gp.get('los_calls', 0)} hit {gp.get('los_hits', 0) + gp.get('line_hits', 0)}",
            f"visible {rp.get('visible_units', 0)}  dynamic tiles {rp.get('dynamic_tiles', 0)}",
            f"tracers {len(self.game.tracers)}  smoke/expl {len(self.game.explosions)}  decals {len(self.game.blood)}",
        ]
        self.text("PERFORMANCE [F9]", (x + 8, y + 7), 10, "select")
        yy = y + 24
        for line in lines:
            self.text(line, (x + 8, yy), 9, "muted")
            yy += 15

    def _perf_draw_map3(self):
        t0 = time.perf_counter()
        mr = self.map_view_rect()
        pygame.draw.rect(self.screen, COLORS["black"], mr)
        self.update_preview()
        x0, y0, x1, y1 = self.visible_bounds()
        keys = pygame.key.get_pressed()
        ts = time.perf_counter()
        terrain = self.ensure_terrain_cache()
        tp = self.tile_px
        src = pygame.Rect(
            int(self.camera_x * tp),
            int(self.camera_y * tp),
            MAP_VIEW_W_PX,
            MAP_VIEW_H_PX,
        )
        ox, oy = self.shake_offset
        self.screen.blit(terrain, (MAP_X + ox, MAP_Y + oy), src)
        pygame.draw.rect(self.screen, COLORS["muted"], mr, 1)
        terrain_ms = (time.perf_counter() - ts) * 1000
        td = time.perf_counter()
        self.refresh_dynamic_tiles()
        dynamic_count = 0
        for x, y, supp, smoke, fire in self._dynamic_tiles:
            if not (x0 <= x < x1 and y0 <= y < y1):
                continue
            r = self.cell_rect(x, y)
            if not r.colliderect(mr):
                continue
            dynamic_count += 1
            if supp > 18:
                self.screen.blit(
                    self.overlay_surface(
                        (r.w, r.h), (190, 105, 45), int(clamp(supp * 1.1, 20, 105))
                    ),
                    r.topleft,
                )
            if smoke > 0.05:
                self.screen.blit(
                    self.overlay_surface(
                        (r.w, r.h), (190, 190, 185), int(clamp(smoke * 38, 20, 165))
                    ),
                    r.topleft,
                )
            if fire > 0:
                pygame.draw.circle(
                    self.screen,
                    COLORS["fire"],
                    r.center,
                    max(2, int(min(r.w, r.h) * 0.18)),
                )
        if self.show_threat:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    th = self.game.tile_threat("player", x, y)
                    if th > 0.25:
                        r = self.cell_rect(x, y)
                        if r.colliderect(mr):
                            self.screen.blit(
                                self.overlay_surface(
                                    (r.w, r.h),
                                    (210, 70, 55),
                                    int(clamp(th * 34, 12, 100)),
                                ),
                                r.topleft,
                            )
        dynamic_ms = (time.perf_counter() - td) * 1000
        tu = time.perf_counter()
        for b in self.game.blood:
            sx, sy = self.world_to_screen(b.x, b.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(
                    self.screen,
                    COLORS["blood_dark"],
                    (sx, sy),
                    max(2, int(b.size * self.tile_px * 0.45)),
                )
        for puff in self.game.dust:
            sx, sy = self.world_to_screen(puff.x, puff.y)
            if mr.collidepoint((sx, sy)):
                alpha = int(120 * clamp(puff.life / max(0.01, puff.total), 0, 1))
                rad = max(2, int(puff.size * self.tile_px))
                self.screen.blit(
                    self.dust_surface(rad, alpha), (sx - rad - 1, sy - rad - 1)
                )
        for tr in self.game.tracers:
            a = self.world_to_screen(*tr.a)
            b = self.world_to_screen(*tr.b)
            if mr.clipline(a, b):
                pygame.draw.line(self.screen, (234, 215, 145), a, b, 1)
        for imp in self.game.impacts:
            sx, sy = self.world_to_screen(imp.x, imp.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(self.screen, COLORS["impact"], (sx, sy), 2)
        visible_units = 0
        for u in self.game.units:
            if u.x < x0 - 2 or u.x > x1 + 2 or u.y < y0 - 2 or (u.y > y1 + 2):
                continue
            if (
                u.faction == "enemy"
                and u.alive
                and (not self.game.visible_to("player", u))
            ):
                continue
            if u.combat_effective and (u.overwatch or u.fire_lane):
                self.draw_arc(u)
            self.draw_unit(u)
            visible_units += 1
        for e in self.game.explosions:
            sx, sy = self.world_to_screen(e.x, e.y)
            if mr.collidepoint((sx, sy)):
                pygame.draw.circle(
                    self.screen,
                    COLORS["danger"] if e.kind == "HE" else COLORS["smoke"],
                    (sx, sy),
                    int(e.radius * self.tile_px),
                    1,
                )
                self.text(f"{e.timer:.1f}", (sx - 10, sy - 8), 12, "white")
        units_ms = (time.perf_counter() - tu) * 1000
        self.draw_tactical_previews()
        self.draw_planned_orders()
        if keys[pygame.K_LALT]:
            self.draw_directional_cover(self.map_cell_from_mouse(self.mouse))
        self.draw_selection_box()
        if self.game.victory or self.game.defeat:
            self.draw_after_action()
        if self.state in ("game", "deployment"):
            self.draw_objectives()
            self.draw_contact_intel()
            self.draw_assault_plan()
            self.draw_notifications()
        self._render_perf.update(
            {
                "map_ms": (time.perf_counter() - t0) * 1000,
                "terrain_ms": terrain_ms,
                "dynamic_ms": dynamic_ms,
                "units_ms": units_ms,
                "visible_units": visible_units,
                "dynamic_tiles": dynamic_count,
            }
        )
        self.draw_profiler_panel()

    def _perf_issue_context2(self, cell, append=False):
        if self.command_mode == "fallback":
            us = self.selected_units()
            if us and cell and self.game.in_bounds(*cell):
                for u in us:
                    u.fallback_point = cell
                self.message = f"Fallback/rally point set: {cell}"
                self.command_mode = "normal"
            return
        self._kz_issue_context(cell, append=append)

    def _perf_draw_bottom(self):
        y0 = MAP_Y + MAP_VIEW_H_PX + 2
        pygame.draw.rect(self.screen, COLORS["panel"], (0, y0, WINDOW_W, WINDOW_H - y0))
        for key, r in self.squad_rects().items():
            active = (
                key == "ALL"
                and len(self.selected)
                == len([u for u in self.game.living("player") if u.combat_effective])
                or (
                    key != "ALL"
                    and self.selected
                    and all(
                        (
                            getattr(self.game.get_unit(i), "squad_id", -1) == key
                            for i in self.selected
                            if self.game.get_unit(i)
                        )
                    )
                )
            )
            pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=3)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if active else COLORS["muted"],
                r,
                1,
                border_radius=3,
            )
            lab = "ALL" if key == "ALL" else f"SQUAD {chr(64 + int(key))}"
            ss = self.cached_text_surface(lab, 11, "white")
            self.screen.blit(
                ss, (r.centerx - ss.get_width() // 2, r.centery - ss.get_height() // 2)
            )
        for u, r in self.unit_card_rects():
            sel = u.uid in self.selected
            pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=2)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if sel else COLORS["muted"],
                r,
                2 if sel else 1,
                border_radius=2,
            )
            abbr = {
                "Rifleman": "RF",
                "Machine Gunner": "MG",
                "Sniper": "SN",
                "Medic": "MED",
                "Engineer": "ENG",
                "Recon": "REC",
                "Grenadier": "GRN",
                "Assault": "AS",
                "Automatic Rifleman": "AR",
                "Marksman": "DMR",
                "HMG Crew": "HMG",
                "Mortar Team": "MTR",
            }.get(u.role, "INF")
            self.text(abbr, (r.x + 4, r.y + 3), 10, "white")
            self.text(
                f"{u.hp:.0f}",
                (r.x + 4, r.y + 18),
                9,
                "good" if u.hp > u.max_hp * 0.5 else "danger",
            )
            pygame.draw.rect(self.screen, (30, 30, 28), (r.x + 30, r.y + 20, 30, 3))
            pygame.draw.rect(
                self.screen,
                COLORS["contact"],
                (r.x + 30, r.y + 20, int(30 * u.suppression / 100), 3),
            )
        us = self.selected_units()
        if us:
            for name, r in self.command_bar_rects().items():
                active = (
                    name == "ASSAULT"
                    and self.command_mode == "assault"
                    or (name == "FALLBACK" and self.command_mode == "fallback")
                    or (
                        name == "HOLD"
                        and all((getattr(u, "hold_position", False) for u in us))
                    )
                )
                pygame.draw.rect(self.screen, COLORS["panel2"], r, border_radius=3)
                pygame.draw.rect(
                    self.screen,
                    COLORS["select"] if active else COLORS["muted"],
                    r,
                    2 if active else 1,
                    border_radius=3,
                )
                label = name
                if name == "FORMATION":
                    label = self.formation.upper()
                elif name == "DISCIPLINE":
                    label = us[0].fire_discipline.upper()
                elif name == "PRIORITY":
                    label = us[0].target_priority.upper()
                elif name == "AUTO":
                    label = (
                        "AUTO ON"
                        if all(
                            (
                                u.auto_reload
                                and u.auto_cover
                                and u.auto_smoke
                                and u.auto_medic
                                for u in us
                            )
                        )
                        else "AUTO OFF"
                    )
                ss = self.cached_text_surface(
                    label,
                    9,
                    "select" if active or name in ("ASSAULT", "FORMATION") else "white",
                )
                self.screen.blit(
                    ss,
                    (r.centerx - ss.get_width() // 2, r.centery - ss.get_height() // 2),
                )

    def draw_sidebar(self):
        x = SIDEBAR_X
        w = WINDOW_W - x - 12
        pygame.draw.rect(self.screen, COLORS["panel"], (x, MAP_Y, w, MAP_VIEW_H_PX))
        obj = self.game.current_objective
        y = MAP_Y + 9
        if obj:
            pygame.draw.rect(
                self.screen, COLORS["panel2"], (x + 8, y, w - 16, 76), border_radius=3
            )
            pygame.draw.rect(
                self.screen,
                COLORS["objective"],
                (x + 8, y, w - 16, 76),
                1,
                border_radius=3,
            )
            self.text(
                f"OBJECTIVE {self.game.objective_index + 1}/{len(self.game.objectives)}",
                (x + 16, y + 7),
                10,
                "objective",
            )
            self.text(obj["title"][:34], (x + 16, y + 24), 11, "white")
            pygame.draw.rect(self.screen, (25, 27, 24), (x + 16, y + 48, w - 32, 7))
            pygame.draw.rect(
                self.screen,
                COLORS["objective"],
                (x + 16, y + 48, int((w - 32) * clamp(obj["progress"], 0, 1)), 7),
            )
            self.text(f"{obj['progress'] * 100:.0f}%", (x + w - 45, y + 59), 9, "muted")
            y += 88
        self.text("SELECTED", (x + 14, y), 15, "white")
        y += 22
        us = self.selected_units()
        if not us:
            self.text("No units selected", (x + 14, y), 12, "muted")
            y += 24
        else:
            firing = sum((1 for u in us if u.order == "fire"))
            reloading = sum((1 for u in us if u.reload_timer > 0))
            pinned = sum((1 for u in us if getattr(u, "morale_state", "") == "PINNED"))
            wounded = sum((1 for u in us if u.casualty == "wounded"))
            self.text(
                f"{len(us)} troops | fire {firing} rld {reloading} pin {pinned} wnd {wounded}",
                (x + 14, y),
                10,
                "status",
            )
            y += 18
            for u in us[:3]:
                name = getattr(
                    u, "display_name", f"SQ{getattr(u, 'squad_id', 0)} #{u.uid}"
                )
                state = getattr(u, "morale_state", "STEADY")
                self.text(f"{name} — {u.role}"[:39], (x + 14, y), 11, "select")
                y += 15
                self.text(
                    f"HP {u.hp:.0f} MOR {u.morale:.0f} SUP {u.suppression:.0f} COH {u.cohesion:.0f}",
                    (x + 14, y),
                    10,
                    "text",
                )
                y += 14
                self.text(
                    f"{state} | {u.weapon_name} {u.ammo} | {u.order}",
                    (x + 14, y),
                    9,
                    "contact"
                    if state in ("PINNED", "BREAKING", "ROUTING")
                    else "muted",
                )
                y += 18
            if len(us) == 1:
                u = us[0]
                self.text(
                    f"MORALE — {getattr(u, 'morale_state', 'STEADY')}",
                    (x + 14, y),
                    10,
                    "white",
                )
                y += 14
                factors = sorted(
                    self.game.morale_breakdown(u), key=lambda z: abs(z[1]), reverse=True
                )[:3]
                for name, val in factors:
                    self.text(
                        f"{name[:24]:24s} {val:+.0f}",
                        (x + 14, y),
                        9,
                        "danger" if val > 0 else "good",
                    )
                    y += 13
                if u.low_morale_since is not None:
                    self.text(
                        f"under break pressure {self.game.time - u.low_morale_since:.1f}s",
                        (x + 14, y),
                        9,
                        "muted",
                    )
                    y += 14
                if getattr(u, "fallback_point", None):
                    self.text(
                        f"fallback {u.fallback_point}"
                        + (" | HOLD" if u.hold_position else ""),
                        (x + 14, y),
                        9,
                        "select",
                    )
                    y += 14
        report_y = max(y + 5, MAP_Y + 350)
        self.text("FIELD REPORT", (x + 14, report_y), 13, "white")
        yy = report_y + 20
        for line in self.game.log[-5:]:
            self.text(line[:43], (x + 14, yy), 10, "muted")
            yy += 15
        sec_y = min(MAP_Y + MAP_VIEW_H_PX - 72, yy + 4)
        self.text("LINE STABILITY", (x + 14, sec_y), 9, "muted")
        sec_y += 13
        for sec in ("NORTH", "CENTRE", "SOUTH"):
            st = self.game.sector_stability.get(sec, 100)
            col = "danger" if st > 65 else "contact" if st > 30 else "good"
            self.text(
                f"{sec:6s} {st:3.0f}%"
                + (" COLLAPSED" if sec in self.game.collapsed_sectors else ""),
                (x + 14, sec_y),
                8,
                col,
            )
            sec_y += 12
        if pygame.key.get_pressed()[pygame.K_LALT]:
            cell = self.map_cell_from_mouse(self.mouse)
            if cell:
                cx, cy = cell
                c = self.game.grid[cy][cx]
                td = TERRAIN[c.terrain]
                base = MAP_Y + MAP_VIEW_H_PX - 96
                pygame.draw.rect(
                    self.screen,
                    COLORS["panel2"],
                    (x + 8, base - 5, w - 16, 88),
                    border_radius=3,
                )
                self.text("TILE INTEL [LALT]", (x + 14, base), 11, "select")
                self.text(
                    f"{cell} {c.terrain.upper()} cover {td['cover']} conceal {td['conceal']}",
                    (x + 14, base + 17),
                    10,
                    "white",
                )
                self.text(
                    f"move x{td['move']:.2f} smoke {c.smoke:.1f} suppression {c.ground_suppression:.0f}",
                    (x + 14, base + 34),
                    10,
                    "muted",
                )
                self.text(
                    f"known threat {self.game.tile_threat('player', cx, cy):.1f}",
                    (x + 14, base + 51),
                    10,
                    "contact",
                )
                self.text(
                    "edges: green strong / yellow partial / red open",
                    (x + 14, base + 68),
                    9,
                    "muted",
                )

    def _perf_draw3(self):
        t0 = time.perf_counter()
        if hasattr(self, "game"):
            self.game.profile_enabled = bool(self.show_perf)
            self.selected = [
                uid
                for uid in self.selected
                if self.game.get_unit(uid) and self.game.get_unit(uid).combat_effective
            ]
        self._vs_draw2()
        frame = (time.perf_counter() - t0) * 1000
        self._render_perf["frame_ms"] = frame
        self._render_perf["ui_ms"] = max(0, frame - self._render_perf.get("map_ms", 0))

    def _maintenance_draw_unit(self, unit):
        self._perf_draw_unit2(unit)
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
            (
                badge_center[0] - badge.get_width() // 2,
                badge_center[1] - badge.get_height() // 2,
            ),
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

    def _maintenance_draw_command_bar(self):
        self._perf_draw_bottom()
        active_units = [
            unit for unit in self.game.living("player") if unit.combat_effective
        ]
        active_ids = {unit.uid for unit in active_units}
        selected_ids = set(self.selected) & active_ids
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
                    (
                        rect.centerx - label.get_width() // 2,
                        rect.centery - label.get_height() // 2,
                    ),
                )
                continue
            members = [
                unit
                for unit in active_units
                if getattr(unit, "squad_id", 0) == squad_id
            ]
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
            pygame.draw.rect(
                self.screen, color, (rect.x + 5, rect.y + 5, 17, 18), border_radius=3
            )
            hotkey = self.cached_text_surface(str(squad_id), 10, "black")
            self.screen.blit(
                hotkey,
                (
                    rect.x + 13 - hotkey.get_width() // 2,
                    rect.y + 14 - hotkey.get_height() // 2,
                ),
            )
            letter = chr(64 + min(26, int(squad_id)))
            title = self.cached_text_surface(f"SQUAD {letter}", 8, "white")
            kind = self.cached_text_surface(
                squad_tactical_label(self.game, squad_id), 7, "muted"
            )
            self.screen.blit(title, (rect.x + 27, rect.y + 4))
            self.screen.blit(kind, (rect.x + 27, rect.y + 15))
        for unit, rect in self.unit_card_rects():
            squad_id = max(1, int(getattr(unit, "squad_id", 1)))
            color = squad_visual_color(squad_id)
            selected = unit.uid in selected_ids
            pygame.draw.rect(
                self.screen, color, (rect.x + 2, rect.y + 2, rect.w - 4, 3)
            )
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
                (
                    badge_rect.centerx - number.get_width() // 2,
                    badge_rect.centery - number.get_height() // 2,
                ),
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
                pygame.draw.rect(
                    self.screen, COLORS["select"], rect, 2, border_radius=3
                )

    def _maintenance_issue_context(self, cell, append=False):
        if self.command_mode == "overwatch":
            units = self.selected_units()
            if units and cell and self.game.in_bounds(*cell):
                for unit in units:
                    self.game.set_overwatch(unit, angle_to(unit, cell), 100)
                self.message = "Overwatch arc established"
            self.command_mode = "normal"
            return
        return self._perf_issue_context2(cell, append=append)

    def _maintenance_draw_command_guide(self, standalone=False):
        if standalone:
            self.draw_menu_background()
        width, height = (1160, 650)
        x = (WINDOW_W - width) // 2
        y = 40
        if standalone:
            pygame.draw.rect(
                self.screen, COLORS["panel"], (x, y, width, height), border_radius=4
            )
        else:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((20, 23, 20, 247))
            self.screen.blit(overlay, (x, y))
        pygame.draw.rect(
            self.screen, COLORS["select"], (x, y, width, height), 2, border_radius=4
        )
        self.text("FIELD MANUAL · COMMAND BAR", (x + 24, y + 16), 23, "white")
        self.text(
            "Select troops first. TARGET commands wait for a right-click on the battlefield.",
            (x + 24, y + 48),
            11,
            "muted",
        )
        close_hint = (
            "Use BACK to return to the menu."
            if standalone
            else "Press F1 to close this guide."
        )
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
                pygame.draw.rect(
                    self.screen, accent, (row.x, row.y, 4, row.h), border_radius=2
                )
                self.text(button, (row.x + 13, row.y + 7), 10, "white")
                self.text(
                    gesture,
                    (row.x + 13, row.y + 25),
                    8,
                    "contact" if column_index == 0 else "muted",
                )
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

    def draw_help(self):
        self._maintenance_draw_command_guide(standalone=False)

    def draw_help_menu(self):
        self._maintenance_draw_command_guide(standalone=True)

    def text(self, value, pos, size=14, color="text"):
        text_value = str(value)
        help_replacements = {
            "Ctrl+1..9 save groups; 1..9 recall them.": "1..9 select squads; Ctrl+1..9 save groups; Shift+1..9 recall groups.",
            "Alt+1..5 assign persistent Squad A–E | click squad tabs to select | Ctrl+1..9 control groups": "1..9 select Squad A–I | Alt+1..5 reassign | Ctrl+1..9 save groups | Shift+1..9 recall",
        }
        if text_value in help_replacements:
            value = help_replacements[text_value]
            text_value = value
        stripped = text_value.lstrip()
        if (
            size == 8
            and stripped.startswith(("NORTH", "CENTRE", "SOUTH"))
            and ("%" in stripped)
        ):
            try:
                stability = float(stripped.split("%", 1)[0].split()[-1])
            except (ValueError, IndexError):
                pass
            else:
                color = sector_stability_color(stability)
        return self._perf_text(value, pos, size, color)

    def _qol_draw_command_bar(self):
        self._maintenance_draw_command_bar()
        units = self.selected_units()
        rects = self.command_bar_rects()
        for button, rect in rects.items():
            enabled, _reason = command_button_status(self, button, units)
            if enabled:
                continue
            pygame.draw.rect(self.screen, (33, 36, 32), rect, border_radius=3)
            pygame.draw.rect(self.screen, (73, 78, 69), rect, 1, border_radius=3)
            label = self.cached_text_surface(
                _qol_command_label(self, button, units), 9, "muted"
            )
            self.screen.blit(
                label,
                (
                    rect.centerx - label.get_width() // 2,
                    rect.centery - label.get_height() // 2,
                ),
            )
        hovered_command = next(
            (
                (button, rect)
                for button, rect in rects.items()
                if rect.collidepoint(self.mouse)
            ),
            None,
        )
        hovered_card = next(
            (
                (unit, rect)
                for unit, rect in self.unit_card_rects()
                if rect.collidepoint(self.mouse)
            ),
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
            mode = (
                "TARGET — click, then right-click the battlefield"
                if button in QOL_TARGET_MODES
                else "INSTANT / SETTING"
            )
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

    def _qol_issue_context(self, cell, append=False):
        previous_mode = self.command_mode
        result = self._maintenance_issue_context(cell, append=append)
        if previous_mode in QOL_TARGET_MODES.values() and self.command_mode == "normal":
            label = next(
                (
                    button
                    for button, mode in QOL_TARGET_MODES.items()
                    if mode == previous_mode
                ),
                previous_mode.upper(),
            )
            _qol_notify(self, f"{label} order confirmed", duration=1.5)
        elif previous_mode == "normal" and self.selected_units():
            _qol_notify(self, "Order confirmed", duration=1.2)
        return result

    def _qol_draw_map(self):
        self._perf_draw_map3()
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
        pygame.draw.line(
            self.screen,
            color,
            (center[0] - radius - 4, center[1]),
            (center[0] + radius + 4, center[1]),
            1,
        )
        pygame.draw.line(
            self.screen,
            color,
            (center[0], center[1] - radius - 4),
            (center[0], center[1] + radius + 4),
            1,
        )
        label = self.cached_text_surface(
            f"{self.command_mode.upper()} · RMB", 9, color_key
        )
        label_x = int(
            clamp(
                center[0] + 12, MAP_X + 4, MAP_X + MAP_VIEW_W_PX - label.get_width() - 4
            )
        )
        self.screen.blit(label, (label_x, center[1] - 18))

    def draw_planned_orders(self):
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
                    self._qol_marker(current, str(order_number), color, shape="diamond")
                    self.text("MOVE", (current[0] + 10, current[1] - 7), 8, color)
                last = current
                order_number += 1
            for queue_index, (kind, data) in enumerate(
                unit.command_queue[:6], order_number
            ):
                if kind == "move":
                    current = self.world_to_screen(*data)
                    if map_rect.clipline(last, current):
                        pygame.draw.line(
                            self.screen, COLORS["select"], last, current, 1
                        )
                    if map_rect.collidepoint(current):
                        self._qol_marker(current, str(queue_index), COLORS["select"])
                        self.text(
                            "QUEUED", (current[0] + 10, current[1] - 7), 8, "select"
                        )
                    last = current
                elif kind == "fire":
                    target_uid, _mode = data
                    target = self.game.get_unit(target_uid)
                    if target is None:
                        continue
                    current = self.world_to_screen(target.x, target.y)
                    if map_rect.collidepoint(current):
                        pygame.draw.circle(
                            self.screen, COLORS["danger"], current, 10, 1
                        )
                        pygame.draw.line(
                            self.screen,
                            COLORS["danger"],
                            (current[0] - 12, current[1]),
                            (current[0] + 12, current[1]),
                            1,
                        )
                        pygame.draw.line(
                            self.screen,
                            COLORS["danger"],
                            (current[0], current[1] - 12),
                            (current[0], current[1] + 12),
                            1,
                        )
                        self.text(
                            f"F{queue_index}",
                            (current[0] + 11, current[1] - 8),
                            8,
                            "danger",
                        )

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
                self.button(
                    rect,
                    f"HELP ON BATTLE START: {('ON' if self.menu_show_help else 'OFF')}",
                    self.mouse,
                    accent=self.menu_show_help,
                )
            elif name == "audio":
                self.button(
                    rect,
                    f"COMBAT AUDIO: {('ON' if self.audio_enabled else 'OFF')}",
                    self.mouse,
                    accent=self.audio_enabled,
                )
            elif name == "fps":
                self.button(
                    rect,
                    f"FPS COUNTER: {('ON' if self.show_fps else 'OFF')}",
                    self.mouse,
                    accent=self.show_fps,
                )
            elif name == "perf":
                self.button(
                    rect,
                    f"PERFORMANCE PROFILER: {('ON' if self.show_perf else 'OFF')}",
                    self.mouse,
                    accent=self.show_perf,
                )
            elif name == "fpscap":
                label = (
                    "RENDER FPS: UNCAPPED"
                    if self.fps_cap == 0
                    else f"RENDER FPS: {self.fps_cap}"
                )
                self.button(rect, label, self.mouse, accent=self.fps_cap == 0)
            elif name == "fullscreen":
                mode = {
                    "windowed": "WINDOWED",
                    "borderless": "BORDERLESS FULLSCREEN",
                    "exclusive": "EXCLUSIVE FULLSCREEN",
                }.get(self.display_mode, self.display_mode.upper())
                self.button(
                    rect,
                    f"DISPLAY MODE: {mode}",
                    self.mouse,
                    accent=self.display_mode != "windowed",
                )
            elif name == "uiscale":
                self.button(
                    rect,
                    f"UI SCALE: {self.ui_scale * 100:.0f}%",
                    self.mouse,
                    accent=self.ui_scale > 1.0,
                )
            elif name == "largetext":
                self.button(
                    rect,
                    f"LARGER TEXT: {('ON' if self.large_text else 'OFF')}",
                    self.mouse,
                    accent=self.large_text,
                )
            elif name == "back":
                self.button(rect, "BACK", self.mouse)
        self.text(
            "Settings save automatically.", (WINDOW_W // 2 - 105, 648), 10, "muted"
        )

    def _feedback_draw_unit(self, unit):
        self._maintenance_draw_unit(unit)
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
        self.screen.blit(
            surface,
            (
                rect.centerx - surface.get_width() // 2,
                rect.centery - surface.get_height() // 2,
            ),
        )

    def draw_edge_arrow(self, world_screen_pos, color, label=None):
        indicator = offscreen_indicator_point(self.map_view_rect(), world_screen_pos)
        if indicator is None:
            return False
        (center_x, center_y), angle = indicator
        direction_x, direction_y = (math.cos(angle), math.sin(angle))
        perpendicular_x, perpendicular_y = (-direction_y, direction_x)
        tip = (round(center_x + direction_x * 8), round(center_y + direction_y * 8))
        back_x, back_y = (center_x - direction_x * 6, center_y - direction_y * 6)
        left = (
            round(back_x + perpendicular_x * 5),
            round(back_y + perpendicular_y * 5),
        )
        right = (
            round(back_x - perpendicular_x * 5),
            round(back_y - perpendicular_y * 5),
        )
        pygame.draw.polygon(self.screen, color, (tip, left, right))
        pygame.draw.polygon(self.screen, COLORS["black"], (tip, left, right), 1)
        if label:
            surface = self.cached_text_surface(label, 8, "white")
            label_x = round(center_x - direction_x * 17 - surface.get_width() / 2)
            label_y = round(center_y - direction_y * 17 - surface.get_height() / 2)
            self.screen.blit(surface, (label_x, label_y))
        return True

    def draw_battlefield_readability(self):
        map_rect = self.map_view_rect()
        active_badges = []
        for unit in self.selected_units()[:16]:
            status = battlefield_status_badge(unit, self.game.time)
            if status and status[0] not in active_badges:
                active_badges.append(status[0])
            screen_pos = self.world_to_screen(unit.x, unit.y)
            if not map_rect.collidepoint(screen_pos):
                color = squad_visual_color(getattr(unit, "squad_id", 1))
                self.draw_edge_arrow(
                    screen_pos, color, str(getattr(unit, "squad_id", 1))
                )
        for event in getattr(self.game, "battle_events", [])[-20:]:
            style = battlefield_event_style(event)
            position = event.get("pos")
            age = self.game.time - event.get("time", -99.0)
            if style is None or position is None or (not 0 <= age <= 4.0):
                continue
            label, color_key = style
            color = COLORS[color_key]
            screen_pos = self.world_to_screen(*position)
            if not map_rect.collidepoint(screen_pos):
                self.draw_edge_arrow(screen_pos, color, "!")
                continue
            radius = 12 + int(age * 3)
            pygame.draw.circle(
                self.screen, color, screen_pos, radius, 2 if age < 1.5 else 1
            )
            text_surface = self.cached_text_surface(label, 8, color_key)
            text_x = int(
                clamp(
                    screen_pos[0] + 12,
                    map_rect.left + 4,
                    map_rect.right - text_surface.get_width() - 4,
                )
            )
            text_y = int(
                clamp(screen_pos[1] - 18, map_rect.top + 4, map_rect.bottom - 14)
            )
            self.screen.blit(text_surface, (text_x, text_y))
        if active_badges:
            legend = "STATUS  " + " · ".join(active_badges[:5])
            surface = self.cached_text_surface(legend, 8, "white")
            rect = pygame.Rect(
                map_rect.left + 7, map_rect.bottom - 22, surface.get_width() + 14, 16
            )
            pygame.draw.rect(self.screen, (25, 28, 24), rect, border_radius=3)
            pygame.draw.rect(self.screen, COLORS["muted"], rect, 1, border_radius=3)
            self.screen.blit(surface, (rect.x + 7, rect.y + 3))

    def _feedback_draw_map(self):
        self._qol_draw_map()
        if self.state in ("deployment", "game"):
            self.draw_battlefield_readability()

    def draw_operation_setup(self):
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
        title_y = {
            "mission": 121,
            "variant": 233,
            "weather": 341,
            "strength": 449,
            "duration": 557,
        }
        for heading, group, selected in rows:
            self.text(
                heading,
                (min((rect.x for rect in rects[group].values())), title_y[group]),
                13,
                "select",
            )
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

    def draw_setup(self):
        self._kz_draw_setup()
        rect = self.operation_setup_button_rect()
        mission = "DEFENSE" if self.setup_mission == "defense" else "ASSAULT"
        self.button(
            rect,
            f"ADVANCED · {mission}",
            self.mouse,
            accent=self.setup_mission == "defense",
        )

    def draw_briefing(self):
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
        self.button(
            pygame.Rect(WINDOW_W // 2 - 150, 690, 300, 46),
            "BEGIN DEPLOYMENT",
            self.mouse,
            accent=True,
        )
        self.button(pygame.Rect(34, 690, 180, 42), "BACK", self.mouse)

    def draw_deployment(self):
        if self.game.deployment_zone_side != "east":
            return self._kz_draw_deployment()
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
        pygame.draw.line(
            self.screen, COLORS["select"], (x, MAP_Y), (x, MAP_Y + MAP_VIEW_H_PX), 2
        )

    def draw_build_preview(self, kind, rect):
        color = (
            COLORS["objective"]
            if "role" in ENGINEER_BUILD_TYPES[kind]
            else COLORS["blue"]
        )
        ink = COLORS["black"]
        cx, cy = (rect.right - 30, rect.centery - 3)
        if kind == "sandbags":
            for row, count in enumerate((3, 2)):
                for column in range(count):
                    sack = pygame.Rect(
                        cx - 14 + column * 10 + row * 5, cy - 7 + row * 7, 9, 6
                    )
                    pygame.draw.ellipse(self.screen, color, sack)
                    pygame.draw.ellipse(self.screen, ink, sack, 1)
        elif kind == "wire":
            pygame.draw.line(
                self.screen, color, (cx - 15, cy - 8), (cx + 15, cy + 8), 2
            )
            pygame.draw.line(
                self.screen, color, (cx + 15, cy - 8), (cx - 15, cy + 8), 2
            )
            for offset in (-10, 0, 10):
                pygame.draw.circle(self.screen, color, (cx + offset, cy), 3, 1)
        elif kind == "trench":
            pygame.draw.lines(
                self.screen,
                color,
                False,
                (
                    (cx - 16, cy - 9),
                    (cx - 7, cy + 7),
                    (cx + 2, cy - 7),
                    (cx + 16, cy + 8),
                ),
                3,
            )
            pygame.draw.lines(
                self.screen,
                ink,
                False,
                (
                    (cx - 14, cy - 9),
                    (cx - 5, cy + 5),
                    (cx + 3, cy - 5),
                    (cx + 15, cy + 7),
                ),
                1,
            )
        elif kind == "mg_nest":
            pygame.draw.arc(
                self.screen,
                color,
                pygame.Rect(cx - 16, cy - 11, 32, 22),
                math.pi,
                math.tau,
                4,
            )
            pygame.draw.circle(self.screen, color, (cx, cy), 4)
            pygame.draw.line(self.screen, color, (cx, cy), (cx + 17, cy - 4), 3)
        elif kind == "field_gun":
            pygame.draw.circle(self.screen, color, (cx - 8, cy + 6), 7, 2)
            pygame.draw.circle(self.screen, color, (cx + 8, cy + 6), 7, 2)
            pygame.draw.rect(self.screen, color, pygame.Rect(cx - 8, cy - 6, 16, 11), 2)
            pygame.draw.line(self.screen, color, (cx, cy - 2), (cx + 18, cy - 9), 3)
        elif kind == "artillery":
            pygame.draw.circle(self.screen, color, (cx - 10, cy + 5), 7, 2)
            pygame.draw.circle(self.screen, color, (cx + 10, cy + 5), 7, 2)
            pygame.draw.line(self.screen, color, (cx, cy), (cx + 16, cy - 12), 5)
            pygame.draw.line(
                self.screen, color, (cx - 2, cy + 3), (cx - 14, cy + 13), 3
            )
            pygame.draw.line(
                self.screen, color, (cx + 2, cy + 3), (cx + 14, cy + 13), 3
            )

    def draw_build_menu(self):
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
            pygame.draw.rect(
                self.screen,
                COLORS["objective"] if "role" in definition else COLORS["blue"],
                rect,
                1,
                border_radius=4,
            )
            self.text(definition["label"], (rect.x + 12, rect.y + 11), 12, "white")
            self.text(definition["description"], (rect.x + 12, rect.y + 38), 8, "muted")
            self.draw_build_preview(kind, rect)
        self.button(rects["cancel"], "CLOSE", self.mouse)
        self.text(
            "FREE BUILD PREVIEW · static weapon cap 6 per side · supply/logistics costs follow next update",
            (panel.x + 27, panel.bottom - 29),
            9,
            "contact",
        )

    def draw_command_bar(self):
        self._qol_draw_command_bar()
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
        self.screen.blit(
            surface,
            (
                rect.centerx - surface.get_width() // 2,
                rect.centery - surface.get_height() // 2,
            ),
        )
        mobile = [unit for unit in units if unit.role not in STATIC_WEAPON_ROLES]
        if mobile:
            doctrine = self.game.doctrine_for(mobile[0]).upper()
            self.text(
                f"DOCTRINE  {doctrine}  [SHIFT+D]", (rect.x, rect.y - 20), 9, "contact"
            )
        if self.build_menu_open:
            self.draw_build_menu()

    def draw_topbar(self):
        self._vs_draw_topbar2()
        if getattr(
            self.game, "mission_type", "assault"
        ) != "defense" or self.state not in ("game", "deployment"):
            return
        if self.state == "deployment":
            label = "DEFENSE · DEPLOY EAST"
            color = "select"
        else:
            remaining = max(
                0,
                int(
                    math.ceil(self.game.defense_time_limit - self.game.defense_elapsed)
                ),
            )
            wave = max(getattr(self.game, "defense_wave_announced", {1}))
            capture = getattr(self.game, "defense_capture_progress", 0.0)
            command = "COMMAND CONTESTED" if capture > 0 else "COMMAND SECURE"
            label = f"HOLD {remaining // 60:02d}:{remaining % 60:02d}  ·  WAVE {wave}/3  ·  {command}"
            color = "danger" if capture > 0 else "objective"
        surface = self.cached_text_surface(label, 10, color)
        panel = pygame.Rect(
            WINDOW_W - surface.get_width() - 32, 28, surface.get_width() + 20, 22
        )
        pygame.draw.rect(self.screen, COLORS["panel2"], panel, border_radius=3)
        pygame.draw.rect(self.screen, COLORS[color], panel, 1, border_radius=3)
        self.screen.blit(surface, (panel.x + 10, panel.y + 5))

    def _operation_draw_map(self):
        self._feedback_draw_map()
        for pos, reservation in self.game.construction_reservations.items():
            engineer_uid, kind, faction = reservation
            if faction != "player":
                continue
            rect = self.cell_rect(*pos)
            if not rect.colliderect(self.map_view_rect()):
                continue
            pygame.draw.rect(self.screen, COLORS["blue"], rect, 2)
            pygame.draw.line(
                self.screen, COLORS["blue"], rect.topleft, rect.bottomright, 1
            )
            pygame.draw.line(
                self.screen, COLORS["blue"], rect.topright, rect.bottomleft, 1
            )
            label = self.cached_text_surface(
                f"BUILD {ENGINEER_BUILD_TYPES[kind]['label']}", 7, "white"
            )
            self.screen.blit(
                label, (rect.centerx - label.get_width() // 2, rect.y - 11)
            )
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

    def _operation_draw_unit(self, unit):
        if unit.role not in STATIC_WEAPON_ROLES:
            self._feedback_draw_unit(unit)
            return
        center_x, center_y = self.world_to_screen(unit.x, unit.y)
        if not self.map_view_rect().inflate(35, 35).collidepoint((center_x, center_y)):
            return
        color = (
            COLORS["nato_friend"]
            if unit.faction == "player"
            else COLORS["nato_hostile"]
        )
        ink = COLORS["black"]
        scale = max(0.72, self.tile_px / 20.0)
        radius = max(11, round(13 * scale))
        angle = math.radians(unit.facing)
        forward = (math.cos(angle), math.sin(angle))
        normal = (-forward[1], forward[0])

        def point(ahead=0.0, side=0.0):
            return (
                round(center_x + forward[0] * ahead * scale + normal[0] * side * scale),
                round(center_y + forward[1] * ahead * scale + normal[1] * side * scale),
            )

        if not unit.alive:
            pygame.draw.circle(
                self.screen, COLORS["muted"], (center_x, center_y), radius, 2
            )
            pygame.draw.line(
                self.screen,
                COLORS["muted"],
                (center_x - radius, center_y - radius),
                (center_x + radius, center_y + radius),
                3,
            )
            pygame.draw.line(
                self.screen,
                COLORS["muted"],
                (center_x + radius, center_y - radius),
                (center_x - radius, center_y + radius),
                3,
            )
            return
        if unit.role == "MG Emplacement":
            bunker = pygame.Rect(
                center_x - radius, center_y - radius + 3, radius * 2, radius * 2 - 3
            )
            pygame.draw.arc(
                self.screen, color, bunker, math.pi, math.tau, max(3, round(4 * scale))
            )
            for side in (-8, 0, 8):
                pygame.draw.circle(
                    self.screen, color, point(-4, side), max(3, round(3 * scale))
                )
                pygame.draw.circle(
                    self.screen, ink, point(-4, side), max(3, round(3 * scale)), 1
                )
            pygame.draw.circle(
                self.screen, color, (center_x, center_y), max(4, round(5 * scale))
            )
            pygame.draw.circle(
                self.screen, ink, (center_x, center_y), max(4, round(5 * scale)), 1
            )
            pygame.draw.line(
                self.screen, ink, point(1), point(16), max(3, round(3 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(2), point(17), max(2, round(2 * scale))
            )
            pygame.draw.line(self.screen, color, point(-1), point(-9, -7), 2)
            pygame.draw.line(self.screen, color, point(-1), point(-9, 7), 2)
        elif unit.role == "Field Gun":
            wheel_radius = max(5, round(6 * scale))
            for side in (-8, 8):
                wheel = point(-2, side)
                pygame.draw.circle(
                    self.screen, color, wheel, wheel_radius, max(2, round(2 * scale))
                )
                pygame.draw.circle(self.screen, ink, wheel, max(2, round(2 * scale)))
            shield = [
                point(2, -8),
                point(5, -6),
                point(5, 6),
                point(2, 8),
                point(-3, 5),
                point(-3, -5),
            ]
            pygame.draw.polygon(self.screen, color, shield)
            pygame.draw.polygon(self.screen, ink, shield, 2)
            pygame.draw.line(
                self.screen, ink, point(2), point(20), max(4, round(4 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(4), point(21), max(2, round(2 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(-2), point(-14), max(3, round(3 * scale))
            )
        else:
            wheel_radius = max(6, round(7 * scale))
            for side in (-9, 9):
                wheel = point(-1, side)
                pygame.draw.circle(
                    self.screen, color, wheel, wheel_radius, max(3, round(3 * scale))
                )
                pygame.draw.circle(self.screen, ink, wheel, max(2, round(2 * scale)))
            breech = pygame.Rect(
                0, 0, max(8, round(10 * scale)), max(7, round(8 * scale))
            )
            breech.center = point(1)
            pygame.draw.rect(self.screen, color, breech, border_radius=2)
            pygame.draw.rect(self.screen, ink, breech, 2, border_radius=2)
            elevated_tip = point(19, -6)
            pygame.draw.line(
                self.screen, ink, point(3), elevated_tip, max(6, round(6 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(4), elevated_tip, max(3, round(3 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(-3), point(-16, -9), max(3, round(3 * scale))
            )
            pygame.draw.line(
                self.screen, color, point(-3), point(-16, 9), max(3, round(3 * scale))
            )
        if unit.faction == "player":
            pygame.draw.rect(
                self.screen,
                color,
                pygame.Rect(
                    center_x - radius - 2,
                    center_y - radius - 2,
                    radius * 2 + 4,
                    radius * 2 + 4,
                ),
                1,
            )
        else:
            pygame.draw.polygon(
                self.screen,
                color,
                (
                    (center_x, center_y - radius - 3),
                    (center_x + radius + 3, center_y),
                    (center_x, center_y + radius + 3),
                    (center_x - radius - 3, center_y),
                ),
                1,
            )
        if unit.uid in self.selected:
            pygame.draw.circle(
                self.screen, COLORS["select"], (center_x, center_y), radius + 6, 2
            )
        visual = EMPLACEMENT_VISUALS[unit.role]
        surface = self.cached_text_surface(visual["label"], 8, "white")
        self.screen.blit(
            surface, (center_x - surface.get_width() // 2, center_y - radius - 14)
        )
        bar_width = radius * 2
        bar_y = center_y + radius + 7
        pygame.draw.rect(
            self.screen, COLORS["black"], (center_x - radius, bar_y, bar_width, 3)
        )
        pygame.draw.rect(
            self.screen,
            COLORS["good"],
            (
                center_x - radius,
                bar_y,
                round(bar_width * clamp(unit.hp / unit.max_hp, 0, 1)),
                3,
            ),
        )
        if unit.suppression > 15:
            pygame.draw.rect(
                self.screen,
                COLORS["contact"],
                (
                    center_x - radius,
                    bar_y + 4,
                    round(bar_width * unit.suppression / 100),
                    2,
                ),
            )

    def _operation_issue_context(self, cell, append=False):
        if not self.command_mode.startswith("build:"):
            return self._qol_issue_context(cell, append=append)
        kind = self.command_mode.split(":", 1)[1]
        preferred = [
            unit
            for unit in self.selected_units()
            if unit.role == "Engineer" and unit.combat_effective
        ]
        engineer, reason = self.game.queue_construction(
            "player", kind, cell, preferred_engineers=preferred
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

    def _operation_draw(self):
        if self.state == "operation_setup":
            self.screen.fill(COLORS["bg"])
            self.draw_operation_setup()
            self.present()
            return
        return self._perf_draw3()

    def draw_main_menu(self):
        self._base_draw_main_menu()
        self.button(
            self.multiplayer_menu_rect(), "MULTIPLAYER", self.mouse, accent=False
        )

    def draw_multiplayer_browser(self):
        self.draw_menu_background()
        rects = self.network_browser_rects()
        title = self.get_font(48).render("MULTIPLAYER", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 52))
        self.text("AUTHORITATIVE KILL ZONE SERVER", (190, 113), 13, "select")
        for field, label, value in (
            ("address", "SERVER ADDRESS", self.network_server_address),
            ("name", "PLAYER NAME", self.network_player_name),
        ):
            rect = rects[field]
            pygame.draw.rect(self.screen, COLORS["panel"], rect, border_radius=4)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if self.network_input == field else COLORS["muted"],
                rect,
                2 if self.network_input == field else 1,
                border_radius=4,
            )
            self.text(label, (rect.x, rect.y - 18), 10, "muted")
            self.text(
                value + ("_" if self.network_input == field else ""),
                (rect.x + 12, rect.y + 13),
                14,
                "white",
            )
        self.button(
            rects["connect"], "CONNECT", self.mouse, accent=self.network.connected
        )
        self.button(
            rects["refresh"], "REFRESH", self.mouse, enabled=self.network.connected
        )
        self.button(
            rects["create"], "CREATE BATTLE", self.mouse, accent=self.network.connected
        )
        self.text(
            self.network_status[:90],
            (190, 270),
            13,
            "good" if self.network.connected else "contact",
        )
        self.text(
            f"{self.network_online} PLAYER(S) ONLINE",
            (WINDOW_W - 410, 270),
            12,
            "muted",
        )
        self.text("AVAILABLE BATTLES", (190, 286), 14, "white")
        if not self.network_rooms:
            self.text(
                "No public battles found. Connect, refresh, or create one.",
                (210, 340),
                14,
                "muted",
            )
        for index, room in enumerate(self.network_rooms[:6]):
            rect = rects[f"room:{index}"]
            available = (
                room.get("status") == "lobby" and int(room.get("players", 0)) < 2
            )
            pygame.draw.rect(self.screen, COLORS["panel"], rect, border_radius=4)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if available else COLORS["muted"],
                rect,
                1,
                border_radius=4,
            )
            lock = "LOCKED" if room.get("locked") else "OPEN"
            self.text(
                str(room.get("name", "Battle"))[:38],
                (rect.x + 14, rect.y + 8),
                14,
                "white",
            )
            self.text(
                f"{room.get('players', 0)}/2 · {str(room.get('battlefield', 'field')).upper()} · {lock} · {str(room.get('status', 'lobby')).upper()}",
                (rect.x + 14, rect.y + 27),
                10,
                "muted",
            )
            self.button(
                pygame.Rect(rect.right - 138, rect.y + 7, 124, 34),
                "JOIN" if available else "UNAVAILABLE",
                self.mouse,
                enabled=available,
                accent=available,
            )
        self.button(rects["back"], "BACK", self.mouse)
        self.text(
            "Matches are server-authoritative; neither player can pause or change speed.",
            (190, 765),
            11,
            "muted",
        )

    def draw_multiplayer_lobby(self):
        self.draw_menu_background()
        room = self.network_lobby or {}
        rects = self.network_lobby_rects()
        title = self.get_font(48).render("PVP LOBBY", True, COLORS["white"])
        self.screen.blit(title, (WINDOW_W // 2 - title.get_width() // 2, 65))
        self.text(
            f"ROOM {room.get('id', '------')} · {room.get('name', 'Battle')}",
            (WINDOW_W // 2 - 320, 150),
            18,
            "select",
        )
        self.text(
            f"MAP {str(room.get('battlefield', 'farmland')).upper()} · SEED {room.get('seed', '-')}",
            (WINDOW_W // 2 - 320, 183),
            13,
            "muted",
        )
        players = room.get("players", [])
        for slot in range(2):
            panel = pygame.Rect(WINDOW_W // 2 - 390 + slot * 410, 255, 370, 245)
            pygame.draw.rect(self.screen, COLORS["panel"], panel, border_radius=6)
            pygame.draw.rect(
                self.screen,
                COLORS["nato_friend"] if slot == 0 else COLORS["nato_hostile"],
                panel,
                2,
                border_radius=6,
            )
            player = next(
                (item for item in players if int(item.get("slot", -1)) == slot), None
            )
            self.text(
                "BLUE FORCE" if slot == 0 else "RED FORCE",
                (panel.x + 20, panel.y + 20),
                18,
                "white",
            )
            if player:
                self.text(
                    str(player.get("name", "Player")),
                    (panel.x + 20, panel.y + 78),
                    24,
                    "select",
                )
                self.text(
                    "READY" if player.get("ready") else "NOT READY",
                    (panel.x + 20, panel.y + 132),
                    16,
                    "good" if player.get("ready") else "contact",
                )
            else:
                self.text(
                    "WAITING FOR PLAYER...", (panel.x + 20, panel.y + 92), 16, "muted"
                )
        me = next(
            (item for item in players if item.get("id") == self.network_connection_id),
            None,
        )
        ready = bool(me and me.get("ready"))
        self.button(
            rects["ready"],
            "UNREADY" if ready else "READY",
            self.mouse,
            accent=not ready,
        )
        self.button(rects["leave"], "LEAVE LOBBY", self.mouse)
        self.text(
            "The battle begins automatically when both commanders are ready.",
            (WINDOW_W // 2 - 290, 555),
            14,
            "muted",
        )

    def _network_issue_context(self, cell, append=False):
        if not getattr(self, "network_match_active", False):
            return self._operation_issue_context(cell, append=append)
        units = self.selected_units()
        if not units:
            return
        target = self.game.unit_at(*cell)
        if (
            target is not None
            and target.faction == "enemy"
            and self.game.visible_to("player", target)
        ):
            self.send_network_command(
                "fire", units, target=target.uid, mode=units[0].fire_mode
            )
            return
        mode = self.command_mode
        payload = {
            "position": list(cell),
            "append": bool(append),
            "formation": self.formation,
        }
        if mode.startswith("build:"):
            self.send_network_command(
                "build", units, kind=mode.split(":", 1)[1], position=list(cell)
            )
        elif mode in ("grenade", "smoke", "rifle_grenade"):
            self.send_network_command(mode, units, position=list(cell), cook=self.cook)
        elif mode in ("suppress", "overwatch", "assault", "bound", "fallback"):
            self.send_network_command(mode, units, position=list(cell))
        elif mode == "mortar":
            self.send_network_command("mortar", units, position=list(cell), smoke=False)
        elif mode == "mortar_smoke":
            self.send_network_command("mortar", units, position=list(cell), smoke=True)
        elif mode == "normal":
            self.send_network_command("move", units, **payload)
        else:
            _qol_notify(
                self,
                f"{mode.upper()} is not network-enabled yet",
                kind="danger",
                duration=1.8,
            )
            return
        self.command_mode = "normal"

    def draw(self):
        self.process_network_messages()
        if self.state == "multiplayer":
            self.screen.fill(COLORS["bg"])
            self.draw_multiplayer_browser()
            self.present()
            return
        if self.state == "multiplayer_lobby":
            self.screen.fill(COLORS["bg"])
            self.draw_multiplayer_lobby()
            self.present()
            return
        result = self._operation_draw()
        network_match_active = getattr(self, "network_match_active", False)
        network_match_result = getattr(self, "network_match_result", None)
        if self.state == "game" and (network_match_active or network_match_result):
            status = (
                "LIVE" if network_match_active else str(network_match_result).upper()
            )
            label = f"MULTIPLAYER · {str(self.network_side or '?').upper()} · {status}"
            panel = pygame.Rect(WINDOW_W // 2 - 190, 8, 380, 30)
            pygame.draw.rect(self.screen, COLORS["panel2"], panel, border_radius=3)
            pygame.draw.rect(
                self.screen,
                COLORS["select"] if network_match_active else COLORS["contact"],
                panel,
                1,
                border_radius=3,
            )
            surface = self.cached_text_surface(label, 11, "white")
            self.screen.blit(
                surface,
                (
                    panel.centerx - surface.get_width() // 2,
                    panel.centery - surface.get_height() // 2,
                ),
            )
            if network_match_result:
                overlay = pygame.Rect(WINDOW_W // 2 - 260, WINDOW_H // 2 - 95, 520, 190)
                pygame.draw.rect(self.screen, COLORS["panel"], overlay, border_radius=6)
                pygame.draw.rect(
                    self.screen,
                    COLORS["select"] if self.game.victory else COLORS["danger"],
                    overlay,
                    2,
                    border_radius=6,
                )
                self.text(
                    f"PVP {str(network_match_result).upper()}",
                    (overlay.x + 115, overlay.y + 42),
                    32,
                    "white",
                )
                self.text(
                    "Press Enter to return to the server browser",
                    (overlay.x + 86, overlay.y + 112),
                    14,
                    "muted",
                )
            self.present()
        return result

    def draw_terrain(self, cell, rect, x, y):
        self._vs_draw_terrain2(cell, rect, x, y)
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
                pygame.draw.line(
                    self.screen,
                    color,
                    (px, py + 2),
                    (px + (1 if mark[2] > 0.5 else -1), py - 1),
                    1,
                )
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
                pygame.draw.ellipse(
                    self.screen, (78, 70, 56), (px - 3, py - 1, 7, 3), 1
                )
                pygame.draw.line(
                    self.screen, (111, 102, 83), (px - 1, py), (px + 2, py), 1
                )
        elif cell.terrain == "road":
            for mark in marks[:2]:
                _px, py = pixel(mark)
                pygame.draw.line(
                    self.screen,
                    (103, 96, 78),
                    (rect.left + 3, py),
                    (rect.right - 4, py),
                    1,
                )
        elif cell.terrain == "rubble":
            for mark in marks[:4]:
                px, py = pixel(mark)
                pygame.draw.polygon(
                    self.screen,
                    (91, 88, 78),
                    ((px, py - 2), (px + 3, py + 2), (px - 2, py + 2)),
                )
                pygame.draw.polygon(
                    self.screen,
                    (48, 49, 45),
                    ((px, py - 2), (px + 3, py + 2), (px - 2, py + 2)),
                    1,
                )
        elif cell.terrain == "water":
            for mark in marks[:2]:
                _px, py = pixel(mark)
                inset = 4 + int(mark[2] * 5)
                pygame.draw.line(
                    self.screen,
                    (85, 111, 112),
                    (rect.left + inset, py),
                    (rect.right - inset, py),
                    1,
                )
        elif cell.terrain in ("building", "wall", "woodwall"):
            for mark in marks[:2]:
                px, py = pixel(mark)
                pygame.draw.line(
                    self.screen, (43, 44, 41), (px - 2, py - 1), (px + 3, py + 2), 1
                )

    def _presentation_draw_unit(self, unit):
        self._operation_draw_unit(unit)
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
                pygame.draw.line(
                    self.screen,
                    color,
                    corner,
                    (corner[0] - sx * (5 + pulse), corner[1]),
                    2,
                )
                pygame.draw.line(
                    self.screen,
                    color,
                    corner,
                    (corner[0], corner[1] - sy * (5 + pulse)),
                    2,
                )
        stance = getattr(unit, "stance", "stand")
        stance_color = (
            COLORS["good"]
            if stance == "prone"
            else COLORS["contact"]
            if stance == "crouch"
            else COLORS["muted"]
        )
        pygame.draw.circle(
            self.screen,
            stance_color,
            (cx - max(12, int(14 * scale)), cy + max(9, int(10 * scale))),
            2,
        )
        if unit.suppression >= 50:
            arc_color = (
                COLORS["danger"] if unit.suppression >= 80 else COLORS["suppression"]
            )
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

    def draw_presentation_transient(self, event, now):
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
            pygame.draw.line(
                self.screen,
                color,
                (center[0] - radius * 2, center[1]),
                (center[0] + radius * 2, center[1]),
                1,
            )
            pygame.draw.line(
                self.screen,
                color,
                (center[0], center[1] - radius * 2),
                (center[0], center[1] + radius * 2),
                1,
            )
        elif kind == "explosion" and age <= 0.72:
            progress = clamp(age / 0.72, 0.0, 1.0)
            radius = max(
                4,
                int(
                    (8 + float(event.get("radius", 2.0)) * self.tile_px * 0.62)
                    * (0.35 + progress)
                ),
            )
            alpha = int(165 * (1.0 - progress))
            surface = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
            local = (radius + 3, radius + 3)
            pygame.draw.circle(surface, (235, 126, 50, alpha), local, radius)
            pygame.draw.circle(
                surface,
                (255, 222, 145, min(210, alpha + 35)),
                local,
                max(2, radius // 3),
            )
            pygame.draw.circle(surface, (76, 68, 57, alpha), local, radius, 2)
            self.screen.blit(surface, (center[0] - radius - 3, center[1] - radius - 3))
        elif kind in ("hurt", "death") and age <= 0.42:
            progress = clamp(age / 0.42, 0.0, 1.0)
            radius = 5 + int(progress * 12)
            pygame.draw.circle(
                self.screen,
                COLORS["danger"],
                center,
                radius,
                2 if kind == "death" else 1,
            )

    def draw_presentation_weather(self, clock):
        rect = self.map_view_rect()
        weather = getattr(self.game, "weather", "clear")
        count = 48 if weather == "rain" else 12 if weather == "fog" else 9
        particles = presentation_weather_particles(
            weather, self.game.seed, clock, rect.w, rect.h, count
        )
        if weather == "rain":
            layer = pygame.Surface(rect.size, pygame.SRCALPHA)
            wind_x = int(clamp(getattr(self.game, "wind", (0, 0))[0] * 3, -4, 4))
            for x, y, length, alpha in particles:
                pygame.draw.line(
                    layer, (166, 187, 190, alpha), (x, y), (x + wind_x, y + length), 1
                )
            self.screen.blit(layer, rect.topleft)
        elif weather == "fog":
            layer = pygame.Surface(rect.size, pygame.SRCALPHA)
            for x, y, length, alpha in particles:
                pygame.draw.ellipse(
                    layer, (202, 203, 190, alpha), (x - length // 2, y - 8, length, 16)
                )
            self.screen.blit(layer, rect.topleft)
        else:
            for x, y, _length, alpha in particles:
                color = (164, 150, 112) if alpha > 23 else (106, 103, 84)
                pygame.draw.circle(self.screen, color, (rect.left + x, rect.top + y), 1)

    def draw_presentation_vignette(self):
        rect = self.map_view_rect()
        if (
            self._presentation_vignette is None
            or self._presentation_vignette.get_size() != rect.size
        ):
            surface = pygame.Surface(rect.size, pygame.SRCALPHA)
            steps = 14
            for index in range(steps):
                alpha = int(4 + index * 1.35)
                inset = index * 3
                pygame.draw.rect(
                    surface,
                    (8, 10, 8, alpha),
                    pygame.Rect(inset, inset, rect.w - inset * 2, rect.h - inset * 2),
                    3,
                )
            self._presentation_vignette = surface
        self.screen.blit(self._presentation_vignette, rect.topleft)
        pygame.draw.rect(self.screen, (121, 116, 91), rect, 1)

    def _presentation_draw_map(self):
        self._operation_draw_map()
        if self.state not in ("deployment", "game"):
            return
        now = time.perf_counter()
        supports_clip = hasattr(self.screen, "get_clip") and hasattr(
            self.screen, "set_clip"
        )
        old_clip = self.screen.get_clip() if supports_clip else None
        if supports_clip:
            self.screen.set_clip(self.map_view_rect())
        try:
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
                rng = random.Random(
                    self.game.seed ^ x * 9137 ^ y * 193 ^ int(self.game.time * 8)
                )
                for _ in range(min(4, 1 + int(fire))):
                    ex = center[0] + rng.randint(-5, 5)
                    ey = center[1] - rng.randint(4, 14)
                    pygame.draw.circle(
                        self.screen, (242, 137 + rng.randint(0, 60), 62), (ex, ey), 1
                    )
            self._presentation_events = [
                event
                for event in self._presentation_events
                if now - float(event.get("presented_at", now)) <= 0.75
            ]
            for event in self._presentation_events:
                self.draw_presentation_transient(event, now)
            self.draw_presentation_weather(getattr(self.game, "time", 0.0))
            self.draw_presentation_vignette()
        finally:
            if supports_clip:
                self.screen.set_clip(old_clip)

    def draw_menu_background(self):
        self._base_draw_menu_background()
        if (
            self._presentation_menu_overlay is None
            or self._presentation_menu_overlay.get_size() != (WINDOW_W, WINDOW_H)
        ):
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
                pygame.draw.line(
                    overlay, (195, 185, 146, 13), (x, 220), (x + 170, 650), 1
                )
            self._presentation_menu_overlay = overlay
        self.screen.blit(self._presentation_menu_overlay, (0, 0))

    def _combat2_draw_unit(self, unit):
        self._presentation_draw_unit(unit)
        if not unit.alive or unit.role in COMBAT2_STATIC_ROLES:
            return
        wound_load = max(
            float(getattr(unit, "wound_head", 0.0)),
            float(getattr(unit, "wound_torso", 0.0)),
            float(getattr(unit, "wound_arm", 0.0)),
            float(getattr(unit, "wound_leg", 0.0)),
        )
        if wound_load < 18:
            return
        center = self.world_to_screen(unit.x, unit.y)
        if not self.map_view_rect().inflate(30, 30).collidepoint(center):
            return
        radius = max(14, int(self.tile_px * 0.58))
        color = COLORS["danger"] if wound_load >= 55 else COLORS["contact"]
        pygame.draw.line(
            self.screen,
            color,
            (center[0] + radius - 5, center[1] - radius),
            (center[0] + radius, center[1] - radius),
            2,
        )
        pygame.draw.line(
            self.screen,
            color,
            (center[0] + radius, center[1] - radius),
            (center[0] + radius, center[1] - radius + 5),
            2,
        )

    def draw_settings(self):
        self._qol_draw_settings()
        rects = self.settings_rects()
        self.button(
            rects["shake"],
            f"CAMERA SHAKE: {('ON' if self.camera_shake_enabled else 'OFF')}",
            self.mouse,
            accent=self.camera_shake_enabled,
        )
        self.button(
            rects["edge"],
            f"EDGE SCROLL: {('ON' if self.edge_scroll_enabled else 'OFF')}",
            self.mouse,
            accent=self.edge_scroll_enabled,
        )

    def issue_context_command(self, cell, append=False):
        units = list(self.selected_units())
        result = self._network_issue_context(cell, append=append)
        blocked = [
            unit
            for unit in units
            if self.game.time < getattr(unit, "polish_lane_blocked_until", 0.0)
        ]
        if blocked:
            _qol_notify(
                self,
                f"{len(blocked)} unit{('s' if len(blocked) != 1 else '')} waiting for a clear friendly lane",
                kind="danger",
                duration=2.0,
            )
        return result

    def draw_unit(self, unit):
        self._combat2_draw_unit(unit)
        if not unit.combat_effective:
            return
        center = self.world_to_screen(unit.x, unit.y)
        if not self.map_view_rect().inflate(30, 30).collidepoint(center):
            return
        if self.game.time < getattr(unit, "polish_reaction_until", 0.0):
            radians = math.radians(unit.facing)
            direction = (math.cos(radians), math.sin(radians))
            base = (
                center[0] - round(direction[0] * 17),
                center[1] - round(direction[1] * 17),
            )
            tip = (
                center[0] - round(direction[0] * 26),
                center[1] - round(direction[1] * 26),
            )
            pygame.draw.line(self.screen, COLORS["suppression"], base, tip, 2)
        if unit.uid in self.selected and self.game.time < getattr(
            unit, "polish_lane_blocked_until", 0.0
        ):
            radius = max(15, int(self.tile_px * 0.6))
            pygame.draw.circle(self.screen, COLORS["danger"], center, radius, 2)
            pygame.draw.line(
                self.screen,
                COLORS["danger"],
                (center[0] - radius + 3, center[1] + radius - 3),
                (center[0] + radius - 3, center[1] - radius + 3),
                2,
            )

    def draw_map(self):
        self._presentation_draw_map()
        if self.state not in ("game", "deployment"):
            return
        map_rect = self.map_view_rect()
        for start_x, start_y, end_x, end_y, faction, expires in getattr(
            self.game, "polish_recent_tracers", []
        )[-90:]:
            if expires <= self.game.time:
                continue
            start = self.world_to_screen(start_x, start_y)
            end = self.world_to_screen(end_x, end_y)
            clipped = map_rect.clipline(start, end)
            if clipped:
                color = (151, 220, 232) if faction == "player" else (238, 133, 72)
                pygame.draw.line(self.screen, color, clipped[0], clipped[1], 1)
        age = self.game.time - getattr(self.game, "polish_engagement_changed_at", -99.0)
        if 0 <= age <= 2.2:
            label = self.game.polish_engagement_state
            alpha_color = "danger" if label in ("ENGAGEMENT", "BROKEN") else "objective"
            surface = self.cached_text_surface(label, 11, alpha_color)
            panel = pygame.Rect(
                map_rect.centerx - surface.get_width() // 2 - 12,
                map_rect.top + 8,
                surface.get_width() + 24,
                22,
            )
            pygame.draw.rect(self.screen, (25, 28, 24), panel, border_radius=3)
            pygame.draw.rect(
                self.screen, COLORS[alpha_color], panel, 1, border_radius=3
            )
            self.screen.blit(
                surface,
                (
                    panel.centerx - surface.get_width() // 2,
                    panel.centery - surface.get_height() // 2,
                ),
            )

    def draw_after_action(self):
        now = time.perf_counter()
        game_identity = id(self.game)
        if self.polish_result_game != game_identity:
            self.polish_result_game = game_identity
            self.polish_result_seen_at = None
        if self.polish_result_seen_at is None:
            self.polish_result_seen_at = now
        if now - self.polish_result_seen_at < 0.9:
            return
        result = self._vs_draw_after_action()
        width = 760
        x = MAP_X + (MAP_VIEW_W_PX - width) // 2
        y = MAP_Y + 35
        state = getattr(self.game, "polish_engagement_state", "COMPLETE")
        peak = getattr(self.game, "polish_peak_intensity", 0.0)
        self.text(
            f"FINAL STATE {state}   ·   PEAK COMBAT INTENSITY {peak:.0f}",
            (x + 24, y + 72),
            9,
            "muted",
        )
        return result
