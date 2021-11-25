import copy
import fnmatch
import glob
import logging
import os
import re
import sys
import tempfile
import time

import datetime as dt
from ftplib import FTP
from pprint import pformat

import numpy as np
import pandas as pd
import xarray as xr

from icenet2.data.cli import download_args
from icenet2.data.producers import Downloader
from icenet2.data.sic.mask import Masks
from icenet2.utils import Hemisphere


invalid_sic_days = {
    Hemisphere.NORTH: [
        *[d.date() for d in
          pd.date_range(dt.date(1979, 5, 21), dt.date(1979, 6, 4))],
        *[d.date() for d in
          pd.date_range(dt.date(1979, 6, 10), dt.date(1979, 6, 26))],
        dt.date(1979, 7, 1),
        *[d.date() for d in
          pd.date_range(dt.date(1979, 7, 24), dt.date(1979, 7, 28))],
        *[d.date() for d in
          pd.date_range(dt.date(1980, 1, 4), dt.date(1980, 1, 10))],
        *[d.date() for d in
          pd.date_range(dt.date(1980, 2, 27), dt.date(1980, 3, 4))],
        *[d.date() for d in
          pd.date_range(dt.date(1980, 3, 16), dt.date(1980, 3, 22))],
        *[d.date() for d in
          pd.date_range(dt.date(1980, 4, 9), dt.date(1980, 4, 15))],
        *[d.date() for d in
          pd.date_range(dt.date(1981, 2, 27), dt.date(1981, 3, 5))],
        *[d.date() for d in
          pd.date_range(dt.date(1984, 8, 12), dt.date(1984, 8, 24))],
        dt.date(1984, 9, 14),
        *[d.date() for d in
          pd.date_range(dt.date(1985, 9, 22), dt.date(1985, 9, 28))],
        *[d.date() for d in
          pd.date_range(dt.date(1986, 3, 29), dt.date(1986, 7, 1))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 1, 3), dt.date(1987, 1, 19))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 1, 29), dt.date(1987, 2, 2))],
        dt.date(1987, 2, 23),
        *[d.date() for d in
          pd.date_range(dt.date(1987, 2, 26), dt.date(1987, 3, 2))],
        dt.date(1987, 3, 13),
        *[d.date() for d in
          pd.date_range(dt.date(1987, 3, 22), dt.date(1987, 3, 26))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 4, 3), dt.date(1987, 4, 17))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 12, 1), dt.date(1988, 1, 12))],
        dt.date(1989, 1, 3),
        *[d.date() for d in
          pd.date_range(dt.date(1990, 12, 21), dt.date(1990, 12, 26))],
    ],
    Hemisphere.SOUTH: [
        dt.date(1979, 2, 5),
        dt.date(1979, 2, 25),
        dt.date(1979, 3, 23),
        *[d.date() for d in
          pd.date_range(dt.date(1979, 3, 26), dt.date(1979, 3, 30))],
        dt.date(1979, 4, 12),
        dt.date(1979, 5, 16),
        *[d.date() for d in
          pd.date_range(dt.date(1979, 5, 21), dt.date(1979, 5, 27))],
        *[d.date() for d in
          pd.date_range(dt.date(1979, 7, 10), dt.date(1979, 7, 18))],
        dt.date(1979, 8, 10),
        dt.date(1979, 9, 3),
        *[d.date() for d in
          pd.date_range(dt.date(1980, 1, 4), dt.date(1980, 1, 10))],
        dt.date(1980, 2, 16),
        *[d.date() for d in
          pd.date_range(dt.date(1980, 2, 27), dt.date(1980, 3, 4))],
        *[d.date() for d in
          pd.date_range(dt.date(1980, 3, 14), dt.date(1980, 3, 22))],
        dt.date(1980, 3, 31),
        *[d.date() for d in
          pd.date_range(dt.date(1980, 4, 9), dt.date(1980, 4, 15))],
        dt.date(1980, 4, 22),
        *[d.date() for d in
          pd.date_range(dt.date(1981, 2, 27), dt.date(1981, 3, 5))],
        dt.date(1981, 6, 10),
        *[d.date() for d in
          pd.date_range(dt.date(1981, 8, 3), dt.date(1982, 8, 9))],
        dt.date(1982, 8, 6),
        *[d.date() for d in
          pd.date_range(dt.date(1983, 7, 7), dt.date(1983, 7, 11))],
        dt.date(1983, 7, 22),
        dt.date(1984, 6, 12),
        *[d.date() for d in
          pd.date_range(dt.date(1984, 8, 12), dt.date(1984, 8, 24))],
        *[d.date() for d in
          pd.date_range(dt.date(1984, 9, 13), dt.date(1984, 9, 17))],
        *[d.date() for d in
          pd.date_range(dt.date(1984, 10, 3), dt.date(1984, 10, 9))],
        *[d.date() for d in
          pd.date_range(dt.date(1984, 11, 18), dt.date(1984, 11, 22))],
        dt.date(1985, 7, 23),
        *[d.date() for d in
          pd.date_range(dt.date(1985, 9, 22), dt.date(1985, 9, 28))],
        *[d.date() for d in
          pd.date_range(dt.date(1986, 3, 29), dt.date(1986, 11, 2))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 1, 3), dt.date(1987, 1, 15))],
        *[d.date() for d in
          pd.date_range(dt.date(1987, 12, 1), dt.date(1988, 1, 12))],
        #dt.date(1990, 1, 9),
        dt.date(1990, 8, 14),
        dt.date(1990, 8, 15),
        dt.date(1990, 8, 24),
        *[d.date() for d in
          pd.date_range(dt.date(1990, 12, 22), dt.date(1990, 12, 26))],
    ]
}

