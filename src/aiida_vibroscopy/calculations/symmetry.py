# -*- coding: utf-8 -*-
"""Symmetry utils for vectors and tensors, and for pre/post analysis."""
from copy import deepcopy

from aiida.orm import TrajectoryData
from aiida_phonopy.data import PreProcessData
import numpy as np
from phonopy import Phonopy
from phonopy.harmonic.force_constants import similarity_transformation
from phonopy.structure.cells import PhonopyAtoms

from aiida_vibroscopy.utils.elfield_cards_functions import get_tuple_from_vector, get_vector_from_number

__all__ = (
    'tensor_3rd_rank_transformation', 'symmetrize_3nd_rank_tensor', 'take_average_of_dph0',
    'symmetrize_susceptibility_derivatives', 'get_connected_fields_with_operations', 'transform_trajectory',
    'get_trajectories_from_symmetries', 'get_irreducible_numbers_and_signs'
)


def tensor_3rd_rank_transformation(rot, mat):
    """Tensor transformation."""
    return np.tensordot(rot, np.tensordot(rot, np.tensordot(rot, mat, axes=[1, 0]), axes=[1, 1]), axes=[1, 2])


def symmetrize_3nd_rank_tensor(tensor, symmetry_operations, lattice):
    """Symmetrize a 3rd rank tensor using symmetry operations in the lattice."""
    sym_cart = [similarity_transformation(lattice.T, r) for r in symmetry_operations]
    sum_tensor = np.zeros_like(tensor)
    for sym in sym_cart:
        sum_tensor += tensor_3rd_rank_transformation(sym, tensor)
    return sum_tensor / len(symmetry_operations)


def take_average_of_dph0(dchi_ph0, rotations, translations, cell, symprec):
    """Symmetrize :math:`\\frac{d \\Chi}{dr}` tensors in respect to space group symmetries
    and applies sum rules (as in *M. Veiten et al., PRB, 71, 125107, (2005)*)."""
    lattice = cell.cell
    positions = cell.scaled_positions
    dchi_ph0_ = np.zeros_like(dchi_ph0)

    for i in range(len(dchi_ph0)):
        for r, t in zip(rotations, translations):
            diff = np.dot(positions, r.T) + t - positions[i]
            diff -= np.rint(diff)
            dist = np.sqrt(np.sum(np.dot(diff, lattice)**2, axis=1))
            j = np.nonzero(dist < symprec)[0][0]
            r_cart = similarity_transformation(lattice.T, r)
            dchi_ph0_[i] += tensor_3rd_rank_transformation(r_cart, dchi_ph0[j])
        dchi_ph0_[i] /= len(rotations)

    # Apply simple sum rules as in `M. Veiten et al., PRB, 71, 125107 (2005)`
    sum_dchi = dchi_ph0_.sum(axis=0) / len(dchi_ph0_)  # sum over atomic index
    dchi_ph0_ -= sum_dchi

    return dchi_ph0_


