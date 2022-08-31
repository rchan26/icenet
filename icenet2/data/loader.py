import argparse
import datetime as dt
import json
import logging
import os
import sys
import time

from pprint import pprint, pformat

import dask
import dask.array as da
from dask.distributed import Client, LocalCluster


import numpy as np
import pandas as pd
import tensorflow as tf
import xarray as xr

from icenet2.data.sic.mask import Masks
from icenet2.data.process import IceNetPreProcessor
from icenet2.data.producers import Generator
from icenet2.data.cli import add_date_args, process_date_args
from icenet2.utils import setup_logging

"""

"""


def generate_and_write(path: str,
                       var_files: object,
                       dates: object,
                       args: object,
                       dry: bool = False):
    """

    :param path:
    :param var_files:
    :param dates:
    :param args:
    :param dry:
    :return:
    """
    count = 0
    times = []

    # TODO: refactor, this is very smelly - with new data throughput args
    #  will always be the same
    (channels,
     dtype,
     loss_weight_days,
     meta_channels,
     missing_dates,
     n_forecast_days,
     num_channels,
     shape,
     trend_steps,
     masks,
     data_check) = args

    ds_kwargs = dict(
        chunks=dict(time=1, yc=shape[0], xc=shape[1]),
        drop_variables=["month", "plev", "realization"],
        parallel=True,
    )

    var_ds = xr.open_mfdataset(
        [v for k, v in var_files.items()
         if k not in meta_channels and not k.endswith("linear_trend")],
        **ds_kwargs)
    trend_ds = xr.open_mfdataset(
        [v for k, v in var_files.items()
         if k.endswith("linear_trend")],
        **ds_kwargs)

    var_ds = var_ds.transpose("xc", "yc", "time")

    with tf.io.TFRecordWriter(path) as writer:
        for date in dates:
            start = time.time()

            try:
                x, y, sample_weights = generate_sample(date,
                                                       var_ds,
                                                       var_files,
                                                       trend_ds,
                                                       *args)
                if not dry:
                    write_tfrecord(writer,
                                   x, y, sample_weights,
                                   data_check,
                                   date)
                count += 1
            except IceNetDataWarning:
                continue

            end = time.time()
            times.append(end - start)
            logging.debug("Time taken to produce {}: {}".
                          format(date, times[-1]))
    return path, count, times


