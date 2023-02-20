# -*- coding: utf-8 -*-
"""Mixin for aiida-vibroscopy DataTypes."""

from aiida.plugins import DataFactory

from .vibro_mixin import VibrationalMixin

ForceConstantsData = DataFactory('phonopy.force_constants')

__all__ = ('VibrationalData',)


class VibrationalData(ForceConstantsData, VibrationalMixin):
    """Vibrational data for IR and Raman spectra from linear response."""
