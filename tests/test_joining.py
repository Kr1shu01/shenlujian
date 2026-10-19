import array,hashlib,json,math,subprocess,tempfile,unittest
import sys
from pathlib import Path
from app.editor.operations import VideoInfo
from app.editor.joining import concatenate_arguments


class JoiningTests(unittest.TestCase):
    def test_mixed_dimensions_fps_audio_and_order(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-join-') as directory:
            folder=Path(directory);infos=[];hashes=[]
            quote='\'' if sys.platform=='win32' else '"'
            definitions=[('红 $ clip', 'red','64x64',30,1.2,True),('绿 silent','green','96x64',24,1,False),(f'蓝 {quote} clip','blue','80x96',15,1.6,True)]
            probe=lambda p:json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
            for name,color,size,fps,duration,audio in definitions:
                path=folder/(name+'.mp4')
                args=['ffmpeg','-v','error','-f','lavfi','-i',f'color=c={color}:s={size}:r={fps}:d={duration}']
                if audio:args+=['-f','lavfi','-i',f'sine=frequency=440:sample_rate=32000:duration={duration}','-c:a','aac']
                args+=['-c:v','libx264','-pix_fmt','yuv420p','-shortest',str(path)]
                subprocess.run(args,check=True,stderr=subprocess.PIPE)
                infos.append(VideoInfo.from_probe(path,probe(path)));hashes.append(hashlib.sha256(path.read_bytes()).digest())
            target=folder/f'拼接 $ {quote} .mp4';args,duration=concatenate_arguments(infos,target,crf=18)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            meta=probe(target);v=next(s for s in meta['streams'] if s['codec_type']=='video');a=next(s for s in meta['streams'] if s['codec_type']=='audio')
            self.assertEqual((v['width'],v['height'],v['avg_frame_rate']),(64,64,'30/1'))
            self.assertEqual((a['channels'],a['sample_rate']),(2,'48000'))
            self.assertAlmostEqual(float(meta['format']['duration']),duration,delta=.07)
            self.assertLess(abs(float(a['duration'])-float(v['duration'])),.07)
            for time,channel in [(0.5,0),(1.7,1),(3.1,2)]:
                rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-i',str(target),'-frames:v','1','-vf','scale=1:1:flags=neighbor','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
                self.assertEqual(max(range(3),key=lambda i:rgb[i]),channel)
            rms=[]
            for time in [.3,1.5,2.7]:
                raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-t','0.3','-i',str(target),'-map','0:a:0','-f','f32le','-c:a','pcm_f32le','pipe:1'])
                samples=array.array('f');samples.frombytes(raw);rms.append(math.sqrt(sum(x*x for x in samples)/len(samples)))
            self.assertGreater(rms[0],.02);self.assertLess(rms[1],.001);self.assertGreater(rms[2],.02)
            reverse=folder/'反序无声.mp4';args,_=concatenate_arguments(list(reversed(infos)),reverse,audio=False)
            subprocess.run(['ffmpeg',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            self.assertFalse(any(s['codec_type']=='audio' for s in probe(reverse)['streams']))
            rgb=subprocess.check_output(['ffmpeg','-v','error','-ss','0.4','-i',str(reverse),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
            self.assertEqual(max(range(3),key=lambda i:rgb[i]),2)
            self.assertEqual([hashlib.sha256(i.path.read_bytes()).digest() for i in infos],hashes)

    def test_requires_multiple_clips(self):
        with self.assertRaises(ValueError):concatenate_arguments([],Path('/tmp/unused.mp4'))


if __name__=='__main__':unittest.main()
