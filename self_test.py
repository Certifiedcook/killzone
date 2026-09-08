import importlib.util, sys, math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
path=ROOT/'kill_zone.py'
spec=importlib.util.spec_from_file_location('kill_zone_rt',path)
kz=importlib.util.module_from_spec(spec);sys.modules['kill_zone_rt']=kz;spec.loader.exec_module(kz)


def clear_area(g,x1=0,y1=0,x2=20,y2=20):
    for y in range(y1,min(y2,kz.MAP_H)):
        for x in range(x1,min(x2,kz.MAP_W)):
            g.set_cell(x,y,'open')
            g.grid[y][x].mine=False
            g.grid[y][x].smoke=0
            g.grid[y][x].fire=0


def fresh(seed=1):
    g=kz.RealTimeGame(seed=seed,difficulty='Hard')
    g.units=[];g.next_uid=1;g.explosions=[];g.tracers=[]
    clear_area(g,0,0,kz.MAP_W,kz.MAP_H)
    g.check_end = lambda: None
    return g


def step(g,seconds):
    for _ in range(int(seconds*30)):g.update(1/30)


def test_realtime_movement():
    g=fresh();u=g.add_unit('player','Rifleman',2,2)
    g.issue_move([u],(8,2),mode='fast');step(g,3.0)
    assert u.x>4.5, u.x
    assert g.time>2.9


def test_continuous_fire_and_suppression():
    g=fresh(2);a=g.add_unit('player','Machine Gunner',3,4);b=g.add_unit('enemy','Rifleman',8,4)
    a.deployed=True;g.issue_fire(a,b,'rapid');step(g,2.0)
    assert a.ammo<kz.WEAPONS[a.weapon_name]['mag']
    assert b.suppression>0 or b.hp<b.max_hp


def test_smoke_los_and_drift():
    g=fresh(3);a=g.add_unit('player','Rifleman',2,2);b=g.add_unit('enemy','Rifleman',8,2)
    assert g.can_see(a,b)
    g.grid[2][5].smoke=2.4;g._los_cache.clear();g._line_cache.clear()
    assert not g.can_see(a,b)
    old=sum(c.smoke for row in g.grid for c in row);step(g,1);new=sum(c.smoke for row in g.grid for c in row)
    assert new>0 and new!=old


def test_medic_and_drag():
    g=fresh(4);m=g.add_unit('player','Medic',3,3);t=g.add_unit('player','Rifleman',4,3)
    t.casualty='incapacitated';t.hp=0;t.bleed=20
    g.medic_action(m,t);step(g,3.2)
    assert t.casualty=='wounded' and t.hp>0
    t.casualty='incapacitated';t.hp=0;t.bleed=20
    g.drag_toggle(m,t);assert m.dragging_uid==t.uid


def test_engineer_systems():
    g=fresh(5);e=g.add_unit('player','Engineer',5,5)
    g.set_cell(6,5,'wire');g.engineer_action(e,(6,5),'cut');step(g,2.7);assert g.grid[5][6].terrain=='open'
    e.tools=max(e.tools,1);g.grid[5][6].mine=True;g.engineer_action(e,(6,5),'clear_mine');step(g,2.4);assert not g.grid[5][6].mine
    e.tools=max(e.tools,1);g.engineer_action(e,(6,5),'fortify');step(g,5.2);assert g.grid[5][6].terrain=='sandbags'


def test_door_and_building():
    g=fresh(6);u=g.add_unit('player','Rifleman',4,4);g.set_cell(5,4,'door')
    assert not g.passable(5,4,u);g.toggle_door(u,(5,4));assert g.grid[4][5].door_open and g.passable(5,4,u)


def test_heat_jam_barrel():
    g=fresh(7);u=g.add_unit('player','Machine Gunner',4,4);u.heat=100
    t=g.add_unit('enemy','Rifleman',6,4);before=u.ammo;g.perform_shot(u,t);assert u.ammo==before
    t.casualty='dead'
    u.heat=90;sp=u.barrel_spares;g.change_barrel(u);step(g,4.2);assert u.heat<20 and u.barrel_spares==sp-1


