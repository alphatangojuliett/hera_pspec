import numpy as np
import aipy
import pyuvdata
from hera_pspec.utils import hash, cov
import itertools
import copy
import hera_cal as hc



class PSpecData(object):

    def __init__(self, dsets=[], wgts=[], beam=None):
        """
        Object to store multiple sets of UVData visibilities and perform
        operations such as power spectrum estimation on them.

        Parameters
        ----------
        dsets : List of UVData objects, optional
            List of UVData objects containing the data that will be used to
            compute the power spectrum. Default: Empty list.

        wgts : List of UVData objects, optional
            List of UVData objects containing weights for the input data.
            Default: Empty list.

        beam : PspecBeam object, optional
            PspecBeam object containing information about the primary beam
            Default: None.
        """
        self.clear_cov_cache()  # Covariance matrix cache
        self.dsets = []; self.wgts = []
        self.Nfreqs = None
        
        # Set R to identity by default
        self.R = self.I

        # Store the input UVData objects if specified
        if len(dsets) > 0:
            self.add(dsets, wgts)

        # Store a primary beam
        self.primary_beam = beam


    def add(self, dsets, wgts):
        """
        Add a dataset to the collection in this PSpecData object.

        Parameters
        ----------
        dsets : UVData or list
            UVData object or list of UVData objects containing data to add to
            the collection.

        wgts : UVData or list
            UVData object or list of UVData objects containing weights to add
            to the collection. Must be the same length as dsets. If a weight is
            set to None, the flags of the corresponding
        """
        # Convert input args to lists if possible
        if isinstance(dsets, pyuvdata.UVData): dsets = [dsets,]
        if isinstance(wgts, pyuvdata.UVData): wgts = [wgts,]
        if wgts is None: wgts = [wgts,]
        if isinstance(dsets, tuple): dsets = list(dsets)
        if isinstance(wgts, tuple): wgts = list(wgts)

        # Only allow UVData or lists
        if not isinstance(dsets, list) or not isinstance(wgts, list):
            raise TypeError("dsets and wgts must be UVData or lists of UVData")

        # Make sure enough weights were specified
        assert(len(dsets) == len(wgts))

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

        # Store no. frequencies and no. times
        self.Nfreqs = self.dsets[0].Nfreqs
        self.Ntimes = self.dsets[0].Ntimes
        
        # Store the actual frequencies
        self.freqs = self.dsets[0].freq_array[0]
        
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

        # Check for the same polarizations
        pols = []
        for d in self.dsets: pols.extend(d.polarization_array)
        pols = np.unique(pols)
        if np.unique(pols).size > 1:
            raise ValueError("all dsets must have the same number and kind of polarizations: \n{}".format(pols))

    def check_key_in_dsets(self, key):
        """
        Check 'key' exists in all UVData objects in self.dsets

        Parameters
        ----------
        key : tuple
            if length 1: assumed to be polarization number or string
            elif length 2: assumed to be antenna-number tuple (ant1, ant2)
            elif length 3: assuemd ot be antenna-number-polarization tuple (ant1, ant2, pol)

        Returns
        -------
        exists : bool
            True if the key exists in all dsets, False otherwise
        """
        # get iterable
        key = pyuvdata.utils.get_iterable(key)
        if isinstance(key, str):
            key = (key,)

        # check key is a tuple
        if isinstance(key, tuple) == False or len(key) not in (1, 2, 3):
            raise KeyError("key {} must be a length 1, 2 or 3 tuple".format(key))

        # start exists as False in case len(self.dsets) == 0
        exists = False
        # loop over all dsets
        for i, dset in enumerate(self.dsets):
            try:
                _ = dset._key2inds(key)
            except KeyError:
                break

            # if loop survived all dsets, the key exists in all dsets
            if i+1 == len(self.dsets):
                exists = True

        return exists

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
            self._C, self._Cempirical, self._I, self._iC = {}, {}, {}, {}
            self._iCt = {}
        else:
            for k in keys:
                try: del(self._C[k])
                except(KeyError): pass
                try: del(self._Cempirical[k])
                except(KeyError): pass
                try: del(self._I[k])
                except(KeyError): pass
                try: del(self._iC[k])
                except(KeyError): pass

    def x(self, key):
        """
        Get data for a given dataset and baseline, as specified in a standard
        key format.

        Parameters
        ----------
        key : tuple
            Tuple containing dataset ID and baseline index. The first element
            of the tuple is the dataset index, and the subsequent elements are
            the baseline ID.

        Returns
        -------
        x : array_like
            Array of data from the requested UVData dataset and baseline.
        """
        assert isinstance(key, tuple)
        dset = key[0]; bl = key[1:]
        return self.dsets[dset].get_data(bl).T # FIXME: Transpose?

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
        assert isinstance(key, tuple)

        dset = key[0]; bl = key[1:]
        
        if self.wgts[dset] is not None:
            return self.wgts[dset].get_data(bl).T # FIXME: Transpose?
        else:
            # If weights were not specified, use the flags built in to the
            # UVData dataset object
            flags = self.dsets[dset].get_flags(bl).astype(float).T
            return 1. - flags # Flag=1 => weight=0

    def C(self, key):
        """
        Estimate covariance matrices from the data.

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        Returns
        -------
        C : array_like
            (Weighted) empirical covariance of data for baseline 'bl'.
        """
        assert isinstance(key, tuple)

        # Set covariance if it's not in the cache
        if not self._C.has_key(key):
            self.set_C( {key : cov(self.x(key), self.w(key))} )
            self._Cempirical[key] = self._C[key]

        # Return cached covariance
        return self._C[key]

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

    def C_empirical(self, key):
        """
        Calculate empirical covariance from the data (with appropriate
        weighting).

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        Returns
        -------
        C_empirical : array_like
            Empirical covariance for the specified key.
        """
        assert isinstance(key, tuple)

        # Check cache for empirical covariance
        if not self._Cempirical.has_key(key):
            self._Cempirical[key] = cov(self.x(key), self.w(key))
        return self._Cempirical[key]

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

        if not self._I.has_key(key):
            self._I[key] = np.identity(self.Nfreqs)
        return self._I[key]

    def iC(self, key):
        """
        Return the inverse covariance matrix, C^-1.

        Parameters
        ----------
        key : tuple
            Tuple containing indices of dataset and baselines. The first item
            specifies the index (ID) of a dataset in the collection, while
            subsequent indices specify the baseline index, in _key2inds format.

        Returns
        -------
        iC : array_like
            Inverse covariance matrix for specified dataset and baseline.
        """
        assert isinstance(key, tuple)

        # Calculate inverse covariance if not in cache
        if not self._iC.has_key(key):
            C = self.C(key)
            U,S,V = np.linalg.svd(C.conj()) # conj in advance of next step

            # FIXME: Not sure what these are supposed to do
            #if self.lmin is not None: S += self.lmin # ensure invertibility
            #if self.lmode is not None: S += S[self.lmode-1]

            # FIXME: Is series of dot products quicker?
            self.set_iC({key:np.einsum('ij,j,jk', V.T, 1./S, U.T)})
        return self._iC[key]

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

    def q_hat(self, key1, key2, use_fft=True, taper='none'):
        """
        Construct an unnormalized bandpower, q_hat, from a given pair of
        visibility vectors. Returns the following quantity:

          \hat{q}_a = (1/2) conj(x_1) R_1 Q_a R_2 x_2 (arXiv:1502.06016, Eq. 13)

        Note that the R matrix need not be set to C^-1. This is something that
        is set by the user in the set_R method.

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
                tapering_fct = aipy.dsp.gen_window(self.Nfreqs, taper)
                Rx1 *= tapering_fct
                Rx2 *= tapering_fct

            _Rx1 = np.fft.fft(Rx1.conj(), axis=0)
            _Rx2 = np.fft.fft(Rx2.conj(), axis=0)
            
            return 0.5 * np.conj(  np.fft.fftshift(_Rx1, axes=0).conj() 
                                 * np.fft.fftshift(_Rx2, axes=0) )
        else:
            # Slow method, used to explicitly cross-check FFT code
            q = []
            for i in xrange(self.Nfreqs):
                Q = self.get_Q(i, self.Nfreqs, taper=taper)
                RQR = np.einsum('ab,bc,cd',
                                self.R(key1).T.conj(), Q, self.R(key2))
                qi = np.sum(self.x(key1).conj()*np.dot(RQR, self.x(key2)), axis=0)
                q.append(qi)
            return 0.5 * np.array(q)

    def get_G(self, key1, key2, taper='none'):
        """
        Calculates the response matrix G of the unnormalized band powers q
        to the true band powers p, i.e.,

            <q_a> = \sum_b G_{ab} p_b

        This is given by

            G_ab = (1/2) Tr[R_1 Q_a R_2 Q_b]

        Note that in the limit that R_1 = R_2 = C^-1, this reduces to the Fisher
        matrix

            F_ab = 1/2 Tr [C^-1 Q_a C^-1 Q_b] (arXiv:1502.06016, Eq. 17)

        Parameters
        ----------
        key1, key2 : tuples or lists of tuples
            Tuples containing indices of dataset and baselines for the two 
            input datavectors. If a list of tuples is provided, the baselines 
            in the list will be combined with inverse noise weights.

        taper : str, optional
            Tapering (window) function used when calculating Q. Takes the same
            arguments as aipy.dsp.gen_window(). Default: 'none'.

        Returns
        -------
        G : array_like, complex
            Fisher matrix, with dimensions (Nfreqs, Nfreqs).
        """
        G = np.zeros((self.Nfreqs, self.Nfreqs), dtype=np.complex)
        R1 = self.R(key1)
        R2 = self.R(key2)

        iR1Q, iR2Q = {}, {}
        for ch in xrange(self.Nfreqs): # this loop is nchan^3
            Q = self.get_Q(ch, self.Nfreqs, taper=taper)
            iR1Q[ch] = np.dot(R1, Q) # R_1 Q
            iR2Q[ch] = np.dot(R2, Q) # R_2 Q

        for i in xrange(self.Nfreqs): # this loop goes as nchan^4
            for j in xrange(self.Nfreqs):
                # tr(R_2 Q_i R_1 Q_j)
                G[i,j] += np.einsum('ab,ba', iR1Q[i], iR2Q[j])

        return G / 2.
    
    
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
    
    
    def get_MW(self, G, mode='I'):
        """
        Construct the normalization matrix M and window function matrix W for
        the power spectrum estimator. These are defined through Eqs. 14-16 of
        arXiv:1502.06016:

            \hat{p} = M \hat{q}
            <\hat{p}> = W p
            W = M G,

        where p is the true band power and G is the response matrix (defined above
        in get_G) of unnormalized bandpowers to normed bandpowers. The G matrix
        is the Fisher matrix when R = C^-1

        Several choices for M are supported:

            'G^-1':   Set M = G^-1, the (pseudo)inverse response matrix.
            'G^-1/2': Set M = G^-1/2, the root-inverse response matrix (using SVD).
            'I':      Set M = I, the identity matrix.
            'L^-1':   Set M = L^-1, Cholesky decomposition.

        Note that when we say (e.g., M = I), we mean this before normalization.
        The M matrix needs to be normalized such that each row of W sums to 1.

        Parameters
        ----------
        G : array_like or dict of array_like
            Response matrix for the bandpowers, with dimensions (Nfreqs, Nfreqs).
            If a dict is specified, M and W will be calculated for each G
            matrix in the dict.

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
        # Recursive case, if many G's were specified at once
        if type(G) is dict:
            M,W = {}, {}
            for key in G: M[key], W[key] = self.get_MW(G[key], mode=mode)
            return M, W

        # Check that mode is supported
        modes = ['G^-1', 'G^-1/2', 'I', 'L^-1']
        assert(mode in modes)

        # Build M matrix according to specified mode
        if mode == 'G^-1':
            M = np.linalg.pinv(G, rcond=1e-12)
            #U,S,V = np.linalg.svd(F)
            #M = np.einsum('ij,j,jk', V.T, 1./S, U.T)

        elif mode == 'G^-1/2':
            U,S,V = np.linalg.svd(G)
            M = np.einsum('ij,j,jk', V.T, 1./np.sqrt(S), U.T)

        elif mode == 'I':
            M = np.identity(G.shape[0], dtype=G.dtype)

        else:
            # Cholesky decomposition
            order = np.arange(G.shape[0]) - np.ceil((G.shape[0]-1.)/2.)
            order[order < 0] = order[order < 0] - 0.1

            # Negative integers have larger absolute value so they are sorted
            # after positive integers.
            order = (np.abs(order)).argsort()
            if np.mod(G.shape[0], 2) == 1:
                endindex = -2
            else:
                endindex = -1
            order = np.hstack([order[:5], order[endindex:], order[5:endindex]])
            iorder = np.argsort(order)

            G_o = np.take(np.take(G, order, axis=0), order, axis=1)
            L_o = np.linalg.cholesky(G_o)
            U,S,V = np.linalg.svd(L_o.conj())
            M_o = np.dot(np.transpose(V), np.dot(np.diag(1./S), np.transpose(U)))
            M = np.take(np.take(M_o, iorder, axis=0), iorder, axis=1)

        # Calculate (normalized) W given Fisher matrix and choice of M
        W = np.dot(M, G)
        norm = W.sum(axis=-1); norm.shape += (1,)
        M /= norm; W = np.dot(M, G)
        return M, W

    def get_Q(self, mode, n_k, taper='none'):
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
            Number of k bins that will be .

        taper : str, optional
            Type of tapering (window) function to use. Valid options are any
            window function supported by aipy.dsp.gen_window(). Default: 'none'.

        Returns
        -------
        Q : array_like
            Response matrix for bandpower p_alpha.
        """
        _m = np.zeros((n_k,), dtype=np.complex)
        _m[mode] = 1. # delta function at specific delay mode

        # FFT to transform to frequency space, and apply window function
        m = np.fft.fft(np.fft.ifftshift(_m)) * aipy.dsp.gen_window(n_k, taper)
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
    
    
    def units(self):
        """
        Return the units of the power spectrum. These are inferred from the 
        units reported by the input visibilities (UVData objects).

        Returns
        -------
        pspec_units : str
            Units of the power spectrum that is returned by pspec().
        
        delay_units : str
            Units of the delays (wavenumbers) returned by pspec().
        """
        # Frequency units of UVData are always Hz => always convert to ns
        delay_units = 'ns'
        
        # Work out the power spectrum units
        if len(self.dsets) == 0:
            raise IndexError("No datasets have been added yet; cannot "
                             "calculate power spectrum units.")
        else:
            pspec_units = "(%s)^2 (ns)^-1" % self.dsets[0].vis_units
        
        return pspec_units, delay_units
        
    
    def delays(self):
        """
        Return an array of delays, tau, corresponding to the bins of the delay 
        power spectrum output by pspec().
        
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
            nu = self.dsets[0].freq_array[0] # always in Hz
            delay = np.fft.fftfreq(nu.size, d=nu[1]-nu[0])
            return delay * 1e9 # convert to ns
    
    
    def scalar(self, stokes='pseudo_I', taper='none', little_h=True, num_steps=2000, beam=None):
        """
        Computes the scalar function to convert a power spectrum estimate
        in "telescope units" to cosmological units

        See arxiv:1304.4991 and HERA memo #27 for details.

        Currently this is only for Stokes I.

        Parameters
        ----------
        stokes: str, optional
                Which Stokes parameter's beam to compute the scalar for.
                'I', 'Q', 'U', 'V', although currently only 'I' is implemented
                Default: 'I'

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
            Option to use a manually-fed PSpecBeam object instead of using self.primary_beam.

        Returns
        -------
        scalar: float
                [\int dnu (\Omega_PP / \Omega_P^2) ( B_PP / B_P^2 ) / (X^2 Y)]^-1
                in h^-3 Mpc^3 or Mpc^3.
        """
        if beam is None:
            scalar = self.primary_beam.compute_pspec_scalar(self.freqs[0], self.freqs[-1], len(self.freqs), stokes=stokes,
                                                            taper=taper, little_h=little_h, num_steps=num_steps)
        else:
            scalar = beam.compute_pspec_scalar(self.freqs[0], self.freqs[-1], len(self.freqs), stokes=stokes,
                                                            taper=taper, little_h=little_h, num_steps=num_steps)

        return scalar

    def pspec(self, bls, input_data_weight='identity', norm='I', taper='none', little_h=True, 
              add_reverse_bl_pairs=False, enforce_bl_cross=True, average_bl_group=False, verbose=True):
        """
        Estimate the delay power spectrum from the datasets contained in this 
        object, using the optimal quadratic estimator from arXiv:1502.06016.

        Parameters
        ----------
        bls : list of tuples (or list of lists of tuples)
            List of baseline tuples to use in the power spectrum calculation. 
            Each baseline is specified as a tuple of antenna numbers: (ant1_num, ant2_num)
            
            Alternatively, bls can contain multiple lists of baselines, which are each interpreted
            as a redundant baseline group. In this case, pspec will do one of two things:

                1) The bl in each baseline-group are averaged together before squaring (average_bl_group=True),
                   reducing the number of cross-correlations needed.
                2) All N_choose_2 cross-spectra between bls in a group are calculated (average_bl_group=False)

            If add_reverse_bl_pairs == True, bl-pairs with conjugated baseline pair is added to the bl group.
            If enforce_bl_cross == True, all baselines crossed with itself are eliminated.

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

        add_reverse_bl_pairs : boolean, optional
            If bls is a list of redundant bl groups, conjugated bl-pairs are added to each group.

        enforce_bl_cross : boolean, optional
            If bls is a list of redundant bl groups, enforces that a bl is never paired with itself.

        average_bl_group : boolean, optional
            If bls is a list of redundant bl groups, average data in each group before squaring.

        verbose : bool, optional
            If True, print progress, warnings and debugging info to stdout.

        Returns
        -------
        pspec : list of np.ndarray
            Optimal quadratic estimate of the delay power spectrum for the 
            datasets stored in this PSpecData and baselines specified in 
            'keys'. Units: given by the units() method.
        
        pairs : list of tuples
            List of the pairs of datasets and baselines that were used to
            calculate each element of the 'pspec' list.
        """
        # Validate the input data to make sure it's sensible
        self.validate_datasets(verbose=verbose)

        # get polarization array from zero'th dset
        pol_arr = map(lambda p: pyuvdata.utils.polnum2str(p), self.dsets[0].polarization_array)


        # Compute the scalar to convert from "telescope units" to "cosmo units"
        # once and for all
        if self.primary_beam is not None:
            scalar = self.scalar(taper=taper, little_h=True)
        else: raise_warning("Warning: self.primary_beam is not defined, so pspectra are not properly normalized", verbose=verbose)

        # construct list of baseline pairs
        bl_pairs = []
        if isinstance(bls[0], tuple) and isinstance(bls[0][0], (int, np.int, np.int32)):
            # assume bls is a list of tuple antenna pairs
            # in which case we take a bl crossed with itself
            bls = map(lambda bl: (bl, bl), bls)
            fed_redundant_bls = False

        elif isinstance(bls[0], list) and isinstance(bls[0][0], tuple) and isinstance(bls[0][0][0], (int, np.int, np.int32)):
            # assume bls is a list of redundant baseline groups, in which case
            # we take all N choose 2 combinations with replacement within each baseline group.
            # this includes a baseline being crossed with itself, which will lead to a bias
            # unless the data in each dset is from a different night / LST, or the
            # enforce_cross_bl option is set (by default).
            red_bls = copy.copy(bls)
            bls = map(lambda bl_group: list(itertools.combinations_with_replacement(bl_group, 2)), bls)
            bls = [item for sublist in bls for item in sublist]
            fed_redundant_bls = True
        else:
            raise ValueError("could not parse format of bls. must be fed as a list of tuples, " \
                             "or a list of lists of tuples.")

        # iterate through all bl_groups and ensure bl_pair exists in all dsets, else remove bl_pair
        new_bls = []
        for i, bl_pair in enumerate(bls):
            if self.check_key_in_dsets(bl_pair[0]) and self.check_key_in_dsets(bl_pair[1]):
                new_bls.append(bl_pair)
        bls = new_bls

        if reverse_bl_pairing:
            # adds extra bl_pairs having reversed baseline pair ordering
            new_bls = copy.copy(bls)
            for i, bl_pair in enumerate(bls):
                if bl_pair[0] != bl_pair[1]:
                    new_bls.append(bl_pair[::-1])
            bls = new_bls

        if enforce_cross_bl and fed_redundant_bls:
            # eliminate all instances of a bl paired w/ itself
            new_bls = []
            for i, bl_pair in enumerate(bls):
                if bl_pair[0] != bl_pair[1]:
                    new_bls.append(bl_pair)
            bls = new_bls

        # construct empty output lists
        pspecs = []
        pairs = []

        # Loop over pairs of datasets
        for m in xrange(len(self.dsets)):
            for n in xrange(m+1, len(self.dsets)):
                # Datasets should not be cross-correlated with themselves, and
                # dataset pair (m, n) gives the same result as (n, m)

                # Loop over baselines
                for bl in bls:
                    if isinstance(bl, list):
                        key1 = [(m,) + _bl for _bl in bl]
                        key2 = [(n,) + _bl for _bl in bl]
                    else:
                        key1 = (m,) + bl
                        key2 = (n,) + bl
                    if verbose: print("Baselines:", key1, key2)

                    # Set covariance weighting scheme for input data
                    if verbose: print("  Setting weight matrix for input data...")
                    self.set_R(input_data_weight)

                    # Build Fisher matrix
                    if verbose: print("  Building G...")
                    Gv = self.get_G(key1, key2, taper=taper)

                    # Calculate unnormalized bandpowers
                    if verbose: print("  Building q_hat...")
                    qv = self.q_hat(key1, key2, taper=taper)

                    # Normalize power spectrum estimate
                    if verbose: print("  Normalizing power spectrum...")
                    Mv, Wv = self.get_MW(Gv, mode=norm)
                    pv = self.p_hat(Mv, qv)
                    
                    # Multiply by scalar
                    if self.primary_beam != None:
                        if verbose: print("  Computing and multiplying scalar...")
                        pv *= scalar

                    # Save power spectra and dataset/baseline pairs
                    pvs.append(pv)
                    pairs.append((key1, key2))
                    
        return np.array(pvs), pairs

    def rephase_to_dset(self, dset_index=0, inplace=True):
        """
        Rephase visibility data in self.dsets to the LST grid of dset[dset_index] 
        using hera_cal.utils.lst_rephase. 

        Each integration in all other dsets are phased to the center of the 
        corresponding LST bin (by index) in dset[dset_index].

        Parameters
        ----------
        dset_index : int
            index of dataset in self.dset to phase other datasets to.

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
                continue

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
            
def raise_warning(warning, verbose=True):
    '''warning function'''
    if verbose:
        print(warning)
