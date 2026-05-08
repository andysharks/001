import copy
import math
import random

from eval_weights import DEFAULT_EVAL_WEIGHTS, merge_eval_weights, score_from_features

SHIP_TEMPLATES = {
    "Cruiser": {
        "cost": 2.0, "movement": 0.0, "max_health": 6.0, "damage": 2.0, "range": 0.0, "aircraft_storage": 4.0
    },
    "Light Cruiser": {
        "cost": 2.0, "movement": 2.0, "max_health": 3.0, "damage": 1.0, "range": 1.0, "aircraft_storage": 2.0, "fleet_movement": 2.0
    },
    "Fighter": {
        "cost": 0.5, "movement": 1.0, "max_health": 0.25, "damage": 0.25, "range": 0.0, "aircraft_storage": 0.0
    },
    "Bomber": {
        "cost": 0.5, "movement": 1.0, "max_health": 0.25, "damage": 0.5, "range": 0.0, "aircraft_storage": 0.0
    },
    "Aircraft Carrier": {
        "cost": 3.0, "movement": 0.0, "max_health": 4.0, "damage": 0.0, "range": 0.0, "aircraft_storage": 16.0
    },
    "Dreadnaught": {
        "cost": 3.0, "movement": 0.0, "max_health": 4.0, "damage": 4.0, "range": 2.0, "aircraft_storage": 4.0,
        # Battery: two hull shots per turn — 2 damage at Euclidean distance ≤1, 1 damage at ≤2 (see hull helpers).
        "damage_profile": (2.0, 1.0), "range_profile": (1.0, 2.0),
    },
    "Heavy Cruiser": {
        "cost": 3.0, "movement": 0.0, "max_health": 7.0, "damage": 2.0, "range": 0.0, "aircraft_storage": 4.0
    },
    "Super Star Destroyer": {
        "cost": 5.0, "movement": 1.0, "max_health": 12.0, "damage": 6.0, "range": 1.0, "aircraft_storage": 4.0
    },
    "Destroyer": {
        "cost": 1.0, "movement": 1.0, "max_health": 1.0, "damage": 1.0, "range": 1.0, "aircraft_storage": 2.0
    },
    "Light Destroyer": {
        "cost": 0.5, "movement": 2.0, "max_health": 0.5, "damage": 0.5, "range": 1.0, "aircraft_storage": 1.0, "fleet_movement": 2.0
    },
    "Base": {
        "cost": 0.0, "movement": 0.0, "max_health": 2.0, "damage": 0.0, "range": 0.0, "aircraft_storage": 0.0
    },
}

LIGHT_SHIP_TYPES = frozenset({"Light Cruiser", "Light Destroyer"})
DESTROYER_TYPES = frozenset({"Destroyer", "Light Destroyer"})
CAPITAL_SHIP_TYPES = frozenset(
    {"Cruiser", "Light Cruiser", "Heavy Cruiser", "Aircraft Carrier", "Dreadnaught", "Super Star Destroyer"}
)
DREADNAUGHT_EXCLUDED = frozenset({"Cruiser", "Heavy Cruiser", "Aircraft Carrier"})
MAX_CAPITALS_PER_FLEET = 4


def _fleet_rule_violation(stack_after):
    """Return a string describing the broken rule, or None if the stack is legal.

    `stack_after` is an iterable of mobile-ship objects that would share a
    tile after the proposed move/build. Bases and aircraft-counter hulls are
    expected to already be filtered out by the caller.
    """
    has_dread = any(s.ship_type == "Dreadnaught" for s in stack_after)
    has_excluded = any(s.ship_type in DREADNAUGHT_EXCLUDED for s in stack_after)
    if has_dread and has_excluded:
        return "Movement denied: Dreadnaught cannot fleet with Cruiser / Heavy Cruiser / Aircraft Carrier."
    capitals_after = sum(1 for s in stack_after if s.ship_type in CAPITAL_SHIP_TYPES)
    if capitals_after > MAX_CAPITALS_PER_FLEET:
        return "Movement denied: max 4 large ships per fleet."
    return None

SHIP_TYPE_IDS = {
    "Destroyer": 1,
    "Cruiser": 2,
    "Dreadnaught": 3,
    "Aircraft Carrier": 4,
    "Heavy Cruiser": 5,
    "Light Cruiser": 6,
    "Fighter": 7,
    "Bomber": 8,
    "Super Star Destroyer": 9,
    "Light Destroyer": 10,
}
# Display on map for bases uses scrap count, not ship_type_id.

# Heuristic multipliers keyed by declared ship type id.
# These fine-tune value beyond raw cost/HP so evaluate_board() accounts for all known ids.
SHIP_ID_EVAL_MULTIPLIERS = {
    SHIP_TYPE_IDS["Destroyer"]: 1.00,
    SHIP_TYPE_IDS["Cruiser"]: 1.10,
    SHIP_TYPE_IDS["Dreadnaught"]: 1.20,
    SHIP_TYPE_IDS["Aircraft Carrier"]: 1.25,
    SHIP_TYPE_IDS["Heavy Cruiser"]: 1.15,
    SHIP_TYPE_IDS["Light Cruiser"]: 1.00,
    SHIP_TYPE_IDS["Fighter"]: 0.90,
    SHIP_TYPE_IDS["Bomber"]: 1.00,
    SHIP_TYPE_IDS["Super Star Destroyer"]: 1.40,
    SHIP_TYPE_IDS["Light Destroyer"]: 0.95,
}

WIN_SCORE = 100000.0
BASE_VALUE_BONUS = 140.0
MOBILITY_LOCK_PENALTY = 90.0
DREAD_KITING_BONUS = 16.0
DREAD_LIGHT_THREAT_PENALTY = 35.0
EARLY_PLANET_PRESSURE_BONUS = 8.0
EARLY_BASE_EXPANSION_BONUS = 24.0
FIGHTER_STRIKE_DAMAGE_VALUE = SHIP_TEMPLATES["Fighter"]["damage"]
BOMBER_STRIKE_DAMAGE_VALUE = SHIP_TEMPLATES["Bomber"]["damage"]
FOCUS_FIRE_KILL_BONUS = 25.0
FOCUS_FIRE_BASE_BONUS = 800.0
BASE_GUARD_BONUS = 15.0
BASE_UNGUARDED_PENALTY = 40.0
BASE_HYPER_THREAT_PENALTY = 120.0
DEFENDER_HP_BONUS_CAP = 30.0


def manhattan_distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def mobile_defenders_at(game, x, y, owner):
    return [
        s for s in game.all_ships
        if s.x == x and s.y == y and s.owner == owner
        and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    ]


def is_base_guarded(game, base_ship):
    if not getattr(base_ship, "is_base", False):
        return False
    return len(mobile_defenders_at(game, base_ship.x, base_ship.y, base_ship.owner)) > 0


def _ship_available_fighters(ship):
    return max(0, getattr(ship, "fighters", 0) - getattr(ship, "fighters_used_this_turn", 0))


def _ship_available_bombers(ship):
    return max(0, getattr(ship, "bombers", 0) - getattr(ship, "bombers_used_this_turn", 0))


def _ship_aircraft_strike_damage(ship):
    return (
        _ship_available_fighters(ship) * float(FIGHTER_STRIKE_DAMAGE_VALUE)
        + _ship_available_bombers(ship) * float(BOMBER_STRIKE_DAMAGE_VALUE)
    )


def _ship_air_launch_range(ship):
    rng = float(getattr(ship, "range", 0))
    if rng <= 0.0:
        return 2.0
    return max(1.0, rng)


def _ship_can_threaten(ship):
    if getattr(ship, "is_base", False) or getattr(ship, "is_aircraft_counter", False):
        return False
    if getattr(ship, "just_built", False):
        return False
    return True


def _ship_can_threaten_air(ship):
    """Like _ship_can_threaten, but also allows aircraft-counter (Fighter/Bomber)
    hull ships. They cannot move themselves and can only contribute to a dogfight
    when the target is within manhattan <= 1, but they DO project damage that the
    AI evaluator should account for.
    """
    if getattr(ship, "is_base", False):
        return False
    if getattr(ship, "just_built", False):
        return False
    return True


def threat_map_for(game, owner):
    """Approximate damage `owner` can deliver to each square this turn.

    Movement reach is capped at the ship's remaining move budget (or 8 for
    charged ships). Aircraft strike damage is added to squares within move
    reach + air launch range. Hull damage is added to squares within move
    reach + hull range.
    """
    threats = {}
    board_size = game.board_size
    for ship in game.all_ships:
        if ship.owner != owner or not _ship_can_threaten(ship):
            continue
        if getattr(ship, "is_charged", False):
            move_reach = 8
        else:
            move_reach = max(0, int(getattr(ship, "move_budget_remaining", 0)))
        move_reach = min(move_reach, 8)

        if getattr(ship, "shots", 0) <= 0:
            hull_damage_band = 0.0
        elif ship_is_dreadnaught(ship):
            # Upper envelope for heuristic map: farthest shells do 1, inner band 2.
            hull_damage_band = 2.0
        else:
            hull_damage_band = float(getattr(ship, "damage", 0))
        hull_damage = hull_damage_band
        hull_rf = float(getattr(ship, "range", 0))
        hull_range = 2 if ship_is_dreadnaught(ship) else max(0, int(round(hull_rf)))
        air_launch = max(0, int(round(_ship_air_launch_range(ship))))
        air_dmg = _ship_aircraft_strike_damage(ship)

        if hull_damage <= 0 and air_dmg <= 0:
            continue

        if hull_rf <= 0.0:
            melee_hull_reach = hull_damage > 0.0
            max_reach = max(
                move_reach if melee_hull_reach else 0,
                move_reach + air_launch if air_dmg > 0 else 0,
            )
        else:
            max_reach = max(
                move_reach + hull_range,
                move_reach + air_launch if air_dmg > 0 else 0,
            )
        for dx in range(-max_reach, max_reach + 1):
            for dy in range(-max_reach, max_reach + 1):
                manhat = abs(dx) + abs(dy)
                if manhat > max_reach:
                    continue
                tx, ty = ship.x + dx, ship.y + dy
                if not (0 <= tx < board_size and 0 <= ty < board_size):
                    continue
                contribution = 0.0
                if hull_damage > 0:
                    if hull_rf <= 0.0:
                        if manhat <= move_reach:
                            contribution += hull_damage
                    elif manhat <= move_reach + hull_range:
                        contribution += hull_damage
                if air_dmg > 0 and manhat <= move_reach + air_launch:
                    contribution += air_dmg
                if contribution > 0:
                    threats[(tx, ty)] = threats.get((tx, ty), 0.0) + contribution

    # Second pass: aircraft-counter (Fighter/Bomber) hull ships. They cannot
    # move themselves; they only contribute to a dogfight when the target is at
    # manhattan <= 1 from their position (the dogfight zone is the target's
    # 4-neighborhood + center).
    for ship in game.all_ships:
        if ship.owner != owner:
            continue
        if not getattr(ship, "is_aircraft_counter", False):
            continue
        if not _ship_can_threaten_air(ship):
            continue
        air_dmg = _ship_aircraft_strike_damage(ship)
        if air_dmg <= 0:
            continue
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if abs(dx) + abs(dy) > 1:
                    continue
                tx, ty = ship.x + dx, ship.y + dy
                if not (0 <= tx < board_size and 0 <= ty < board_size):
                    continue
                threats[(tx, ty)] = threats.get((tx, ty), 0.0) + air_dmg
    return threats


