"""Wayland bridge lifecycle and real GStreamer-to-MP4 regression checks."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PyQt5.QtCore import QRect
from app.recording.geometry import CaptureGeometry
if sys.platform.startswith('linux'):
    from app.recording.wayland_capture import Capture
else:
    Capture=None

@unittest.skipUnless(sys.platform.startswith('linux'), 'Wayland is Linux-only')
class WaylandTests(unittest.TestCase):
    def test_portal_requests_are_subscribed_before_async_call(self):
        capture=Capture.__new__(Capture);capture.bus=Mock();capture.bus.get_unique_name.return_value=':1.42';capture.portal=Mock();capture.closed=False
        callback=Mock();capture.request_call('CreateSession',[],{'session_handle_token':'session'},callback)
        options=capture.portal.CreateSession.call_args.args[0]
        path=capture.bus.add_signal_receiver.call_args.kwargs['path']
        self.assertEqual(path,'/org/freedesktop/portal/desktop/request/1_42/'+str(options['handle_token']))
        self.assertEqual(str(options['session_handle_token']),'session')
        response=capture.bus.add_signal_receiver.call_args.args[0];response(0,{'session_handle':'/session'})
        callback.assert_called_once_with({'session_handle':'/session'});self.assertIsNone(capture.request)
    def test_cancelled_permission_does_not_start_encoding(self):
        capture=Capture.__new__(Capture);capture.bus=Mock();capture.bus.get_unique_name.return_value=':1.42';capture.portal=Mock();capture.closed=False;capture.event=Mock();capture.finish=Mock()
        callback=Mock();capture.request_call('Start',['/session',''],{},callback)
        response=capture.bus.add_signal_receiver.call_args.args[0];response(1,{})
        callback.assert_not_called();capture.event.assert_called_once_with(event='cancelled');capture.finish.assert_called_once_with(0)
    def test_wayland_geometry_uses_qt_scale_and_never_xrandr(self):
        screen=Mock();screen.geometry.return_value=QRect(0,0,1920,1080);screen.devicePixelRatio.return_value=2;screen.name.return_value='DP-1'
        with patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland'}),patch('app.recording.geometry.subprocess.run') as run:
            geometry=CaptureGeometry.detect([screen]);run.assert_not_called()
        self.assertEqual(geometry.root,QRect(0,0,3840,2160))
    def test_real_encoder_stops_and_saves_full_and_cropped_video(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-wayland-') as folder:
            for crop,output,expected in ((None,[0,0],(320,240)),([20,30,160,120],[640,480],(640,480))):
                path=Path(folder)/('crop.mp4' if crop else 'full.mp4')
                config={'ffmpeg':'/usr/bin/ffmpeg','destination':str(path),'fps':24,'crf':23,'preset':'ultrafast','cursor':True,'output':output,'crop':crop}
                process=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).resolve().parents[1]/'app'/'recording'/'wayland_capture.py'),json.dumps(config),'--test-source'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                stopped=False
                try:
                    for line in process.stdout:
                        if line.startswith('frame=') and int(line.split('=',1)[1])>=12:
                            process.stdin.write('q\n');process.stdin.flush();stopped=True;break
                    out,error=process.communicate(timeout=30)
                    self.assertEqual(process.returncode,0,error);self.assertTrue(stopped,error)
                    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
                    video=data['streams'][0];self.assertEqual((video['width'],video['height']),expected);self.assertEqual(video['avg_frame_rate'],'24/1');self.assertGreaterEqual(int(video['nb_frames']),12)
                finally:
                    if process.poll() is None:process.kill();process.communicate()

if __name__=='__main__':unittest.main()
