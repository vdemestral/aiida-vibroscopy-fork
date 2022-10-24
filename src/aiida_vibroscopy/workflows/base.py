# -*- coding: utf-8 -*-
"""Base class for `phonons` and `spectra` workchains."""
import time

from aiida import orm
from aiida.common.extendeddicts import AttributeDict
from aiida.engine import WorkChain
from aiida.plugins import DataFactory, WorkflowFactory

from aiida_vibroscopy.calculations.phonon_utils import get_energy, get_forces
from aiida_vibroscopy.calculations.spectra_utils import get_supercells_for_hubbard
from aiida_vibroscopy.utils.validation import validate_matrix, validate_positive, validate_tot_magnetization

from .dielectric.base import DielectricWorkChain

__all__ = ('BaseWorkChain',)

PreProcessData = DataFactory('phonopy.preprocess')
PhonopyData = DataFactory('phonopy.phonopy')
PwBaseWorkChain = WorkflowFactory('quantumespresso.pw.base')


def validate_inputs(inputs, _):
    """Validate the entire inputs namespace."""
    ensamble_inputs = [
        'structure', 'symprec', 'is_symmetry', 'distinguish_kinds', 'primitive_matrix', 'supercell_matrix'
    ]

    given_inputs = []

    for einput in ensamble_inputs:
        if einput in inputs:
            given_inputs.append(einput)
        if einput in inputs['phonon_workchain']:
            given_inputs.append(einput)

    if 'preprocess_data' in inputs and given_inputs:
        return 'too many inputs have been provided'

    if given_inputs and 'structure' not in given_inputs:
        return 'a structure data is required'

    if not given_inputs and 'preprocess_data' not in inputs:
        return 'at least one between `preprocess_data` and `structure` must be provided in input'

    if 'nac_parameters' in inputs and 'dielectric_workchain' in inputs:
        return 'too many inputs for non-analytical constants'