def hull_shots_resting_cap(ship):
    """Max hull cannon presses per activation (excluding aircraft strikes)."""
    return 2 if getattr(ship, "ship_type", None) == "Dreadnaught" else 1


def ship_is_dreadnaught(attacker_ship):
    return getattr(attacker_ship, "ship_type", None) == "Dreadnaught"


def _generic_hull_geometry(attacker_ship, target_ship):
    """Hull reach for normal batteries (ignored for Dreadnaught)."""
    sr = float(getattr(attacker_ship, "range", 0))
    if sr <= 0.0:
        return attacker_ship.x == target_ship.x and attacker_ship.y == target_ship.y
    dist = math.dist((attacker_ship.x, attacker_ship.y), (target_ship.x, target_ship.y))
    return dist <= sr + 1e-9


def hull_geometry_in_range(attacker_ship, target_ship):
    """Hull battery reach (ignores ammunition)."""
    if ship_is_dreadnaught(attacker_ship):
        dist = math.dist((attacker_ship.x, attacker_ship.y), (target_ship.x, target_ship.y))
        return dist <= 2.0 + 1e-9
    return _generic_hull_geometry(attacker_ship, target_ship)


def dreadnaught_battery_shell_damage(attacker_ship, target_ship):
    """Single hull shell vs target distance; 0 if out of Euclidean battery arc."""
    dist = math.dist((attacker_ship.x, attacker_ship.y), (target_ship.x, target_ship.y))
    if dist <= 1.0 + 1e-9:
        return 2.0
    if dist <= 2.0 + 1e-9:
        return 1.0
    return 0.0


def hull_damage_one_volley(attacker_ship, target_ship):
    """Damage from one hull FIRE press (excluding aircraft). Used when geometry and shots permit."""
    if ship_is_dreadnaught(attacker_ship):
        return dreadnaught_battery_shell_damage(attacker_ship, target_ship)
    return float(getattr(attacker_ship, "damage", 0)) if _generic_hull_geometry(attacker_ship, target_ship) else 0.0


def hull_weapon_hits(attacker_ship, target_ship):
    """True if hull guns can legally fire at ``target_ship`` this turn."""
    if getattr(attacker_ship, "shots", 0) <= 0:
        return False
    return hull_geometry_in_range(attacker_ship, target_ship)


def focus_fire_potential(game, target_ship, attackers_owner):
    """Upper-bound damage `attackers_owner` can deliver to `target_ship` this turn
    from in-place attackers (no movement assumed).
    """
    if target_ship is None:
        return 0.0
    if getattr(target_ship, "is_base", False) and is_base_guarded(game, target_ship):
        return 0.0

    total = 0.0
    target_pos = (target_ship.x, target_ship.y)
    for ship in game.all_ships:
        if ship.owner != attackers_owner:
            continue
        if not _ship_can_threaten(ship):
            continue
        dist = math.dist((ship.x, ship.y), target_pos)
        air_launch = _ship_air_launch_range(ship)
        if hull_weapon_hits(ship, target_ship):
            if ship_is_dreadnaught(ship):
                per = dreadnaught_battery_shell_damage(ship, target_ship)
                ns = max(0, getattr(ship, "shots", 0))
                if per > 0:
                    total += per * ns
            else:
                total += float(getattr(ship, "damage", 0))
        if dist <= air_launch:
            total += _ship_aircraft_strike_damage(ship)

    # Aircraft-counter friendlies contribute their air strike damage when they
    # sit inside the target's dogfight zone (manhattan <= 1).
    for ship in game.all_ships:
        if ship.owner != attackers_owner:
            continue
        if not getattr(ship, "is_aircraft_counter", False):
            continue
        if not _ship_can_threaten_air(ship):
            continue
        if manhattan_distance((ship.x, ship.y), target_pos) <= 1:
            total += _ship_aircraft_strike_damage(ship)
    return total


def base_safety_score(game, base_ship):
    """Returns dict of safety attributes for a base, or None if the input is not a base."""
    if not getattr(base_ship, "is_base", False):
        return None

    defenders = mobile_defenders_at(game, base_ship.x, base_ship.y, base_ship.owner)
    defender_hp = float(sum(getattr(d, "hp", 0) for d in defenders))

    enemy_owner = 1 if base_ship.owner == 2 else 2
    enemy_charged_threat = False
    for ship in game.all_ships:
        if ship.owner != enemy_owner:
            continue
        if getattr(ship, "is_base", False) or getattr(ship, "is_aircraft_counter", False):
            continue
        if not getattr(ship, "is_charged", False):
            continue
        if manhattan_distance((ship.x, ship.y), (base_ship.x, base_ship.y)) <= 8:
            enemy_charged_threat = True
            break

    return {
        "guarded": len(defenders) > 0,
        "defender_count": len(defenders),
        "defender_hp": defender_hp,
        "enemy_charged_threat": enemy_charged_threat,
    }


def aircraft_dominance(game, owner):
    """Sum over enemy-occupied tiles of clipped (my available aircraft - their fighters)
    inside the dogfight zone of that tile.
    """
    enemy_owner = 1 if owner == 2 else 2
    enemy_tiles = {
        (s.x, s.y)
        for s in game.all_ships
        if s.owner == enemy_owner and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    }
    if not enemy_tiles:
        return 0.0

    total = 0.0
    for tx, ty in enemy_tiles:
        zone = {(tx, ty)}
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = tx + dx, ty + dy
            if 0 <= nx < game.board_size and 0 <= ny < game.board_size:
                zone.add((nx, ny))
        my_air = 0.0
        their_fighters = 0.0
        for ship in game.all_ships:
            if (ship.x, ship.y) not in zone:
                continue
            if getattr(ship, "is_base", False):
                continue
            if ship.owner == owner:
                my_air += _ship_available_fighters(ship) + _ship_available_bombers(ship)
            else:
                their_fighters += _ship_available_fighters(ship)
        total += max(0.0, my_air - their_fighters)
    return total


EVAL_CORE_BAND_CHEB = 1


def localized_aircraft_dominance_near_contact(game_state, owner, contact_radius=2):
    enemy_owner = 1 if owner == 2 else 2
    enemy_tiles = {
        (s.x, s.y)
        for s in game_state.all_ships
        if s.owner == enemy_owner and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    }
    if not enemy_tiles:
        return 0.0
    ally_cells = [
        (s.x, s.y)
        for s in game_state.all_ships
        if s.owner == owner and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    ]
    if not ally_cells:
        return 0.0
    flagged = set()
    for tx, ty in enemy_tiles:
        if any(
            manhattan_distance((tx, ty), (ax, ay)) <= contact_radius for ax, ay in ally_cells
        ):
            flagged.add((tx, ty))
    if not flagged:
        return 0.0
    total = 0.0
    board_size = game_state.board_size
    for tx, ty in flagged:
        zone = {(tx, ty)}
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = tx + dx, ty + dy
            if 0 <= nx < board_size and 0 <= ny < board_size:
                zone.add((nx, ny))
        my_air = 0.0
        their_fighters = 0.0
        for ship in game_state.all_ships:
            if (ship.x, ship.y) not in zone:
                continue
            if getattr(ship, "is_base", False):
                continue
            if ship.owner == owner:
                my_air += _ship_available_fighters(ship) + _ship_available_bombers(ship)
            elif ship.owner == enemy_owner:
                their_fighters += _ship_available_fighters(ship)
        total += max(0.0, my_air - their_fighters)
    return total


def _enemy_mobile_ships(game_state, owner):
    return [
        s
        for s in game_state.all_ships
        if s.owner == owner
        and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    ]


def _adjacency_inbound_pressure_raw(game_state):
    raw = 0.0
    p2m = _enemy_mobile_ships(game_state, 2)
    p1m = _enemy_mobile_ships(game_state, 1)
    for ship in p2m:
        if not any(manhattan_distance((ship.x, ship.y), (e.x, e.y)) <= 1 for e in p1m):
            continue
        raw -= focus_fire_potential(game_state, ship, 1)
    for ship in p1m:
        if not any(manhattan_distance((ship.x, ship.y), (e.x, e.y)) <= 1 for e in p2m):
            continue
        raw += focus_fire_potential(game_state, ship, 2)
    return raw


def _melee_leverage_trade_raw(game_state):
    p2m = _enemy_mobile_ships(game_state, 2)
    p1m = _enemy_mobile_ships(game_state, 1)
    gain = 0.0
    for ship in p2m:
        for foe in p1m:
            if manhattan_distance((ship.x, ship.y), (foe.x, foe.y)) > 1:
                continue
            atk = focus_fire_potential(game_state, foe, 2)
            defn = focus_fire_potential(game_state, ship, 1)
            gain += max(0.0, atk - defn)
    loss = 0.0
    for ship in p1m:
        for foe in p2m:
            if manhattan_distance((ship.x, ship.y), (foe.x, foe.y)) > 1:
                continue
            atk = focus_fire_potential(game_state, foe, 1)
            defn = focus_fire_potential(game_state, ship, 2)
            loss += max(0.0, atk - defn)
    return gain - loss


def _initiative_contested_raw(game_state, contest_radius=2):
    def side_total(owner):
        opp = 1 if owner == 2 else 2
        foes = _enemy_mobile_ships(game_state, opp)
        heroes = _enemy_mobile_ships(game_state, owner)
        pts = 0.0
        for s in heroes:
            if not any(manhattan_distance((s.x, s.y), (e.x, e.y)) <= contest_radius for e in foes):
                continue
            pts += (
                float(getattr(s, "shots", 0))
                + _ship_available_fighters(s)
                + _ship_available_bombers(s)
            )
        return pts

    return side_total(2) - side_total(1)


