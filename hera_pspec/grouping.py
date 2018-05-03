import numpy as np
from collections import OrderedDict as odict
from hera_pspec import uvpspec_utils as uvputils
import random
import copy


def group_baselines(bls, Ngroups, keep_remainder=False, randomize=False, 
                    seed=None):
    """
    Group baselines together into equal-sized sets.
    
    These groups can be passed into PSpecData.pspec(), where the corresponding 
    baselines will be averaged together (grouping reduces the number of 
    cross-spectra that need to be computed).
    
    Parameters
    ----------
    bls : list of tuples
        Set of unique baselines tuples.
    
    Ngroups : int
        Number of groups to create. The groups will be equal in size, except 
        the last group (if there are remainder baselines).
    
    keep_remainder : bool, optional
        Whether to keep remainder baselines that don't fit exactly into the 
        number of specified groups. If True, the remainder baselines are 
        appended to the last group in the output list. Otherwise, the remainder 
        baselines are discarded. Default: False.
    
    randomize : bool, optional
        Whether baselines should be added to groups in the order they appear in 
        'bls', or if they should be assigned at random. Default: False.
    
    seed : int, optional
        Random seed to use if randomize=True. If None, no random seed will be 
        set. Default: None.
    
    Returns
    -------
    grouped_bls : list of lists of tuples
        List of grouped baselines.
    """
    Nbls = len(bls) # Total baselines
    n = Nbls / Ngroups # Baselines per group
    rem = Nbls - n*Ngroups
    
    # Sanity check on number of groups
    if Nbls < Ngroups: raise ValueError("Can't have more groups than baselines.")
    
    # Make sure only tuples were provided (can't have groups of groups)
    for bl in bls: assert isinstance(bl, tuple)
    
    # Randomize baseline order if requested
    if randomize:
        if seed is not None: random.seed(seed)
        bls = copy.deepcopy(bls)
        random.shuffle(bls)
    
    # Assign to groups sequentially
    grouped_bls = [bls[i*n:(i+1)*n] for i in range(Ngroups)]
    if keep_remainder and rem > 0: grouped_bls[-1] += bls[-rem:]
    return grouped_bls


def sample_baselines(bls, seed=None):
    """
    Sample a set of baselines with replacement (to be used to generate a 
    bootstrap sample).
    
    Parameters
    ----------
    bls : list of either tuples or lists of tuples
        Set of unique baselines to be sampled from. If groups of baselines 
        (contained in lists) are provided, each group will be treated as a 
        single object by the sampler; its members will not be sampled 
        separately.
    
    seed : int, optional
        Random seed to use if randomize=True. If None, no random seed will be 
        set. Default: None.
    
    Returns
    -------
    sampled_bls : list of tuples or lists of tuples
        Bootstrap-sampled set of baselines (will include multiple instances of 
        some baselines).
    """
    if seed is not None: random.seed(seed)
    
    # Sample with replacement; return as many baselines/groups as were input
    return [random.choice(bls) for i in range(len(bls))]