def generate_sample(forecast_date: object,
                    var_ds: object,
                    var_files: object,
                    trend_ds: object,
                    channels: object,
                    dtype: object,
                    loss_weight_days: bool,
                    meta_channels: object,
                    missing_dates: object,
                    n_forecast_days: int,
                    num_channels: int,
                    shape: object,
                    trend_steps: object,
                    masks: object,
                    *args):
    """

    :param forecast_date:
    :param channels:
    :param dtype:
    :param loss_weight_days:
    :param meta_channels:
    :param missing_dates:
    :param n_forecast_days:
    :param num_channels:
    :param shape:
    :param trend_steps:
    :param var_files:
    :param trend_files:
    :param meta_ds:
    :param masks:
    :param data_check:
    :return:
    """

    ### Prepare data sample
    # To become array of shape (*raw_data_shape, n_forecast_days)
    forecast_dts = [forecast_date + dt.timedelta(days=n)
                    for n in range(n_forecast_days)]

    sample_output = var_ds.siconca_abs.sel(time=forecast_dts)

    y = da.zeros((*shape, n_forecast_days, 1), dtype=dtype)
    sample_weights = da.zeros((*shape, n_forecast_days, 1), dtype=dtype)

    y[:, :, :, 0] = sample_output

    # Masked recomposition of output
    for leadtime_idx in range(n_forecast_days):
        forecast_day = forecast_date + dt.timedelta(days=leadtime_idx)

        if any([forecast_day == missing_date
                for missing_date in missing_dates]):
            sample_weight = da.zeros(shape, dtype)
        else:
            # Zero loss outside of 'active grid cells'
            sample_weight = masks[forecast_day.month - 1]
            sample_weight = sample_weight.astype(dtype)

            # Scale the loss for each month s.t. March is
            #   scaled by 1 and Sept is scaled by 1.77
            if loss_weight_days:
                sample_weight *= 33928. / sample_weight.sum()

        sample_weights[:, :, leadtime_idx, 0] = sample_weight

    # INPUT FEATURES
    x = da.zeros((*shape, num_channels), dtype=dtype)
    v1, v2 = 0, 0

    for var_name, num_channels in channels.items():
        if var_name in meta_channels:
            continue

        v2 += num_channels

        if var_name.endswith("linear_trend"):
            channel_ds = trend_ds
            if type(trend_steps) == list:
                channel_dates = [pd.Timestamp(forecast_date +
                                              dt.timedelta(days=int(n)))
                                 for n in trend_steps]
            else:
                channel_dates = [pd.Timestamp(forecast_date +
                                              dt.timedelta(days=n))
                                 for n in range(num_channels)]
        else:
            channel_ds = var_ds
            channel_dates = [pd.Timestamp(forecast_date - dt.timedelta(days=n))
                             for n in range(num_channels)]

        channel_data = []
        for cdate in channel_dates:
            try:
                channel_data.append(getattr(channel_ds, var_name).
                                            sel(time=cdate))
            except KeyError:
                channel_data.append(da.zeros(shape))

        x[:, :, v1:v2] = da.from_array(channel_data).transpose([1, 2, 0])
        v1 += num_channels

    for var_name in meta_channels:
        if channels[var_name] > 1:
            raise RuntimeError("{} meta variable cannot have more than "
                               "one channel".format(var_name))

        meta_ds = xr.open_dataarray(var_files[var_name])

        if var_name in ["sin", "cos"]:
            ref_date = "2012-{}-{}".format(forecast_date.month,
                                           forecast_date.day)
            trig_val = meta_ds.sel(time=ref_date).to_numpy()
            x[:, :, v1] = da.broadcast_to([trig_val], shape)
        else:
            x[:, :, v1] = da.array(meta_ds.to_numpy())
        v1 += channels[var_name]

    #    x.visualize(filename='x.svg', optimize_graph=True)
    #    y.visualize(filename='y.svg', optimize_graph=True)
    #    sample_weights.visualize(filename='sample_weights.svg', optimize_graph=True)
    #    import sys
    #    sys.exit(0)

    return x, y, sample_weights


def write_tfrecord(writer: object,
                   x: object,
                   y: object,
                   sample_weights: object,
                   data_check: bool,
                   forecast_date: object):
    """

    :param writer:
    :param x:
    :param y:
    :param sample_weights:
    :param data_check:
    """

#    y_nans = da.isnan(y).sum()
#    x_nans = da.isnan(x).sum()
#    sw_nans = da.isnan(sample_weights).sum()

#    if y_nans + x_nans + sw_nans > 0:
#        logging.warning("NaNs detected {}: input = {}, "
#                        "output = {}, weights = {}".
#                        format(forecast_date, x_nans, y_nans, sw_nans))

#        if data_check and sample_weights[da.isnan(y)].sum() > 0:
#            raise IceNetDataWarning("NaNs in output with non-zero weights")

#        if data_check and x_nans > 0:
    x[da.isnan(x)] = 0.

    x, y, sample_weights = dask.compute(x, y, sample_weights,
                                        optimize_graph=True)

    record_data = tf.train.Example(features=tf.train.Features(feature={
        "x": tf.train.Feature(
            float_list=tf.train.FloatList(value=x.reshape(-1))),
        "y": tf.train.Feature(
            float_list=tf.train.FloatList(value=y.reshape(-1))),
        "sample_weights": tf.train.Feature(
            float_list=tf.train.FloatList(value=sample_weights.reshape(-1))),
    })).SerializeToString()

    writer.write(record_data)