def compute_evaluation_features(game_state):
    """Raw features (Player-2 perspective). Dot with merge_eval_weights(...)."""
    feats = {k: 0.0 for k in DEFAULT_EVAL_WEIGHTS}

    center = (game_state.board_size - 1) / 2.0
    center_cap = max(1.0, game_state.board_size / 2.0)
    turn_number = getattr(game_state, "turn_number", 1)
    base_positions = {
        (s.x, s.y) for s in game_state.all_ships if getattr(s, "is_base", False)
    }
    unbased_planets = [p for p in game_state.planets if p not in base_positions]

    stack_map = {}
    for ship in game_state.all_ships:
        if getattr(ship, "is_base", False):
            continue
        stack_map.setdefault((ship.x, ship.y, ship.owner), []).append(ship)

    for (_, _, owner), stack in stack_map.items():
        has_destroyer = any(s.ship_type in DESTROYER_TYPES for s in stack)
        locked_non_destroyers = sum(1 for s in stack if s.ship_type not in DESTROYER_TYPES)
        if locked_non_destroyers and not has_destroyer:
            penalty = MOBILITY_LOCK_PENALTY * locked_non_destroyers
            feats["mobility_lock"] += -penalty if owner == 2 else penalty

    for ship in game_state.all_ships:
        mult = 1.0 if ship.owner == 2 else -1.0
        health_ratio = 0.0 if ship.max_health <= 0 else (ship.hp / ship.max_health)
        fv = float(ship.cost) * 10.0 + (health_ratio * 5.0)
        ship_type_bonus = SHIP_ID_EVAL_MULTIPLIERS.get(getattr(ship, "ship_type_id", 0), 1.0)
        fv *= ship_type_bonus

        if getattr(ship, "is_base", False):
            fv += BASE_VALUE_BONUS
            fv += float(getattr(ship, "scrap", 0)) * 3.0
            if is_base_guarded(game_state, ship):
                fv += 18.0
            else:
                fv -= 22.0
            if turn_number <= 10 and (ship.x, ship.y) in game_state.planets:
                feats["early_base_on_planet"] += mult * EARLY_BASE_EXPANSION_BONUS

        if getattr(ship, "is_charged", False):
            feats["charge_pressure"] += mult * 3.0
        elif getattr(ship, "is_charging", False):
            feats["charge_pressure"] += mult * 1.0

        if ship.ship_type == "Dreadnaught":
            enemies = [
                e for e in game_state.all_ships
                if e.owner != ship.owner and not getattr(e, "is_base", False)
            ]
            if any(manhattan_distance((ship.x, ship.y), (e.x, e.y)) == 2 for e in enemies):
                feats["dread_kiting"] += mult * DREAD_KITING_BONUS
            if any(
                e.ship_type in LIGHT_SHIP_TYPES
                and manhattan_distance((ship.x, ship.y), (e.x, e.y)) <= 3
                for e in enemies
            ):
                feats["dread_light_threat"] += mult * (-DREAD_LIGHT_THREAT_PENALTY)

        if (
            turn_number <= 10
            and not getattr(ship, "is_base", False)
            and not getattr(ship, "is_aircraft_counter", False)
            and unbased_planets
        ):
            nearest_open_planet = min(
                manhattan_distance((ship.x, ship.y), planet) for planet in unbased_planets
            )
            feats["early_planet_pressure"] += mult * (
                max(0.0, 4 - nearest_open_planet) * EARLY_PLANET_PRESSURE_BONUS
            )

        feats["fleet_material_core"] += fv * mult

        dist_to_center = abs(ship.x - center) + abs(ship.y - center)
        feats["center_manhattan_units"] += mult * max(0.0, center_cap - dist_to_center)

        if (
            not getattr(ship, "is_base", False)
            and not getattr(ship, "is_aircraft_counter", False)
        ):
            cheb = max(abs(ship.x - center), abs(ship.y - center))
            if cheb <= EVAL_CORE_BAND_CHEB:
                feats["core_band_occupancy"] += mult * 1.0

    p2_threats = threat_map_for(game_state, 2)
    p1_threats = threat_map_for(game_state, 1)
    threat_balance = 0.0
    for ship in game_state.all_ships:
        if getattr(ship, "is_aircraft_counter", False):
            continue
        pos = (ship.x, ship.y)
        if ship.owner == 1:
            threat_balance += p2_threats.get(pos, 0.0)
        elif ship.owner == 2:
            threat_balance -= p1_threats.get(pos, 0.0)
    feats["threat_balance"] = threat_balance

    for enemy in (s for s in game_state.all_ships if s.owner == 1):
        if focus_fire_potential(game_state, enemy, 2) >= getattr(enemy, "hp", 0) - 1e-9:
            if getattr(enemy, "is_base", False):
                if not is_base_guarded(game_state, enemy):
                    feats["focus_fire_base"] += FOCUS_FIRE_BASE_BONUS
            else:
                feats["focus_fire_kill"] += FOCUS_FIRE_KILL_BONUS
    for friendly in (s for s in game_state.all_ships if s.owner == 2):
        if focus_fire_potential(game_state, friendly, 1) >= getattr(friendly, "hp", 0) - 1e-9:
            if getattr(friendly, "is_base", False):
                if not is_base_guarded(game_state, friendly):
                    feats["focus_fire_base"] -= FOCUS_FIRE_BASE_BONUS
            else:
                feats["focus_fire_kill"] -= FOCUS_FIRE_KILL_BONUS

    for base_ship in (s for s in game_state.all_ships if getattr(s, "is_base", False)):
        safety = base_safety_score(game_state, base_ship)
        if safety is None:
            continue
        side_mult = 1.0 if base_ship.owner == 2 else -1.0
        if safety["guarded"]:
            feats["base_guard"] += side_mult * BASE_GUARD_BONUS
        else:
            feats["base_unguarded"] += side_mult * (-BASE_UNGUARDED_PENALTY)
        if safety["enemy_charged_threat"]:
            feats["base_hyper_threat"] += side_mult * (-BASE_HYPER_THREAT_PENALTY)
        feats["base_defender_hp_term"] += side_mult * min(
            safety["defender_hp"] * 2.0,
            DEFENDER_HP_BONUS_CAP,
        )

    feats["aircraft_dominance"] = aircraft_dominance(game_state, 2) - aircraft_dominance(
        game_state, 1
    )

    la2 = localized_aircraft_dominance_near_contact(game_state, 2, contact_radius=2)
    la1 = localized_aircraft_dominance_near_contact(game_state, 1, contact_radius=2)
    feats["cqb_local_air"] = la2 - la1
    feats["cqb_adjacent_pressure"] = _adjacency_inbound_pressure_raw(game_state)
    feats["cqb_melee_leverage"] = _melee_leverage_trade_raw(game_state)
    feats["cqb_initiative"] = _initiative_contested_raw(game_state)

    return feats


def evaluate_board(game_state, eval_weights_overlay=None):
    """Returns board score from Player 2 (AI) perspective.

    Positive score means Player 2 is ahead, negative means Player 1 is ahead.
    """
    if getattr(game_state, "game_over", False):
        if getattr(game_state, "winner", None) == 2:
            return WIN_SCORE
        if getattr(game_state, "winner", None) == 1:
            return -WIN_SCORE
        return 0.0

    p1_ships = [s for s in game_state.all_ships if s.owner == 1]
    p2_ships = [s for s in game_state.all_ships if s.owner == 2]
    if not p2_ships:
        return -2000.0
    if not p1_ships:
        return 2000.0

    merged = merge_eval_weights(eval_weights_overlay)
    return score_from_features(compute_evaluation_features(game_state), merged)

# Hangar buys add +1 fighter/bomber to the ship at this base tile with highest aircraft_storage.
HANGAR_FIGHTER_KEY = "__HANGAR_FIGHTER__"
HANGAR_BOMBER_KEY = "__HANGAR_BOMBER__"

BUILD_MENU_ORDER = [
    "Destroyer", "Cruiser", "Dreadnaught", "Aircraft Carrier", "Heavy Cruiser",
    "Light Cruiser",
    HANGAR_FIGHTER_KEY,
    HANGAR_BOMBER_KEY,
    "Super Star Destroyer", "Light Destroyer",
]

BUILD_MENU_LABELS = {HANGAR_FIGHTER_KEY: "+1 Fighter (hangar)", HANGAR_BOMBER_KEY: "+1 Bomber (hangar)"}
SCENARIO_POOL = [
    "Destroyer", "Light Destroyer", "Cruiser", "Light Cruiser",
    "Aircraft Carrier", "Dreadnaught", "Heavy Cruiser", "Fighter", "Bomber"
]
FIGHTER_STRIKE_DAMAGE = SHIP_TEMPLATES["Fighter"]["damage"]
BOMBER_STRIKE_DAMAGE = SHIP_TEMPLATES["Bomber"]["damage"]

HYPERDRIVE_MAX_STEPS = 4
_HYPER_KEY_TO_VEC = {"w": (0, -1), "a": (-1, 0), "s": (0, 1), "d": (1, 0)}
_HYPER_VEC_TO_KEY = {(0, -1): "w", (-1, 0): "a", (0, 1): "s", (1, 0): "d"}


def mobile_ships_at(game, x, y, owner):
    return [
        s for s in game.all_ships
        if s.x == x and s.y == y and s.owner == owner
        and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False)
    ]


def aircraft_carrying_capacity_int(ship):
    return max(0, int(round(float(getattr(ship, "aircraft_storage", 0.0)))))


def aircraft_aircraft_stored_total(ship):
    return max(0, int(getattr(ship, "fighters", 0)) + int(getattr(ship, "bombers", 0)))


def aircraft_hangar_space(ship):
    return max(0, aircraft_carrying_capacity_int(ship) - aircraft_aircraft_stored_total(ship))


def pick_hangar_recipient_at_base(game, base_ship):
    """Mobile at same tile as base with the most runway storage that can accept one aircraft."""
    if base_ship is None or not getattr(base_ship, "is_base", False):
        return None
    bx, by, owner = base_ship.x, base_ship.y, base_ship.owner
    candidates = [
        s for s in game.all_ships
        if s.owner == owner and s.x == bx and s.y == by and not getattr(s, "is_base", False)
        and not getattr(s, "is_aircraft_counter", False) and aircraft_carrying_capacity_int(s) >= 1
        and aircraft_hangar_space(s) >= 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (aircraft_carrying_capacity_int(s), s.id))


def fleet_move_budget_for_mobiles(mobiles):
    if not mobiles:
        return 0
    all_light = all(s.ship_type in LIGHT_SHIP_TYPES for s in mobiles)
    return 2 if all_light else 1

