import math
import pygame

from game_logic import (
    BUILD_MENU_LABELS,
    BUILD_MENU_ORDER,
    CAPITAL_SHIP_TYPES,
    DESTROYER_TYPES,
    HANGAR_BOMBER_KEY,
    HANGAR_FIGHTER_KEY,
    LIGHT_SHIP_TYPES,
    SHIP_TEMPLATES,
)

ESCORT_SHIP_TYPES = DESTROYER_TYPES

def _sans_ui(size, bold=False):
    names = ["segoe ui", "inter", "consolas"]
    for n in names:
        f = pygame.font.SysFont(n, size, bold=bold)
        if f.get_height() > 0:
            return f
    return pygame.font.Font(None, size)

def _mono_ui(size, bold=False):
    names = ["cascadia mono", "consolas", "couriernew"]
    for n in names:
        f = pygame.font.SysFont(n, size, bold=bold)
        if f.get_height() > 0:
            return f
    return pygame.font.SysFont("courier", size, bold=bold)


# Board visual themes — includes legacy “original” palette plus conceptual mock-ups.
VISUAL_THEMES = [
    {
        "name": "Classic (original)",
        "retro_courier_fonts": True,
        "board_font_mono": False,
        "cell_a": (10, 10, 20),
        "cell_b": (10, 10, 20),
        "grid": (40, 40, 60),
        "grid_w": 1,
        "glass_top_highlight": False,
        "planet_fill": (50, 200, 100),
        "planet_edge": (50, 200, 100),
        "planet_stroke_w": 0,
        "planet_glow_alpha": 0,
        "p1_fill": (50, 100, 255),
        "p1_edge": (110, 170, 255),
        "p2_fill": (255, 50, 50),
        "p2_edge": (255, 110, 110),
        "base_ring": (150, 150, 158),
        "air_fighter": (210, 210, 210),
        "air_bomber": (60, 60, 60),
        "frame_unit_friend": (170, 255, 255),
        "frame_unit_hostile": (255, 255, 120),
        "tile_friend": (120, 220, 255),
        "tile_hostile": (255, 240, 120),
        "stripe": (60, 60, 60),
        "scrap": (255, 245, 200),
        "stack_label": (230, 230, 230),
        "ui_left": (20, 20, 20),
        "ui_right": (30, 30, 30),
        "ui_sep": (255, 255, 255),
        "text_friend": (100, 255, 255),
        "text_hostile": (255, 255, 100),
        "text_log": (200, 200, 200),
        "text_muted": (180, 180, 180),
        "text_tuning_on": (120, 255, 120),
        "text_tuning_off": (160, 160, 160),
        "text_ai_on": (255, 200, 120),
        "text_ai_off": (140, 140, 140),
        "build_overlay": (10, 10, 22, 220),
        "build_title": (220, 220, 150),
        "build_line": (200, 235, 200),
        "game_over_dark": (18, 8, 8, 230),
        "game_over_title": (255, 210, 160),
        "game_over_sub": (240, 240, 240),
    },
    {
        "name": "Carbon monolith",
        "board_font_mono": True,
        "cell_a": (28, 30, 34),
        "cell_b": (34, 36, 41),
        "grid": (64, 70, 78),
        "grid_w": 1,
        "glass_top_highlight": False,
        "planet_fill": (112, 120, 132),
        "planet_edge": (238, 240, 246),
        "planet_stroke_w": 2,
        "planet_glow_alpha": 42,
        "p1_fill": (72, 90, 112),
        "p1_edge": (210, 218, 230),
        "p2_fill": (96, 78, 76),
        "p2_edge": (226, 210, 200),
        "base_ring": (160, 168, 180),
        "air_fighter": (240, 242, 246),
        "air_bomber": (68, 72, 82),
        "frame_unit_friend": (160, 210, 255),
        "frame_unit_hostile": (255, 210, 150),
        "tile_friend": (120, 200, 255),
        "tile_hostile": (255, 220, 140),
        "stripe": (54, 60, 70),
        "scrap": (230, 234, 240),
        "stack_label": (200, 205, 214),
        "ui_left": (22, 24, 28),
        "ui_right": (26, 28, 33),
        "ui_sep": (88, 92, 100),
        "text_friend": (170, 220, 245),
        "text_hostile": (255, 220, 165),
        "text_log": (192, 198, 208),
        "text_muted": (150, 156, 168),
        "text_tuning_on": (140, 220, 160),
        "text_tuning_off": (146, 150, 160),
        "text_ai_on": (255, 200, 150),
        "text_ai_off": (130, 136, 150),
        "build_overlay": (18, 20, 24, 230),
        "build_title": (230, 234, 240),
        "build_line": (170, 210, 180),
        "game_over_dark": (18, 10, 12, 230),
        "game_over_title": (255, 210, 200),
        "game_over_sub": (230, 225, 230),
    },
    {
        "name": "Arctic chrome",
        "board_font_mono": False,
        "cell_a": (250, 251, 253),
        "cell_b": (242, 244, 248),
        "grid": (210, 218, 230),
        "grid_w": 1,
        "glass_top_highlight": True,
        "planet_fill": (214, 224, 234),
        "planet_edge": (255, 255, 255),
        "planet_stroke_w": 2,
        "planet_glow_alpha": 20,
        "p1_fill": (198, 210, 228),
        "p2_fill": (222, 214, 210),
        "p1_edge": (112, 128, 150),
        "p2_edge": (150, 128, 120),
        "base_ring": (176, 186, 200),
        "air_fighter": (252, 252, 254),
        "air_bomber": (128, 136, 150),
        "frame_unit_friend": (70, 130, 200),
        "frame_unit_hostile": (210, 150, 80),
        "tile_friend": (100, 180, 235),
        "tile_hostile": (240, 200, 120),
        "stripe": (168, 180, 198),
        "scrap": (64, 72, 86),
        "stack_label": (90, 98, 112),
        "ui_left": (248, 249, 252),
        "ui_right": (244, 246, 250),
        "ui_sep": (210, 220, 235),
        "text_friend": (40, 80, 130),
        "text_hostile": (120, 70, 50),
        "text_log": (66, 76, 90),
        "text_muted": (110, 120, 138),
        "text_tuning_on": (52, 120, 92),
        "text_tuning_off": (126, 132, 146),
        "text_ai_on": (130, 100, 70),
        "text_ai_off": (140, 145, 155),
        "build_overlay": (252, 252, 254, 215),
        "build_title": (48, 56, 70),
        "build_line": (60, 90, 70),
        "game_over_dark": (40, 36, 38, 230),
        "game_over_title": (250, 240, 240),
        "game_over_sub": (232, 230, 235),
    },
]