def symmetrize_susceptibility_derivatives(
    raman_susceptibility,
    nlo_susceptibility,
    ucell,
    primitive_matrix=None,
    primitive=None,
    supercell_matrix=None,
    symprec=1e-5,
    is_symmetry=True,
) -> tuple:
    """Symmetrize susceptibility derivatives tensors (dChi/dr and Chi^2).

    :param raman_susceptibility: array_like dChi/dr tensors, shape=(unitcell_atoms, 3, 3, 3).
        Convention is to have the symmetric elements over the 2 and 3 indices,
        i.e. [I,k,i,j] = [I,k,j,i] <==> k is the index of the displacement.
    :param nlo_susceptibility: array_like Chi^2 tensors, shape=(3, 3, 3)
    :param ucell: PhonopyAtoms unit cell
    :param primitive_matrix: array_like, optional
        Primitive matrix. This is used to select dChi/dr tensors in
        primitive cell. If None (default), dChi/dr tensors in unit cell
        are returned.
        shape=(3, 3)
    :param primitive: PhonopyAtoms
        This is an alternative of giving primitive_matrix (Mp). Mp is given as
            Mp = (a_u, b_u, c_u)^-1 * (a_p, b_p, c_p).
        In addition, the order of atoms is alined to those of atoms in this
        primitive cell for Born effective charges. No rigid rotation of
        crystal structure is assumed.
    :param supercell_matrix: array_like, optional
        Supercell matrix. This is used to select Born effective charges in
        **primitive cell**. Supercell matrix is needed because primitive
        cell is created first creating supercell from unit cell, then
        the primitive cell is created from the supercell. If None (defautl),
        1x1x1 supercell is created.
        shape=(3, 3)
    :param symprec: float, optional
        Symmetry tolerance. Default is 1e-5
    :param is_symmetry: bool, optinal
        By setting False, symmetrization can be switched off. Default is True.

    :return: symmetrized tensors (dph0, nlo)
    """
    from phonopy.structure.symmetry import Symmetry, _get_mapping_between_cells, _get_supercell_and_primitive

    lattice = ucell.cell
    u_sym = Symmetry(ucell, is_symmetry=is_symmetry, symprec=symprec)
    rotations = u_sym.symmetry_operations['rotations']
    translations = u_sym.symmetry_operations['translations']
    ptg_ops = u_sym.pointgroup_operations

    transpose_dph0 = np.transpose(raman_susceptibility, axes=[0, 2, 1, 3])  # transpose i <--> k

    nlo_ = symmetrize_3nd_rank_tensor(nlo_susceptibility, ptg_ops, lattice)
    tdph0_ = take_average_of_dph0(transpose_dph0, rotations, translations, ucell, symprec)
    dph0_ = np.transpose(tdph0_, axes=[0, 2, 1, 3])  # transpose back i <--> k

    if (abs(raman_susceptibility - dph0_) > 0.1).any():
        lines = [
            'Symmetry of dChi/dr tensors is largely broken. '
            'The max difference is:',
            f'{(raman_susceptibility - dph0_).max()}',
        ]
        import warnings

        warnings.warn('\n'.join(lines))

    if primitive_matrix is None and primitive is None:
        return dph0_, nlo_

    pmat = (np.dot(np.linalg.inv(ucell.cell.T), primitive.cell.T) if primitive is not None else primitive_matrix)

    scell, pcell = _get_supercell_and_primitive(
        ucell,
        primitive_matrix=pmat,
        supercell_matrix=supercell_matrix,
        symprec=symprec,
    )

    idx = [scell.u2u_map[i] for i in scell.s2u_map[pcell.p2s_map]]
    dph0_in_prim = dph0_[idx].copy()

    if primitive is None:
        return dph0_in_prim, nlo_

    idx2 = _get_mapping_between_cells(pcell, primitive)
    return dph0_in_prim[idx2].copy(), nlo_


def get_connected_fields_with_operations(
    phonopy_instance: Phonopy,
    field_direction: list,
) -> tuple:
    """Return symmetry equivalent electric field direction (always with zeros ones).

    :param field_direction: (3,) shape list

    :return: tuple as (numpy.ndarray,numpy.ndarray,numpy.ndarray),
        containing equivalent fields and associated rotations and translations
    """
    lattice = phonopy_instance.unitcell.cell
    operations = phonopy_instance.symmetry.symmetry_operations
    rotations = operations['rotations']
    translations = operations['translations']

    directions = []

    for r, t in zip(rotations, translations):
        r_cart = similarity_transformation(lattice.T, r)
        directions.append(tuple(np.dot(r_cart, field_direction).round(2).tolist()))

    directions = [list(direction) for direction in set(directions)]

    not_discarded = [get_vector_from_number(i, 1.) for i in range(6)]
    not_discarded += np.negative(not_discarded).tolist()
    not_discarded = np.array(not_discarded)

    index_to_pop = []
    for i, direction in enumerate(directions):
        diff = not_discarded - direction
        diff_bool = [np.isclose(diff_element, [0, 0, 0]).all() for diff_element in diff]
        if not any(diff_bool):
            index_to_pop.append(i)

    count = 0
    for i in index_to_pop:
        directions.pop(i - count)
        count += 1

    rotations_set = []
    translations_set = []

    directions_copy = []

    for r, t in zip(rotations, translations):
        r_cart = similarity_transformation(lattice.T, r)
        field_cart = np.dot(r_cart, field_direction).round(2).tolist()
        if field_cart in directions:
            rotations_set.append(r)
            translations_set.append(t)
            directions_copy.append(field_cart)
            directions.remove(field_cart)

    return np.array(directions_copy, dtype='int32'), np.array(rotations_set, dtype='int32'), np.array(translations_set)


def transform_trajectory(
    trajectory_data: TrajectoryData,
    rotation: np.ndarray,
    translation: np.ndarray,
    cell: PhonopyAtoms,
    symprec: float,
) -> TrajectoryData:
    """Transform and return the TrajectoryData using rotation and traslation symmetry operations.
    Only `forces` and `electronic_dipole_cartesian_axes` are transformed."""
    new_trajectory = deepcopy(trajectory_data)

    forces = new_trajectory.get_array('forces')[-1]
    polarisation = new_trajectory.get_array('electronic_dipole_cartesian_axes')[-1]

    lattice = cell.cell
    positions = cell.scaled_positions
    r_cart = similarity_transformation(lattice.T, rotation)
    num_atoms = cell.get_number_of_atoms()

    forces_ = np.zeros_like(forces)
    pola_ = np.dot(r_cart, polarisation)

    for i in range(num_atoms):
        diff = np.dot(positions, rotation.T) + translation - positions[i]
        diff -= np.rint(diff)
        dist = np.sqrt(np.sum(np.dot(diff, lattice)**2, axis=1))
        j = np.nonzero(dist < symprec)[0][0]
        forces_[i] = np.dot(r_cart, forces[j])

    new_forces = np.array([forces_])
    new_pola = np.array([pola_])

    new_trajectory.set_array('forces', new_forces)
    new_trajectory.set_array('electronic_dipole_cartesian_axes', new_pola)

    return new_trajectory


