import numpy as np
import md5
import yaml
from conversions import Cosmo_Conversions
import traceback
import operator
from hera_cal import redcal
import itertools
import argparse
import glob
import os
import aipy
from collections import OrderedDict as odict
from pyuvdata import utils as uvutils
from pyuvdata import UVData


def hash(w):
    """
    Return an MD5 hash of a set of weights.
    """
    DeprecationWarning("utils.hash is deprecated.")
    return md5.md5(w.copy(order='C')).digest()

def cov(d1, w1, d2=None, w2=None, conj_1=False, conj_2=True):
    """
    Computes an empirical covariance matrix from data vectors. If d1 is of size 
    (M,N), then the output is M x M. In other words, the second axis is the 
    axis that is averaged over in forming the covariance (e.g. a time axis).

    If d2 is provided and d1 != d2, then this computes the cross-variance, 
    i.e. <d1 d2^dagger> - <d1> <d2>^dagger

    The fact that the second copy is complex conjugated is the default behaviour,
    which can be altered by the conj_1 and the conj_2 kwargs. If conj_1 = False
    and conj_2 = False, then <d1 d2^t> is computed, whereas if conj_1 = True
    and conj_2 = True, then <d1^* d2^t*> is computed. (Minus the mean terms).

    Parameters
    ----------
    d1 : array_like
        Data vector of size (M,N), where N is the length of the "averaging axis"
    w1 : integer
        Weights for averaging d1
    d2 : array_like, optional
        Data vector of size (M,N), where N is the length of the "averaging axis"
        Default: None
    w2 : integer, optional
        Weights for averaging d1. Default: None
    conj_1 : boolean, optional
        Whether to conjugate d1 or not. Default: False
    conj_2 : boolean, optional
        Whether to conjugate d2 or not. Default: True

    Returns
    -------
    cov : array_like
        Covariance (or cross-variance) matrix of size (M,M)
    """
    if d2 is None: d2,w2 = d1,w1
    if not np.isreal(w1).all(): raise TypeError("Weight matrices must be real")
    if not np.isreal(w2).all(): raise TypeError("Weight matrices must be real")
    if np.less(w1, 0.).any() or np.less(w2, 0.).any(): 
        raise ValueError("Weight matrices must be positive")
    d1sum,d1wgt = (w1*d1).sum(axis=1), w1.sum(axis=1)
    d2sum,d2wgt = (w2*d2).sum(axis=1), w2.sum(axis=1)
    x1 = d1sum / np.where(d1wgt > 0, d1wgt, 1)
    x2 = d2sum / np.where(d2wgt > 0, d2wgt, 1)
    x1.shape = (-1,1); x2.shape = (-1,1)

    z1 = w1*d1
    z2 = w2*d2

    if conj_1:
        z1 = z1.conj()
        x1 = x1.conj()
    if conj_2:
        z2 = z2.conj()
        x2 = x2.conj()
    
    C = np.dot(z1, z2.T)
    W = np.dot(w1, w2.T)
    C /= np.where(W > 0, W, 1)
    C -= np.outer(x1, x2)
    return C

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


