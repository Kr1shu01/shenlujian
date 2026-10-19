import tempfile
import unittest
from pathlib import Path
from app.recording.commands import RecordingOptions, ffmpeg_arguments, output_path


class RecordingTests(unittest.TestCase):
    def test_command_preserves_filename_without_shell(self):
        destination=Path("/tmp/录屏 spaces '$(touch unsafe)'.mp4")
        options=RecordingOptions(":1",30,40,1280,720,fps=60,crf=18)
        command=ffmpeg_arguments(options,destination)
        self.assertEqual(command[-1],str(destination))
        self.assertEqual(command[command.index("-i")+1],":1+30,40")
        self.assertEqual(command[command.index("-framerate")+1],"60")
        self.assertIn("-n",command)

    def test_output_presets_and_arbitrary_dimensions_use_native_capture(self):
        for target in [(1920,1080),(2560,1440),(3840,2160),(1001,777),(8192,4608)]:
            options=RecordingOptions(':1',100,120,320,180,output_width=target[0],output_height=target[1])
            args=ffmpeg_arguments(options,Path('/tmp/check.mp4'))
            self.assertEqual(args[args.index('-video_size')+1],'320x180')
            self.assertEqual(args[args.index('-i')+1],':1+100,120')
            self.assertIn(f'pad={target[0]//2*2}:{target[1]//2*2}',args[args.index('-vf')+1])

    def test_filename_collision_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            existing=Path(directory)/"test.mp4"
            existing.write_bytes(b"keep")
            (Path(directory)/"test_001.mp4").touch()
            self.assertEqual(output_path(directory,"test.mp4",False).name,"test_002.mp4")
            self.assertEqual(existing.read_bytes(),b"keep")

    def test_filename_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../movie","/tmp/movie","", "..","a\nb"):
                with self.assertRaises(ValueError): output_path(directory,name,False)

    def test_odd_dimensions_produce_valid_yuv420_size(self):
        options=RecordingOptions(":1",0,0,1025,769)
        self.assertEqual(options.video_size,(1024,768))
        arguments=ffmpeg_arguments(options,Path("/tmp/a.mp4"))
        self.assertIn("pad=1024:768",arguments[arguments.index("-vf")+1])

    def test_invalid_options_rejected_before_starting_ffmpeg(self):
        for options in [RecordingOptions("",0,0,1280,720),RecordingOptions(":1",-1,0,1280,720),
                        RecordingOptions(":1",0,0,1280,720,fps=0),RecordingOptions(":1",0,0,1280,720,output_width=1920)]:
            with self.assertRaises(ValueError): ffmpeg_arguments(options,Path("/tmp/a.mp4"))


if __name__=="__main__": unittest.main()
