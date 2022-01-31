from past.utils import old_div
import numpy as np
from astropy.wcs import WCS
from astropy.io import fits
from astropy.nddata import Cutout2D
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
from reproject import reproject_interp
import string
import sys
from astropy.modeling.models import Gaussian2D
from astropy.convolution import convolve, Gaussian2DKernel
from matplotlib.ticker import LogLocator, LogFormatterSciNotation as LogFormatter
import os
from scipy.ndimage import gaussian_filter


def flatten(f):
    """ Flatten a fits file so that it becomes a 2D image. Return new header and data """

    naxis = f[0].header['NAXIS']
    if naxis < 2:
        sys.exit('Can\'t make map from this')
    if naxis == 2:
        return fits.PrimaryHDU(header=f[0].header, data=f[0].data)

    w = WCS(f[0].header)
    wn = WCS(naxis=2)

    wn.wcs.crpix[0] = w.wcs.crpix[0]
    wn.wcs.crpix[1] = w.wcs.crpix[1]
    wn.wcs.cdelt = w.wcs.cdelt[0:2]
    wn.wcs.crval = w.wcs.crval[0:2]
    wn.wcs.ctype[0] = w.wcs.ctype[0]
    wn.wcs.ctype[1] = w.wcs.ctype[1]

    header = wn.to_header()
    header["NAXIS"] = 2
    copy = ('EQUINOX', 'EPOCH', 'BMAJ', 'BMIN', 'BPA', 'RESTFRQ', 'TELESCOP', 'OBSERVER')
    for k in copy:
        r = f[0].header.get(k)
        if r is not None:
            header[k] = r

    slice = []
    for i in range(naxis, 0, -1):
        if i <= 2:
            slice.append(np.s_[:], )
        else:
            slice.append(0)

    hdu = fits.PrimaryHDU(header=header, data=f[0].data[slice])
    return hdu

def reproject_hdu(hdu1, hdu2, outputname):

    array, _ = reproject_interp(hdu2, hdu1.header)
    fits.writeto(outputname, array, hdu1.header, overwrite=True)

    return