class BaseWorkChain(WorkChain):
    """
    Base class for `phonons` and `spectra` workchains.
    """

    _ENABLED_DISPLACEMENT_GENERATOR_FLAGS = {
        'distance': [float],
        'is_plusminus': ['auto', float],
        'is_diagonal': [bool],
        'is_trigonal': [bool],
        'number_of_snapshots': [int, None],
        'random_seed': [int, None],
        'cutoff_frequency': [float, None],
    }

    _RUN_PREFIX = 'scf_supercell'

    @classmethod
    def define(cls, spec):
        """Define inputs, outputs, and outline."""
        super().define(spec)

        spec.input(
            'structure', valid_type=orm.StructureData, required=False, help='The structure at equilibrium volume.'
        )
        spec.input_namespace(
            'phonon_workchain',
            help='Inputs for the frozen phonons calculation.',
        )
        spec.input(
            'phonon_workchain.primitive_matrix',
            valid_type=orm.List,
            validator=validate_matrix,
            required=False,
            help='Primitive matrix that defines the primitive cell from the unitcell.',
        )
        spec.input(
            'phonon_workchain.symprec',
            valid_type=orm.Float,
            validator=validate_positive,
            required=False,
            help='Symmetry tolerance for space group analysis on the input structure.',
        )
        spec.input(
            'phonon_workchain.is_symmetry',
            valid_type=orm.Bool,
            required=False,
            help='Whether using or not the space group symmetries.',
        )
        spec.input(
            'phonon_workchain.distinguish_kinds',
            valid_type=orm.Bool,
            required=False,
            help='Whether or not to distinguish atom with same species but different names with symmetries.',
        )
        spec.input(
            'phonon_workchain.displacement_generator',
            valid_type=orm.Dict,
            required=False,
            validator=cls._validate_displacements,
            help=(
                'Info for displacements generation. The following flags are allowed:\n ' +
                '\n '.join(f'{flag_name}' for flag_name in cls._ENABLED_DISPLACEMENT_GENERATOR_FLAGS)
            ),
        )
        spec.expose_inputs(
            PwBaseWorkChain,
            namespace='phonon_workchain.scf',
            namespace_options={
                'required': True,
                'help': ('Inputs for the `PwBaseWorkChain` that will be used to run the electric enthalpy scfs.')
            },
            exclude=('clean_workdir', 'pw.parent_folder', 'pw.structure')
        )
        spec.expose_inputs(
            DielectricWorkChain,
            namespace='dielectric_workchain',
            namespace_options={
                'required':
                False,
                'populate_defaults':
                False,
                'help':
                ('Inputs for the `DielectricWorkChain` that will be'
                 'used to calculate the non-analytical constants.')
            },
            exclude=(
                'clean_workdir', 'scf.pw.structure', 'options.symprec', 'options.distinguish_kinds',
                'options.is_symmetry'
            )
        )
        spec.input_namespace(
            'options',
            help='Options for how to run the workflow.',
        )
        spec.input(
            'options.run_parallel',
            valid_type=bool,
            non_db=True,
            default=True,
            help='Whether running dielectric workchain and forces calculations in parallel.',
        )
        spec.input(
            'options.sleep_submission_time',
            valid_type=(int, float),
            non_db=True,
            default=3.0,
            help='Time in seconds to wait before submitting subsequent displaced structure scf calculations.',
        )
        spec.input(
            'clean_workdir',
            valid_type=orm.Bool,
            default=lambda: orm.Bool(False),
            help='If `True`, work directories of all called calculation will be cleaned at the end of execution.'
        )
        spec.inputs.validator = validate_inputs

        spec.output_namespace(
            'supercells',
            valid_type=orm.StructureData,
            dynamic=True,
            required=False,
            help='The supercells with displacements.'
        )
        spec.output_namespace(
            'supercells_forces',
            valid_type=orm.ArrayData,
            required=True,
            help='The forces acting on the atoms of each supercell.'
        )
        spec.output_namespace(
            'supercells_energies', valid_type=orm.Float, required=False, help='The total energy of each supercell.'
        )
        spec.expose_outputs(
            DielectricWorkChain,
            namespace_options={
                'required': False,
                'help': ('Outputs of the `DielectricWorkChain`.')
            },
        )

        spec.exit_code(400, 'ERROR_FAILED_BASE_SCF', message='The initial supercell scf work chain failed.')
        spec.exit_code(
            401,
            'ERROR_NON_INTEGER_TOT_MAGNETIZATION',
            message=(
                'The scf PwBaseWorkChain sub process in iteration '
                'returned a non integer total magnetization (threshold exceeded).'
            )
        )
        spec.exit_code(
            402, 'ERROR_SUB_PROCESS_FAILED', message='At least one sub processe did not finish successfully.'
        )

    @classmethod
    def _validate_displacements(cls, value, _):
        """Validate the ``displacements`` input namespace."""
        if value:
            value_dict = value.get_dict()
            enabled_dict = cls._ENABLED_DISPLACEMENT_GENERATOR_FLAGS
            unknown_flags = set(value_dict.keys()) - set(enabled_dict.keys())
            if unknown_flags:
                return (
                    f"Unknown flags in 'displacements': {unknown_flags}."
                    # f"allowed flags are {cls._ENABLED_DISPLACEMENT_GENERATOR_FLAGS.keys()}."
                )
            invalid_values = [
                value_dict[key]
                for key in value_dict.keys()
                if not (type(value_dict[key]) in enabled_dict[key] or value_dict[key] in enabled_dict[key])
            ]
            if invalid_values:
                return f'Displacement options must be of the correct type; got invalid values {invalid_values}.'

    def set_ctx_variables(self):
        """Set `is_magnetic` and `plus_hubbard` context variables."""
        parameters = self.inputs.phonon_workchain.scf.pw.parameters.get_dict()
        nspin = parameters.get('SYSTEM', {}).get('nspin', 1)
        self.ctx.is_magnetic = (nspin != 1)

        if parameters.get('SYSTEM', {}).get('lda_plus_u_kind', None) == 2:
            self.ctx.plus_hubbard = True
        else:
            self.ctx.plus_hubbard = False

    def should_run_parallel(self):
        """Return whether to run in parallel phonon and dielectric calculation."""
        return self.ctx.run_parallel

    def run_base_supercell(self):
        """Run a `pristine` supercell calculation from where to restart supercell with displacements."""
        inputs = AttributeDict(self.exposed_inputs(PwBaseWorkChain, namespace='phonon_workchain.scf'))
        if self.ctx.plus_hubbard:
            self.ctx.supercell = self.inputs.structure
        else:
            self.ctx.supercell = self.ctx.preprocess_data.calcfunctions.get_supercell()
        inputs.pw.structure = self.ctx.supercell

        key = f'{self._RUN_PREFIX}_0'
        inputs.metadata.label = key
        inputs.metadata.call_link_label = key
        inputs.clean_workdir = orm.Bool(False)  # the folder is needed for next calculations

        node = self.submit(PwBaseWorkChain, **inputs)
        self.to_context(**{key: node})
        self.report(f'launched base supercell scf PwBaseWorkChain<{node.pk}>')

    def inspect_base_supercell(self):
        """Verify that the scf PwBaseWorkChain finished successfully."""
        base_key = f'{self._RUN_PREFIX}_0'
        workchain = self.ctx[base_key]

        if not workchain.is_finished_ok:
            self.report(f'base supercell scf failed with exit status {workchain.exit_status}')
            return self.exit_codes.ERROR_FAILED_BASE_SCF

    def run_parallel(self):
        """It runs in parallel forces calculations and dielectric workchain."""
        self.run_forces()
        self.run_dielectric()

    def run_forces(self):
        """Run an scf for each supercell with displacements."""
        if self.ctx.plus_hubbard:
            supercells = get_supercells_for_hubbard(
                preprocess_data=self.ctx.preprocess_data, ref_structure=self.inputs.structure
            )
        else:
            supercells = self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()

        self.out('supercells', supercells)

        base_key = f'{self._RUN_PREFIX}_0'
        base_out = self.ctx[base_key].outputs

        for key, supercell in supercells.items():
            num = key.split('_')[-1]
            label = f'{self._RUN_PREFIX}_{num}'

            inputs = AttributeDict(self.exposed_inputs(PwBaseWorkChain, namespace='phonon_workchain.scf'))
            inputs.pw.structure = supercell
            inputs.pw.parent_folder = base_out.remote_folder

            parameters = inputs.pw.parameters.get_dict()
            parameters.setdefault('CONTROL', {})
            parameters.setdefault('SYSTEM', {})
            parameters.setdefault('ELECTRONS', {})
            if self.ctx.is_magnetic:
                parameters['SYSTEM']['occupations'] = 'fixed'
                parameters['SYSTEM'].pop('smearing', None)
                parameters['SYSTEM'].pop('degauss', None)
                parameters['SYSTEM'].pop('starting_magnetization', None)
                parameters['SYSTEM']['nbnd'] = base_out.output_parameters.get_attribute('number_of_bands')
                tot_magnetization = base_out.output_parameters.get_attribute('total_magnetization')
                parameters['SYSTEM']['tot_magnetization'] = tot_magnetization
                if validate_tot_magnetization(tot_magnetization):
                    return self.exit_codes.ERROR_NON_INTEGER_TOT_MAGNETIZATION

            parameters['ELECTRONS']['startingpot'] = 'file'
            inputs.pw.parameters = orm.Dict(dict=parameters)

            inputs.clean_workdir = self.inputs.clean_workdir
            inputs.metadata.label = label
            inputs.metadata.call_link_label = label

            future = self.submit(PwBaseWorkChain, **inputs)
            self.report(f'submitting `PwBaseWorkChain` <PK={future.pk}> with supercell n.o {key}')
            self.to_context(**{label: future})
            time.sleep(self.inputs.options.sleep_submission_time)

    def run_dielectric(self):
        """Run a DielectricWorkChain."""

    def inspect_all_runs(self):
        """Inspect all previous workchains."""
        # First we check the forces
        failed_runs = []

        for label, workchain in self.ctx.items():
            if label.startswith(self._RUN_PREFIX):
                if workchain.is_finished_ok:
                    forces = get_forces(workchain.outputs.output_trajectory)
                    energy = get_energy(workchain.outputs.output_parameters)
                    self.out(f'supercells_forces.{label}', forces)
                    self.out(f'supercells_energies.{label}', energy)
                else:
                    self.report(
                        f'PwBaseWorkChain with <PK={workchain.pk}> failed'
                        'with exit status {workchain.exit_status}'
                    )
                    failed_runs.append(workchain.pk)

        if 'dielectric_workchain' in self.ctx:
            workchain = self.ctx.dielectric_workchain
            if not workchain.is_finished_ok:
                self.report(f'DielectricWorkChain failed with exit status {workchain.exit_status}')
                failed_runs.append(workchain.pk)
            else:
                self.out_many(self.exposed_outputs(workchain, DielectricWorkChain))

        if failed_runs:
            self.report('one or more workchains did not finish succesfully')
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED

    def on_terminated(self):
        """Clean the working directories of all child calculations if `clean_workdir=True` in the inputs."""
        super().on_terminated()

        if self.inputs.clean_workdir.value is False:
            self.report('remote folders will not be cleaned')
            return

        cleaned_calcs = []

        for called_descendant in self.node.called_descendants:
            if isinstance(called_descendant, orm.CalcJobNode):
                try:
                    called_descendant.outputs.remote_folder._clean()  # pylint: disable=protected-access
                    cleaned_calcs.append(called_descendant.pk)
                except (IOError, OSError, KeyError):
                    pass

        if cleaned_calcs:
            self.report(f"cleaned remote folders of calculations: {' '.join(map(str, cleaned_calcs))}")