# TODO: TFDatasetGenerator should be created, so we can also have an
#  alternate numpy based loader. Easily abstracted after implementation and
#  can also inherit from a new BatchGenerator - this family tree can be rich!
class IceNetDataLoader(Generator):
    """

    :param configuration_path,
    :param identifier,
    :param var_lag,
    :param dataset_config_path: 
    :param generate_workers: 
    :param loss_weight_days: 
    :param n_forecast_days: 
    :param output_batch_size: 
    :param path: 
    :param var_lag_override: 
    """

    def __init__(self,
                 configuration_path: str,
                 identifier: str,
                 var_lag: int,
                 *args,
                 dataset_config_path: str = ".",
                 dry: bool = False,
                 futures_per_worker: int = 2,
                 generate_workers: int = 8,
                 loss_weight_days: bool = True,
                 n_forecast_days: int = 93,
                 output_batch_size: int = 32,
                 path: str = os.path.join(".", "network_datasets"),
                 var_lag_override: object = None,
                 **kwargs):
        super().__init__(*args,
                         identifier=identifier,
                         path=path,
                         **kwargs)

        self._channels = dict()
        self._channel_files = dict()

        self._configuration_path = configuration_path
        self._dataset_config_path = dataset_config_path
        self._config = dict()
        self._dry = dry
        self._futures = futures_per_worker
        self._loss_weight_days = loss_weight_days
        self._meta_channels = []
        self._missing_dates = []
        self._n_forecast_days = n_forecast_days
        self._output_batch_size = output_batch_size
        self._trend_steps = dict()
        self._workers = generate_workers

        self._var_lag = var_lag
        self._var_lag_override = dict() \
            if not var_lag_override else var_lag_override

        self._load_configuration(configuration_path)
        self._construct_channels()

        self._dtype = getattr(np, self._config["dtype"])
        self._shape = tuple(self._config["shape"])

        masks = Masks(north=self.north, south=self.south)
        self._masks = da.array([
            masks.get_active_cell_mask(month) for month in range(1, 13)])

        self._missing_dates = [
            dt.datetime.strptime(s, IceNetPreProcessor.DATE_FORMAT)
            for s in self._config["missing_dates"]]

    def write_dataset_config_only(self):
        """

        """
        splits = ("train", "val", "test")
        counts = {el: 0 for el in splits}

        logging.info("Writing dataset configuration without data generation")

        # FIXME: cloned mechanism from generate() - do we need to treat these as
        #  sets that might have missing data for fringe cases?
        for dataset in splits:
            forecast_dates = sorted(list(set(
                [dt.datetime.strptime(s,
                 IceNetPreProcessor.DATE_FORMAT).date()
                 for identity in
                 self._config["sources"].keys()
                 for s in
                 self._config["sources"][identity]
                 ["dates"][dataset]])))

            logging.info("{} {} dates in total, NOT generating cache "
                         "data.".format(len(forecast_dates), dataset))
            counts[dataset] += len(forecast_dates)

        self._write_dataset_config(counts, network_dataset=False)

    def generate(self,
                 client: object = None,
                 dates_override: object = None,
                 pickup: bool = False):
        """

        :param client:
        :param dates_override:
        :param pickup:
        """
        # TODO: for each set, validate every variable has an appropriate file
        #  in the configuration arrays, otherwise drop the forecast date
        splits = ("train", "val", "test")

        if dates_override and type(dates_override) is dict:
            for split in splits:
                assert split in dates_override.keys() \
                       and type(dates_override[split]) is list, \
                       "{} needs to be list in dates_override".format(split)
        elif dates_override:
            raise RuntimeError("dates_override needs to be a dict if supplied")

        counts = {el: 0 for el in splits}
        exec_times = []

        def batch(batch_dates, num):
            i = 0
            while i < len(batch_dates):
                yield batch_dates[i:i + num]
                i += num

        masks = client.scatter(self._masks, broadcast=True)

        for dataset in splits:
            batch_number = 0
            futures = []

            forecast_dates = set([dt.datetime.strptime(s,
                                  IceNetPreProcessor.DATE_FORMAT).date()
                                  for identity in
                                  self._config["sources"].keys()
                                  for s in
                                  self._config["sources"][identity]
                                  ["dates"][dataset]])

            if dates_override:
                logging.info("{} available {} dates".
                             format(len(forecast_dates), dataset))
                forecast_dates = forecast_dates.intersection(
                    dates_override[dataset])
            forecast_dates = sorted(list(forecast_dates))

            output_dir = self.get_data_var_folder(dataset)
            tf_path = os.path.join(output_dir, "{:08}.tfrecord")

            logging.info("{} {} dates to process, generating cache "
                         "data.".format(len(forecast_dates), dataset))

            for dates in batch(forecast_dates, self._output_batch_size):
                if not pickup or \
                    (pickup and
                     not os.path.exists(tf_path.format(batch_number))):
                    args = [
                        self._channels,
                        self._dtype,
                        self._loss_weight_days,
                        self._meta_channels,
                        self._missing_dates,
                        self._n_forecast_days,
                        self.num_channels,
                        self._shape,
                        self._trend_steps,
                        masks,
                        True
                    ]

                    fut = client.submit(generate_and_write,
                                        tf_path.format(batch_number),
                                        self.get_sample_files(),
                                        dates,
                                        args,
                                        dry=self._dry)
                    futures.append(fut)

                    # Use this to limit the future list, to avoid crashing the
                    # distributed scheduler / workers (task list gets too big!)
                    if len(futures) >= self._workers * self._futures:
                        for tf_data, samples, gen_times \
                                in client.gather(futures):
                            logging.info("Finished output {}".format(tf_data))
                            counts[dataset] += samples
                            exec_times += gen_times
                        futures = []

                    # tf_data, samples, times = generate_and_write(
                    #    tf_path.format(batch_number), args, dry=self._dry)
                else:
                    logging.warning("Skipping {} on pickup run".
                                    format(tf_path.format(batch_number)))

                batch_number += 1

            # Hoover up remaining futures
            for tf_data, samples, gen_times \
                    in client.gather(futures):
                logging.info("Finished output {}".format(tf_data))
                counts[dataset] += samples
                exec_times += gen_times

        if len(exec_times) > 0:
            logging.info("Average sample generation time: {}".
                         format(np.average(exec_times)))
        self._write_dataset_config(counts)

    def generate_sample(self, date: object):
        """

        :param date:
        :return:
        """

        ds_kwargs = dict(
            chunks=dict(time=1, yc=self._shape[0], xc=self._shape[1]),
            drop_variables=["month", "plev", "realization"],
            parallel=True,
        )
        var_files = self.get_sample_files()

        var_ds = xr.open_mfdataset(
            [v for k, v in var_files.items()
             if k not in self._meta_channels
             and not k.endswith("linear_trend")],
            **ds_kwargs)
        trend_ds = xr.open_mfdataset(
            [v for k, v in var_files.items()
             if k.endswith("linear_trend")],
            **ds_kwargs)

        var_ds = var_ds.transpose("xc", "yc", "time")

        args = [
            self._channels,
            self._dtype,
            self._loss_weight_days,
            self._meta_channels,
            self._missing_dates,
            self._n_forecast_days,
            self.num_channels,
            self._shape,
            self._trend_steps,
            self._masks,
            False
        ]

        return generate_sample(date,
                               var_ds,
                               var_files,
                               trend_ds,
                               *args)

    def get_sample_files(self) -> object:
        """

        :param date:
        :return:
        """
        # FIXME: is this not just the same as _channel_files now?
        # FIXME: still experimental code, move to multiple implementations
        # FIXME: CLEAN THIS ALL UP ONCE VERIFIED FOR local/shared STORAGE!
        var_files = dict()

        for var_name, num_channels in self._channels.items():
            var_file = self._get_var_file(var_name)

            if not var_file:
                raise RuntimeError("No file returned for {}".format(var_name))

            if var_name not in var_files:
                var_files[var_name] = var_file
            elif var_file != var_files[var_name]:
                raise RuntimeError("Differing files? {} {} vs {}".
                                   format(var_name,
                                          var_file,
                                          var_files[var_name]))

        return var_files

    def _add_channel_files(self,
                           var_name: str,
                           filelist: object):
        """

        :param var_name:
        :param filelist:
        """
        if var_name in self._channel_files:
            logging.warning("{} already has files, but more found, "
                            "this could be an unintentional merge of "
                            "sources".format(var_name))
        else:
            self._channel_files[var_name] = []

        logging.debug("Adding {} to {} channel".format(len(filelist), var_name))
        self._channel_files[var_name] += filelist

    def _construct_channels(self):
        """

        """
        # As of Python 3.7 dict guarantees the order of keys based on
        # original insertion order, which is great for this method
        lag_vars = [(identity, var, data_format)
                    for data_format in ("abs", "anom")
                    for identity in
                    sorted(self._config["sources"].keys())
                    for var in
                    sorted(self._config["sources"][identity][data_format])]

        for identity, var_name, data_format in lag_vars:
            var_prefix = "{}_{}".format(var_name, data_format)
            var_lag = (self._var_lag
                       if var_name not in self._var_lag_override
                       else self._var_lag_override[var_name])

            self._channels[var_prefix] = int(var_lag)
            self._add_channel_files(
                var_prefix,
                [el for el in
                 self._config["sources"][identity]["var_files"][var_name]
                 if var_prefix in os.path.split(el)[1]])

        trend_names = [(identity, var,
                        self._config["sources"][identity]["linear_trend_steps"])
                       for identity in
                       sorted(self._config["sources"].keys())
                       for var in
                       sorted(
                           self._config["sources"][identity]["linear_trends"])]

        for identity, var_name, trend_steps in trend_names:
            var_prefix = "{}_linear_trend".format(var_name)

            self._channels[var_prefix] = len(trend_steps)
            self._trend_steps[var_prefix] = trend_steps
            filelist = [el for el in
                        self._config["sources"][identity]["var_files"][var_name]
                        if "linear_trend" in os.path.split(el)[1]]

            self._add_channel_files(var_prefix, filelist)

        # Metadata input variables that don't span time
        meta_names = [(identity, var)
                      for identity in
                      sorted(self._config["sources"].keys())
                      for var in
                      sorted(self._config["sources"][identity]["meta"])]

        for identity, var_name in meta_names:
            self._meta_channels.append(var_name)
            self._channels[var_name] = 1
            self._add_channel_files(
                var_name,
                self._config["sources"][identity]["var_files"][var_name])

        logging.debug("Channel quantities deduced:\n{}\n\nTotal channels: {}".
                      format(pformat(self._channels), self.num_channels))

    def _get_var_file(self, var_name: str):
        """

        :param var_name:
        :return:
        """

        filename = "{}.nc".format(var_name)
        files = self._channel_files[var_name]

        if len(self._channel_files[var_name]) > 1:
            logging.warning("Multiple files found for {}, only returning {}".
                            format(filename, files[0]))
        elif not len(files):
            logging.warning("No files in channel list for {}".format(filename))
            return None
        return files[0]

    def _load_configuration(self, path: str):
        """

        :param path:
        """
        if os.path.exists(path):
            logging.info("Loading configuration {}".format(path))

            with open(path, "r") as fh:
                obj = json.load(fh)

                self._config.update(obj)
        else:
            raise OSError("{} not found".format(path))

    def _write_dataset_config(self,
                              counts: object,
                              network_dataset: bool = True):
        """

        :param counts:
        :param network_dataset:
        :return:
        """
        # TODO: move to utils for this and process
        def _serialize(x):
            if x is dt.date:
                return x.strftime(IceNetPreProcessor.DATE_FORMAT)
            return str(x)

        configuration = {
            "identifier":       self.identifier,
            "implementation":   self.__class__.__name__,
            # This is only for convenience ;)
            "channels":         [
                "{}_{}".format(channel, i)
                for channel, s in
                self._channels.items()
                for i in range(1, s + 1)],
            "counts":           counts,
            "dtype":            self._dtype.__name__,
            "loader_config":    self._configuration_path,
            "missing_dates":    [date.strftime(
                IceNetPreProcessor.DATE_FORMAT) for date in
                self._missing_dates],
            "n_forecast_days":  self._n_forecast_days,
            "north":            self.north,
            "num_channels":     self.num_channels,
            # FIXME: this naming is inconsistent, sort it out!!! ;)
            "shape":            list(self._shape),
            "south":            self.south,

            # For recreating this dataloader
            # "dataset_config_path = ".",
            # FIXME: badly named, should really be dataset_path
            "loader_path":      self._path if network_dataset else False,
            "loss_weight_days": self._loss_weight_days,
            "output_batch_size": self._output_batch_size,
            "var_lag":          self._var_lag,
            "var_lag_override": self._var_lag_override,
        }

        output_path = os.path.join(self._dataset_config_path,
                                   "dataset_config.{}.json".format(
                                       self.identifier))

        logging.info("Writing configuration to {}".format(output_path))

        with open(output_path, "w") as fh:
            json.dump(configuration, fh, indent=4, default=_serialize)

    @property
    def config(self):
        return self._config

    @property
    def num_channels(self):
        return sum(self._channels.values())


