import numpy as np
import aipy
import pyuvdata
import copy, operator, itertools
from collections import OrderedDict as odict
import hera_cal as hc
from hera_pspec import uvpspec, utils, version, pspecbeam
from hera_pspec import uvpspec_utils as uvputils
from pyuvdata import utils as uvutils
import datetime


class PSpecData(object):

    def __init__(self, dsets=[], wgts=[], labels=None, beam=None):
        """
        Object to store multiple sets of UVData visibilities and perform
        operations such as power spectrum estimation on them.

        Parameters
        ----------
        dsets : list or dict of UVData objects, optional
            Set of UVData objects containing the data that will be used to
            compute the power spectrum. If specified as a dict, the key names 
            will be used to tag each dataset. Default: Empty list.

        wgts : list or dict of UVData objects, optional
            Set of UVData objects containing weights for the input data.
            Default: Empty list.
        
        labels : list of str, optional
            An ordered list of names/labels for each dataset, if dsets was 
            specified as a list. If None, names will not be assigned to the 
            datasets. If dsets was specified as a dict, the keys 
            of that dict will be used instead of this. Default: None.
        
        beam : PspecBeam object, optional
            PspecBeam object containing information about the primary beam
            Default: None.
        """
        self.clear_cov_cache()  # Covariance matrix cache
        self.dsets = []; self.wgts = []; self.labels = []
        self.Nfreqs = None
        self.spw_range = None
        self.spw_Nfreqs = None
        
        # Set R to identity by default
        self.R = self.I

        # Store the input UVData objects if specified
        if len(dsets) > 0:
            self.add(dsets, wgts, labels=labels)

        # Store a primary beam
        self.primary_beam = beam

    def add(self, dsets, wgts, labels=None):
        """
        Add a dataset to the collection in this PSpecData object.

        Parameters
        ----------
        dsets : UVData or list or dict
            UVData object or list of UVData objects containing data to add to
            the collection.

        wgts : UVData or list or dict
            UVData object or list of UVData objects containing weights to add
            to the collection. Must be the same length as dsets. If a weight is
            set to None, the flags of the corresponding

        labels : list of str
            An ordered list of names/labels for each dataset, if dsets was 
            specified as a list. If dsets was specified as a dict, the keys 
            of that dict will be used instead.
        """
        # Check for dicts and unpack into an ordered list if found
        if isinstance(dsets, dict):
            # Disallow labels kwarg if a dict was passed
            if labels is not None:
                raise ValueError("If 'dsets' is a dict, 'labels' cannot be "
                                 "specified.")
            
            if not isinstance(wgts, dict):
                raise TypeError("If 'dsets' is a dict, 'wgts' must also be "
                                "a dict")
            
            # Unpack dsets and wgts dicts
            labels = dsets.keys()
            _dsets = [dsets[key] for key in labels]
            _wgts = [wgts[key] for key in labels]
            dsets = _dsets
            wgts = _wgts
            
        # Convert input args to lists if possible
        if isinstance(dsets, pyuvdata.UVData): dsets = [dsets,]
        if isinstance(wgts, pyuvdata.UVData): wgts = [wgts,]
        if isinstance(labels, str): labels = [labels,]
        if wgts is None: wgts = [wgts,]
        if isinstance(dsets, tuple): dsets = list(dsets)
        if isinstance(wgts, tuple): wgts = list(wgts)

        # Only allow UVData or lists
        if not isinstance(dsets, list) or not isinstance(wgts, list):
            raise TypeError("dsets and wgts must be UVData or lists of UVData")

        # Make sure enough weights were specified
        assert(len(dsets) == len(wgts))
        if labels is not None: assert(len(dsets) == len(labels))

        # Check that everything is a UVData object
        for d, w in zip(dsets, wgts):
            if not isinstance(d, pyuvdata.UVData):
                raise TypeError("Only UVData objects can be used as datasets.")
            if not isinstance(w, pyuvdata.UVData) and w is not None:
                raise TypeError("Only UVData objects (or None) can be used as "
                                "weights.")

        # Append to list
        self.dsets += dsets
        self.wgts += wgts
        
        # Store labels (if they were set)
        if labels is None:
            self.labels = [None for d in dsets]
        else:
            self.labels += labels

        # Store no. frequencies and no. times
        self.Nfreqs = self.dsets[0].Nfreqs
        self.Ntimes = self.dsets[0].Ntimes
        
        # Store the actual frequencies
        self.freqs = self.dsets[0].freq_array[0]
        self.spw_range = (0, self.Nfreqs)
        self.spw_Nfreqs = self.Nfreqs
    
    def __str__(self):
        """
        Print basic info about this PSpecData object.
        """
        # Basic info
        s = "PSpecData object\n"
        s += "  %d datasets" % len(self.dsets)
        if len(self.dsets) == 0: return s
        
        # Dataset summary
        for i, d in enumerate(self.dsets):
            if self.labels[i] is None:
                s += "  dset (%d): %d bls (freqs=%d, times=%d, pols=%d)\n" \
                      % (i, d.Nbls, d.Nfreqs, d.Ntimes, d.Npols)
            else:
                s += "  dset '%s' (%d): %d bls (freqs=%d, times=%d, pols=%d)\n" \
                      % (self.labels[i], i, d.Nbls, d.Nfreqs, d.Ntimes, d.Npols)
        return s
        
    def validate_datasets(self, verbose=True):
        """
        Validate stored datasets and weights to make sure they are consistent
        with one another (e.g. have the same shape, baselines etc.).
        """
        # check dsets and wgts have same number of elements
        if len(self.dsets) != len(self.wgts):
            raise ValueError("self.wgts does not have same length as self.dsets")

        # Check if dsets are all the same shape along freq axis
        Nfreqs = [d.Nfreqs for d in self.dsets]
        if np.unique(Nfreqs).size > 1:
            raise ValueError("all dsets must have the same Nfreqs")

        # Check shape along time axis
        Ntimes = [d.Ntimes for d in self.dsets]
        if np.unique(Ntimes).size > 1:
            raise ValueError("all dsets must have the same Ntimes")

        # raise warnings if times don't match
        lst_diffs = np.array(map(lambda dset: np.unique(self.dsets[0].lst_array) - np.unique(dset.lst_array), self.dsets[1:]))
        if np.max(np.abs(lst_diffs)) > 0.001:
            raise_warning("Warning: taking power spectra between LST bins misaligned by more than 15 seconds",
                            verbose=verbose)

        # raise warning if frequencies don't match       
        freq_diffs = np.array(map(lambda dset: np.unique(self.dsets[0].freq_array) - np.unique(dset.freq_array), self.dsets[1:]))
        if np.max(np.abs(freq_diffs)) > 0.001e6:
            raise_warning("Warning: taking power spectra between frequency bins misaligned by more than 0.001 MHz",
                          verbose=verbose)

        # Check phase type
        phase_types = []
        for d in self.dsets: phase_types.append(d.phase_type)
        if np.unique(phase_types).size > 1:
            raise ValueError("all datasets must have the same phase type (i.e. 'drift', 'phased', ...)\ncurrent phase types are {}".format(phase_types))

        # Check phase centers if phase type is phased
        if 'phased' in set(phase_types):
            phase_ra = map(lambda d: d.phase_center_ra_degrees, self.dsets)
            phase_dec = map(lambda d: d.phase_center_dec_degrees, self.dsets)
            max_diff_ra = np.max(map(lambda d: np.diff(d), itertools.combinations(phase_ra, 2)))
            max_diff_dec = np.max(map(lambda d: np.diff(d), itertools.combinations(phase_dec, 2)))
            max_diff = np.sqrt(max_diff_ra**2 + max_diff_dec**2)
            if max_diff > 0.15: raise_warning("Warning: maximum phase-center difference between datasets is > 10 arcmin", verbose=verbose)
    
    def check_key_in_dset(self, key, dset_ind):
        """
        Check 'key' exists in the UVData object self.dsets[dset_ind]

        Parameters
        ----------
        key : tuple
            if length 1: assumed to be polarization number or string
            elif length 2: assumed to be antenna-number tuple (ant1, ant2)
            elif length 3: assumed ot be antenna-number-polarization tuple (ant1, ant2, pol)

        dset_ind : int, the index of the dataset to-be-checked

        Returns
        -------
        exists : bool
            True if the key exists, False otherwise
        """
        #FIXME: Fix this to enable label keys
        
        
        # get iterable
        key = pyuvdata.utils.get_iterable(key)
        if isinstance(key, str):
            key = (key,)

        # check key is a tuple
        if isinstance(key, tuple) == False or len(key) not in (1, 2, 3):
            raise KeyError("key {} must be a length 1, 2 or 3 tuple".format(key))

        try:
            _ = self.dsets[dset_ind]._key2inds(key)
            return True
        except KeyError:
            return False

    def clear_cov_cache(self, keys=None):
        """
        Clear stored covariance data (or some subset of it).

        Parameters
        ----------
        keys : list of tuples, optional
            List of keys to remove from covariance matrix cache. If None, all
            keys will be removed. Default: None.
        """
        if keys is None:
            self._C, self._I, self._iC = {}, {}, {}
            self._iCt = {}
        else:
            for k in keys:
                try: del(self._C[k])
                except(KeyError): pass
                try: del(self._I[k])
                except(KeyError): pass
                try: del(self._iC[k])
                except(KeyError): pass

    def dset_idx(self, dset):
        """
        Return the index of a dataset, regardless of whether it was specified 
        as an integer of a string.

        Parameters
        ----------
        dset : int or str
            Index or name of a dataset belonging to this PSpecData object.

        Returns
        -------
        dset_idx : int
            Index of dataset.
        """
        # Look up dset label if it's a string
        if isinstance(dset, str):
            if dset in self.labels:
                return self.labels.index(dset)
            else:
                raise KeyError("dset '%s' not found." % dset)
        elif isinstance(dset, int):
            return dset
        else:
            raise TypeError("dset must be either an int or string")

    def parse_blkey(self, key):
        """
        Parse a dataset + baseline key in the form (dataset, baseline, [pol]) 
        into a dataset index and a baseline(pol) key, where pol is optional.

        Parameters
        ----------
        key : tuple

        Returns
        -------
        dset : int
            dataset index

        bl : tuple
            baseline (pol) key
        """
        # type check
        assert isinstance(key, tuple), "key must be fed as a tuple"
        assert len(key) > 1, "key must have len >= 2"

        # get dataset index
        dset_idx = self.dset_idx(key[0])
        key = key[1:]

        # get baseline
        bl = key[0]
        if isinstance(bl, (int, np.int, np.int32)):
            assert len(key) > 1, "baseline must be fed as a tuple"
            bl = tuple(key[:2])
            key = key[2:]
        else:
            key = key[1:]
        assert isinstance(bl, tuple), "baseline must be fed as a tuple"

        # put pol into bl key if it exists
        if len(key) > 0:
            pol = key[0]
            assert isinstance(pol, (str, int, np.int, np.int32)), "pol must be fed as a str or int"
            bl += (key[0],)

        return dset_idx, bl

    def x(self, key):
        """
        Get data for a given dataset and baseline, as specified in a standard
        key format.

        Parameters
        ----------
        key : tuple
            Tuple containing dataset ID and baseline index. The first element
            of the tuple is the dataset index (or label), and the subsequent 
            elements are the baseline ID.

        Returns
        -------
        x : array_like
            Array of data from the requested UVData dataset and baseline.
        """
        dset, bl = self.parse_blkey(key)
        spw = slice(self.spw_range[0], self.spw_range[1])
        return self.dsets[dset].get_data(bl).T[spw]

    def w(self, key):
        """
        Get weights for a given dataset and baseline, as specified in a
        standard key format.

        Parameters
        ----------
        key : tuple
            Tuple containing dataset ID and baseline index. The first element
            of the tuple is the dataset index, and the subsequent elements are
            the baseline ID.

        Returns
        -------
        x : array_like
            Array of weights for the requested UVData dataset and baseline.
        """
        dset, bl = self.parse_blkey(key)
        spw = slice(self.spw_range[0], self.spw_range[1])
        
        if self.wgts[dset] is not None:
            return self.wgts[dset].get_data(bl).T[spw]
        else:
            # If weights were not specified, use the flags built in to the
            # UVData dataset object
            wgts = (~self.dsets[dset].get_flags(bl)).astype(float).T[spw]
            return wgts

    def set_C(self, cov):
        """
        Set the cached covariance matrix to a set of user-provided values.

        Parameters
        ----------
        cov : dict
            Dictionary containing new covariance values for given datasets and
            baselines. Keys of the dictionary are tuples, with the first item
            being the ID (index) of the dataset, and subsequent items being the
            baseline indices.
        """
        self.clear_cov_cache(cov.keys())
        for key in cov: self._C[key] = cov[key]

    def C_model(self, key, model='empirical'):
        """
        Return a covariance model having specified a key and model type.

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        model : string, optional
            Type of covariance model to calculate, if not cached. options=['empirical']

        Returns
        -------
        C : array-like
            Covariance model for the specified key.
        """
        # type check
        assert isinstance(key, tuple), "key must be fed as a tuple"
        assert isinstance(model, (str, np.str)), "model must be a string"
        assert model in ['empirical'], "didn't recognize model {}".format(model)

        # parse key
        dset, bl = self.parse_blkey(key)
        key = (dset,) + (bl,)

        # add model to key
        Ckey = key + (model,)

        # check cache
        if not self._C.has_key(Ckey):
            # calculate covariance model
            if model == 'empirical':
                self.set_C({Ckey: utils.cov(self.x(key), self.w(key))})

        return self._C[Ckey]

    def I(self, key):
        """
        Return identity covariance matrix.

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        Returns
        -------
        I : array_like
            Identity covariance matrix, dimension (Nfreqs, Nfreqs).
        """
        assert isinstance(key, tuple)
        # parse key
        dset, bl = self.parse_blkey(key)
        key = (dset,) + (bl,)

        if not self._I.has_key(key):
            self._I[key] = np.identity(self.spw_Nfreqs)
        return self._I[key]

    def iC(self, key, model='empirical'):
        """
        Return the inverse covariance matrix, C^-1.

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        model : string
            Type of covariance model to calculate, if not cached. options=['empirical']

        Returns
        -------
        iC : array_like
            Inverse covariance matrix for specified dataset and baseline.
        """
        assert isinstance(key, tuple)
        # parse key
        dset, bl = self.parse_blkey(key)
        key = (dset,) + (bl,)

        Ckey = key + (model,)

        # Calculate inverse covariance if not in cache
        if not self._iC.has_key(Ckey):
            C = self.C_model(key, model=model)
            U,S,V = np.linalg.svd(C.conj()) # conj in advance of next step

            # FIXME: Not sure what these are supposed to do
            #if self.lmin is not None: S += self.lmin # ensure invertibility
            #if self.lmode is not None: S += S[self.lmode-1]

            # FIXME: Is series of dot products quicker?
            self.set_iC({Ckey:np.einsum('ij,j,jk', V.T, 1./S, U.T)})
        return self._iC[Ckey]

    def set_iC(self, d):
        """
        Set the cached inverse covariance matrix for a given dataset and
        baseline to a specified value. For now, you should already have applied
        weights to this matrix.

        Parameters
        ----------
        d : dict
            Dictionary containing data to insert into inverse covariance matrix
            cache. Keys are tuples, following the same format as the input to
            self.iC().
        """
        for k in d: self._iC[k] = d[k]
    
    def set_R(self, R_matrix):
        """
        Set the weighting matrix R for later use in q_hat.

        Parameters
        ----------
        R_matrix : string or matrix
            If set to "identity", sets R = I
            If set to "iC", sets R = C^-1
            Otherwise, accepts a user inputted dictionary
        """
        if R_matrix == "identity":
            self.R = self.I
        elif R_matrix == "iC":
            self.R = self.iC
        else:
            self.R = R_matrix
    
    def set_spw(self, spw_range):
        """
        Set the spectral window range.

        Parameters
        ----------
        spw_range : tuple, contains start and end of spw in channel indices
            used to slice the frequency array
        """
        assert isinstance(spw_range, tuple), \
            "spw_range must be fed as a len-2 integer tuple"
        assert isinstance(spw_range[0], (int, np.int)), \
            "spw_range must be fed as len-2 integer tuple"
        self.spw_range = spw_range
        self.spw_Nfreqs = spw_range[1] - spw_range[0]

    def q_hat(self, key1, key2, use_fft=True, taper='none'):
        """
        Construct an unnormalized bandpower, q_hat, from a given pair of
        visibility vectors. Returns the following quantity:

          \hat{q}_a = (1/2) conj(x_1) R_1 Q^alt_a R_2 x_2

        Note that the R matrix need not be set to C^-1. This is something that
        is set by the user in the set_R method.

        This is related to Equation 13 of arXiv:1502.06016. However, notice
        that there is a Q^alt_a instead of Q_a. The latter is defined as
        Q_a \equiv dC/dp_a. Since this is the derivative of the covariance
        with respect to the power spectrum, it contains factors of the primary
        beam etc. Q^alt_a strips away all of this, leaving only the barebones
        job of taking a Fourier transform. See HERA memo #44 for details.

        Parameters
        ----------
        key1, key2 : tuples or lists of tuples
            Tuples containing indices of dataset and baselines for the two 
            input datavectors. If a list of tuples is provided, the baselines 
            in the list will be combined with inverse noise weights.
            
        use_fft : bool, optional
            Whether to use a fast FFT summation trick to construct q_hat, or
            a simpler brute-force matrix multiplication. The FFT method assumes
            a delta-fn bin in delay space. Default: True.

        taper : str, optional
            Tapering (window) function to apply to the data. Takes the same
            arguments as aipy.dsp.gen_window(). Default: 'none'.

        Returns
        -------
        q_hat : array_like
            Unnormalized bandpowers
        """
        Rx1, Rx2 = 0, 0
        
        # Calculate R x_1
        if isinstance(key1, list):
            for _key in key1: Rx1 += np.dot(self.R(_key), self.x(_key))
        else:
            Rx1 = np.dot(self.R(key1), self.x(key1))
        
        # Calculate R x_2
        if isinstance(key2, list):
            for _key in key2: Rx2 += np.dot(self.R(_key), self.x(_key))
        else:
            Rx2 = np.dot(self.R(key2), self.x(key2))
        
        # Whether to use FFT or slow direct method
        if use_fft:
            if taper != 'none':
                tapering_fct = aipy.dsp.gen_window(self.spw_Nfreqs, taper)
                Rx1 *= tapering_fct[:, None]
                Rx2 *= tapering_fct[:, None]

            _Rx1 = np.fft.fft(Rx1.conj(), axis=0)
            _Rx2 = np.fft.fft(Rx2.conj(), axis=0)
            
            return 0.5 * np.conj(  np.fft.fftshift(_Rx1, axes=0).conj() 
                                 * np.fft.fftshift(_Rx2, axes=0) )
        else:
            # get taper if provided
            if taper != 'none':
                tapering_fct = aipy.dsp.gen_window(self.spw_Nfreqs, taper)

            # Slow method, used to explicitly cross-check FFT code
            q = []
            for i in xrange(self.spw_Nfreqs):
                Q = self.get_Q(i, self.spw_Nfreqs)
                RQR = np.einsum('ab,bc,cd',
                                self.R(key1).T.conj(), Q, self.R(key2))
                x1 = self.x(key1).conj()
                x2 = self.x(key2)
                if taper != 'none':
                    x1 = x1 * tapering_fct[:, None]
                    x2 = x2 * tapering_fct[:, None]
                qi = np.sum(x1*np.dot(RQR, x2), axis=0)
                q.append(qi)
            return 0.5 * np.array(q)

    def get_G(self, key1, key2):
        """
        Calculates

            G_ab = (1/2) Tr[R_1 Q_a R_2 Q_b],

        which is needed for normalizing the power spectrum (see HERA memo #44).

        Note that in the limit that R_1 = R_2 = C^-1, this reduces to the Fisher
        matrix

            F_ab = 1/2 Tr [C^-1 Q_a C^-1 Q_b] (arXiv:1502.06016, Eq. 17)

        Parameters
        ----------
        key1, key2 : tuples or lists of tuples
            Tuples containing indices of dataset and baselines for the two 
            input datavectors. If a list of tuples is provided, the baselines 
            in the list will be combined with inverse noise weights.

        Returns
        -------
        G : array_like, complex
            Fisher matrix, with dimensions (Nfreqs, Nfreqs).
        """
        G = np.zeros((self.spw_Nfreqs, self.spw_Nfreqs), dtype=np.complex)
        R1 = self.R(key1)
        R2 = self.R(key2)

        iR1Q, iR2Q = {}, {}
        for ch in xrange(self.spw_Nfreqs): # this loop is nchan^3
            Q = self.get_Q(ch, self.spw_Nfreqs)
            iR1Q[ch] = np.dot(R1, Q) # R_1 Q
            iR2Q[ch] = np.dot(R2, Q) # R_2 Q

        for i in xrange(self.spw_Nfreqs): # this loop goes as nchan^4
            for j in xrange(self.spw_Nfreqs):
                # tr(R_2 Q_i R_1 Q_j)
                G[i,j] += np.einsum('ab,ba', iR1Q[i], iR2Q[j])

        return G / 2.

    def get_H(self, key1, key2, taper='none'):
        """
        Calculates the response matrix H of the unnormalized band powers q
        to the true band powers p, i.e.,

            <q_a> = \sum_b H_{ab} p_b

        This is given by

            H_ab = (1/2) Tr[R_1 Q_a^alt R_2 Q_b]

        (See HERA memo #44). As currently implemented, this approximates the
        primary beam as frequency independent. Under this approximation, the
        our H_ab is defined using the equation above *except* we have
        Q^tapered rather than Q_b, where

            \overline{Q}^{tapered,beta} 
            = e^{i 2pi eta_beta (nu_i - nu_j)} gamma(nu_i) gamma(nu_j)

        where gamma is the tapering function. Again, see HERA memo #44 for
        details.

        Note that in the limit that R_1 = R_2 = C^-1 and Q_a is used instead
        of Q_a^alt, this reduces to the Fisher matrix

            F_ab = 1/2 Tr [C^-1 Q_a C^-1 Q_b] (arXiv:1502.06016, Eq. 17)

        Parameters
        ----------
        key1, key2 : tuples or lists of tuples
            Tuples containing indices of dataset and baselines for the two 
            input datavectors. If a list of tuples is provided, the baselines 
            in the list will be combined with inverse noise weights.

        taper : str, optional
            Tapering (window) function to apply to the data. Takes the same
            arguments as aipy.dsp.gen_window(). Default: 'none'.

        Returns
        -------
        H : array_like, complex
            Dimensions (Nfreqs, Nfreqs).
        """
        H = np.zeros((self.spw_Nfreqs, self.spw_Nfreqs), dtype=np.complex)
        R1 = self.R(key1)
        R2 = self.R(key2)

        if taper != 'none':
            tapering_fct = aipy.dsp.gen_window(self.spw_Nfreqs, taper)
            tapering_matrix = np.diag(tapering_fct)

        iR1Q_alt, iR2Q = {}, {}
        for ch in xrange(self.spw_Nfreqs): # this loop is nchan^3
            Q_alt = self.get_Q(ch, self.spw_Nfreqs)
            iR1Q_alt[ch] = np.dot(R1, Q_alt) # R_1 Q_alt
            if taper != 'none':
                Q_tapered = np.dot(tapering_matrix, np.dot(Q_alt, tapering_matrix))
                iR2Q[ch] = np.dot(R2, Q_tapered) # R_2 Q
            else:
                iR2Q[ch] = np.dot(R2, Q_alt) # R_2 Q

        for i in xrange(self.spw_Nfreqs): # this loop goes as nchan^4
            for j in xrange(self.spw_Nfreqs):
                # tr(R_2 Q_i R_1 Q_j)
                H[i,j] += np.einsum('ab,ba', iR1Q_alt[i], iR2Q[j])

        return H / 2.
    
    def get_V_gaussian(self, key1, key2):
        """
        Calculates the bandpower covariance matrix,
        
            V_ab = tr(C E_a C E_b)
            
        FIXME: Must check factor of 2 with Wick's theorem for complex vectors,
        and also check expression for when x_1 != x_2.
        
        Parameters
        ----------
        key1, key2 : tuples or lists of tuples
            Tuples containing indices of dataset and baselines for the two 
            input datavectors. If a list of tuples is provided, the baselines 
            in the list will be combined with inverse noise weights.
        
        Returns
        -------
        V : array_like, complex
            Bandpower covariance matrix, with dimensions (Nfreqs, Nfreqs).
        """
        raise NotImplementedError()

    def get_MW(self, G, H, mode='I'):
        """
        Construct the normalization matrix M and window function matrix W for
        the power spectrum estimator. These are defined through Eqs. 14-16 of
        arXiv:1502.06016:

            \hat{p} = M \hat{q}
            <\hat{p}> = W p
            W = M H,

        where p is the true band power and H is the response matrix (defined above
        in get_H) of unnormalized bandpowers to normed bandpowers.

        Several choices for M are supported:
            'I':      Set M to be diagonal (e.g. HERA Memo #44)

        These choices will be supported very soon:
            'G^-1':   Set M = G^-1, the (pseudo)inverse response matrix.
            'G^-1/2': Set M = G^-1/2, the root-inverse response matrix (using SVD).
            'L^-1':   Set M = L^-1, Cholesky decomposition.

        As written, the window functions will not be correclty normalized; it needs
        to be adjusted by the pspec scalar for it to be approximately correctly
        normalized. If the beam is being provided, this will be done in the pspec
        function.

        Parameters
        ----------
        G : array_like
            Denominator matrix for the bandpowers, with dimensions (Nfreqs, Nfreqs).

        H : array_like
            Response matrix for the bandpowers, with dimensions (Nfreqs, Nfreqs).

        mode : str, optional
            Definition to use for M. Must be one of the options listed above.
            Default: 'I'.

        Returns
        -------
        M : array_like
            Normalization matrix, M. (If G was passed in as a dict, a dict of
            array_like will be returned.)

        W : array_like
            Window function matrix, W. (If G was passed in as a dict, a dict of
            array_like will be returned.)
        """

        ### Next few lines commented out because (while elegant), the situation
        ### here where G is a distionary is not supported by the rest of the code.
        # Recursive case, if many G's were specified at once
        # if type(G) is dict:
        #     M,W = {}, {}
        #     for key in G: M[key], W[key] = self.get_MW(G[key], mode=mode)
        #     return M, W

        # Check that mode is supported
        modes = ['G^-1', 'G^-1/2', 'I', 'L^-1']
        assert(mode in modes)

        # Build M matrix according to specified mode
        if mode == 'G^-1':
            raise NotImplementedError("G^-1 mode not currently supported.")
            # M = np.linalg.pinv(G, rcond=1e-12)
            # #U,S,V = np.linalg.svd(F)
            # #M = np.einsum('ij,j,jk', V.T, 1./S, U.T)

        elif mode == 'G^-1/2':
            raise NotImplementedError("G^-1/2 mode not currently supported.")
            # U,S,V = np.linalg.svd(G)
            # M = np.einsum('ij,j,jk', V.T, 1./np.sqrt(S), U.T)

        elif mode == 'I':
            # This is not the M matrix as is rigorously defined in the
            # OQE formalism, because the power spectrum scalar is excluded
            # in this matrix normalization (i.e., M doesn't do the full
            # normalization)
            M = np.diag(1. / np.sum(G, axis=1))
            W_norm = np.diag(1. / np.sum(H, axis=1))
            W = np.dot(W_norm, H)
        else:
            raise NotImplementedError("Cholesky decomposition mode not currently supported.")
            # # Cholesky decomposition
            # order = np.arange(G.shape[0]) - np.ceil((G.shape[0]-1.)/2.)
            # order[order < 0] = order[order < 0] - 0.1

            # # Negative integers have larger absolute value so they are sorted
            # # after positive integers.
            # order = (np.abs(order)).argsort()
            # if np.mod(G.shape[0], 2) == 1:
            #     endindex = -2
            # else:
            #     endindex = -1
            # order = np.hstack([order[:5], order[endindex:], order[5:endindex]])
            # iorder = np.argsort(order)

            # G_o = np.take(np.take(G, order, axis=0), order, axis=1)
            # L_o = np.linalg.cholesky(G_o)
            # U,S,V = np.linalg.svd(L_o.conj())
            # M_o = np.dot(np.transpose(V), np.dot(np.diag(1./S), np.transpose(U)))
            # M = np.take(np.take(M_o, iorder, axis=0), iorder, axis=1)

        return M, W

    def get_Q(self, mode, n_k):
        """
        Response of the covariance to a given bandpower, dC / dp_alpha.

        Assumes that Q will operate on a visibility vector in frequency space.
        In other words, produces a matrix Q that performs a two-sided Fourier
        transform and extracts a particular Fourier mode.

        (Computing x^t Q y is equivalent to Fourier transforming x and y
        separately, extracting one element of the Fourier transformed vectors,
        and then multiplying them.)

        Parameters
        ----------
        mode : int
            Central wavenumber (index) of the bandpower, p_alpha.

        n_k : int
            Number of k bins that will be used in power spectrum.

        Returns
        -------
        Q : array_like
            Response matrix for bandpower p_alpha.
        """
        _m = np.zeros((n_k,), dtype=np.complex)
        _m[mode] = 1. # delta function at specific delay mode

        # FFT to transform to frequency space
        m = np.fft.fft(np.fft.ifftshift(_m))
        Q = np.einsum('i,j', m, m.conj()) # dot it with its conjugate
        return Q

    def p_hat(self, M, q):
        """
        Optimal estimate of bandpower p_alpha, defined as p_hat = M q_hat.

        Parameters
        ----------
        M : array_like
            Normalization matrix, M.

        q : array_like
            Unnormalized bandpowers, \hat{q}.

        Returns
        -------
        p_hat : array_like
            Optimal estimate of bandpower, \hat{p}.
        """
        return np.dot(M, q)

    def units(self, little_h=True):
        """
        Return the units of the power spectrum. These are inferred from the 
        units reported by the input visibilities (UVData objects).

        Parameters
        ----------
        little_h : boolean, optional
                Whether to have cosmological length units be h^-1 Mpc or Mpc
                Default: h^-1 Mpc

        Returns
        -------
        pspec_units : str
            Units of the power spectrum that is returned by pspec().
        """
        # Work out the power spectrum units
        if len(self.dsets) == 0:
            raise IndexError("No datasets have been added yet; cannot "
                             "calculate power spectrum units.")

        # get visibility units
        vis_units = self.dsets[0].vis_units

        # set pspec norm units
        if self.primary_beam is None:
            norm_units = "Hz str [beam normalization not specified]"
        else:
            if little_h:
                h_unit = "h^-3 "
            else:
                h_unit = ""
            norm_units = "{}Mpc^3".format(h_unit)
        
        return vis_units, norm_units
    
    def delays(self):
        """
        Return an array of delays, tau, corresponding to the bins of the delay 
        power spectrum output by pspec() using self.spw_range to specify the 
        spectral window.
        
        Returns
        -------
        delays : array_like
            Delays, tau. Units: ns.
        """
        # Calculate the delays
        if len(self.dsets) == 0:
            raise IndexError("No datasets have been added yet; cannot "
                             "calculate delays.")
        else:
            return utils.get_delays(self.freqs[self.spw_range[0]:self.spw_range[1]]) * 1e9 # convert to ns    
        
    def scalar(self, pol, taper='none', little_h=True, 
               num_steps=2000, beam=None):
        """
        Computes the scalar function to convert a power spectrum estimate
        in "telescope units" to cosmological units, using self.spw_range to set 
        spectral window.

        See arxiv:1304.4991 and HERA memo #27 for details.

        Parameters
        ----------
        pol: str
                Which polarization to compute the scalar for.
                e.g. 'I', 'Q', 'U', 'V', 'XX', 'YY'...

        taper : str, optional
                Whether a tapering function (e.g. Blackman-Harris) is being
                used in the power spectrum estimation.
                Default: none

        little_h : boolean, optional
                Whether to have cosmological length units be h^-1 Mpc or Mpc
                Default: h^-1 Mpc

        num_steps : int, optional
                Number of steps to use when interpolating primary beams for
                numerical integral
                Default: 10000

        beam : PSpecBeam object
            Option to use a manually-fed PSpecBeam object instead of using 
            self.primary_beam.

        Returns
        -------
        scalar: float
                [\int dnu (\Omega_PP / \Omega_P^2) ( B_PP / B_P^2 ) / (X^2 Y)]^-1
                in h^-3 Mpc^3 or Mpc^3.
        """
        # set spw_range and get freqs
        freqs = self.freqs[self.spw_range[0]:self.spw_range[1]]
        start = freqs[0]
        end = freqs[0] + np.median(np.diff(freqs)) * len(freqs)

        # calculate scalar
        if beam is None:
            scalar = self.primary_beam.compute_pspec_scalar(
                                        start, end, len(freqs), pol=pol,
                                        taper=taper, little_h=little_h, 
                                        num_steps=num_steps)
        else:
            scalar = beam.compute_pspec_scalar(start, end, len(freqs), 
                                               pol=pol, taper=taper, 
                                               little_h=little_h, 
                                               num_steps=num_steps)
        return scalar

    def validate_pol(self, dsets, pol_pair):
        """
        Validate polarization and returns the index of the datasets so that 
        the polarization pair is consistent with the UVData objects.

        Parameters
        ----------
        dsets : length-2 list or length-2 tuple of integers or str
            Contains indices of self.dsets to use in forming power spectra,
            where the first index is for the Left-Hand dataset and second index
            is used for the Right-Hand dataset (see above).

        pol_pair : length-2 tuple of integers or strings
            Contains polarization pair which will be used in estiamting the power 
            spectrum e,g (-5, -5) or  ('xy', 'xy'). Only auto-polarization pairs
            are implemented for the time being.               
    
        Returns
        -------
        valid : boolean
            True if the UVData objects polarizations are consistent with the 
            pol_pair (user specified polarizations) else False.
        """
        err_msg = "polarization must be fed as len-2 tuple of strings or ints"
        assert isinstance(pol_pair, tuple), err_msg

        # convert elements to integers if fed as strings
        if isinstance(pol_pair[0], (str, np.str)):
            pol_pair = (uvutils.polstr2num(pol_pair[0]), pol_pair[1])
        if isinstance(pol_pair[1], (str, np.str)):
            pol_pair = (pol_pair[0], uvutils.polstr2num(pol_pair[1]))

        assert isinstance(pol_pair[0], (int, np.integer)), err_msg
        assert isinstance(pol_pair[1], (int, np.integer)), err_msg
             
        if pol_pair[0] != pol_pair[1]:
            raise NotImplementedError("Only auto/equal polarizations are implement at the moment.") 

        dset_ind1 = self.dset_idx(dsets[0])
        dset_ind2 = self.dset_idx(dsets[1])
        dset1 = self.dsets[dset_ind1]  # first UVData object
        dset2 = self.dsets[dset_ind2]  # second UVData object

        valid = True
        if pol_pair[0] not in dset1.polarization_array:
            print "dset {} does not contain data for polarization {}".format(dset_ind1, pol_pair[0])
            valid = False

        if pol_pair[1] not in dset2.polarization_array:
            print "dset {} does not contain data for polarization {}".format(dset_ind2, pol_pair[1])
            valid = False

        return valid

    def pspec(self, bls1, bls2, dsets, pols, input_data_weight='identity', norm='I', 
              taper='none', little_h=True, spw_ranges=None, verbose=True, 
              history=''):
        """
        Estimate the delay power spectrum from a pair of datasets contained in 
        this object, using the optimal quadratic estimator of arXiv:1502.06016.

        In this formulation, the power spectrum is proportional to the 
        visibility data via
        
        P = M data_{LH} E data_{RH}

        where E contains the data weighting and FT matrices, M is a 
        normalization matrix, and the two separate datasets are denoted as 
        "left-hand" and "right-hand".

        Each power spectrum is generated by taking a baseline (specified by 
        an antenna-pair and polarization key) from bls1 out of dsets[0] and 
        assigning it as data_LH, and a bl from bls2 out of the dsets[1] and 
        assigning it as data_RH.

        If the bl chosen from bls1 is (ant1, ant2) and the bl chosen from bls2 
        is (ant3, ant4), the "baseline-pair" describing their cross 
        multiplication is ((ant1, ant2), (ant3, ant4)).

        Parameters
        ----------
        bls1, bls2 : list
            List of baseline groups, each group being a list of ant-pair tuples.

        dsets : length-2 tuple or list
            Contains indices of self.dsets to use in forming power spectra, 
            where the first index is for the Left-Hand dataset and second index 
            is used for the Right-Hand dataset (see above).
    
        pols : length-2 tuple of strings or integers or list of length-2 tuples of strings or integers
            Contains polarization pairs to use in forming power spectra 
            e.g. ('XX','XX') or [('XX','XX'),('XY','YX')] or list of polarization pairs. 
            Only auto/equal polarization pairs are implemented at the moment. 
            It uses the polarizations of the UVData onjects (specified in dsets)
            by default only if the UVData object consists of equal polarizations.
    
        input_data_weight : str, optional
            String specifying which weighting matrix to apply to the input
            data. See the options in the set_R() method for details. 
            Default: 'identity'.

        norm : str, optional
            String specifying how to choose the normalization matrix, M. See 
            the 'mode' argument of get_MW() for options. Default: 'I'.

        taper : str, optional
            Tapering (window) function to apply to the data. Takes the same
            arguments as aipy.dsp.gen_window(). Default: 'none'.

        little_h : boolean, optional
                Whether to have cosmological length units be h^-1 Mpc or Mpc
                Default: h^-1 Mpc

        spw_ranges : list of tuples, optional
            A list of spectral window channel ranges to select within the total 
            bandwidth of the datasets, each of which forms an independent power 
            spectrum estimate. Example: [(220, 320), (650, 775)].
            Each tuple should contain a start (inclusive) and stop (exclusive) 
            channel used to index the `freq_array` of each dataset. The default 
            (None) is to use the entire band provided in each dataset.
        
        verbose : bool, optional
            If True, print progress, warnings and debugging info to stdout.
        history : str, optional
            history string to attach to UVPSpec object

        Returns
        -------
        uvp : UVPSpec object
            Instance of UVPSpec that holds the output power spectrum data.

        Examples
        --------
        *Example 1:* No grouping; i.e. each baseline is its own group, no 
        brackets needed for each bl. If::
        
            A = (1, 2); B = (2, 3); C = (3, 4); D = (4, 5); E = (5, 6); F = (6, 7)
        
        and::
        
            bls1 = [ A, B, C ]
            bls2 = [ D, E, F ]
        
        then::
        
            blpairs = [ (A, D), (B, E), (C, F) ]

        *Example 2:* Grouping; blpairs come in lists of blgroups, which are 
        considered "grouped" in OQE. 
        If::
        
            bls1 = [ [A, B], [C, D] ]
            bls2 = [ [C, D], [E, F] ]
        
        then::
        
            blpairs = [ [(A, C), (B, D)], [(C, E), (D, F)] ]   
    
        *Example 3:* Mixed grouping; i.e. some blpairs are grouped, others are 
        not. If::
        
            bls1 = [ [A, B], C ]
            bls2 = [ [D, E], F ]
        
        then::
        
            blpairs = [ [(A, D), (B, E)], (C, F)]
        """
        # Validate the input data to make sure it's sensible
        self.validate_datasets(verbose=verbose)

        # Currently the "pspec normalization scalar" doesn't work if a
        # non-identity data weighting AND a non-trivial taper are used
        if taper != 'none' and input_data_weight != 'identity':
            raise_warning("Warning: Scalar power spectrum normalization "
                                  "doesn't work with current implementation "
                                  "if the tapering AND non-identity "
                                  "weighting matrices are both used.", 
                                  verbose=verbose)

        # get datasets
        assert isinstance(dsets, (list, tuple)), "dsets must be fed as length-2 tuple of integers"
        assert len(dsets) == 2, "len(dsets) must be 2"
        assert isinstance(dsets[0], (int, np.int)) and isinstance(dsets[1], (int, np.int)), "dsets must contain integer indices"
        dset1 = self.dsets[self.dset_idx(dsets[0])]
        dset2 = self.dsets[self.dset_idx(dsets[1])]

        # assert form of bls1 and bls2
        assert isinstance(bls1, list), "bls1 and bls2 must be fed as a list of antpair tuples"
        assert isinstance(bls2, list), "bls1 and bls2 must be fed as a list of antpair tuples"
        assert len(bls1) == len(bls2), "length of bls1 must equal length of bls2"
        for i in range(len(bls1)):
            if isinstance(bls1[i], tuple):
                assert isinstance(bls2[i], tuple), "bls1[{}] type must match bls2[{}] type".format(i, i)
            else:
                assert len(bls1[i]) == len(bls2[i]), "len(bls1[{}]) must match len(bls2[{}])".format(i, i)

        # construct list of baseline pairs
        bl_pairs = []
        for i in range(len(bls1)):
            if isinstance(bls1[i], tuple):
                bl_pairs.append( (bls1[i], bls2[i]) )
            elif isinstance(bls1[i], list) and len(bls1[i]) == 1:
                bl_pairs.append( (bls1[i][0], bls2[i][0]) )
            else:
                bl_pairs.append(map(lambda j: (bls1[i][j] , bls2[i][j]), range(len(bls1[i]))))

        # validate bl-pair redundancy
        validate_blpairs(bl_pairs, dset1, dset2, baseline_tol=1.0)

        # configure spectral window selections
        if spw_ranges is None:
            spw_ranges = [(0, self.Nfreqs)]
        else:
            assert np.isclose(map(lambda t: len(t), spw_ranges), 2).all(), "spw_ranges must be fed as a list of length-2 tuples"

        # setup polarization selection
        if isinstance(pols, tuple):
            pols = [pols]

        # convert all polarizations to integers if fed as strings
        _pols = []
        for p in pols:
            if isinstance(p[0], (str, np.str)):
                p = (uvutils.polstr2num(p[0]), p[1])
            if isinstance(p[1], (str, np.str)):
                p = (p[0], uvutils.polstr2num(p[1]))
            _pols.append(p)
        pols = _pols

        # initialize empty lists
        data_array = odict()
        wgt_array = odict()
        integration_array = odict()
        time1 = []
        time2 = []
        lst1 = []
        lst2 = []
        spws = []
        dlys = []
        freqs = []
        sclr_arr = []
        blp_arr = []
        bls_arr = []

        # Loop over spectral windows
        for i in range(len(spw_ranges)):
            # set spectral range
            if verbose:
                print( "\nSetting spectral range: {}".format(spw_ranges[i]))
            self.set_spw(spw_ranges[i])

            # clear covariance cache
            self.clear_cov_cache()
            built_GH = False  # haven't built Gv and Hv matrices in this spw loop yet

            # setup emtpy data arrays
            spw_data = []
            spw_wgts = []
            spw_ints = []
            spw_scalar = []
            spw_pol = []            

            d = self.delays() * 1e-9
            dlys.extend(d)
            spws.extend(np.ones_like(d, np.int) * i)
            freqs.extend(
                dset1.freq_array.flatten()[spw_ranges[i][0]:spw_ranges[i][1]] )

            # Loop over polarizations                
            for j, p in enumerate(pols):
                p_str = tuple(map(lambda _p: uvutils.polnum2str(_p), p))
                if verbose: print( "\nUsing polarization pair: {}".format(p_str))

                # validating polarization pair on UVData objects
                valid = self.validate_pol(dsets, tuple(p))

                if not valid:
                   # storing only one polarization as only equal polarization are allowed at the 
                   # moment and UVPSpec object also understands one polarization
                   print ("Polarization pair: {} failed the validation test, continuing...".format(p_str))
                   continue

                # UVPSpec only takes a single pol currently
                spw_pol.append(p[0]) 
                pol_data = []
                pol_wgts = []
                pol_ints = []

                # Compute scalar to convert "telescope units" to "cosmo units"
                if self.primary_beam is not None:
                    # using zero'th indexed poalrization as cross polarized beam are not yet implemented
                    scalar = self.scalar(p[0], taper=taper, little_h=True)
                else: 
                    raise_warning("Warning: self.primary_beam is not defined, "
                                  "so pspectra are not properly normalized", 
                                  verbose=verbose)
                    scalar = 1.0
                spw_scalar.append(scalar)

                # Loop over baseline pairs
                for k, blp in enumerate(bl_pairs):

                    # assign keys
                    if isinstance(blp, list):
                        # interpet blp as group of baseline-pairs
                        raise NotImplementedError("Baseline lists bls1 and bls2"
                                " must be lists of tuples (not lists of lists"
                                " of tuples).\n"
                                "Use hera_pspec.pspecdata.construct_blpairs()"
                                " to construct appropriately grouped baseline"
                                " lists.")
                        #key1 = [(dsets[0],) + _blp[0] + (p[0],) for _blp in blp]
                        #key2 = [(dsets[1],) + _blp[1] + (p[1],) for _blp in blp]
                    elif isinstance(blp, tuple):
                        # interpret blp as baseline-pair
                        key1 = (dsets[0],) + blp[0] + (p_str[0],)
                        key2 = (dsets[1],) + blp[1] + (p_str[1],)
                        
                    if verbose:
                        print("\n(bl1, bl2) pair: {}\npol: {}".format(blp, tuple(p)))

                    # Set covariance weighting scheme for input data
                    if verbose: print("  Setting weight matrix for input data...")
                    self.set_R(input_data_weight)

                    # Build Fisher matrix
                    if input_data_weight == 'identity' and built_GH:
                        # in this case, all Gv are the same, so skip if already built for this spw!
                        pass
                    else:
                        if verbose: print("  Building G...")
                        print key1, "---", key2
                        Gv = self.get_G(key1, key2)
                        Hv = self.get_H(key1, key2, taper=taper)
                        built_GH = True

                    # Calculate unnormalized bandpowers
                    if verbose: print("  Building q_hat...")
                    qv = self.q_hat(key1, key2, taper=taper)

                    # Normalize power spectrum estimate
                    if verbose: print("  Normalizing power spectrum...")
                    Mv, Wv = self.get_MW(Gv, Hv, mode=norm)
                    pv = self.p_hat(Mv, qv)

                    # Multiply by scalar
                    if self.primary_beam != None:
                        if verbose: print("  Computing and multiplying scalar...")
                        pv *= scalar
                        Mv *= scalar

                    # Get baseline keys
                    if isinstance(blp, list):
                        bl1 = blp[0][0]
                        bl2 = blp[0][1]
                    else:
                        bl1 = blp[0]
                        bl2 = blp[1]

                    # append bls
                    bls_arr.extend([bl1, bl2])

                    # insert pspectra
                    pol_data.extend(pv.T)

                    # get weights
                    wgts1 = self.w(key1).T
                    wgts2 = self.w(key2).T

                    # get average of nsample across frequency axis, weighted by wgts
                    nsamp1 = np.sum(dset1.get_nsamples(bl1 + (p[0],))[:, self.spw_range[0]:self.spw_range[1]] * wgts1, axis=1) / np.sum(wgts1, axis=1).clip(1, np.inf)
                    nsamp2 = np.sum(dset2.get_nsamples(bl2 + (p[1],))[:, self.spw_range[0]:self.spw_range[1]] * wgts2, axis=1) / np.sum(wgts2, axis=1).clip(1, np.inf)

                    # take inverse average of nsamp1 and nsamp2 and multiply by integration time [seconds] to get total integration
                    # inverse avg is done b/c nsamp_1 ~ 1/sigma_1 and nsamp_2 ~ 1/sigma_2 where sigma is a proxy for std of noise
                    pol_ints.extend(1./np.mean([1./nsamp1.clip(1e-10, np.inf), 1./nsamp2.clip(1e-10, np.inf)], axis=0) * dset1.integration_time)

                    # combined weight is geometric mean
                    pol_wgts.extend(np.concatenate([wgts1[:, :, None], wgts2[:, :, None]], axis=2))

                    # insert time and blpair info only once
                    if i < 1 and j < 1:
                        # insert time info
                        inds1 = dset1.antpair2ind(*bl1)
                        inds2 = dset1.antpair2ind(*bl2)
                        time1.extend(dset1.time_array[inds1])
                        time2.extend(dset2.time_array[inds2])
                        lst1.extend(dset1.lst_array[inds1])
                        lst2.extend(dset2.lst_array[inds2])

                        # insert blpair info
                        blp_arr.extend(np.ones_like(inds1, np.int) * uvputils._antnums_to_blpair(blp))

                # insert into data and wgts integrations dictionaries
                spw_data.append(pol_data)
                spw_wgts.append(pol_wgts)
                spw_ints.append(pol_ints)

            # insert into data and integration dictionaries
            spw_data = np.moveaxis(np.array(spw_data), 0, -1)
            spw_wgts = np.moveaxis(np.array(spw_wgts), 0, -1)
            spw_ints = np.moveaxis(np.array(spw_ints), 0, -1)
            data_array[i] = spw_data
            wgt_array[i] = spw_wgts
            integration_array[i] = spw_ints
            sclr_arr.append(spw_scalar)

        # raise error if none of pols are consistent witht the UVData objects
        if len(spw_pol)==0:
            raise ValueError("None of the specified polarization pair match that of the UVData objects")

        # fill uvp object
        uvp = uvpspec.UVPSpec()

        # fill meta-data
        uvp.time_1_array = np.array(time1)
        uvp.time_2_array = np.array(time2)
        uvp.time_avg_array = np.mean([uvp.time_1_array, uvp.time_2_array], axis=0)
        uvp.lst_1_array = np.array(lst1)
        uvp.lst_2_array = np.array(lst2)
        uvp.lst_avg_array = np.mean([np.unwrap(uvp.lst_1_array), np.unwrap(uvp.lst_2_array)], axis=0) % (2*np.pi)
        uvp.blpair_array = np.array(blp_arr)
        uvp.Nblpairs = len(np.unique(blp_arr))
        uvp.Ntimes = len(np.unique(time1))
        uvp.Nblpairts = len(time1)
        bls_arr = sorted(set(bls_arr))
        uvp.bl_array = np.array(map(lambda bl: uvp.antnums_to_bl(bl), bls_arr))
        antpos = dict(zip(dset1.antenna_numbers, dset1.antenna_positions))
        uvp.bl_vecs = np.array(map(lambda bl: antpos[bl[0]] - antpos[bl[1]], bls_arr))
        uvp.Nbls = len(uvp.bl_array)
        uvp.spw_array = np.array(spws)
        uvp.freq_array = np.array(freqs)
        uvp.dly_array = np.array(dlys)
        uvp.Nspws = len(np.unique(spws))
        uvp.Ndlys = len(np.unique(dlys))
        uvp.Nspwdlys = len(spws)
        uvp.Nfreqs = len(np.unique(freqs))
        uvp.pol_array = np.array(spw_pol, np.int)
        uvp.Npols = len(spw_pol)
        uvp.scalar_array = np.array(sclr_arr)
        uvp.channel_width = dset1.channel_width
        uvp.weighting = input_data_weight
        uvp.vis_units, uvp.norm_units = self.units(little_h=little_h)
        uvp.telescope_location = dset1.telescope_location
        filename1 = getattr(dset1.extra_keywords, 'filename', None)
        filename2 = getattr(dset2.extra_keywords, 'filename', None)
        label1 = self.labels[self.dset_idx(dsets[0])]
        label2 = self.labels[self.dset_idx(dsets[1])]
        uvp.labels = np.array([label1, label2], np.str)
        uvp.label_1_array = np.zeros((uvp.Nspws, uvp.Nblpairts, uvp.Npols), np.int)
        uvp.label_2_array = np.ones((uvp.Nspws, uvp.Nblpairts, uvp.Npols), np.int)
        uvp.history = "UVPSpec written on {} with hera_pspec git hash {}\n{}\n" \
                      "dataset1: filename: {}, label: {}, history:\n{}\n{}\n" \
                      "dataset2: filename: {}, label: {}, history:\n{}\n{}\n" \
                      "".format(datetime.datetime.now(), version.git_hash, '-'*20, 
                                filename1, label1, dset1.history, '-'*20, 
                                filename2, label2, dset2.history, '-'*20)
        uvp.taper = taper
        uvp.norm = norm
        
        if self.primary_beam is not None:
            # attach cosmology
            uvp.cosmo = self.primary_beam.cosmo
            # attach beam info
            uvp.beam_freqs = self.primary_beam.beam_freqs
            uvp.OmegaP, uvp.OmegaPP = self.primary_beam.get_Omegas(uvp.pol_array)
            if hasattr(self.primary_beam, 'filename'):
                uvp.beamfile = self.primary_beam.filename

        # fill data arrays
        uvp.data_array = data_array
        uvp.integration_array = integration_array
        uvp.wgt_array = wgt_array
        uvp.nsample_array = dict(map(lambda k: (k, np.ones_like(uvp.integration_array[k], np.float)), uvp.integration_array.keys()))

        # run check
        uvp.check()

        return uvp

    def rephase_to_dset(self, dset_index=0, inplace=True):
        """
        Rephase visibility data in self.dsets to the LST grid of dset[dset_index] 
        using hera_cal.utils.lst_rephase. Each integration in all other dsets is 
        phased to the center of the corresponding LST bin (by index) in dset[dset_index].

        Will only phase if the dataset's phase type is 'drift'. This is because the rephasing
        algorithm assumes the data is drift-phased when applying phasor term.

        Note that PSpecData.Jy_to_mK() must be run after rephase_to_dset(), if one intends
        to use the former capability at any point.

        Parameters
        ----------
        dset_index : int or str
            Index or label of dataset in self.dset to phase other datasets to.

        inplace : bool, optional
            If True, edits data in dsets in-memory. Else, makes a copy of
            dsets, edits data in the copy and returns to user.

        Returns
        -------
        if inplace:
            return new_dsets
        else:
            return None
        """
        # run dataset validation
        self.validate_datasets()

        # assign dsets
        if inplace:
            dsets = self.dsets
        else:
            dsets = copy.deepcopy(self.dsets)
        
        # Parse dset_index
        dset_index = self.dset_idx(dset_index)

        # get LST grid we are phasing to
        lst_grid = []
        lst_array = dsets[dset_index].lst_array.ravel()
        for l in lst_array:
            if l not in lst_grid:
                lst_grid.append(l)
        lst_grid = np.array(lst_grid)

        # get polarization list
        pol_list = dsets[dset_index].polarization_array.tolist()

        # iterate over dsets
        for i, dset in enumerate(dsets):
            # don't rephase dataset we are using as our LST anchor
            if i == dset_index:
                # even though not phasing this dset, must set to match all other 
                # dsets due to phasing-check validation
                dset.phase_type = 'unknown'
                continue

            # skip if dataset is not drift phased
            if dset.phase_type != 'drift':
                print "skipping dataset {} b/c it isn't drift phased".format(i)

            # convert UVData to DataContainers. Note this doesn't make
            # a copy of the data
            (data, flgs, antpos, ants, freqs, times, lsts, 
             pols) = hc.io.load_vis(dset, return_meta=True)

            # make bls dictionary
            bls = dict(map(lambda k: (k, antpos[k[0]] - antpos[k[1]]), data.keys()))

            # Get dlst array
            dlst = lst_grid - lsts

            # get telescope latitude
            lat = dset.telescope_location_lat_lon_alt_degrees[0]

            # rephase
            hc.utils.lst_rephase(data, bls, freqs, dlst, lat=lat)

            # re-insert into dataset
            for j, k in enumerate(data.keys()):
                # get blts indices of basline
                indices = dset.antpair2ind(*k[:2])
                # get index in polarization_array for this polarization
                polind = pol_list.index(hc.io.polstr2num[k[-1]])
                # insert into dset
                dset.data_array[indices, 0, :, polind] = data[k]

            # set phasing in UVData object to unknown b/c there isn't a single
            # consistent phasing for the entire data set.
            dset.phase_type = 'unknown'

        if inplace is False:
            return dsets

    def Jy_to_mK(self, beam=None):
        """
        Convert internal datasets from a Jy-scale to mK scale using a primary beam
        model if available. Note that if you intend to rephase_to_dset(), Jy to mK conversion
        must be done after that step.

        Parameters
        ----------
        beam : 
        """
        # get all unique polarizations of all the datasets
        pols = set(np.ravel([dset.polarization_array for dset in self.dsets]))

        # assign beam
        if beam is None:
            beam = self.primary_beam
        else:
            if self.primary_beam is not None:
                print "Warning: feeding a beam model when self.primary_beam already exists..."

        # assert type of beam
        assert isinstance(beam, pspecbeam.PSpecBeamBase), "beam model must be a subclass of pspecbeam.PSpecBeamBase"

        # iterate over all pols and get conversion factors
        factors = {}
        for p in pols:
            factors[p] = beam.Jy_to_mK(self.freqs, pol=p)

        # iterate over datasets and apply factor
        for i, dset in enumerate(self.dsets):
            # check dset vis units
            if dset.vis_units != 'Jy':
                print "Cannot convert dset {} Jy -> mK because vis_units = {}".format(i, dset.vis_units)
                continue
            for j, p in enumerate(dset.polarization_array):
                dset.data_array[:, :, :, j] *= factors[p][None, None, :]
            dset.vis_units = 'mK'


