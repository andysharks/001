import pygame
import sys
from game_logic import GameState
from game_graphics import Renderer

def main():
    game = GameState()
    renderer = Renderer()
    clock = pygame.time.Clock()
    
    prev_key = None
    awaiting_split_move = False
    awaiting_hyperdrive = False

    game.reset_match(deterministic=False)

    # Start Main Game Loop (Repeat Forever)
    while True:
        # 1. Processing time Input
        # 1. Processing time Input
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1: # Left click
                    # Space mode: map click to board cells.
                    x, y = event.pos[0] // 50, event.pos[1] // 50
                    if not (0 <= x < 10 and 0 <= y < 10):
                        continue
                    game.handle_space_click(x, y)

            if event.type == pygame.KEYDOWN:
                char = event.unicode.lower()
                
                if char == 'x':
                    game.switch_turns()
                    prev_key = None
                    awaiting_split_move = False
                    awaiting_hyperdrive = False
                elif char == 't':
                    game.toggle_tuning_mode()
                elif char == 'g':
                    game.reset_match(deterministic=game.tuning_mode)
                    prev_key = None
                    awaiting_split_move = False
                elif game.build_menu_open and char in "1234567890":
                    slot = 10 if char == "0" else int(char)
                    game.try_build_ship(slot)
                elif char in ['1', '2', '3', '4', '5', '6'] and game.tuning_mode and not game.build_menu_open:
                    game.load_tuning_scenario(int(char))
                    prev_key = None
                    awaiting_split_move = False
                elif char == 'b':
                    game.toggle_build_menu()
                elif char == 'v':
                    awaiting_split_move = True
                    awaiting_hyperdrive = False
                    game.action_log = ["V mode armed: press WASD to move only the selected ship and defleet."]
                elif char == 'c':
                    awaiting_split_move = False
                    ship = next((s for s in game.all_ships if s.is_selected), None)
                    if ship:
                        awaiting_hyperdrive = game.handle_c_press(ship)
                    else:
                        awaiting_hyperdrive = False
                        game.action_log = [f"Select a Player {game.active_player} ship first."]
                elif char == 'r':
                    game.reset_to_turn_start()
                        
                elif char == 'm':
                    # Cycle through Player fleet
                    ship = next((s for s in game.all_ships if s.is_selected), None)
                    if ship:
                        fleet = sorted(
                            [s for s in game.all_ships if s.x == ship.x and s.y == ship.y and s.owner == ship.owner],
                            key=lambda v: (1 if getattr(v, "is_base", False) else 0, v.id),
                        )
                        if len(fleet) > 1:
                            idx = fleet.index(ship)
                            ship.is_selected = False
                            fleet[(idx + 1) % len(fleet)].is_selected = True
                            
                elif char == 'n':
                    # Cycle through Enemy fleet
                    target = next((s for s in game.all_ships if s.is_enemy_selected), None)
                    if target:
                        fleet = sorted(
                            [s for s in game.all_ships if s.x == target.x and s.y == target.y and s.owner == target.owner],
                            key=lambda v: (1 if getattr(v, "is_base", False) else 0, v.id),
                        )
                        if len(fleet) > 1:
                            idx = fleet.index(target)
                            target.is_enemy_selected = False
                            fleet[(idx + 1) % len(fleet)].is_enemy_selected = True

                elif char in ['w', 'a', 's', 'd', 'f']:
                    ship = next((s for s in game.all_ships if s.is_selected), None)
                    target = next((s for s in game.all_ships if s.is_enemy_selected), None)
                    if ship:
                        is_movement_key = char in ['w', 'a', 's', 'd']
                        ship_charged = getattr(ship, "is_charged", False) and not getattr(ship, "is_base", False)
                        if awaiting_split_move and is_movement_key:
                            game.break_fleet_move(ship, char)
                            awaiting_split_move = False
                        elif is_movement_key and (awaiting_hyperdrive or ship_charged):
                            game.hyperdrive_move(ship, char)
                            awaiting_hyperdrive = False
                        else:
                            game.update_stats(ship, target, char, prev_key)
                    else:
                        game.action_log = [f"Select a Player {game.active_player} ship first."]
                        awaiting_split_move = False
                        awaiting_hyperdrive = False
                
                prev_key = char
        renderer.draw(game)
        clock.tick(30)

if __name__ == "__main__":
    main()
