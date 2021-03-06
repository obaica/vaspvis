from pymatgen.electronic_structure.core import Spin, Orbital
from pymatgen.io.vasp.outputs import BSVasprun
from pymatgen.io.vasp.inputs import Kpoints, Poscar
from functools import reduce
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import time


class BandStructure:
    """
    This class contains all the methods for constructing band structures
    from the outputs of VASP band structure calculations.
    """

    def __init__(self, folder, projected=False, hse=False, spin='up', kpath=None, n=None):
        """
        Initialize parameters upon the generation of this class

        Inputs:
        ----------
        folder: (str) This is the folder that contains the VASP files
        projected: (bool) Determined wheter of not to parte the projected
            eigenvalues from the vasprun.xml file. Making this true
            increases the computational time, so only use if a projected
            band structure is required.
        hse: (bool) Determines if the KPOINTS file is in the form of HSE
            or not. Only make true if the band structure was calculated
            using a hybrid functional.
        spin: (str) Choose which spin direction to parse. ('up' or 'down')
        """

        self.vasprun = BSVasprun(
            f'{folder}/vasprun.xml',
            parse_projected_eigen=projected
        )
        self.poscar = Poscar.from_file(
            f'{folder}/POSCAR',
            check_for_POTCAR=False,
            read_velocities=False
        )
        self.projected = projected
        self.hse = hse
        self.kpath = kpath
        self.n = n
        self.folder = folder
        self.spin = 'up'
        self.spin_dict = {'up': Spin.up, 'dowm': Spin.down}
        self.bands_dict = self.load_bands()
        self.color_dict = {
            0: '#FF0000',
            1: '#0000FF',
            2: '#008000',
            3: '#800080',
            4: '#E09200',
            5: '#FF5C77',
            6: '#778392',
            7: '#07C589',
            8: '#40BAF2',
        }

        if projected:
            self.projected_dict = self.load_projected_bands()

        if not hse:
            self.kpoints = Kpoints.from_file(f'{folder}/KPOINTS')

    def load_bands(self):
        """
        This function is used to load eigenvalues from the vasprun.xml
        file and into a dictionary which is in the form of
        band index --> eigenvalues

        Output:
        ---------
        bands_dict: (dict[str][np.ndarray]) Dictionary which contains
            the eigenvalues for each band
        """

        spin = self.spin

        if self.hse:
            kpoints_band = self.n * (len(self.kpath) - 1)
            eigenvalues = self.vasprun.eigenvalues[
                self.spin_dict[spin]
            ][-1 * kpoints_band:]
        else:
            eigenvalues = self.vasprun.eigenvalues[self.spin_dict[spin]]

        efermi = self.vasprun.efermi
        nkpoints = len(eigenvalues)
        nbands = len(eigenvalues[0])

        bands_dict = {f'band{i+1}': [] for i in range(nbands)}

        for i in range(nkpoints):
            for j in range(nbands):
                bands_dict[f'band{j+1}'].append(
                    eigenvalues[i][j][0] - efermi
                )

        return bands_dict

    def load_projected_bands(self):
        """
        This function loads the project weights of the orbitals in each band
        from vasprun.xml into a dictionary of the form:
        band index --> atom index --> weights of orbitals

        Output:
        ----------
        projected_dict: (dict([str][int][pd.DataFrame])) Dictionary containing the
            projected weights of all orbitals on each atom for each band.
        """

        spin = self.spin

        if self.hse:
            kpoints_band = self.n * (len(self.kpath) - 1)
            projected_eigenvalues = self.vasprun.projected_eigenvalues[
                self.spin_dict[spin]
            ][-1 * kpoints_band:]
        else:
            projected_eigenvalues = self.vasprun.projected_eigenvalues[
                self.spin_dict[spin]
            ]

        poscar = Poscar.from_file(
            f'{self.folder}/POSCAR',
            check_for_POTCAR=False,
            read_velocities=False
        )
        spin = self.spin
        natoms = np.sum(poscar.natoms)
        nkpoints = len(projected_eigenvalues)
        nbands = len(projected_eigenvalues[0])

        projected_dict = {f'band{i+1}':
                          {atom: np.zeros(9) for atom in range(natoms)}
                          for i in range(nbands)}

        for i in range(nkpoints):
            for j in range(nbands):
                band = f'band{j+1}'
                for atom in range(natoms):
                    orbital_weights = projected_eigenvalues[i][j][atom]
                    projected_dict[band][atom] = np.vstack([
                        projected_dict[band][atom],
                        orbital_weights
                    ])

        for band in projected_dict:
            for atom in projected_dict[band]:
                projected_dict[band][atom] = pd.DataFrame(
                    projected_dict[band][atom][1:]
                )

        return projected_dict

    def sum_spd(self):
        """
        This function sums the weights of the s, p, and d orbitals for each atom
        and creates a dictionary of the form:
        band index --> s,p,d orbital weights

        Outputs:
        ----------
        spd_dict: (dict([str][pd.DataFrame])) Dictionary that contains the summed
            weights for the s, p, and d orbitals for each band
        """

        spd_orbitals = {'s': [0], 'p': [1, 2, 3], 'd': [4, 5, 6, 7, 8]}

        spd_dict = {band: np.nan for band in self.projected_dict}

        for band in self.projected_dict:
            atom_list = [
                self.projected_dict[band][atom] for atom in self.projected_dict[band]]
            spd_dict[band] = reduce(
                lambda x, y: x.add(y, fill_value=0), atom_list
            )

        for band in spd_dict:
            df = spd_dict[band]
            spd_dict[band]['s'] = df[0]
            spd_dict[band]['p'] = df[1] + df[2] + df[3]
            spd_dict[band]['d'] = df[4] + df[5] + df[6] + df[7] + df[8]
            spd_dict[band] = spd_dict[band].drop(columns=range(9))

        return spd_dict

    def sum_orbitals(self, orbitals):
        """
        This function finds the weights of desired orbitals for all atoms and
            returns a dictionary of the form:
            band index --> orbital index

        Inputs:
        ----------
        orbitals: (list) List of desired orbitals. 
            0 = s
            1 = py
            2 = pz
            3 = px
            4 = dxy
            5 = dyz
            6 = dz2
            7 = dxz
            8 = dx2-y2

        Outputs:
        ----------
        orbital_dict: (dict[str][pd.DataFrame]) Dictionary that contains the projected
            weights of the selected orbitals.
        """

        orbital_dict = {band: np.nan for band in self.projected_dict}

        for band in self.projected_dict:
            atom_list = [
                self.projected_dict[band][atom] for atom in self.projected_dict[band]]
            orbital_dict[band] = reduce(
                lambda x, y: x.add(y, fill_value=0), atom_list
            )

        for band in orbital_dict:
            df = orbital_dict[band]
            for col in df.columns.tolist():
                if sum(np.isin(orbitals, col)) == 0:
                    orbital_dict[band] = orbital_dict[band].drop(columns=col)

        return orbital_dict

    def sum_atoms(self, atoms):
        """
        This function finds the weights of desired atoms for all orbitals and
            returns a dictionary of the form:
            band index --> atom index

        Inputs:
        ----------
        atoms: (list) List of desired atoms where atom 0 is the first atom in
            the POSCAR file. 

        Outputs:
        ----------
        atom_dict: (dict[str][pd.DataFrame]) Dictionary that contains the projected
            weights of the selected atoms.
        """

        projected_dict = self.projected_dict
        atoms_dict = {band: np.nan for band in projected_dict}

        for band in projected_dict:
            atom_dict = {atom: projected_dict[band][atom].sum(
                axis=1) for atom in atoms}
            atoms_dict[band] = pd.DataFrame.from_dict(atom_dict)

        return atoms_dict

    def sum_elements(self, elements, orbitals=False, spd=False):
        """
        This function sums the weights of the orbitals of specific elements within the
        calculated structure and returns a dictionary of the form:
        band index --> element label --> orbital weights for orbitals = False
        band index --> element label for orbitals = True
        This is useful for structures with many elements because manually entering indicies is
        not practical for large structures.

        Inputs:
        ----------
        elements: (list) List of element symbols to sum the weights of.
        orbitals: (bool) Determines whether or not to inclue orbitals or not
            (True = keep orbitals, False = sum orbitals together )
        spd: (bool) Determines whether or not to sum the s, p, and d orbitals


        Outputs:
        ----------
        element_dict: (dict([str][str][pd.DataFrame])) Dictionary that contains the summed
            weights for each orbital for a given element in the structure.
        """

        poscar = self.poscar
        natoms = poscar.natoms
        symbols = poscar.site_symbols
        projected_dict = self.projected_dict

        element_list = np.hstack(
            [[symbols[i] for j in range(natoms[i])]
             for i in range(len(symbols))]
        )

        element_dict = {
            band: {element: [] for element in elements} for band in projected_dict
        }

        for band in projected_dict:
            band_df = pd.DataFrame()
            for element in elements:
                element_index = np.where(element_list == element)[0]
                df = pd.concat(
                    [projected_dict[band][i] for i in element_index],
                    axis=1
                )

                if orbitals:
                    element_dict[band][element] = df.groupby(
                        by=df.columns,
                        axis=1
                    ).sum()
                    if spd:
                        df = element_dict[band][element]
                        element_dict[band][element]['s'] = df[0]
                        element_dict[band][element]['p'] = df[1] + \
                            df[2] + df[3]
                        element_dict[band][element]['d'] = df[4] + \
                            df[5] + df[6] + df[7] + df[8]
                        element_dict[band][element] = element_dict[band][element].drop(
                            columns=range(9))
                else:
                    element_dict[band][element] = df.sum(axis=1).tolist()

        return element_dict

    def get_kticks(self, ax):
        """
        This function extracts the kpoint labels and index locations for a regular
        band structure calculation (non HSE).

        Inputs:
        ----------
        ax: (matplotlib.pyplot.axis) Axis to append the tick labels
        """

        high_sym_points = self.kpoints.kpts
        kpts_labels = np.array([f'${k}$' for k in self.kpoints.labels])
        all_kpoints = self.vasprun.actual_kpoints

        index = [0]
        for i in range(len(high_sym_points) - 2):
            if high_sym_points[i + 2] != high_sym_points[i + 1]:
                index.append(i)
        index.append(len(high_sym_points) - 1)

        kpts_loc = np.isin(all_kpoints, high_sym_points).all(1)
        kpoints_index = np.where(kpts_loc == True)[0]

        kpts_labels = kpts_labels[index]
        kpoints_index = list(kpoints_index[index])

        for i in range(len(kpoints_index)):
            if 0 < i < len(kpoints_index) - 1:
                kpoints_index[i] = kpoints_index[i] + 0.5

        for k in kpoints_index:
            ax.axvline(x=k, color='black', alpha=0.7, linewidth=0.5)

        plt.xticks(kpoints_index, kpts_labels)

    def get_kticks_hse(self, ax, kpath, n):

        kpoints_index = [(i*n) - 1 for i in range(len(kpath))
                         if 0 < i < len(kpath)-1]
        kpoints_index.append(n*(len(kpath) - 1)-1)
        kpoints_index.insert(0, 0)

        kpath = [f'${k}$' if k !=
                 'G' else '$\\Gamma$' for k in kpath.upper().strip()]

        for i in range(len(kpoints_index)):
            if 0 < i < len(kpoints_index) - 1:
                kpoints_index[i] = kpoints_index[i] + 0.5

        for k in kpoints_index:
            ax.axvline(x=k, color='black', alpha=0.7, linewidth=0.5)

        plt.xticks(kpoints_index, kpath)

    def plot_plain(self, ax, color='black', linewidth=1.5):
        """
        This function plots a plain band structure given that the band data
        has already been loaded with the load_bands() method.

        Inputs:
        ----------
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        color: (str) Color of the band structure lines
        linewidth: (float) Line width of the band structure lines
        """

        wave_vector = range(len(self.bands_dict['band1']))

        for band in self.bands_dict:
            band_values = self.bands_dict[band]
            ax.plot(
                wave_vector,
                band_values,
                color=color,
                linewidth=linewidth,
                zorder=0,
            )

        if self.hse:
            self.get_kticks_hse(ax=ax, kpath=self.kpath, n=self.n)
        else:
            self.get_kticks(ax=ax)

        plt.xlim(0, len(wave_vector)-1)

    def plot_spd(self, ax, scale_factor=5, order=['s', 'p', 'd'], color_dict=None):
        """
        This function plots the s, p, d projected band structure given that the band
        data has already been loaded with the load_bands() and load_projected_bands()
        methods

        Inputs:
        ----------
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        order: (list) This determines the order in which the points are plotted on the
            graph. This is an option because sometimes certain orbitals can be hidden
            under other orbitals because they have a larger weight. For example, if the
            signitures of the d orbitals are greater than that of the s orbitals, it
            might be smart to choose ['d', 'p', 's'] as the order so the s orbitals are
            plotted over the d orbitals.
        color_dict: (dict[str][str]) This option allow the colors of the s, p, and d
            orbitals to be specified. Should be in the form of:
            {'s': <s color>, 'p': <p color>, 'd': <d color>}
        """

        spd_dict = self.sum_spd()

        if color_dict is None:
            color_dict = {
                's': self.color_dict[0],
                'p': self.color_dict[1],
                'd': self.color_dict[2],
            }

        self.plot_plain(ax, linewidth=0.5)

        plot_df = pd.DataFrame(columns=['s', 'p', 'd'])
        plot_band = []
        plot_wave_vec = []

        for band in spd_dict:
            plot_df = plot_df.append(spd_dict[band])
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(spd_dict[band])))

        for col in order:
            ax.scatter(
                plot_wave_vec,
                plot_band,
                c=color_dict[col],
                s=scale_factor * plot_df[col],
                zorder=1,
            )

    def plot_atom_orbitals(self, atom_orbital_pairs, ax, scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure of individual orbitals on
        individual atoms given that the band data has already been loaded with the
        load_bands() and load_projected_bands() methods

        Inputs:
        -----------
        atom_orbital_pairs: (list[list]): Selected orbitals on selected atoms to plot.
            This should take the form of [[atom index, orbital_index], ...]. 
            To plot the px orbital of the 1st atom and the pz orbital of the 2nd atom
            in the POSCAR file, the input would be [[0, 3], [1, 2]]
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        colors: (dict[int][str]) Dictionary of colors for the atom-orbital pairs in          the order that the atom-orbital pairs were given.
        """

        self.plot_plain(ax=ax, linewidth=0.75)
        # self.get_kticks(ax=ax)

        projected_dict = self.projected_dict
        wave_vector = range(len(self.bands_dict['band1']))

        if color_dict is None:
            color_dict = self.color_dict

        for band in projected_dict:
            for (i, atom_orbital_pair) in enumerate(atom_orbital_pairs):
                atom = atom_orbital_pair[0]
                orbital = atom_orbital_pair[1]

                ax.scatter(
                    wave_vector,
                    self.bands_dict[band],
                    c=color_dict[i],
                    s=scale_factor * projected_dict[band][atom][orbital]
                )

    def plot_orbitals(self, orbitals, ax, scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure of given orbitals summed
        across all atoms given that the band data has already been loaded with the
        load_bands() and load_projected_bands() methods.

        Inputs:
        ----------
        orbitals: (list) List of orbits to compare
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        color_dict: (dict[str][str]) This option allow the colors of each orbital
            specified. Should be in the form of:
            {'orbital index': <color>, 'orbital index': <color>, ...}
        """
        self.plot_plain(ax=ax, linewidth=0.75)
        # self.get_kticks(ax=ax)

        orbital_dict = self.sum_orbitals(orbitals=orbitals)

        if color_dict is None:
            color_dict = self.color_dict

        plot_df = pd.DataFrame(columns=orbitals)
        plot_band = []
        plot_wave_vec = []

        for band in orbital_dict:
            plot_df = plot_df.append(orbital_dict[band])
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(orbital_dict[band])))

        for orbital in orbitals:
            ax.scatter(
                plot_wave_vec,
                plot_band,
                c=color_dict[orbital],
                s=scale_factor * plot_df[orbital],
                zorder=1,
            )

    def plot_atoms(self, atoms, ax, scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure of given orbitals summed
        across all atoms given that the band data has already been loaded with the
        load_bands() and load_projected_bands() methods.

        Inputs:
        ----------
        atoms: (list) List of atoms to compare
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        color_dict: (dict[str][str]) This option allow the colors of each orbital
            specified. Should be in the form of:
            {'orbital index': <color>, 'orbital index': <color>, ...}
        """

        self.plot_plain(ax=ax, linewidth=0.75)

        atom_dict = self.sum_atoms(atoms=atoms)

        if color_dict is None:
            color_dict = self.color_dict

        plot_df = pd.DataFrame(columns=atoms)
        plot_band = []
        plot_wave_vec = []

        for band in atom_dict:
            plot_df = plot_df.append(atom_dict[band], ignore_index=True)
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(atom_dict[band])))

        for atom in atoms:
            ax.scatter(
                plot_wave_vec,
                plot_band,
                c=color_dict[atom],
                s=scale_factor * plot_df[atom],
                zorder=1,
            )

    def plot_elements(self, elements, ax, scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure on each element in
        the calculated structure. This is useful for supercells where the are
        many atoms of the same element and it is inconvienient to manually
        list each index in the POSCAR.

        Inputs:
        ----------
        elements: (list) List of element symbols to project onto
        orbitals: (list) List of orbitals to plot for each element listed.
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        color_dict: (dict[str][str]) This option allow the colors of each orbital
            specified. Should be in the form of:
            {'orbital index': <color>, 'orbital index': <color>, ...}

        """

        self.plot_plain(ax=ax, linewidth=0.75)

        element_dict = self.sum_elements(elements=elements, orbitals=False)

        if color_dict is None:
            color_dict = self.color_dict

        plot_element = {element: [] for element in elements}
        plot_band = []
        plot_wave_vec = []

        for band in element_dict:
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(self.bands_dict[band])))
            for element in elements:
                plot_element[element].extend(element_dict[band][element])

        for (i, element) in enumerate(elements):
            ax.scatter(
                plot_wave_vec,
                plot_band,
                c=color_dict[i],
                s=scale_factor * plot_element[element],
                zorder=1,
            )

    def plot_element_orbitals(self, elements, orbitals, ax, scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure on each element in
        the calculated structure. This is useful for supercells where the are
        many atoms of the same element and it is inconvienient to manually
        list each index in the POSCAR.

        Inputs:
        ----------
        elements: (list) List of element symbols to project onto
        orbitals: (list) List of orbitals to plot for each element listed.
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        color_dict: (dict[str][str]) This option allow the colors of each orbital
            specified. Should be in the form of:
            {'orbital index': <color>, 'orbital index': <color>, ...}

        """

        self.plot_plain(ax=ax, linewidth=0.75)

        element_dict = self.sum_elements(elements=elements, orbitals=True)

        if color_dict is None:
            color_dict = self.color_dict

        plot_element = {element: pd.DataFrame(
            columns=[range(9)]) for element in elements}
        plot_band = []
        plot_wave_vec = []

        for band in element_dict:
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(self.bands_dict[band])))
            for element in elements:
                plot_element[element] = plot_element[element].append(
                    element_dict[band][element])

        for (i, element) in enumerate(elements):
            for orbital in orbitals:
                ax.scatter(
                    plot_wave_vec,
                    plot_band,
                    c=color_dict[orbital],
                    s=scale_factor * plot_element[element][orbital],
                    zorder=1,
                )

    def plot_element_spd(self, elements, ax, order=['s', 'p', 'd'], scale_factor=5, color_dict=None):
        """
        This function plots the projected band structure on each element in
        the calculated structure. This is useful for supercells where the are
        many atoms of the same element and it is inconvienient to manually
        list each index in the POSCAR.

        Inputs:
        ----------
        elements: (list) List of element symbols to project onto
        ax: (matplotlib.pyplot.axis) Axis to plot the data on
        scale_factor: (float) Factor to scale weights. This changes the size of the
            points in the scatter plot
        order: (list) This determines the order in which the points are plotted on the
            graph. This is an option because sometimes certain orbitals can be hidden
            under other orbitals because they have a larger weight. For example, if the
            signitures of the d orbitals are greater than that of the s orbitals, it
            might be smart to choose ['d', 'p', 's'] as the order so the s orbitals are
            plotted over the d orbitals.
        color_dict: (dict[str][str]) This option allow the colors of the s, p, and d
            orbitals to be specified. Should be in the form of:
            {'s': <s color>, 'p': <p color>, 'd': <d color>}

        """

        self.plot_plain(ax=ax, linewidth=0.75)

        element_dict = self.sum_elements(
            elements=elements, orbitals=True, spd=True)

        if color_dict is None:
            color_dict = {
                's': self.color_dict[0],
                'p': self.color_dict[1],
                'd': self.color_dict[2],
            }

        plot_element = {element: pd.DataFrame(
            columns=['s', 'p', 'd']) for element in elements}
        plot_band = []
        plot_wave_vec = []

        for band in element_dict:
            plot_band.extend(self.bands_dict[band])
            plot_wave_vec.extend(range(len(self.bands_dict[band])))
            for element in elements:
                plot_element[element] = plot_element[element].append(
                    element_dict[band][element])

        for (i, element) in enumerate(elements):
            for orbital in order:
                ax.scatter(
                    plot_wave_vec,
                    plot_band,
                    c=color_dict[orbital],
                    s=scale_factor * plot_element[element][orbital],
                    zorder=1,
                )


def main():
    bands = BandStructure(
        folder='../../vaspvis_data/hse',
        projected=True,
        spin='up',
        hse=True,
        kpath='GXWLGK',
        n=20,
    )
    fig = plt.figure(figsize=(4, 3), dpi=300)
    ax = fig.add_subplot(111)
    # bands.get_kticks_hse(ax=ax, kpath='GXWLGK', n=20)

    # bands.get_kticks(ax=ax)
    # bands.plot_spd(ax=ax, order=['s', 'p', 'd'], scale_factor=9)
    # bands.plot_plain(ax=ax, linewidth=1)
    # bands.plot_atom_orbitals(ax=ax, atom_orbital_pairs=[[0, 0], [1, 3]])
    # bands.plot_atoms(ax=ax, atoms=[0])
    # element_dict = bands.sum_elements(elements=['In'])
    bands.plot_element_spd(ax=ax, elements=['As'])
    plt.ylim(-7, 6)
    plt.ylabel('$E - E_F$ $(eV)$', fontsize=6)
    plt.tick_params(labelsize=6, length=1.5)
    plt.tick_params(axis='x', length=0)
    plt.tight_layout(pad=0.5)
    plt.savefig('bs_InSb1110_spd2.png')
    plt.show()


if __name__ == "__main__":
    main()