class Imaging:

    def __init__(self, fits_file: str = None):
        self.hdu = fits.open(fits_file)
        self.image_data = self.hdu[0].data
        while len(self.image_data.shape) != 2:
            self.image_data = self.image_data[0]
        self.wcs = WCS(self.hdu[0].header, naxis=2)
        self.header = self.wcs.to_header()
        self.rms = self.noise
        self.rms_full = self.rms.copy()

    def make_image(self, image_data=None, cmap: str = 'CMRmap', vmin=None, vmax=None):
        """
        Image your data with this method.
        image_data -> insert your image_data or plot full image
        cmap -> choose your preferred cmap
        """

        if vmin is None:
            vmin = self.rms
        else:
            vmin = vmin
        if vmax is None:
            vmax = self.rms*25

        if image_data is None:
            image_data = self.image_data

        plt.figure(figsize=(7, 10))
        plt.subplot(projection=self.wcs)
        im = plt.imshow(image_data, origin='lower', cmap=cmap)
        im.set_norm(SymLogNorm(linthresh=vmin*10, vmin=vmin, vmax=vmax, base=10))
        plt.xlabel('Galactic Longitude')
        plt.ylabel('Galactic Latitude')
        cbar = plt.colorbar(orientation='horizontal', shrink=1)
        # cbar.ax.set_xscale('log')
        cbar.locator = LogLocator()
        cbar.formatter = LogFormatter()
        cbar.update_normal(im)
        cbar.set_label('Surface brightness [Jy/beam]')
        plt.show()

        return self

    def taper(self, gaussian):
        # Gaussian2DKernel(gaussian)
        # gauss_kernel = Gaussian2DKernel(100)
        # self.image_data = convolve(self.image_data, gauss_kernel)
        self.image_data = gaussian_filter(self.image_data, sigma=1)
        self.rms = self.noise
        return self

    def reproject_map(self, input, output):

        hduflat1 = flatten(self.hdu)

        hdu2 = fits.open(input)
        hduflat2 = flatten(hdu2)

        reproject_hdu(hduflat1, hduflat2, output)

        return self

    def make_contourplot(self, image_data=None, maxlevel=None, minlevel=None, steps=None, wcs=None, title=None, smallcutout=False):

        if image_data is None:
            image_data = self.image_data

        if maxlevel is None:
            maxlevel = np.max(image_data)
            if smallcutout:
                maxlevel = self.rms_full/0.0001892

        if wcs is None:
            wcs = self.wcs

        if minlevel is None:
            minlevel = self.rms*1.5
            if smallcutout:
                minlevel = self.rms_full/0.2521040

        if steps is None:
            steps = 1000

        image_data = np.clip(image_data, a_min=np.min(image_data), a_max=maxlevel*0.99)
        plt.figure(figsize=(7, 10))
        plt.subplot(projection=wcs)

        if smallcutout:
            levels = [minlevel/1.5]
        else:
            levels = [minlevel]
        for _ in range(50):
            levels.append(levels[-1]*2)

        levels2 = np.linspace(minlevel, maxlevel, steps)

        norm = SymLogNorm(linthresh=minlevel, vmin=minlevel, vmax=maxlevel, base=10)

        plt.contour(image_data, levels, colors=('k'), linestyles=('-'), linewidths=(0.3,))
        plt.contourf(image_data, levels2, cmap='Blues', norm=norm)
        cbar = plt.colorbar(orientation='horizontal', shrink=1,
                            ticks=[round(a, 5) for a in np.logspace(np.log(minlevel), np.log(maxlevel), 4, endpoint=True)])
        cbar.set_label('Surface brightness [Jy/beam]')
        cbar.ax.set_xscale('log')
        plt.xlabel('Right Ascension (J2000)')
        plt.ylabel('Declination (J2000)')
        plt.title(title)
        plt.show()

        return self

    def get_xray(self, fitsfile, reproject=True):
        if reproject:
            for f in [fitsfile, fitsfile.replace('.fits','_bkg.fits'), fitsfile.replace('.fits', '_exp.fits')]:
                fnew = f.replace('.fits','_reproj.fits')
                self.reproject_map(f, fnew)
                if 'bkg' in f:
                    hdu_bkg = fits.open(fnew)
                    data_bkg = hdu_bkg[0].data
                elif 'exp' in f:
                    hdu_exp = fits.open(fnew)
                    data_exp = hdu_exp[0].data
                else:
                    hdu = fits.open(fnew)
                    data = hdu[0].data

        else:
            hdu = fits.open(fitsfile)
            hdu_bkg = fits.open(fitsfile.replace('.fits', '_bkg.fits'))
            hdu_exp = fits.open(fitsfile.replace('.fits', '_exp.fits'))

            data = hdu[0].data
            data_bkg = hdu_bkg[0].data
            data_exp = hdu_exp[0].data

        return (data - data_bkg)/data_exp

    def make_bridge_overlay_contourplot(self, fitsfile=None, minlevel_1=None, maxlevel_1=None, maxlevel_2=None,
                                 minlevel_2=None, steps_1=1000, steps_2=None, title=None, convolve_2=False, xray=False):

        self.reproject_map(fitsfile, 'test.fits')

        hdu = fits.open('test.fits')
        if xray:
            image_data_2 = self.get_xray(fitsfile, reproject=True)
        else:
            image_data_2 = hdu[0].data

        while len(image_data_2.shape) != 2:
            image_data_2 = image_data_2[0]
        wcs_2 = WCS(hdu[0].header)

        if convolve_2:
            gauss_kernel = Gaussian2DKernel(10)
            image_data_2 = convolve(image_data_2, gauss_kernel)

        if maxlevel_2 is None:
            maxlevel_2 = np.max(image_data_2)

        if minlevel_2 is None:
            minlevel_2 = self.get_noise(image_data_2)
            if xray:
                minlevel_2*=10

        if maxlevel_1 is None:
            maxlevel_1 = np.max(self.image_data)

        if minlevel_1 is None:
            minlevel_1 = self.rms*3


        # image_data_2 = np.clip(image_data_2, a_min=0, a_max=maxlevel_2)
        plt.figure(figsize=(7, 10))
        plt.subplot(projection=wcs_2)

        levels_2 = [minlevel_2]
        for _ in range(10):
            levels_2.append(levels_2[-1]*2)

        levels_1 = np.linspace(minlevel_1, maxlevel_1, steps_1)

        plt.contour(image_data_2, levels_2, colors=('r'), linestyles=('-'), linewidths=(1,))
        plt.imshow(np.where(self.image_data<levels_1[-1], 0, 1), cmap='Greys')
        plt.contourf(np.clip(self.image_data, a_min=levels_1[0], a_max=np.max(self.image_data)), levels_1, cmap='Blues')
        cbar = plt.colorbar(orientation='horizontal', shrink=1, ticks=[round(a, 4) for a in np.linspace(minlevel_1, maxlevel_1, 4)])
        cbar.set_label('Surface brightness  [Jy/beam]')
        # cbar.ax.set_xscale('log')
        plt.xlabel('Right Ascension (J2000)')
        plt.ylabel('Declination (J2000)')
        plt.title(title)
        plt.show()

    def make_cutout(self, pos: tuple = None, size: tuple = (1000, 1000)):
        """
        Make cutout from your image with this method.
        pos (tuple) -> position in pixels
        size (tuple) -> size of your image in pixel size, default=(1000,1000)
        """
        out = Cutout2D(
            data=self.image_data,
            position=pos,
            size=size,
            wcs=self.wcs,
            mode='partial'
        )

        self.hdu = [fits.PrimaryHDU(out.data, header=out.wcs.to_header())]
        self.image_data = out.data
        self.wcs = out.wcs
        self.rms = self.noise

        return self

    @property
    def noise(self):
        """
        from Cyril Tasse/kMS
        """
        maskSup = 1e-7
        m = self.image_data[np.abs(self.image_data)>maskSup]
        rmsold = np.std(m)
        diff = 1e-1
        cut = 3.
        med = np.median(m)
        for _ in range(10):
            ind = np.where(np.abs(m - med) < rmsold*cut)[0]
            rms = np.std(m[ind])
            if np.abs(old_div((rms-rmsold), rmsold)) < diff: break
            rmsold = rms
        print('Noise : ' + str(round(rms * 1000, 2)) + ' mJy/beam')
        self.rms = rms
        return rms

    def get_noise(self, image_data):
        """
        from Cyril Tasse/kMS
        """
        maskSup = 1e-7
        m = image_data[np.abs(image_data)>maskSup]
        rmsold = np.std(m)
        diff = 1e-1
        cut = 3.
        med = np.median(m)
        for _ in range(10):
            ind = np.where(np.abs(m - med) < rmsold*cut)[0]
            rms = np.std(m[ind])
            if np.abs(old_div((rms-rmsold), rmsold)) < diff: break
            rmsold = rms
        print('Noise : ' + str(round(rms * 1000, 2)) + ' mJy/beam')
        return rms

