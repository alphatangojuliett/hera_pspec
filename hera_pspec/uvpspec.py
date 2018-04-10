import numpy as np
from collections import OrderedDict as odict
from hera_pspec import conversions
from hera_pspec.parameter import PSpecParam
import os
from pyuvdata import uvutils as uvutils
import h5py
import shutil
import copy
import operator
import ast


class UVPSpec(object):
    """
    Object for storing power spectra generated by hera_pspec.
    """
    def __init__(self):
        """
        A container object for storing power spectra generated by hera_pspec.
        """
        # Summary attributes
        self._Ntimes = PSpecParam("Ntimes", description="Number of unique times.", expected_type=int)
        self._Nblpairts = PSpecParam("Nblpairts", description="Total number of baseline-pair times.", expected_type=int)
        self._Nblpairs = PSpecParam("Nblpairs", description='Total number of baseline-pairs.', expected_type=int)
        self._Nspwdlys = PSpecParam("Nspwdlys", description="Total number of delay bins across all sub-bands.", expected_type=int)
        self._Nspws = PSpecParam("Nspws", description="Number of spectral windows.", expected_type=int)
        self._Ndlys = PSpecParam("Ndlys", description="Total number of delay bins.", expected_type=int)
        self._Nfreqs = PSpecParam("Nfreqs", description="Total number of frequency bins in the original data.", expected_type=int)
        self._Npols = PSpecParam("Npols", description="Number of polarizations in the data.", expected_type=int)
        self._history = PSpecParam("history", description='The file history.', expected_type=str)

        # Data attributes
        desc = "Power spectrum data dictionary with spw integer as keys and values as complex ndarrays."
        self._data_array = PSpecParam("data_array", description=desc, expected_type=dict, form="(Nblpairts, Ndlys, Npols)")
        desc = "Weight dictionary for original two datasets. The second axis holds [dset1_wgts, dset2_wgts] in that order."
        self._wgt_array = PSpecParam("wgt_array", description=desc, expected_type=dict, form="(Nblpairts, Nfreqs, 2, Npols)")
        desc = "Integration dictionary containing total amount of integration time (seconds) in each power spectrum " \
                "with same form as data_array except without the dlys axis."
        self._integration_array = PSpecParam("integration_array", description=desc, expected_type=dict, form="(Nblpairts, Npols)")
        self._spw_array = PSpecParam("spw_array", description="Spw integer array.", form="(Nspwdlys,)")
        self._freq_array = PSpecParam("freq_array", description="Frequency array of the original data in Hz.", form="(Nspwdlys,)")
        self._dly_array = PSpecParam("dly_array", description="Delay array in seconds.", form="(Nspwdlys,)")
        self._pol_array = PSpecParam("pol_array", description="Polarizations in data.", form="(Npols,)")
        self._lst_1_array = PSpecParam("lst_1_array", description="LST array of the first bl in the bl-pair [radians].", form="(Nblpairts,)")
        self._lst_2_array = PSpecParam("lst_2_array", description="LST array of the second bl in the bl-pair [radians].", form="(Nblpairts,)")
        self._time_1_array = PSpecParam("time_1_array", description="Time array of the first bl in the bl-pair [Julian Date].", form="(Nblpairts,)")
        self._time_1_array = PSpecParam("time_2_array", description="Time array of the second bl in the bl-pair [Julian Date].", form="(Nblpairts,)")
        self._blpair_array = PSpecParam("blpair_array", description="Baseline-pair integer for all baseline-pair times.", form="(Nblpairts,)")

        # Baseline attributes
        self._Nbls = PSpecParam("Nbls", description="Number of unique baseline integers.", expected_type=int)
        self._bl_vecs = PSpecParam("bl_vecs", description="ndarray of baseline separation vectors in the ITRF frame [meters]. To get it in ENU frame see self.get_ENU_bl_vecs().", expected_type=np.ndarray, form="(Nbls,)")
        self._bl_array = PSpecParam("bl_array", description="All unique baseline (antenna-pair) integers.", expected_type=np.ndarray, form="(Nbls,)")

        # Misc Attributes
        self._channel_width = PSpecParam("channel_width", description="width of visibility frequency channels in Hz.", expected_type=float)
        self._telescope_location = PSpecParam("telescope_location", description="telescope location in ECEF frame [meters]. To get it in Lat/Lon/Alt see pyuvdata.utils.LatLonAlt_from_XYZ().", expected_type=np.ndarray)
        self._weighting = PSpecParam("weighting", description="form of data weighting used when forming power spectra.", expected_type=str)
        self._norm = PSpecParam("norm", description="normalization method", expected_type=str)
        self._taper = PSpecParam("taper", description='taper function applied to data before FFT"', expected_type=str)
        self._units = PSpecParam("units", description="units of the power spectra.", expected_type=str)
        self._scalar_array = PSpecParam("scalar_array", description="power spectrum scalar from pspecbeam module.", expected_type=np.ndarray, form="(Nspws, Npols)")
        self._filename1 = PSpecParam("filename1", description="filename of data from first dataset", expected_type=str)
        self._filename2 = PSpecParam("filename1", description="filename of data from second dataset", expected_type=str)
        self._tag1 = PSpecParam("tag1", description="tag of data from first dataset", expected_type=str)
        self._tag2 = PSpecParam("tag2", description="tag of data from second dataset", expected_type=str)
        self._git_hash = PSpecParam("git_hash", description="GIT hash of hera_pspec when pspec was generated.", expected_type=str)
        self._cosmo_params = PSpecParam("cosmo_params", description="LCDM cosmological parameter string, used to instantiate a conversions.Cosmo_Conversions object.", expected_type=str)

        # collect required parameters
        self._req_params = ["Ntimes", "Nblpairts", "Nblpairs", "Nspwdlys", "Nspws", "Ndlys", "Npols", "Nfreqs", "history",
                            "data_array", "wgt_array", "integration_array", "spw_array", "freq_array", "dly_array",
                            "pol_array", "lst_1_array", "lst_2_array", "time_1_array", "time_2_array", "blpair_array",
                            "Nbls", "bl_vecs", "bl_array", "channel_width", "telescope_location", "weighting", "units",
                            "taper", "norm", "git_hash"]
        self._all_params = copy.copy(self._req_params) + \
                            ["filename1", "filename2", "tag1", "tag2", "scalar_array"]
        self._immutable_params = ["Ntimes", "Nblpairts", "Nblpairs", "Nspwdlys", "Nspws", "Ndlys", "Npols", "Nfreqs", "history",
                                 "Nbls", "channel_width", "weighting", "units", "filename1", "filename2", "tag1", "tag2",
                                 "norm", "taper", "git_hash", "cosmo_params"]
        self._ndarrays = ["spw_array", "freq_array", "dly_array", "pol_array", "lst_1_array", 
                          "lst_2_array", "time_1_array", "time_2_array", "blpair_array",
                          "bl_vecs", "bl_array", "telescope_location", "scalar_array"]
        self._dicts = ["data_array", "wgt_array", "integration_array"]
        self._meta_dsets = ["lst_1_array", "lst_2_array", "time_1_array", "time_2_array", "blpair_array", 
                            "bl_vecs", "bl_array"]
        self._meta_attrs = sorted(set(self._all_params) - set(self._dicts) - set(self._meta_dsets))
        self._meta = sorted(set(self._meta_dsets).union(set(self._meta_attrs)))

    def get_data(self, key, *args):
        """
        Slice into data_array with a specified data key in the format

        (spw, ((ant1, ant2), (ant3, ant4)), pol)

        or

        (spw, blpair-integer, pol)

        where spw is the spectral window integer, ant1 etc. are integers, 
        and pol is either a polarization string (ex. 'XX') or integer (ex. -5).

        Parameters
        ----------
        key : tuple, baseline-pair key

        Return
        ------
        data : complex ndarray with shape (Ntimes, Ndlys)
        """
        spw, blpairts, pol = self.key_to_indices(key, *args)

        return self.data_array[spw][blpairts, :, pol]

    def get_wgts(self, key, *args):
        """
        Slice into wgt_array with a specified data key in the format

        (spw, ((ant1, ant2), (ant3, ant4)), pol)

        or

        (spw, blpair-integer, pol)

        where spw is the spectral window integer, ant1 etc. are integers, 
        and pol is either a polarization string (ex. 'XX') or integer (ex. -5).

        Parameters
        ----------
        key : tuple, baseline-pair key

        Return
        ------
        wgts : float ndarray with shape (2, Ntimes, Ndlys), where the zeroth axis holds
            [wgt_1, wgt_2] in that order
        """
        spw, blpairts, pol = self.key_to_indices(key, *args)

        return self.wgt_array[spw][blpairts, :, :, pol]

    def get_integrations(self, key, *args):
        """
        Slice into integration_array with a specified data key in the format

        (spw, ((ant1, ant2), (ant3, ant4)), pol)

        or

        (spw, blpair-integer, pol)

        where spw is the spectral window integer, ant1 etc. are integers, 
        and pol is either a polarization string (ex. 'XX') or integer (ex. -5).

        Parameters
        ----------
        key : tuple, baseline-pair key

        Return
        ------
        data : float ndarray with shape (Ntimes,)
        """
        spw, blpairts, pol = self.key_to_indices(key, *args)

        return self.integration_array[spw][blpairts, pol]

    def get_dlys(self, key):
        """
        Get array of delays given a spectral window selection.

        Parameters
        ----------
        key : int, or tuple with integer
            Spectral window selection

        Returns
        -------
        dlys : float ndarray, contains delays in nanosec of pspectra given spw
        """
        indices = self.spw_to_indices(key)
        return self.dly_array[indices]

    def get_blpair_seps(self):
        """
        For each baseline-pair, get the average baseline separation in ENU frame in meters.

        Returns blp_avg_sep
        -------
        blp_avg_sep : float ndarray, shape=(Nblpairts,)
        """
        # get list of bl separations
        bl_vecs = self.get_ENU_bl_vecs()
        bls = self.bl_array.tolist()
        blseps = np.array(map(lambda bl: np.linalg.norm(bl_vecs[bls.index(bl)]), self.bl_array))

        # iterate over blpair_array
        blp_avg_sep = []
        for blp in self.blpair_array:
            an = self.blpair_to_antnums(blp)
            bl1 = self.antnums_to_bl(an[0])
            bl2 = self.antnums_to_bl(an[1])
            blp_avg_sep.append(np.mean([blseps[bls.index(bl1)], blseps[bls.index(bl2)]]))

        return np.array(blp_avg_sep)

    def get_kvecs(self, spw, little_h=True):
        """
        Get cosmological wavevectors for power spectra given an adopted cosmology.

        Parameters
        ----------
        spw : int, choice of spectral window

        little_h : boolean, optional
                Whether to have cosmological length units be h^-1 Mpc or Mpc
                Default: h^-1 Mpc

        Returns (k_perp, k_para)
        -------
        k_perp : float ndarray, containing perpendicular cosmological wave-vectors, shape=(Nblpairs,)
        k_para : float ndarray, containing parallel cosmological wave-vectors, shape=(Ndlys given spw)

        """
        # assert cosmo
        assert hasattr(self, 'cosmo'), "self.cosmo must exist to form cosmological wave-vectors. See self.add_cosmology()"

        # calculate mean redshift of band
        avg_z = self.cosmo.f2z(np.mean(self.freq_array[self.spw_to_indices(spw)]))

        # get kperps
        blpair_seps = self.get_blpair_seps()
        k_perp = blpair_seps * self.cosmo.bl_to_kperp(avg_z, little_h=little_h)

        # get kparas
        k_para = self.get_dlys(spw) * self.cosmo.tau_to_kpara(avg_z, little_h=little_h)

        return k_perp, k_para

    def convert_to_deltasq(self, little_h=True):
        """
        Convert from P(k) to Delta^2(k) by multiplying by k^3 / (2pi^2).

        The units of the output is therefore the current units (self.units) times h^3 Mpc^-3,
        where the h^3 is only included if little_h == True.

        Parameters
        ----------
        little_h : boolean, optional
                Whether to have cosmological length units be h^-1 Mpc or Mpc
                Default: h^-1 Mpc
        """
        # loop over spectral windows
        for spw in range(self.Nspws):
            # get k vectors
            k_perp, k_para = self.get_kvecs(spw, little_h=little_h)
            k_mag = np.sqrt(k_perp[:, None, None]**2 + k_para[None, :, None]**2)

            # multiply into data
            self.data_array[spw] *= k_mag**3 / (2*np.pi**2)

        # edit units
        if little_h:
            self.units += " h^3 k^3 / (2pi^2)"
        else:
            self.units += " k^3 / (2pi^2)"

    def blpair_to_antnums(self, blpair):
        """
        Convert baseline-pair integer to nested tuple of antenna numbers.

        Parameters
        ----------
        blpair : i12 int
            baseline-pair integer ID

        Return
        ------
        antnums : tuple
            nested tuple containing baseline-pair antenna numbers. Ex. ((ant1, ant2), (ant3, ant4))
        """
        return _blpair_to_antnums(blpair)

    def antnums_to_blpair(self, antnums):
        """
        Convert nested tuple of antenna numbers to baseline-pair integer.

        Parameters
        ----------
        antnums : tuple
            nested tuple containing integer antenna numbers for a baseline-pair.
            Ex. ((ant1, ant2), (ant3, ant4))

        Return
        ------
        blpair : i12 integer
            baseline-pair integer
        """
        return _antnums_to_blpair(antnums)

    def bl_to_antnums(self, bl):
        """
        Convert baseline (anntenna-pair) integer to nested tuple of antenna numbers.

        Parameters
        ----------
        bl : i6 int
            baseline integer ID

        Return
        ------
        antnums : tuple
            tuple containing baseline antenna numbers. Ex. (ant1, ant2)
        """
        return _bl_to_antnums(bl)

    def antnums_to_bl(self, antnums):
        """
        Convert tuple of antenna numbers to baseline integer.

        Parameters
        ----------
        antnums : tuple
            tuple containing integer antenna numbers for a baseline.
            Ex. (ant1, ant2)

        Return
        ------
        bl : i6 integer
            baseline integer
        """
        return _antnums_to_bl(antnums)

    def blpair_to_indices(self, blpair):
        """
        Convert a baseline-pair nested tuple ((ant1, ant2), (ant3, ant4)) or
        a baseline-pair integer into indices to index the blpairts axis of data_array.

        Parameters
        ----------
        blpair : nested tuple or blpair i12 integer, Ex. ((1, 2), (3, 4))
            or list of blpairs
        """
        # convert blpair to integer if fed as tuple
        if isinstance(blpair, tuple):
            blpair = [self.antnums_to_blpair(blpair)]
        elif isinstance(blpair, (np.int, int)):
            blpair = [blpair]
        elif isinstance(blpair, list):
            if isinstance(blpair[0], tuple):
                blpair = map(lambda blp: self.antnums_to_blpair(blp), blpair)
        # assert exists in data
        assert np.array(map(lambda b: b in self.blpair_array, blpair)).all(), "blpairs {} not all found in data".format(blpair)
        return np.arange(self.Nblpairts)[reduce(operator.add, map(lambda b: self.blpair_array == b, blpair))]

    def spw_to_indices(self, spw):
        """
        Convert a spectral window integer into a list of indices to index
        into the spwdlys axis of dly_array and/or freq_array.

        Parameters
        ----------
        spw : int, spectral window index or list of indices
        """
        # convert to list if int
        if isinstance(spw, (np.int, int)):
            spw = [spw]

        # assert exists in data
        assert np.array(map(lambda s: s in self.spw_array, spw)).all(), "spws {} not all found in data".format(spw)

        return np.arange(self.Nspwdlys)[reduce(operator.add, map(lambda s: self.spw_array == s, spw))]

    def pol_to_indices(self, pol):
        """
        Map a polarization integer or str to its index in pol_array

        Parameters
        ----------
        pol : str or int, polarization string (ex. 'XX') or integer (ex. -5)
            or list of strs or ints

        Returns
        -------
        indices : int, index of pol in pol_array
        """
        # convert pol to int if str
        if isinstance(pol, (str, np.str)):
            pol = [uvutils.polstr2num(pol)]
        elif isinstance(pol, (int, np.int)):
            pol = [pol]
        elif isinstance(pol, (list, tuple)):
            for i in range(len(pol)):
                if isinstance(pol[i], (np.str, str)):
                    pol[i] = uvutils.polstr2num(pol[i])

        # ensure all pols exist in data
        assert np.array(map(lambda p: p in self.pol_array, pol)).all(), "pols {} not all found in data".format(pol)

        indices = np.arange(self.Npols)[reduce(operator.add, map(lambda p: self.pol_array == p, pol))]
        return indices

    def key_to_indices(self, key, *args):
        """
        Convert a data key into relevant slice arrays. A data key takes the form

        (spw, ((ant1, ant2), (ant3, ant4)), pol)

        or

        (spw, blpair-integer, pol)

        where spw is the spectral window integer, ant1 etc. are integers, 
        and pol is either a polarization string (ex. 'XX') or integer (ex. -5).

        One can also expand this key into the kwarg slots, such that key=spw, key2=blpair, and key3=pol.
    
        Parameters
        ----------
        key : tuple, baseline-pair key

        Returns (spw, blpairts, pol)
        -------
        spw : integer
        blpairts : list of integers to apply along blpairts axis
        pol : integer
        """
        # assert key length
        if len(args) == 0: assert len(key) == 3, "length of key must be 3."
        elif len(args) > 0:
            assert isinstance(key, (int, np.int)) and len(args) == 2, "length of key must be 3."
            key = (key, args[0], args[1])

        # assign key elements
        spw = key[0]
        blpair = key[1]
        pol = key[2]
        # assert types
        assert type(spw) in (int, np.int), "spw must be an integer"
        assert type(blpair) in (int, np.int, tuple), "blpair must be an integer or nested tuple"
        assert type(pol) in (np.str, str, np.int, int), "pol must be a string or integer"
        # convert blpair to int if not int
        if type(blpair) == tuple:
            blpair = self.antnums_to_blpair(blpair)
        # convert pol to int if str
        if type(pol) in (str, np.str):
            pol = uvutils.polstr2num(pol)
        # check attribuets exists in data
        assert spw in self.spw_array, "spw {} not found in data".format(spw)
        assert blpair in self.blpair_array, "blpair {} not found in data".format(blpair)
        assert pol in self.pol_array, "pol {} not found in data".format(pol)
        # index polarization array
        pol = self.pol_to_indices(pol)
        # index blpairts
        blpairts = self.blpair_to_indices(blpair)

        return spw, blpairts, pol

    def select(self, spws=None, bls=None, only_pairs_in_bls=True, inplace=True):
        """
        Select function for selecting out certain slices of the data.

        Parameters
        ----------
        spws : list of spectral window integers to select

        bls : list of i6 baseline integers or baseline tuples, Ex. (2, 3) 
            Select all baseline-pairs whose first _or_ second baseline are in bls list.
            This changes if only_pairs_in_bls == True.

        only_pairs_in_bls : bool, if True, keep only baseline-pairs whose first _and_ second baseline
            are found in bls list.

        inplace : boolean, if True edit and overwrite arrays in self, else make a copy of self and return
        """
        if inplace:
            uvp = self
        else:
            uvp = copy.deepcopy(self)

        _select(uvp, spws=spws, bls=bls, only_pairs_in_bls=only_pairs_in_bls)

        if inplace == False:
            return uvp

    def get_ENU_bl_vecs(self):
        """
        return baseline vector array in TOPO (ENU) frame in meters, with matched ordering of self.bl_vecs.
        """
        return uvutils.ENU_from_ECEF((self.bl_vecs + self.telescope_location).T, *uvutils.LatLonAlt_from_XYZ(self.telescope_location)).T

    def read_hdf5(self, filepath, just_meta=False, spws=None, bls=None, only_pairs_in_bls=False):
        """
        Clear current UVPSpec object and load in data from an HDF5 file.

        Parameters
        ----------
        filepath : str, path to HDF5 file

        just_meta : boolean, read-in only metadata and no data, wgts or integration arrays

        spws : list of spectral window integers to select

        bls : list of i6 baseline integers or baseline tuples, Ex. (2, 3) 
            Select all baseline-pairs whose first _or_ second baseline are in bls list.
            This changes if only_pairs_in_bls == True.

        only_pairs_in_bls : bool, if True, keep only baseline-pairs whose first _and_ second baseline
            are found in bls list.
        """
        # clear object
        self._clear()

        # open file descriptor
        with h5py.File(filepath, 'r') as f:
            # load-in meta data
            for k in f.attrs:
                if k in self._meta_attrs:
                    setattr(self, k, f.attrs[k])
            for k in f:
                if k in self._meta_dsets:
                    setattr(self, k, f[k][:])

            if spws is not None or bls is not None:
                if just_meta:
                    _select(self, spws=spws, bls=bls, only_pairs_in_bls=only_pairs_in_bls)
                else:
                    _select(self, spws=spws, bls=bls, only_pairs_in_bls=only_pairs_in_bls, h5file=f)
                return

            if just_meta:
                return
            else:
                # load in all data if desired
                self.data_array = odict()
                self.wgt_array = odict()
                self.integration_array = odict()
                # iterate over spectral windows
                for i in np.arange(self.Nspws):
                    self.data_array[i] = f['data_spw{}'.format(i)][:]
                    self.wgt_array[i] = f['wgt_spw{}'.format(i)][:]
                    self.integration_array[i] = f['integration_spw{}'.format(i)][:]

    def write_hdf5(self, filepath, overwrite=False, run_check=True):
        """
        Write a UVPSpec object to HDF5 file.

        Parameters
        ----------
        filepath : str, filepath for output file

        overwrite : boolean, overwrite output file if it exists

        run_check : boolean, run UVPSpec check before writing to file
        """
        # check output
        if os.path.exists(filepath) and overwrite is False:
            raise IOError("{} exists, not overwriting...".format(filepath))
        elif os.path.exists(filepath) and overwrite is True:
            print "{} exists, overwriting...".format(filepath)
            os.remove(filepath)

        # run check
        if run_check:
            self.check()

        # write file
        with h5py.File(filepath, 'w') as f:
            # write meta data
            for k in self._meta_attrs:
                if hasattr(self, k):
                    f.attrs[k] = getattr(self, k)
            for k in self._meta_dsets:
                if hasattr(self, k):
                    f.create_dataset(k, data=getattr(self, k))

            # iterate over spectral windows and create datasets
            for i in np.unique(self.spw_array):
                f.create_dataset("data_spw{}".format(i), data=self.data_array[i], dtype=np.complex)
                f.create_dataset("wgt_spw{}".format(i), data=self.wgt_array[i], dtype=np.float)
                f.create_dataset("integration_spw{}".format(i), data=self.integration_array[i], dtype=np.float)

    def add_cosmology(self, cosmo):
        """
        Add a cosmological model to self.cosmo via an instance of hera_pspec.conversions.Cosmo_Conversions

        Parameters
        ----------
        cosmo : conversions.Cosmo_Conversions instance, or self.cosmo_params string, or dictionary
        """
        if isinstance(cosmo, (str, np.str)):
            cosmo = ast.literal_eval(cosmo)
        if isinstance(cosmo, (dict, odict)):
            cosmo = conversions.Cosmo_Conversions(**cosmo)
        print("attaching cosmology: \n{}".format(cosmo))
        self.cosmo = cosmo
        self.cosmo_params = str(self.cosmo.get_params())

    def check(self):
        """
        Run checks
        """
        # check required parameters exist
        for p in self._req_params:
            assert hasattr(self, p), "required parameter {} hasn't been defined".format(p)
        # check data
        assert type(self.data_array) in (dict, odict), "self.data_array must be a dictionary type"
        assert np.min(map(lambda k: self.data_array[k].dtype in (np.complex, complex, np.complex128), self.data_array.keys())), "self.data_array values must be complex type"
        # check wgts
        assert type(self.wgt_array) in (dict, odict), "self.wgt_array must be a dictionary type"
        assert np.min(map(lambda k: self.wgt_array[k].dtype in (np.float, float), self.wgt_array.keys())), "self.wgt_array values must be float type"
        # check integration
        assert type(self.integration_array) in (dict, odict), "self.integration_array must be a dictionary type"
        assert np.min(map(lambda k: self.integration_array[k].dtype in (np.float, float, np.float64), self.integration_array.keys())), "self.integration_array values must be float type"

    def _clear(self):
        """
        Clear UVPSpec of all parameters. Warning: this cannot be undone.
        """
        for p in self._all_params:
            if hasattr(self, p):
                delattr(self, p)

    def __eq__(self, other):
        """ Check equivalence between attributes of two UVPSpec objects """
        try:
            for p in self._all_params:
                if p not in self._req_params and (not hasattr(self, p) and not hasattr(other, p)):
                    continue
                if p in self._immutable_params:
                    assert getattr(self, p) == getattr(other, p)
                elif p in self._ndarrays:
                    assert np.isclose(getattr(self, p), getattr(other, p)).all()
                elif p in self._dicts:
                    for i in getattr(self, p):
                        assert np.isclose(getattr(self, p)[i], getattr(other, p)[i]).all()
        except AssertionError:
            return False

        return True

    def generate_noise_spectra(self, spw, Tsys, beam, little_h=True, form='Pk', num_steps=5000):
        """
        Generate the expected 1-sigma noise-floor power spectrum given the spectral window, system temp., 
        a beam model, a cosmological model, and the integration time of data_array.

        Parameters
        ----------
        spw : int, spectral window index to generate noise curve for

        Tsys : float, system temperature in Kelvin

        beam : pspecbeam.UVBeam instance

        form : str, form of pspectra, P(k) or Delta^2(k), options=['Pk', 'Dsq']

        Returns noise_spectra
        -------
        noise_spectra : complex ndarray containing power spectrum noise estimate, shape=(Nblpairts, Ndlys, Npols)
        """
        # assert cosmology exists
        assert hasattr(self, 'cosmo'), "self.cosmo required to generate noise spectra. See self.add_cosmology()"

        # get frequency band
        freqs = self.freq_array[self.spw_to_indices(spw)]

        # Get mean redshift
        avg_z = self.cosmo.f2z(np.mean(freqs))

        # loop over polarization
        noise_spectra = []

        for i, p in enumerate(self.pol_array):

            # Generate noise prefactor
            P_N = np.ones((uvp.Nblpairts, len(freqs), uvp.Npols), np.complex)

            # Multiply by scalar
            P_N *= beam.compute_pspec_scalar(freqs.min(), freqs.max(), len(freqs), num_steps=num_steps,
                                            stokes=p, no_Bpp_ov_BpSq=True, little_h=little_h)

            # Multiply by Tsys
            P_N *= Tsys**2

            # Divide by integration time
            P_N /= np.sqrt(self.integration_array[spw][:, None, i])

            # convert to deltasq
            if form == 'Dsq':
                k_perp, k_para = self.get_kvecs(spw, little_h=little_h)
                k_mag = np.sqrt(k_perp[:, None, None]**2 + k_para[None, :, None]**2)
                P_N *= k_mag**3 / (2*np.pi**2)


            noise_spectra.append(P_N)

        noise_spectra = np.moveaxis(noise_spectra, 0, -1)

        return noise_spectra

