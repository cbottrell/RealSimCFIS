#!/usr/bin/env python

'''
Create CFIS photometric images from SKIRT IFS datacube.
Version 0.1

SED to flux conversions use the AB system following the documentation here: http://www.astro.ljmu.ac.uk/~ikb/research/mags-fluxes/
Also found here (though incorrect in places): http://mfouesneau.github.io/docs/pyphot/

Update History:

Version 0.1 - Corrected to explicitly account for the target redshift by stretching the emitted spectrum by the redshift factor and reducing the specific intensities by a factor of (1+z)**5. Now requires a redshift as input in addition to image properties. The output image AB surface brightnesses have already been scaled to account for the target redshift. ObsRealism should not then apply any brightness factor.
'''

import os,sys,string,time
import numpy as np
from astropy.io import fits

def SpecPhotCFIS(inputName,_outputName,wl_filename,cfis_cfg_path,redshift=0.05,bands=['g','r','i'],airmass=0.,overwrite=0):
    '''
    Generate idealized mock CFIS photometric images with same spatial scale as the original datacube. The input is a SKIRT data cube with units specific intensity units W/m2/micron/arcsec2. This code is provided as a companion to the Realism suite as it produces output in the exact format accepted by the suite.
    
    "_outputName - formattable string: Should be a formattable string which can be updated for each band (e.g. Outputs/photo_{}.fits).
    
    "wl_filename" - string: Path to wavelength file accompanied with SKIRT. The file should show provide the wavelengths for which each specific intensity in the datacubes is defined.
    
    "cfis_cfg_path" - string: Path to CFIS response curve files.
    
    "redshift" - float: Redshift by which the input spectrum is streched and dimmed.
    
    "airmass" - float>=0: Airmass used to determine atmospheric extinction effects on the response curves. The average value for CFIS is 1.13 over all fields. If 0, the unattenuated response curves are used (only telescope/filter/ccd). This should nominally be set to zero because calibrated images account for atmospheric extinction.
    
    "overwrite" - boolean: Overwrite output in output location.
    
    "bands" - list object: Options are 'u','g','r','i','z', but depends on how much of the spectrum is modelled by SKIRT. Additionally, care should also be taken when interpreting 'u' or 'z' band fluxes because response functions in these bands are strongly (and non-uniformly) affected by atmospheric absorption.
    '''
    
    # useful constants / quantities
    speed_of_light = 2.998e8 # [m/s]
    speed_of_light = speed_of_light*1e10 # [Angstrom/s]

    # wavelengths of datacube [microns] (expand by redshift factor)
    wl = np.loadtxt(wl_filename).astype(float)*1e4*(1+redshift) # [Angstrom]
    # wavelength bin widths [Angstrom]
    dwl = np.median(np.diff(wl)) # [Angstrom]

    # read IFU cube header and data
    with fits.open(inputName,mode='readonly') as hdul:
        # IFU header
        header = hdul[0].header
        # image spectral flux density in W/m2/micron/arcsec2; convert to [Jy*Hz/Angstrom/arcsec2]
        ifu_data = hdul[0].data*1e22 # [Jy*Hz/Angstrom/arcsec2]

    # header changes for photometry 
    header.remove('NAXIS3')
    # calibrated flux units; easily converted to nanomaggies
    header['BUNIT'] = 'AB mag/arcsec2'
    header.set('FILTER', value='', comment='Transmission band')
    header.set('WLEFF' , value=np.float32(0.)  , comment='Effective WL of response [Angstrom]')

    for band in bands:

        # filter response function 
        filter_data = np.loadtxt(cfis_cfg_path+'{}_CFIS.res'.format(band.capitalize()))
        # wavelength elements in response curve file
        filter_wl = filter_data[:,0]
        # filter response
        filter_res = filter_data[:,1]
        # filter response interpolated onto image wavelength grid
        filter_res = np.interp(xp=filter_wl,x=wl,fp=filter_res,left=0,right=0) # unitless
        
        # apply extinction correction to filters: extinction file
        kkFile = cfis_cfg_path+'CFIS_extinction.txt'
        # unpack wavelengths and extinctions [mag/airmass]
        wl_kk,kk = np.loadtxt(kkFile,unpack=True)
        # interpolated onto wavelength grid
        kk = np.interp(xp=wl_kk,x=wl,fp=kk,left=np.nanmax(kk),right=0)
        # 1.25 because CFIS response curves assume 1.25 airmass by default
        filter_res *= 10**(0.4*((1.25-airmass)*kk))

        # filter-specific pivot wavelength squared [m2]
        wl_pivot2 = np.sum(filter_res*wl*dwl)/np.sum(filter_res*dwl/wl)

        # now the mean photon rate density in the filter [Jy*Hz/Angstrom/arcsec2]
        f_wl = np.sum(wl*filter_res*ifu_data.T*dwl,axis=2)/np.sum(wl*filter_res*dwl)

        # multiplying by wl_pivot2/speed_of_light gives [Jy/arcsec2]
        # convert to maggies/arcsec2 (w/ AB zeropoint) using 1 maggy ~ 3631 Jy
        # apply (1+z)**-5 redshift degradation to wavelength specific intensities
        f_mgys = f_wl*wl_pivot2/speed_of_light/3631.*(1+redshift)**-5 # [maggies/arcsec2]

        # convert to mag/arcsec2 surface brightness for numerical ease
        with np.errstate(divide='ignore'):
            f_sb = -2.5*np.log10(f_mgys) # [mag/arcsec2] AB system

        # fits file output                                                                                             
        photo_out = _outputName.format(band)
        if os.access(photo_out,0):os.remove(photo_out)

        # create output photometry file and make band-specific header updates
        hdu = fits.PrimaryHDU(f_sb)
        header['FILTER'] = '{}'.format(band)
        header['WLEFF'] = np.around(np.sqrt(wl_pivot2),decimals=1)
        header['REDSHIFT'] = (redshift,'Redshift')
        hdu.header = header
        hdu.writeto(photo_out, overwrite=True)

