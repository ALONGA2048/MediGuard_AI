import unittest
from multiprocessing import shared_memory

import numpy as np

from realtime_inference import SharedFrameBundle, array_hash, attach_frame


class SharedMemoryImageTests(unittest.TestCase):
    def test_full_hd_bgr_pixels_round_trip_losslessly_and_cleanup(self):
        rng = np.random.default_rng(42)
        cam0 = rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
        cam1 = rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
        originals = [cam0.copy(), cam1.copy()]
        names = []
        with SharedFrameBundle("request-a", {0: cam0, 1: cam1}) as bundle:
            names = [item["shm_name"] for item in bundle.descriptors]
            for expected, descriptor in zip(originals, bundle.descriptors):
                received, block = attach_frame(descriptor)
                try:
                    self.assertEqual(received.shape, (1080, 1920, 3))
                    self.assertEqual(received.dtype, np.uint8)
                    self.assertFalse(received.flags.writeable)
                    self.assertEqual(descriptor["color_format"], "BGR")
                    self.assertEqual(array_hash(received), array_hash(expected))
                    self.assertTrue(np.array_equal(received, expected))
                finally:
                    block.close()
        self.assertTrue(np.array_equal(cam0, originals[0]))
        self.assertTrue(np.array_equal(cam1, originals[1]))
        for name in names:
            with self.assertRaises(FileNotFoundError):
                shared_memory.SharedMemory(name=name, create=False)


if __name__ == "__main__":
    unittest.main()