@setup_logging
def get_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", type=str)
    ap.add_argument("hemisphere", choices=("north", "south"))

    ap.add_argument("-c", "--cfg-only", help="Do not generate data, "
                                             "only config", default=False,
                    action="store_true", dest="cfg")
    ap.add_argument("-d", "--dry",
                    help="Don't output files, just generate data",
                    default=False, action="store_true")
    ap.add_argument("-dt", "--dask-timeouts", type=int, default=120)
    ap.add_argument("-dp", "--dask-port", type=int, default=8888)
    ap.add_argument("-f", "--futures-per-worker", type=float, default=2.,
                    dest="futures")
    ap.add_argument("-fn", "--forecast-name", dest="forecast_name",
                    default=None, type=str)
    ap.add_argument("-fd", "--forecast-days", dest="forecast_days",
                    default=93, type=int)

    ap.add_argument("-l", "--lag", type=int, default=2)

    ap.add_argument("-ob", "--output-batch-size", dest="batch_size", type=int,
                    default=8)

    ap.add_argument("-p", "--pickup", help="Skip existing tfrecords",
                    default=False, action="store_true")
    ap.add_argument("-t", "--tmp-dir", help="Temporary directory",
                    default="/local/tmp", dest="tmp_dir", type=str)

    ap.add_argument("-v", "--verbose", action="store_true", default=False)
    ap.add_argument("-w", "--workers", help="Number of workers to use "
                                            "generating sets",
                    type=int, default=2)

    add_date_args(ap)
    args = ap.parse_args()
    return args