if __name__ == '__main__':



    Image = Imaging(f'../fits/60all.fits')
    #
    Image.make_cutout(pos=(int(Image.image_data.shape[0]/2), int(Image.image_data.shape[0]/2)), size=(850, 850))
    Image.make_contourplot(title='Contour plot with radio data', maxlevel=0.5)
    # # Image.make_image()
    #
    Image.make_bridge_overlay_contourplot('../fits/a401_curdecmaps_0.2_1.5s_sz.fits', title='y-map contour lines and radio filled contour',
                                          minlevel_1=0, maxlevel_1=0.005, steps_1=100, steps_2=6, minlevel_2=(10**(-5)/2), convolve_2=True)


    Image.make_bridge_overlay_contourplot('../fits/mosaic_a399_a401.fits', title='X-ray contour lines and radio filled contour',
                                          minlevel_1=0, maxlevel_1=0.005, steps_1=100, steps_2=6, convolve_2=True, maxlevel_2=50, xray=True)

    # for n, galpos in enumerate([(3150, 4266.82), (2988, 3569), (2564, 3635), (2524, 2814), (3297, 2356), (3019, 1945)]):
    #
    #     Image = Imaging('../fits/archive0.fits')
    #     if n in [2, 4]:
    #         Image.make_cutout(pos=galpos, size=(600, 600))
    #     else:
    #         Image.make_cutout(pos=galpos, size=(400, 400))
    #     Image.make_contourplot(title=f'Source {string.ascii_uppercase[n]} (6")', smallcutout=True)
    #     Image.make_image()
    #
    #     galpos = tuple([g/2 for g in galpos])
    #
    #     Image = Imaging('../fits/20arcsec.fits')
    #     if n in [2,4]:
    #         Image.make_cutout(pos=galpos, size=(300, 300))
    #     else:
    #         Image.make_cutout(pos=galpos, size=(200, 200))
    #     Image.make_contourplot(title=f'Source {string.ascii_uppercase[n]} (20")', smallcutout=True)
    #     Image.make_image()

    os.system('test.fits')
