# -*- coding: utf-8 -*-
"""Workflow for numerical averaging of vibrational intensities. """

from aiida import orm
from aiida.engine import WorkChain, calcfunction
from aiida_quantumespresso_vibroscopy.data import VibrationalFrozenPhononData, VibrationalLinearResponseData


@calcfunction
def compute_ir_average(**kwargs):
    vibro_data = kwargs['vibro_data']
    options = kwargs['options']
    intensities, freqs, labels = vibro_data.get_powder_ir_intensities(**options)
    array = orm.ArrayData()

    array.set_array('intensities', intensities)
    array.set_array('frequencies', freqs)
    array.set_array('labels', labels)

    return array

@calcfunction
def compute_raman_average(**kwargs):
    vibro_data = kwargs['vibro_data']
    options = kwargs['options']
    intensities_hh, intensities_hv, freqs, labels = vibro_data.get_powder_raman_intensities(**options)
    array = orm.ArrayData()

    array.set_array('intensities_HH', intensities_hh)
    array.set_array('intensities_HV', intensities_hv)
    array.set_array('frequencies', freqs)
    array.set_array('labels', labels)

    return array

@calcfunction
def compute_ir_average(**kwargs):
    vibro_data = kwargs['vibro_data']
    options = kwargs['options']
    intensities, freqs, labels = vibro_data.get_powder_ir_intensities(**options)
    array = orm.ArrayData()

    array.set_array('intensities', intensities)
    array.set_array('frequencies', freqs)
    array.set_array('labels', labels)

    return array

def validate_vibrational_data(value, _):
    """Validate vibrational data with having at least the NAC parameters."""
    if not value.has_nac_parameters():
        return 'vibrational data does not contain non-analytical parameters.'


def validate_positive(value, _):
    """Validate the value of the electric field."""
    if value.value < 0:
        return 'specified value is negative.'


class IntensitiesAverageWorkChain(WorkChain):
    """
    Workchain that computes IR and Raman spatial and q-direction average spectra.
    """
    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.input('vibrational_data', valid_type=(VibrationalLinearResponseData, VibrationalFrozenPhononData), required=True, validator=validate_vibrational_data,
            help='Vibrational data containing force constants or frozen phonons forces, nac parameters and/or susceptibility derivatives.'
        )
        spec.input('quadrature_order', valid_type=orm.Int, default=lambda: orm.Int(41), validator=validate_positive,
            help='The order for the numerical quadrature on the sphere (for non-analytical direction averaging).'
        )
        spec.input('options', valid_type=orm.Dict, default=lambda: orm.Dict(dict={'quadrature_order':41}),
            help='Options for averaging on the non-analytical directions.'
        )

        spec.outline(
            cls.run_results,
        )

        spec.output('ir_averaged', valid_type=orm.ArrayData,
            help='Contains high frequency dielectric tensor computed in Cartesian coordinates.'
        )
        spec.output('raman_averaged', valid_type=orm.ArrayData, required=False,
            help='Contains Born effective charges tensors computed in Cartesian coordinates.'
        )
        spec.output('units', valid_type=orm.Dict, required=False,
            help='Units of intensities and frequencies.'
        )

    def run_results(self):
        """Run averaging procedure."""
        kwargs = {'virbo':self.inputs.vibrational_data, 'options':self.inputs.options}
        ir_average = compute_ir_average(**kwargs)

        self.out('ir_averaged', ir_average)

        if self.inputs.vibrational_data.has_raman_parameters():
            options = kwargs['options'].get_dict()

            try:
                options['with_nlo'] = options.pop('with_nlo')
            except:
                if self.inputs.vibrational_data.has_nlo():
                    options['with_nlo'] = True
            kwargs['options'] = orm.Dict(dict=options)

            raman_average = compute_raman_average(**kwargs)
            self.out('raman_averaged', raman_average)
