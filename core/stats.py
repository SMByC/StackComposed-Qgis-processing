# -*- coding: utf-8 -*-
"""
/***************************************************************************
 StackComposed
                          A QGIS plugin processing
 Compute and generate the composed of a raster images stack
                              -------------------
        copyright            : (C) 2021-2022 by Xavier Corredor Llano, SMByC
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
import operator
import warnings

import dask.array as da
import numpy as np

from StackComposed.core.image import Image
from StackComposed.utils.progress import ProgressBar

# Safe operator dispatch — replaces eval() for -preproc CLI conditions.
_CMP_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def _build_stat_func(stat):
    """Return a vectorized ``(stack_chunk, metadata) -> 2D array`` function for ``stat``."""

    # Extract: keep only voxels equal to v, then per-pixel mean (NaN where empty).
    if stat.startswith("extract_"):
        v = int(stat.split("_")[1])

        def extract_stat(stack_chunk, metadata):
            masked = np.where(stack_chunk == v, stack_chunk, np.nan)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanmean(masked, axis=2)
        return extract_stat

    if stat == "median":
        def median_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanmedian(stack_chunk, axis=2)
        return median_stat

    if stat == "mean":
        def mean_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanmean(stack_chunk, axis=2)
        return mean_stat

    # Geometric mean as exp(mean(log(x))) — naturally handles NaN, vectorized.
    # Zero values are preserved (gmean of a series containing zero is zero);
    # negative values are dropped because log is undefined for real numbers.
    if stat == "gmean":
        def gmean_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                valid = ~np.isnan(stack_chunk)
                has_zero = ((stack_chunk == 0) & valid).any(axis=2)
                positive = np.where(stack_chunk > 0, stack_chunk, np.nan)
                gmean = np.exp(np.nanmean(np.log(positive), axis=2))
                return np.where(has_zero, 0, gmean)
        return gmean_stat

    if stat == "sum":
        def sum_stat(stack_chunk, metadata):
            valid = np.count_nonzero(~np.isnan(stack_chunk), axis=2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                total = np.nansum(stack_chunk, axis=2)
            return np.where(valid == 0, np.nan, total)
        return sum_stat

    if stat == "max":
        def max_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanmax(stack_chunk, axis=2)
        return max_stat

    if stat == "min":
        def min_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanmin(stack_chunk, axis=2)
        return min_stat

    if stat == "std":
        def std_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanstd(stack_chunk, axis=2)
        return std_stat

    if stat == "valid_pixels":
        def valid_pixels_stat(stack_chunk, metadata):
            return np.count_nonzero(~np.isnan(stack_chunk), axis=2)
        return valid_pixels_stat

    if stat.startswith("percentile_"):
        p = int(stat.split("_")[1])

        def percentile_stat(stack_chunk, metadata):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                return np.nanpercentile(stack_chunk, p, axis=2)
        return percentile_stat

    if stat == "last_pixel":
        def last_pixel_stat(stack_chunk, metadata):
            # Sort layers most-recent-first, then take the first non-NaN per pixel.
            order = np.argsort(metadata["date"])[::-1]
            sorted_stack = stack_chunk[:, :, order]
            return _first_valid_along_axis(sorted_stack, sorted_stack)
        return last_pixel_stat

    if stat == "jday_last_pixel":
        def jday_last_pixel_stat(stack_chunk, metadata):
            order = np.argsort(metadata["date"])[::-1]
            sorted_stack = stack_chunk[:, :, order]
            jdays = np.asarray(metadata["jday"], dtype=np.float64)[order]
            jday_grid = np.broadcast_to(jdays, sorted_stack.shape)
            result = _first_valid_along_axis(sorted_stack, jday_grid)
            # Preserve historical behavior: all-NaN pixels emit 0 (uint16 output).
            return np.where(np.isnan(result), 0, result)
        return jday_last_pixel_stat

    if stat == "jday_median":
        def jday_median_stat(stack_chunk, metadata):
            order = np.argsort(metadata["date"])
            sorted_stack = stack_chunk[:, :, order]
            jdays = np.asarray(metadata["jday"], dtype=np.float64)[order]
            valid = ~np.isnan(sorted_stack)
            jday_grid = np.where(valid, np.broadcast_to(jdays, sorted_stack.shape), np.nan)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                med = np.nanmedian(jday_grid, axis=2)
            return np.where(np.isnan(med), 0, np.ceil(med))
        return jday_median_stat

    if stat.startswith("trim_mean_"):
        lower = int(stat.split("_")[2])
        upper = int(stat.split("_")[3])

        def trim_mean_stat(stack_chunk, metadata):
            return _trim_mean_axis2(stack_chunk, lower, upper)
        return trim_mean_stat

    if stat == "linear_trend":
        def linear_trend_stat(stack_chunk, metadata):
            order = np.argsort(metadata["date"])
            sorted_stack = stack_chunk[:, :, order]
            dates = np.asarray(metadata["date"])[order]
            # Days since the earliest date.
            epoch = dates[0]
            x_days = np.array(
                [(d - epoch).days for d in dates], dtype=np.float64
            )
            return _linear_trend_axis2(sorted_stack, x_days) * 1e6
        return linear_trend_stat

    raise ValueError(f"Unknown statistic: {stat!r}")


def _first_valid_along_axis(sorted_stack, values):
    """For each (y, x), return ``values`` at the first non-NaN layer of ``sorted_stack``.

    Both arrays share shape ``(H, W, N)`` and are sorted along the z-axis in the
    desired priority order.
    """
    valid = ~np.isnan(sorted_stack)
    # argmax returns 0 when all are False, so guard with an "any valid" mask.
    first_idx = valid.argmax(axis=2)
    H, W = sorted_stack.shape[:2]
    yy, xx = np.indices((H, W))
    picked = values[yy, xx, first_idx]
    any_valid = valid.any(axis=2)
    return np.where(any_valid, picked, np.nan)


def _trim_mean_axis2(stack_chunk, lower, upper):
    """Vectorized trimmed-mean along axis=2 with percentile bounds.

    For pixels with <= 2 valid samples, falls back to the percentile at the midpoint
    (matching the original per-pixel behavior).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        lo = np.nanpercentile(stack_chunk, lower, axis=2)
        hi = np.nanpercentile(stack_chunk, upper, axis=2)
        valid = ~np.isnan(stack_chunk)
        n_valid = valid.sum(axis=2)

        in_range = (stack_chunk >= lo[..., None]) & (stack_chunk <= hi[..., None]) & valid
        # avoid division by zero — mark as NaN later
        clean = np.where(in_range, stack_chunk, np.nan)
        trimmed = np.nanmean(clean, axis=2)

        fallback = np.nanpercentile(stack_chunk, (lower + upper) / 2.0, axis=2)
        result = np.where(n_valid <= 2, fallback, trimmed)
        # all-NaN pixels emit 0 to preserve the historical multiprocessing-safe value
        return np.where(n_valid == 0, 0, result)