def _select(uvp, spws=None, bls=None, only_pairs_in_bls=False, h5file=None):
    """
    Select function for selecting out certain slices of the data.

    Parameters
    ----------
    uvp : UVPSpec object with at least meta-data in required params loaded in.
        If only meta-data is loaded in then h5file must be specified.

    spws : list of spectral window integers to select

    bls : list of i6 baseline integers or baseline tuples, Ex. (2, 3) 
        Select all baseline-pairs whose first _or_ second baseline are in bls list.
        This changes if only_pairs_in_bls == True.

    only_pairs_in_bls : bool, if True, keep only baseline-pairs whose first _and_ second baseline
        are both found in bls list.

    h5file : h5py file descriptor, used for loading in selection of data from h5py file
    """
    if spws is not None:
        # spectral window selection
        spw_select = uvp.spw_to_indices(spws)
        uvp.spw_array = uvp.spw_array[spw_select]
        uvp.freq_array = uvp.freq_array[spw_select]
        uvp.dly_array = uvp.dly_array[spw_select]
        uvp.Nspws = len(np.unique(uvp.spw_array))
        uvp.Ndlys = len(np.unique(uvp.dly_array))
        uvp.Nspwdlys = len(uvp.spw_array)
        if hasattr(uvp, 'scalar_array'):
            uvp.scalar_array = uvp.scalar_array[spws, :]

    if bls is not None:
        # get blpair baselines in integer form
        bl1 = np.floor(uvp.blpair_array / 1e6)
        blpair_bls = np.vstack([bl1, uvp.blpair_array - bl1*1e6]).astype(np.int).T
        # ensure bls is in integer form
        if isinstance(bls, tuple):
            assert isinstance(bls[0], (int, np.int)), "bls must be fed as a list of baseline tuples Ex: [(1, 2), ...]"
            bls = [uvp.antnums_to_bl(bls)]
        elif isinstance(bls, list):
            if isinstance(bls[0], tuple):
                bls = map(lambda b: uvp.antnums_to_bl(b), bls)
        elif isinstance(bls, (int, np.int)):
            bls = [bls]
        # get indices
        if only_pairs_in_bls:
            blp_select = np.array(reduce(operator.add, map(lambda b: (blpair_bls[:,0]==b) * (blpair_bls[:,1]==b), bls)))
        else:
            blp_select = np.array(reduce(operator.add, map(lambda b: (blpair_bls[:,0]==b) + (blpair_bls[:,1]==b), bls)))
        # index arrays
        uvp.blpair_array = uvp.blpair_array[blp_select]
        uvp.time_1_array = uvp.time_1_array[blp_select]
        uvp.time_2_array = uvp.time_2_array[blp_select]
        uvp.lst_1_array = uvp.lst_1_array[blp_select]
        uvp.lst_2_array = uvp.lst_2_array[blp_select]
        uvp.Ntimes = len(np.unique(uvp.time_1_array))
        uvp.Nblpairs = len(np.unique(uvp.blpair_array))
        uvp.Nblpairts = len(uvp.blpair_array)
        bl_array = np.unique(blpair_bls)
        bl_select = reduce(operator.add, map(lambda b: uvp.bl_array==b, bl_array))
        uvp.bl_array = uvp.bl_array[bl_select]
        uvp.bl_vecs = uvp.bl_vecs[bl_select]
        uvp.Nbls = len(uvp.bl_array)        

    # select data arrays
    try:
        # select data arrays
        data = odict()
        wgts = odict()
        ints = odict()
        for s in np.unique(uvp.spw_array):
            if h5file is not None:
                if bls is not None:
                    # fancy index
                    data[s] = h5file['data_spw{}'.format(s)][blp_select, :, :]
                    wgts[s] = h5file['wgt_spw{}'.format(s)][blp_select, :, :]
                    ints[s] = h5file['integration_spw{}'.format(s)][blp_select, :]
                else:
                    # slice
                    data[s] = h5file['data_spw{}'.format(s)][:]
                    wgts[s] = h5file['wgt_spw{}'.format(s)][:]
                    ints[s] = h5file['integration_spw{}'.format(s)][:]
            else:
                if bls is not None:
                    data[s] = uvp.data_array[s][blp_select]
                    wgts[s] = uvp.wgt_array[s][blp_select]
                    ints[s] = uvp.integration_array[s][blp_select]
                else:
                    data[s] = uvp.data_array[s]
                    wgts[s] = uvp.wgt_array[s]
                    ints[s] = uvp.integration_array[s]
 
        uvp.data_array = data
        uvp.wgt_array = wgts
        uvp.integration_array = ints
    except AttributeError:
        # if no h5file fed and hasattr(uvp, data_array) is False then just load meta-data
        pass