def select_common(uvp_list, spws=True, blpairs=True, times=True, pols=True, 
                  inplace=False):
    """
    Find spectral windows, baseline-pairs, times, and/or polarizations that a 
    set of UVPSpec objects have in common and return new UVPSpec objects that 
    contain only those data.
    
    If there is no overlap, an error will be raised.
    
    Parameters
    ----------
    uvp_list : list of UVPSpec
        List of input UVPSpec objects.
    
    spws : bool, optional
        Whether to retain only the spectral windows that all UVPSpec objects 
        have in common. For a spectral window to be retained, the entire set of 
        delays in that window must match across all UVPSpec objects (this will 
        not allow you to just pull out common delays).
        
        If set to False, the original spectral windows will remain in each 
        UVPSpec. Default: True.
    
    blpairs : bool, optional
        Whether to retain only the baseline-pairs that all UVPSpec objects have 
        in common. Default: True.
    
    times : bool, optional
        Whether to retain only the (average) times that all UVPSpec objects 
        have in common. This does not check to make sure that time_1 and time_2 
        (i.e. the LSTs for the left-hand and right-hand visibilities that went 
        into the power spectrum calculation) are the same. See the 
        UVPSpec.time_avg_array attribute for more details. Default: True.
    
    pols : bool, optional
        Whether to retain only the polarizations that all UVPSpec objects have 
        in common. Default: True.
    
    inplace : bool, optional
        Whether the selection should be applied to the UVPSpec objects 
        in-place, or new copies of the objects should be returned.
    
    Returns
    -------
    uvp_list : list of UVPSpec, optional
        List of UVPSpec objects with the overlap selection applied. This will 
        only be returned if inplace = False.
    """
    if len(uvp_list) < 2:
        raise IndexError("uvp_list must contain two or more UVPSpec objects.")
    
    # Get times that are common to all UVPSpec objects in the list
    if times:
        common_times = np.unique(uvp_list[0].time_avg_array)
        has_times = [np.isin(common_times, uvp.time_avg_array) 
                     for uvp in uvp_list]
        common_times = common_times[np.all(has_times, axis=0)]
        print "common_times:", common_times
    
    # Get baseline-pairs that are common to all
    if blpairs:
        common_blpairs = np.unique(uvp_list[0].blpair_array)
        has_blpairs = [np.isin(common_blpairs, uvp.blpair_array) 
                       for uvp in uvp_list]
        common_blpairs = common_blpairs[np.all(has_blpairs, axis=0)]
        print "common_blpairs:", common_blpairs
    
    # Get polarizations that are common to all
    if pols:
        common_pols = np.unique(uvp_list[0].pol_array)
        has_pols = [np.isin(common_pols, uvp.pol_array) for uvp in uvp_list]
        common_pols = common_pols[np.all(has_pols, axis=0)]
        print "common_pols:", common_pols
    
    # Get common spectral windows (the entire window must match)
    # Each row of common_spws is a list of that spw's index in each UVPSpec
    if spws:
        common_spws = []
        for spw in range(uvp_list[0].Nspws):
            dlys0 = uvp_list[0].get_dlys((spw,))
            
            # Check if this window exists in all UVPSpec objects
            found_spws = [spw, ]
            missing = False
            for uvp in uvp_list:
                # Check if any spws in this UVPSpec match the current spw
                matches_spw = np.array([ np.array_equal(dlys0, uvp.get_dlys((i,))) 
                                         for i in range(uvp.Nspws) ])
                if not np.any(matches_spw):
                    missing = True
                    break
                else:
                    # Store which spw of this UVPSpec it was found in
                    found_spws.append( np.where(matches_spw)[0] )
            
            # Only add this spw to the list if it was found in all UVPSpecs
            if missing: continue
            common_spws.append(found_spws)
        common_spws = np.array(common_spws).T # Transpose
        print "common_spws:", common_spws
        
    # Check that this won't be an empty selection
    if spws and len(common_spws) == 0:
        raise ValueError("No spectral windows were found that exist in all "
                         "spectra (the entire spectral window must match).")
    
    if blpairs and len(common_blpairs) == 0:
        raise ValueError("No baseline-pairs were found that exist in all spectra.")
    
    if times and len(common_times) == 0:
        raise ValueError("No times were found that exist in all spectra.")
    
    if pols and len(common_pols) == 0:
        raise ValueError("No polarizations were found that exist in all spectra.")
    
    # Apply selections
    out_list = []
    for i, uvp in enumerate(uvp_list):
        _spws, _blpairs, _times, _pols = None, None, None, None
        
        # Set indices of blpairs, times, and pols to keep
        if blpairs: _blpairs = common_blpairs
        if times: _times = common_times
        if pols: _pols = common_pols
        if spws: _spws = common_spws[i]
        
        _uvp = uvp.select(spws=_spws, blpairs=_blpairs, times=_times, 
                          pols=_pols, inplace=inplace)
        if not inplace: out_list.append(_uvp)
    
    # Return if not inplace
    if not inplace: return out_list


