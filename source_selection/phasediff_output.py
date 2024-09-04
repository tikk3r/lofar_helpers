"""
WARNING: THIS SCRIPT HAS BEEN MOVED TO https://github.com/rvweeren/lofar_facet_selfcal REPOSITORY

This script is used to derive a S/N selection score by using an h5parm with scalarphasediff solutions from facetselfcal.
This is described in Section 3.3 of de Jong et al. (2024)
"""

author__ = "Jurjen de Jong (jurjendejong@strw.leidenuniv.nl)"
__all__ = ['GetSolint']

import tables
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import circstd
from glob import glob
import csv
import sys
from argparse import ArgumentParser
from typing import Union

try: # fix this
    from selfcal_selection import parse_source_from_h5
    import scienceplots
    plt.style.use(['science', 'ieee'])
except ImportError:
    pass


def make_utf8(inp):
    """
    Convert input to utf8 instead of bytes

    :param inp: string input
    :return: input in utf-8 format
    """

    try:
        inp = inp.decode('utf8')
        return inp
    except (UnicodeDecodeError, AttributeError):
        return inp


def rad_to_degree(inp):
    """
    Check if radians and convert to degree

    :param inp: two coordinates (RA, DEC)
    :return: output in degrees
    """

    try:
        if abs(inp[0]) < np.pi and abs(inp[1]) < np.pi:
            return inp * 360 / 2 / np.pi % 360
        else:
            return inp
    except ValueError: # Sorry for the ugly code..
        if abs(inp[0][0]) < np.pi and abs(inp[0][1]) < np.pi:
            return inp[0] * 360 / 2 / np.pi % 360
        else:
            return inp[0]


class GetSolint:
    def __init__(self, h5: str = None, optimal_score: float = 0.5, ref_solint: float = 10., station: str = None):
        """
        Get a score based on the phase difference between XX and YY. This reflects the noise in the observation.
        From this score we can determine an optimal solution interval, by fitting a wrapped normal distribution.

        See:
        - https://en.wikipedia.org/wiki/Wrapped_normal_distribution
        - https://en.wikipedia.org/wiki/Yamartino_method
        - https://en.wikipedia.org/wiki/Directional_statistics

        :param h5: h5parm
        :param optimal_score: score to fit solution interval
        :param ref_solint: reference solution interval
        :param station: station name
        """

        self.h5 = h5
        self.optimal_score = optimal_score
        self.ref_solint = ref_solint
        self.cstd = 0
        self.C = None
        self.station = station
        self.limit = np.pi

    def plot_C(self, title: str = None, saveas: str = None, extrapoints: Union[list, tuple] = None):
        """
        Plot circstd score in function of solint for given C
        """

        # normal_sigmas = [n / 1000 for n in range(1, 10000)]
        # values = [circstd(normal(0, n, 300)) for n in normal_sigmas]
        # x = (self.C*limit**2) / (np.array(normal_sigmas) ** 2) / 2
        bestsolint = self.best_solint
        # plt.plot(x, values, alpha=0.5)
        solints = np.array(range(1, int(max(bestsolint * 200, self.ref_solint * 150)))) / 100
        plt.plot(solints, [self.theoretical_curve(float(t)) for t in solints], color='green')
        plt.scatter([self.ref_solint], [self.cstd], c='blue', label='measurement', s=80, marker='x')
        plt.scatter([bestsolint], [self.optimal_score], color='red', label='best solint', s=80, marker='x')
        if extrapoints is not None:
            plt.scatter(extrapoints[0], extrapoints[1], color='orange', label='other measurements', s=80, marker='x')
        plt.xlim(0, max(bestsolint * 1.5, self.ref_solint * 1.5))
        # plt.xlim(0, 0.2)
        plt.xlabel("solint (min)")
        plt.ylabel("circstd score")
        plt.legend(frameon=True, loc='upper right', fontsize=10)
        if title is not None:
            plt.title(title)
        if saveas is not None:
            plt.savefig(saveas)
        else:
            plt.show()

        return self

    def _circvar_to_normvar(self, circ_var: float = None):
        """
        Convert circular variance to normal variance

        return: circular variance
        """

        if circ_var >= self.limit ** 2:
            return 999 # replacement for infinity
        else:
            return -2 * np.log(1 - circ_var / (self.limit ** 2))

    @property
    def _get_C(self):
        """
        Get constant defining the normal circular distribution

        :return: C
        """

        if self.cstd == 0:
            self.get_phasediff_score(station=self.station)
        normvar = self._circvar_to_normvar(self.cstd ** 2)
        return normvar * self.ref_solint

    def get_phasediff_score(self, station: str = None):
        """
        Calculate score for phasediff

        :return: circular standard deviation score
        """

        H = tables.open_file(self.h5)

        stations = [make_utf8(s) for s in list(H.root.sol000.antenna[:]['name'])]

        if station is None or station == '':
            stations_idx = [stations.index(stion) for stion in stations if
                            ('RS' not in stion) &
                            ('ST' not in stion) &
                            ('CS' not in stion) &
                            ('DE' not in stion) &
                            ('PL' not in stion)]
        else:
            stations_idx = [stations.index(station)]

        axes = str(H.root.sol000.phase000.val.attrs["AXES"]).replace("b'", '').replace("'", '').split(',')
        axes_idx = sorted({ax: axes.index(ax) for ax in axes}.items(), key=lambda x: x[1], reverse=True)

        phase = H.root.sol000.phase000.val[:] * H.root.sol000.phase000.weight[:]
        H.close()

        phasemod = phase % (2 * np.pi)

        for ax in axes_idx:
            if ax[0] == 'pol':  # YX should be zero
                phasemod = phasemod.take(indices=0, axis=ax[1])
            elif ax[0] == 'dir':  # there should just be one direction
                if phasemod.shape[ax[1]] == 1:
                    phasemod = phasemod.take(indices=0, axis=ax[1])
                else:
                    sys.exit('ERROR: This solution file should only contain one direction, but it has ' +
                             str(phasemod.shape[ax[1]]) + ' directions')
            elif ax[0] == 'freq':  # faraday corrected
                if phasemod.shape[ax[1]] == 1:
                    print("WARNING: only 1 frequency --> Skip frequency diff for Faraday correction (score will be less accurate)")
                else:
                    phasemod = np.diff(phasemod, axis=ax[1])
            elif ax[0] == 'ant':  # take only international stations
                phasemod = phasemod.take(indices=stations_idx, axis=ax[1])

        phasemod[phasemod == 0] = np.nan

        self.cstd = circstd(phasemod, nan_policy='omit')

        return circstd(phasemod, nan_policy='omit')

    @property
    def best_solint(self):
        """
        Get optimal solution interval from phasediff, given C

        :return: value corresponding with increase solution interval
        """

        if self.cstd == 0:
            self.get_phasediff_score(station=self.station)
        self.C = self._get_C
        optimal_cirvar = self.optimal_score ** 2
        return self.C / (self._circvar_to_normvar(optimal_cirvar))

    def theoretical_curve(self, t):
        """
        Theoretical curve based on circ statistics
        :return: circular std
        """

        if self.C is None:
            self.C = self._get_C
        return self.limit * np.sqrt(1 - np.exp(-(self.C / (2 * t))))


