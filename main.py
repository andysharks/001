import argparse
import pygame
import sys
from game_ai import AIController
from game_logic import GameState
from game_graphics import Renderer, VISUAL_THEME_COUNT
from eval_weights import load_eval_weights_file

def main():
    parser = argparse.ArgumentParser(description="Naval tactical game UI")
    parser.add_argument(
        "--eval-weights",
        default=None,
        metavar="PATH",
        help="JSON file with eval_weights (merged atop defaults and config/eval_weights.default.json).",
    )
    argv = [a for a in sys.argv[1:] if not a.startswith("-psn")]  # macOS Finder
    args, pygame_argv = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + pygame_argv

    eval_w = load_eval_weights_file(args.eval_weights)
    game = GameState()
    renderer = Renderer()
    clock = pygame.time.Clock()
    ai = AIController(owner=2, depth=4, min_depth=3, eval_weights_overlay=eval_w)
    ai_enabled = False
    ai_step_timer_ms = 0
    ai_step_delay_ms = 250
    
    prev_key = None
    awaiting_split_move = False
    awaiting_hyperdrive = False

    game.reset_match(deterministic=False)
    game.ai_enabled = ai_enabled
    game.ai_thinking = False

    # Start Main Game Loop (Repeat Forever)
    while True:
        ai_turn_active = ai_enabled and game.active_player == 2 and not game.game_over
        game.ai_enabled = ai_enabled
        game.ai_thinking = ai.is_thinking

        if ai_turn_active:
            if not ai.has_plan():
                ai.compute_plan(game)
                game.ai_thinking = ai.is_thinking
            now = pygame.time.get_ticks()
            if now - ai_step_timer_ms >= ai_step_delay_ms:
                still_running = ai.step(game)
                ai_step_timer_ms = now
                if not still_running:
                    ai.clear_plan()
                    game.switch_turns()
            ai_turn_active = ai_enabled and game.active_player == 2

        # 1. Processing time Input
        # 1. Processing time Input
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            if event.type == pygame.MOUSEBUTTONDOWN:
                if ai_turn_active:
                    continue
                if event.button == 1: # Left click
                    # Space mode: map click to board cells.
                    cell = renderer.cell_size
                    x, y = event.pos[0] // cell, event.pos[1] // cell
                    bs = game.board_size
                    if not (0 <= x < bs and 0 <= y < bs):
                        continue
                    game.handle_space_click(x, y)

            if event.type == pygame.KEYDOWN:
                char = event.unicode.lower()

                if char == "z":
                    renderer.cycle_board_visual_theme()
                    game.action_log.append(
                        f"Board look ({renderer.board_visual_theme + 1}/{VISUAL_THEME_COUNT}): "
                        f"{renderer.visual_theme_name}"
                    )

                elif game.game_over and char != 'g':
                    game.action_log = [f"Game over. Player {game.winner} wins. Press G for new match."]
                elif char == 'o':
                    ai_enabled = not ai_enabled
                    game.ai_enabled = ai_enabled
                    if not ai_enabled:
                        ai.clear_plan()
                        game.ai_thinking = False
                    game.action_log = [f"AI for P2: {'ON' if ai_enabled else 'OFF'}"]
                elif char == 'x':
                    if ai_turn_active:
                        ai.clear_plan()
                    game.switch_turns()
                    prev_key = None
                    awaiting_split_move = False
                    awaiting_hyperdrive = False
                elif char == 't':
                    if ai_turn_active:
                        continue
                    game.toggle_tuning_mode()
                elif char == 'g':
                    ai.clear_plan()
                    game.reset_match(deterministic=game.tuning_mode)
                    prev_key = None
                    awaiting_split_move = False
                    awaiting_hyperdrive = False
                elif game.build_menu_open and char in "1234567890":
                    if ai_turn_active:
                        continue
                    slot = 10 if char == "0" else int(char)
                    game.try_build_ship(slot)
                elif char in ['1', '2', '3', '4', '5', '6', '7'] and game.tuning_mode and not game.build_menu_open:
                    if ai_turn_active:
                        continue
                    sid = int(char)
                    ai.clear_plan()
                    game.load_tuning_scenario(sid)
                    if sid == 7:
                        ai_enabled = True
                        game.ai_enabled = True
                    prev_key = None
                    awaiting_split_move = False
                    awaiting_hyperdrive = False
                elif char == 'b':
                    if ai_turn_active:
                        continue
                    game.toggle_build_menu()
                elif char == 'v':
                    if ai_turn_active:
                        continue
                    awaiting_split_move = True
                    awaiting_hyperdrive = False
                    game.action_log = ["V mode armed: press WASD to move only the selected ship and defleet."]
                elif char == 'c':
                    if ai_turn_active:
                        continue
                    awaiting_split_move = False
                    ship = next((s for s in game.all_ships if s.is_selected), None)
                    if ship:
                        awaiting_hyperdrive = game.handle_c_press(ship)
                    else:
                        awaiting_hyperdrive = False
                        game.action_log = [f"Select a Player {game.active_player} ship first."]
                elif char == 'r':
                    ai.clear_plan()
                    game.reset_to_turn_start()
                elif char == 'm':
                    if ai_turn_active:
                        continue
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
                    if ai_turn_active:
                        continue
                    # Cycle through Enemy fleet
                    target = next((s for s in game.all_ships if s.is_enemy_selected), None)
                    if target:
                        fleet = sorted(
                            [
                                s for s in game.all_ships
                                if s.x == target.x
                                and s.y == target.y
                                and s.owner == target.owner
                                and (not getattr(s, "is_base", False) or game.can_target_ship(s))
                            ],
                            key=lambda v: (1 if getattr(v, "is_base", False) else 0, v.id),
                        )
                        if target not in fleet:
                            for s in game.all_ships:
                                s.is_enemy_selected = False
                            if fleet:
                                fleet[0].is_enemy_selected = True
                        elif len(fleet) > 1:
                            idx = fleet.index(target)
                            target.is_enemy_selected = False
                            fleet[(idx + 1) % len(fleet)].is_enemy_selected = True

                elif char in ['w', 'a', 's', 'd', 'f']:
                    if ai_turn_active:
                        continue
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
