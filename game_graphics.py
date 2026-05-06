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

class Renderer:
    def __init__(self):
        pygame.init()
        # Pixelated retro look
        self.cell_size = 60
        self.width = self.cell_size * 10
        self.height = (self.cell_size * 10) + 200 # Extra space for textboxes
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Starfleet Command")
        self.font = pygame.font.SysFont("courier", 14, bold=True) # Monospace retro font
        self.small_font = pygame.font.SysFont("courier", 12)

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

    def _draw_diagonal_stripes(self, rect, stripe_color=(60, 60, 60), gap=4):
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
        self.screen.fill((10, 10, 20)) # Dark space background

        # Draw Grid & Planets
        bs = getattr(game_state, "board_size", 10)
        half = self.cell_size // 2
        pr = min(15, max(8, half - 5))
        for x in range(bs):
            for y in range(bs):
                rect = pygame.Rect(x * self.cell_size, y * self.cell_size, self.cell_size, self.cell_size)
                pygame.draw.rect(self.screen, (40, 40, 60), rect, 1)

        for px, py in game_state.planets:
            pygame.draw.circle(
                self.screen,
                (50, 200, 100),
                (px * self.cell_size + half, py * self.cell_size + half),
                pr,
            )

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
            fleet_color = (50, 100, 255) if owner == 1 else (255, 50, 50)
            base_tile_color = (140, 100, 50) if owner == 1 else (160, 70, 50)
            border_color = (110, 170, 255) if owner == 1 else (255, 110, 110)
            cell_left = x * self.cell_size
            cell_top = y * self.cell_size
            cell_rect = pygame.Rect(cell_left, cell_top, self.cell_size, self.cell_size)
            selected_in_stack = selected_ship and any(s.id == selected_ship.id for s in stack_sorted)
            enemy_selected_in_stack = enemy_selected_ship and any(s.id == enemy_selected_ship.id for s in stack_sorted)
            # Base is drawn as a small circle in the rear corner of the tile
            # so it never fully covers a planet glyph behind it.
            # Rear corner: P1 bases anchor top-left; P2 bases anchor bottom-right.
            if bases_here:
                br = max(7, self.cell_size // 8)
                if owner == 1:
                    bcx = cell_left + br + 3
                    bcy = cell_top + br + 3
                else:
                    bcx = cell_left + self.cell_size - br - 3
                    bcy = cell_top + self.cell_size - br - 3
                base_border = (180, 140, 70) if owner == 1 else (200, 100, 70)
                pygame.draw.circle(self.screen, base_tile_color, (bcx, bcy), br)
                pygame.draw.circle(self.screen, base_border, (bcx, bcy), br, 2)
                if not mobiles_here:
                    scrap_surf = self.small_font.render(self._fmt(bases_here[0].scrap), True, (255, 245, 200))
                    self.screen.blit(scrap_surf, (bcx - scrap_surf.get_width() // 2, bcy - scrap_surf.get_height() // 2))

            if mobiles_here:
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
                cap_band_y  = center_y + front_dir * 13
                esc_band_y  = center_y + front_dir * 0
                ftr_band_y  = center_y - front_dir * 11
                bmb_band_y  = center_y - front_dir * 20

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
                    pygame.draw.rect(self.screen, fleet_color, r)
                    if light:
                        self._draw_diagonal_stripes(r)
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
                    pygame.draw.rect(self.screen, fleet_color, r)
                    if light:
                        self._draw_diagonal_stripes(r)
                    pygame.draw.rect(self.screen, border_color, r, 1)
                    shape_bounds[ship.id] = ("rect", r)

                # --- Aircraft: drawn from hangar counts on all stack ships ---
                # Fighter/Bomber hull ships (aircraft_counters_here) contribute
                # their own fighters/bombers; capital ships contribute via attributes.
                all_stack = mobiles_here + aircraft_counters_here
                fighter_count = sum(getattr(s, "fighters", 0) for s in all_stack)
                bomber_count = sum(getattr(s, "bombers", 0) for s in all_stack)
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
                                self._clamp_point_to_cell(cx, cy - TRI_SZ, cell_rect),
                                self._clamp_point_to_cell(cx - TRI_SZ, cy + TRI_SZ, cell_rect),
                                self._clamp_point_to_cell(cx + TRI_SZ, cy + TRI_SZ, cell_rect),
                            ]
                        else:
                            pts = [
                                self._clamp_point_to_cell(cx, cy + TRI_SZ, cell_rect),
                                self._clamp_point_to_cell(cx - TRI_SZ, cy - TRI_SZ, cell_rect),
                                self._clamp_point_to_cell(cx + TRI_SZ, cy - TRI_SZ, cell_rect),
                            ]
                        fill = (210, 210, 210) if is_fighter else (60, 60, 60)
                        pygame.draw.polygon(self.screen, fill, pts)
                        pygame.draw.polygon(self.screen, border_color, pts, 1)

                _draw_air_row(fighter_count, ftr_band_y, True)
                _draw_air_row(bomber_count, bmb_band_y, False)

                # Always show total aircraft for the whole fleet stack.
                contributors = mobiles_here + aircraft_counters_here

                def avail(ship, kind):
                    total = getattr(ship, kind, 0)
                    used = getattr(ship, f"{kind}_used_this_turn", 0)
                    return max(0, total - used)

                f_total = sum(getattr(s, "fighters", 0) for s in contributors)
                b_total = sum(getattr(s, "bombers", 0) for s in contributors)
                f_avail = sum(avail(s, "fighters") for s in contributors)
                b_avail = sum(avail(s, "bombers") for s in contributors)

                air_txt = self.small_font.render(
                    f"{self._fmt(f_avail)}/{self._fmt(f_total)}"
                    f"|{self._fmt(b_avail)}/{self._fmt(b_total)}",
                    True,
                    (230, 230, 230),
                )
                self.screen.blit(air_txt, (cell_left + 2, cell_top - 12))

                # Show ship type number on tile.
                # If a ship in this stack is selected, show that selected ship's type id.
                # Otherwise show the first ship type id in stack.
                type_id = mobiles_here[0].ship_type_id
                if selected_in_stack and selected_ship and not getattr(selected_ship, "is_base", False):
                    type_id = selected_ship.ship_type_id
                elif enemy_selected_in_stack and enemy_selected_ship and not getattr(enemy_selected_ship, "is_base", False):
                    type_id = enemy_selected_ship.ship_type_id

                type_id_text = self.font.render(str(type_id), True, (255, 255, 255))
                self.screen.blit(type_id_text, (cell_left + 2, cell_top + 2))

                # Unit frame: shape-specific outline around selected unit.
                selected_unit = selected_ship if selected_in_stack else enemy_selected_ship if enemy_selected_in_stack else None
                if selected_unit is not None and selected_unit.id in shape_bounds:
                    kind, geom = shape_bounds[selected_unit.id]
                    frame_color = (170, 255, 255) if selected_in_stack else (255, 255, 120)
                    if kind == "rect":
                        outline = self._clamp_rect_to_cell(geom.inflate(4, 4), cell_rect)
                        pygame.draw.rect(self.screen, frame_color, outline, 2)
                    else:
                        pygame.draw.polygon(self.screen, frame_color, geom, 2)

            if mobiles_here and bases_here:
                scrap_txt = self.small_font.render(self._fmt(bases_here[0].scrap), True, (255, 245, 200))
                br = max(7, self.cell_size // 8)
                if owner == 1:
                    sx, sy = cell_left + br + 3, cell_top + br + 3
                else:
                    sx, sy = cell_left + self.cell_size - br - 3, cell_top + self.cell_size - br - 3
                self.screen.blit(scrap_txt, (sx - scrap_txt.get_width() // 2, sy - scrap_txt.get_height() // 2))

            # Fleet frame: tile-wide selection frame.
            if selected_in_stack:
                pygame.draw.rect(self.screen, (120, 220, 255), cell_rect, 1)
            elif enemy_selected_in_stack:
                pygame.draw.rect(self.screen, (255, 240, 120), cell_rect, 1)

            if len(mobiles_here) > 1:
                stack_text = self.small_font.render(f"x{len(mobiles_here)}", True, (230, 230, 230))
                self.screen.blit(stack_text, (cell_left + self.cell_size - 18, cell_top + self.cell_size - 14))

        self.draw_ui(game_state)
        pygame.display.flip()

    def draw_ui(self, game_state):
        board_px = self.cell_size * getattr(game_state, "board_size", 10)
        ui_top = board_px
        left_w = board_px // 2
        right_x = left_w
        right_w = board_px - left_w
        ui_bottom = ui_top + 200
        # Draw UI Backgrounds
        pygame.draw.rect(self.screen, (20, 20, 20), (0, ui_top, left_w, 200)) # Left Box
        pygame.draw.rect(self.screen, (30, 30, 30), (right_x, ui_top, right_w, 200)) # Right Box
        pygame.draw.line(self.screen, (255, 255, 255), (0, ui_top), (board_px, ui_top), 2)
        pygame.draw.line(self.screen, (255, 255, 255), (right_x, ui_top), (right_x, ui_bottom), 2)

        # Lower Left text box (Stats)
        selected_ship = next((s for s in game_state.all_ships if s.is_selected), None)
        enemy_ship = next((s for s in game_state.all_ships if s.is_enemy_selected), None)
        
        y_offset = ui_top + 10
        if selected_ship:
            stats = [
                f"Player Ship ID: {selected_ship.id} Type-{selected_ship.ship_type}",
                f"Health-{self._fmt(selected_ship.hp)} Dmg-{self._fmt(selected_ship.damage)} "
                f"Shots-{selected_ship.shots} Air-{self._fmt(selected_ship.aircraft_storage)}",
                f"Pos=({selected_ship.x},{selected_ship.y}) Moved={selected_ship.has_moved} Budget-{self._fmt(getattr(selected_ship, 'move_budget_remaining', 0))}",
            ]
            if getattr(selected_ship, "is_base", False):
                stats.insert(2, f"Scrap-{self._fmt(selected_ship.scrap)} (bases earn +1/turn)")
            for line in stats:
                y_offset = self._render_wrapped(line, (100, 255, 255), 10, y_offset, left_w - 18, self.small_font)
                
        y_offset += 10
        if enemy_ship:
            distance = math.dist((selected_ship.x, selected_ship.y), (enemy_ship.x, enemy_ship.y)) if selected_ship else 0
            stats = [
                f"Enemy Ship ID: {enemy_ship.id} Type-{enemy_ship.ship_type}",
                f"Health-{self._fmt(enemy_ship.hp)} Air-{self._fmt(enemy_ship.aircraft_storage)}",
                f"Pos=({enemy_ship.x},{enemy_ship.y}) Dist={distance:.1f}",
            ]
            if getattr(enemy_ship, "is_base", False):
                stats.insert(2, f"Scrap-{self._fmt(enemy_ship.scrap)}")
            for line in stats:
                y_offset = self._render_wrapped(line, (255, 255, 100), 10, y_offset, left_w - 18, self.small_font)

        # Lower Right text box (Log)
        y_offset = ui_top + 10
        for log_line in game_state.action_log[-8:]:
            y_offset = self._render_wrapped(log_line, (200, 200, 200), right_x + 10, y_offset, right_w - 18, self.small_font)
            if y_offset > ui_bottom - 18:
                break

        # Controls footer
        if getattr(game_state, "game_over", False):
            controls = f"GAME OVER | Winner: Player {game_state.winner} | Press G for new match"
        else:
            controls = (
                f"Turn: P{game_state.active_player} | "
                "WASD move, V+WASD split move, F fire, C charge, M/N cycle stack, O AI toggle, R reset turn, X end turn"
            )
        self._render_wrapped(controls, (180, 180, 180), 8, ui_bottom - 20, board_px - 8, self.small_font)

        tuning_status = "ON" if game_state.tuning_mode else "OFF"
        tuning_line = f"Tuning: {tuning_status} | T toggle | G new match ({'seeded' if game_state.tuning_mode else 'random'}) | 1–7 scenarios (7 = 5x5 vs AI)"
        tuning_color = (120, 255, 120) if game_state.tuning_mode else (160, 160, 160)
        self._render_wrapped(tuning_line, tuning_color, 8, ui_bottom - 36, board_px - 8, self.small_font)

        ai_status = "ON" if getattr(game_state, "ai_enabled", False) else "OFF"
        ai_line = f"AI P2: {ai_status}"
        if getattr(game_state, "ai_thinking", False):
            ai_line += " | Thinking..."
        ai_color = (255, 200, 120) if getattr(game_state, "ai_enabled", False) else (140, 140, 140)
        self._render_wrapped(ai_line, ai_color, 8, ui_bottom - 52, board_px - 8, self.small_font)

        if getattr(game_state, "game_over", False):
            overlay = pygame.Surface((420, 90), pygame.SRCALPHA)
            overlay.fill((18, 8, 8, 230))
            self.screen.blit(overlay, (40, 205))
            title = self.font.render(f"Player {game_state.winner} wins", True, (255, 210, 160))
            subtitle = self.small_font.render("A base was destroyed. Press G to restart.", True, (240, 240, 240))
            self.screen.blit(title, (155, 228))
            self.screen.blit(subtitle, (95, 255))

        if getattr(game_state, "build_menu_open", False):
            overlay = pygame.Surface((480, 150), pygame.SRCALPHA)
            overlay.fill((10, 10, 22, 220))
            self.screen.blit(overlay, (10, 330))
            header = next(
                (
                    b for b in game_state.all_ships
                    if b.is_selected and getattr(b, "is_base", False)
                ),
                None,
            )
            title_col = (220, 220, 150)
            if header:
                htxt = self.font.render(
                    f"BUILD scrap {self._fmt(header.scrap)} | keys 1-9 slot N, 0 slot 10",
                    True,
                    title_col,
                )
            else:
                htxt = self.font.render("BUILD (select a base)", True, title_col)
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
                    (200, 235, 200),
                )
                self.screen.blit(line, (22, yb))
                yb += 14