class Ship:
    def __init__(self, x, y, owner, ship_id, ship_type="Destroyer", aircraft_storage=0, just_built=False):
        # Constants
        template = SHIP_TEMPLATES.get(ship_type, SHIP_TEMPLATES["Destroyer"])
        self.max_health = template["max_health"]
        self.damage = template["damage"]
        self.range = template["range"]
        self.movement = template["movement"]
        self.fleet_movement = template.get("fleet_movement", 1.0)
        self.cost = template["cost"]
        self.aircraft_storage = aircraft_storage if aircraft_storage != 0 else template["aircraft_storage"]
        self.ship_type = ship_type
        self.is_base = ship_type == "Base"
        self.is_aircraft_counter = ship_type in {"Fighter", "Bomber"}
        self.ship_type_id = SHIP_TYPE_IDS.get(ship_type, 0)
        # Aircraft: only standalone Fighter/Bomber hull ships start with planes.
        # Carrier-line hulls have empty hangars; buy +1 Fighter/Bomber at a base (+ highest storage hull).
        self.fighters = 0
        self.bombers = 0
        if ship_type == "Fighter":
            self.fighters = 1
        elif ship_type == "Bomber":
            self.bombers = 1
        self.damage_profile = template.get("damage_profile", (self.damage,))
        self.range_profile = template.get("range_profile", (self.range,))
        self.scrap = 0
        self.just_built = just_built
        self.move_budget_remaining = 1
        self.did_move_this_turn = False
        
        # Variables
        self.x = x
        self.y = y
        self.start_x = x
        self.start_y = y
        self.owner = owner
        self.id = ship_id
        self.hp = self.max_health
        self.fleet_num = 1
        self.start_fleet_num = 1
        
        # Status Booleans
        self.has_fired = False
        self.has_moved = False
        self.is_selected = False
        self.is_enemy_selected = False
        self.is_reorganizing = False
        self.is_fleeted = False
        self.is_turn = False
        self.is_charging = False
        self.is_charged = False
        self.charge_turns = 0
        # Hyperdrive glide: cardinal lock + count (max 8 one-cell hops per charge).
        self.hyperdrive_dx = None
        self.hyperdrive_dy = None
        self.hyperdrive_steps_used = 0
        self.did_dogfight_this_turn = False
        self.did_hyperdrive_this_turn = False
        self.fighters_used_this_turn = 0
        self.bombers_used_this_turn = 0
        self.pending_bomber_strikes = 0
        self.pending_fighter_strikes = 0
        self.pending_air_center = None
        if ship_type == "Dreadnaught":
            self.shots = 2 if not just_built else 0
        else:
            self.shots = 1 if not just_built else 0
        if just_built:
            self.has_fired = True

        self.fleet_list = []

