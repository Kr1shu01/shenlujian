"""Translate Qt selection coordinates to the X11 framebuffer's pixels."""
import ctypes,math,os,re,subprocess
from dataclasses import dataclass
from PyQt5.QtCore import QRect


@dataclass
class ScreenMapping:
    name: str
    logical: QRect
    native: QRect


class CaptureGeometry:
    def __init__(self,root,mappings):
        self.root=QRect(root);self.mappings=mappings
        self.logical_bounds=QRect()
        for screen in mappings:self.logical_bounds=self.logical_bounds.united(screen.logical)

    @classmethod
    def detect(cls,screens):
        if os.environ.get('XDG_SESSION_TYPE')=='wayland':
            mappings=[];root=QRect()
            for screen in screens:
                logical=QRect(screen.geometry());ratio=screen.devicePixelRatio()
                native=QRect(logical.x(),logical.y(),round(logical.width()*ratio),round(logical.height()*ratio))
                mappings.append(ScreenMapping(screen.name(),logical,native));root=root.united(native)
            return cls(root,mappings)
        env=os.environ.copy()
        if 'LD_LIBRARY_PATH_ORIG' in env:env['LD_LIBRARY_PATH']=env['LD_LIBRARY_PATH_ORIG']
        elif getattr(__import__('sys'),'frozen',False):env.pop('LD_LIBRARY_PATH',None)
        root=None;native={}
        try:
            result=subprocess.run(['xrandr','--current'],capture_output=True,text=True,env=env,timeout=3)
            size=re.search(r'current\s+(\d+)\s+x\s+(\d+)',result.stdout)
            if size:root=QRect(0,0,int(size[1]),int(size[2]))
            for match in re.finditer(r'^(\S+)\s+connected(?:\s+primary)?\s+(\d+)x(\d+)([+-]\d+)([+-]\d+)',result.stdout,re.M):
                name,w,h,x,y=match.groups();native[name]=QRect(int(x),int(y),int(w),int(h))
        except (OSError,subprocess.TimeoutExpired):pass
        if root is None:
            try:
                lib=ctypes.CDLL('libX11.so.6');lib.XOpenDisplay.restype=ctypes.c_void_p
                lib.XDefaultScreen.argtypes=[ctypes.c_void_p]
                for name in ['XDisplayWidth','XDisplayHeight']:getattr(lib,name).argtypes=[ctypes.c_void_p,ctypes.c_int]
                lib.XCloseDisplay.argtypes=[ctypes.c_void_p];display=lib.XOpenDisplay(None)
                if display:
                    index=lib.XDefaultScreen(display);root=QRect(0,0,lib.XDisplayWidth(display,index),lib.XDisplayHeight(display,index));lib.XCloseDisplay(display)
            except OSError:pass
        mappings=[]
        for screen in screens:
            logical=screen.geometry();physical=native.get(screen.name())
            if physical is None:
                if len(screens)==1 and root is not None:physical=root
                else:
                    ratio=screen.devicePixelRatio()
                    physical=QRect(logical.x(),logical.y(),round(logical.width()*ratio),round(logical.height()*ratio))
            mappings.append(ScreenMapping(screen.name(),QRect(logical),QRect(physical)))
        if root is None:
            root=QRect()
            for screen in mappings:root=root.united(screen.native)
        return cls(root,mappings)

    def to_native(self,rectangle):
        result=QRect()
        for screen in self.mappings:
            part=rectangle.intersected(screen.logical)
            if part.isEmpty():continue
            logical=screen.logical;native=screen.native
            sx=native.width()/logical.width();sy=native.height()/logical.height()
            x=native.x()+math.floor((part.x()-logical.x())*sx+1e-8)
            y=native.y()+math.floor((part.y()-logical.y())*sy+1e-8)
            right=native.x()+math.ceil((part.x()+part.width()-logical.x())*sx-1e-8)
            bottom=native.y()+math.ceil((part.y()+part.height()-logical.y())*sy-1e-8)
            result=result.united(QRect(x,y,right-x,bottom-y))
        return result.intersected(self.root)


def screen_choices(geometry,primary_name):
    primary=next((s for s in geometry.mappings if s.name==primary_name),geometry.mappings[0] if geometry.mappings else None)
    result=[('全屏录制',primary.native if primary else geometry.root,'fullscreen')]
    if len(geometry.mappings)>1:
        for index,screen in enumerate(geometry.mappings):
            suffix='（主屏）' if screen is primary else ''
            result.append((f'屏幕 {index+1} · {screen.name}{suffix}',screen.native,'screen:'+screen.name))
        result.append(('所有屏幕',geometry.root,'all'))
    result.append(('框选 / 自定义区域',None,'custom'));return result
