import hashlib,json,subprocess,tempfile,unittest
from fractions import Fraction
from pathlib import Path
from editing import VideoInfo
from project_model import Project,project_export_arguments


class ProjectTests(unittest.TestCase):
    def info(self,name,duration=2,fps=30):return VideoInfo(Path('/tmp')/name,64,64,Fraction(fps),round(duration*fps),duration,False)
    def test_reorder_delete_across_clips_and_undo(self):
        p=Project();p.insert([self.info('a.mp4'),self.info('b.mp4'),self.info('c.mp4',fps=24)])
        ids=[c.uid for c in p.clips];self.assertEqual(p.frames,180)
        self.assertTrue(p.move(ids[0],3));self.assertEqual([c.info.path.name for c in p.clips],['b.mp4','c.mp4','a.mp4'])
        self.assertEqual(p.fps,Fraction(30));p.delete_range(50,130)
        self.assertEqual(p.frames,100);self.assertEqual([(c.info.path.name,c.start,c.end) for c in p.clips],[('b.mp4',0,50),('a.mp4',10,60)])
        self.assertEqual(p.locate(50)[2],10)
        p.undo();self.assertEqual(p.frames,180);p.undo();self.assertEqual([c.uid for c in p.clips],ids)
        p.redo();self.assertEqual(p.clips[-1].uid,ids[0])
        p.delete_range(0,p.frames);self.assertEqual(p.frames,0);p.undo();self.assertEqual(p.frames,180)

    def test_clip_speed_selection_delete_and_stable_colors(self):
        p=Project();p.insert([self.info('a.mp4'),self.info('b.mp4'),self.info('c.mp4')])
        a,b,c=p.clips;colors={clip.uid:clip.color for clip in p.clips}
        p.move(a.uid,3);self.assertEqual({clip.uid:clip.color for clip in p.clips},colors)
        p.set_clip_speed(b.uid,2);self.assertEqual(p.frames,150)
        self.assertEqual([clip.speed for clip in p.clips],[2,1,1]);self.assertEqual(p.locate(29)[2],58)
        p.delete_range(5,8);self.assertEqual(p.frames,147)
        self.assertEqual(p.clips[0].color,p.clips[1].color)
        self.assertEqual(p.locate(5)[2],16)
        p.undo();p.undo();self.assertEqual(p.frames,180)
        self.assertTrue(p.delete_clip(c.uid));self.assertEqual(p.frames,120)
        p.undo();self.assertEqual({clip.uid:clip.color for clip in p.clips},colors)
        p.set_clip_speed(b.uid,.25);self.assertEqual(p.clips[0].frames,240)
        p.delete_range(1,2);self.assertEqual(p.frames,359)
        self.assertEqual(p.locate(1)[2],0)

    def test_speed_export_and_frame_deletion_at_fast_and_slow_rates(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-clip-speed-') as folder:
            source=Path(folder)/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',"nullsrc=s=64x64:r=30:d=2,geq=lum='16+N':cb=128:cr=128",
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(source)]))
            def frames(path):
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-vsync','0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
                return [raw[i] for i in range(0,len(raw),64*64*3//2)]
            for speed in (.25,.5,1.5,2):
                p=Project();p.insert([VideoInfo.from_probe(source,metadata)]);p.set_clip_speed(p.clips[0].uid,speed)
                full=Path(folder)/f'full-{speed}.mp4';args,duration=project_export_arguments(p,full,crf=0)
                subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                reference=frames(full);self.assertEqual(len(reference),p.frames)
                p.delete_range(5,8);p.delete_range(11,12)
                edited=Path(folder)/f'edited-{speed}.mp4';args,duration=project_export_arguments(p,edited,crf=0)
                subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                expected=reference[:5]+reference[8:];expected=expected[:11]+expected[12:]
                self.assertEqual(frames(edited),expected)
                data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(edited)]))
                self.assertAlmostEqual(float(data['format']['duration']),duration,delta=.07)
                self.assertTrue(any(stream['codec_type']=='audio' for stream in data['streams']))

    def test_frame_exact_export_after_splitting_one_source(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-project-') as folder:
            source=Path(folder)/'源 $ video.mp4';target=Path(folder)/'剪辑项目.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',"nullsrc=s=64x64:r=30:d=4,geq=lum='16+N':cb=128:cr=128",
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4','-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(source)]))
            p=Project();p.insert([VideoInfo.from_probe(source,metadata)]);original=hashlib.sha256(source.read_bytes()).digest()
            p.delete_range(10,20);p.delete_range(40,41)
            args,duration=project_export_arguments(p,target,crf=0)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(target),'-map','0:v:0','-vsync','0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
            values=[raw[i] for i in range(0,len(raw),64*64*3//2)]
            self.assertEqual(values,[16+i for i in list(range(10))+list(range(20,50))+list(range(51,120))])
            fast=Path(folder)/'倍速.mp4';args,length=project_export_arguments(p,fast,speed=1.5)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(fast)]))
            self.assertAlmostEqual(float(metadata['format']['duration']),length,delta=.07)
            self.assertTrue(any(s['codec_type']=='audio' for s in metadata['streams']))
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),original)


if __name__=='__main__':unittest.main()
