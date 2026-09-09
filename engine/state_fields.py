"""Reviewed serialized attributes; extend deliberately with new engine state."""

GAME_FIELDS = frozenset(
    """
    _ai_cursor
    _cohesion_timer
    _contact_last_report
    _counterattack_launched
    _defense_attack_order_timer
    _defense_last_minute
    _defense_next_plan_time
    _engineer_builder_timer
    _intensity_timer
    _last_engineer_builder_update
    _last_stage
    _last_visual_terrain_rev
    _line_cache
    _los_cache
    _maintenance_paths_started
    _maintenance_visual_revision
    _mission_complete_recorded
    _mission_timer
    _mortar_solutions
    _occupancy
    _path_budget
    _path_cache
    _reserves_activated
    _sector_low_since
    _spot_timer
    _stability_timer
    _terrain_revision
    _terrain_state
    _threat_cache_time
    _threat_grids
    _world_timer
    assault_orders
    ballistic_rounds
    battle_events
    battle_stage
    battle_variant
    blood
    bounding_orders
    collapsed_sectors
    combat2_last_projectile_count
    combat2_next_plan_at
    combat2_tactical_plans
    combat_intensity
    construction_reservations
    defeat
    defense_attack_plan
    defense_capture_progress
    defense_deployment_x
    defense_elapsed
    defense_main_effort
    defense_plan_revision
    defense_sector_pressure
    defense_time_limit
    defense_wave_announced
    deployment_zone_side
    deployment_zone_x
    difficulty
    dust
    enemy_estimate
    events
    explosions
    grid
    impacts
    initial_enemy_total
    initial_mobile_enemy_total
    initial_role_counts
    initial_sector_counts
    intel
    log
    map_features
    mission_brief
    mission_title
    mission_type
    network_replica
    next_ballistic_round_id
    next_uid
    notifications
    objective_index
    objectives
    operation_config
    operation_enemy_strength
    operation_variant
    operation_weather
    paused
    player_reserves
    player_roster
    polish_contact_pressure
    polish_engagement_changed_at
    polish_engagement_state
    polish_last_impact_event_at
    polish_peak_intensity
    polish_plan_commits
    polish_preparation_until
    polish_recent_tracers
    primary_line_x
    rally_points
    reserve_count
    rng
    secondary_line_x
    sector_stability
    seed
    squad_doctrine
    stats
    support
    time
    tracers
    units
    victory
    weather
    wind
    """.split()
)

UNIT_FIELDS = frozenset(
    """
    _cleanup_state
    _construction_kind
    _construction_pos
    _construction_queued
    _construction_staging
    _moving_fire_active
    action_timer
    aim_progress
    ammo
    arc_range
    arc_width
    artillery_shells
    assistant_alive
    attack_assignment
    attack_sector
    attack_wave
    auto_cover
    auto_medic
    auto_reload
    auto_smoke
    barrel_spares
    battle_role
    battle_sector
    bayonet
    bleed
    blocked_since
    breaking_since
    built_by_uid
    callsign
    carrying_uid
    casualty
    cohesion
    combat2_acquired_uid
    combat2_assignment
    combat2_decision_reason
    combat2_exposed_until
    combat2_flank
    combat2_last_move_pos
    combat2_phase
    combat2_plan_target
    combat2_ready_at
    combat2_settle_until
    command_delay_until
    command_queue
    counterattack_point
    covering_uid
    crew
    deployed
    disoriented_until
    display_name
    dragging_uid
    facing
    faction
    fallback_point
    fire_discipline
    fire_lane
    fire_lane_center
    fire_mode
    first_name
    full_name
    grenades
    heat
    hold_position
    hp
    identity_index
    incoming_bearings
    initial_battle_role
    is_emplacement
    jammed
    last_ai
    last_attacker_uid
    last_shot_time
    low_morale_since
    magazines
    max_hp
    med_supplies
    momentum
    morale
    morale_state
    mortar_ranging
    mortar_shells
    move_mode
    next_artillery_shot
    next_builder_decision
    next_shot
    order
    overwatch
    path
    path_ready_at
    peek_until
    plan_state
    polish_arrival_facing
    polish_burst_pause_until
    polish_burst_remaining
    polish_deploy_lock_until
    polish_lane_blocked_until
    polish_lane_reason
    polish_last_order_at
    polish_last_order_signature
    polish_last_progress_at
    polish_last_progress_pos
    polish_order_state
    polish_order_state_until
    polish_plan_commit_until
    polish_reaction_kind
    polish_reaction_stance
    polish_reaction_until
    polish_recoil
    polish_target_lock_until
    polish_wait_reason
    prepared
    rally_safe_since
    rally_shock
    rally_target
    rallying
    reaction_ready_at
    reaction_target_uid
    reload_emergency
    reload_timer
    reserve
    reserve_active
    rifle_grenades
    role
    rout_started_at
    route_preview
    satchel
    selected
    shots_recent
    signature
    smoke_grenades
    spotted_enemy_until
    spotted_player_until
    squad_id
    squad_morale
    stamina
    stance
    stationary_time
    suppression
    surname
    survival_react_at
    target_pos
    target_priority
    target_uid
    tools
    traverse_ready_at
    uid
    under_fire_until
    wait_until
    waypoints
    weapon_name
    wound_arm
    wound_head
    wound_leg
    wound_torso
    wound_treated
    x
    y
    """.split()
)

