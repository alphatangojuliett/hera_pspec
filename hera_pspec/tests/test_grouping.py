import unittest
import nose.tools as nt
import numpy as np
import os
from hera_pspec.data import DATA_PATH
from test_uvpspec import build_example_uvpspec
from hera_pspec import uvpspec, conversions, parameter, pspecbeam, pspecdata
from hera_pspec import uvpspec_utils as uvputils
from hera_pspec import grouping

class Test_grouping(unittest.TestCase):

    def setUp(self):
        beamfile = os.path.join(DATA_PATH, 'NF_HERA_Beams.beamfits')
        self.beam = pspecbeam.PSpecBeamUV(beamfile)
        uvp, cosmo = build_example_uvpspec(beam=self.beam)
        uvp.check()
        self.uvp = uvp

    def tearDown(self):
        pass

    def runTest(self):
        pass
    
    def test_group_baselines(self):
        """
        Test baseline grouping behavior.
        """
        # Generate example lists of baselines
        bls1 = [(0,i) for i in range(1)]
        bls2 = [(0,i) for i in range(2)]
        bls3 = [(0,i) for i in range(4)]
        bls4 = [(0,i) for i in range(5)]
        bls5 = [(0,i) for i in range(13)]
        bls6 = [(0,i) for i in range(521)]
        
        # Check that error is raised when more groups requested than baselines
        nt.assert_raises(ValueError, grouping.group_baselines, bls1, 2)
        nt.assert_raises(ValueError, grouping.group_baselines, bls2, 5)
        nt.assert_raises(ValueError, grouping.group_baselines, bls4, 6)
        
        # Check that keep_remainder=False results in equal-sized blocks
        g1a = grouping.group_baselines(bls4, 2, keep_remainder=False, randomize=False)
        g1b = grouping.group_baselines(bls5, 5, keep_remainder=False, randomize=False)
        g1c = grouping.group_baselines(bls6, 10, keep_remainder=False, randomize=False)
        g2a = grouping.group_baselines(bls4, 2, keep_remainder=False, randomize=True)
        g2b = grouping.group_baselines(bls5, 5, keep_remainder=False, randomize=True)
        g2c = grouping.group_baselines(bls6, 10, keep_remainder=False, randomize=True)
        
        # Loop over groups and check that blocks are equal in size
        gs = [g1a, g1b, g1c, g2a, g2b, g2c]
        for g in gs:
            self.assert_(np.unique([len(grp) for grp in g]).size == 1)
        
        # Check that total no. baselines is preserved with keep_remainder=False
        for bls in [bls1, bls2, bls3, bls4, bls5, bls6]:
            for ngrp in [1, 2, 5, 10, 45]:
                for rand in [True, False]:
                    try:
                        g = grouping.group_baselines(bls, ngrp, 
                                                 keep_remainder=True, 
                                                 randomize=rand)
                    except:
                        continue
                    count = np.sum([len(_g) for _g in g])
                    self.assertEqual(count, len(bls))
        
        # Check that random seed works
        g1 = grouping.group_baselines(bls5, 3, randomize=True, seed=10)
        g2 = grouping.group_baselines(bls5, 3, randomize=True, seed=11)
        g3 = grouping.group_baselines(bls5, 3, randomize=True, seed=10)
        for i in range(len(g1)):
            for j in range(len(g1[i])):
                self.assertEqual(g1[i][j], g3[i][j])
    
    def test_sample_baselines(self):
        """
        Test baseline sampling (with replacement) behavior.
        """
        # Generate example lists of baselines
        bls1 = [(0,i) for i in range(1)]
        bls2 = [(0,i) for i in range(2)]
        bls3 = [(0,i) for i in range(4)]
        bls4 = [(0,i) for i in range(5)]
        bls5 = [(0,i) for i in range(13)]
        bls6 = [(0,i) for i in range(521)]
        
        # Example grouped list
        g1 = grouping.group_baselines(bls5, 3, randomize=False)
        
        # Check that returned length is the same as input length
        for bls in [bls1, bls2, bls3, bls4, bls5, bls6]:
            samp = grouping.sample_baselines(bls)
            self.assertEqual(len(bls), len(samp))
        
        # Check that returned length is the same for groups too
        samp = grouping.sample_baselines(g1)
        self.assertEqual(len(g1), len(samp))
    
    def test_select_common(self):
        """
        Test selecting power spectra that two UVPSpec objects have in common.
        """
        # Carve up some example UVPSpec objects
        uvp1 = self.uvp.select(times=np.unique(self.uvp.time_avg_array)[:-1], 
                               inplace=False)
        uvp2 = self.uvp.select(times=np.unique(self.uvp.time_avg_array)[1:], 
                               inplace=False)
        uvp3 = self.uvp.select(blpairs=np.unique(self.uvp.blpair_array)[1:], 
                               inplace=False)
        
        # Check that selecting on common times works
        uvp_list = [uvp1, uvp2]
        uvp_new = grouping.select_common(uvp_list, spws=True, blpairs=True, 
                                         times=True, pols=True, inplace=False)
        self.assertEqual(uvp_new[0], uvp_new[1])
        np.testing.assert_array_equal(uvp_new[0].time_avg_array, 
                                      uvp_new[1].time_avg_array)
        
        # Check that matching times are ignored when set to False
        uvp_new = grouping.select_common(uvp_list, spws=True, blpairs=True, 
                                         times=False, pols=True, inplace=False)
        self.assertNotEqual( np.sum(uvp_new[0].time_avg_array 
                                  - uvp_new[1].time_avg_array), 0.)
        self.assertEqual(len(uvp_new), len(uvp_list))
        
        # Check that in-place selection works
        grouping.select_common(uvp_list, spws=True, blpairs=True, 
                               times=True, pols=True, inplace=True)
        self.assertEqual(uvp1, uvp2)
        
if __name__ == "__main__":
    unittest.main()
