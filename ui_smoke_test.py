import sys, types, importlib.util

pg=types.ModuleType('pygame')
class PGError(Exception): pass
pg.error=PGError
class Rect:
    def __init__(self,*a):
        if len(a)==1 and isinstance(a[0],(tuple,list)): a=a[0]
        if len(a)==2 and isinstance(a[0],(tuple,list)) and isinstance(a[1],(tuple,list)): a=(*a[0],*a[1])
        self.x,self.y,self.w,self.h=map(int,a)
    @property
    def left(self): return self.x
    @property
    def right(self): return self.x+self.w
    @property
    def top(self): return self.y
    @property
    def bottom(self): return self.y+self.h
    @property
    def centerx(self): return self.x+self.w//2
    @property
    def centery(self): return self.y+self.h//2
    @property
    def center(self): return (self.centerx,self.centery)
    @property
    def topleft(self): return (self.x,self.y)
    @property
    def size(self): return (self.w,self.h)
    def collidepoint(self,p):
        x,y=p; return self.left<=x<self.right and self.top<=y<self.bottom
    def colliderect(self,r): return not (self.right<=r.left or self.left>=r.right or self.bottom<=r.top or self.top>=r.bottom)
    def inflate(self,x,y): return Rect(self.x-x//2,self.y-y//2,self.w+x,self.h+y)
    def clipline(self,*args): return True
pg.Rect=Rect
class Surface:
    def __init__(self,size,*a,**k): self._size=tuple(map(int,size))
    def fill(self,*a,**k): pass
    def blit(self,*a,**k): pass
    def get_width(self): return self._size[0]
    def get_height(self): return self._size[1]
    def get_size(self): return self._size
    def convert_alpha(self): return self
pg.Surface=Surface
class Font:
    def __init__(self,name,size,bold=False): self.size=size
    def render(self,s,*a,**k): return Surface((max(1,len(str(s))*max(4,self.size//2)),self.size+2))
pg.font=types.SimpleNamespace(SysFont=lambda n,s,bold=False:Font(n,s,bold))
pg.draw=types.SimpleNamespace(rect=lambda *a,**k:None,line=lambda *a,**k:None,circle=lambda *a,**k:None,polygon=lambda *a,**k:None,ellipse=lambda *a,**k:None)
_screen=Surface((1500,900))
def _set_mode(size,*a,**k):
    if tuple(size)==(0,0): size=(1600,900)
    return Surface(size)
pg.display=types.SimpleNamespace(set_caption=lambda *a:None,set_mode=_set_mode,flip=lambda:None,Info=lambda:types.SimpleNamespace(current_w=1600,current_h=900))
class Clock:
    def tick(self,*a): return 16
    def get_fps(self): return 144.0
pg.time=types.SimpleNamespace(Clock=Clock)
class Keys:
    def __getitem__(self,k): return False
pg.key=types.SimpleNamespace(get_pressed=lambda:Keys(),get_mods=lambda:0)
pg.mouse=types.SimpleNamespace(get_pos=lambda:(100,100))
pg.event=types.SimpleNamespace(get=lambda:[])
pg.mixer=types.SimpleNamespace(get_init=lambda:False,init=lambda:None,Sound=lambda p:types.SimpleNamespace(set_volume=lambda v:None,play=lambda:None))
pg.image=types.SimpleNamespace(load=lambda p:Surface((32,32)))
pg.transform=types.SimpleNamespace(scale=lambda src,size,dst=None: dst if dst is not None else Surface(size),smoothscale=lambda src,size:Surface(size))
pg.init=lambda:None;pg.quit=lambda:None
# constants
names=['QUIT','KEYDOWN','MOUSEBUTTONDOWN','MOUSEBUTTONUP','MOUSEMOTION','MOUSEWHEEL','SRCALPHA','FULLSCREEN','SCALED','NOFRAME','KMOD_SHIFT','KMOD_CTRL','KMOD_ALT']
for i,n in enumerate(names,1): setattr(pg,n,i)
keys=['RETURN','ESCAPE','F11','F1','TAB','MINUS','EQUALS','RIGHTBRACKET','F3','F4','F7','F8','F10','z','x','a','f','w','r','j','b','d','v','p','g','c','s','l','k','q','m','n','h','y','o','i','e','t','u','KP_ENTER','F9','4','F5','F6','BACKSPACE','BACKQUOTE','LALT','SPACE','HOME','F2','F12','LEFT','RIGHT','UP','DOWN']
for i,n in enumerate(keys,100): setattr(pg,'K_'+n,i)
for i in range(10): setattr(pg,'K_'+str(i),300+i)
# pygame assumes contiguous digits
pg.K_0=300;pg.K_1=301;pg.K_5=305;pg.K_9=309
sys.modules['pygame']=pg

path='kill_zone.py'
spec=importlib.util.spec_from_file_location('kz_ui',path);m=importlib.util.module_from_spec(spec);sys.modules['kz_ui']=m;spec.loader.exec_module(m)
app=m.KillZoneApp()
# menu/setup/settings/help smoke
for state in ('menu','setup','settings','help'):
    app.state=state; app.draw()
# deployment smoke
app.state='setup';app.setup_roster={r:0 for r in m.PLAYER_ROLE_ORDER};app.setup_roster['Rifleman']=6;app.setup_roster['Machine Gunner']=1;app.setup_roster['Medic']=1;app.setup_reserves=2;app.seed_text='12345';app.start_battle();assert app.state=='briefing';app.draw();app.begin_deployment_from_briefing();assert app.state=='deployment';app.selected=[u.uid for u in app.game.living('player')[:4]];app.draw()
app.finalize_deployment();assert app.state=='game';app.game.update_spotting();app.draw()
# renderer cache + new tactical command smoke
assert app._terrain_cache_surface is not None
cache_id=id(app._terrain_cache_surface);app.draw();assert id(app._terrain_cache_surface)==cache_id
assert 'HOLD' in app.command_bar_rects() and 'FALLBACK' in app.command_bar_rects()
app.selected=[u.uid for u in app.game.living('player')[:2]]
app.handle_command_bar(app.command_bar_rects()['HOLD'].center);assert all(u.hold_position for u in app.selected_units())
app.handle_command_bar(app.command_bar_rects()['FALLBACK'].center);assert app.command_mode=='fallback'
app.issue_context_command((3,3));assert all(u.fallback_point==(3,3) for u in app.selected_units())
# exercise tactical previews, threat and after-action overlay
app.show_threat=True;app.show_fps=True;app.show_perf=True;app.draw();app.game.victory=True;app.draw()
# display mode + coordinate scaling smoke
app.set_display_mode('borderless');assert app.fullscreen and app.display_mode=='borderless';assert app.display_to_logical((800,450))==(m.WINDOW_W//2,m.WINDOW_H//2)
app.set_display_mode('exclusive');assert app.fullscreen and app.display_mode=='exclusive'
app.toggle_fullscreen();assert app.display_mode=='windowed'
app.toggle_fullscreen();assert app.display_mode=='exclusive'
app.draw()
print('UI SMOKE PASS')