def construct_blpairs(bls, exclude_auto_bls=False, exclude_permutations=False, group=False, Nblps_per_group=1):
    """
    Construct a list of baseline-pairs from a baseline-group. This function can be used to easily convert a 
    single list of baselines into the input needed by PSpecData.pspec(bls1, bls2, ...).

    Parameters
    ----------
    bls : list of baseline tuples, Ex. [(1, 2), (2, 3), (3, 4)]

    exclude_auto_bls: boolean, if True, exclude all baselines crossed with itself from the final blpairs list

    exclude_permutations : boolean, if True, exclude permutations and only form combinations of the bls list.
        For example, if bls = [1, 2, 3] (note this isn't the proper form of bls, but makes this example clearer)
        and exclude_permutations = False, then blpairs = [11, 12, 13, 21, 22, 23,, 31, 32, 33].
        If however exclude_permutations = True, then blpairs = [11, 12, 13, 22, 23, 33].
        Furthermore, if exclude_auto_bls = True then 11, 22, and 33 would additionally be excluded.   
        
    group : boolean, optional
        if True, group each consecutive Nblps_per_group blpairs into sub-lists

    Nblps_per_group : integer, number of baseline-pairs to put into each sub-group

    Returns (bls1, bls2, blpairs)
    -------
    bls1 : list of baseline tuples from the zeroth index of the blpair

    bls2 : list of baseline tuples from the first index of the blpair

    blpairs : list of blpair tuples
    """
    # assert form
    assert isinstance(bls, list) and isinstance(bls[0], tuple), "bls must be fed as list of baseline tuples"

    # form blpairs w/o explicitly forming auto blpairs
    # however, if there are repeated bl in bls, there will be auto bls in blpairs
    if exclude_permutations:
        blpairs = list(itertools.combinations(bls, 2))
    else:
        blpairs = list(itertools.permutations(bls, 2))

    # explicitly add in auto baseline pairs
    blpairs.extend(zip(bls, bls))

    # iterate through and eliminate all autos if desired
    if exclude_auto_bls:
        new_blpairs = []
        for blp in blpairs:
            if blp[0] != blp[1]:
                new_blpairs.append(blp)
        blpairs = new_blpairs

    # create bls1 and bls2 list
    bls1 = map(lambda blp: blp[0], blpairs)
    bls2 = map(lambda blp: blp[1], blpairs)

    # group baseline pairs if desired
    if group:
        Nblps = len(blpairs)
        Ngrps = int(np.ceil(float(Nblps) / Nblps_per_group))
        new_blps = []
        new_bls1 = []
        new_bls2 = []
        for i in range(Ngrps):
            new_blps.append(blpairs[i*Nblps_per_group:(i+1)*Nblps_per_group])
            new_bls1.append(bls1[i*Nblps_per_group:(i+1)*Nblps_per_group])
            new_bls2.append(bls2[i*Nblps_per_group:(i+1)*Nblps_per_group])

        bls1 = new_bls1
        bls2 = new_bls2
        blpairs = new_blps

    return bls1, bls2, blpairs