def main():
    args = get_args()
    dates = process_date_args(args)

    dl = IceNetDataLoader("loader.{}.json".format(args.name),
                          args.forecast_name
                          if args.forecast_name else args.name,
                          args.lag,
                          dry=args.dry,
                          n_forecast_days=args.forecast_days,
                          north=args.hemisphere == "north",
                          south=args.hemisphere == "south",
                          output_batch_size=args.batch_size,
                          generate_workers=args.workers,
                          futures_per_worker=args.futures)
    if args.cfg:
        dl.write_dataset_config_only()
    else:
        dashboard = "localhost:{}".format(args.dask_port)

        with dask.config.set({
            "temporary_directory": args.tmp_dir,
            "distributed.comm.timeouts.connect": args.dask_timeouts,
            "distributed.comm.timeouts.tcp": args.dask_timeouts,
        }):
            cluster = LocalCluster(
                dashboard_address=dashboard,
                n_workers=args.workers,
                threads_per_worker=1,
                scheduler_port=0,
            )
            logging.info("Dashboard at {}".format(dashboard))

            with Client(cluster) as client:
                logging.info("Using dask client {}".format(client))
                dl.generate(client,
                            dates_override=dates
                            if sum([len(v) for v in dates.values()]) > 0
                            else None,
                            pickup=args.pickup)


class IceNetDataWarning(RuntimeWarning):
    pass
