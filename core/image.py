# -*- coding: utf-8 -*-
"""
/***************************************************************************
 StackComposed
                          A QGIS plugin processing
 Compute and generate the composed of a raster images stack
                              -------------------
        copyright            : (C) 2021-2026 by Xavier Corredor Llano, SMByC
        email                : xavier.corredor.llano@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os
import threading
import numpy as np
from osgeo import gdal

from StackComposed.core.parse import parse_filename

# ENVI dataset extensions to probe when an ".hdr" path is given.
_ENVI_DATASET_EXTS = ('.dat', '.raw', '.sli', '.hyspex', '.img')

# Thread-local cache of opened GDAL datasets. Each thread gets its own
# handles so concurrent reads from dask threads are safe.
_thread_local = threading.local()


def _open_dataset(file_path):
    if not hasattr(_thread_local, 'cache'):
        _thread_local.cache = {}
    ds = _thread_local.cache.get(file_path)
    if ds is None:
        ds = gdal.Open(file_path, gdal.GA_ReadOnly)
        _thread_local.cache[file_path] = ds
    return ds


def reset_dataset_cache():
    """Drop any cached GDAL handles in the current thread."""
    if hasattr(_thread_local, 'cache'):
        for ds in _thread_local.cache.values():
            try:
                del ds
            except Exception:
                pass
        _thread_local.cache.clear()


class Image:
    # global wrapper matrix properties
    wrapper_extent = None
    wrapper_x_res = None
    wrapper_y_res = None
    wrapper_shape = None
    # global projection
    projection = None
    # no data values from arguments
    nodata_from_arg = None

    def __init__(self, file_path):
        self.file_path = self.get_dataset_path(file_path)
        ### set geoproperties ###
        # setting the extent, pixel sizes and projection
        gdal_file = _open_dataset(self.file_path)
        min_x, x_res, x_skew, max_y, y_skew, y_res = gdal_file.GetGeoTransform()
        max_x = min_x + (gdal_file.RasterXSize * x_res)
        min_y = max_y + (gdal_file.RasterYSize * y_res)
        # extent
        self.extent = [min_x, max_y, max_x, min_y]
        # pixel sizes
        self.x_res = abs(float(x_res))
        self.y_res = abs(float(y_res))
        # number of bands
        self.n_bands = gdal_file.RasterCount
        # projection
        if Image.projection is None:
            Image.projection = gdal_file.GetProjectionRef()
        # per-band nodata and dtype
        self.nodata_from_file = {
            b: gdal_file.GetRasterBand(b).GetNoDataValue()
            for b in range(1, self.n_bands + 1)
        }
        self.data_type = {
            b: gdal_file.GetRasterBand(b).DataType
            for b in range(1, self.n_bands + 1)
        }
        # output type
        self.output_type = None

    @staticmethod
    def get_dataset_path(file_path):
        path, ext = os.path.splitext(file_path)
        if ext.lower() != ".hdr":
            return file_path
        # ENVI: probe for a matching dataset alongside the .hdr.
        # Try the extensionless basename first (common ENVI layout), then known extensions.
        candidates = [''] + list(_ENVI_DATASET_EXTS) + [e.upper() for e in _ENVI_DATASET_EXTS]
        for test_ext in candidates:
            test_dataset_path = path + test_ext
            if os.path.isfile(test_dataset_path):
                return test_dataset_path
        raise FileNotFoundError(
            f"Could not locate ENVI dataset for header file: {file_path}"
        )

    def set_bounds(self):
        wrapper_extent = Image.wrapper_extent
        wrapper_x_res = Image.wrapper_x_res
        wrapper_y_res = Image.wrapper_y_res
        wrapper_shape = Image.wrapper_shape
        if (wrapper_extent is None or wrapper_x_res is None
                or wrapper_y_res is None or wrapper_shape is None):
            raise RuntimeError("Image wrapper state is not initialized")
        # bounds for image with respect to wrapper
        # the 0,0 is left-upper corner
        self.xi_min = round((self.extent[0] - wrapper_extent[0]) / wrapper_x_res)
        self.xi_max = round(wrapper_shape[1] - (wrapper_extent[2] - self.extent[2]) / wrapper_x_res)
        self.yi_min = round((wrapper_extent[1] - self.extent[1]) / wrapper_y_res)
        self.yi_max = round(wrapper_shape[0] - (self.extent[3] - wrapper_extent[3]) / wrapper_y_res)

    def set_metadata_from_filename(self):
        self.landsat_version, self.sensor, self.path, self.row, self.date, self.jday = parse_filename(self.file_path)

    def get_chunk(self, band, xoff, xsize, yoff, ysize):
        """
        Get the array of the band for the respective chunk
        """
        gdal_file = _open_dataset(self.file_path)
        raster_band = gdal_file.GetRasterBand(band).ReadAsArray(xoff, yoff, xsize, ysize)
        if raster_band is None:
            return np.full((ysize, xsize), np.nan, dtype=np.float32)
        raster_band = raster_band.astype(np.float32)

        # convert the no data values from file and arguments to NaN
        nodata_values = {self.nodata_from_file[band], self.nodata_from_arg}
        nodata_values.discard(None)
        if nodata_values:
            nodata_mask = np.isin(raster_band, list(nodata_values))
            raster_band[nodata_mask] = np.nan

        return raster_band

    def get_chunk_in_wrapper(self, band, xc, xc_size, yc, yc_size):
        """
        Get the array of the band adjusted into the wrapper matrix for the respective chunk
        """
        xc_max = xc + xc_size
        yc_max = yc + yc_size

        # chunk fully outside the image footprint
        if xc_max <= self.xi_min or xc >= self.xi_max or yc_max <= self.yi_min or yc >= self.yi_max:
            return None

        # intersect chunk window with image window in wrapper coords
        x0 = max(xc, self.xi_min)
        x1 = min(xc_max, self.xi_max)
        y0 = max(yc, self.yi_min)
        y1 = min(yc_max, self.yi_max)

        xoff = x0 - self.xi_min
        yoff = y0 - self.yi_min
        xsize = x1 - x0
        ysize = y1 - y0

        x_min = x0 - xc
        y_min = y0 - yc

        chunk_matrix = np.full((yc_size, xc_size), np.nan, dtype=np.float32)
        data_chunk = self.get_chunk(band, xoff, xsize, yoff, ysize)

        # Edge case: GDAL may return a slightly smaller/larger array near the
        # raster boundary; pad with NaN or crop to fit the target slice.
        target = chunk_matrix[y_min:y_min + ysize, x_min:x_min + xsize]
        if data_chunk.shape != target.shape:
            diff_y = target.shape[0] - data_chunk.shape[0]
            diff_x = target.shape[1] - data_chunk.shape[1]
            if diff_y > 0 or diff_x > 0:
                data_chunk = np.pad(
                    data_chunk,
                    ((0, max(diff_y, 0)), (0, max(diff_x, 0))),
                    mode="constant",
                    constant_values=np.nan,
                )
            if diff_y < 0 or diff_x < 0:
                data_chunk = data_chunk[:target.shape[0], :target.shape[1]]

        chunk_matrix[y_min:y_min + ysize, x_min:x_min + xsize] = data_chunk
        return chunk_matrix