def validate_blpairs(blpairs, uvd1, uvd2, baseline_tol=1.0, verbose=True):
    """
    Validate baseline pairings in the blpair list are redundant within the 
    specified tolerance.

    Parameters
    ----------
    blpairs : list of baseline-pair tuples, Ex. [((1,2),(1,2)), ((2,3),(2,3))]
        See docstring of PSpecData.pspec() for details on format.

    uvd1 : pyuvdata.UVData instance containing visibility data that first bl in blpair will draw from

    uvd2 : pyuvdata.UVData instance containing visibility data that second bl in blpair will draw from

    baseline_tol : float, distance tolerance for notion of baseline "redundancy" in meters
    
    verbose : bool, if True report feedback to stdout
    """
    # ensure uvd1 and uvd2 are UVData objects
    if isinstance(uvd1, pyuvdata.UVData) == False:
        raise TypeError("uvd1 must be a pyuvdata.UVData instance")
    if isinstance(uvd2, pyuvdata.UVData) == False:
        raise TypeError("uvd2 must be a pyuvdata.UVData instance")

    # get antenna position dictionary
    ap1, a1 = uvd1.get_ENU_antpos(pick_data_ants=True)
    ap2, a2 = uvd1.get_ENU_antpos(pick_data_ants=True)
    ap1 = dict(zip(a1, ap1))
    ap2 = dict(zip(a2, ap2))

    # ensure shared antenna keys match within tolerance
    shared = sorted(set(ap1.keys()) & set(ap2.keys()))
    for k in shared:
        assert np.linalg.norm(ap1[k] - ap2[k]) <= baseline_tol, "uvd1 and uvd2 don't agree on antenna positions within tolerance of {} m".format(baseline_tol)
    ap = ap1
    ap.update(ap2)

    # iterate through baselines and check baselines crossed with each other are within tolerance
    for i, blg in enumerate(blpairs):
        if isinstance(blg, tuple):
            blg = [blg]
        for blp in blg:
            bl1_vec = ap[blp[0][0]] - ap[blp[0][1]]
            bl2_vec = ap[blp[1][0]] - ap[blp[1][1]]
            if np.linalg.norm(bl1_vec - bl2_vec) >= baseline_tol:
                raise_warning("blpair {} exceeds redundancy tolerance of {} m".format(blp, baseline_tol), verbose=verbose)

def raise_warning(warning, verbose=True):
    '''warning function'''
    if verbose:
        print(warning)