# Finite numeric types exclude bool; tuple layouts preserve exact arity.
UNIT_DYNAMIC_TYPES = {
    "_cleanup_state": {"one_of": ["null", {"tuple": ["str", "bool"]}]},
    "_construction_kind": {"one_of": ["null", "str"]},
    "_construction_pos": {"one_of": ["null", {"tuple": ["int", "int"]}]},
    "_construction_queued": "bool",
    "_construction_staging": {"one_of": ["null", {"tuple": ["int", "int"]}]},
    "_moving_fire_active": "bool",
    "artillery_shells": "int",
    "attack_assignment": "str",
    "attack_sector": "str",
    "attack_wave": "int",
    "battle_role": "str",
    "battle_sector": "str",
    "blocked_since": "number",
    "breaking_since": {"one_of": ["null", "number"]},
    "built_by_uid": "int",
    "callsign": "str",
    "combat2_acquired_uid": {"one_of": ["null", "int"]},
    "combat2_assignment": "str",
    "combat2_decision_reason": "str",
    "combat2_exposed_until": "number",
    "combat2_flank": {"one_of": ["null", {"tuple": ["number", "number"]}]},
    "combat2_last_move_pos": {"tuple": ["number", "number"]},
    "combat2_phase": "str",
    "combat2_plan_target": {"one_of": ["null", {"tuple": ["number", "number"]}]},
    "combat2_ready_at": "number",
    "combat2_settle_until": "number",
    "counterattack_point": {"one_of": ["null", {"tuple": ["number", "number"]}]},
    "display_name": "str",
    "first_name": "str",
    "full_name": "str",
    "hold_position": "bool",
    "identity_index": "int",
    "initial_battle_role": "str",
    "is_emplacement": "bool",
    "last_shot_time": "number",
    "low_morale_since": {"one_of": ["null", "number"]},
    "morale_state": "str",
    "mortar_ranging": "number",
    "next_artillery_shot": "number",
    "next_builder_decision": "number",
    "path_ready_at": "number",
    "plan_state": "str",
    "polish_arrival_facing": "number",
    "polish_burst_pause_until": "number",
    "polish_burst_remaining": "int",
    "polish_deploy_lock_until": "number",
    "polish_lane_blocked_until": "number",
    "polish_lane_reason": "str",
    "polish_last_order_at": "number",
    "polish_last_order_signature": {
        "one_of": [
            "null",
            {
                "tuple": [
                    {"literal": "move"},
                    {"tuple": ["number", "number"]},
                    "str",
                    "bool",
                ]
            },
            {"tuple": [{"literal": "fire"}, "int", "str"]},
            {"tuple": [{"literal": "suppress"}, "number", "number"]},
        ]
    },
    "polish_last_progress_at": "number",
    "polish_last_progress_pos": {"tuple": ["number", "number"]},
    "polish_order_state": "str",
    "polish_order_state_until": "number",
    "polish_plan_commit_until": "number",
    "polish_reaction_kind": "str",
    "polish_reaction_stance": {"one_of": ["null", "str"]},
    "polish_reaction_until": "number",
    "polish_recoil": "number",
    "polish_target_lock_until": "number",
    "polish_wait_reason": "str",
    "rally_safe_since": {"one_of": ["null", "number"]},
    "rally_target": {"one_of": ["null", {"tuple": ["number", "number"]}]},
    "rallying": "bool",
    "reserve": "bool",
    "reserve_active": "bool",
    "rout_started_at": "number",
    "shots_recent": "int",
    "squad_id": "int",
    "squad_morale": "number",
    "surname": "str",
    "survival_react_at": "number",
    "wait_until": "number",
    "wound_arm": "number",
    "wound_head": "number",
    "wound_leg": "number",
    "wound_torso": "number",
    "wound_treated": "bool",
}
