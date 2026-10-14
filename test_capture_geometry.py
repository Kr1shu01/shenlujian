import unittest
from PyQt5.QtCore import QRect
from capture_geometry import CaptureGeometry,ScreenMapping
from video_sizes import export_size


class CaptureGeometryTests(unittest.TestCase):
    def test_two_times_display_scaling(self):
        model=CaptureGeometry(QRect(0,0,3840,2160),[ScreenMapping('4K',QRect(0,0,1920,1080),QRect(0,0,3840,2160))])
        self.assertEqual(model.to_native(QRect(50,80,300,200)),QRect(100,160,600,400))
        self.assertEqual(model.to_native(QRect(0,0,1920,1080)),model.root)
    def test_mixed_scaling_and_monitor_offsets(self):
        model=CaptureGeometry(QRect(0,0,4480,1440),[
            ScreenMapping('left',QRect(-1280,0,1280,720),QRect(0,0,2560,1440)),
            ScreenMapping('right',QRect(0,0,1920,1080),QRect(2560,0,1920,1080))])
        self.assertEqual(model.to_native(QRect(-100,40,200,120)),QRect(2360,40,300,280))
        self.assertEqual(model.to_native(QRect(100,50,400,300)),QRect(2660,50,400,300))
    def test_fractional_scaling_covers_selected_pixels_and_clamps(self):
        model=CaptureGeometry(QRect(0,0,2560,1440),[ScreenMapping('2K',QRect(0,0,2048,1152),QRect(0,0,2560,1440))])
        self.assertEqual(model.to_native(QRect(1,1,101,101)),QRect(1,1,127,127))
        self.assertEqual(model.to_native(QRect(-100,-100,3000,2000)),model.root)
    def test_quality_sizes_preserve_aspect_and_do_not_upscale(self):
        self.assertEqual([export_size(3840,2160,q) for q in (18,23,28)],[(3840,2160),(1920,1080),(1280,720)])
        self.assertEqual([export_size(1440,2560,q) for q in (18,23,28)],[(1440,2560),(1080,1920),(720,1280)])
        self.assertEqual(export_size(2300,1500,23),(1656,1080))
        self.assertEqual(export_size(641,481,28),(640,480))


if __name__=='__main__':unittest.main()
