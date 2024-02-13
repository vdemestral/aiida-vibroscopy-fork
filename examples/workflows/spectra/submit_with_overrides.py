# -*- coding: utf-8 -*-
# pylint: disable=line-too-long,wildcard-import,pointless-string-statement,unused-wildcard-import
"""Submit an IRamanSpectraWorkChain via the get_builder_from_protocol using the overrides."""
from pathlib import Path

from aiida import load_profile
from aiida.engine import submit
from aiida.orm import *
from aiida_quantumespresso.common.types import ElectronicType

from aiida_vibroscopy.workflows.spectra.iraman import IRamanSpectraWorkChain

load_profile()

# =============================== INPUTS =============================== #
# Please, change the following inputs.
pw_code_label = 'pw@localhost'
structure_id = 0  # PK or UUID of your AiiDA StructureData
protocol = 'fast'  # also 'moderate' and 'precise'; 'moderate' should be good enough in general
overrides_filepath = './overrides.yaml'  # should be a path, e.g. /path/to/overrides.yaml. Format is YAML
# Consult the documentation for HOW-TO for how to use properly the overrides.
# !!!!! FOR FULL INPUT NESTED STRUCTURE: https://aiida-vibroscopy.readthedocs.io/en/latest/topics/workflows/spectra/iraman.html
# You can follow the input structure provided on the website to fill further the overrides.
# ====================================================================== #
# If you don't have a StructureData, but you have a CIF or XYZ, or similar, file
# you can import your structure uncommenting the following:
# from ase.io import read
# atoms = read('/path/to/file.cif')
# structure = StructureData(ase=atoms)
# structure.store()
# structure_id =  structure.pk
# print(f"Your structure has been stored in the database with PK={structure_id}")


def main():
    """Submit an IRamanSpectraWorkChain calculation."""
    code = load_code(pw_code_label)
    structure = load_node(structure_id)
    kwargs = {'electronic_type': ElectronicType.INSULATOR}

    builder = IRamanSpectraWorkChain.get_builder_from_protocol(
        code=code,
        structure=structure,
        protocol=protocol,
        overrides=Path(overrides_filepath),
        **kwargs,
    )

    calc = submit(builder)
    print(f'Submitted IRamanSpectraWorkChain with PK={calc.pk} and UUID={calc.uuid}')
    print('Register *at least* the PK number, e.g. in you submit script.')
    print('You can monitor the status of your calculation with the following commands:')
    print('  * verdi process status PK')
    print('  * verdi process list -L IRamanSpectraWorkChain # list all running IRamanSpectraWorkChain')
    print(
        '  * verdi process list -ap1 -L IRamanSpectraWorkChain # list all IRamanSpectraWorkChain submitted in the previous 1 day'
    )
    print('If the WorkChain finishes with exit code 0, then you can inspect the outputs and post-process the data.')
    print('Use the command')
    print('  * verdi process show PK')
    print('To show further information about your WorkChain. When finished, you should see some outputs.')
    print('The main output can be accessed via `load_node(PK).outputs.vibrational_data.numerical_accuracy_*`.')
    print('You have to complete the remaning `*`, which depends upond the accuracy of the calculation.')
    print('See also the documentation and the reference paper for further details.')


if __name__ == '__main__':
    """Run script."""
    main()