def calc_reds(uvd1, uvd2, bl_tol=1.0, filter_blpairs=True, xant_flag_thresh=0.95, exclude_auto_bls=True, 
              exclude_permutations=True, Nblps_per_group=None, bl_len_range=(0, 1e10), bl_deg_range=(0, 180)):
    """
    Use hera_cal.redcal to get matching redundant baselines groups from uvd1 and uvd2
    within the specified baseline tolerance, not including flagged ants.

    Parameters
    ----------
    uvd1 : UVData instance with visibility data

    uvd2 : UVData instance with visibility data

    bl_tol : float, optional
        Baseline-vector redundancy tolerance in meters
    
    filter_blpairs : bool, optional
        if True, calculate xants and filters-out baseline pairs based on xant lists
        and baselines in the data.

    xant_flag_thresh : float, optional
        Fraction of 2D visibility (per-waterfall) needed to be flagged to 
        consider the entire visibility flagged.

    exclude_auto_bls: boolean, optional
        If True, exclude all bls crossed with itself from the blpairs list

    exclude_permutations : boolean, optional
        if True, exclude permutations and only form combinations of the bls list.
        For example, if bls = [1, 2, 3] (note this isn't the proper form of bls, 
        but makes this example clearer) and exclude_permutations = False, 
        then blpairs = [11, 12, 13, 21, 22, 23, 31, 32, 33]. If however 
        exclude_permutations = True, then blpairs = [11, 12, 13, 22, 23, 33]. 
        Furthermore, if exclude_auto_bls = True then 11, 22, and 33 are excluded.   
        
    Nblps_per_group : integer
        Number of baseline-pairs to put into each sub-group. No grouping if None.
        Default: None

    bl_len_range : tuple, optional
        len-2 tuple containing minimum baseline length and maximum baseline length [meters]
        to keep in baseline type selection

    bl_deg_range : tuple, optional
        len-2 tuple containing (minimum, maximum) baseline angle in degrees to keep in
        baseline selection

    Returns
    -------
    baselines1 : list of baseline tuples
        Contains list of baseline tuples that should be fed as first argument
        to PSpecData.pspec(), corresponding to uvd1

    baselines2 : list of baseline tuples
        Contains list of baseline tuples that should be fed as second argument
        to PSpecData.pspec(), corresponding to uvd2

    blpairs : list of baseline-pair tuples
        Contains the baseline-pair tuples. i.e. zip(baselines1, baselines2)

    xants1 : list of bad antenna integers for uvd1

    xants2 : list of bad antenna integers for uvd2
    """
    # get antenna positions
    antpos1, ants1 = uvd1.get_ENU_antpos(pick_data_ants=False)
    antpos1 = dict(zip(ants1, antpos1))
    antpos2, ants2 = uvd2.get_ENU_antpos(pick_data_ants=False)
    antpos2 = dict(zip(ants2, antpos2))
    antpos = dict(antpos1.items() + antpos2.items())

    # assert antenna positions match
    for a in set(antpos1).union(set(antpos2)):
        if a in antpos1 and a in antpos2:
            msg = "antenna positions from uvd1 and uvd2 do not agree to within " \
                  "tolerance of {} m".format(bl_tol)
            assert np.linalg.norm(antpos1[a] - antpos2[a]) < bl_tol, msg

    # get xants
    xants1, xants2 = [], []
    if filter_blpairs:
        xants1, xants2 = set(ants1), set(ants2)
        baselines = sorted(set(uvd1.baseline_array).union(set(uvd2.baseline_array)))
        for bl in baselines:
            # get antenna numbers
            antnums = uvd1.baseline_to_antnums(bl)

            # continue if autocorr
            if antnums[0] == antnums[1]: continue

            # work on xants1
            if bl in uvd1.baseline_array:
                # get flags
                f1 = uvd1.get_flags(bl)
                # remove from bad list if unflagged data exists
                if np.sum(f1) < reduce(operator.mul, f1.shape) * xant_flag_thresh:
                    if antnums[0] in xants1:
                        xants1.remove(antnums[0])
                    if antnums[1] in xants2:
                        xants1.remove(antnums[1])

            # work on xants2
            if bl in uvd2.baseline_array:
                # get flags
                f2 = uvd2.get_flags(bl)
                # remove from bad list if unflagged data exists
                if np.sum(f2) < reduce(operator.mul, f2.shape) * xant_flag_thresh:
                    if antnums[0] in xants2:
                        xants2.remove(antnums[0])
                    if antnums[1] in xants2:
                        xants2.remove(antnums[1])

        xants1 = sorted(xants1)
        xants2 = sorted(xants2)

    # get reds
    reds = redcal.get_pos_reds(antpos, bl_error_tol=bl_tol, low_hi=True)

    # construct baseline pairs
    baselines1, baselines2, blpairs = [], [], []
    for r in reds:
        (_bls1, _bls2, 
         _blps) = construct_blpairs(r, exclude_auto_bls=exclude_auto_bls, group=False,
                                    exclude_permutations=exclude_permutations)

        # filter based on xants, existance in uvd1 and uvd2 and bl_len_range
        bls1, bls2 = [], []
        for bl1, bl2 in _blps:
            # get baseline length and angle
            bl1i = uvd1.antnums_to_baseline(*bl1)
            bl2i = uvd1.antnums_to_baseline(*bl2)
            bl1v = (antpos[bl1[0]] - antpos[bl1[1]])[:2]
            bl2v = (antpos[bl2[0]] - antpos[bl2[1]])[:2]
            bl1_len, bl2_len = np.linalg.norm(bl1v), np.linalg.norm(bl2v)
            bl1_deg = np.arctan2(*bl1v[::-1]) * 180 / np.pi
            if bl1_deg < 0: bl1_deg = (bl1_deg + 180) % 360
            bl2_deg = np.arctan2(*bl2v[::-1]) * 180 / np.pi
            if bl2_deg < 0: bl2_deg = (bl2_deg + 180) % 360
            bl_len = np.mean([bl1_len, bl2_len])
            bl_deg = np.mean([bl1_deg, bl2_deg])
            # filter based on length cut
            if bl_len < bl_len_range[0] or bl_len > bl_len_range[1]:
                continue
            # filter based on angle cut
            if bl_deg < bl_deg_range[0] or bl_deg > bl_deg_range[1]:
                continue
            # filter on other things
            if filter_blpairs:
                if (bl1i not in uvd1.baseline_array or bl1[0] in xants1 or bl1[1] in xants1) \
                   or (bl2i not in uvd2.baseline_array or bl2[0] in xants2 or bl2[1] in xants2):
                   continue
            bls1.append(bl1)
            bls2.append(bl2)

        if len(bls1) < 1:
            continue

        blps = zip(bls1, bls2)

        # group if desired
        if Nblps_per_group is not None:
            Ngrps = int(np.ceil(float(len(blps)) / Nblps_per_group))
            bls1 = [bls1[Nblps_per_group*i:Nblps_per_group*(i+1)] for i in range(Ngrps)]
            bls2 = [bls2[Nblps_per_group*i:Nblps_per_group*(i+1)] for i in range(Ngrps)]
            blps = [blps[Nblps_per_group*i:Nblps_per_group*(i+1)] for i in range(Ngrps)]

        baselines1.extend(bls1)
        baselines2.extend(bls2)
        blpairs.extend(blps)

    return baselines1, baselines2, blpairs, xants1, xants2


