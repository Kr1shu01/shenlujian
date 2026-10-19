"""Native Windows/X11 F9/F10 hotkeys delivered on Qt's GUI thread."""
import ctypes as C
import os
import sys
from PyQt5.QtCore import QAbstractNativeEventFilter,QCoreApplication,QObject,QSocketNotifier,QTimer


class WindowsMessage(C.Structure):
    # Windows LONG/DWORD are 32-bit even on x64; WPARAM/LPARAM are pointer-sized.
    _fields_=[('hwnd',C.c_void_p),('message',C.c_uint32),('wParam',C.c_size_t),
              ('lParam',C.c_ssize_t),('time',C.c_uint32),
              ('x',C.c_int32),('y',C.c_int32),('lPrivate',C.c_uint32)]


class WindowsHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self,callbacks):
        super().__init__();self.callbacks=callbacks

    def nativeEventFilter(self,event_type,message):
        if bytes(event_type) not in (b'windows_dispatcher_MSG',b'windows_generic_MSG'):
            return False,0
        native=WindowsMessage.from_address(int(message))
        callback=self.callbacks.get(native.wParam) if native.message==0x0312 else None
        if callback:
            # Defer widget/FFmpeg state transitions until the native dispatch ends.
            identifier=native.wParam
            QTimer.singleShot(0,lambda:self.dispatch(identifier))
            return True,0
        return False,0

    def dispatch(self,identifier):
        # close() clears this shared registry; an already queued event must not
        # call a recorder widget that is being torn down.
        callback=self.callbacks.get(identifier)
        if callback:callback()


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
        self.windows_api=None;self.native_filter=None;self.application=None
        if sys.platform=='win32':
            try:self.setup_windows(callbacks)
            except (OSError,RuntimeError,AttributeError) as error:
                self.error='Windows 全局 F9/F10 不可用；仅在窗口内生效。 '+str(error);self.close()
            return
        if os.environ.get("XDG_SESSION_TYPE")=="wayland":
            self.error="Wayland 下 F9/F10 在应用窗口内生效；也可使用开始与停止按钮。";return
        try:self.setup(callbacks)
        except (OSError,RuntimeError) as error:self.error=str(error);self.close()

    def setup_windows(self,callbacks):
        self.application=QCoreApplication.instance()
        if self.application is None:raise RuntimeError('需要先创建 Qt 应用。')
        self.windows_api=C.WinDLL('user32',use_last_error=True)
        self.windows_api.RegisterHotKey.argtypes=[C.c_void_p,C.c_int,C.c_uint,C.c_uint]
        self.windows_api.RegisterHotKey.restype=C.c_int32
        self.windows_api.UnregisterHotKey.argtypes=[C.c_void_p,C.c_int]
        self.windows_api.UnregisterHotKey.restype=C.c_int32
        self.native_filter=WindowsHotkeyFilter(self.callbacks)
        self.application.installNativeEventFilter(self.native_filter)
        for index,(name,callback) in enumerate(callbacks.items()):
            virtual_key={'F9':0x78,'F10':0x79}.get(name)
            identifier=0x5300+index
            if virtual_key is None:
                self.error+=name+' 不可用。 ';continue
            # NULL HWND routes WM_HOTKEY through Qt's thread event dispatcher,
            # so minimization or recreation of the main HWND cannot break it.
            if self.windows_api.RegisterHotKey(None,identifier,0x4000,virtual_key):
                self.grabs.append(identifier);self.registered.add(name);self.callbacks[identifier]=callback
            else:self.error+=name+' 已被其他应用占用；仅在窗口内生效。 '
        self.application.aboutToQuit.connect(self.close)

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
        if self.windows_api:
            for identifier in self.grabs:self.windows_api.UnregisterHotKey(None,identifier)
            self.grabs.clear();self.callbacks.clear();self.registered.clear()
            self.windows_api=None
        if self.native_filter:
            try:self.application.removeNativeEventFilter(self.native_filter)
            except RuntimeError:pass  # QApplication can already be shutting down.
            self.native_filter=None
        if self.notifier:self.notifier.setEnabled(False)
        if self.display:
            for code,mask in self.grabs:self.x.XUngrabKey(self.display,code,mask,self.root)
            self.x.XCloseDisplay(self.display);self.display=None