def _linear_trend_axis2(sorted_stack, x_days):
    """Vectorized linear regression slope along axis=2.

    Returns NaN when fewer than 2 valid samples exist for a pixel.
    """
    valid = ~np.isnan(sorted_stack)
    n_valid = valid.sum(axis=2)

    y = np.where(valid, sorted_stack, 0.0)
    x = np.broadcast_to(x_days, sorted_stack.shape)
    x_masked = np.where(valid, x, 0.0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        n = n_valid.astype(np.float64)
        sum_x = x_masked.sum(axis=2)
        sum_y = y.sum(axis=2)
        sum_xy = (x_masked * y).sum(axis=2)
        sum_xx = (x_masked * x_masked).sum(axis=2)

        # mean over valid samples only
        mean_x = np.where(n > 0, sum_x / n, np.nan)
        mean_y = np.where(n > 0, sum_y / n, np.nan)

        ssxym = sum_xy / np.where(n > 0, n, 1) - mean_x * mean_y
        ssxm = sum_xx / np.where(n > 0, n, 1) - mean_x * mean_x

        slope = np.where(ssxm > 0, ssxym / ssxm, np.nan)
        slope = np.where(n_valid < 2, np.nan, slope)
    return slope


def _build_preproc_func(preproc_arg):
    """Module-level builder for the preprocess function."""
    return ChunkProcessor(preproc_arg)._setup_preprocess()


class ChunkProcessor:
    """Build a per-chunk preprocessing function.

    Kept as a thin builder so ``_setup_preprocess`` can construct any of the
    supported preproc closures without needing the full processing context.
    """

    def __init__(self, preproc_arg):
        self.preproc_arg = preproc_arg

    def _setup_preprocess(self):
        arg = self.preproc_arg

        if arg is None:
            return lambda chunks: chunks

        if isinstance(arg, (int, float)):
            threshold = float(arg)

            def preproc_function(chunks):
                return np.where(chunks > threshold, chunks, np.nan)

            return preproc_function

        if isinstance(arg, list):
            # Each item is [operator_str, threshold].
            ops = [(_CMP_OPS[op], float(thr)) for op, thr in arg]

            def preproc_function(chunks):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    mask = np.ones(chunks.shape, dtype=bool)
                    for op, thr in ops:
                        mask &= op(chunks, thr)
                return np.where(mask, chunks, np.nan)

            return preproc_function

        if arg.startswith("percentile_"):
            lower = int(arg.split("_")[1])
            upper = int(arg.split("_")[2])

            def preproc_function(chunks):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    lo = np.nanpercentile(chunks, lower, axis=2, keepdims=True)
                    hi = np.nanpercentile(chunks, upper, axis=2, keepdims=True)
                    mask = (chunks >= lo) & (chunks <= hi)
                return np.where(mask, chunks, np.nan)

            return preproc_function

        if arg.endswith("_std_devs"):
            N = float(arg.split("_")[0])

            def preproc_function(chunks):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    mean = np.nanmean(chunks, axis=2, keepdims=True)
                    std = np.nanstd(chunks, axis=2, keepdims=True)
                    mask = (chunks >= mean - N * std) & (chunks <= mean + N * std)
                return np.where(mask, chunks, np.nan)

            return preproc_function

        if arg.endswith("_IQR"):
            N = float(arg.split("_")[0])

            def preproc_function(chunks):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    q25 = np.nanpercentile(chunks, 25, axis=2, keepdims=True)
                    q75 = np.nanpercentile(chunks, 75, axis=2, keepdims=True)
                    iqr = q75 - q25
                    mask = (chunks >= q25 - N * iqr) & (chunks <= q75 + N * iqr)
                return np.where(mask, chunks, np.nan)

            return preproc_function

        raise ValueError(f"Unknown preproc argument: {arg!r}")


def statistic(stat, preproc, images, band, num_process, chunksize, feedback):
    # create a empty initial wrapper raster for managed dask parallel
    # in chunks and storage result
    wrapper_array = da.empty(Image.wrapper_shape, chunks=chunksize)
    chunksize = wrapper_array.chunks[0][0]

    stat_func = _build_stat_func(stat)
    preproc_func = _build_preproc_func(preproc)

    # Compute the statistical for the respective chunk
    def calc(block, block_id=None, chunksize=None):
        if feedback.isCanceled():
            return

        yc = block_id[0] * chunksize
        yc_size = block.shape[0]
        xc = block_id[1] * chunksize
        xc_size = block.shape[1]

        # make stack reading all images only in specific chunk
        raw_chunks = [image.get_chunk_in_wrapper(band, xc, xc_size, yc, yc_size) for image in images]
        mask_none = [c is not None for c in raw_chunks]
        valid_chunks = [c for c in raw_chunks if c is not None]

        if not valid_chunks:
            # all chunks are empty, return the chunk with nan
            return np.full((yc_size, xc_size), np.nan)

        stack = np.empty((yc_size, xc_size, len(valid_chunks)), dtype=np.float32)
        for k, c in enumerate(valid_chunks):
            stack[:, :, k] = c
        data_chunk = preproc_func(stack)

        if np.all(np.isnan(data_chunk)):
            return np.full((yc_size, xc_size), np.nan)

        # for some statistics that required filename as metadata
        metadata = {}
        if stat in ["last_pixel", "jday_last_pixel", "jday_median", "linear_trend"]:
            metadata["date"] = np.array([image.date for image in images])[mask_none]
        if stat in ["jday_last_pixel", "jday_median"]:
            metadata["jday"] = np.array([image.jday for image in images])[mask_none]

        return stat_func(data_chunk, metadata)

    # process
    with ProgressBar(feedback=feedback):
        map_blocks = da.map_blocks(calc, wrapper_array, chunks=wrapper_array.chunks, chunksize=chunksize, dtype=float)
        result_array = map_blocks.compute(num_workers=num_process, scheduler="threads")

    return result_array