class GameState:
    def __init__(self):
        self.board_size = 10
        self.ai_vs_ai = False
        self.tuning_mode = False
        self.tuning_seed = 1337
        self.all_ships = []
        self.planets = []
        self.active_player = 1
        self.state_history = []
        self.action_log = []
        self.build_menu_open = False
        self.attack_damage_done_this_turn = False
        self.turn_number = 1
        self.game_over = False
        self.winner = None
        self.build_anchor_base_id = None
        self.setup_board(seed=self.tuning_seed)
        self.next_ship_id = max((s.id for s in self.all_ships), default=-1) + 1
        for ship in self.all_ships:
            ship.is_turn = (ship.owner == self.active_player)
        self._assign_move_budgets_for_turn_start()

    def setup_board(self, seed=None):
        if seed is not None:
            random.seed(seed)
        self.all_ships = []
        self.planets = []

        # Spawn 6 planets on top, then mirror to bottom and vertically reflect bottom.
        for _ in range(6):
            px, py = random.randint(0, self.board_size - 1), random.randint(0, (self.board_size // 2) - 1)
            self.planets.append((px, py))
            bottom_y = (self.board_size - 1) - py
            mirrored_x = (self.board_size - 1) - px
            self.planets.append((mirrored_x, bottom_y))

        # Each side starts as one stacked fleet of Cruiser + 2 Destroyers.
        # Anchor fleets so they begin the same distance from their nearest
        # "first" planet: use the first generated top-hemisphere planet column
        # for P1, and its mirrored column for P2.
        if self.planets:
            # First entry in `planets` is always a top-hemisphere planet from the loop above.
            first_top_px, first_top_py = self.planets[0]
            p1_anchor_x = first_top_px
        else:
            p1_anchor_x = self.board_size // 2
        p1_anchor = (p1_anchor_x, 0)
        p2_anchor = ((self.board_size - 1) - p1_anchor_x, self.board_size - 1)
        starting_pack = ("Cruiser", "Destroyer", "Destroyer")
        sid = 0
        for ship_type in starting_pack:
            self.all_ships.append(Ship(p1_anchor[0], p1_anchor[1], 1, sid, ship_type=ship_type))
            sid += 1
            self.all_ships.append(Ship(p2_anchor[0], p2_anchor[1], 2, sid, ship_type=ship_type))
            sid += 1

    def _setup_skirmish_start(self, seed=None):
        """Symmetric 5×5-style opener: planets + Cruiser stack at mid column ends."""
        if seed is not None:
            random.seed(seed)
        self.all_ships = []
        self.planets = [(1, 1), (3, 3), (0, 2)]
        p1_anchor = (self.board_size // 2, 0)
        p2_anchor = (self.board_size // 2, self.board_size - 1)
        starting_pack = ("Cruiser", "Destroyer", "Destroyer")
        sid = 0
        for ship_type in starting_pack:
            self.all_ships.append(Ship(p1_anchor[0], p1_anchor[1], 1, sid, ship_type=ship_type))
            sid += 1
            self.all_ships.append(Ship(p2_anchor[0], p2_anchor[1], 2, sid, ship_type=ship_type))
            sid += 1

    def reset_match(self, deterministic=False, board_size=None, skirmish_layout=False):
        self.board_size = 10 if board_size is None else int(board_size)
        self.ai_vs_ai = False
        self.active_player = 1
        self.state_history = []
        self.action_log = []
        self.build_menu_open = False
        self.attack_damage_done_this_turn = False
        self.turn_number = 1
        self.game_over = False
        self.winner = None
        self.build_anchor_base_id = None
        seed = self.tuning_seed if deterministic else None
        if skirmish_layout and self.board_size == 5:
            self._setup_skirmish_start(seed=seed)
        else:
            self.setup_board(seed=seed)
        self.next_ship_id = max((s.id for s in self.all_ships), default=-1) + 1
        for ship in self.all_ships:
            ship.is_selected = False
            ship.is_enemy_selected = False
            ship.is_turn = (ship.owner == self.active_player)
            ship.has_moved = False
            ship.has_fired = False
            ship.shots = hull_shots_resting_cap(ship)
            ship.did_move_this_turn = False
            ship.did_dogfight_this_turn = False
            ship.did_hyperdrive_this_turn = False
            ship.fighters_used_this_turn = 0
            ship.bombers_used_this_turn = 0
            ship.pending_bomber_strikes = 0
            ship.pending_fighter_strikes = 0
            ship.pending_air_center = None
        self._assign_move_budgets_for_turn_start()
        self.save_state("Start of Turn")

    def toggle_tuning_mode(self):
        self.tuning_mode = not self.tuning_mode
        status = "ON" if self.tuning_mode else "OFF"
        self.action_log = [f"Tuning mode: {status}"]

    def load_tuning_scenario(self, scenario_id):
        if scenario_id not in (1, 2, 3, 4, 5, 6, 7):
            return
        self.active_player = 1
        self.state_history = []
        self.action_log = (
            [f"Loaded tuning scenario {scenario_id} — 5x5 vs AI P2, 3 planets (you are P1)"]
            if scenario_id == 7
            else [f"Loaded tuning scenario {scenario_id}"]
        )
        self.attack_damage_done_this_turn = False
        self.turn_number = 1
        self.game_over = False
        self.winner = None
        self.planets = []
        self.all_ships = []

        random.seed((self.tuning_seed + scenario_id + random.randint(0, 10000)))
        if scenario_id == 7:
            # 5x5 arena, 3 planets — human P1 vs AI P2 (main enables P2 AI).
            self.board_size = 5
            self.ai_vs_ai = False
            self.planets = [(1, 1), (3, 3), (0, 2)]
            p1_cells = [(2, 0), (2, 0), (1, 0)]
            p2_cells = [(2, 4), (2, 4), (3, 4)]
        else:
            self.board_size = 10
            self.ai_vs_ai = False
            if scenario_id == 1:
                p1_cells = [(4, 4), (4, 4), (4, 5), (5, 5)]
                p2_cells = [(5, 4), (5, 4), (5, 3), (4, 3)]
            elif scenario_id == 2:
                p1_cells = [(3, 5), (3, 5), (4, 5), (4, 4), (5, 5)]
                p2_cells = [(6, 4), (6, 4), (5, 4), (5, 3), (4, 4)]
            elif scenario_id == 3:
                p1_cells = [(3, 4), (3, 4), (3, 5), (4, 5), (4, 4), (5, 5)]
                p2_cells = [(6, 5), (6, 5), (6, 4), (5, 4), (5, 5), (4, 4)]
            elif scenario_id == 4:
                p1_cells = [(2, 4), (2, 4), (3, 4), (3, 5), (4, 5), (4, 4), (5, 5)]
                p2_cells = [(7, 5), (7, 5), (6, 5), (6, 4), (5, 4), (5, 5), (4, 4)]
            elif scenario_id == 5:
                p1_cells = [(3, 3), (3, 3), (3, 4), (4, 4), (4, 5), (5, 5), (5, 4)]
                p2_cells = [(6, 6), (6, 6), (6, 5), (5, 5), (5, 4), (4, 4), (4, 5)]
            else:  # scenario 6
                p1_cells = [(2, 5), (2, 5), (3, 5), (3, 4), (4, 4), (4, 5), (5, 5), (5, 4)]
                p2_cells = [(7, 4), (7, 4), (6, 4), (6, 5), (5, 5), (5, 4), (4, 4), (4, 5)]

        sid = 0
        # Ensure each side has a premade destroyer-containing fleet anchor.
        p1_anchor = p1_cells[0]
        p2_anchor = p2_cells[0]
        self.all_ships.append(Ship(p1_anchor[0], p1_anchor[1], 1, sid, ship_type="Destroyer"))
        sid += 1
        self.all_ships.append(Ship(p2_anchor[0], p2_anchor[1], 2, sid, ship_type="Destroyer"))
        sid += 1

        # Random bomber amounts per side in tuning scenarios.
        p1_bombers = random.randint(1, min(3, len(p1_cells)))
        p2_bombers = random.randint(1, min(3, len(p2_cells)))
        p1_cells_bomber = p1_cells[:p1_bombers]
        p2_cells_bomber = p2_cells[:p2_bombers]
        p1_cells_rest = p1_cells[p1_bombers:]
        p2_cells_rest = p2_cells[p2_bombers:]

        for pos in p1_cells_bomber:
            self.all_ships.append(Ship(pos[0], pos[1], 1, sid, ship_type="Bomber"))
            sid += 1
        for pos in p2_cells_bomber:
            self.all_ships.append(Ship(pos[0], pos[1], 2, sid, ship_type="Bomber"))
            sid += 1
        for pos in p1_cells_rest:
            st = random.choice(SCENARIO_POOL)
            self.all_ships.append(Ship(pos[0], pos[1], 1, sid, ship_type=st))
            sid += 1
        for pos in p2_cells_rest:
            st = random.choice(SCENARIO_POOL)
            self.all_ships.append(Ship(pos[0], pos[1], 2, sid, ship_type=st))
            sid += 1

        for ship in self.all_ships:
            ship.is_selected = False
            ship.is_enemy_selected = False
            ship.is_turn = (ship.owner == self.active_player)
            ship.has_moved = False
            ship.has_fired = False
            ship.shots = hull_shots_resting_cap(ship)
            ship.did_move_this_turn = False
            ship.did_dogfight_this_turn = False
            ship.did_hyperdrive_this_turn = False
            ship.fighters_used_this_turn = 0
            ship.bombers_used_this_turn = 0
            ship.pending_bomber_strikes = 0
            ship.pending_fighter_strikes = 0
            ship.pending_air_center = None
        self.next_ship_id = max((s.id for s in self.all_ships), default=-1) + 1
        self.build_menu_open = False
        self._assign_move_budgets_for_turn_start()
        self.save_state("Start of Turn")

    def _assign_move_budgets_for_turn_start(self):
        for ship in self.all_ships:
            ship.did_move_this_turn = False
            if getattr(ship, "is_base", False):
                ship.move_budget_remaining = 0
        seen_cell = set()
        for anchor in self.all_ships:
            if getattr(anchor, "is_base", False):
                continue
            k = (anchor.x, anchor.y, anchor.owner)
            if k in seen_cell:
                continue
            seen_cell.add(k)
            mobiles = mobile_ships_at(self, anchor.x, anchor.y, anchor.owner)
            budget = fleet_move_budget_for_mobiles(mobiles)
            for mobile in mobiles:
                mobile.move_budget_remaining = budget

    def base_at(self, x, y):
        for s in self.all_ships:
            if getattr(s, "is_base", False) and s.x == x and s.y == y:
                return s
        return None

    def can_target_ship(self, target_ship):
        if target_ship is None:
            return False
        if getattr(target_ship, "is_base", False) and is_base_guarded(self, target_ship):
            return False
        return True

    def _neighbor_hangar_recipients_for_aircraft(self, x, y, owner, excluded_ids):
        """Ortho-adjacent friendly hulls that can absorb at least one stored plane."""
        out = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < self.board_size and 0 <= ny < self.board_size):
                continue
            for s in self.all_ships:
                if s.hp <= 0 or s.id in excluded_ids:
                    continue
                if s.x != nx or s.y != ny or s.owner != owner:
                    continue
                if getattr(s, "is_aircraft_counter", False) or getattr(s, "is_base", False):
                    continue
                if aircraft_carrying_capacity_int(s) < 1 or aircraft_hangar_space(s) < 1:
                    continue
                out.append(s)
        out.sort(key=lambda q: (-aircraft_hangar_space(q), -aircraft_carrying_capacity_int(q), q.id))
        return out

    def _redirect_hangar_aircraft(self, doomed, doomed_and_peer_ids):
        """Fighters evacuate before bombers; planes without adjacent hangar capacity are lost."""
        if getattr(doomed, "is_base", False) or getattr(doomed, "is_aircraft_counter", False):
            return
        fl = max(0, self._available_fighters(doomed))
        bl = max(0, self._available_bombers(doomed))
        if fl == 0 and bl == 0:
            return
        receivers = self._neighbor_hangar_recipients_for_aircraft(doomed.x, doomed.y, doomed.owner, doomed_and_peer_ids)
        rescued_f = rescued_b = lost_f = lost_b = 0
        while fl > 0:
            receivers.sort(key=lambda q: (-aircraft_hangar_space(q), q.id))
            recv = next((r for r in receivers if aircraft_hangar_space(r) >= 1), None)
            if recv is None:
                lost_f += fl
                break
            recv.fighters = int(recv.fighters) + 1
            fl -= 1
            rescued_f += 1
        while bl > 0:
            receivers.sort(key=lambda q: (-aircraft_hangar_space(q), q.id))
            recv = next((r for r in receivers if aircraft_hangar_space(r) >= 1), None)
            if recv is None:
                lost_b += bl
                break
            recv.bombers = int(recv.bombers) + 1
            bl -= 1
            rescued_b += 1
        if rescued_f or rescued_b or lost_f or lost_b:
            self.action_log.append(
                f"Scramble from sunk {doomed.ship_type}: +{rescued_f} fighters, +{rescued_b} bombers evacuated; "
                f"{lost_f} fighters and {lost_b} bombers had no adjacent hangar."
            )

    def _cleanup_destroyed_ships(self):
        destroyed = [s for s in self.all_ships if s.hp <= 0]
        if not destroyed:
            return
        destroy_ids = {s.id for s in destroyed}

        enemy_sel_meta = None
        for ship in self.all_ships:
            if getattr(ship, "is_enemy_selected", False):
                enemy_sel_meta = (ship.x, ship.y, ship.owner, ship.id)
                break

        destroyed_bases_meta = [s for s in destroyed if getattr(s, "is_base", False)]

        for d in destroyed:
            self._redirect_hangar_aircraft(d, destroy_ids)

        self.all_ships = [s for s in self.all_ships if s.hp > 0]

        if enemy_sel_meta is not None:
            ex, ey, eowner, eid = enemy_sel_meta
            if eid in destroy_ids:
                mates = sorted(
                    [
                        s
                        for s in self.all_ships
                        if s.x == ex and s.y == ey and s.owner == eowner
                        and not getattr(s, "is_aircraft_counter", False)
                    ],
                    key=lambda m: m.id,
                )
                for ship in self.all_ships:
                    ship.is_enemy_selected = False
                pick = mates[0] if mates else None
                if pick is not None:
                    pick.is_enemy_selected = True

        if destroyed_bases_meta and not self.game_over:
            blown_base = destroyed_bases_meta[0]
            self.game_over = True
            self.winner = 2 if blown_base.owner == 1 else 1
            self.action_log.append(
                f"Base destroyed at ({blown_base.x},{blown_base.y}). Player {self.winner} wins!"
            )

    def try_spawn_base_on_planet(self, ship):
        if getattr(ship, "is_base", False):
            return
        pos = (ship.x, ship.y)
        if pos not in self.planets:
            return
        if self.base_at(ship.x, ship.y) is not None:
            return
        nid = self.next_ship_id
        self.next_ship_id += 1
        base_ship = Ship(ship.x, ship.y, ship.owner, nid, ship_type="Base")
        self.all_ships.append(base_ship)
        self.action_log.append(f"Base established at ({ship.x},{ship.y}) for P{ship.owner}")

    def _dogfight_tiles(self, x, y):
        # 4-neighborhood + center.
        tiles = [(x, y)]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.board_size and 0 <= ny < self.board_size:
                tiles.append((nx, ny))
        return tiles

    def _is_in_dogfight_space(self, center, ship):
        cx, cy = center
        return abs(ship.x - cx) + abs(ship.y - cy) <= 1

    def _available_fighters(self, ship):
        return max(0, getattr(ship, "fighters", 0) - getattr(ship, "fighters_used_this_turn", 0))

    def _available_bombers(self, ship):
        return max(0, getattr(ship, "bombers", 0) - getattr(ship, "bombers_used_this_turn", 0))

    def _mark_attackers_used(self, ships):
        for ship in ships:
            ship.fighters_used_this_turn += self._available_fighters(ship)
            ship.bombers_used_this_turn += self._available_bombers(ship)

    def _mark_defender_fighters_used(self, ships, fighters_to_use):
        remaining = fighters_to_use
        for ship in sorted(ships, key=lambda s: s.id):
            if remaining <= 0:
                break
            usable = min(self._available_fighters(ship), remaining)
            ship.fighters_used_this_turn += usable
            remaining -= usable

    def _resolve_air_dogfight(self, attacker, target_ship):
        tx, ty = target_ship.x, target_ship.y
        zone_tiles = set(self._dogfight_tiles(tx, ty))

        friends = [
            s for s in self.all_ships
            if s.owner == attacker.owner
            and not getattr(s, "is_base", False)
            and (s.x, s.y) in zone_tiles
        ]
        enemies = [
            s for s in self.all_ships
            if s.owner != attacker.owner
            and not getattr(s, "is_base", False)
            and (s.x, s.y) in zone_tiles
        ]

        a_f = sum(self._available_fighters(s) for s in friends)
        a_b = sum(self._available_bombers(s) for s in friends)
        d_f = sum(self._available_fighters(s) for s in enemies)

        fighter_repels = min(a_f, d_f)
        surviving_fighters = a_f - fighter_repels
        bomber_repels = min(a_b, d_f - fighter_repels)
        surviving_bombers = a_b - bomber_repels

        damage = (
            surviving_fighters * FIGHTER_STRIKE_DAMAGE
            + surviving_bombers * BOMBER_STRIKE_DAMAGE
        )
        self._mark_attackers_used(friends)
        self._mark_defender_fighters_used(enemies, fighter_repels + bomber_repels)
        attacker.pending_bomber_strikes = surviving_bombers
        attacker.pending_fighter_strikes = surviving_fighters
        attacker.pending_air_center = (tx, ty)

        def fmt(v):
            if isinstance(v, (int, float)) and float(v).is_integer():
                return str(int(v))
            return f"{v:.2f}".rstrip("0").rstrip(".")

        self.action_log.append(
            f"Dogfight: F{fmt(a_f)} B{fmt(a_b)} vs F{fmt(d_f)}; "
            f"repelled F{fmt(fighter_repels)}+B{fmt(bomber_repels)}; "
            f"damage {fmt(damage)}"
        )

    def _has_aircraft_in_zone(self, owner, center):
        cx, cy = center
        for s in self.all_ships:
            if s.owner != owner or getattr(s, "is_base", False):
                continue
            if abs(s.x - cx) + abs(s.y - cy) <= 1 and (self._available_fighters(s) + self._available_bombers(s)) > 0:
                return True
        return False

    def save_state(self, tag):
        # Deep copy all ships and active player
        snapshot = {
            "tag": tag,
            "ships": copy.deepcopy(self.all_ships),
            "active_player": self.active_player,
            "attack_damage_done_this_turn": self.attack_damage_done_this_turn,
            "turn_number": self.turn_number,
            "game_over": self.game_over,
            "winner": self.winner,
            "next_ship_id": self.next_ship_id,
            "build_menu_open": self.build_menu_open,
            "build_anchor_base_id": getattr(self, "build_anchor_base_id", None),
            "board_size": self.board_size,
            "ai_vs_ai": getattr(self, "ai_vs_ai", False),
        }
        self.state_history.append(snapshot)

    def reset_to_turn_start(self):
        # RRR logic: find last 'Start of Turn'
        for state in reversed(self.state_history):
            if state["tag"] == "Start of Turn":
                self.all_ships = copy.deepcopy(state["ships"])
                self.active_player = state["active_player"]
                self.attack_damage_done_this_turn = state.get("attack_damage_done_this_turn", False)
                self.turn_number = state.get("turn_number", 1)
                self.game_over = state.get("game_over", False)
                self.winner = state.get("winner")
                self.next_ship_id = state.get("next_ship_id", self.next_ship_id)
                self.build_menu_open = state.get("build_menu_open", False)
                self.build_anchor_base_id = state.get("build_anchor_base_id")
                self.board_size = state.get("board_size", 10)
                self.ai_vs_ai = state.get("ai_vs_ai", False)
                self.action_log = ["Turn reset to start state."]
                break

    def undo_last_action(self):
        # R logic: pop last snapshot
        if len(self.state_history) > 1:
            state = self.state_history.pop()
            self.all_ships = copy.deepcopy(state["ships"])
            self.active_player = state["active_player"]
            self.attack_damage_done_this_turn = state.get("attack_damage_done_this_turn", False)
            self.turn_number = state.get("turn_number", 1)
            self.game_over = state.get("game_over", False)
            self.winner = state.get("winner")
            self.next_ship_id = state.get("next_ship_id", self.next_ship_id)
            self.build_menu_open = state.get("build_menu_open", False)
            self.build_anchor_base_id = state.get("build_anchor_base_id")
            self.board_size = state.get("board_size", 10)
            self.ai_vs_ai = state.get("ai_vs_ai", False)

    def switch_turns(self):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        # Resolve charge progress for current player's ending turn.
        for s in self.all_ships:
            if s.owner != self.active_player:
                continue
            if s.is_charging:
                if s.has_moved or s.has_fired:
                    s.is_charging = False
                    s.is_charged = False
                    s.charge_turns = 0
                else:
                    s.charge_turns += 1
                    if s.charge_turns >= 1:
                        s.is_charged = True
                        s.is_charging = False

        # X switches turns, changes active player, unselects ships
        self.active_player = 2 if self.active_player == 1 else 1
        if self.active_player == 1:
            self.turn_number += 1
        self.attack_damage_done_this_turn = False
        for s in self.all_ships:
            if getattr(s, "is_base", False) and s.owner == self.active_player:
                s.scrap += 1
            if s.owner == self.active_player:
                s.just_built = False
            s.is_selected = False
            s.is_enemy_selected = False
            s.is_turn = (s.owner == self.active_player)
            if s.is_charging:
                s.is_charged = True
                s.is_charging = False
            s.has_moved = False
            s.has_fired = False
            s.shots = hull_shots_resting_cap(s)
            s.did_move_this_turn = False
            s.did_dogfight_this_turn = False
            s.did_hyperdrive_this_turn = False
            s.fighters_used_this_turn = 0
            s.bombers_used_this_turn = 0
            s.pending_bomber_strikes = 0
            s.pending_fighter_strikes = 0
            s.pending_air_center = None
            s.start_x, s.start_y = s.x, s.y
            s.hyperdrive_dx = None
            s.hyperdrive_dy = None
            s.hyperdrive_steps_used = 0
        self.build_menu_open = False
        self.build_anchor_base_id = None
        self._assign_move_budgets_for_turn_start()
        self.save_state("Start of Turn")

    def handle_c_press(self, ship):
        """Charge / hyperdrive key behavior:
        - If charged: arm hyperdrive.
        - Else: start charging (must end turn without move/fire).
        """
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return False
        if ship.owner != self.active_player or getattr(ship, "is_base", False):
            self.action_log = ["Cannot charge this selection."]
            return False
        if ship.is_charged:
            steps = getattr(ship, "hyperdrive_steps_used", 0) or 0
            if steps > 0:
                move_group = mobile_ships_at(self, ship.x, ship.y, ship.owner)
                if not move_group or ship not in move_group:
                    move_group = [ship]
                self._finalize_hyperdrive_glide(move_group, consumed_action=True)
                self.action_log = ["Hyperdrive stopped early."]
                return False
            self.action_log = [
                "Hyperdrive: each WASD moves 1 tile in a locked line "
                f"(max {HYPERDRIVE_MAX_STEPS}); press C again to finish before using all steps.",
            ]
            return True
        if ship.is_charging:
            self.action_log = ["Already charging; end turn without moving/firing."]
            return False
        if (ship.x, ship.y) != (ship.start_x, ship.start_y):
            self.action_log = ["Charge denied: must charge from your start-of-turn space (R to reset)."]
            return False
        ship.is_charging = True
        ship.is_charged = False
        ship.charge_turns = 0
        ship.hyperdrive_dx = None
        ship.hyperdrive_dy = None
        ship.hyperdrive_steps_used = 0
        self.action_log = ["Charging started. End turn without movement/fire; next turn WASD will hyperdrive."]
        return False

    def select_ship_at(self, x, y, is_enemy_click):
        if x < 0 or y < 0 or x >= self.board_size or y >= self.board_size:
            return

        # Mouse click logic
        target_owner = 2 if self.active_player == 1 else 1
        if not is_enemy_click: target_owner = self.active_player
        
        for ship in self.all_ships:
            if is_enemy_click: ship.is_enemy_selected = False
            else: ship.is_selected = False

        candidates = [
            s for s in self.all_ships
            if s.x == x and s.y == y and s.owner == target_owner and not getattr(s, "is_aircraft_counter", False)
        ]
        if not candidates:
            return
        if is_enemy_click:
            mobiles = [s for s in candidates if not getattr(s, "is_base", False)]
            bases = [
                s for s in candidates
                if getattr(s, "is_base", False) and self.can_target_ship(s)
            ]
            pick_pool = mobiles if mobiles else bases
            if not pick_pool:
                return
            pick = sorted(pick_pool, key=lambda s: s.id)[0]
            pick.is_enemy_selected = True
        else:
            bases = [s for s in candidates if getattr(s, "is_base", False)]
            mobiles = [s for s in candidates if not getattr(s, "is_base", False)]
            pick = mobiles[0] if mobiles else bases[0]
            pick.is_selected = True

    def handle_space_click(self, x, y):
        """Click behavior for mixed stacks:
        1) first click picks friendly stack ship
        2) click same space again sets enemy_selected if enemy stack exists
        """
        if self.game_over:
            return
        if x < 0 or y < 0 or x >= self.board_size or y >= self.board_size:
            return
        friendly = [
            s for s in self.all_ships
            if s.x == x and s.y == y and s.owner == self.active_player and not getattr(s, "is_aircraft_counter", False)
        ]
        enemy_owner = 2 if self.active_player == 1 else 1
        enemies = [
            s for s in self.all_ships
            if s.x == x and s.y == y and s.owner == enemy_owner and not getattr(s, "is_aircraft_counter", False)
        ]
        selected = next((s for s in self.all_ships if s.is_selected), None)

        if friendly:
            # Always select friendly on click.
            self.select_ship_at(x, y, False)
            # If already selected this same tile and enemies exist, set enemy selected too.
            if selected and selected.x == x and selected.y == y and enemies:
                self.select_ship_at(x, y, True)
            return
        if enemies:
            self.select_ship_at(x, y, True)

    def _fleet_broadcast_hyper_metadata(self, anchor, move_group):
        """Keep glide counters/direction synced across stacked mobiles."""
        for m in move_group:
            m.hyperdrive_dx = anchor.hyperdrive_dx
            m.hyperdrive_dy = anchor.hyperdrive_dy
            m.hyperdrive_steps_used = anchor.hyperdrive_steps_used

    def _finalize_hyperdrive_glide(self, move_group, *, consumed_action):
        """Ends a glide (charge spent). consumed_action iff the ship actually moved this glide."""
        if not move_group:
            return
        for m in move_group:
            m.hyperdrive_dx = None
            m.hyperdrive_dy = None
            m.hyperdrive_steps_used = 0
            m.is_charging = False
            m.is_charged = False
            m.charge_turns = 0
            if consumed_action:
                m.has_moved = True
                m.did_move_this_turn = True
                m.move_budget_remaining = 0

    def hyperdrive_move(self, ship, key):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        if ship.owner != self.active_player or getattr(ship, "is_base", False):
            self.action_log = ["Hyperdrive denied."]
            return
        if key not in _HYPER_KEY_TO_VEC:
            return
        if not ship.is_charged:
            self.action_log = ["Hyperdrive denied: ship is not charged yet."]
            return
        if ship.has_moved or ship.has_fired:
            self.action_log = ["Hyperdrive denied: ship already acted."]
            return

        move_group = mobile_ships_at(self, ship.x, ship.y, ship.owner)
        if not move_group or ship not in move_group:
            move_group = [ship]

        vx, vy = _HYPER_KEY_TO_VEC[key]
        steps_used = getattr(ship, "hyperdrive_steps_used", 0) or 0

        if steps_used == 0:
            ship.hyperdrive_dx, ship.hyperdrive_dy = vx, vy
        elif (ship.hyperdrive_dx, ship.hyperdrive_dy) != (vx, vy):
            lock = _HYPER_VEC_TO_KEY.get((ship.hyperdrive_dx, ship.hyperdrive_dy), "?")
            self.action_log = [
                f"Hyperdrive locked to [{lock.upper()}]; same direction for each step ({HYPERDRIVE_MAX_STEPS} max), or C to stop.",
            ]
            return

        self._fleet_broadcast_hyper_metadata(ship, move_group)

        nx = max(0, min(self.board_size - 1, ship.x + vx))
        ny = max(0, min(self.board_size - 1, ship.y + vy))
        incoming_ids = {s.id for s in move_group}
        if (nx, ny) == (ship.x, ship.y):
            if steps_used == 0:
                ship.hyperdrive_dx = ship.hyperdrive_dy = None
                self._fleet_broadcast_hyper_metadata(ship, move_group)
                self.action_log = ["Hyperdrive blocked by map edge."]
                return
            self._finalize_hyperdrive_glide(move_group, consumed_action=True)
            self.action_log = [f"Hyperdrive ended at edge after {steps_used} step(s); now ({ship.x},{ship.y})."]
            return

        blocker = next(
            (
                b
                for b in self.all_ships
                if b.id not in incoming_ids
                and b.x == nx
                and b.y == ny
            ),
            None,
        )
        planet_block = (nx, ny) in self.planets

        if blocker is not None or planet_block:
            if steps_used == 0:
                ship.hyperdrive_dx = ship.hyperdrive_dy = None
                self._fleet_broadcast_hyper_metadata(ship, move_group)
                self.action_log = [
                    "Hyperdrive blocked: planet or obstacle in next square; stayed in place.",
                ]
                return
            self._finalize_hyperdrive_glide(move_group, consumed_action=True)
            reason = "planet" if planet_block else "obstacle"
            self.action_log = [
                f"Hyperdrive stopped short before {reason} after {steps_used} step(s); holding ({ship.x},{ship.y}).",
            ]
            return

        for mover in move_group:
            mover.x = nx
            mover.y = ny
            mover.did_hyperdrive_this_turn = True

        ship.hyperdrive_steps_used = steps_used + 1
        self._fleet_broadcast_hyper_metadata(ship, move_group)
        for mover in move_group:
            self.try_spawn_base_on_planet(mover)

        stepped = ship.hyperdrive_steps_used
        done = stepped >= HYPERDRIVE_MAX_STEPS

        if done:
            self._finalize_hyperdrive_glide(move_group, consumed_action=True)
            why = "max range"
            self.action_log = [
                f"Hyperdrive ({why}): {stepped} step(s) → ({ship.x},{ship.y})",
            ]
        else:
            self.action_log = [
                f"Hyperdrive step {stepped}/{HYPERDRIVE_MAX_STEPS} → ({ship.x},{ship.y}); repeat [{key.upper()}] or C to stop.",
            ]

    def base_for_build_commands(self):
        """Return the allied base granting builds for the current selection (base tile or docked fleet)."""
        sel = next((s for s in self.all_ships if getattr(s, "is_selected", False)), None)
        if sel is None:
            return None
        if sel.owner != self.active_player:
            return None
        if getattr(sel, "is_base", False):
            return sel
        b = self.base_at(sel.x, sel.y)
        if b is not None and b.owner == sel.owner:
            return b
        return None

    def toggle_build_menu(self):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        base_ship = self.base_for_build_commands()
        if base_ship is None:
            self.build_menu_open = False
            self.build_anchor_base_id = None
            self.action_log = [
                "B: Select one of your ships on a planet with a base — or select the base — to open builds.",
            ]
            return
        self.build_menu_open = not self.build_menu_open
        if self.build_menu_open:
            self.build_anchor_base_id = base_ship.id
            self.action_log = [f"Build menu open — scrap {base_ship.scrap:g} (base hull #{base_ship.id})."]
        else:
            self.build_anchor_base_id = None
            self.action_log = ["Build menu closed."]

    def try_build_ship(self, slot_index_one_based):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        if not self.build_menu_open:
            return
        base = None
        if getattr(self, "build_anchor_base_id", None) is not None:
            base = next(
                (
                    s
                    for s in self.all_ships
                    if s.id == self.build_anchor_base_id
                    and getattr(s, "is_base", False)
                    and s.hp > 0
                ),
                None,
            )
        if base is None:
            base = self.base_for_build_commands()
        if not base or base.owner != self.active_player:
            self.action_log = [
                "Build denied: reopen the menu with B while a docked fleet or the base planet is selected.",
            ]
            return
        idx = slot_index_one_based - 1
        if not (0 <= idx < len(BUILD_MENU_ORDER)):
            return
        entry = BUILD_MENU_ORDER[idx]
        if entry == HANGAR_FIGHTER_KEY:
            cost = SHIP_TEMPLATES["Fighter"]["cost"]
            if base.scrap + 1e-9 < cost:
                self.action_log = [f"Not enough scrap (need {cost}, have {base.scrap})."]
                return
            recipient = pick_hangar_recipient_at_base(self, base)
            if recipient is None:
                self.action_log = ["Hangar denied: no ship with runway space docked at this base."]
                return
            self.save_state("Pre-Build")
            base.scrap -= cost
            recipient.fighters = int(recipient.fighters) + 1
            self.action_log = [
                f"Bought fighter for {recipient.ship_type} (hangar "
                f"{aircraft_aircraft_stored_total(recipient)}/{aircraft_carrying_capacity_int(recipient)}).",
            ]
            self.build_menu_open = False
            self.build_anchor_base_id = None
            self._assign_move_budgets_for_turn_start()
            return
        if entry == HANGAR_BOMBER_KEY:
            cost = SHIP_TEMPLATES["Bomber"]["cost"]
            if base.scrap + 1e-9 < cost:
                self.action_log = [f"Not enough scrap (need {cost}, have {base.scrap})."]
                return
            recipient = pick_hangar_recipient_at_base(self, base)
            if recipient is None:
                self.action_log = ["Hangar denied: no ship with runway space docked at this base."]
                return
            self.save_state("Pre-Build")
            base.scrap -= cost
            recipient.bombers = int(recipient.bombers) + 1
            self.action_log = [
                f"Bought bomber for {recipient.ship_type} (hangar "
                f"{aircraft_aircraft_stored_total(recipient)}/{aircraft_carrying_capacity_int(recipient)}).",
            ]
            self.build_menu_open = False
            self.build_anchor_base_id = None
            self._assign_move_budgets_for_turn_start()
            return

        ship_type = entry
        cost = SHIP_TEMPLATES[ship_type]["cost"]
        if base.scrap + 1e-9 < cost:
            self.action_log = [f"Not enough scrap (need {cost}, have {base.scrap})."]
            return
        # Composition rules: simulate adding the new hull to the base tile's
        # current mobile stack and reject if it would break Dreadnaught
        # exclusivity or the max-4-capitals cap.
        prospective_ship = Ship(base.x, base.y, base.owner, -1, ship_type=ship_type, just_built=True)
        existing_mobiles = mobile_ships_at(self, base.x, base.y, base.owner)
        violation_b = _fleet_rule_violation(list(existing_mobiles) + [prospective_ship])
        if violation_b:
            if "Dreadnaught" in violation_b:
                self.action_log = [
                    "Build denied: Dreadnaught cannot fleet with Cruiser / Heavy Cruiser / Aircraft Carrier."
                ]
            else:
                self.action_log = ["Build denied: max 4 large ships per fleet."]
            return
        self.save_state("Pre-Build")
        base.scrap -= cost
        new_id = self.next_ship_id
        self.next_ship_id += 1
        new_ship = Ship(base.x, base.y, base.owner, new_id, ship_type=ship_type, just_built=True)
        self.all_ships.append(new_ship)
        self.action_log = [f"Built {ship_type} at ({base.x},{base.y}); cannot attack until next activation."]
        self.build_menu_open = False
        self.build_anchor_base_id = None
        self._assign_move_budgets_for_turn_start()

    def update_stats(self, ship, target_ship, key, prev_key):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        if ship.owner != self.active_player:
            self.action_log = [f"Not your turn. Player {self.active_player} acts now."]
            return
        if getattr(ship, "is_base", False):
            self.action_log = ["Base has no movement. Press B for build."]
            return

        if ship.is_charging and key in ['w', 'a', 's', 'd', 'f']:
            ship.is_charging = False
            ship.is_charged = False
            ship.charge_turns = 0
            ship.hyperdrive_dx = None
            ship.hyperdrive_dy = None
            ship.hyperdrive_steps_used = 0
            self.action_log = ["Charging interrupted by action."]

        if key in ['w', 'a', 's', 'd']:
            move_group_early = mobile_ships_at(self, ship.x, ship.y, ship.owner)
            if not move_group_early or ship not in move_group_early:
                self.action_log = ["Cannot move selection."]
                return
            # Rulebook movement gate:
            # non-destroyers must be fleeted with a destroyer-class ship to move.
            has_destroyer_in_stack = any(s.ship_type in DESTROYER_TYPES for s in move_group_early)
            if ship.ship_type not in DESTROYER_TYPES and not has_destroyer_in_stack:
                self.action_log = ["Movement denied: non-destroyers must be fleeted with a destroyer."]
                return
            pool_early = min(m.move_budget_remaining for m in move_group_early)
            if pool_early <= 0:
                self.action_log = ["No move budget remaining."]
                return
            dx_early, dy_early = 0, 0
            if key == 'w':
                dy_early = -1
            if key == 'a':
                dx_early = -1
            if key == 's':
                dy_early = 1
            if key == 'd':
                dx_early = 1
            dest_x = max(0, min(self.board_size - 1, ship.x + dx_early))
            dest_y = max(0, min(self.board_size - 1, ship.y + dy_early))
            incoming_ids = {s.id for s in move_group_early}
            destination_friendlies = [
                s for s in self.all_ships
                if s.owner == ship.owner
                and not getattr(s, "is_base", False)
                and not getattr(s, "is_aircraft_counter", False)
                and s.id not in incoming_ids
                and s.x == dest_x and s.y == dest_y
            ]
            if self.attack_damage_done_this_turn and destination_friendlies:
                self.action_log = ["Fleet/defleet locked after first attack damage this turn."]
                return
            # Composition rules for the post-merge stack at the destination.
            stack_after = list(move_group_early) + list(destination_friendlies)
            violation = _fleet_rule_violation(stack_after)
            if violation:
                self.action_log = [violation]
                return

        if key == 'f':
            if getattr(ship, "just_built", False):
                self.action_log = ["New ships cannot fire until your next activation."]
                return

        # Player-facing HUD: keep concise action lines (no fleet debug graph).
        self.action_log = []
        self.save_state("Pre-Action")

        # Update Fleet List (mobile allies on same tile; bases stay docked)
        mobiles_here_now = mobile_ships_at(self, ship.x, ship.y, ship.owner)
        ship.fleet_list = [s for s in mobiles_here_now if s.id != ship.id]
        ship.is_fleeted = len(ship.fleet_list) > 0
        for f_ship in ship.fleet_list:
            f_ship.is_fleeted = True
        
        # Determine Reorganization
        ship.fleet_num = 1 + len(ship.fleet_list)
        if ship.fleet_num != ship.start_fleet_num:
            ship.is_reorganizing = True
            for f_ship in ship.fleet_list: f_ship.is_reorganizing = True

        # Movement: mobiles move together; light-only stacks budget 2, mixed stacks 1 step/turn pool.
        if key in ['w', 'a', 's', 'd']:
            dx, dy = 0, 0
            if key == 'w':
                dy = -1
            if key == 'a':
                dx = -1
            if key == 's':
                dy = 1
            if key == 'd':
                dx = 1

            move_group = mobile_ships_at(self, ship.x, ship.y, ship.owner)
            shared = min(m.move_budget_remaining for m in move_group)
            for mover in move_group:
                mover.move_budget_remaining = shared

            old_positions = {s.id: (s.x, s.y) for s in move_group}
            for moving_ship in move_group:
                moving_ship.x = max(0, min(self.board_size - 1, moving_ship.x + dx))
                moving_ship.y = max(0, min(self.board_size - 1, moving_ship.y + dy))

            moved = any(
                (moving_ship.x, moving_ship.y) != old_positions[moving_ship.id]
                for moving_ship in move_group
            )
            if moved:
                new_pool = shared - 1
                remaining = max(0, new_pool)
                for moving_ship in move_group:
                    moving_ship.did_move_this_turn = True
                    moving_ship.move_budget_remaining = remaining
                    moving_ship.has_moved = remaining <= 0
                self.action_log.append(
                    f"Action A: {'Fleet moved' if len(move_group) > 1 else 'Moved'} "
                    f"{key} (budget left {remaining})"
                )
                for moving_ship in move_group:
                    self.try_spawn_base_on_planet(moving_ship)
            else:
                self.action_log.append("Action A: Blocked by map edge")

        # Firing Logic
        if key == 'f' and target_ship:
            etyp = getattr(target_ship, "ship_type", "?")
            if not self.can_target_ship(target_ship):
                self.action_log.append(
                    f"F: {ship.ship_type} selected vs {etyp}, but guarded bases cannot be attacked until defenders leave.",
                )
                return
            dist = math.sqrt((ship.x - target_ship.x) ** 2 + (ship.y - target_ship.y) ** 2)
            ship_range = float(ship.range)
            aircraft_launch_range = 2.0 if ship_range <= 0.0 else max(1.0, ship_range)
            in_air_range = dist <= aircraft_launch_range
            in_hull_range = hull_geometry_in_range(ship, target_ship)

            zone_tiles = set(self._dogfight_tiles(target_ship.x, target_ship.y))
            attacker_zone = [
                s for s in self.all_ships
                if s.owner == ship.owner
                and not getattr(s, "is_base", False)
                and (s.x, s.y) in zone_tiles
            ]
            attacker_aircraft = sum(
                self._available_fighters(s) + self._available_bombers(s)
                for s in attacker_zone
            )
            can_dogfight = (
                not getattr(ship, "did_dogfight_this_turn", False)
                and in_air_range
                and attacker_aircraft > 0
            )
            pending_aircraft = (
                getattr(ship, "pending_bomber_strikes", 0)
                + getattr(ship, "pending_fighter_strikes", 0)
            )
            pending_center = getattr(ship, "pending_air_center", None)

            if pending_aircraft > 0:
                strike = "bomber" if ship.pending_bomber_strikes > 0 else "fighter"
                if pending_center is None or not self._is_in_dogfight_space(pending_center, target_ship):
                    self.action_log.append(
                        f"F: {strike} ripple active — choose an enemy tile touching that dogfight footprint (vs {etyp}).",
                    )
                    return
                if ship.pending_bomber_strikes > 0:
                    ship.pending_bomber_strikes -= 1
                    target_ship.hp -= BOMBER_STRIKE_DAMAGE
                    self.attack_damage_done_this_turn = True
                    self.action_log.append(
                        f"F: {ship.ship_type} bomber sortie hits {etyp} for {BOMBER_STRIKE_DAMAGE}.",
                    )
                else:
                    ship.pending_fighter_strikes -= 1
                    target_ship.hp -= FIGHTER_STRIKE_DAMAGE
                    self.attack_damage_done_this_turn = True
                    self.action_log.append(
                        f"F: {ship.ship_type} fighter sortie scratches {etyp} for {FIGHTER_STRIKE_DAMAGE}.",
                    )
                if ship.pending_bomber_strikes <= 0 and ship.pending_fighter_strikes <= 0:
                    ship.pending_air_center = None
                self._cleanup_destroyed_ships()
                return

            if can_dogfight:
                self.action_log.append(
                    f"F: {ship.ship_type} commits hangar strikes against {etyp} ({attacker_aircraft} ready craft in melee zone).",
                )
                self._resolve_air_dogfight(ship, target_ship)
                ship.did_dogfight_this_turn = True
                return

            if in_hull_range and ship.shots > 0:
                shell = hull_damage_one_volley(ship, target_ship)
                if shell <= 1e-9:
                    self.action_log.append(
                        f"F: {ship.ship_type} hull cannot square a shell on {etyp} (geometry / distance mismatch).",
                    )
                    return
                target_ship.hp -= shell
                self.attack_damage_done_this_turn = True
                ship.shots -= 1
                if ship.shots <= 0:
                    ship.has_fired = True
                self.action_log.append(
                    f"F: {ship.ship_type} main battery hits {etyp} for {shell:g}. "
                    f"Hull salvos remaining: {ship.shots}.",
                )
                self._cleanup_destroyed_ships()
                return

            pending_summary = ""
            if ship.pending_bomber_strikes or ship.pending_fighter_strikes:
                pending_summary = (
                    " Finish resolving pending bomber/fighter strikes before starting a new weapon profile."
                )
            elif getattr(ship, "did_dogfight_this_turn", False):
                pending_summary = " Hangar strike already coordinated this impulse."

            if ship.shots <= 0 and attacker_aircraft <= 0:
                self.action_log.append(
                    f"F: {ship.ship_type} has no hull rounds or hangar planes left versus {etyp}.{pending_summary}"
                )
            elif attacker_aircraft > 0 and not in_air_range:
                self.action_log.append(
                    f"F: Fighters/Bombers need the carrier closer — {ship.ship_type} is out of launcher range of {etyp}.",
                )
            elif attacker_aircraft == 0 and ship.shots > 0 and not in_hull_range:
                self.action_log.append(
                    f"F: {ship.ship_type} has gun solutions remaining but {etyp} is outside cannon arc.",
                )
            elif attacker_aircraft > 0 and in_air_range and not can_dogfight:
                self.action_log.append(
                    f"F: Stored craft must sit inside {etyp}'s dogfight tile — slide friendlies adjacent to them first.",
                )
            elif ship_range <= 0.0 and attacker_aircraft == 0:
                hint = (
                    f"F: Same-tile cannons required to engage {etyp}."
                    if ship.shots > 0 and not hull_geometry_in_range(ship, target_ship)
                    else f"F: {ship.ship_type} needs hangar craft or turrets."
                )
                self.action_log.append(hint + pending_summary)
            else:
                self.action_log.append(f"F: No legal shot versus {etyp} right now.{pending_summary}")

        # Charge Logic
        if key == 'c' and not ship.is_charging:
            if (ship.x, ship.y) != (ship.start_x, ship.start_y):
                self.action_log.append("Charge denied: must charge from your start-of-turn space.")
            else:
                ship.is_charging = True
                for s in ship.fleet_list: s.is_charging = True
                self.action_log.append("Action C: Charging")
            
        # Clean up dead ships
        self._cleanup_destroyed_ships()

    def break_fleet_move(self, ship, key):
        if self.game_over:
            self.action_log = [f"Game over. Player {self.winner} wins. Press G for new match."]
            return
        if ship.owner != self.active_player:
            self.action_log = [f"Not your turn. Player {self.active_player} acts now."]
            return
        if getattr(ship, "is_base", False):
            self.action_log.append("Bases cannot use V-move.")
            return
        if key not in ['w', 'a', 's', 'd']:
            return
        if self.attack_damage_done_this_turn:
            self.action_log = ["Fleet/defleet locked after first attack damage this turn."]
            return

        mobile_peers = mobile_ships_at(self, ship.x, ship.y, ship.owner)
        self.action_log = []
        self.save_state("Pre-Action")

        has_destroyer_in_stack = any(s.ship_type in DESTROYER_TYPES for s in mobile_peers)
        if ship.ship_type not in DESTROYER_TYPES and not has_destroyer_in_stack:
            self.action_log.append("Action V denied: non-destroyers must fleet with a destroyer to move")
            return

        # V cannot bypass post-fire / exhausted movement (partial fleet moves still OK).
        if ship.move_budget_remaining <= 0 or any(m.has_fired for m in mobile_peers):
            self.action_log.append("Action V denied: no move budget or fleet already attacked")
            return

        dx, dy = 0, 0
        if key == 'w':
            dy = -1
        if key == 'a':
            dx = -1
        if key == 's':
            dy = 1
        if key == 'd':
            dx = 1

        # Composition rules for the post-merge stack at the destination.
        peek_x = max(0, min(self.board_size - 1, ship.x + dx))
        peek_y = max(0, min(self.board_size - 1, ship.y + dy))
        destination_friendlies_v = [
            s for s in self.all_ships
            if s.owner == ship.owner
            and not getattr(s, "is_base", False)
            and not getattr(s, "is_aircraft_counter", False)
            and s.id != ship.id
            and s.x == peek_x and s.y == peek_y
        ]
        violation_v = _fleet_rule_violation([ship] + destination_friendlies_v)
        if violation_v:
            self.action_log.append(violation_v)
            return

        original_x, original_y = ship.x, ship.y
        ship.x = max(0, min(self.board_size - 1, ship.x + dx))
        ship.y = max(0, min(self.board_size - 1, ship.y + dy))

        moved = (ship.x != original_x or ship.y != original_y)
        if moved:
            ship.did_move_this_turn = True
            ship.move_budget_remaining = max(0, ship.move_budget_remaining - 1)
            ship.has_moved = ship.move_budget_remaining <= 0
            # Defleet action consumes attacks for the entire original stack this turn (mobile ships).
            for fleet_ship in mobile_peers:
                fleet_ship.shots = 0
                fleet_ship.has_fired = True
                fleet_ship.is_fleeted = False
            ship.is_fleeted = False
            self.try_spawn_base_on_planet(ship)
            self.action_log.append("Action V: Broke fleet and moved single ship (no attacks for that fleet this turn)")
        else:
            self.action_log.append("Action V: Blocked by map edge")
