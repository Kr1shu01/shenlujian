import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from editing import VideoInfo, export_arguments, kept_ranges, merge_cuts, tempo_chain


class EditingTests(unittest.TestCase):
    def test_overlapping_and_adjacent_deletions_are_merged(self):
        self.assertEqual(merge_cuts([(9,12),(3,6),(5,9)],20),[(3,12)])
        self.assertEqual(kept_ranges(20,2,18,[(3,12)]),[(2,3),(12,18)])

    def test_cannot_delete_all_frames(self):
        with self.assertRaises(ValueError): kept_ranges(20,0,20,[(0,20)])

    def test_audio_speed_chain_supports_slow_and_fast_playback(self):
        self.assertEqual(tempo_chain(.125),'atempo=0.5,atempo=0.5,atempo=0.5')
        self.assertEqual(tempo_chain(8),'atempo=2,atempo=2,atempo=2')

    def test_frame_exact_deletion_speed_and_audio(self):
        with tempfile.TemporaryDirectory(prefix='shenlujian-') as directory:
            source=Path(directory)/"源视频 空格.mp4"
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',"nullsrc=s=64x64:r=30:d=4,geq=lum='16+N':cb=128:cr=128",
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
                            '-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
            probe=lambda p: json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
            info=VideoInfo.from_probe(source,probe(source))
            cuts=[(10,20),(50,51)]
            target=Path(directory)/'删帧 $x.mp4'
            arguments,duration,ranges=export_arguments(info,target,0,100,cuts,crf=0)
            subprocess.run(['ffmpeg',*arguments],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(target),'-map','0:v:0','-vsync','0','-f','rawvideo','-pix_fmt','yuv420p','pipe:1'])
            stride=64*64*3//2
            pixels=[raw[i] for i in range(0,len(raw),stride)]
            expected=[16+frame for a,b in ranges for frame in range(a,b)]
            self.assertEqual(pixels,expected)
            self.assertEqual(len(pixels),89)
            self.assertTrue(any(s['codec_type']=='audio' for s in probe(target)['streams']))
            fast=Path(directory)/'倍速.mp4'
            arguments,expected_duration,_=export_arguments(info,fast,0,100,cuts,speed=1.5)
            subprocess.run(['ffmpeg',*arguments],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            metadata=probe(fast)
            video=next(s for s in metadata['streams'] if s['codec_type']=='video')
            audio=next(s for s in metadata['streams'] if s['codec_type']=='audio')
            self.assertAlmostEqual(float(metadata['format']['duration']),expected_duration,delta=.06)
            self.assertLess(abs(float(video['duration'])-float(audio['duration'])),.06)
            self.assertEqual(source.exists(),True)


if __name__=='__main__': unittest.main()
