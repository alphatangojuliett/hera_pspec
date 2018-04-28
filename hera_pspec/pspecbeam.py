import numpy as np
import os
import aipy
import pyuvdata
from hera_pspec import conversions
from scipy import __version__ as scipy_version
from scipy import integrate
from scipy.interpolate import interp1d


def _compute_pspec_scalar(cosmo, beam_freqs, omega_ratio, pspec_freqs, 
                          num_steps=5000, taper='none', little_h=True, 
                          noise_scalar=False):
    """
    This is not to be used by the novice user to calculate a pspec scalar.
    Instead, look at the PSpecBeamUV and PSpecBeamGauss classes.

    Computes the scalar function to convert a power spectrum estimate
    in "telescope units" to cosmological units

    See arxiv:1304.4991 and HERA memo #27 for details.

    Parameters
    ----------
    cosmo : conversions.Cosmo_Conversions instance
        Instance of the cosmological conversion object.

    beam_freqs : array of floats
        Frequency of beam integrals in omega_ratio in units of Hz.

    omega_ratio : array of floats
        Ratio of the integrated squared-beam power over the square of the 
        integrated beam power for each frequency in beam_freqs. 
        i.e. Omega_pp(nu) / Omega_p(nu)^2

    pspec_freqs : array of floats
        Array of frequencies over which power spectrum is estimated in Hz.

    num_steps : int, optional
        Number of steps to use when interpolating primary beams for numerical 
        integral. Default: 5000.

    taper : str, optional
        Whether a tapering function (e.g. Blackman-Harris) is being used in the 
        power spectrum estimation. Default: 'none'.

    little_h : boolean, optional
        Whether to have cosmological length units be h^-1 Mpc or Mpc. Value of 
        h is obtained from cosmo object stored in pspecbeam. Default: h^-1 Mpc.

    noise_scalar : boolean, optional
        Whether to calculate power spectrum scalar, or noise power scalar. The 
        noise power scalar only differs in that the Bpp_over_BpSq term turns 
        into 1_over_Bp. See Pober et al. 2014, ApJ 782, 66, and Parsons HERA 
        Memo #27. Default: False.

    Returns
    -------
    scalar: float
        [\int dnu (\Omega_PP / \Omega_P^2) ( B_PP / B_P^2 ) / (X^2 Y)]^-1
        Units: h^-3 Mpc^3 or Mpc^3.
    """
    # Get integration freqs
    df = np.median(np.diff(pspec_freqs))
    integration_freqs = np.linspace(pspec_freqs.min(), 
                                    pspec_freqs.min() + df*len(pspec_freqs), 
                                    num_steps, endpoint=True, dtype=np.float)
    
    # The interpolations are generally more stable in MHz
    integration_freqs_MHz = integration_freqs / 1e6
    
    # Get redshifts and cosmological functions
    redshifts = cosmo.f2z(integration_freqs).flatten()
    X2Y = np.array(map(lambda z: cosmo.X2Y(z, little_h=little_h), redshifts))

    # Use linear interpolation to interpolate the frequency-dependent 
    # quantities derived from the beam model to the same frequency grid as the 
    # power spectrum estimation
    beam_model_freqs_MHz = beam_freqs / 1e6
    dOpp_over_Op2_fit = interp1d(beam_model_freqs_MHz, omega_ratio, 
                                 kind='quadratic', fill_value='extrapolate')
    dOpp_over_Op2 = dOpp_over_Op2_fit(integration_freqs_MHz)

    # Get B_pp = \int dnu taper^2 and Bp = \int dnu
    if taper == 'none':
        dBpp_over_BpSq = np.ones_like(integration_freqs, np.float)
    else:
        dBpp_over_BpSq = aipy.dsp.gen_window(len(pspec_freqs), taper)**2.
        dBpp_over_BpSq = interp1d(pspec_freqs, dBpp_over_BpSq, kind='nearest', 
                                  fill_value='extrapolate')(integration_freqs)
    dBpp_over_BpSq /= (integration_freqs[-1] - integration_freqs[0])**2.

    # Keep dBpp_over_BpSq term or not
    if noise_scalar:
        dBpp_over_BpSq = 1. / (integration_freqs[-1] - integration_freqs[0])

    # Integrate to get scalar
    d_inv_scalar = dBpp_over_BpSq * dOpp_over_Op2 / X2Y
    scalar = 1. / integrate.trapz(d_inv_scalar, x=integration_freqs)
    return scalar