def parse_args():
    """
    Command line argument parser

    :return: parsed arguments
    """

    parser = ArgumentParser()
    parser.add_argument('--h5', nargs='+', help='selfcal phasediff solutions', default=None)
    parser.add_argument('--station', help='for one specific station', default=None)
    parser.add_argument('--all_stations', action='store_true', help='for all stations specifically')
    parser.add_argument('--make_plot', action='store_true', help='make phasediff plot')
    parser.add_argument('--optimal_score', help='optimal score between 0 and pi', default=2.4, type=float)
    return parser.parse_args()

def main():

    print('WARNING: THIS SCRIPT HAS BEEN MOVED TO https://github.com/rvweeren/lofar_facet_selfcal REPOSITORY\n'
          'This version has therefore not be maintained since September 2024')

    args = parse_args()

    # set std score, for which you want to find the solint
    optimal_score = args.optimal_score

    # reference solution interval
    ref_solint = 10

    h5s = args.h5
    if len(h5s)==1 and ' ' in h5s[0]:
        h5s = h5s[0].split(" ")
    elif h5s is None:
        h5s = glob("P*_phasediff/phasediff0*.h5")

    if args.station is not None:
        station = args.station
    else:
        station = ''

    with open('phasediff_output.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(["source", "spd_score", "best_solint", 'RA', 'DEC'])
        for h5 in h5s:
            # try:
            S = GetSolint(h5, optimal_score, ref_solint)
            if args.all_stations:
                H = tables.open_file(h5)
                stations = [make_utf8(s) for s in list(H.root.sol000.antenna[:]['name'])]
                H.close()
            else:
                stations = [station]
            for station in stations:
                std = S.get_phasediff_score(station=station)
                solint = S.best_solint
                H = tables.open_file(h5)
                dir = rad_to_degree(H.root.sol000.source[:]['dir'])
                writer.writerow([parse_source_from_h5(h5) + station, std, solint, dir[0], dir[1]])
                if args.make_plot:
                    S.plot_C("T=" + str(round(solint, 2)) + " min", saveas=h5 + station + '.png')
                H.close()
            # except:
            #     pass

    # sort output
    df = pd.read_csv('phasediff_output.csv').sort_values(by='spd_score')
    df.to_csv('phasediff_output.csv', index=False)



if __name__ == '__main__':
    main()
