#!/usr/bin/env python2
import numpy as np
import copy, operator, itertools
from collections import OrderedDict as odict
from hera_pspec import uvpspec, pspecdata, conversions, pspecbeam, utils
from pyuvdata import UVData


def build_vanilla_uvpspec(beam=None):
    """
    Build an example vanilla UVPSpec object from scratch, with all necessary metadata.

    Parameters
    ----------
    beam : PSpecBeamBase subclass
    covariance: if true, compute covariance

    Returns
    -------
    uvp : UVPSpec object
    """
    uvp = uvpspec.UVPSpec()

    Ntimes = 10
    Nfreqs = 50
    Ndlys = 30
    Nspws = 1
    Nspwfreqs = 1 * Nfreqs
    Nspwdlys = 1 * Ndlys

    # [((1, 2), (1, 2)), ((2, 3), (2, 3)), ((1, 3), (1, 3))]
    blpairs = [1002001002, 2003002003, 1003001003]
    bls = [1002, 2003, 1003]
    Nbls = len(bls)
    Nblpairs = len(blpairs)
    Nblpairts = Nblpairs * Ntimes

    blpair_array = np.tile(blpairs, Ntimes)
    bl_array = np.array(bls)
    bl_vecs = np.array([[  5.33391548e+00,  -1.35907816e+01,  -7.91624188e-09],
                        [ -8.67982998e+00,   4.43554478e+00,  -1.08695203e+01],
                        [ -3.34591450e+00,  -9.15523687e+00,  -1.08695203e+01]])
    time_array = np.repeat(np.linspace(2458042.1, 2458042.2, Ntimes), Nblpairs)
    time_1_array = time_array
    time_2_array = time_array
    lst_array = np.repeat(np.ones(Ntimes, dtype=np.float), Nblpairs)
    lst_1_array = lst_array
    lst_2_array = lst_array
    time_avg_array = time_array
    lst_avg_array = lst_array
    spw_freq_array = np.tile(np.arange(Nspws), Nfreqs)
    spw_dly_array = np.tile(np.arange(Nspws), Ndlys)
    spw_array = np.arange(Nspws)
    freq_array = np.repeat(np.linspace(100e6, 105e6, Nfreqs, endpoint=False), Nspws)
    dly_array = np.repeat(utils.get_delays(freq_array, n_dlys=Ndlys), Nspws)
    pol_array = np.array([-5])
    Npols = len(pol_array)
    vis_units = 'unknown'
    norm_units = 'Hz str'
    weighting = 'identity'
    channel_width = np.median(np.diff(freq_array))
    history = 'example'
    taper = "none"
    norm = "I"
    git_hash = "random"
    scalar_array = np.ones((Nspws, Npols), np.float)
    label1 = 'red'
    label2 = 'blue'
    labels = np.array([label1, label2])
    label_1_array = np.ones((Nspws, Nblpairts, Npols), np.int) * 0
    label_2_array = np.ones((Nspws, Nblpairts, Npols), np.int) * 1
    if beam is not None:
        OmegaP, OmegaPP = beam.get_Omegas(beam.primary_beam.polarization_array[0])
        beam_freqs = beam.beam_freqs

    # HERA coordinates in Karoo Desert, SA
    telescope_location = np.array([5109325.85521063,
                                   2005235.09142983,
                                  -3239928.42475397])

    store_cov=True
    cosmo = conversions.Cosmo_Conversions()

    data_array, wgt_array, integration_array, nsample_array, cov_array = {}, {}, {}, {}, {}
    for s in spw_array:
        data_array[s] = np.ones((Nblpairts, Ndlys, Npols), dtype=np.complex) \
                      * blpair_array[:, None, None] / 1e9
        wgt_array[s] = np.ones((Nblpairts, Ndlys, 2, Npols), dtype=np.float)
        integration_array[s] = np.ones((Nblpairts, Npols), dtype=np.float)
        nsample_array[s] = np.ones((Nblpairts, Npols), dtype=np.float)
        cov_array[s] =np.moveaxis(np.array([[np.identity(Ndlys,dtype=np.complex)\
         for m in range(Nblpairts)] for n in range(Npols)]),0,-1)


    params = ['Ntimes', 'Nfreqs', 'Nspws', 'Nspwdlys', 'Nspwfreqs', 'Nspws', 'Nblpairs', 'Nblpairts',
              'Npols', 'Ndlys', 'Nbls', 'blpair_array', 'time_1_array',
              'time_2_array', 'lst_1_array', 'lst_2_array', 'spw_array',
              'dly_array', 'freq_array', 'pol_array', 'data_array', 'wgt_array',
              'integration_array', 'bl_array', 'bl_vecs', 'telescope_location',
              'vis_units', 'channel_width', 'weighting', 'history', 'taper', 'norm',
              'git_hash', 'nsample_array', 'time_avg_array', 'lst_avg_array',
              'cosmo', 'scalar_array', 'labels', 'norm_units', 'labels', 'label_1_array',
              'label_2_array','store_cov','cov_array', 'spw_dly_array', 'spw_freq_array']

    if beam is not None:
        params += ['OmegaP', 'OmegaPP', 'beam_freqs']

    # Set all parameters
    for p in params:
        setattr(uvp, p, locals()[p])

    uvp.check()

    return uvp, cosmo