VISUAL_THEME_COUNT = len(VISUAL_THEMES)


class Renderer:
    def __init__(self):
        pygame.init()
        # Pixelated retro look
        self.cell_size = 60
        self.width = self.cell_size * 10
        self.height = (self.cell_size * 10) + 200 # Extra space for textboxes
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Starfleet Command")
        self.board_visual_theme = 0
        self.font = pygame.font.SysFont("courier", 14, bold=True) # Monospace retro font
        self.small_font = pygame.font.SysFont("courier", 12)
        self._apply_visual_theme_fonts()

    def _palette(self):
        return VISUAL_THEMES[self.board_visual_theme % len(VISUAL_THEMES)]

    def cycle_board_visual_theme(self):
        self.board_visual_theme = (self.board_visual_theme + 1) % len(VISUAL_THEMES)
        self._apply_visual_theme_fonts()

    def _apply_visual_theme_fonts(self):
        pal = self._palette()
        if pal.get("retro_courier_fonts"):
            self.font = pygame.font.SysFont("courier", 14, bold=True)
            self.small_font = pygame.font.SysFont("courier", 12)
        elif pal.get("board_font_mono"):
            self.font = _mono_ui(14, bold=True)
            self.small_font = _mono_ui(12, bold=False)
        else:
            self.font = _sans_ui(14, bold=True)
            self.small_font = _sans_ui(12, bold=False)

    @property
    def visual_theme_name(self):
        return self._palette()["name"]

    def _fmt(self, value):
        if isinstance(value, (int, float)):
            if float(value).is_integer():
                return str(int(value))
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return str(value)

    def _render_wrapped(self, text, color, x, y, max_width, font=None):
        f = font or self.small_font
        words = str(text).split()
        if not words:
            return y
        line = words[0]
        for w in words[1:]:
            trial = f"{line} {w}"
            if f.size(trial)[0] <= max_width:
                line = trial
            else:
                self.screen.blit(f.render(line, True, color), (x, y))
                y += 16
                line = w
        self.screen.blit(f.render(line, True, color), (x, y))
        return y + 16

    def _clamp_point_to_cell(self, x, y, cell_rect):
        min_x = cell_rect.left + 2
        max_x = cell_rect.right - 3
        min_y = cell_rect.top + 2
        max_y = cell_rect.bottom - 3
        return (
            max(min_x, min(int(x), max_x)),
            max(min_y, min(int(y), max_y)),
        )

    def _clamp_rect_to_cell(self, rect, cell_rect):
        r = rect.copy()
        if r.width > cell_rect.width - 4:
            r.width = cell_rect.width - 4
        if r.height > cell_rect.height - 4:
            r.height = cell_rect.height - 4
        min_left = cell_rect.left + 2
        max_left = cell_rect.right - 2 - r.width
        min_top = cell_rect.top + 2
        max_top = cell_rect.bottom - 2 - r.height
        r.left = max(min_left, min(r.left, max_left))
        r.top = max(min_top, min(r.top, max_top))
        return r

    def _capital_center_offsets(self, count, spacing):
        if count <= 0:
            return []
        cols = max(1, math.ceil(math.sqrt(count)))
        rows = math.ceil(count / cols)
        x0 = -((cols - 1) * spacing) / 2.0
        y0 = -((rows - 1) * spacing) / 2.0
        offsets = []
        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= count:
                    break
                offsets.append((x0 + c * spacing, y0 + r * spacing))
                idx += 1
        return offsets

    def _escort_flank_offsets(self, count, half_step, flank_x):
        """Return per-destroyer offsets that form a half-overlapping cluster on
        each flank. Half of the previous destroyer remains visible."""
        offsets = []
        per_side = [0, 0]
        for i in range(count):
            side_idx = i % 2
            rank = per_side[side_idx]
            per_side[side_idx] += 1
            sign = -1 if side_idx == 0 else 1
            ox = sign * flank_x + rank * half_step * sign
            oy = rank * half_step
            offsets.append((ox, oy))
        return offsets

    def _resolve_non_destroyer_overlaps(self, rects, cell_rect, max_passes=6):
        """Iteratively nudge any intersecting non-destroyer rects apart along
        the cell's center-out vector while clamping to cell bounds."""
        if len(rects) < 2:
            return
        cx, cy = cell_rect.centerx, cell_rect.centery
        for _ in range(max_passes):
            moved_any = False
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a = rects[i]
                    b = rects[j]
                    if not a.colliderect(b):
                        continue
                    moved_any = True
                    # Push b away from cell center; if it's at center, push down.
                    dx = b.centerx - cx
                    dy = b.centery - cy
                    if dx == 0 and dy == 0:
                        dy = 1
                    sx = 0 if dx == 0 else (1 if dx > 0 else -1)
                    sy = 0 if dy == 0 else (1 if dy > 0 else -1)
                    if abs(dx) >= abs(dy):
                        b.left += sx if sx else 1
                    else:
                        b.top += sy if sy else 1
                    nudged = self._clamp_rect_to_cell(b, cell_rect)
                    rects[j] = nudged
            if not moved_any:
                return

    def _draw_diagonal_stripes(self, rect, stripe_color, gap=4):
        """Draw dark-grey diagonal stripes over a rect to indicate a light ship."""
        clip = self.screen.get_clip()
        self.screen.set_clip(rect)
        x0 = rect.left - rect.height
        while x0 < rect.right + rect.height:
            pygame.draw.line(
                self.screen, stripe_color,
                (x0, rect.bottom),
                (x0 + rect.height, rect.top),
                1,
            )
            x0 += gap
        self.screen.set_clip(clip)

    def _draw_cell_glass_highlight(self, rect, pal):
        if not pal.get("glass_top_highlight"):
            return
        hi = pygame.Surface((rect.width, max(4, rect.height // 5)), pygame.SRCALPHA)
        hi.fill((255, 255, 255, 52))
        self.screen.blit(hi, rect.topleft)

    def _rear_offsets(self, count, spacing):
        if count <= 0:
            return []
        cols = max(1, min(5, math.ceil(math.sqrt(count))))
        rows = math.ceil(count / cols)
        x0 = -((cols - 1) * spacing) / 2.0
        offsets = []
        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= count:
                    break
                offsets.append((x0 + c * spacing, r * spacing))
                idx += 1
        return offsets

    def draw(self, game_state):
        pal = self._palette()
        bs = getattr(game_state, "board_size", 10)
        half = self.cell_size // 2
        pr = min(15, max(8, half - 5))
        gw = int(pal.get("grid_w", 1))

        # Board field (orthogonal tiles — conceptual material study)
        for x in range(bs):
            for y in range(bs):
                rect = pygame.Rect(x * self.cell_size, y * self.cell_size, self.cell_size, self.cell_size)
                filler = pal["cell_a"] if (x + y) % 2 == 0 else pal["cell_b"]
                pygame.draw.rect(self.screen, filler, rect)
                self._draw_cell_glass_highlight(rect, pal)
                pygame.draw.rect(self.screen, pal["grid"], rect, gw)

        for px, py in game_state.planets:
            tcx, tcy = px * self.cell_size + half, py * self.cell_size + half
            glow_alpha = min(220, max(12, pal.get("planet_glow_alpha", 30)))
            glow_r = max(4, pr - 6)
            if glow_alpha > 0 and glow_r > 0:
                glow = pygame.Surface((glow_r * 2 + 2, glow_r * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(glow, (255, 255, 255, glow_alpha), (glow_r + 1, glow_r + 1), glow_r)
                gr = glow.get_rect(center=(tcx, tcy))
                self.screen.blit(glow, gr.topleft)
            pygame.draw.circle(self.screen, pal["planet_fill"], (tcx, tcy), pr)
            planet_sw = int(pal.get("planet_stroke_w", 2))
            if planet_sw > 0:
                pygame.draw.circle(self.screen, pal["planet_edge"], (tcx, tcy), pr, planet_sw)

        selected_ship = next((s for s in game_state.all_ships if s.is_selected), None)
        enemy_selected_ship = next((s for s in game_state.all_ships if s.is_enemy_selected), None)

        # Draw each fleet stack as a bounded mini-formation inside each tile.
        stack_map = {}
        for ship in game_state.all_ships:
            stack_map.setdefault((ship.x, ship.y, ship.owner), []).append(ship)

        for (x, y, owner), stack in stack_map.items():
            stack_sorted = sorted(stack, key=lambda s: s.id)
            bases_here = [s for s in stack_sorted if getattr(s, "is_base", False)]
            aircraft_counters_here = [s for s in stack_sorted if getattr(s, "is_aircraft_counter", False)]
            mobiles_here = [
                s for s in stack_sorted
                if not getattr(s, "is_base", False) and not getattr(s, "is_aircraft_counter", False)
            ]
            fleet_fill = pal["p1_fill"] if owner == 1 else pal["p2_fill"]
            border_color = pal["p1_edge"] if owner == 1 else pal["p2_edge"]
            cell_left = x * self.cell_size
            cell_top = y * self.cell_size
            cell_rect = pygame.Rect(cell_left, cell_top, self.cell_size, self.cell_size)
            selected_in_stack = selected_ship and any(s.id == selected_ship.id for s in stack_sorted)
            enemy_selected_in_stack = enemy_selected_ship and any(s.id == enemy_selected_ship.id for s in stack_sorted)
            # Base: thin neutral ring seated on the planet disc (planet drawn first in grid pass).
            if bases_here:
                half_sz = self.cell_size // 2
                cell_cx = cell_left + half_sz
                cell_cy = cell_top + half_sz
                ring_color = pal["base_ring"]
                if (x, y) in game_state.planets:
                    ring_r = max(pr - 4, max(8, half_sz // 3))
                else:
                    ring_r = max(10, half_sz - 10)
                pygame.draw.circle(self.screen, ring_color, (cell_cx, cell_cy), ring_r, 2)
                if not mobiles_here:
                    scrap_surf = self.small_font.render(self._fmt(bases_here[0].scrap), True, pal["scrap"])
                    self.screen.blit(scrap_surf, (cell_cx - scrap_surf.get_width() // 2, cell_cy - scrap_surf.get_height() // 2))

            # Aircraft glyphs should render even on tiles with only Fighter/Bomber
            # hulls (no carrier/escort). Those hulls are marked as
            # `is_aircraft_counter`, so `mobiles_here` may be empty.
            if mobiles_here or aircraft_counters_here:
                capitals = [s for s in mobiles_here if s.ship_type in CAPITAL_SHIP_TYPES]
                escorts = [s for s in mobiles_here if s.ship_type in ESCORT_SHIP_TYPES]
                others = [
                    s for s in mobiles_here
                    if s.ship_type not in CAPITAL_SHIP_TYPES and s.ship_type not in ESCORT_SHIP_TYPES
                ]
                front_line_units = capitals + others

                # Fixed glyph dimensions.
                CAP_W, CAP_H = 16, 12
                LONG_W, LONG_H = 22, 10   # Dreadnaught / Aircraft Carrier
                ESC_SZ = 10
                TRI_SZ = 5  # aircraft triangles slightly smaller than destroyers

                center_x = cell_left + self.cell_size // 2
                center_y = cell_top + self.cell_size // 2
                front_dir = 1 if owner == 1 else -1

                # Row bands spaced so they never overlap each other.
                cap_band_y = center_y + front_dir * 13
                esc_band_y = center_y + front_dir * 0
                # Aircraft should visually stay with the hulls that store them.
                # When a hull crosses the board's midline, the old rear-only
                # placement could appear "split" because the triangles were
                # still drawn toward the player's home side.
                capitals_here = any(s.ship_type in CAPITAL_SHIP_TYPES for s in mobiles_here)
                escorts_here = any(s.ship_type in ESCORT_SHIP_TYPES for s in mobiles_here)
                carrier_band_y = cap_band_y if capitals_here else (esc_band_y if escorts_here else center_y)
                ftr_band_y = carrier_band_y
                bmb_band_y = carrier_band_y - front_dir * 4

                cap_spacing = CAP_W + 3
                esc_spacing = ESC_SZ + 3
                tri_spacing = TRI_SZ * 2 + 3

                shape_bounds = {}
                non_destroyer_rects = []

                # --- Front line: capitals + other non-escort hulls ---
                cap_cols = max(1, (self.cell_size - 6) // cap_spacing)
                cap_row_gap = max(CAP_H, LONG_H) + 3
                cap_layout = []
                for idx, ship in enumerate(front_line_units):
                    row = idx // cap_cols
                    col = idx % cap_cols
                    row_count = min(cap_cols, len(front_line_units) - row * cap_cols)
                    x0 = center_x - ((row_count - 1) * cap_spacing) / 2.0
                    cx = x0 + col * cap_spacing
                    cy = cap_band_y - front_dir * row * cap_row_gap
                    elongated = ship.ship_type in ("Dreadnaught", "Aircraft Carrier")
                    w, h = (LONG_W, LONG_H) if elongated else (CAP_W, CAP_H)
                    r = pygame.Rect(0, 0, w, h)
                    r.center = (int(cx), int(cy))
                    r = self._clamp_rect_to_cell(r, cell_rect)
                    cap_layout.append((ship, r, elongated))
                    non_destroyer_rects.append(r)

                self._resolve_non_destroyer_overlaps(non_destroyer_rects, cell_rect)
                for (ship, _, elongated), r in zip(cap_layout, non_destroyer_rects):
                    light = ship.ship_type in LIGHT_SHIP_TYPES
                    pygame.draw.rect(self.screen, fleet_fill, r)
                    if light:
                        self._draw_diagonal_stripes(r, pal["stripe"])
                    pygame.draw.rect(self.screen, border_color, r, 1)
                    shape_bounds[ship.id] = ("rect", r)

                # --- Destroyer / light-destroyer row ---
                esc_cols = max(1, (self.cell_size - 6) // esc_spacing)
                escort_layout = []
                for idx, ship in enumerate(escorts):
                    row = idx // esc_cols
                    col = idx % esc_cols
                    row_count = min(esc_cols, len(escorts) - row * esc_cols)
                    x0 = center_x - ((row_count - 1) * esc_spacing) / 2.0
                    cx = x0 + col * esc_spacing
                    cy = esc_band_y - front_dir * row * (ESC_SZ + 3)
                    r = pygame.Rect(0, 0, ESC_SZ, ESC_SZ)
                    r.center = (int(cx), int(cy))
                    r = self._clamp_rect_to_cell(r, cell_rect)
                    escort_layout.append((ship, r))
                for ship, r in escort_layout:
                    light = ship.ship_type in LIGHT_SHIP_TYPES
                    pygame.draw.rect(self.screen, fleet_fill, r)
                    if light:
                        self._draw_diagonal_stripes(r, pal["stripe"])
                    pygame.draw.rect(self.screen, border_color, r, 1)
                    shape_bounds[ship.id] = ("rect", r)

                # --- Aircraft glyphs (F/B counters) ---
                # Fighter/Bomber hull ships (aircraft_counters_here) contribute
                # their own fighters/bombers; capital ships contribute via attributes.
                all_stack = mobiles_here + aircraft_counters_here
                fighter_count = sum(getattr(s, "fighters", 0) for s in all_stack)
                bomber_count = sum(getattr(s, "bombers", 0) for s in all_stack)

                if fighter_count or bomber_count:
                    air_cols = max(1, (self.cell_size - 6) // tri_spacing)

                    def _draw_air_row(count, row_y, is_fighter):
                        for idx in range(count):
                            row = idx // air_cols
                            col = idx % air_cols
                            rc = min(air_cols, count - row * air_cols)
                            x0 = center_x - ((rc - 1) * tri_spacing) / 2.0
                            cx = x0 + col * tri_spacing
                            cy = row_y - front_dir * row * (TRI_SZ + 3)
                            if owner == 1:
                                pts = [
                                    self._clamp_point_to_cell(cx, cy + TRI_SZ, cell_rect),
                                    self._clamp_point_to_cell(cx - TRI_SZ, cy - TRI_SZ, cell_rect),
                                    self._clamp_point_to_cell(cx + TRI_SZ, cy - TRI_SZ, cell_rect),
                                ]
                            else:
                                pts = [
                                    self._clamp_point_to_cell(cx, cy - TRI_SZ, cell_rect),
                                    self._clamp_point_to_cell(cx - TRI_SZ, cy + TRI_SZ, cell_rect),
                                    self._clamp_point_to_cell(cx + TRI_SZ, cy + TRI_SZ, cell_rect),
                                ]
                            fill = pal["air_fighter"] if is_fighter else pal["air_bomber"]
                            pygame.draw.polygon(self.screen, fill, pts)
                            pygame.draw.polygon(self.screen, border_color, pts, 1)

                    _draw_air_row(fighter_count, ftr_band_y, True)
                    _draw_air_row(bomber_count, bmb_band_y, False)

                # Unit frame: shape-specific outline around selected unit.
                selected_unit = selected_ship if selected_in_stack else enemy_selected_ship if enemy_selected_in_stack else None
                if selected_unit is not None and selected_unit.id in shape_bounds:
                    kind, geom = shape_bounds[selected_unit.id]
                    frame_color = pal["frame_unit_friend"] if selected_in_stack else pal["frame_unit_hostile"]
                    if kind == "rect":
                        outline = self._clamp_rect_to_cell(geom.inflate(4, 4), cell_rect)
                        pygame.draw.rect(self.screen, frame_color, outline, 2)
                    else:
                        pygame.draw.polygon(self.screen, frame_color, geom, 2)

            if mobiles_here and bases_here:
                half_sz = self.cell_size // 2
                sx = cell_left + half_sz
                sy = cell_top + half_sz
                scrap_txt = self.small_font.render(self._fmt(bases_here[0].scrap), True, (255, 245, 200))
                self.screen.blit(scrap_txt, (sx - scrap_txt.get_width() // 2, sy - scrap_txt.get_height() // 2))

            # Fleet frame: tile-wide selection frame.
            if selected_in_stack:
                pygame.draw.rect(self.screen, pal["tile_friend"], cell_rect, 1)
            elif enemy_selected_in_stack:
                pygame.draw.rect(self.screen, pal["tile_hostile"], cell_rect, 1)

            if len(mobiles_here) > 1:
                stack_text = self.small_font.render(f"x{len(mobiles_here)}", True, pal["stack_label"])
                self.screen.blit(stack_text, (cell_left + self.cell_size - 18, cell_top + self.cell_size - 14))

        self.draw_ui(game_state)
        pygame.display.flip()

    def draw_ui(self, game_state):
        pal = self._palette()
        board_px = self.cell_size * getattr(game_state, "board_size", 10)
        ui_top = board_px
        left_w = board_px // 2
        right_x = left_w
        right_w = board_px - left_w
        ui_bottom = ui_top + 200
        # Draw UI Backgrounds
        pygame.draw.rect(self.screen, pal["ui_left"], (0, ui_top, left_w, 200)) # Left Box
        pygame.draw.rect(self.screen, pal["ui_right"], (right_x, ui_top, right_w, 200)) # Right Box
        pygame.draw.line(self.screen, pal["ui_sep"], (0, ui_top), (board_px, ui_top), 2)
        pygame.draw.line(self.screen, pal["ui_sep"], (right_x, ui_top), (right_x, ui_bottom), 2)

        # Lower Left text box (Stats)
        selected_ship = next((s for s in game_state.all_ships if s.is_selected), None)
        enemy_ship = next((s for s in game_state.all_ships if s.is_enemy_selected), None)
        
        y_offset = ui_top + 10
        if selected_ship:
            stats = [
                f"Player Ship ID: {selected_ship.id} Type-{selected_ship.ship_type}",
                f"Health-{self._fmt(selected_ship.hp)} Dmg-{self._fmt(selected_ship.damage)} "
                f"Shots-{selected_ship.shots} "
                f"F{int(getattr(selected_ship, 'fighters', 0))} "
                f"B{int(getattr(selected_ship, 'bombers', 0))}",
                f"Pos=({selected_ship.x},{selected_ship.y}) Moved={selected_ship.has_moved} Budget-{self._fmt(getattr(selected_ship, 'move_budget_remaining', 0))}",
            ]
            if getattr(selected_ship, "is_base", False):
                stats.insert(2, f"Scrap-{self._fmt(selected_ship.scrap)} (bases earn +1/turn)")
            for line in stats:
                y_offset = self._render_wrapped(line, pal["text_friend"], 10, y_offset, left_w - 18, self.small_font)
                
        y_offset += 10
        if enemy_ship:
            distance = math.dist((selected_ship.x, selected_ship.y), (enemy_ship.x, enemy_ship.y)) if selected_ship else 0
            stats = [
                f"Enemy Ship ID: {enemy_ship.id} Type-{enemy_ship.ship_type}",
                f"Health-{self._fmt(enemy_ship.hp)} "
                f"F{int(getattr(enemy_ship, 'fighters', 0))} "
                f"B{int(getattr(enemy_ship, 'bombers', 0))}",
                f"Pos=({enemy_ship.x},{enemy_ship.y}) Dist={distance:.1f}",
            ]
            if getattr(enemy_ship, "is_base", False):
                stats.insert(2, f"Scrap-{self._fmt(enemy_ship.scrap)}")
            for line in stats:
                y_offset = self._render_wrapped(line, pal["text_hostile"], 10, y_offset, left_w - 18, self.small_font)

        # Lower Right text box (Log)
        y_offset = ui_top + 10
        for log_line in game_state.action_log[-14:]:
            y_offset = self._render_wrapped(log_line, pal["text_log"], right_x + 10, y_offset, right_w - 18, self.small_font)
            if y_offset > ui_bottom - 18:
                break

        # Controls footer
        if getattr(game_state, "game_over", False):
            controls = f"GAME OVER | Winner: Player {game_state.winner} | Press G for new match"
        else:
            controls = (
                f"Turn: P{game_state.active_player} | "
                "WASD move, V+WASD split, F fire, C charge, M/N stacks, "
                "B build, Z board look — O AI, R rewind, X end"
            )
        self._render_wrapped(controls, pal["text_muted"], 8, ui_bottom - 20, board_px - 8, self.small_font)

        tuning_status = "ON" if game_state.tuning_mode else "OFF"
        tuning_line = f"Tuning: {tuning_status} | T toggle | G new match ({'seeded' if game_state.tuning_mode else 'random'}) | 1–7 scenarios (7 = 5x5 vs AI)"
        tuning_color = pal["text_tuning_on"] if game_state.tuning_mode else pal["text_tuning_off"]
        self._render_wrapped(tuning_line, tuning_color, 8, ui_bottom - 36, board_px - 8, self.small_font)

        ai_status = "ON" if getattr(game_state, "ai_enabled", False) else "OFF"
        ai_line = f"AI P2: {ai_status}"
        if getattr(game_state, "ai_thinking", False):
            ai_line += " | Thinking..."
        ai_color = pal["text_ai_on"] if getattr(game_state, "ai_enabled", False) else pal["text_ai_off"]
        self._render_wrapped(ai_line, ai_color, 8, ui_bottom - 52, board_px - 8, self.small_font)

        if getattr(game_state, "game_over", False):
            overlay = pygame.Surface((420, 90), pygame.SRCALPHA)
            overlay.fill(pal["game_over_dark"])
            self.screen.blit(overlay, (40, 205))
            title = self.font.render(f"Player {game_state.winner} wins", True, pal["game_over_title"])
            subtitle = self.small_font.render("A base was destroyed. Press G to restart.", True, pal["game_over_sub"])
            self.screen.blit(title, (155, 228))
            self.screen.blit(subtitle, (95, 255))

        if getattr(game_state, "build_menu_open", False):
            overlay = pygame.Surface((480, 150), pygame.SRCALPHA)
            overlay.fill(pal["build_overlay"])
            self.screen.blit(overlay, (10, 330))
            anchor_id = getattr(game_state, "build_anchor_base_id", None)
            header = (
                next(
                    (
                        b
                        for b in game_state.all_ships
                        if b.id == anchor_id and getattr(b, "is_base", False)
                    ),
                    None,
                )
                if anchor_id is not None
                else None
            )
            if header is None:
                header = next(
                    (
                        b
                        for b in game_state.all_ships
                        if b.is_selected and getattr(b, "is_base", False)
                    ),
                    None,
                )
            title_col = pal["build_title"]
            if header:
                htxt = self.font.render(
                    f"BUILD at base {header.id}: scrap {self._fmt(header.scrap)} "
                    f"| keys 1-9 slot N, 0 slot 10",
                    True,
                    title_col,
                )
            else:
                htxt = self.font.render("BUILD (no base anchored — select a hull on-base)", True, title_col)
            self.screen.blit(htxt, (20, 335))
            yb = 360
            for idx, raw in enumerate(BUILD_MENU_ORDER, start=1):
                label = BUILD_MENU_LABELS.get(raw, raw)
                if raw == HANGAR_FIGHTER_KEY:
                    cost = SHIP_TEMPLATES["Fighter"]["cost"]
                elif raw == HANGAR_BOMBER_KEY:
                    cost = SHIP_TEMPLATES["Bomber"]["cost"]
                else:
                    cost = SHIP_TEMPLATES[raw]["cost"]
                afford = ""
                if header and header.scrap + 1e-9 >= cost:
                    afford = "+"
                key_hint = str(idx % 10) if idx >= 10 else str(idx)
                line = self.small_font.render(
                    f"#{idx} (key {key_hint}) {label} ({self._fmt(cost)}){afford}",
                    True,
                    pal["build_line"],
                )
                self.screen.blit(line, (22, yb))
                yb += 14