class PSpecBeamBase(object):

    def __init__(self, cosmo=None):
        """
        Base class for PSpecBeam objects. Provides compute_pspec_scalar() 
        method to integrate over and interpolate beam solid angles, and 
        Jy_to_mK() method to convert units.
        
        Parameters
        ----------
        cosmo : conversions.Cosmo_Conversions object, optional
            Cosmology object. Uses the default cosmology object if not 
            specified. Default: None.
        """
        if cosmo is not None:
            self.cosmo = cosmo
        else:
            self.cosmo = conversions.Cosmo_Conversions()

    def compute_pspec_scalar(self, lower_freq, upper_freq, num_freqs, num_steps=5000, 
                             pol='I', taper='none', little_h=True, noise_scalar=False):
        """
        Computes the scalar function to convert a power spectrum estimate
        in "telescope units" to cosmological units

        See arxiv:1304.4991 and HERA memo #27 for details.

        Currently, only the "I", "XX" and "YY" polarization beams are supported.
        See Equations 4 and 5 of Moore et al. (2017) ApJ 836, 154
        or arxiv:1502.05072 for details.

        Parameters
        ----------
        lower_freq : float
            Bottom edge of frequency band over which power spectrum is being 
            estimated. Assumed to be in Hz.

        upper_freq : float
            Top edge of frequency band over which power spectrum is being 
            estimated. Assumed to be in Hz.

        num_freqs : int, optional
            Number of frequencies used in estimating power spectrum.

        num_steps : int, optional
            Number of steps to use when interpolating primary beams for 
            numerical integral. Default: 5000.

        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX', although 
                Default: 'I'

        taper : str, optional
            Whether a tapering function (e.g. Blackman-Harris) is being used in 
            the power spectrum estimation. Default: none.

        little_h : boolean, optional
            Whether to have cosmological length units be h^-1 Mpc or Mpc. Value 
            of h is obtained from cosmo object stored in pspecbeam.
            Default: h^-1 Mpc

        noise_scalar : boolean, optional
            Whether to calculate power spectrum scalar, or noise power scalar. 
            The noise power scalar only differs in that the Bpp_over_BpSq term 
            just because 1_over_Bp. See Pober et al. 2014, ApJ 782, 66.

        Returns
        -------
        scalar: float
            [\int dnu (\Omega_PP / \Omega_P^2) ( B_PP / B_P^2 ) / (X^2 Y)]^-1
            Units: h^-3 Mpc^3 or Mpc^3.
        """
        # Get pspec_freqs
        pspec_freqs = np.linspace(lower_freq, upper_freq, num_freqs, 
                                  endpoint=False)

        # Get omega_ratio
        omega_ratio = self.power_beam_sq_int(pol) \
                      / self.power_beam_int(pol)**2

        # Get scalar
        scalar = _compute_pspec_scalar(self.cosmo, self.beam_freqs, 
                                       omega_ratio, pspec_freqs,
                                       num_steps=num_steps, taper=taper, 
                                       little_h=little_h,
                                       noise_scalar=noise_scalar)
        return scalar

    def Jy_to_mK(self, freqs, pol='I'):
        """
        Return the multiplicative factor [mK / Jy], to convert a visibility 
        from Jy -> mK,

        factor = 1e3 * 1e-23 * c^2 / [2 * k_b * nu^2 * Omega_p(nu)]

        where k_b is boltzmann constant, c is speed of light, nu is frequency 
        and Omega_p is the integral of the unitless beam-response (steradians),
        and the 1e3 is the conversion from K -> mK and the 1e-23 is the 
        conversion from Jy to cgs.

        Parameters
        ----------
        freqs : float ndarray
            Contains frequencies to evaluate conversion factor [Hz].

        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX', although 
                Default: 'I'

        Returns
        -------
        factor : float ndarray
            Contains Jy -> mK factor at each frequency.
        """
        # Check input types
        if isinstance(freqs, (np.float, float)):
            freqs = np.array([freqs])
        elif not isinstance(freqs, np.ndarray):
            raise TypeError("freqs must be fed as a float ndarray")
        elif isinstance(freqs, np.ndarray) \
            and freqs.dtype not in (float, np.float, np.float64):
            raise TypeError("freqs must be fed as a float ndarray")
        
        # Check frequency bounds
        if np.min(freqs) < self.beam_freqs.min():
            raise ValueError("Warning: min freq {} < self.beam_freqs.min(), extrapolating...".format(np.min(freqs)))
        if np.max(freqs) > self.beam_freqs.max(): 
            raise ValueError("Warning: max freq {} > self.beam_freqs.max(), extrapolating...".format(np.max(freqs)))
        
        Op = interp1d(self.beam_freqs/1e6, self.power_beam_int(pol=pol), 
                      kind='quadratic', fill_value='extrapolate')(freqs/1e6)

        return 1e-20 * conversions.cgs_units.c**2 \
               / (2 * conversions.cgs_units.kb * freqs**2 * Op)