def average_spectra(uvp_in, blpair_groups=None, time_avg=False, inplace=True):
    """
    Average power spectra across the baseline-pair-time axis, weighted by 
    each spectrum's integration time.
    
    This is an "incoherent" average, in the sense that this averages power 
    spectra, rather than visibility data. The 'nsample_array' and 
    'integration_array' will be updated to reflect the averaging.

    In the case of averaging across baseline pairs, the resultant averaged 
    spectrum is assigned to the zeroth blpair in the group. In the case of 
    time averaging, the time and LST arrays are assigned to the mean of the 
    averaging window.

    Note that this is designed to be separate from spherical binning in k: 
    here we are not connecting k_perp modes to k_para modes. However, if 
    blpairs holds groups of iso baseline separation, then this is 
    equivalent to cylindrical binning in 3D k-space.

    If you want help constructing baseline-pair groups from baseline 
    groups, see self.get_blpair_groups_from_bl_groups.

    Parameters
    ----------
    blpair_groups : list of baseline-pair groups
        List of list of tuples or integers. All power spectra in a 
        baseline-pair group are averaged together. If a baseline-pair 
        exists in more than one group, a warning is raised.
        
        Ex: blpair_groups = [ [((1, 2), (1, 2)), ((2, 3), (2, 3))], [((4, 6), (4, 6))]] or
        blpair_groups = [ [1002001002, 2003002003], [4006004006] ]

    time_avg : bool, optional
        If True, average power spectra across the time axis. Default: False.

    inplace : bool, optional
        If True, edit data in self, else make a copy and return. Default: 
        True.

    Notes
    -----
    Currently, every baseline-pair in a blpair group must have the same 
    Ntimes, unless time_avg=True. Future versions may support 
    baseline-pair averaging of heterogeneous time arrays. This includes 
    the scenario of repeated blpairs (e.g. in bootstrapping), which will 
    return multiple copies of their time_array.
    """
    if inplace:
        uvp = uvp_in
    else:
        uvp = copy.deepcopy(uvp_in)

    # If blpair_groups were fed in, enforce type and structure
    if blpair_groups is not None:
        
        # Enforce shape of blpair_groups
        assert isinstance(blpair_groups[0], list), \
              "blpair_groups must be fed as a list of baseline-pair lists. " \
              "See docstring."

        # Convert blpair_groups to list of blpair group integers
        if isinstance(blpair_groups[0][0], tuple):
            new_blpair_grps = [map(lambda blp: uvp.antnums_to_blpair(blp), blpg) 
                               for blpg in blpair_groups]
            blpair_groups = new_blpair_groups
    else:
        # If not, each baseline pair is its own group
        blpair_groups = map(lambda blp: [blp], np.unique(uvp.blpair_array))

    # Print warning if a blpair appears more than once in all of blpair_groups
    all_blpairs = [item for sublist in blpair_groups for item in sublist]
    if len(set(all_blpairs)) < len(all_blpairs): 
        print "Warning: some baseline-pairs are repeated between blpair "\
              "averaging groups..."

    # For baseline pairs not in blpair_groups, add them as their own group
    extra_blpairs = set(uvp.blpair_array) - set(all_blpairs)
    blpair_groups += map(lambda blp: [blp], extra_blpairs)

    # Create new data arrays
    data_array, wgts_array = odict(), odict()
    ints_array, nsmp_array = odict(), odict()

    # Iterate over spectral windows
    for spw in range(uvp.Nspws):
        spw_data, spw_wgts, spw_ints, spw_nsmp = [], [], [], []

        # Iterate over polarizations
        for i, p in enumerate(uvp.pol_array):
            pol_data, pol_wgts, pol_ints, pol_nsmp = [], [], [], []

            # Iterate over baseline-pair groups
            for j, blpg in enumerate(blpair_groups):
                bpg_data, bpg_wgts, bpg_ints, bpg_nsmp = [], [], [], []
                w_list = []

                # Iterate within a baseline-pair group and get integration-
                # weighted data
                for k, blp in enumerate(blpg):
                    
                    # Get no. samples and construct integration weight
                    nsmp = uvp.get_nsamples(spw, blp, p)[:, None]
                    data = uvp.get_data(spw, blp, p)
                    wgts = uvp.get_wgts(spw, blp, p)
                    ints = uvp.get_integrations(spw, blp, p)[:, None]
                    w = (ints * np.sqrt(nsmp))
                    
                    # Take time average if desired
                    if time_avg:
                      data = (np.sum(data * w, axis=0) \
                           / np.sum(w, axis=0).clip(1e-10, np.inf))[None]
                      wgts = (np.sum(wgts * w[:, None], axis=0) \
                           / np.sum(w, axis=0).clip(1e-10, np.inf)[:, None])[None] 
                      ints = (np.sum(ints * w, axis=0) \
                           / np.sum(w, axis=0).clip(1e-10, np.inf))[None]
                      nsmp = np.sum(nsmp, axis=0)[None]
                      w = np.sum(w, axis=0)[None]
                    
                    # Apply integration weight to data
                    bpg_data.append(data * w)
                    bpg_wgts.append(wgts * w[:, None])
                    bpg_ints.append(ints * w)
                    bpg_nsmp.append(nsmp)
                    w_list.append(w)

                # Take integration-weighted averages, with clipping to deal 
                # with zeros
                bpg_data = np.sum(bpg_data, axis=0) \
                         / np.sum(w_list, axis=0).clip(1e-10, np.inf)
                bpg_wgts = np.sum(bpg_wgts, axis=0) \
                         / np.sum(w_list, axis=0).clip(1e-10, np.inf)[:, None]
                bpg_nsmp = np.sum(bpg_nsmp, axis=0)
                bpg_ints = np.sum(bpg_ints, axis=0) \
                         / np.sum(w_list, axis=0).clip(1e-10, np.inf)
                w_list = np.sum(w_list, axis=0)

                # Append to lists (polarization)
                pol_data.extend(bpg_data); pol_wgts.extend(bpg_wgts)
                pol_ints.extend(bpg_ints); pol_nsmp.extend(bpg_nsmp)

            # Append to lists (spectral window)
            spw_data.append(pol_data); spw_wgts.append(pol_wgts)
            spw_ints.append(pol_ints); spw_nsmp.append(pol_nsmp)

        # Append to dictionaries
        data_array[spw] = np.moveaxis(spw_data, 0, -1)
        wgts_array[spw] = np.moveaxis(spw_wgts, 0, -1)
        ints_array[spw] = np.moveaxis(spw_ints, 0, -1)[:, 0, :]
        nsmp_array[spw] = np.moveaxis(spw_nsmp, 0, -1)[:, 0, :]

    # Iterate over blpair groups one more time to assign metadata
    time_1, time_2, time_avg_arr  = [], [], []
    lst_1, lst_2, lst_avg_arr = [], [], []
    blpair_arr, bl_arr = [], []
    
    for i, blpg in enumerate(blpair_groups):
        
        # Get blpairts indices for zeroth blpair in this group
        blpairts = uvp.blpair_to_indices(blpg[0])
        
        # Assign meta-data
        bl_arr.extend(list(uvputils._blpair_to_bls(blpg[0])))
        if time_avg:
            blpair_arr.append(blpg[0])
            time_1.extend([np.mean(uvp.time_1_array[blpairts])])
            time_2.extend([np.mean(uvp.time_2_array[blpairts])])
            time_avg_arr.extend([np.mean(uvp.time_avg_array[blpairts])])
            lst_1.extend([np.mean(np.unwrap(uvp.lst_1_array[blpairts]))%(2*np.pi)])
            lst_2.extend([np.mean(np.unwrap(uvp.lst_2_array[blpairts]))%(2*np.pi)])
            lst_avg_arr.extend([np.mean(np.unwrap(uvp.lst_avg_array[blpairts]))%(2*np.pi)])
        else:
            blpair_arr.extend(np.ones_like(blpairts, np.int) * blpg[0])
            time_1.extend(uvp.time_1_array[blpairts])
            time_2.extend(uvp.time_2_array[blpairts])
            time_avg_arr.extend(uvp.time_avg_array[blpairts])
            lst_1.extend(uvp.lst_1_array[blpairts])
            lst_2.extend(uvp.lst_2_array[blpairts])
            lst_avg_arr.extend(uvp.lst_avg_array[blpairts])

    # Update arrays
    bl_arr = np.array(sorted(set(bl_arr)))
    bl_vecs = np.array(map(lambda bl: uvp.bl_vecs[uvp.bl_array.tolist().index(bl)], bl_arr))

    # Assign arrays and metadata to UVPSpec object
    uvp.Ntimes = len(np.unique(time_avg_arr))
    uvp.Nblpairts = len(time_avg_arr)
    uvp.Nblpairs = len(np.unique(blpair_arr))
    uvp.Nbls = len(bl_arr)
    
    # Baselines
    uvp.bl_array = bl_arr
    uvp.bl_vecs = bl_vecs
    uvp.blpair_array = np.array(blpair_arr)
    
    # Times
    uvp.time_1_array = np.array(time_1)
    uvp.time_2_array = np.array(time_2)
    uvp.time_avg_array = np.array(time_avg_arr)
    
    # LSTs
    uvp.lst_1_array = np.array(lst_1)
    uvp.lst_2_array = np.array(lst_2)
    uvp.lst_avg_array = np.array(lst_avg_arr)
    
    # Data, weights, and no. samples
    uvp.data_array = data_array
    uvp.integration_array = ints_array
    uvp.wgt_array = wgts_array
    uvp.nsample_array = nsmp_array
    if hasattr(uvp_in, 'label1'): uvp.label1 = uvp_in.label1
    if hasattr(uvp_in, 'label2'): uvp.label2 = uvp_in.label2

    # Validity check
    uvp.check()
    
    # Return
    if inplace == False:
        return uvp
    