def _blpair_to_antnums(blpair):
    """
    Convert baseline-pair integer to nested tuple of antenna numbers.

    Parameters
    ----------
    blpair : <i12 integer
        baseline-pair integer

    Return
    ------
    antnums : tuple
        nested tuple containing baseline-pair antenna numbers. Ex. ((ant1, ant2), (ant3, ant4))
    """
    # get antennas
    ant1 = int(np.floor(blpair / 1e9))
    ant2 = int(np.floor(blpair / 1e6 - ant1*1e3))
    ant3 = int(np.floor(blpair / 1e3 - ant1*1e6 - ant2*1e3))
    ant4 = int(np.floor(blpair - ant1*1e9 - ant2*1e6 - ant3*1e3))

    # form antnums tuple
    antnums = ((ant1, ant2), (ant3, ant4))

    return antnums

def _antnums_to_blpair(antnums):
    """
    Convert nested tuple of antenna numbers to baseline-pair integer.

    Parameters
    ----------
    antnums : tuple
        nested tuple containing integer antenna numbers for a baseline-pair.
        Ex. ((ant1, ant2), (ant3, ant4))

    Return
    ------
    blpair : <i12 integer
        baseline-pair integer
    """
    # get antennas
    ant1 = antnums[0][0]
    ant2 = antnums[0][1]
    ant3 = antnums[1][0]
    ant4 = antnums[1][1]

    # form blpair
    blpair = int(ant1*1e9 + ant2*1e6 + ant3*1e3 + ant4)

    return blpair

