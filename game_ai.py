import copy
import math
import time

from game_logic import (
    BUILD_MENU_ORDER,
    DESTROYER_TYPES,
    HANGAR_BOMBER_KEY,
    HANGAR_FIGHTER_KEY,
    HYPERDRIVE_MAX_STEPS,
    LIGHT_SHIP_TYPES,
    SHIP_TEMPLATES,
    evaluate_board,
    focus_fire_potential,
    is_base_guarded,
    manhattan_distance,
    mobile_ships_at,
    pick_hangar_recipient_at_base,
    threat_map_for,
)

TANK_HULL_TYPES = frozenset(
    {"Cruiser", "Heavy Cruiser", "Dreadnaught", "Aircraft Carrier", "Super Star Destroyer"}
)


class AIController:
    _HYPER_VEC_TO_KEY = {(0, -1): "w", (-1, 0): "a", (0, 1): "s", (1, 0): "d"}

    QUICK_BUDGET_MS = 250
    QUIET_BUDGET_MS = 2000
    MODERATE_BUDGET_MS = 5000
    DECISIVE_BUDGET_MS = 9000
    BUDGET_CEILING_MS = 12000
    BUDGET_FLOOR_MS = 500
    MODERATE_SWING_THRESHOLD = 20.0
    DECISIVE_SWING_THRESHOLD = 60.0
    KILL_SWING_BONUS = 10.0

    def __init__(
        self,
        owner=2,
        depth=4,
        min_depth=3,
        top_k_turns=4,
        max_actions_per_turn=12,
        time_budget_ms=2000,
    ):
        self.owner = owner
        self.depth = depth
        self.min_depth = min_depth
        self.top_k_turns = top_k_turns
        self.max_actions_per_turn = max_actions_per_turn
        self.time_budget_ms = time_budget_ms
        self.default_time_budget_ms = time_budget_ms
        self.max_branch_actions = max(8, top_k_turns * 2)
        self.queued_plan = []
        self.is_thinking = False
        # Search memo (reset each pick_best_turn)
        self._leaf_tt = {}
        self._history_table = {}
        self._killer_actions = []
        self._threat_map_cache = {}

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
        self._leaf_tt.clear()
        self._history_table.clear()
        self._killer_actions.clear()
        self._threat_map_cache.clear()
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
        best_plan = None

        # Iterative deepening: complete shallow depths first so we always have a
        # plan, then keep refining at greater depths until the budget runs out.
        # This means depth 3 is a guarantee on most turns and depth 4 is a bonus
        # when the position is simple enough to finish in time.
        for depth in range(self.min_depth, self.depth + 1):
            if self._time_exceeded(search_start):
                break
            self._current_root_depth = depth
            _, plan = self._negamax(
                root,
                depth,
                float("-inf"),
                float("inf"),
                self.owner,
                search_start,
            )
            if plan:
                best_plan = plan
            if self._time_exceeded(search_start):
                break

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
                affordable = []
                for idx, raw in enumerate(BUILD_MENU_ORDER, start=1):
                    if raw == HANGAR_FIGHTER_KEY:
                        cost = SHIP_TEMPLATES["Fighter"]["cost"]
                        if ship.scrap + 1e-9 < cost:
                            continue
                        if pick_hangar_recipient_at_base(game, ship) is None:
                            continue
                    elif raw == HANGAR_BOMBER_KEY:
                        cost = SHIP_TEMPLATES["Bomber"]["cost"]
                        if ship.scrap + 1e-9 < cost:
                            continue
                        if pick_hangar_recipient_at_base(game, ship) is None:
                            continue
                    else:
                        cost = SHIP_TEMPLATES[raw]["cost"]
                        if ship.scrap + 1e-9 < cost:
                            continue
                    affordable.append(idx)
                affordable.sort(
                    key=lambda slot: self._build_priority(game, owner, BUILD_MENU_ORDER[slot - 1]),
                    reverse=True,
                )
                for slot in affordable[:4]:
                    actions.append(("build", ship.id, slot))
                continue

            if ship.is_charged and not ship.has_moved and not ship.has_fired:
                su = getattr(ship, "hyperdrive_steps_used", 0) or 0
                if su == 0:
                    for hk in "wasd":
                        if self._can_step(ship.x, ship.y, hk, game.board_size):
                            actions.append(("hyper", ship.id, hk))
                elif su < HYPERDRIVE_MAX_STEPS:
                    lk = None
                    if ship.hyperdrive_dx is not None and ship.hyperdrive_dy is not None:
                        lk = self._HYPER_VEC_TO_KEY.get((ship.hyperdrive_dx, ship.hyperdrive_dy))
                    if lk and self._can_step(ship.x, ship.y, lk, game.board_size):
                        actions.append(("hyper", ship.id, lk))

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
                and (ship.x, ship.y) == (ship.start_x, ship.start_y)
            ):
                actions.append(("charge", ship.id))

            fire_actions = self._enumerate_fire_actions(game, ship, enemy_targets)
            actions.extend(fire_actions)

        actions = self._sort_action_list(game, owner, actions)
        actions.append(("end",))
        return actions

    def _sort_action_list(self, game, owner, actions):
        killers = {tuple(x) for x in self._killer_actions}
        # Per-call cache: (state signature, action tuple) -> hp_delta
        sig = self._state_signature(game)
        fire_delta_cache = {}

        def sort_key(atom):
            t = tuple(atom)
            killer_boost = 4e6 if t in killers else 0.0
            hist_boost = self._history_table.get(t, 0) * 120.0
            return killer_boost + hist_boost + self._atomic_action_estimate_priority(
                game, owner, atom, sig=sig, fire_delta_cache=fire_delta_cache,
            )

        return sorted(actions, key=sort_key, reverse=True)

    def _atomic_action_estimate_priority(self, game, owner, action, sig=None, fire_delta_cache=None):
        k = action[0]
        if k == "end":
            return -1e12
        if k == "fire":
            ship = self._ship_by_id(game, action[1])
            tgt = self._ship_by_id(game, action[2])
            if ship is None or tgt is None:
                return -900.0
            bonus = 420.0 + focus_fire_potential(game, tgt, owner) * 14.0
            if getattr(tgt, "is_base", False):
                bonus += 1100.0
            # T1. Destroyer assassination — heavily prefer killing a stack's only
            # destroyer (it strands the rest of the stack).
            if (
                not getattr(tgt, "is_base", False)
                and getattr(tgt, "ship_type", None) in DESTROYER_TYPES
            ):
                stack = mobile_ships_at(game, tgt.x, tgt.y, tgt.owner)
                destroyers_in_stack = sum(1 for s in stack if s.ship_type in DESTROYER_TYPES)
                non_destroyers_in_stack = sum(1 for s in stack if s.ship_type not in DESTROYER_TYPES)
                if destroyers_in_stack == 1 and non_destroyers_in_stack >= 1:
                    bonus += 1500.0
                elif len(stack) >= 2:
                    bonus += 400.0
            # Tactical-template "must-consider attacks": simulate the fire and
            # add a strong ordering boost if it actually delivers damage.
            cache_key = None
            if fire_delta_cache is not None:
                cache_key = (sig if sig is not None else self._state_signature(game), tuple(action))
                if cache_key in fire_delta_cache:
                    hp_delta = fire_delta_cache[cache_key]
                else:
                    sim = self._clone_for_search(game)
                    if self.apply_action(sim, action, simulate=True):
                        hp_delta = self._enemy_hp_delta(game, sim, owner)
                    else:
                        hp_delta = 0.0
                    fire_delta_cache[cache_key] = hp_delta
            else:
                sim = self._clone_for_search(game)
                if self.apply_action(sim, action, simulate=True):
                    hp_delta = self._enemy_hp_delta(game, sim, owner)
                else:
                    hp_delta = 0.0
            if hp_delta > 0:
                bonus += 5000.0 + hp_delta * 800.0
            return bonus
        if k == "hyper":
            return 720.0
        if k == "charge":
            return 535.0
        if k == "build":
            entry = BUILD_MENU_ORDER[action[2] - 1]
            return 360.0 + self._build_priority(game, owner, entry)
        if k == "move":
            ship = self._ship_by_id(game, action[1])
            if ship is None:
                return -300.0
            move_key = action[2]
            bonus = self._movement_priority(game, ship, move_key, owner)
            nx, ny = self._next_position(ship.x, ship.y, move_key, game.board_size)
            if getattr(game, "turn_number", 99) <= 6:
                if (nx, ny) in game.planets and game.base_at(nx, ny) is None:
                    bonus += 48.0
            # T2a. Tank-on-base: park a high-HP friendly hull on an unguarded
            # friendly base, especially when that base is under enemy threat.
            bonus += self._tank_on_base_bonus(game, ship, nx, ny, owner)
            return bonus + 40.0
        if k == "vmove":
            ship = self._ship_by_id(game, action[1])
            if ship is None:
                return -400.0
            return self._movement_priority(game, ship, action[2], owner) - 70.0
        return 0.0

    def _enumerate_fire_actions(self, game, ship, enemy_targets):
        actions = []
        if getattr(ship, "just_built", False):
            return actions
        if getattr(ship, "did_hyperdrive_this_turn", False):
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

    def _record_killer_cutoff(self, plan):
        if not plan:
            return
        first = tuple(plan[0])
        if first not in self._killer_actions:
            self._killer_actions.insert(0, first)
            self._killer_actions = self._killer_actions[:6]
        self._history_table[first] = self._history_table.get(first, 0) + 3

    def _negamax(self, game, depth, alpha, beta, owner, start_time):
        if self._time_exceeded(start_time):
            return self._owner_score(game, owner), [("end",)]
        if depth <= 0:
            leaf_key = (self._state_signature(game), owner)
            cached = self._leaf_tt.get(leaf_key)
            if cached is not None:
                return cached, [("end",)]
            sc = self._owner_score(game, owner)
            self._leaf_tt[leaf_key] = sc
            return sc, [("end",)]

        # Wider beam at the root of the current search; tighter at interior plies
        # to keep the deeper search tractable.
        root_depth = getattr(self, "_current_root_depth", self.depth)
        top_k = self.top_k_turns if depth == root_depth else max(2, self.top_k_turns - 1)
        candidates = self.enumerate_candidate_turns(game, owner, start_time, top_k=top_k)
        if not candidates:
            return self._owner_score(game, owner), [("end",)]

        def candidate_sort_key(cp):
            if not cp.get("plan"):
                return (-1e13, cp["score"])
            first_act = tuple(cp["plan"][0])
            killer_hit = first_act in {tuple(k) for k in self._killer_actions}
            kboost = 1e12 if killer_hit else 0.0
            est = self._atomic_action_estimate_priority(game, owner, cp["plan"][0])
            return (kboost + est + cp["score"] * 1e-6, cp["score"])

        candidates_ordered = sorted(candidates, key=candidate_sort_key, reverse=True)

        best_score = float("-inf")
        best_plan = candidates_ordered[0]["plan"]
        next_owner = 1 if owner == 2 else 2
        for candidate in candidates_ordered:
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
            if alpha >= beta:
                self._record_killer_cutoff(candidate["plan"])
                break
            if self._time_exceeded(start_time):
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
            entry = BUILD_MENU_ORDER[action[2] - 1]
            bonus += self._build_priority(before_game, owner, entry)

        if kind == "fire":
            target = self._ship_by_id(before_game, action[2])
            if target is not None and getattr(target, "is_base", False):
                bonus += 250.0
            if getattr(after_game, "game_over", False) and getattr(after_game, "winner", None) == owner:
                bonus += 50000.0
            hp_delta = self._enemy_hp_delta(before_game, after_game, owner)
            if hp_delta > 0:
                bonus += hp_delta * 60.0
            # T1. If the fire just removed the only destroyer in an enemy stack
            # while non-destroyer mobiles remain, that stack is now frozen.
            if target is not None and not getattr(target, "is_base", False):
                tx, ty, tow = target.x, target.y, target.owner
                before_stack = mobile_ships_at(before_game, tx, ty, tow)
                before_destroyers = sum(1 for s in before_stack if s.ship_type in DESTROYER_TYPES)
                after_stack = mobile_ships_at(after_game, tx, ty, tow)
                after_destroyers = sum(1 for s in after_stack if s.ship_type in DESTROYER_TYPES)
                after_non_destroyers = sum(1 for s in after_stack if s.ship_type not in DESTROYER_TYPES)
                if before_destroyers >= 1 and after_destroyers == 0 and after_non_destroyers >= 1:
                    bonus += 200.0

        return bonus

    def _enemy_threat_map(self, game, owner):
        """Cached enemy threat map for the current `pick_best_turn` search."""
        sig = self._state_signature(game)
        opp = 1 if owner == 2 else 2
        cache = getattr(self, "_threat_map_cache", None)
        if cache is None:
            cache = {}
            self._threat_map_cache = cache
        key = (sig, opp)
        cached = cache.get(key)
        if cached is None:
            cached = threat_map_for(game, opp)
            cache[key] = cached
        return cached

    def _tank_on_base_bonus(self, game, ship, nx, ny, owner):
        if ship is None or getattr(ship, "is_aircraft_counter", False):
            return 0.0
        if getattr(ship, "ship_type", None) not in TANK_HULL_TYPES:
            return 0.0
        base = game.base_at(nx, ny)
        if base is None or base.owner != owner:
            return 0.0
        if is_base_guarded(game, base):
            return 0.0
        bonus = 800.0
        threat_map = self._enemy_threat_map(game, owner)
        if threat_map.get((nx, ny), 0.0) > 0.0:
            bonus += 700.0
        return bonus

    def _enemy_hp_delta(self, before_game, after_game, owner):
        """Total HP that `owner`'s actions removed from enemy ships (mobile or base)
        between before_game and after_game. Destroyed ships count their full
        before-state HP, capped at max_health. aircraft-counter ships included so
        bombers/fighters being chewed in a dogfight also register.
        """
        before_hp = {}
        before_max = {}
        for s in before_game.all_ships:
            if s.owner == owner:
                continue
            before_hp[s.id] = float(getattr(s, "hp", 0.0))
            before_max[s.id] = float(getattr(s, "max_health", 0.0)) or before_hp[s.id]

        delta = 0.0
        survivors = {s.id: float(getattr(s, "hp", 0.0)) for s in after_game.all_ships if s.owner != owner}
        for sid, hp in before_hp.items():
            after_hp = survivors.get(sid)
            if after_hp is None:
                delta += min(hp, before_max.get(sid, hp))
            elif after_hp < hp:
                delta += hp - after_hp
        return max(0.0, delta)

    def _build_priority(self, game, owner, menu_entry):
        bonus = 0.0
        if menu_entry == HANGAR_FIGHTER_KEY:
            allied_air = sum(
                getattr(s, "fighters", 0) + getattr(s, "bombers", 0)
                for s in game.all_ships
                if s.owner == owner and not getattr(s, "is_base", False)
            )
            enemy_air = sum(
                getattr(s, "fighters", 0) + getattr(s, "bombers", 0)
                for s in game.all_ships
                if s.owner != owner and not getattr(s, "is_base", False)
            )
            if allied_air <= enemy_air + 3:
                bonus += 70.0
            return bonus
        if menu_entry == HANGAR_BOMBER_KEY:
            unguarded_enemy_bases = [
                b
                for b in game.all_ships
                if b.owner != owner and getattr(b, "is_base", False) and not is_base_guarded(game, b)
            ]
            if unguarded_enemy_bases:
                bonus += 60.0
            allied_air = sum(
                getattr(s, "fighters", 0) + getattr(s, "bombers", 0)
                for s in game.all_ships
                if s.owner == owner and not getattr(s, "is_base", False)
            )
            enemy_air = sum(
                getattr(s, "fighters", 0) + getattr(s, "bombers", 0)
                for s in game.all_ships
                if s.owner != owner and not getattr(s, "is_base", False)
            )
            if allied_air <= enemy_air + 3:
                bonus += 40.0
            return bonus
        enemy_ships = [s for s in game.all_ships if s.owner != owner]
        if any(s.ship_type == "Cruiser" for s in enemy_ships) and menu_entry == "Aircraft Carrier":
            bonus += 40.0
        if any(s.ship_type == "Dreadnaught" for s in enemy_ships) and menu_entry in LIGHT_SHIP_TYPES:
            bonus += 35.0

        # T2b. Tank-build template: if a friendly base is unguarded and the
        # enemy can reach it, prefer high-HP hulls that can later park on it.
        threat_map = self._enemy_threat_map(game, owner)
        threatened_unguarded_base = any(
            b.owner == owner
            and getattr(b, "is_base", False)
            and not is_base_guarded(game, b)
            and threat_map.get((b.x, b.y), 0.0) > 0.0
            for b in game.all_ships
        )
        if threatened_unguarded_base:
            if menu_entry == "Heavy Cruiser":
                bonus += 50.0
            elif menu_entry == "Cruiser":
                bonus += 35.0
            elif menu_entry == "Dreadnaught":
                bonus += 30.0

        # T4. Replacement-destroyer build: if any friendly stack has
        # non-destroyer mobiles but no destroyers, building a Destroyer
        # restores the anchor that lets them move again.
        if menu_entry == "Destroyer":
            stacks = {}
            for s in game.all_ships:
                if s.owner != owner:
                    continue
                if getattr(s, "is_base", False):
                    continue
                if getattr(s, "is_aircraft_counter", False):
                    continue
                stacks.setdefault((s.x, s.y), []).append(s)
            for tile_ships in stacks.values():
                has_destroyer = any(s.ship_type in DESTROYER_TYPES for s in tile_ships)
                has_non_destroyer = any(s.ship_type not in DESTROYER_TYPES for s in tile_ships)
                if has_non_destroyer and not has_destroyer:
                    bonus += 60.0
                    break

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

        # T2a. Mirror the tank-on-base movement template into the candidate
        # ordering so _negamax explores those moves first.
        priority += self._tank_on_base_bonus(game, ship, nx, ny, owner)

        # T3. Formation cohesion / anti-isolation.
        centroid = self._allied_centroid(game, owner)
        if centroid is not None and ship.ship_type not in DESTROYER_TYPES:
            dist_centroid = manhattan_distance((nx, ny), centroid)
            if dist_centroid > 2:
                priority -= 25.0

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
            # T3. Dreadnaught rear-positioning: reward staying >= 2 from the
            # nearest enemy mobile so it kites behind the line.
            enemy_mobiles = [
                e for e in game.all_ships
                if e.owner != owner
                and not getattr(e, "is_base", False)
                and not getattr(e, "is_aircraft_counter", False)
            ]
            if enemy_mobiles:
                nearest = min(manhattan_distance((nx, ny), (e.x, e.y)) for e in enemy_mobiles)
                if nearest >= 2:
                    priority += 12.0

        return priority

    def _allied_centroid(self, game, owner):
        xs = []
        ys = []
        for s in game.all_ships:
            if s.owner != owner:
                continue
            if getattr(s, "is_base", False):
                continue
            if getattr(s, "is_aircraft_counter", False):
                continue
            xs.append(s.x)
            ys.append(s.y)
        if not xs:
            return None
        return (sum(xs) / len(xs), sum(ys) / len(ys))

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
                plan_hyper = []
                for _burst in range(HYPERDRIVE_MAX_STEPS):
                    cur = self._ship_by_id(sim, ship.id)
                    if cur is None or not cur.is_charged:
                        break
                    su = getattr(cur, "hyperdrive_steps_used", 0) or 0
                    lk = key if su == 0 else self._HYPER_VEC_TO_KEY.get((cur.hyperdrive_dx, cur.hyperdrive_dy))
                    if not lk:
                        break
                    if not self._can_step(cur.x, cur.y, lk, sim.board_size):
                        break
                    ox, oy = cur.x, cur.y
                    sim.hyperdrive_move(cur, lk)
                    after = self._ship_by_id(sim, ship.id)
                    if after is None:
                        break
                    if (after.x, after.y) == (ox, oy):
                        break
                    plan_hyper.append(("hyper", ship.id, lk))
                    if not after.is_charged:
                        break

                if not plan_hyper:
                    continue
                moved_ship = self._ship_by_id(sim, ship.id)
                if moved_ship is None:
                    continue

                # Hyperdrive uses the tactical move this turn — no shooting until next activation.
                plan = list(plan_hyper) + [("end",)]
                score = self._owner_score(sim, self.owner)
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
                    getattr(ship, "hyperdrive_steps_used", 0),
                    getattr(ship, "hyperdrive_dx", None),
                    getattr(ship, "hyperdrive_dy", None),
                    getattr(ship, "did_hyperdrive_this_turn", False),
                    getattr(ship, "fighters", 0),
                    getattr(ship, "bombers", 0),
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
