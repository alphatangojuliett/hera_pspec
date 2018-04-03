"""
__init__.py file for hera_pspec
"""
import version
import conversions
import bootstrap
import grouping

from pspecdata import PSpecData

# XXX: This will eventually be deprecated
import legacy_pspec as legacy

__version__ = version.version