def _bl_to_antnums(bl):
    """
    Convert baseline integer to tuple of antenna numbers.

    Parameters
    ----------
    blpair : <i6 integer
        baseline integer

    Return
    ------
    antnums : tuple
        tuple containing baseline antenna numbers. Ex. (ant1, ant2)
    """
    # get antennas
    ant1 = int(np.floor(bl / 1e3))
    ant2 = int(np.floor(bl - ant1*1e3))

    # form antnums tuple
    antnums = (ant1, ant2)

    return antnums

def _antnums_to_bl(antnums):
    """
    Convert tuple of antenna numbers to baseline integer.

    Parameters
    ----------
    antnums : tuple
        tuple containing integer antenna numbers for a baseline.
        Ex. (ant1, ant2)

    Return
    ------
    blpair : <i6 integer
        baseline integer
    """
    # get antennas
    ant1 = antnums[0]
    ant2 = antnums[1]

    # form blpair
    blpair = int(ant1*1e3 + ant2)

    return blpair

def _blpair_to_bls(blpair):
    """
    Convert a blpair integer or nested tuple of antenna pairs
    into a tuple of baseline integers

    Parameters
    ----------
    blpair : baseline-pair integer or nested antenna-pair tuples
    """
    # convert to antnums if fed as ints
    if isinstance(blpair, int):
        blpair = _antnums_to_blpair(blpair)

    # convert first and second baselines to baseline ints
    bl1 = _antnums_to_bl(blpair[0])
    bl2 = _antnums_to_bl(blpair[1])

    return bl1, bl2

