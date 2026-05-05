import math
import pygame

from game_logic import BUILD_MENU_ORDER, SHIP_TEMPLATES

class Renderer:
    def __init__(self):
        pygame.init()
        # Pixelated retro look
        self.cell_size = 50
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

    def draw(self, game_state):
        self.screen.fill((10, 10, 20)) # Dark space background

        # Draw Grid & Planets
        for x in range(10):
            for y in range(10):
                rect = pygame.Rect(x * self.cell_size, y * self.cell_size, self.cell_size, self.cell_size)
                pygame.draw.rect(self.screen, (40, 40, 60), rect, 1)
        
        for px, py in game_state.planets:
            pygame.draw.circle(self.screen, (50, 200, 100), (px * self.cell_size + 25, py * self.cell_size + 25), 15)

        selected_ship = next((s for s in game_state.all_ships if s.is_selected), None)
        enemy_selected_ship = next((s for s in game_state.all_ships if s.is_enemy_selected), None)

        # Draw each fleet stack as one square (no visual offset).
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
            px = x * self.cell_size + 10
            py = y * self.cell_size + 10
            rect = pygame.Rect(px, py, 30, 30)
            selected_in_stack = selected_ship and any(s.id == selected_ship.id for s in stack_sorted)
            enemy_selected_in_stack = enemy_selected_ship and any(s.id == enemy_selected_ship.id for s in stack_sorted)

            if mobiles_here:
                pygame.draw.rect(self.screen, fleet_color, rect)
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
                self.screen.blit(air_txt, (px + 2, py - 12))

                # Show ship type number on tile.
                # If a ship in this stack is selected, show that selected ship's type id.
                # Otherwise show the first ship type id in stack.
                type_id = mobiles_here[0].ship_type_id
                if selected_in_stack and selected_ship and not getattr(selected_ship, "is_base", False):
                    type_id = selected_ship.ship_type_id
                elif enemy_selected_in_stack and enemy_selected_ship and not getattr(enemy_selected_ship, "is_base", False):
                    type_id = enemy_selected_ship.ship_type_id

                type_id_text = self.font.render(str(type_id), True, (255, 255, 255))
                self.screen.blit(type_id_text, (px + 10, py + 5))

            elif bases_here:
                pygame.draw.rect(self.screen, base_tile_color, rect)
                scrap_only = self.font.render(self._fmt(bases_here[0].scrap), True, (255, 245, 200))
                self.screen.blit(scrap_only, (px + 6, py + 6))

            if mobiles_here and bases_here:
                scrap_txt = self.small_font.render(self._fmt(bases_here[0].scrap), True, (255, 245, 200))
                self.screen.blit(scrap_txt, (px + 2, py + 18))

            if selected_in_stack:
                pygame.draw.rect(self.screen, (170, 255, 255), rect, 3)
            elif enemy_selected_in_stack:
                pygame.draw.rect(self.screen, (255, 255, 170), rect, 3)

            if len(mobiles_here) > 1:
                stack_text = self.small_font.render(f"x{len(mobiles_here)}", True, (230, 230, 230))
                self.screen.blit(stack_text, (px + 13, py + 18))

        self.draw_ui(game_state)
        pygame.display.flip()

    def draw_ui(self, game_state):
        # Draw UI Backgrounds
        pygame.draw.rect(self.screen, (20, 20, 20), (0, 500, 250, 200)) # Left Box
        pygame.draw.rect(self.screen, (30, 30, 30), (250, 500, 250, 200)) # Right Box
        pygame.draw.line(self.screen, (255, 255, 255), (0, 500), (500, 500), 2)
        pygame.draw.line(self.screen, (255, 255, 255), (250, 500), (250, 700), 2)

        # Lower Left text box (Stats)
        selected_ship = next((s for s in game_state.all_ships if s.is_selected), None)
        enemy_ship = next((s for s in game_state.all_ships if s.is_enemy_selected), None)
        
        y_offset = 510
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
                y_offset = self._render_wrapped(line, (100, 255, 255), 10, y_offset, 232, self.small_font)
                
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
                y_offset = self._render_wrapped(line, (255, 255, 100), 10, y_offset, 232, self.small_font)

        # Lower Right text box (Log)
        y_offset = 510
        for log_line in game_state.action_log[-8:]:
            y_offset = self._render_wrapped(log_line, (200, 200, 200), 260, y_offset, 232, self.small_font)
            if y_offset > 682:
                break

        # Controls footer
        controls = (
            f"Turn: P{game_state.active_player} | "
            "WASD move, V+WASD split move, F fire, C charge, M/N cycle stack, R undo, RRR reset turn, X end turn"
        )
        self._render_wrapped(controls, (180, 180, 180), 8, 680, 492, self.small_font)

        tuning_status = "ON" if game_state.tuning_mode else "OFF"
        tuning_line = f"Tuning: {tuning_status} | T toggle | G new match ({'seeded' if game_state.tuning_mode else 'random'}) | 1/2/3/4/5/6 scenarios"
        tuning_color = (120, 255, 120) if game_state.tuning_mode else (160, 160, 160)
        self._render_wrapped(tuning_line, tuning_color, 8, 664, 492, self.small_font)

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
            for idx, typename in enumerate(BUILD_MENU_ORDER, start=1):
                cost = SHIP_TEMPLATES[typename]["cost"]
                afford = ""
                if header and header.scrap + 1e-9 >= cost:
                    afford = "+"
                key_hint = str(idx % 10) if idx >= 10 else str(idx)
                line = self.small_font.render(
                    f"#{idx} (key {key_hint}) {typename} ({self._fmt(cost)}){afford}",
                    True,
                    (200, 235, 200),
                )
                self.screen.blit(line, (22, yb))
                yb += 14