def get_trajectories_from_symmetries(
    preprocess_data: PreProcessData,
    data: dict,
    accuracy_order: int,
) -> dict:
    """Return the full dictionary with transformed TrajectoryData using symmetry operation. Only `forces`
    and `electronic_dipole_cartesian_axes` are transformed.

    :return: dict following the standard conventions:
        * main fields are named `field_index_{index}`
        * secondary fields have `{number}`, where number refer to the coeffient for the numerical derivation
    """
    full_data = deepcopy(data)
    phonopy_instance = preprocess_data.get_phonopy_instance()
    symprec = preprocess_data.symprec
    cell = phonopy_instance.unitcell

    for key, value in data.items():  # `data` contains the least amount of trajectories
        # key could be `field_index_2` and value its sub dictionary
        if not len(value) == accuracy_order:  # it means we can extrapolate extra info
            vector = get_vector_from_number(int(key[-1]), 1)
            subvalues = [0 for _ in range(len(value))]

            count = 0  # it counts the numerical order for correct arrangement if data

            # Sanity check to have correct order
            for subkey, subvalue in value.items():
                subvalues[int(subkey)] = subvalue

            fields, rotations, translations = get_connected_fields_with_operations(
                phonopy_instance=phonopy_instance,
                field_direction=vector,
            )

            for trajectory_data in subvalues:

                for field, rotation, translation in zip(fields, rotations, translations):
                    new_trajectory = transform_trajectory(trajectory_data, rotation, translation, cell, symprec)
                    number, sign = get_tuple_from_vector(field)
                    index_key = f'field_index_{number}'
                    index = 0 if sign > 0 else 1
                    index += count
                    try:
                        full_data[index_key][str(index)] = new_trajectory
                    except KeyError:
                        full_data[index_key] = {}
                        full_data[index_key][str(index)] = new_trajectory

                count += 2

    return full_data


def get_irreducible_numbers_and_signs(preprocess_data: PreProcessData, number_id: int) -> tuple:
    """Return tuple with list of independent numbers to run
    and corresponding list of [bool, bool] for the sign to run."""
    phonopy_instance = preprocess_data.get_phonopy_instance()
    irr_numbers = list(range(number_id))
    irr_signs = [[True, True] for _ in range(number_id)]  # we start supposing having no symmetries

    # Checking first for inversion symmetry
    for irr_number in irr_numbers:
        field = get_vector_from_number(irr_number, 1)  # just for consistency
        connected_fields, _, _ = get_connected_fields_with_operations(phonopy_instance, field)
        connected_fields = connected_fields.tolist()
        opposite_field = np.negative(field).tolist()

        if opposite_field in connected_fields:
            irr_signs[irr_number][1] = False  # i.e. we do not have to run it

    # Then we look from 2 (and 3 in case of second order) to remove symmetry
    # equivalent numbers (i.e. equivalent, electric field, directions),
    # which represents the z direction QE is optimized for (3 is for mixed directions,
    # and is chosen arbitrarly among the z-containing mixed directions).
    start_numbers = [2] if len(irr_numbers) == 3 else [2, 3]

    for snumber in start_numbers:
        field = get_vector_from_number(snumber, 1)  # just for consistency
        connected_fields, _, _ = get_connected_fields_with_operations(phonopy_instance, field)
        connected_fields = connected_fields.tolist()
        connected_fields.remove(field)  # we know for sure that the identity operator exists

        for cfield in connected_fields:
            number, _ = get_tuple_from_vector(cfield)
            if number != snumber:
                try:
                    index = irr_numbers.index(number)
                    irr_numbers.pop(index)
                    irr_signs.pop(index)
                except ValueError:
                    pass

    final_number = deepcopy(irr_numbers)

    for fnumber in final_number:
        field = get_vector_from_number(fnumber, 1)  # just for consistency
        connected_fields, _, _ = get_connected_fields_with_operations(phonopy_instance, field)
        connected_fields = connected_fields.tolist()
        connected_fields.remove(field)  # we know for sure that the identity operator exists

        for cfield in connected_fields:
            number, _ = get_tuple_from_vector(cfield)
            if number != fnumber:
                try:
                    index = irr_numbers.index(number)
                    irr_numbers.pop(index)
                    irr_signs.pop(index)
                except ValueError:
                    pass

    return irr_numbers, irr_signs