var_remove_list = ['time_bnds', 'raw_ice_conc_values', 'total_standard_error',
                   'smearing_standard_error', 'algorithm_standard_error',
                   'status_flag', 'Lambert_Azimuthal_Grid']


class SICDownloader(Downloader):
    """
    Downloads OSI-SAF SIC data from 1979-present using OpenDAP.
    The dataset comprises OSI-450 (1979-2015) and OSI-430-b (2016-ownards)
    Monthly averages are-computed on the server-side.
    This script can take about an hour to run.

    The query URLs were obtained from the following sites:
        - OSI-450 (1979-2016): https://thredds.met.no/thredds/dodsC/osisaf/
            met.no/reprocessed/ice/conc_v2p0_nh_agg.html
        - OSI-430-b (2016-present): https://thredds.met.no/thredds/dodsC/osisaf/
            met.no/reprocessed/ice/conc_crb_nh_agg.html
    """
    def __init__(self,
                 *args,
                 additional_invalid_dates=(),
                 dates=(),
                 delete_temp=False,
                 download=True,
                 dtype=np.float32,
                 **kwargs):
        super().__init__(*args, identifier="osisaf", **kwargs)

        self._dates = dates
        self._delete_temp = delete_temp
        self._download = download
        self._dtype=dtype
        self._invalid_dates = invalid_sic_days[self.hemisphere] + \
            list(additional_invalid_dates)
        self._masks = Masks(north=self.north, south=self.south)

        self._mask_dict = {
            month: self._masks.get_active_cell_mask(month)
            for month in np.arange(1, 12+1)
        }

    def download(self):
        hs = self.hemisphere_str[0]

        logging.info(
            "Not downloading SIC files, (re)processing NC files in "
            "existence already" if not self._download else
            "Downloading SIC datafiles to .temp intermediates...")

        #cmd = "wget -m -nH -nv --cut-dirs=4 -P {} {}"
        ftp_osi450 = "/reprocessed/ice/conc/v2p0/{:04d}/{:02d}/"
        ftp_osi430b = "/reprocessed/ice/conc-cont-reproc/v2p0/{:04d}/{:02d}/"
        cache = {}
        osi430b_start = dt.date(2016, 1, 1)

        # Bit wasteful
        dt_arr = list(reversed(sorted(copy.copy(self._dates))))
        data_files = []
        ftp = None

        while len(dt_arr):
            el = dt_arr.pop()

            if el in self._invalid_dates:
                logging.warning("Date {} is in invalid list".format(el))
                continue

            date_str = el.strftime("%Y_%m_%d")
            temp_path = os.path.join(self.get_data_var_folder("siconca"),
                                     str(el.year),
                                     "{}.temp".format(date_str))
            nc_path = os.path.join(self.get_data_var_folder("siconca"),
                                   str(el.year),
                                   "{}.nc".format(date_str))

            if not self._download:
                if os.path.exists(nc_path):
                    reproc_path = os.path.join(
                        self.get_data_var_folder("siconca"),
                        str(el.year),
                        "{}.reproc.nc".format(date_str))

                    logging.debug("{} exists, becoming {}".
                                  format(nc_path, reproc_path))
                    os.rename(nc_path, reproc_path)
                    data_files.append(reproc_path)
                else:
                    logging.debug("{} does not exist".format(nc_path))
                continue
            else:
                if not os.path.isdir(os.path.dirname(temp_path)):
                    os.makedirs(os.path.dirname(temp_path), exist_ok=True)

                if os.path.exists(temp_path) or os.path.exists(nc_path):
                    logging.info("{} file exists, skipping".format(date_str))
                    if not os.path.exists(nc_path):
                        data_files.append(temp_path)
                    continue

                if not ftp:
                    ftp = FTP('osisaf.met.no')
                    ftp.login()

                chdir_path = ftp_osi450 if el < osi430b_start else ftp_osi430b
                chdir_path = chdir_path.format(el.year, el.month)

                ftp.cwd(chdir_path)

                if chdir_path not in cache:
                    cache[chdir_path] = ftp.nlst()

                cache_match = "ice_conc_{}_ease*_{:04d}{:02d}{:02d}*.nc".\
                    format(hs, el.year, el.month, el.day)
                ftp_files = [el for el in cache[chdir_path]
                             if fnmatch.fnmatch(el, cache_match)]

                if len(ftp_files) > 1:
                    raise ValueError("More than a single file found: {}".
                                     format(ftp_files))
                elif not len(ftp_files):
                    continue

                with open(temp_path, "wb") as fh:
                    ftp.retrbinary("RETR {}".format(ftp_files[0]), fh.write)

                logging.debug("Downloaded {}".format(temp_path))
                data_files.append(temp_path)

            if ftp:
                ftp.quit()

        logging.debug("Files being processed: {}".format(data_files))

        if len(data_files):
            ds = xr.open_mfdataset(data_files, engine="netcdf4", parallel=True)

            logging.debug("Processing out extraneous data")

            ds = ds.drop_vars(var_remove_list, errors="ignore")
            dts = [pd.to_datetime(date).date() for date in ds.time.values]
            da = ds.resample(time="1D").mean().ice_conc.sel(time=dts)

            if self._download:
                da /= 100.  # Convert from SIC % to fraction

            da = self._missing_dates(da)

            for date in da.time.values:
                date_str = pd.to_datetime(date).strftime("%Y_%m_%d")
                fpath = os.path.join(self.get_data_var_folder("siconca"),
                                     str(pd.to_datetime(date).year),
                                     "{}.nc".format(date_str))

                logging.debug("Processing {}".format(date_str))

                if not os.path.exists(fpath):
                    day_da = da.sel(time=slice(date, date))

                    mask = self._mask_dict[pd.to_datetime(date).month]

                    # TODO: active grid cell mask possibly should move to
                    #  preproc Set outside mask to zero
                    day_da.data[0][~mask] = 0.

                    logging.info("Writing {}".format(fpath))
                    day_da.to_netcdf(fpath)

        if self._delete_temp:
            for fpath in data_files:
                os.unlink(fpath)

    def missing_dates(self):
        filenames = [os.path.join(self.get_data_var_folder("siconca"),
                                  str(el.year),
                                  "{}.nc".format(
                                      el.strftime("%Y_%m_%d")))
                     for el in self._dates]
        filenames = [f for f in filenames if os.path.exists(f)]

        ds = xr.open_mfdataset(filenames,
                               combine="nested",
                               concat_dim="time",
                               parallel=True)
        self._missing_dates(ds.to_array())

    def _missing_dates(self, da):
        if pd.Timestamp(1979, 1, 2) in da.time.values\
                and dt.date(1979, 1, 1) in self._dates:
            da_1979_01_01 = da.sel(
                time=[pd.Timestamp(1979, 1, 2)]).copy().assign_coords(
                {'time': [pd.Timestamp(1979, 1, 1)]})
            da = xr.concat([da, da_1979_01_01], dim='time')
            da = da.sortby('time')

        dates_obs = [pd.to_datetime(date).date() for date in da.time.values]
        dates_all = [pd.to_datetime(date).date() for date in
                     pd.date_range(min(self._dates), max(self._dates))]
        missing_dates = [date for date in dates_all
                         if date not in dates_obs
                         or date in self._invalid_dates]

        logging.info("Processing {} missing dates".format(len(missing_dates)))

        missing_dates_path = os.path.join(
            self.get_data_var_folder("siconca"), "missing_days.csv")

        with open(missing_dates_path, "a") as fh:
            for date in missing_dates:
                # FIXME: slightly unusual format for Ymd dates
                fh.write(date.strftime("%Y,%m,%d\n"))

        logging.debug("Interpolating {} missing dates".
                      format(len(missing_dates)))

        for date in missing_dates:
            da = xr.concat([da,
                            da.interp(time=pd.Timestamp(date))],
                           dim='time')

        logging.debug("Finished interpolation")

        da = da.sortby('time')
        da.data = np.array(da.data, dtype=self._dtype)

        return da


def main():
    args = download_args(skip_download=True)

    logging.info("OSASIF-SIC Data Downloading")
    sic = SICDownloader(
        dates=[pd.to_datetime(date).date() for date in
               pd.date_range(args.start_date, args.end_date,
                             freq="D")],
        north=args.hemisphere == "north",
        south=args.hemisphere == "south",
        download=not args.skip_download
    )
    sic.download()
