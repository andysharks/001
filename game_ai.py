import copy
import math
import time

from game_logic import (
    BUILD_MENU_ORDER,
    LIGHT_SHIP_TYPES,
    SHIP_TEMPLATES,
    evaluate_board,
    is_base_guarded,
    manhattan_distance,
    mobile_ships_at,
)


class AIController:
    QUICK_BUDGET_MS = 200
    QUIET_BUDGET_MS = 500
    MODERATE_BUDGET_MS = 1200
    DECISIVE_BUDGET_MS = 2500
    BUDGET_CEILING_MS = 4000
    BUDGET_FLOOR_MS = 200
    MODERATE_SWING_THRESHOLD = 20.0
    DECISIVE_SWING_THRESHOLD = 60.0
    KILL_SWING_BONUS = 10.0

    def __init__(
        self,
        owner=2,
        depth=2,
        top_k_turns=4,
        max_actions_per_turn=12,
        time_budget_ms=600,
    ):
        self.owner = owner
        self.depth = depth
        self.top_k_turns = top_k_turns
        self.max_actions_per_turn = max_actions_per_turn
        self.time_budget_ms = time_budget_ms
        self.default_time_budget_ms = time_budget_ms
        self.max_branch_actions = max(8, top_k_turns * 2)
        self.queued_plan = []
        self.is_thinking = False

    def has_plan(self):
        return bool(self.queued_plan)

    def clear_plan(self):
        self.queued_plan = []
        self.is_thinking = False

    def compute_plan(self, game):
        self.is_thinking = True
        self.queued_plan = self.pick_best_turn(game)
        self.is_thinking = False

    def pick_best_turn(self, game):
        if game.active_player != self.owner:
            return []
        root = self._clone_for_search(game)
        priority_plan = self._find_hyperdrive_base_assault_plan(root)
        if priority_plan:
            return priority_plan

        quick_plan, swing = self._quick_decisive_check(root)
        if quick_plan is not None:
            return self._finalize_plan(quick_plan)

        self.time_budget_ms = self._budget_for_swing(swing)
        search_start = time.monotonic()
        _, best_plan = self._negamax(
            root,
            self.depth,
            float("-inf"),
            float("inf"),
            self.owner,
            search_start,
        )
        self.time_budget_ms = self.default_time_budget_ms
        if not best_plan:
            return [("end",)]
        return self._finalize_plan(best_plan)

    def _finalize_plan(self, plan):
        if not plan:
            return [("end",)]
        if plan[-1][0] != "end":
            plan = list(plan) + [("end",)]
        return plan

    def _quick_decisive_check(self, game):
        """Run a fast depth-1 sweep; return a decisive plan if found, else (None, swing).

        A plan is decisive if it wins the game outright or destroys an enemy ship/base
        (the latter only when it also clearly improves our score).
        """
        saved_budget = self.time_budget_ms
        self.time_budget_ms = self.QUICK_BUDGET_MS
        scan_start = time.monotonic()
        try:
            candidates = self.enumerate_candidate_turns(
                game, self.owner, scan_start, top_k=4
            )
        finally:
            self.time_budget_ms = saved_budget

        if not candidates:
            return None, 0.0

        current_score = self._owner_score(game, self.owner)
        best = candidates[0]
        best_state = best["state"]
        best_score = best["score"]

        winning_candidates = [
            c for c in candidates
            if getattr(c["state"], "game_over", False)
            and getattr(c["state"], "winner", None) == self.owner
        ]
        if winning_candidates:
            winning_candidates.sort(key=lambda c: len(c["plan"]))
            return winning_candidates[0]["plan"], 0.0

        enemy_ids_before = {
            s.id for s in game.all_ships
            if s.owner != self.owner and not getattr(s, "is_aircraft_counter", False)
        }

        kill_candidates = []
        for candidate in candidates:
            ids_after = {
                s.id for s in candidate["state"].all_ships
                if s.owner != self.owner and not getattr(s, "is_aircraft_counter", False)
            }
            killed_ids = enemy_ids_before - ids_after
            if not killed_ids:
                continue
            killed_ships = [s for s in game.all_ships if s.id in killed_ids]
            kills_base = any(getattr(s, "is_base", False) for s in killed_ships)
            score_swing = candidate["score"] - current_score
            if kills_base or score_swing > self.KILL_SWING_BONUS:
                kill_candidates.append((len(candidate["plan"]), -candidate["score"], candidate["plan"]))

        if kill_candidates:
            kill_candidates.sort()
            return kill_candidates[0][2], 0.0

        return None, best_score - current_score

    def _budget_for_swing(self, swing):
        abs_swing = abs(swing)
        if abs_swing > self.DECISIVE_SWING_THRESHOLD:
            budget = self.DECISIVE_BUDGET_MS
        elif abs_swing > self.MODERATE_SWING_THRESHOLD:
            budget = self.MODERATE_BUDGET_MS
        else:
            budget = self.QUIET_BUDGET_MS
        return max(self.BUDGET_FLOOR_MS, min(self.BUDGET_CEILING_MS, budget))

    def step(self, game):
        if not self.queued_plan:
            return False
        action = self.queued_plan.pop(0)
        if action[0] == "end":
            return False
        self.apply_action(game, action, simulate=False)
        return bool(self.queued_plan)

    def apply_action(self, game, action, simulate=True):
        before_sig = self._state_signature(game)
        kind = action[0]

        if kind == "end":
            game.switch_turns()
            if simulate:
                game.state_history = []
            return True

        if kind in {"move", "vmove", "hyper", "charge", "fire"}:
            ship = self._ship_by_id(game, action[1])
            if ship is None:
                return False
            self._set_selected(game, ship.id, False)

        if kind == "move":
            ship = self._ship_by_id(game, action[1])
            game.update_stats(ship, None, action[2], None)
        elif kind == "vmove":
            ship = self._ship_by_id(game, action[1])
            game.break_fleet_move(ship, action[2])
        elif kind == "hyper":
            ship = self._ship_by_id(game, action[1])
            game.hyperdrive_move(ship, action[2])
        elif kind == "charge":
            ship = self._ship_by_id(game, action[1])
            game.handle_c_press(ship)
        elif kind == "fire":
            ship = self._ship_by_id(game, action[1])
            target = self._ship_by_id(game, action[2])
            if target is None:
                return False
            self._set_selected(game, target.id, True)
            game.update_stats(ship, target, "f", None)
        elif kind == "build":
            base = self._ship_by_id(game, action[1])
            if base is None:
                return False
            game.build_menu_open = False
            self._set_selected(game, base.id, False)
            game.toggle_build_menu()
            game.try_build_ship(action[2])
        else:
            return False

        if simulate:
            game.state_history = []
        return self._state_signature(game) != before_sig

    def enumerate_candidate_turns(self, game, owner, start_time, top_k=None):
        limit = top_k or self.top_k_turns
        beam = [
            {
                "plan": [],
                "state": self._clone_for_search(game),
                "ended": False,
                "cumulative_bonus": 0.0,
                "score": self._owner_score(game, owner),
            }
        ]

        for _ in range(self.max_actions_per_turn):
            if self._time_exceeded(start_time):
                break

            next_beam = []
            all_ended = True
            for node in beam:
                if node["ended"]:
                    next_beam.append(node)
                    continue

                all_ended = False
                actions = self.enumerate_atomic_actions(node["state"], owner)
                expansions = []
                for action in actions:
                    if self._time_exceeded(start_time):
                        break
                    sim = self._clone_for_search(node["state"])
                    if not self.apply_action(sim, action, simulate=True):
                        continue
                    ended = action[0] == "end"
                    bonus = self._action_bonus(node["state"], sim, action, owner)
                    cumulative = node.get("cumulative_bonus", 0.0) + bonus
                    expansions.append(
                        {
                            "plan": node["plan"] + [action],
                            "state": sim,
                            "ended": ended,
                            "cumulative_bonus": cumulative,
                            "score": self._owner_score(sim, owner) + cumulative,
                        }
                    )

                if not expansions:
                    fallback = self._clone_for_search(node["state"])
                    self.apply_action(fallback, ("end",), simulate=True)
                    next_beam.append(
                        {
                            "plan": node["plan"] + [("end",)],
                            "state": fallback,
                            "ended": True,
                            "cumulative_bonus": node.get("cumulative_bonus", 0.0),
                            "score": self._owner_score(fallback, owner)
                            + node.get("cumulative_bonus", 0.0),
                        }
                    )
                    continue

                expansions.sort(key=lambda item: (-item["score"], len(item["plan"])))
                next_beam.extend(expansions[: self.max_branch_actions])

            if not next_beam:
                break

            beam = self._dedupe_and_trim(next_beam, limit)
            if all_ended:
                break

        finalized = []
        for node in beam:
            if node["ended"]:
                finalized.append(node)
                continue
            sim = self._clone_for_search(node["state"])
            self.apply_action(sim, ("end",), simulate=True)
            finalized.append(
                {
                    "plan": node["plan"] + [("end",)],
                    "state": sim,
                    "ended": True,
                    "cumulative_bonus": node.get("cumulative_bonus", 0.0),
                    "score": self._owner_score(sim, owner)
                    + node.get("cumulative_bonus", 0.0),
                }
            )

        finalized.sort(key=lambda item: (-item["score"], len(item["plan"])))
        return finalized[:limit]

    def enumerate_atomic_actions(self, game, owner):
        actions = []
        enemy_targets = sorted(
            [
                s
                for s in game.all_ships
                if s.owner != owner
                and not getattr(s, "is_aircraft_counter", False)
                and game.can_target_ship(s)
            ],
            key=lambda s: (0 if getattr(s, "is_base", False) else 1, s.hp, s.id),
        )

        owned_ships = sorted(
            [s for s in game.all_ships if s.owner == owner],
            key=lambda s: (1 if getattr(s, "is_base", False) else 0, s.id),
        )

        for ship in owned_ships:
            if getattr(ship, "is_aircraft_counter", False):
                continue

            if getattr(ship, "is_base", False):
                affordable = [
                    idx
                    for idx, ship_type in enumerate(BUILD_MENU_ORDER, start=1)
                    if ship.scrap + 1e-9 >= SHIP_TEMPLATES[ship_type]["cost"]
                ]
                affordable.sort(
                    key=lambda slot: self._build_priority(game, owner, BUILD_MENU_ORDER[slot - 1]),
                    reverse=True,
                )
                for slot in affordable[:4]:
                    actions.append(("build", ship.id, slot))
                continue

            if ship.is_charged and not ship.has_moved and not ship.has_fired:
                for key in "wasd":
                    if self._can_step(ship.x, ship.y, key, game.board_size):
                        actions.append(("hyper", ship.id, key))

            if getattr(ship, "move_budget_remaining", 0) > 0:
                move_keys = sorted(
                    "wasd",
                    key=lambda key: self._movement_priority(game, ship, key, owner),
                    reverse=True,
                )
                for key in move_keys:
                    if self._can_step(ship.x, ship.y, key, game.board_size):
                        actions.append(("move", ship.id, key))
                if (
                    len(mobile_ships_at(game, ship.x, ship.y, owner)) > 1
                    and not getattr(game, "attack_damage_done_this_turn", False)
                ):
                    for key in move_keys:
                        if self._can_step(ship.x, ship.y, key, game.board_size):
                            actions.append(("vmove", ship.id, key))

            if (
                not ship.is_charging
                and not ship.is_charged
                and not ship.has_moved
                and not ship.has_fired
            ):
                actions.append(("charge", ship.id))

            fire_actions = self._enumerate_fire_actions(game, ship, enemy_targets)
            actions.extend(fire_actions)

        actions.append(("end",))
        return actions

    def _enumerate_fire_actions(self, game, ship, enemy_targets):
        actions = []
        if getattr(ship, "just_built", False):
            return actions

        pending_center = getattr(ship, "pending_air_center", None)
        pending_aircraft = (
            getattr(ship, "pending_bomber_strikes", 0)
            + getattr(ship, "pending_fighter_strikes", 0)
        )
        if pending_aircraft > 0 and pending_center is not None:
            for target in enemy_targets:
                if game._is_in_dogfight_space(pending_center, target):
                    actions.append(("fire", ship.id, target.id))
            return actions

        ship_range = float(ship.range)
        aircraft_launch_range = 2.0 if ship_range <= 0.0 else max(1.0, ship_range)
        for target in enemy_targets:
            dist = math.dist((ship.x, ship.y), (target.x, target.y))
            in_air_range = dist <= aircraft_launch_range
            in_hull_range = ship_range > 0.0 and dist <= ship_range
            if not in_air_range and not in_hull_range:
                continue
            zone_tiles = set(game._dogfight_tiles(target.x, target.y))
            attacker_aircraft = sum(
                game._available_fighters(s) + game._available_bombers(s)
                for s in game.all_ships
                if s.owner == ship.owner
                and not getattr(s, "is_base", False)
                and (s.x, s.y) in zone_tiles
            )
            if ship.shots > 0 or attacker_aircraft > 0:
                actions.append(("fire", ship.id, target.id))
        return actions

    def _negamax(self, game, depth, alpha, beta, owner, start_time):
        if self._time_exceeded(start_time) or depth <= 0:
            return self._owner_score(game, owner), [("end",)]

        top_k = self.top_k_turns if depth == self.depth else max(2, self.top_k_turns - 1)
        candidates = self.enumerate_candidate_turns(game, owner, start_time, top_k=top_k)
        if not candidates:
            return self._owner_score(game, owner), [("end",)]

        best_score = float("-inf")
        best_plan = candidates[0]["plan"]
        next_owner = 1 if owner == 2 else 2
        for candidate in candidates:
            child_score, _ = self._negamax(
                candidate["state"],
                depth - 1,
                -beta,
                -alpha,
                next_owner,
                start_time,
            )
            score = -child_score
            if score > best_score:
                best_score = score
                best_plan = candidate["plan"]
            alpha = max(alpha, score)
            if alpha >= beta or self._time_exceeded(start_time):
                break

        return best_score, best_plan

    def _dedupe_and_trim(self, nodes, limit):
        unique = []
        seen = set()
        # Higher score first, shorter plan first as the tiebreaker so we don't
        # prefer longer round-about paths to the same state.
        nodes.sort(key=lambda item: (-item["score"], len(item["plan"])))
        for node in nodes:
            sig = self._state_signature(node["state"])
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(node)
            if len(unique) >= limit:
                break
        return unique

    def _owner_score(self, game, owner):
        score = evaluate_board(game)
        return score if owner == 2 else -score

    def _action_bonus(self, before_game, after_game, action, owner):
        kind = action[0]
        bonus = 0.0

        if kind in {"move", "hyper"}:
            ship = self._ship_by_id(after_game, action[1])
            if ship is not None:
                if getattr(after_game, "turn_number", 1) <= 10:
                    if (ship.x, ship.y) in after_game.planets and after_game.base_at(ship.x, ship.y) is not None:
                        bonus += 35.0
                if ship.ship_type == "Dreadnaught":
                    enemies = [
                        e for e in after_game.all_ships
                        if e.owner != owner and not getattr(e, "is_base", False)
                    ]
                    if any(manhattan_distance((ship.x, ship.y), (e.x, e.y)) == 2 for e in enemies):
                        bonus += 14.0
                    if any(
                        e.ship_type in LIGHT_SHIP_TYPES
                        and manhattan_distance((ship.x, ship.y), (e.x, e.y)) <= 3
                        for e in enemies
                    ):
                        bonus -= 28.0

        if kind == "build":
            built_type = BUILD_MENU_ORDER[action[2] - 1]
            bonus += self._build_priority(before_game, owner, built_type)

        if kind == "fire":
            target = self._ship_by_id(before_game, action[2])
            if target is not None and getattr(target, "is_base", False):
                bonus += 250.0
            if getattr(after_game, "game_over", False) and getattr(after_game, "winner", None) == owner:
                bonus += 50000.0

        return bonus

    def _build_priority(self, game, owner, ship_type):
        enemy_ships = [s for s in game.all_ships if s.owner != owner]
        bonus = 0.0
        if any(s.ship_type == "Cruiser" for s in enemy_ships) and ship_type == "Aircraft Carrier":
            bonus += 40.0
        if any(s.ship_type == "Dreadnaught" for s in enemy_ships) and ship_type in LIGHT_SHIP_TYPES:
            bonus += 35.0
        return bonus

    def _movement_priority(self, game, ship, key, owner):
        nx, ny = self._next_position(ship.x, ship.y, key, game.board_size)
        priority = 0.0

        if getattr(game, "turn_number", 1) <= 10 and (nx, ny) in game.planets and game.base_at(nx, ny) is None:
            priority += 30.0

        enemy_bases = [
            b for b in game.all_ships
            if b.owner != owner and getattr(b, "is_base", False) and not is_base_guarded(game, b)
        ]
        if enemy_bases:
            priority += max(0.0, 10.0 - min(manhattan_distance((nx, ny), (b.x, b.y)) for b in enemy_bases))

        if ship.ship_type == "Dreadnaught":
            enemies = [
                e for e in game.all_ships
                if e.owner != owner and not getattr(e, "is_base", False)
            ]
            if any(manhattan_distance((nx, ny), (e.x, e.y)) == 2 for e in enemies):
                priority += 18.0
            if any(
                e.ship_type in LIGHT_SHIP_TYPES and manhattan_distance((nx, ny), (e.x, e.y)) <= 3
                for e in enemies
            ):
                priority -= 26.0

        return priority

    def _find_hyperdrive_base_assault_plan(self, game):
        best_plan = None
        best_score = float("-inf")
        enemy_bases = [
            b for b in game.all_ships
            if b.owner != self.owner and getattr(b, "is_base", False) and game.can_target_ship(b)
        ]
        enemy_bases = [b for b in enemy_bases if not is_base_guarded(game, b)]
        if not enemy_bases:
            return None

        charged_ships = [
            s for s in game.all_ships
            if s.owner == self.owner
            and not getattr(s, "is_base", False)
            and not getattr(s, "is_aircraft_counter", False)
            and getattr(s, "is_charged", False)
            and not s.has_moved
        ]

        for ship in charged_ships:
            for key in "wasd":
                if not self._can_step(ship.x, ship.y, key, game.board_size):
                    continue
                sim = self._clone_for_search(game)
                hyper_action = ("hyper", ship.id, key)
                if not self.apply_action(sim, hyper_action, simulate=True):
                    continue
                moved_ship = self._ship_by_id(sim, ship.id)
                if moved_ship is None:
                    continue

                for base in [
                    b for b in sim.all_ships
                    if b.owner != self.owner and getattr(b, "is_base", False) and not is_base_guarded(sim, b)
                ]:
                    legal_fire_actions = [
                        action
                        for action in self._enumerate_fire_actions(sim, moved_ship, [base])
                        if action[2] == base.id
                    ]
                    if not legal_fire_actions:
                        continue

                    plan = [hyper_action]
                    fire_sim = self._clone_for_search(sim)
                    while True:
                        target_base = self._ship_by_id(fire_sim, base.id)
                        firing_ship = self._ship_by_id(fire_sim, ship.id)
                        if target_base is None or firing_ship is None:
                            break
                        next_actions = [
                            action
                            for action in self._enumerate_fire_actions(fire_sim, firing_ship, [target_base])
                            if action[2] == target_base.id
                        ]
                        if not next_actions:
                            break
                        action = next_actions[0]
                        if not self.apply_action(fire_sim, action, simulate=True):
                            break
                        plan.append(action)
                        if getattr(fire_sim, "game_over", False):
                            break

                    plan.append(("end",))
                    score = self._owner_score(fire_sim, self.owner)
                    if getattr(fire_sim, "game_over", False) and getattr(fire_sim, "winner", None) == self.owner:
                        return plan
                    if score > best_score:
                        best_score = score
                        best_plan = plan

        return best_plan

    def _clone_for_search(self, game):
        sim = copy.deepcopy(game)
        sim.state_history = []
        sim.action_log = []
        return sim

    def _state_signature(self, game):
        ships = []
        for ship in sorted(game.all_ships, key=lambda s: s.id):
            ships.append(
                (
                    ship.id,
                    ship.owner,
                    ship.ship_type,
                    ship.x,
                    ship.y,
                    round(float(ship.hp), 3),
                    round(float(getattr(ship, "scrap", 0)), 3),
                    getattr(ship, "shots", 0),
                    round(float(getattr(ship, "move_budget_remaining", 0)), 3),
                    getattr(ship, "just_built", False),
                    getattr(ship, "is_charging", False),
                    getattr(ship, "is_charged", False),
                    getattr(ship, "did_dogfight_this_turn", False),
                    getattr(ship, "fighters_used_this_turn", 0),
                    getattr(ship, "bombers_used_this_turn", 0),
                    getattr(ship, "pending_bomber_strikes", 0),
                    getattr(ship, "pending_fighter_strikes", 0),
                    getattr(ship, "pending_air_center", None),
                )
            )
        return (
            game.active_player,
            getattr(game, "attack_damage_done_this_turn", False),
            getattr(game, "build_menu_open", False),
            tuple(ships),
        )

    def _ship_by_id(self, game, ship_id):
        return next((s for s in game.all_ships if s.id == ship_id), None)

    def _set_selected(self, game, ship_id, is_enemy):
        for ship in game.all_ships:
            if is_enemy:
                ship.is_enemy_selected = ship.id == ship_id
            else:
                ship.is_selected = ship.id == ship_id

    def _can_step(self, x, y, key, board_size):
        nx, ny = self._next_position(x, y, key, board_size)
        return 0 <= nx < board_size and 0 <= ny < board_size

    def _next_position(self, x, y, key, board_size):
        dx, dy = 0, 0
        if key == "w":
            dy = -1
        elif key == "a":
            dx = -1
        elif key == "s":
            dy = 1
        elif key == "d":
            dx = 1
        return x + dx, y + dy

    def _time_exceeded(self, start_time):
        return (time.monotonic() - start_time) * 1000.0 >= self.time_budget_ms