def get_delays(freqs, n_dlys=None):
    """
    Return an array of delays, tau, corresponding to the bins of the delay 
    power spectrum given by frequency array.
    
    Parameters
    ----------
    freqs : ndarray of frequencies in Hz

    n_dlys : number of delay bins, optional
        Default: None, which then assumes that the number of bins is
        equal to the number of frequency channels.

    Returns
    -------
    delays : array_like
        Delays, tau. Units: seconds.
    """
    Delta_nu = np.median(np.diff(freqs))
    n_freqs = freqs.size

    if n_dlys == None: # assume that n_dlys = n_freqs if not specified
        n_dlys = n_freqs

    # Calculate the delays
    delay = np.fft.fftshift(np.fft.fftfreq(n_dlys, d=Delta_nu))

    return delay


def spw_range_from_freqs(data, freq_range, bounds_error=True):
    """
    Return a tuple defining the spectral window that corresponds to the 
    frequency range specified in freq_range.
    
    (Spectral windows are specified as tuples containing the first and last 
    index of a frequency range in data.freq_array.)
    
    Parameters
    ----------
    data : UVData or UVPSpec object
        Object containing data with a frequency dimension.
        
    freq_range : tuple or list of tuples
        Tuples containing the lower and upper frequency bounds for each 
        spectral window. The range is inclusive of the lower frequency bound, 
        i.e. it includes all channels in freq_range[0] <= freq < freq_range[1]. 
        Frequencies are in Hz.
    
    bounds_error : bool, optional
        Whether to raise an error if a specified lower/upper frequency is 
        outside the frequency range available in 'data'. Default: True.

    Returns
    -------
    spw_range : tuple or list of tuples
        Indices of the channels at the lower and upper bounds of the specified 
        spectral window(s). 

        Note: If the requested spectral window is outside the available 
        frequency range, and bounds_error is False, '(None, None)' is returned. 
    """
    # Get frequency array from input object
    try:
        freqs = data.freq_array
        if len(freqs.shape) == 2 and freqs.shape[0] == 1:
            freqs = freqs.flatten() # Support UVData 2D freq_array
        elif len(freqs.shape) > 2:
            raise ValueError("data.freq_array has unsupported shape: %s" \
                             % str(freqs.shape))
    except:
        raise AttributeError("Object 'data' does not have a freq_array attribute.")
    
    # Check for a single tuple input
    is_tuple = False
    if isinstance(freq_range, tuple):
        is_tuple = True
        freq_range = [freq_range,]
    
    # Make sure freq_range is now a list (of tuples)
    if not isinstance(freq_range, list):
        raise TypeError("freq_range must be a tuple or list of tuples.")
    
    # Loop over tuples and find spectral window indices
    spw_range = []
    for frange in freq_range:
        fmin, fmax = frange
        if fmin > fmax: 
            raise ValueError("Upper bound of spectral window is less than "
                             "the lower bound.")
        
        # Check that this doesn't go beyond the available range of freqs
        if fmin < np.min(freqs) and bounds_error:
            raise ValueError("Lower bound of spectral window is below the "
                             "available frequency range. (Note: freqs should "
                             "be in Hz)")
        if fmax > np.max(freqs) and bounds_error:
            raise ValueError("Upper bound of spectral window is above the "
                             "available frequency range. (Note: freqs should "
                             "be in Hz)")

        # Get indices within this range
        idxs = np.where(np.logical_and(freqs >= fmin, freqs < fmax))[0]
        spw = (idxs[0], idxs[-1]) if idxs.size > 0 else (None, None)
        spw_range.append(spw)
    
    # Unpack from list if only a single tuple was specified originally
    if is_tuple: return spw_range[0]
    return spw_range