class PSpecBeamGauss(PSpecBeamBase):

    def __init__(self, fwhm, beam_freqs, cosmo=None):
        """
        Object to store a simple (frequency independent) Gaussian beam in a 
        PspecBeamBase object.

        Parameters
        ----------
        fwhm: float
            Full width half max of the beam, in radians.

        beam_freqs: float, array-like
            Frequencies over which this Gaussian beam is to be created. Units 
            assumed to be Hz.
        
        cosmo : conversions.Cosmo_Conversions object, optional
            Cosmology object. Uses the default cosmology object if not 
            specified. Default: None.
        """
        self.fwhm = fwhm
        self.beam_freqs = beam_freqs
        if cosmo is not None:
            self.cosmo = cosmo
        else:
            self.cosmo = conversions.Cosmo_Conversions()

    def power_beam_int(self, pol='I'):
        """
        Computes the integral of the beam over solid angle to give
        a beam area (in sr). Uses analytic formula that the answer
        is 2 * pi * fwhm**2 / 8 ln 2.

        Trivially this returns an array (i.e., a function of frequency),
        but the results are frequency independent.

        See Equations 4 and 5 of Moore et al. (2017) ApJ 836, 154
        or arxiv:1502.05072 for details.

        Parameters
        ----------
        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX' 
                Default: 'I'

        Returns
        -------
        primary_beam_area: float, array-like
            Primary beam area.
        """
        return np.ones_like(self.beam_freqs) * 2. * np.pi * self.fwhm**2 \
               / (8. * np.log(2.))

    def power_beam_sq_int(self, pol='I'):
        """
        Computes the integral of the beam**2 over solid angle to give
        a beam area (in str). Uses analytic formula that the answer
        is pi * fwhm**2 / 8 ln 2.

        Trivially this returns an array (i.e., a function of frequency),
        but the results are frequency independent.

        See Equations 4 and 5 of Moore et al. (2017) ApJ 836, 154
        or arxiv:1502.05072 for details.

        Parameters
        ----------
        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX' 
                Default: 'I'

        Returns
        -------
        primary_beam_area: float, array-like
            Primary beam area.
        """
        return np.ones_like(self.beam_freqs) * np.pi * self.fwhm**2 \
               / (8. * np.log(2.))


