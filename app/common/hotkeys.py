"""F9/F10 passive X11 grabs, delivered on Qt's event loop even when minimized."""
import ctypes as C
import os
from PyQt5.QtCore import QObject,QSocketNotifier


class XKeyEvent(C.Structure):
    _fields_=[('type',C.c_int),('serial',C.c_ulong),('send_event',C.c_int),('display',C.c_void_p),
        ('window',C.c_ulong),('root',C.c_ulong),('subwindow',C.c_ulong),('time',C.c_ulong),
        ('x',C.c_int),('y',C.c_int),('x_root',C.c_int),('y_root',C.c_int),
        ('state',C.c_uint),('keycode',C.c_uint),('same_screen',C.c_int)]
class XEvent(C.Union):_fields_=[('key',XKeyEvent),('pad',C.c_long*24)]
class XErrorEvent(C.Structure):
    _fields_=[('type',C.c_int),('display',C.c_void_p),('resourceid',C.c_ulong),('serial',C.c_ulong),
        ('error_code',C.c_ubyte),('request_code',C.c_ubyte),('minor_code',C.c_ubyte)]
class XModifierMap(C.Structure):_fields_=[('max_keypermod',C.c_int),('modifiermap',C.POINTER(C.c_ubyte))]


class GlobalHotkeys(QObject):
    def __init__(self,parent,callbacks):
        super().__init__(parent);self.display=None;self.notifier=None;self.grabs=[];self.callbacks={};self.registered=set();self.error=''
        if os.environ.get("XDG_SESSION_TYPE")=="wayland":
            self.error="Wayland 下 F9/F10 在应用窗口内生效；也可使用开始与停止按钮。";return
        try:self.setup(callbacks)
        except (OSError,RuntimeError) as error:self.error=str(error);self.close()

    def setup(self,callbacks):
        self.x=C.CDLL('libX11.so.6');x=self.x
        signatures={
            'XOpenDisplay':([C.c_char_p],C.c_void_p),'XDefaultRootWindow':([C.c_void_p],C.c_ulong),
            'XConnectionNumber':([C.c_void_p],C.c_int),'XStringToKeysym':([C.c_char_p],C.c_ulong),
            'XKeysymToKeycode':([C.c_void_p,C.c_ulong],C.c_ubyte),
            'XGetModifierMapping':([C.c_void_p],C.POINTER(XModifierMap)),
            'XFreeModifiermap':([C.POINTER(XModifierMap)],C.c_int),
            'XGrabKey':([C.c_void_p,C.c_int,C.c_uint,C.c_ulong,C.c_int,C.c_int,C.c_int],C.c_int),
            'XUngrabKey':([C.c_void_p,C.c_int,C.c_uint,C.c_ulong],C.c_int),
            'XSync':([C.c_void_p,C.c_int],C.c_int),'XSetErrorHandler':([C.c_void_p],C.c_void_p),
            'XPending':([C.c_void_p],C.c_int),'XNextEvent':([C.c_void_p,C.POINTER(XEvent)],C.c_int),
            'XCloseDisplay':([C.c_void_p],C.c_int)}
        for name,(args,result) in signatures.items():getattr(x,name).argtypes=args;getattr(x,name).restype=result
        self.display=x.XOpenDisplay(None)
        if not self.display:raise RuntimeError('无法连接 X11，全局 F9/F10 不可用。')
        self.root=x.XDefaultRootWindow(self.display)
        modifiers={2};mapping=x.XGetModifierMapping(self.display)
        if mapping:
            try:
                keys={x.XKeysymToKeycode(self.display,x.XStringToKeysym(name)) for name in (b'Num_Lock',b'Scroll_Lock')}
                keys.discard(0)
                for index in range(8):
                    if any(mapping.contents.modifiermap[index*mapping.contents.max_keypermod+j] in keys for j in range(mapping.contents.max_keypermod)):
                        modifiers.add(1<<index)
            finally:x.XFreeModifiermap(mapping)
        variants={0}
        for mask in modifiers:variants|={value|mask for value in list(variants)}
        errors=[];handler_type=C.CFUNCTYPE(C.c_int,C.c_void_p,C.POINTER(XErrorEvent))
        @handler_type
        def handler(display,event):
            if display==self.display:errors.append(event.contents.error_code);return 0
            return handler_type(previous)(display,event) if previous else 0
        x.XSync(self.display,0);previous=x.XSetErrorHandler(C.cast(handler,C.c_void_p))
        try:
            for name,callback in callbacks.items():
                code=x.XKeysymToKeycode(self.display,x.XStringToKeysym(name.encode()));errors.clear();attempt=[]
                if not code:self.error+=name+' 不可用。 ';continue
                for mask in variants:
                    x.XGrabKey(self.display,code,mask,self.root,0,1,1);attempt.append((code,mask))
                x.XSync(self.display,0)
                if errors:
                    for key,mask in attempt:x.XUngrabKey(self.display,key,mask,self.root)
                    self.error+=name+' 已被其他应用占用；仅在窗口内生效。 '
                else:
                    self.grabs.extend(attempt);self.registered.add(name);self.callbacks[code]=callback
            x.XSync(self.display,0)
        finally:x.XSetErrorHandler(previous)
        self.notifier=QSocketNotifier(x.XConnectionNumber(self.display),QSocketNotifier.Read,self)
        self.notifier.activated.connect(self.drain)

    def drain(self,*_):
        while self.display and self.x.XPending(self.display):
            event=XEvent();self.x.XNextEvent(self.display,C.byref(event))
            if event.key.type==2:
                callback=self.callbacks.get(event.key.keycode)
                if callback:callback()

    def close(self):
        if self.notifier:self.notifier.setEnabled(False)
        if self.display:
            for code,mask in self.grabs:self.x.XUngrabKey(self.display,code,mask,self.root)
            self.x.XCloseDisplay(self.display);self.display=None