def spw_range_from_redshifts(data, z_range, bounds_error=True):
    """
    Return a tuple defining the spectral window that corresponds to the 
    redshift range specified in z_range.
    
    (Spectral windows are specified as tuples containing the first and last 
    index of a frequency range in data.freq_array.)
    
    Parameters
    ----------
    data : UVData or UVPSpec object
        Object containing data with a frequency dimension.
        
    z_range : tuple or list of tuples
        Tuples containing the lower and upper fredshift bounds for each 
        spectral window. The range is inclusive of the upper redshift bound, 
        i.e. it includes all channels in z_range[0] > z >= z_range[1].
    
    bounds_error : bool, optional
        Whether to raise an error if a specified lower/upper redshift is 
        outside the frequency range available in 'data'. Default: True.

    Returns
    -------
    spw_range : tuple or list of tuples
        Indices of the channels at the lower and upper bounds of the specified 
        spectral window(s).
        
        Note: If the requested spectral window is outside the available 
        frequency range, and bounds_error is False, '(None, None)' is returned. 
    """
    # Check for a single tuple input
    is_tuple = False
    if isinstance(z_range, tuple):
        is_tuple = True
        z_range = [z_range,]
    
    # Convert redshifts to frequencies (in Hz)
    freq_range = []
    for zrange in z_range:
        zmin, zmax = zrange
        freq_range.append( (Cosmo_Conversions.z2f(zmax), 
                            Cosmo_Conversions.z2f(zmin)) )
    
    # Use freq. function to get spectral window
    spw_range = spw_range_from_freqs(data=data, freq_range=freq_range, 
                                     bounds_error=bounds_error)
    
    # Unpack from list if only a single tuple was specified originally
    if is_tuple: return spw_range[0]
    return spw_range
    

def log(msg, f=None, lvl=0, tb=None, verbose=True):
    """
    Add a message to the log.
    
    Parameters
    ----------
    msg : str
        Message string to print.

    f : file descriptor
        file descriptor to write message to.

    lvl : int, optional
        Indent level of the message. Each level adds two extra spaces. 
        Default: 0.

    tb : traceback tuple, optional
        Output of sys.exc_info()

    verbose : bool, optional
        if True, print msg. Even if False, still writes to file
        if f is provided.
    """
    # catch for traceback if provided
    if tb is not None:
        msg += "\n{}".format('\n'.join(traceback.format_exception(*tb)))

    # print
    output = "%s%s" % ("  "*lvl, msg)
    if verbose:
        print(output)

    # write
    if f is not None:
        f.write(output)
        f.flush()


def load_config(config_file):
    """
    Load configuration details from a YAML file.
    All entries of 'None' --> None and all lists
    of lists become lists of tuples.
    """
    # define recursive replace function
    def replace(d):
        if isinstance(d, (dict, odict)):
            for k in d.keys():
                # 'None' and '' turn into None
                if d[k] == 'None': d[k] = None
                # list of lists turn into lists of tuples
                if isinstance(d[k], list) and np.all([isinstance(i, list) for i in d[k]]):
                    d[k] = [tuple(i) for i in d[k]]
                elif isinstance(d[k], (dict, odict)): replace(d[k])

    # Open and read config file
    with open(config_file, 'r') as cfile:
        try:
            cfg = yaml.load(cfile)
        except yaml.YAMLError as exc:
            raise(exc)

    # Replace entries
    replace(cfg)

    return cfg