def fold_spectra(uvp):
    """
    Average bandpowers from matching positive and negative delay bins onto a 
    purely positive delay axis. Negative delay bins are still populated, but 
    are filled with zero power. This is an in-place operation.
    
    Will only work if uvp.folded == False, i.e. data is currently unfolded 
    across negative and positive delay. Because this averages the data, the 
    nsample array is multiplied by a factor of 2. 
    
    WARNING: This operation cannot be undone.
    
    Parameters
    ----------
    uvp : UVPSpec
        UVPSpec object to be folded.
    """
    # assert folded is False
    assert uvp.folded == False, "cannot fold power spectra if uvp.folded == True"

    # Iterate over spw
    for spw in range(uvp.Nspws):

        # get number of dly bins
        Ndlys = len(uvp.get_dlys(spw))

        if Ndlys % 2 == 0:
            # even number of dlys
            left = uvp.data_array[spw][:, 1:Ndlys//2, :][:, ::-1, :]
            right = uvp.data_array[spw][:, Ndlys//2+1:, :]
            uvp.data_array[spw][:, Ndlys//2+1:, :] = np.mean([left, right], axis=0)
            uvp.data_array[spw][:, :Ndlys//2, :] = 0.0
            uvp.nsample_array[spw] *= 2.0

        else:
            # odd number of dlys
            left = uvp.data_array[spw][:, :Ndlys//2, :][:, ::-1, :]
            right = uvp.data_array[spw][:, Ndlys//2+1:, :]   
            uvp.data_array[spw][:, Ndlys//2+1:, :] = np.mean([left, right], axis=0)
            uvp.data_array[spw][:, :Ndlys//2, :] = 0.0
            uvp.nsample_array[spw] *= 2.0

    uvp.folded = True