def test_magazine_sharing():
    g=fresh(8);a=g.add_unit('player','Rifleman',3,3);b=g.add_unit('player','Rifleman',4,3)
    na,nb=len(a.magazines),len(b.magazines);g.share_ammo(a,b);assert len(a.magazines)==na-1 and len(b.magazines)==nb+1


def test_overwatch_realtime():
    g=fresh(9);a=g.add_unit('player','Rifleman',4,4);b=g.add_unit('enemy','Rifleman',8,4)
    g.set_overwatch(a,0,90);start=a.ammo;b.waypoints=[(3,4)];b.order='move';step(g,1.6)
    assert a.ammo<start, (a.ammo,start)


def test_mortar_and_destruction():
    g=fresh(10);m=g.add_unit('player','Mortar Team',2,2);m.deployed=True;t=g.add_unit('enemy','Rifleman',10,10)
    g.set_cell(10,10,'trench','H');m.mortar_shells=2;g.mortar_fire(m,(10,10),False);step(g,3.5)
    assert t.hp<t.max_hp or t.suppression>0


def test_rout_or_surrender():
    # Severe morale loss must persist before a unit routes; suppression alone first pins it.
    g=fresh(11);u=g.add_unit('enemy','Rifleman',6,6);p=g.add_unit('player','Rifleman',50,30);p.fire_discipline='hold'
    u.morale=5;u.cohesion=20;u.suppression=100;step(g,.5)
    assert u.order!='rout' and u.casualty!='surrendered'
    step(g,4.0)
    assert u.order=='rout' or u.casualty=='surrendered' or getattr(u,'rallying',False)


def test_coordinated_advance():
    g=fresh(12);mg=g.add_unit('player','Machine Gunner',2,2);r=g.add_unit('player','Rifleman',2,3)
    mg.deployed=True;g.coordinated_advance([mg,r],(8,3));assert mg.order=='suppress' and r.order=='move'