def uvpspec_from_data(data, bl_grps, data_std=None, spw_ranges=None, beam=None, taper='none', cosmo=None, verbose=False):
    """
    Build an example UVPSpec object from a visibility file and PSpecData.

    Parameters
    ----------
    data : UVData object or str
        This can be a UVData object or a string filepath to a miriad file.

    bl_grps : list
        This is a list of baseline groups (e.g. redundant groups) to form blpairs from.
        Ex: [[(24, 25), (37, 38), ...], [(24, 26), (37, 39), ...], ... ]

    data_std: UVData object or str or None
        Can be UVData object or a string filepath to a miriad file.

    spw_ranges : list
        List of spectral window tuples. See PSpecData.pspec docstring for details.

    beam : PSpecBeamBase subclass or str
        This can be a subclass of PSpecBeamBase of a string filepath to a
        UVBeam healpix map.

    taper : string
        Optional tapering applied to the data before OQE.

    cosmo : Cosmo_Conversions object

    verbose : bool
        if True, report feedback to standard output

    Returns
    -------
    uvp : UVPSpec object
    """
    # load data
    if isinstance(data, str):
        uvd = UVData()
        uvd.read_miriad(data)
    elif isinstance(data, UVData):
        uvd = data

    if isinstance(data_std, str):
        uvd_std = UVData()
        uvd_std.read_miriad(data_std)
    elif isinstance(data_std, UVData):
        uvd_std = data_std
    else:
        uvd_std = None
    if uvd_std is not None:
        store_cov = True
    else:
        store_cov = False

    # get pol
    pol = uvd.polarization_array[0]

    # load beam
    if isinstance(beam, str):
        beam = pspecbeam.PSpecBeamUV(beam, cosmo=cosmo)
    if beam is not None and cosmo is not None:
        beam.cosmo = cosmo

    # instantiate pspecdata
    ds = pspecdata.PSpecData(dsets=[uvd, uvd], dsets_std=[uvd_std, uvd_std], wgts=[None, None], labels=['d1', 'd2'], beam=beam)

    # get blpair groups
    assert isinstance(bl_grps, list), "bl_grps must be a list"
    if not isinstance(bl_grps[0], list): bl_grps = [bl_grps]
    assert np.all([isinstance(blgrp, list) for blgrp in bl_grps]), "bl_grps must be fed as a list of lists"
    assert np.all([isinstance(blgrp[0], tuple) for blgrp in bl_grps]), "bl_grps must be fed as a list of lists of tuples"
    bls1, bls2 = [], []
    for blgrp in bl_grps:
        _bls1, _bls2, _ = utils.construct_blpairs(blgrp, exclude_auto_bls=True, exclude_permutations=True)
        bls1.extend(_bls1)
        bls2.extend(_bls2)

    # run pspec
    uvp = ds.pspec(bls1, bls2, (0, 1), (pol, pol), input_data_weight='identity', spw_ranges=spw_ranges,
                   taper=taper, verbose=verbose,store_cov=store_cov)
    return uvp
