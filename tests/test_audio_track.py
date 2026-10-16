import hashlib,json,math,struct,subprocess,tempfile,unittest
from pathlib import Path
from fractions import Fraction
from app.editor.operations import VideoInfo
from app.media.info import AudioInfo,probe_media
from app.editor.project import Project,project_export_arguments
from app.recording.geometry import CaptureGeometry,ScreenMapping,screen_choices
from PyQt5.QtCore import QRect


def frequency(path,seconds,hz):
    raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(seconds),'-i',str(path),'-t','0.1','-vn','-ac','1','-ar','48000','-f','f32le','pipe:1'])
    values=struct.unpack('<'+'f'*(len(raw)//4),raw);n=len(values)
    return 2/n*math.hypot(sum(v*math.cos(2*math.pi*hz*i/48000) for i,v in enumerate(values)),sum(v*math.sin(2*math.pi*hz*i/48000) for i,v in enumerate(values)))


class AudioTrackTests(unittest.TestCase):
    def video(self):return VideoInfo(Path('/tmp/video.mp4'),64,64,Fraction(30),60,2,True)
    def test_audio_metadata_cover_and_invalid_files(self):
        info=probe_media('/tmp/song.mp3',{'streams':[{'codec_type':'video','disposition':{'attached_pic':1}},{'codec_type':'audio'}],'format':{'duration':'3.1'}})
        self.assertIsInstance(info,AudioInfo);self.assertFalse(info.has_video)
        fallback=probe_media('/tmp/clip.flac',{'streams':[{'codec_type':'audio','duration':'N/A'}],'format':{'duration':'1.5'}})
        self.assertEqual(fallback.duration,1.5)
        with self.assertRaises(ValueError):probe_media('/tmp/broken',{'streams':[]})
    def test_audio_move_delete_speed_and_ripple_undo(self):
        p=Project();p.insert([self.video()]);p.insert_audio([AudioInfo(Path('/tmp/audio.wav'),3)],30)
        uid=p.audio_clips[0].uid;color=p.audio_clips[0].color
        self.assertEqual((p.video_frames,p.frames),(60,120));p.move_audio(uid,60);self.assertEqual(p.frames,150)
        p.undo();self.assertEqual(p.audio_clips[0].offset,30)
        p.set_clip_speed(uid,2);self.assertEqual(p.frames,75);self.assertEqual(p.audio_clips[0].color,color)
        p.undo();p.delete_range(30,60);self.assertEqual((p.video_frames,p.frames),(30,90))
        self.assertEqual((p.audio_clips[0].offset,p.audio_clips[0].source_frame(0)),(30,30))
        p.undo();p.delete_clip(uid);self.assertEqual(p.frames,60);p.undo();self.assertEqual(p.frames,120)
        p.clear();self.assertEqual(p.frames,0);p.undo();self.assertEqual(p.frames,120)
    def test_dynamic_screen_choices_use_primary_not_fixed_size(self):
        geometry=CaptureGeometry(QRect(0,0,6400,2160),[
            ScreenMapping('DP-0',QRect(0,0,2560,1440),QRect(0,0,2560,1440)),
            ScreenMapping('HDMI-0',QRect(2560,0,3840,2160),QRect(2560,0,3840,2160))])
        choices=screen_choices(geometry,'HDMI-0')
        self.assertEqual(choices[0],('全屏录制',QRect(2560,0,3840,2160),'fullscreen'))
        self.assertEqual(len(choices),5);self.assertFalse(any('3840' in c[0] or '2560' in c[0] for c in choices))
        self.assertEqual(choices[-2][1],geometry.root)
    def test_delayed_audio_mixes_with_original_and_continues_after_video(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-audio-export-') as folder:
            root=Path(folder);video=root/'video.mp4';song=root/'song.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=30:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','libx264','-c:a','aac','-shortest',str(video)],check=True)
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=3',str(song)],check=True)
            payload=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
            p=Project();p.insert([VideoInfo.from_probe(video,payload)]);p.insert_audio([AudioInfo(song,3)],30)
            hashes=[hashlib.sha256(path.read_bytes()).digest() for path in (video,song)]
            target=root/'mixed.mp4';args,duration=project_export_arguments(p,target)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(target)]))
            stream=next(s for s in data['streams'] if s['codec_type']=='video')
            self.assertEqual(int(stream['nb_frames']),120);self.assertAlmostEqual(float(data['format']['duration']),4,delta=.08)
            self.assertGreater(frequency(target,.3,440),.04);self.assertLess(frequency(target,.3,880),.015)
            self.assertGreater(frequency(target,1.3,440),.04);self.assertGreater(frequency(target,1.3,880),.04)
            self.assertLess(frequency(target,2.7,440),.015);self.assertGreater(frequency(target,2.7,880),.04)
            muted=root/'without-original.mp4';args,_=project_export_arguments(p,muted,audio=False,speed=2)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            self.assertLess(frequency(muted,.15,440),.015);self.assertGreater(frequency(muted,.7,880),.04)
            p.delete_range(30,60);edited=root/'ripple.mp4';args,length=project_export_arguments(p,edited)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            self.assertEqual(length,3);self.assertGreater(frequency(edited,1.2,880),.04)
            self.assertEqual(hashes,[hashlib.sha256(path.read_bytes()).digest() for path in (video,song)])
    def test_audio_only_export_is_valid_and_later_video_sets_picture_format(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-audio-only-') as folder:
            root=Path(folder);song=root/'clip.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=0.5',str(song)],check=True)
            p=Project();p.insert_audio([AudioInfo(song,.5)]);target=root/'audio-only.mp4'
            args,duration=project_export_arguments(p,target,crf=28)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))
            video=next(s for s in data['streams'] if s['codec_type']=='video');self.assertEqual((video['width'],video['height']),(1280,720))
            self.assertTrue(any(s['codec_type']=='audio' for s in data['streams']))
            p.insert([self.video()]);self.assertEqual((p.width,p.height),(64,64));self.assertEqual(p.frames,60)


if __name__=='__main__':unittest.main()
