"""Selected clip cuts must leave every other clip intact."""
import json,subprocess,tempfile,unittest
from pathlib import Path
from fractions import Fraction
from app.editor.operations import VideoInfo
from app.media.info import AudioInfo
from app.editor.project import Project,project_export_arguments
from tests.test_audio_track import frequency

class ClipRangeTests(unittest.TestCase):
    def video(self,name):return VideoInfo(Path('/tmp')/name,64,64,Fraction(30),90,3,False)
    def test_only_selected_video_changes_at_each_speed(self):
        for speed in (.25,.5,1,1.5,2):
            p=Project();p.insert([self.video('a.mp4'),self.video('b.mp4')]);p.insert_audio([AudioInfo(Path('/tmp/audio.wav'),5)],30)
            uid=p.clips[0].uid;p.set_clip_speed(uid,speed);clip=p.clips[0]
            other=p.clips[1];sounds=list(p.audio_clips);state=p.snapshot()
            reference=[clip.source_frame(i) for i in range(clip.frames)]
            self.assertTrue(p.delete_clip_range(uid,5,15))
            self.assertEqual([c.source_frame(i) for c in p.clips[:-1] for i in range(c.frames)],reference[:5]+reference[15:])
            self.assertEqual(p.clips[-1],other);self.assertEqual(p.audio_clips,sounds)
            self.assertEqual(len({c.uid for c in p.clips}),len(p.clips))
            p.undo();self.assertEqual(p.snapshot(),state);p.redo();self.assertEqual(p.clips[-1],other)
    def test_audio_scope_validation_and_full_removal(self):
        p=Project();p.insert([self.video('a.mp4')]);p.insert_audio([AudioInfo(Path('/tmp/music.wav'),3)],30);p.insert_audio([AudioInfo(Path('/tmp/other.wav'),3)],50)
        video=list(p.clips);target,other=p.audio_clips;history=len(p.history)
        self.assertFalse(p.delete_clip_range(target.uid,10,40));self.assertFalse(p.delete_clip_range(target.uid,40,121));self.assertFalse(p.delete_clip_range('missing',40,50))
        self.assertEqual(len(p.history),history)
        self.assertTrue(p.delete_clip_range(target.uid,40,50))
        self.assertEqual(p.clips,video);self.assertEqual(p.audio_clips[-1],other)
        self.assertEqual([(c.offset,c.start,c.end) for c in p.audio_clips[:-1]],[(30,0,10),(40,20,90)])
        p.undo();self.assertTrue(p.delete_clip_range(target.uid,30,120));self.assertEqual(p.audio_clips,[other]);self.assertEqual(p.clips,video)
        p.undo();self.assertEqual(p.audio_clips,[target,other])
    def test_actual_video_and_audio_export_after_scoped_cuts(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-selected-cut-') as folder:
            root=Path(folder);a=root/'a.mp4';b=root/'b.mp4';music=root/'music.wav';other=root/'other.wav'
            for path,start,duration in ((a,16,3),(b,120,1)):
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f"nullsrc=s=64x64:r=30:d={duration},geq=lum='{start}+N':cb=128:cr=128",'-c:v','libx264','-crf','0','-pix_fmt','yuv420p',str(path)],check=True)
            for path,hz,duration in ((music,880,3),(other,660,2)):
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:sample_rate=48000:duration={duration}',str(path)],check=True)
            p=Project();p.insert([VideoInfo.from_probe(path,json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))) for path in (a,b)])
            p.insert_audio([AudioInfo(music,3)],0);p.insert_audio([AudioInfo(other,2)],60)
            audio=list(p.audio_clips);self.assertTrue(p.delete_clip_range(p.clips[0].uid,30,45));self.assertEqual(p.audio_clips,audio)
            video_out=root/'video-cut.mp4';args,_=project_export_arguments(p,video_out,crf=0)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(video_out),'-map','0:v:0','-vsync','0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
            values=[raw[i] for i in range(0,len(raw),64*64*3//2)]
            self.assertEqual(values,list(range(16,46))+list(range(61,106))+list(range(120,150))+[149]*15)
            p.undo();video=list(p.clips);self.assertTrue(p.delete_clip_range(p.audio_clips[0].uid,30,45));self.assertEqual(p.clips,video);self.assertEqual(p.audio_clips[-1],audio[-1])
            audio_out=root/'audio-cut.mp4';args,_=project_export_arguments(p,audio_out,crf=0)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            measurements={t:{hz:frequency(audio_out,t,hz) for hz in (880,660)} for t in (.3,1.3,1.8,2.3,2.7)}
            variants={}
            if measurements[2.3][880]<=.04:
                index=args.index('-filter_complex')+1;original=args[index]
                graphs={
                    'sample_timestamps':original.replace('asetpts=PTS-STARTPTS','asetpts=N/SR/TB'),
                    'no_async_resampling':original.replace('aresample=48000:async=1:first_pts=0','aresample=48000'),
                    'no_unity_tempo':original.replace('atempo=1,','anull,'),
                }
                for name,graph in graphs.items():
                    candidate=root/(name+'.mp4');altered=list(args);altered[index]=graph;altered[-1]=str(candidate)
                    subprocess.run(['ffmpeg',*altered],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    variants[name]={t:frequency(candidate,t,880) for t in (.3,1.3,1.8,2.3,2.7)}
            details=json.dumps({'actual':measurements,'variants':variants})
            self.assertGreater(measurements[2.3][880],.04,details);self.assertGreater(measurements[2.3][660],.04,details)
            self.assertLess(frequency(audio_out,2.7,880),.015);self.assertGreater(frequency(audio_out,2.7,660),.04)

if __name__=='__main__':unittest.main()