class PSpecBeamUV(PSpecBeamBase):

    def __init__(self, beam_fname, cosmo=None):
        """
        Object to store the primary beam for a pspec observation.
        This is subclassed from PSpecBeamBase to take in a pyuvdata
        UVBeam object.

        Parameters
        ----------
        beam_fname: str
            Path to a pyuvdata UVBeam file.
        
        cosmo : conversions.Cosmo_Conversions object, optional
            Cosmology object. Uses the default cosmology object if not 
            specified. Default: None.
        """
        self.primary_beam = pyuvdata.UVBeam()
        self.primary_beam.read_beamfits(beam_fname)

        self.beam_freqs = self.primary_beam.freq_array[0]
        if cosmo is not None:
            self.cosmo = cosmo
        else:
            self.cosmo = conversions.Cosmo_Conversions()

    def power_beam_int(self, pol='I'):
        """
        Computes the integral of the beam over solid angle to give
        a beam area (in str) as a function of frequency. Uses function
        in pyuvdata.

        See Equations 4 and 5 of Moore et al. (2017) ApJ 836, 154
        or arxiv:1502.05072 for details.

        Parameters
        ----------
        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX' 
                Default: 'I'

        Returns
        -------
        primary_beam_area: float, array-like
            Scalar integral over beam solid angle.
        """
        if hasattr(self.primary_beam, 'get_beam_area'):
            return self.primary_beam.get_beam_area(pol)
        else:
            raise NotImplementedError("Outdated version of pyuvdata.")

    def power_beam_sq_int(self, pol='I'):
        """
        Computes the integral of the beam**2 over solid angle to give
        a beam**2 area (in str) as a function of frequency. Uses function
        in pyuvdata.

        See Equations 4 and 5 of Moore et al. (2017) ApJ 836, 154
        or arxiv:1502.05072 for details.

        Parameters
        ----------
        pol: str, optional
                Which polarization to compute the beam scalar for.
                'I', 'Q', 'U', 'V', 'XX', 'YY', 'XY', 'YX'
                Default: 'I'

        Returns
        -------
        primary_beam_area: float, array-like
        """
        if hasattr(self.primary_beam, 'get_beam_area'):
            return self.primary_beam.get_beam_sq_area(pol)
        else:
            raise NotImplementedError("Outdated version of pyuvdata.")


