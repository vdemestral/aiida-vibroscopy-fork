# -*- coding: utf-8 -*-
"""Tests for the ``IRamanSpectraWorkChain.get_builder_from_protocol`` method."""
from aiida.engine import ProcessBuilder
from aiida_quantumespresso.common.types import ElectronicType, SpinType
import pytest

from aiida_vibroscopy.workflows.spectra.iraman import IRamanSpectraWorkChain


def test_get_available_protocols():
    """Test ``IRamanSpectraWorkChain.get_available_protocols``."""
    protocols = IRamanSpectraWorkChain.get_available_protocols()
    assert sorted(protocols.keys()) == ['fast', 'moderate', 'precise']
    assert all('description' in protocol for protocol in protocols.values())


def test_get_default_protocol():
    """Test ``IRamanSpectraWorkChain.get_default_protocol``."""
    assert IRamanSpectraWorkChain.get_default_protocol() == 'moderate'


def test_default(fixture_code, generate_structure, data_regression, serialize_builder):
    """Test ``IRamanSpectraWorkChain.get_builder_from_protocol`` for the default protocol."""
    code = fixture_code('quantumespresso.pw')
    structure = generate_structure('silicon')
    builder = IRamanSpectraWorkChain.get_builder_from_protocol(code, structure)

    assert isinstance(builder, ProcessBuilder)
    data_regression.check(serialize_builder(builder))


def test_electronic_type(fixture_code, generate_structure):
    """Test ``IRamanSpectraWorkChain.get_builder_from_protocol`` with ``electronic_type`` keyword."""
    code = fixture_code('quantumespresso.pw')
    structure = generate_structure('silicon')

    with pytest.raises(NotImplementedError):
        for electronic_type in [ElectronicType.AUTOMATIC]:
            IRamanSpectraWorkChain.get_builder_from_protocol(code, structure, electronic_type=electronic_type)

    builder = IRamanSpectraWorkChain.get_builder_from_protocol(
        code, structure, electronic_type=ElectronicType.INSULATOR
    )

    for namespace in [builder.phonon_workchain.scf, builder.dielectric_workchain.scf]:
        parameters = namespace['pw']['parameters'].get_dict()
        assert parameters['SYSTEM']['occupations'] == 'fixed'
        assert 'degauss' not in parameters['SYSTEM']
        assert 'smearing' not in parameters['SYSTEM']


def test_spin_type(fixture_code, generate_structure):
    """Test ``IRamanSpectraWorkChain.get_builder_from_protocol`` with ``spin_type`` keyword."""
    code = fixture_code('quantumespresso.pw')
    structure = generate_structure(structure_id='silicon')

    with pytest.raises(NotImplementedError):
        for spin_type in [SpinType.NON_COLLINEAR, SpinType.SPIN_ORBIT]:
            IRamanSpectraWorkChain.get_builder_from_protocol(code, structure, spin_type=spin_type)

    builder = IRamanSpectraWorkChain.get_builder_from_protocol(code, structure, spin_type=SpinType.COLLINEAR)

    for namespace in [builder.phonon_workchain.scf, builder.dielectric_workchain.scf]:
        parameters = namespace['pw']['parameters'].get_dict()
        assert parameters['SYSTEM']['nspin'] == 2
        assert parameters['SYSTEM']['starting_magnetization'] == {'Si': 0.1}


def test_options(fixture_code, generate_structure):
    """Test specifying ``options`` for the ``get_builder_from_protocol()`` method."""
    code = fixture_code('quantumespresso.pw')
    structure = generate_structure()

    queue_name = 'super-fast'
    withmpi = False  # The protocol default is ``True``

    options = {'queue_name': queue_name, 'withmpi': withmpi}
    builder = IRamanSpectraWorkChain.get_builder_from_protocol(code, structure, options=options)

    for subspace in (
        builder.phonon_workchain.scf.pw.metadata,
        builder.dielectric_workchain.scf.pw.metadata,
    ):
        assert subspace['options']['queue_name'] == queue_name, subspace


def test_options(fixture_code, generate_structure):
    """Test specifying ``options`` for the ``get_builder_from_protocol()`` method."""
    code = fixture_code('quantumespresso.pw')
    structure = generate_structure()

    queue_name = 'super-fast'
    withmpi = False  # The protocol default is ``True``

    options = {'queue_name': queue_name, 'withmpi': withmpi}
    builder = IRamanSpectraWorkChain.get_builder_from_protocol(code, structure, options=options)

    for subspace in (
        builder.phonon_workchain.scf.pw.metadata,
        builder.dielectric_workchain.scf.pw.metadata,
    ):
        assert subspace['options']['queue_name'] == queue_name, subspace