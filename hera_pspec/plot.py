import numpy as np
import pyuvdata
from hera_pspec import conversions
import matplotlib.pyplot as plt
import copy


def delay_spectrum(uvp, blpairs, spw, pol, average_blpairs=False, 
                   average_times=False, fold=False, plot_noise=False, 
                   delay=True, deltasq=False, legend=False, ax=None):
    """
    Plot a 1D delay spectrum (or spectra) for a group of baselines.
    
    Parameters
    ----------
    uvp : UVPspec
        UVPSpec object, containing delay spectra for a set of baseline-pairs, 
        times, polarizations, and spectral windows.
    
    blpairs : list of tuples or lists of tuples
        List of baseline-pair tuples, or groups of baseline-pair tuples.
    
    spw, pol : int or str
        Which spectral window and polarization to plot.
    
    average_blpairs : bool, optional
        If True, average over the baseline pairs within each group.
        
    average_times : bool, optional
        If True, average spectra over the time axis. Default: False.
    
    fold : bool, optional
        Whether to fold the power spectrum in |k_parallel|. Default: False.
    
    plot_noise : bool, optional
        Whether to plot noise power spectrum curves or not. Default: False.
    
    delay : bool, optional
        Whether to plot the power spectrum in delay units (ns) or cosmological 
        units (h/Mpc). Default: True.
    
    deltasq : bool, optional
        If True, plot dimensionless power spectra, Delta^2. This is ignored if 
        delay=True. Default: False.
    
    legend : bool, optional
        Whether to switch on the plot legend. Default: False.
    
    ax : matplotlib.axes, optional
        Use this to pass in an existing Axes object, which the power spectra 
        will be added to. (Warning: Labels and legends will not be altered in 
        this case, even if the existing plot has completely different axis 
        labels etc.) If None, a new Axes object will be created. Default: None.
    
    Returns
    -------
    ax : matplotlib.axes
        Matplotlib Axes instance.
    """
    # Create new Axes if none specified
    new_plot = False
    if ax is None:
        new_plot = True
        fig, ax = plt.subplots(1, 1)
    
    # Add ungrouped baseline-pairs into a group of their own (expected by the
    # averaging routines)
    blpairs_in = blpairs
    blpairs = [] # Must be a list, not an array
    for i, blpgrp in enumerate(blpairs_in):
        if not isinstance(blpgrp, list):
            blpairs.append([blpairs_in[i],])
        else:
            blpairs.append(blpairs_in[i])
    
    # Average over blpairs or times if requested
    blpairs_in = copy.deepcopy(blpairs) # Save input blpair list
    if average_blpairs:
        uvp_plt = uvp.average_spectra(blpair_groups=blpairs, 
                                      time_avg=average_times, inplace=False)
    else:
        uvp_plt = copy.deepcopy(uvp)
        if average_times:
            # Average over times, but not baseline-pairs
            uvp_plt.average_spectra(time_avg=True, inplace=True)
            
    # Fold the power spectra if requested
    if fold:
        uvp_plt.fold_spectra()
    
    # Convert to Delta^2 units if requested
    if deltasq and not delay:
        uvp_plt.convert_to_deltasq()
    
    # Get x-axis units (delays in ns, or k_parallel in Mpc^-1 or h Mpc^-1)
    if delay:
        dlys = uvp_plt.get_dlys(spw) * 1e9 # ns
        x = dlys
    else:
        k_para = uvp_plt.get_kparas(spw)
        x = k_para
    
    # Plot power spectra
    for blgrp in blpairs:
        # Loop over blpairs in group and plot power spectrum for each one
        for blp in blgrp:
            key = (spw, blp, pol)
            power = np.abs(np.real(uvp_plt.get_data(key))).T
            
            ax.plot(x, power, label="%s" % str(key))
            
            # If blpairs were averaged, only the first blpair in the group 
            # exists any more (so skip the rest)
            if average_blpairs: break
    
    # Set log scale
    ax.set_yscale('log')
    
    # Add legend
    if legend:
        ax.legend(loc='upper left')
    
    # Add labels with units
    if ax.get_xlabel() == "":
        if delay:
            ax.set_xlabel(r"$\tau$ $[{\rm ns}]$", fontsize=16)
        else:
            ax.set_xlabel("$k_{\parallel}\ h\ Mpc^{-1}$", fontsize=16)
    if ax.get_ylabel() == "":
        # Sanitize power spectrum units 
        psunits = uvp_plt.units
        if "h^-1" in psunits: psunits = psunits.replace("h^-1", "h^{-1}")
        if "h^-3" in psunits: psunits = psunits.replace("h^-3", "h^{-3}")
        if "Mpc" in psunits and "\\rm" not in psunits: 
            psunits = psunits.replace("Mpc", r"{\rm Mpc}")
        if "pi" in psunits and "\\pi" not in psunits: 
            psunits = psunits.replace("pi", r"\pi")
        
        # Power spectrum type
        if deltasq:
            ax.set_ylabel("$\Delta^2$ $[%s]$" % psunits, fontsize=16)
        else:
            ax.set_ylabel("$P(k_\parallel)$ $[%s]$" % psunits, fontsize=16)
    
    # Return Axes
    return ax
    