class PSpecBeamFromArray(PSpecBeamBase):
    
    def __init__(self, OmegaP, OmegaPP, beam_freqs, cosmo=None):
        """
        Primary beam model built from user-defined arrays for the integrals 
        over beam solid angle and beam solid angle squared.
        
        Allowed polarizations are: 
        
            I, Q, U, V, XX, YY, XY, YX
        
        Other polarizations will be ignored.
        
        Parameters
        ----------
        OmegaP : array_like of float (or dict of array_like)
            Integral over beam solid angle, as a function of frequency. 
            
            If only one array is specified, this will be assumed to be for the 
            I polarization. If a dict is specified, an OmegaP array for 
            several polarizations can be specified.
        
        OmegaPP : array_like of float (or dict of array_like)
            Integral over beam solid angle squared, as a function of frequency. 
            
            If only one array is specified, this will be assumed to be for the 
            I polarization. If a dict is specified, an OmegaP array for 
            several polarizations can be specified.
        
        beam_freqs : array_like of float
            Frequencies at which beam solid angles OmegaP and OmegaPP are 
            evaluated, in Hz. This should be specified as a single array, not 
            as a dict.
        
        cosmo : conversions.Cosmo_Conversions object, optional
            Cosmology object. Uses the default cosmology object if not 
            specified. Default: None.
        """
        self.allowed_pols = ['I', 'Q', 'U', 'V', 
                             'XX', 'YY', 'XY', 'YX']
        self.OmegaP = {}; self.OmegaPP = {}
        
        # Set beam_freqs
        self.beam_freqs = np.array(beam_freqs)
        
        if isinstance(OmegaP, np.ndarray) and isinstance(OmegaPP, np.ndarray):
            # Only single arrays were specified; assume I
            OmegaP = {'I': OmegaP}
            OmegaPP = {'I': OmegaPP}
        
        elif isinstance(OmegaP, np.ndarray) or isinstance(OmegaPP, np.ndarray):
            # Mixed dict and array types are not allowed
            raise TypeError("OmegaP and OmegaPP must both be either dicts "
                            "or arrays. Mixing dicts and arrays is not "
                            "allowed.")
        else:
            pass
        
        # Should now have two dicts if everything is OK
        if not isinstance(OmegaP, dict) or not isinstance(OmegaPP, dict):
            raise TypeError("OmegaP and OmegaPP must both be either dicts or "
                            "arrays.")
        
        # Check for disallowed polarizations
        for key in OmegaP.keys():
            if key not in self.allowed_pols:
              raise KeyError("Unrecognized polarization '%s' in OmegaP." % key)
        for key in OmegaPP.keys():
            if key not in self.allowed_pols:
              raise KeyError("Unrecognized polarization '%s' in OmegaPP." % key)
        
        # Check for available polarizations
        for pol in self.allowed_pols:
            if pol in OmegaP.keys() or pol in OmegaPP.keys():
                if pol not in OmegaP.keys() or pol not in OmegaPP.keys():
                    raise KeyError("Polarization '%s' must be specified for"
                                   " both OmegaP and OmegaPP." % pol)
                
                # Add arrays for this polarization
                self.add_pol(pol, OmegaP[pol], OmegaPP[pol])
        
        # Set cosmology
        if cosmo is None:
            self.cosmo = conversions.Cosmo_Conversions()
        else:
            self.cosmo = cosmo
    
    
    def add_pol(self, pol, OmegaP, OmegaPP):
        """
        Add OmegaP and OmegaPP for a new polarization.
        
        Parameters
        ----------
        pol: str
            Which polarization to add beam solid angle arrays for. Valid 
            options are:
            
              'I', 'Q', 'U', 'V', 
              'XX', 'YY', 'XY', 'YX' 
            
            If the arrays already exist for the specified polarization, they 
            will be overwritten.
        
        OmegaP : array_like of float
            Integral over beam solid angle, as a function of frequency. Must 
            have the same shape as self.beam_freqs.
        
        OmegaPP : array_like of float
            Integral over beam solid angle squared, as a function of frequency.  
            Must have the same shape as self.beam_freqs.
        """
        # Check for allowed polarization
        if pol not in self.allowed_pols:
            raise KeyError("Polarization '%s' is not valid." % pol)
        
        # Make sure OmegaP and OmegaPP are arrays
        try:
            OmegaP = np.array(OmegaP).astype(float)
            OmegaPP = np.array(OmegaPP).astype(float)
        except:
            raise TypeError("OmegaP and OmegaPP must both be array_like.")
        
        # Check that array dimensions are consistent
        if OmegaP.shape != self.beam_freqs.shape \
          or OmegaPP.shape != self.beam_freqs.shape:
               raise ValueError("OmegaP and OmegaPP should both "
                                "have the same shape as beam_freqs.")
        # Store arrays
        self.OmegaP[pol] = OmegaP
        self.OmegaPP[pol] = OmegaPP
            
    
    def power_beam_int(self, pol='I'):
        """
        Computes the integral of the beam over solid angle to give
        a beam area (in str) as a function of frequency.

        Parameters
        ----------
        pol: str, optional
            Which polarization to compute the beam scalar for. 
                'I', 'Q', 'U', 'V', 
                'XX', 'YY', 'XY', 'YX'
            Default: I.

        Returns
        -------
        primary_beam_area: float, array-like
            Scalar integral over beam solid angle.
        """
        if pol in self.OmegaP.keys():
            return self.OmegaP[pol]
        else:
            available_pols = ", ".join(self.OmegaP.keys())
            raise KeyError("OmegaP not specified for polarization '%s'. " 
                           "Available polarizations are: %s" \
                           % (pol, available_pols))
    
    def power_beam_sq_int(self, pol='I'):
        """
        Computes the integral of the beam**2 over solid angle to give
        a beam**2 area (in str) as a function of frequency.

        Parameters
        ----------
        pol: str, optional
            Which polarization to compute the beam scalar for.
              'I', 'Q', 'U', 'V', 
              'XX', 'YY', 'XY', 'YX' 
            Default: I.

        Returns
        -------
        primary_beam_area: float, array-like
        """
        if pol in self.OmegaPP.keys():
            return self.OmegaPP[pol]
        else:
            available_pols = ", ".join(self.OmegaPP.keys())
            raise KeyError("OmegaPP not specified for polarization '%s'. " 
                           "Available polarizations are: %s" \
                           % (pol, available_pols))
    
    def __str__(self):
        """
        Print string with useful information.
        """
        s = "PSpecBeamFromArray object\n"
        s += "\tFrequency range: Min. %4.4e Hz, Max. %4.4e Hz\n" \
              % (np.min(self.beam_freqs), np.max(self.beam_freqs))
        s += "\tAvailable pols: %s" % (", ".join(self.OmegaP.keys()))
        return s
        