def test_long_simulation():
    g=kz.RealTimeGame(seed=222,difficulty='Veteran')
    # force the player formation to advance toward the defenders, then let both AIs/fire systems run.
    ps=[u for u in g.living('player') if u.combat_effective]
    g.issue_move(ps,(kz.MAP_W-14,kz.MAP_H//2),mode='safe')
    step(g,35)
    assert math.isfinite(g.time)
    assert all(math.isfinite(u.hp) and math.isfinite(u.suppression) for u in g.units)

def test_emergency_reload_drops_partial():
    g=fresh(13);u=g.add_unit('player','Rifleman',3,3)
    u.ammo=7;before=len(u.magazines);g.start_reload(u,emergency=True);step(g,2.0)
    assert u.ammo==kz.WEAPONS[u.weapon_name]['mag'] and len(u.magazines)==before-1


def test_carry_prevents_fire_and_moves():
    g=fresh(14);u=g.add_unit('player','Rifleman',3,3);cas=g.add_unit('player','Rifleman',4,3);e=g.add_unit('enemy','Rifleman',8,3)
    cas.casualty='incapacitated';cas.hp=0;cas.bleed=20;g.carry_toggle(u,cas);before=u.ammo;g.perform_shot(u,e);assert u.ammo==before
    g.issue_move([u],(6,3),mode='fast');step(g,2);assert u.x>3.5 and abs(cas.x-u.x)<.1


def test_mine_scan_and_wire_placement():
    g=fresh(15);e=g.add_unit('player','Engineer',5,5);g.grid[5][8].mine=True
    g.scan_mines(e);assert g.grid[5][8].mine_seen_player
    e.tools=max(1,e.tools);g.engineer_action(e,(6,5),'wire');step(g,4.7);assert g.grid[5][6].terrain=='wire'


def test_high_ground_and_enfilade():
    g=fresh(16);a=g.add_unit('player','Rifleman',3,5);b=g.add_unit('enemy','Rifleman',8,5)
    g.set_cell(3,5,'hill');g.set_cell(8,5,'open');high=g.hit_chance(a,b)
    g.set_cell(3,5,'open');low=g.hit_chance(a,b);assert high>low
    g.set_cell(8,5,'trench','H');a.x,a.y=3,5;along=g.hit_chance(a,b)
    a.x,a.y=8,1;across=g.hit_chance(a,b);assert along>across


def test_window_and_wood_penetration():
    g=fresh(17);a=g.add_unit('player','Rifleman',2,4);b=g.add_unit('enemy','Rifleman',7,4)
    g.set_cell(4,4,'window');assert g.hit_chance(a,b)>0
    g.set_cell(4,4,'woodwall');assert g.hit_chance(a,b)>0



def test_formation_offsets_and_group_move():
    g=fresh(18)
    us=[g.add_unit('player','Rifleman',2,2+i) for i in range(4)]
    offs=g.formation_offsets(4,'wedge')
    assert len(offs)==4 and len(set(offs))==4
    g.issue_move(us,(10,8),formation='wedge')
    destinations=[u.waypoints[-1] for u in us]
    assert len(set(destinations))>=3, destinations


def test_command_queue_executes():
    g=fresh(19);u=g.add_unit('player','Rifleman',2,2);e=g.add_unit('enemy','Rifleman',8,2)
    g.issue_move([u],(4,2))
    g.queue_fire(u,e.uid,'normal')
    assert len(u.command_queue)==1
    step(g,2.5)
    # Move should complete, queued fire should have been issued/consumed.
    assert not u.command_queue
    assert u.ammo<kz.WEAPONS[u.weapon_name]['mag'] or u.order in ('fire','idle')


def test_fire_discipline_and_target_priority():
    g=fresh(20);u=g.add_unit('player','Rifleman',2,2);e1=g.add_unit('enemy','Rifleman',5,2);e2=g.add_unit('enemy','Machine Gunner',7,2)
    u.fire_discipline='hold';before=u.ammo;step(g,.5);assert u.ammo==before
    u.fire_discipline='free';u.target_priority='specialist';u.next_shot=0
    step(g,.3)
    assert u.ammo<before


def test_bounding_overwatch_starts_in_bounds():
    g=fresh(21);us=[g.add_unit('player','Rifleman',2,3+i) for i in range(4)]
    g.bounding_advance(us,(10,5));assert len(g.bounding_orders)==1
    step(g,.1)
    a=[g.get_unit(uid) for uid in g.bounding_orders[0].a]
    b=[g.get_unit(uid) for uid in g.bounding_orders[0].b]
    assert any(u.order=='move' for u in a)
    assert all(u.overwatch for u in b)


def test_last_known_intel_does_not_track_hidden_target():
    g=fresh(22);o=g.add_unit('enemy','Recon',2,2);p=g.add_unit('player','Rifleman',6,2)
    g.update_spotting();info=dict(g.intel['enemy'][p.uid]);old=info['pos']
    # hard blocker removes LOS, then the player relocates out of sight
    g.set_cell(4,2,'wall');p.x,p.y=8,2;g.time+=1;g.update_spotting()
    assert g.intel['enemy'][p.uid]['pos']==old, (g.intel['enemy'][p.uid]['pos'],old)


def test_blood_and_audio_events():
    g=fresh(23);a=g.add_unit('player','Rifleman',2,2);b=g.add_unit('enemy','Rifleman',4,2)
    g.events=[];g.blood=[]
    g.apply_damage(b,25,a,'test')
    kinds=[e['type'] for e in g.drain_events()]
    assert 'hurt' in kinds and g.blood
    g.events=[];g.resolve_explosion(kz.Explosion(4,2,0,2,0,20,'HE','player'))
    assert 'explosion' in [e['type'] for e in g.drain_events()]


def test_richer_trench_generation():
    found=set()
    for seed in range(24,34):
        g=kz.RealTimeGame(seed=seed,difficulty='Hard')
        found.update(c.terrain for row in g.grid for c in row)
        if {'dugout','firing_step'}<=found:break
    assert 'dugout' in found and 'firing_step' in found, found


def test_asset_manifest_sources():
    expected={'rifle_556.mp3','rifle_762.mp3','smg_9mm.mp3','explosion1.ogg','explosion2.ogg','hurt_01.mp3','hurt_03.mp3','scream_horror1.mp3','blood_red.png'}
    assert expected<=set(kz.ASSET_MANIFEST)
    assert kz.ASSET_MANIFEST['explosion2.ogg'].endswith('/explosion2.ogg')


def test_custom_roster_and_default_free_fire():
    roster=['Rifleman','Rifleman','Medic','HMG Crew']
    g=kz.RealTimeGame(seed=35,difficulty='Hard',player_roster=roster)
    players=[u for u in g.units if u.faction=='player']
    assert [u.role for u in players]==roster
    assert all(u.fire_discipline=='free' for u in players)


def test_roster_validation_and_cap():
    roster=['not-a-role']+['Rifleman']*(kz.MAX_PLAYER_UNITS+5)
    g=kz.RealTimeGame(seed=36,difficulty='Easy',player_roster=roster)
    players=[u for u in g.units if u.faction=='player']
    assert len(players)==kz.MAX_PLAYER_UNITS
    assert all(u.role=='Rifleman' for u in players)


def test_auto_reload_state_aware():
    g=fresh(40);u=g.add_unit('player','Rifleman',3,3)
    u.ammo=0;u.order='idle';step(g,.1)
    assert u.reload_timer>0 and u.order=='reload'
    g2=fresh(41);m=g2.add_unit('player','Machine Gunner',3,3);m.ammo=4;m.order='idle';step(g2,.1)
    assert m.reload_timer>0, (m.ammo,m.reload_timer)


def test_cover_degradation_reduces_protection():
    g=fresh(42);a=g.add_unit('player','Rifleman',3,4);b=g.add_unit('enemy','Rifleman',8,4)
    g.set_cell(8,4,'sandbags');base=g.effective_cover(a,b)
    g.degrade_cover(b.pos,100,3);after=g.effective_cover(a,b)
    assert after < base and g.grid[4][8].cover_wear>0


def test_crossfire_sector_overload():
    g=fresh(43);t=g.add_unit('enemy','Rifleman',8,8)
    t.incoming_bearings=[(0,g.time),(100,g.time)]
    assert g.crossfire_pressure(t)>.3
    t.incoming_bearings=[(0,g.time),(15,g.time)]
    assert g.crossfire_pressure(t)==0


def test_smoke_layers_stack():
    g=fresh(44)
    e=kz.Explosion(6,6,0,2.3,0,0,'SMOKE','player')
    g.resolve_explosion(e);one=g.grid[6][6].smoke
    g.resolve_explosion(e);two=g.grid[6][6].smoke
    assert two>one and two<=5.0


def test_stamina_fatigue_and_recovery():
    g=fresh(45);u=g.add_unit('player','Rifleman',2,2)
    g.issue_move([u],(12,2),mode='fast');step(g,2.0);low=u.stamina
    assert low<90
    u.order='idle';u.path=[];u.waypoints=[];step(g,2.0)
    assert u.stamina>low


def test_reaction_delay_scales_with_suppression():
    g=fresh(46);u=g.add_unit('player','HMG Crew',3,3)
    u.suppression=0;calm=g.reaction_delay(u)
    u.suppression=80;hot=g.reaction_delay(u)
    assert hot>calm


def test_blast_concussion_and_position_suppression():
    g=fresh(47);u=g.add_unit('player','Rifleman',5,5)
    g.resolve_explosion(kz.Explosion(5,5,0,2.8,25,80,'HE','enemy'))
    assert u.disoriented_until>g.time
    assert g.grid[5][5].ground_suppression>0


def test_suppression_decay_slower_under_fire():
    g=fresh(48);u=g.add_unit('player','Rifleman',5,5);u.suppression=70
    u.under_fire_until=g.time+5;before=u.suppression;step(g,1);under=before-u.suppression
    u.suppression=70;u.under_fire_until=0;g.grid[5][5].ground_suppression=0;before=u.suppression;step(g,1);calm=before-u.suppression
    assert calm>under


def test_trench_breach_momentum():
    g=fresh(49);u=g.add_unit('player','Assault',kz.MAP_W-17,6);e=g.add_unit('enemy','Rifleman',kz.MAP_W-10,6)
    g.set_cell(kz.MAP_W-11,6,'trench','H');u.x=kz.MAP_W-11;u.y=6;g.on_enter_tile(u,kz.MAP_W-11,6)
    assert u.momentum>=20


def test_enemy_fallback_when_compromised():
    g=fresh(50);u=g.add_unit('enemy','Rifleman',12,8);g.set_cell(12,8,'trench','V')
    u.suppression=86;u.morale=30
    g.ai_decide(u)
    assert u.order in ('move','rout') or u.smoke_grenades==0


def test_autonomy_defaults_enabled():
    g=fresh(51);u=g.add_unit('player','Medic',3,3)
    assert u.auto_reload and u.auto_cover and u.auto_smoke and u.auto_medic


def test_frontend_does_not_reference_app_time():
    import ast
    root=Path(__file__).resolve().parent
    sources = sorted((root / 'engine' / 'frontend').glob('*.py'))
    assert sources, 'Frontend package not found'
    bad=[]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.Attribute) and node.attr=='time' and isinstance(node.value,ast.Name) and node.value.id=='self':
                bad.append((path.name, node.lineno))
    assert not bad, f'KillZoneApp incorrectly references self.time at lines {bad}; use self.game.time'



def test_large_coherent_battlefield_and_difficulty_physics():
    assert kz.MAP_W >= 50 and kz.MAP_H >= 30
    assert all(kz.DIFFICULTY[d]['acc']==0 for d in ('Easy','Hard','Veteran'))
    g=kz.RealTimeGame(seed=700,difficulty='Hard')
    assert g.primary_line_x < g.secondary_line_x < kz.MAP_W
    assert len(g.map_features['breaches']) >= 3
    terrains={c.terrain for row in g.grid for c in row}
    assert {'trench','bunker','wire','crater','dugout','firing_step'} <= terrains


def test_reserves_are_held_then_committed():
    roster=['Rifleman','Medic','Machine Gunner','Assault','Recon']
    g=kz.RealTimeGame(seed=701,difficulty='Hard',player_roster=roster,reserve_count=2)
    assert len(g.living('player'))==3 and len(g.player_reserves)==2
    new=g.deploy_player_reserves()
    assert len(new)==2 and len(g.living('player'))==5 and not g.player_reserves


def test_persistent_squad_structure():
    g=kz.RealTimeGame(seed=702,difficulty='Hard',player_roster=['Rifleman']*9)
    squads=[u.squad_id for u in g.living('player')]
    assert squads[:4]==[1,1,1,1] and squads[4:8]==[2,2,2,2] and squads[8]==3


def test_assault_order_support_and_movement_phase():
    g=fresh(703)
    mg=g.add_unit('player','Machine Gunner',2,4);a=g.add_unit('player','Assault',2,5);r=g.add_unit('player','Rifleman',3,5)
    e=g.add_unit('enemy','Rifleman',9,5);g.set_cell(9,5,'trench','V')
    g.assault_position([mg,a,r],(9,5),e.uid)
    assert g.assault_orders and (mg.order in ('suppress','deploy') or mg.deployed)
    # Force the support condition so the assault phase advances deterministically.
    g.grid[5][9].ground_suppression=50
    g.update_assault_orders(.1)
    assert g.assault_orders[0].phase>=1
    assert a.order=='move' or r.order=='move'


def test_mortar_minimum_range_and_ranging_solution():
    g=fresh(704);m=g.add_unit('player','Mortar Team',2,2);m.deployed=True;m.mortar_shells=4
    before=m.mortar_shells;g.mortar_fire(m,(4,2),False);assert m.mortar_shells==before
    g.mortar_fire(m,(10,8),False)
    assert m.mortar_shells==before-1 and g._mortar_solutions


def test_crew_replacement_and_recrew():
    g=fresh(705);h=g.add_unit('player','HMG Crew',5,5);r=g.add_unit('player','Rifleman',4,5)
    h.assistant_alive=False;h.crew=1
    assert g.recrew_weapon(r,h) and h.assistant_alive and h.crew>=2
    h.casualty='incapacitated';h.hp=0
    helper=g.add_unit('player','Rifleman',5,4)
    assert g.recrew_weapon(helper,h) and helper.role=='HMG Crew' and helper.weapon_name=='Heavy Machine Gun'


def test_explosion_visual_dust_is_capped():
    g=fresh(706);g.dust=[]
    for _ in range(15):g.resolve_explosion(kz.Explosion(6,6,0,2.5,80,70,'HE','enemy'))
    assert 1 <= len(g.dust) <= 100


def test_mass_move_pathfinding_is_budgeted():
    g=fresh(707);us=[g.add_unit('player','Rifleman',2,2+i) for i in range(12)]
    g.issue_move(us,(30,15),mode='safe',formation='spread')
    # One simulation step may construct only the configured path budget, preventing a frame spike.
    g.update(1/30)
    assert g._perf['paths'] <= 3, g._perf


def test_enemy_estimate_is_uncertain():
    g=kz.RealTimeGame(seed=708,difficulty='Veteran')
    actual=len(g.living('enemy'));lo,hi=g.enemy_estimate
    assert lo < hi and lo <= actual <= hi


def test_uncapped_renderer_and_camera_view_constants():
    assert kz.FPS == 0
    assert kz.MAP_VIEW_W_PX < kz.MAP_W * kz.TILE
    assert kz.MAP_VIEW_H_PX < kz.MAP_H * kz.TILE
    app = kz.KillZoneApp.__new__(kz.KillZoneApp)
    app.camera_x, app.camera_y, app.zoom = 2.0, 3.0, 1.0
    app.shake_offset = (0, 0)
    assert app.world_to_screen(2, 3) == (kz.MAP_X + kz.TILE // 2, kz.MAP_Y + kz.TILE // 2)
    assert app.world_to_screen(3, 4) == (kz.MAP_X + 3 * kz.TILE // 2, kz.MAP_Y + 3 * kz.TILE // 2)


def test_display_modes_use_logical_canvas_and_include_borderless():
    from types import SimpleNamespace
    app = kz.KillZoneApp.__new__(kz.KillZoneApp)
    app.window = SimpleNamespace(get_size=lambda: (kz.WINDOW_W * 2, kz.WINDOW_H * 2))
    assert app.display_to_logical((200, 100)) == (100, 50)
    assert app.display_to_logical((-10, -10)) == (0, 0)
    assert app.display_to_logical((99999, 99999)) == (kz.WINDOW_W - 1, kz.WINDOW_H - 1)
    applied = []
    for mode in ('windowed', 'borderless', 'exclusive'):
        app.apply_display_mode = lambda: applied.append(app.display_mode)
        app.display_mode = 'windowed'
        app._base_set_display_mode(mode)
        assert app.display_mode == mode
    assert applied == ['windowed', 'borderless', 'exclusive']


def test_escape_on_main_menu_never_quits():
    from types import SimpleNamespace
    app = kz.KillZoneApp.__new__(kz.KillZoneApp)
    app.running, app.state = True, 'menu'
    app.handle_menu_event(SimpleNamespace(type=kz.pygame.KEYDOWN, key=kz.pygame.K_ESCAPE))
    assert app.running and app.state == 'menu'
    app.handle_menu_event(SimpleNamespace(type=kz.pygame.QUIT))
    assert not app.running


def test_vertical_slice_has_staged_objectives_and_variant():
    g=kz.RealTimeGame(seed=800,difficulty='Hard')
    assert g.battle_variant in kz.MISSION_VARIANTS
    assert len(g.objectives)==4 and g.objective_index==0
    assert g.objectives[0]['state']=='active' and all(o['state']=='locked' for o in g.objectives[1:])
    assert g.map_features['command_post'][0] > g.secondary_line_x


def test_enemy_force_plan_has_reserve_and_command_group():
    g=kz.RealTimeGame(seed=801,difficulty='Veteran')
    roles={getattr(u,'initial_battle_role','') for u in g.living('enemy')}
    assert {'forward','reserve','command'} <= roles, roles
    reserves=[u for u in g.living('enemy') if u.initial_battle_role=='reserve']
    assert reserves and all(not u.reserve_active for u in reserves)
    u=reserves[0];g.ai_decide(u)
    assert u.order in ('idle','overwatch','deploy'), u.order


def test_enemy_reserves_activate_after_forward_line_break():
    g=kz.RealTimeGame(seed=802,difficulty='Hard')
    forward=[u for u in g.living('enemy') if u.initial_battle_role=='forward']
    keep=max(1,int(len(forward)*.4))
    for u in forward[keep:]:u.casualty='dead';u.hp=0
    ps=[u for u in g.living('player') if u.combat_effective][:2]
    assert len(ps)==2
    for i,u in enumerate(ps):u.x=g.primary_line_x;u.y=5+i*5
    g.update_sector_stability();g.update_objectives()
    assert g.objective_index>=1
    reserves=[u for u in g.living('enemy') if u.initial_battle_role=='reserve']
    assert g._reserves_activated and all(u.reserve_active for u in reserves)


def test_sector_collapse_orders_fallback_or_surrender():
    g=kz.RealTimeGame(seed=803,difficulty='Hard')
    defs=[u for u in g.living('enemy') if u.initial_battle_role=='forward' and u.battle_sector=='NORTH']
    if not defs:
        return
    for u in defs:u.morale=8;u.suppression=96
    p=next(u for u in g.living('player') if u.combat_effective);p.x=g.primary_line_x;p.y=4
    g.update_sector_stability();assert 'NORTH' not in g.collapsed_sectors
    g.time+=3.0;g.update_sector_stability()
    assert 'NORTH' in g.collapsed_sectors
    assert all((not u.combat_effective) or u.order in ('move','rout','surrender','pack') or u.casualty=='surrendered' for u in defs)


def test_isolated_pinned_defender_can_surrender_locally():
    g=fresh(804);e=g.add_unit('enemy','Rifleman',8,8);p=g.add_unit('player','Assault',9,8)
    e.morale=5;e.suppression=100;e.low_morale_since=0;g.time=6.0
    g.update_local_surrenders()
    assert e.casualty=='surrendered'


def test_counterattack_uses_committed_reserve():
    g=kz.RealTimeGame(seed=805,difficulty='Veteran')
    g.activate_enemy_reserves('test');g.launch_counterattack()
    assert g._counterattack_launched
    attackers=[u for u in g.living('enemy') if getattr(u,'plan_state','')=='counterattack']
    assert attackers and all(u.counterattack_point==g.map_features['strongpoint'] for u in attackers)


def test_shot_breakdown_matches_actual_hit_chance():
    g=fresh(806);a=g.add_unit('player','Rifleman',3,5);b=g.add_unit('enemy','Rifleman',8,5);g.set_cell(8,5,'trench','V')
    bd=g.shot_breakdown(a,b,'aimed');actual=g.hit_chance(a,b,'aimed')
    assert abs(bd['chance']-actual)<1e-6 and bd['mods']
    assert any(name=='cover' for name,_ in bd['mods'])


def test_battle_stage_tracks_escalation():
    g=kz.RealTimeGame(seed=807,difficulty='Hard')
    g.combat_intensity=0;g.objective_index=0
    for u in g.living('enemy'):u.spotted_player_until=0
    g.update_battle_stage(.1);assert g.battle_stage in ('APPROACH','CONTACT')
    g.combat_intensity=20;g.update_battle_stage(.1);assert g.battle_stage=='CONTACT'
    g.objective_index=1;g.update_battle_stage(.1);assert g.battle_stage=='ASSAULT'
    g.collapsed_sectors.update({'NORTH','CENTRE'});g.update_battle_stage(.1);assert g.battle_stage=='COLLAPSE'


def test_player_units_have_stable_identity_labels():
    g1=kz.RealTimeGame(seed=808,difficulty='Easy',player_roster=['Rifleman','Medic'])
    g2=kz.RealTimeGame(seed=808,difficulty='Easy',player_roster=['Rifleman','Medic'])
    a=[u.display_name for u in g1.living('player')];b=[u.display_name for u in g2.living('player')]
    assert a==b and all(name for name in a)


def test_final_command_post_can_end_battle_without_extermination():
    g=kz.RealTimeGame(seed=809,difficulty='Easy')
    g.objective_index=3
    for i,o in enumerate(g.objectives):o['state']='complete' if i<3 else 'active'
    cmd=g.map_features['command_post'];p=next(u for u in g.living('player') if u.combat_effective);p.x,p.y=cmd
    for e in g.living('enemy'):
        if kz.dist(e.pos,cmd)<=4.3:e.x,e.y=1,kz.MAP_H-2
    g.update_objectives()
    assert g.victory and g.objective_index==4


def test_contact_report_uses_intel_and_not_hidden_live_position():
    g=fresh(810);o=g.add_unit('player','Recon',2,2);e=g.add_unit('enemy','Machine Gunner',6,2)
    g.update_spotting();assert any('CONTACT' in n['text'] for n in g.notifications)
    old=g.intel['player'][e.uid]['pos'];g.set_cell(4,2,'wall');e.x,e.y=10,2;g.time+=1;g.update_spotting()
    assert g.intel['player'][e.uid]['pos']==old


def test_combat_exit_cleans_overwatch_and_target_state():
    g=fresh(901);a=g.add_unit('player','Rifleman',3,3);b=g.add_unit('enemy','Rifleman',6,3)
    g.set_overwatch(b,180,100);b.target_uid=a.uid;b.reaction_target_uid=a.uid
    g.apply_damage(b,500,a,'test')
    assert not b.combat_effective
    assert not b.overwatch and not b.fire_lane and b.target_uid is None and b.reaction_target_uid is None


def test_suppression_alone_pins_instead_of_routing():
    g=fresh(902);u=g.add_unit('enemy','Rifleman',6,6);p=g.add_unit('player','Rifleman',50,30);p.fire_discipline='hold'
    u.morale=82;u.cohesion=80;u.suppression=100;step(g,2.0)
    assert u.order!='rout' and u.casualty!='surrendered'
    assert getattr(u,'morale_state','') in ('PINNED','SHAKEN')


def test_hold_position_extends_break_delay():
    g=fresh(903);p=g.add_unit('player','Rifleman',50,30);p.fire_discipline='hold'
    normal=g.add_unit('enemy','Rifleman',7,7);held=g.add_unit('enemy','Rifleman',7,10)
    for u in (normal,held):
        u.morale=5;u.cohesion=20;u.suppression=96;u.low_morale_since=0
    held.hold_position=True;g.time=4.0
    g.handle_break(normal);g.handle_break(held)
    assert normal.order=='rout'
    assert held.order!='rout'


def test_rallying_recovers_broken_troop():
    g=fresh(904);u=g.add_unit('player','Rifleman',5,5);e=g.add_unit('enemy','Rifleman',50,30);e.fire_discipline='hold'
    u.morale=22;u.cohesion=32;u.suppression=28;u.rallying=True;u.rally_safe_since=0;u.order='idle';u.under_fire_until=0
    for _ in range(150):
        g.time+=1/30;g.update_unit(u,1/30)
    assert not u.rallying and u.morale>=30 and u.cohesion>=40


def test_explicit_fallback_point_is_preferred():
    g=fresh(905);u=g.add_unit('player','Rifleman',10,10);u.fallback_point=(4,8)
    assert g.choose_retreat_position(u)==(4,8)


def test_los_cache_records_hits_when_profiler_enabled():
    g=fresh(906);a=g.add_unit('player','Recon',3,3);b=g.add_unit('enemy','Rifleman',8,3);g.profile_enabled=True
    g.can_see(a,b);g.can_see(a,b)
    assert g._perf.get('los_hits',0)>=1


def test_morale_breakdown_explains_pressure_and_support():
    g=fresh(907);u=g.add_unit('player','Rifleman',5,5);mate=g.add_unit('player','Rifleman',6,5)
    u.suppression=70;u.cohesion=45;u.rally_shock=8
    factors=dict(g.morale_breakdown(u))
    assert factors['suppression']>0 and factors['cohesion loss']>0 and factors['nearby squadmates']<0


def test_sector_collapse_requires_sustained_instability():
    g=kz.RealTimeGame(seed=908,difficulty='Hard')
    defs=[u for u in g.living('enemy') if u.initial_battle_role=='forward' and u.battle_sector=='CENTRE']
    if not defs:return
    for u in defs:u.morale=5;u.suppression=100
    p=next(u for u in g.living('player') if u.combat_effective);p.x=g.primary_line_x;p.y=kz.MAP_H//2
    g.update_sector_stability();assert 'CENTRE' not in g.collapsed_sectors
    g.time+=3;g.update_sector_stability();assert 'CENTRE' in g.collapsed_sectors

TESTS=[v for k,v in list(globals().items()) if k.startswith('test_')]
if __name__=='__main__':
    for t in TESTS:
        t();print('PASS',t.__name__)
    print(f'ALL {len(TESTS)} TESTS PASSED')
