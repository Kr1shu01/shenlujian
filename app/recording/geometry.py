"""Translate Qt desktop selections to native X11, Windows or portal pixels."""
import ctypes,math,os,re,subprocess,sys
from dataclasses import dataclass
from PyQt5.QtCore import QRect


@dataclass
class ScreenMapping:
    name: str
    logical: QRect
    native: QRect


def windows_native_rectangles(user32=None):
    """Return physical monitor bounds keyed by the QScreen Windows device name.

    Startup establishes per-monitor DPI awareness before QApplication is made.
    Using monitor RECTs instead of multiplying a desktop origin by a DPR is
    essential for screens left/above the primary and mixed display scaling.
    """
    if user32 is None:user32=ctypes.WinDLL('user32',use_last_error=True)
    class Rect(ctypes.Structure):
        _fields_=[('left',ctypes.c_int32),('top',ctypes.c_int32),
                  ('right',ctypes.c_int32),('bottom',ctypes.c_int32)]
    class MonitorInfo(ctypes.Structure):
        _fields_=[('cbSize',ctypes.c_uint32),('rcMonitor',Rect),('rcWork',Rect),
                  ('dwFlags',ctypes.c_uint32),('szDevice',ctypes.c_wchar*32)]
    callback_type=getattr(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE)(
        ctypes.c_int32,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(Rect),ctypes.c_ssize_t)
    user32.EnumDisplayMonitors.argtypes=[ctypes.c_void_p,ctypes.POINTER(Rect),callback_type,ctypes.c_ssize_t]
    user32.EnumDisplayMonitors.restype=ctypes.c_int32
    user32.GetMonitorInfoW.argtypes=[ctypes.c_void_p,ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype=ctypes.c_int32
    native={}
    @callback_type
    def visit(monitor,hdc,rectangle,data):
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
            r=info.rcMonitor
            native[info.szDevice.casefold()]=QRect(r.left,r.top,r.right-r.left,r.bottom-r.top)
        return 1
    if not user32.EnumDisplayMonitors(None,None,visit,0):
        raise OSError('无法读取 Windows 显示器布局。')
    return native


class CaptureGeometry:
    def __init__(self,root,mappings):
        self.root=QRect(root);self.mappings=mappings
        self.logical_bounds=QRect()
        for screen in mappings:self.logical_bounds=self.logical_bounds.united(screen.logical)

    @classmethod
    def detect(cls,screens):
        if sys.platform=='win32':
            try:native=windows_native_rectangles()
            except (OSError,AttributeError):native={}
            mappings=[];root=QRect()
            for screen in screens:
                logical=QRect(screen.geometry());physical=native.get(screen.name().casefold())
                if physical is None:
                    ratio=screen.devicePixelRatio()
                    physical=QRect(logical.x(),logical.y(),round(logical.width()*ratio),round(logical.height()*ratio))
                mappings.append(ScreenMapping(screen.name(),logical,QRect(physical)));root=root.united(physical)
            return cls(root,mappings)
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
