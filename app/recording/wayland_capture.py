#!/usr/bin/env python3
"""System-Python portal/PipeWire bridge; stdout carries FFmpeg progress."""
import json,os,signal,subprocess,sys,threading,uuid
import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi
gi.require_version('Gst','1.0');gi.require_version('GstVideo','1.0')
from gi.repository import GLib,Gst,GstVideo

class Capture:
    def __init__(self,config,test_source=False):
        self.config=config;self.loop=GLib.MainLoop();self.session=None;self.request=None;self.pipeline=None;self.encoder=None;self.closed=False;self.frames=0;self.fd=None;self.test_source=test_source;self.output_lock=threading.Lock()
        DBusGMainLoop(set_as_default=True);Gst.init(None)
        self.bus=None if test_source else dbus.SessionBus();self.portal=dbus.Interface(self.bus.get_object('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop'),'org.freedesktop.portal.ScreenCast') if not test_source else None
        threading.Thread(target=self.commands,daemon=True).start()
    def event(self,**values):
        with self.output_lock:print(json.dumps(values,ensure_ascii=False),flush=True)
    def request_call(self,name,args,options,callback):
        token='slj_'+uuid.uuid4().hex;options=dict(options,handle_token=token)
        sender=self.bus.get_unique_name()[1:].replace('.','_');path='/org/freedesktop/portal/desktop/request/'+sender+'/'+token
        self.request=path
        def response(code,result):
            match.remove();self.request=None
            if self.closed:return
            if int(code):self.event(event='cancelled');self.finish(0);return
            try:callback(result)
            except Exception as error:self.fail(error)
        match=self.bus.add_signal_receiver(response,signal_name='Response',dbus_interface='org.freedesktop.portal.Request',path=path)
        getattr(self.portal,name)(*args,dbus.Dictionary(options,signature='sv'),reply_handler=lambda _path:None,error_handler=self.fail)
    def start(self):
        if self.test_source:self.start_pipeline('videotestsrc is-live=true pattern=ball ! video/x-raw,width=320,height=240');return
        self.event(event='permission')
        self.request_call('CreateSession',[],{'session_handle_token':'slj_'+uuid.uuid4().hex},self.created)
    def created(self,result):
        self.session=str(result['session_handle'])
        self.bus.add_signal_receiver(lambda *_:self.stop(),signal_name='Closed',dbus_interface='org.freedesktop.portal.Session',path=self.session)
        self.request_call('SelectSources',[dbus.ObjectPath(self.session)],{'types':dbus.UInt32(1),'multiple':False,'cursor_mode':dbus.UInt32(2 if self.config['cursor'] else 1)},self.selected)
    def selected(self,result):self.request_call('Start',[dbus.ObjectPath(self.session),''],{},self.granted)
    def granted(self,result):
        streams=result.get('streams',[])
        if len(streams)!=1:raise ValueError('请在系统共享对话框中选择一个屏幕。')
        node,properties=streams[0];self.fd=self.portal.OpenPipeWireRemote(dbus.ObjectPath(self.session),dbus.Dictionary({},signature='sv')).take()
        # New portals provide a stable serial; older portals provide the live node ID.
        target='stream-properties="props,target.object=(string)'+str(int(properties['pipewire-serial']))+'"' if 'pipewire-serial' in properties else 'path='+str(int(node))
        self.start_pipeline('pipewiresrc fd='+str(self.fd)+' '+target+' do-timestamp=true keepalive-time=100')
    def start_pipeline(self,source):
        self.pipeline=Gst.parse_launch(source+' ! queue max-size-buffers=3 ! videoconvert ! videorate ! video/x-raw,format=RGB,framerate='+str(self.config['fps'])+'/1 ! appsink name=sink emit-signals=true sync=false max-buffers=2')
        self.pipeline.get_by_name('sink').connect('new-sample',self.sample)
        bus=self.pipeline.get_bus();bus.add_signal_watch();bus.connect('message',self.message)
        self.pipeline.set_state(Gst.State.PLAYING)
        GLib.timeout_add_seconds(30,self.check_started)
    def check_started(self):
        if not self.closed and not self.frames:self.fail('屏幕共享没有返回画面，请检查 PipeWire 和桌面 portal。')
        return False
    def sample(self,sink):
        sample=sink.emit('pull-sample')
        if self.closed:return Gst.FlowReturn.EOS
        try:
            info=GstVideo.VideoInfo.new_from_caps(sample.get_caps());width,height=info.width,info.height
            if self.encoder is None:self.start_encoder(width,height)
            buffer=sample.get_buffer();raw=buffer.extract_dup(0,buffer.get_size());meta=GstVideo.buffer_get_video_meta(buffer)
            stride=meta.stride[0] if meta else info.stride[0];offset=meta.offset[0] if meta else info.offset[0];row=width*3
            pixels=raw[offset:offset+row*height] if stride==row else b''.join(raw[offset+y*stride:offset+y*stride+row] for y in range(height))
            self.encoder.stdin.write(pixels);self.frames+=1
            return Gst.FlowReturn.OK
        except Exception as error:GLib.idle_add(self.fail,error);return Gst.FlowReturn.ERROR
    def start_encoder(self,width,height):
        c=self.config;x,y,w,h=c['crop'] if c.get('crop') else (0,0,width,height)
        if min(x,y)<0 or min(w,h)<2 or x+w>width or y+h>height:raise ValueError(f'区域超出共享画面 {width}×{height}；Wayland 坐标从所选屏幕左上角计算。')
        ow,oh=c['output'];ow=(ow or w)//2*2;oh=(oh or h)//2*2
        filters=f'crop={w}:{h}:{x}:{y},scale={ow}:{oh}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,setsar=1'
        args=[c['ffmpeg'],'-hide_banner','-loglevel','warning','-n','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{width}x{height}','-framerate',str(c['fps']),'-i','pipe:0','-vf',filters,'-c:v','libx264','-preset',c['preset'],'-crf',str(c['crf']),'-pix_fmt','yuv420p','-threads','4','-movflags','+faststart','-progress','pipe:1','-stats_period','0.5',c['destination']]
        self.encoder=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        self.event(event='recording',width=ow,height=oh,fps=c['fps'])
        def progress():
            for line in self.encoder.stdout:
                with self.output_lock:sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
        threading.Thread(target=progress,daemon=True).start()
    def message(self,bus,message):
        if message.type==Gst.MessageType.ERROR:self.fail(message.parse_error()[0])
        elif message.type==Gst.MessageType.EOS:self.finish(0)
    def commands(self):
        for line in sys.stdin:
            if line.strip()=='q':GLib.idle_add(self.stop);return
        GLib.idle_add(self.stop)
    def stop(self):
        if self.closed:return False
        if self.encoder and self.frames:self.pipeline.send_event(Gst.Event.new_eos())
        else:self.event(event='cancelled');self.finish(0)
        return False
    def fail(self,error):
        if not self.closed:print(str(error),file=sys.stderr,flush=True);self.finish(1)
        return False
    def finish(self,code):
        if self.closed:return
        self.closed=True
        if self.pipeline:self.pipeline.set_state(Gst.State.NULL)
        if self.encoder:
            try:self.encoder.stdin.close();code=self.encoder.wait(timeout=30) or code
            except (OSError,subprocess.TimeoutExpired):self.encoder.kill();self.encoder.wait();code=1
        if self.request:
            try:dbus.Interface(self.bus.get_object('org.freedesktop.portal.Desktop',self.request),'org.freedesktop.portal.Request').Close()
            except dbus.DBusException:pass
        if self.session:
            try:dbus.Interface(self.bus.get_object('org.freedesktop.portal.Desktop',self.session),'org.freedesktop.portal.Session').Close()
            except dbus.DBusException:pass
        if self.fd is not None:os.close(self.fd)
        self.exit_code=code;self.loop.quit()
    def run(self):
        GLib.idle_add(self.start);self.loop.run();return getattr(self,'exit_code',1)

if __name__=='__main__':
    try:
        config=json.loads(sys.argv[1]);capture=Capture(config,'--test-source' in sys.argv[2:]);sys.exit(capture.run())
    except Exception as error:print(str(error),file=sys.stderr);sys.exit(1)