def _conj_blpair_int(blpair):
    """
    Conjugate a baseline-pair integer

    Parameters
    ----------
    blpair : <12 int
        baseline-pair integer

    Return
    -------
    conj_blpair : <12 int
        conjugated baseline-pair integer. 
        Ex: ((ant1, ant2), (ant3, ant4)) --> ((ant3, ant4), (ant1, ant2))
    """
    antnums = _blpair_to_antnums(blpair)
    conj_blpair = _antnums_to_blpair(antnums[::-1])
    return conj_blpair


def _conj_bl_int(bl):
    """
    Conjugate a baseline integer

    Parameters
    ----------
    blpair : i6 int
        baseline integer

    Return
    -------
    conj_bl : i6 int
        conjugated baseline integer. 
        Ex: (ant1, ant2) --> (ant2, ant1)
    """
    antnums = _bl_to_antnums(bl)
    conj_bl = _antnums_to_bl(antnums[::-1])
    return conj_bl


def _conj_blpair(blpair, which='both'):
    """
    Conjugate one or both baseline(s) in a baseline-pair
    Ex. ((ant1, ant2), (ant3, ant4)) --> ((ant2, ant1), (ant4, ant3))

    Parameters
    ----------
    blpair : <12 int
        baseline-pair int

    which : str, options=['first', 'second', 'both']
        which baseline to conjugate

    Return
    ------
    conj_blpair : <12 int
        blpair with one or both baselines conjugated
    """
    antnums = _blpair_to_antnums(blpair)
    if which == 'first':
        conj_blpair = _antnums_to_blpair((antnums[0][::-1], antnums[1]))
    elif which == 'second':
        conj_blpair = _antnums_to_blpair((antnums[0], antnums[1][::-1]))
    elif which == 'both':
        conj_blpair = _antnums_to_blpair((antnums[0][::-1], antnums[1][::-1]))
    else:
        raise ValueError("didn't recognize {}".format(which))

    return conj_blpair