def flatten(nested_list):
    """
    Flatten a list of nested lists
    """
    return [item for sublist in nested_list for item in sublist]


def config_pspec_blpairs(uv_templates, pol_pairs, group_pairs, exclude_auto_bls=True, 
                         exclude_permutations=True, bl_len_range=(0, 1e10), 
                         bl_deg_range=(0, 180), xants=None, verbose=True):
    """
    Given a list of miriad file templates and selections for
    polarization and group labels, construct a master list of
    blpair-group-pol pairs using utils.construct_reds().

    A group is a fieldname in the visibility files that denotes the
    "type" of dataset. For example, the group field in the following files
        zen.even.LST.1.01.xx.HH.uv
        zen.odd.LST.1.01.xx.HH.uv
    are the "even" and "odd" field, and specifies the two time binning groups.
    To form cross spectra between these two files, one would feed a group_pair
    of: group_pairs = [('even', 'odd'), ...].

    A baseline-pair is formed by self-matching unique-files in the
    glob-parsed master list, and then string-formatting-in appropriate 
    pol and group selections given pol_pairs and group_pairs. Those two
    files are then passed to utils.calc_reds(..., **kwargs) to construct
    the baseline-pairs for that particular file-matching.

    Parameters
    ----------
    uv_templates : list
        List of glob-parseable string templates, each of which must have
        a {pol} and {group} field.

    pol_pairs : list
        List of len-2 polarization tuples to use in forming cross spectra.
        Ex: [('xx', 'xx'), ('yy', 'yy'), ...]

    group_pairs : list
        List of len-2 group tuples to use in forming cross spectra.
        See top of doc-string for an explanation of a "group" in this context.
        Ex: [('grp1', 'grp1'), ('grp2', 'grp2'), ...]

    exclude_auto_bls : bool
        If True, exclude all baselines paired with itself.

    exclude_permutations : bool
        If True, exclude baseline2_cross_baseline1 if
        baseline1_cross_baseline2 exists.

    bl_len_range : len-2 tuple
        A len-2 integer tuple specifying the range of baseline lengths
        (meters in ENU frame) to consider.

    bl_deg_range : len-2 tuple
        A len-2 integer tuple specifying the range of baseline angles
        (degrees in ENU frame) to consider.

    xants : list
        A list of integer antenna numbers to exclude.

    verbose : bool
        If True, print feedback to stdout.

    Returns
    -------
    groupings : dict
        A dictionary holding pol and group pair (tuple) as keys
        and a list of baseline-pairs as values.
    """
    # type check
    if isinstance(uv_templates, (str, np.str)):
        uv_templates = [uv_templates]
    assert len(pol_pairs) == len(group_pairs), "len(pol_pairs) must equal "\
                                               "len(group_pairs)"

    # get unique pols and groups
    pols = sorted(set([item for sublist in pol_pairs for item in sublist]))
    groups = sorted(set([item for sublist in group_pairs for item in sublist]))

    # parse wildcards in uv_templates to get wildcard-unique filenames
    unique_files = []
    pol_grps = []
    for template in uv_templates:
        for pol in pols:
            for group in groups:
                # parse wildcards with pol / group selection
                files = glob.glob(template.format(pol=pol, group=group))
                # if any files were parsed, add to pol_grps
                if len(files) > 0:
                    pol_grps.append((pol, group))
                # insert into unique_files with {pol} and {group} re-inserted
                for _file in files:
                    _unique_file = _file.replace(".{pol}.".format(pol=pol), 
                        ".{pol}.").replace(".{group}.".format(group=group), ".{group}.")
                    if _unique_file not in unique_files:
                        unique_files.append(_unique_file)
    unique_files = sorted(unique_files)

    # use a single file from unique_files and a single pol-group combination to get antenna positions
    _file = unique_files[0].format(pol=pol_grps[0][0], group=pol_grps[0][1])
    uvd = UVData()
    uvd.read_miriad_metadata(_file)

    # get baseline pairs
    (_bls1, _bls2, _, _, 
     _) = calc_reds(uvd, uvd, filter_blpairs=False, exclude_auto_bls=exclude_auto_bls,
                    exclude_permutations=exclude_permutations, bl_len_range=bl_len_range,
                    bl_deg_range=bl_deg_range)

    # take out xants if fed
    if xants is not None:
        bls1, bls2 = [], []
        for bl1, bl2 in zip(_bls1, _bls2):
            if bl1[0] not in xants and bl1[1] not in xants and bl2[0] not in xants and bl2[1] not in xants:
                bls1.append(bl1)
                bls2.append(bl2)
    else:
        bls1, bls2 = _bls1, _bls2
    blps = zip(bls1, bls2)

    # iterate over pol-group pairs that exist
    groupings = odict()
    for pp, gp in zip(pol_pairs, group_pairs):
        if (pp[0], gp[0]) not in pol_grps or (pp[1], gp[1]) not in pol_grps:
            if verbose:
                print "pol_pair {} and group_pair {} not found in data files".format(pp, gp)
            continue
        groupings[(tuple(gp), tuple(pp))] = blps

    return groupings


