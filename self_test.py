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
    g.grid[2][5].smoke=2.4
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
    g=fresh(11);u=g.add_unit('enemy','Rifleman',6,6);p=g.add_unit('player','Rifleman',7,6)
    u.morale=5;u.suppression=100;step(g,.2)
    assert u.order=='rout' or u.casualty=='surrendered'


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

TESTS=[v for k,v in list(globals().items()) if k.startswith('test_')]
if __name__=='__main__':
    for t in TESTS:
        t();print('PASS',t.__name__)
    print(f'ALL {len(TESTS)} TESTS PASSED')