def get_blvec_reds(blvecs, bl_error_tol=1.0):
    """
    Given a blvecs dictionary, form groups of baseline-pair objects based on
    redundancy in ENU coordinates. Note: this only uses the East-North components
    of the baseline vectors to calculate redundancy.

    Parameters:
    -----------
    blvecs : dictionary (or UVPSpec object)
        A dictionary with baseline vectors as values. Alternatively, this
        can be a UVPSpec object with baseline-pairs and baseline vectors.

    bl_error_tol : int
        Redundancy tolerance of baseline vector in meters.

    Returns:
    --------
    red_bl_grp : list
        A list of baseline groups, ordered by ascending baseline length.

    red_bl_len : list
        A list of baseline lengths in meters for each bl group

    red_bl_ang : list
        A list of baseline angles in degrees for each bl group

    red_bl_tag : list
        A list of baseline string tags denoting bl length and angle
    """
    from hera_pspec import UVPSpec
    # type check
    assert isinstance(blvecs, (dict, odict, UVPSpec)), "blpairs must be fed as a dict or UVPSpec"
    if isinstance(blvecs, UVPSpec):
        # get baseline vectors
        uvp = blvecs
        bls = uvp.bl_array
        bl_vecs = uvp.get_ENU_bl_vecs()[:, :2]
        blvecs = dict(zip(map(uvp.bl_to_antnums, bls), bl_vecs))
        # get baseline-pairs
        blpairs = uvp.get_blpairs()
        # form dictionary
        _blvecs = odict()
        for blp in blpairs:
            bl1 = blp[0]
            bl2 = blp[1]
            _blvecs[blp] = (blvecs[bl1] + blvecs[bl2]) / 2.
        blvecs = _blvecs

    # create empty lists
    red_bl_grp = []
    red_bl_vec = []
    red_bl_len = []
    red_bl_ang = []
    red_bl_tag = []

    # iterate over each baseline in blvecs
    for bl in blvecs.keys():
        # get bl vector and properties
        bl_vec = blvecs[bl][:2]
        bl_len = np.linalg.norm(bl_vec)
        bl_ang = np.arctan2(*bl_vec[::-1]) * 180 / np.pi
        if bl_ang < 0: bl_ang = (bl_ang + 180) % 360
        bl_tag = "{:03.0f}_{:03.0f}".format(bl_len, bl_ang)

        # append to list if unique within tolerance
        match = [np.all(np.isclose(blv, bl_vec, bl_error_tol)) for blv in red_bl_vec]
        if np.any(match):
            match_id = np.where(match)[0][0]
            red_bl_grp[match_id].append(bl)

        # else create new list
        else:
            red_bl_grp.append([bl])
            red_bl_vec.append(bl_vec)
            red_bl_len.append(bl_len)
            red_bl_ang.append(bl_ang)
            red_bl_tag.append(bl_tag)

    # order based on tag
    order = np.argsort(red_bl_tag)
    red_bl_grp = [red_bl_grp[i] for i in order]
    red_bl_len = [red_bl_len[i] for i in order]
    red_bl_ang = [red_bl_ang[i] for i in order]
    red_bl_tag = [red_bl_tag[i] for i in order]

    return red_bl_grp, red_bl_len, red_bl_ang, red_bl_tag

