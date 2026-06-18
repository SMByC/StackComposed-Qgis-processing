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
import warnings
import numpy as np
from osgeo import gdal, osr

from qgis.core import QgsProcessingException

from StackComposed.core.image import Image, reset_dataset_cache
from StackComposed.core.stats import statistic


def run(stat, preproc, band, nodata, output, output_type, num_process, chunksize, images_files, feedback):
    # ignore warnings
    warnings.filterwarnings("ignore")

    feedback.pushInfo("\nLoading and prepare images in path(s):")

    # load images
    images = [Image(img) for img in images_files]

    if len(images) <= 1:
        raise QgsProcessingException(
            "\n\nError: StackComposed required at least 2 or more images to process.\n")

    # save nodata set from arguments
    for image in images:
        image.nodata_from_arg = nodata

    # get wrapper extent
    min_x = min(image.extent[0] for image in images)
    max_y = max(image.extent[1] for image in images)
    max_x = max(image.extent[2] for image in images)
    min_y = min(image.extent[3] for image in images)
    Image.wrapper_extent = [min_x, max_y, max_x, min_y]

    # define the properties for the raster wrapper
    wrapper_x_res = images[0].x_res
    wrapper_y_res = images[0].y_res
    wrapper_shape = (
        int((max_y - min_y) / wrapper_y_res),
        int((max_x - min_x) / wrapper_x_res),
    )
    Image.wrapper_x_res = wrapper_x_res
    Image.wrapper_y_res = wrapper_y_res
    Image.wrapper_shape = wrapper_shape

    # reset the chunksize with the min of width/high if apply
    if chunksize > min(wrapper_shape):
        chunksize = min(wrapper_shape)

    # some information about process
    feedback.pushInfo("  images to process: {0}".format(len(images)))
    feedback.pushInfo("  band to process: {0}".format(band))
    feedback.pushInfo("  pixels size: {0} x {1}".format(round(wrapper_x_res, 1), round(wrapper_y_res, 1)))
    feedback.pushInfo("  wrapper size: {0} x {1} pixels".format(wrapper_shape[1], wrapper_shape[0]))
    feedback.pushInfo("  running in {0} cores with chunks size {1}".format(num_process, chunksize))

    # check
    feedback.pushInfo("  checking band and pixel size: ")
    for image in images:
        if band > image.n_bands:
            raise QgsProcessingException(
                "\n\nError: the image '{0}' don't have the band {1} needed to process\n".format(image.file_path, band))
        if (round(image.x_res, 1) != round(wrapper_x_res, 1)
                or round(image.y_res, 1) != round(wrapper_y_res, 1)):
            raise QgsProcessingException(
                "\n\nError: the image '{}' don't have the same pixel size to the base image: {}x{} vs {}x{}."
                " The stack-composed is not enabled for process yet images with different pixel size.\n"
                .format(image.file_path, round(image.x_res, 1), round(image.y_res, 1),
                        round(wrapper_x_res, 1), round(wrapper_y_res, 1)))
    feedback.pushInfo("ok")

    # set bounds for all images
    for image in images:
        image.set_bounds()

    # for some statistics that required filename as metadata
    if stat in ["last_pixel", "jday_last_pixel", "jday_median", "linear_trend"]:
        for image in images:
            image.set_metadata_from_filename()

    # choose the default data type based on the statistic
    if output_type in [None, '', 'Default']:
        if stat in ['max', 'min', 'last_pixel']:
            gdal_output_type = images[0].data_type[band]
        elif stat == 'sum':
            # Use float64 if input is float64, otherwise float32 to avoid overflow
            if images[0].data_type[band] == gdal.GDT_Float64:
                gdal_output_type = gdal.GDT_Float64
            else:
                gdal_output_type = gdal.GDT_Float32
        elif stat in ['jday_last_pixel', 'jday_median']:
            gdal_output_type = gdal.GDT_UInt16
        elif stat in ['median', 'mean', 'gmean', 'std', 'snr'] or stat.startswith(('percentile_', 'trim_mean_', 'extract_')):
            # Use float64 if input is float64, otherwise float32
            if images[0].data_type[band] == gdal.GDT_Float64:
                gdal_output_type = gdal.GDT_Float64
            else:
                gdal_output_type = gdal.GDT_Float32
        elif stat == 'valid_pixels':
            if len(images) < 256:
                gdal_output_type = gdal.GDT_Byte
            else:
                gdal_output_type = gdal.GDT_UInt16
        elif stat == 'linear_trend':
            gdal_output_type = gdal.GDT_Int32
        else:
            gdal_output_type = gdal.GDT_Float32
    else:
        _OUTPUT_TYPE_MAP = {
            'Byte': gdal.GDT_Byte,
            'UInt16': gdal.GDT_UInt16,
            'UInt32': gdal.GDT_UInt32,
            'Int16': gdal.GDT_Int16,
            'Int32': gdal.GDT_Int32,
            'Float32': gdal.GDT_Float32,
            'Float64': gdal.GDT_Float64,
        }
        gdal_output_type = _OUTPUT_TYPE_MAP.get(output_type, gdal.GDT_Float32)
    for image in images:
        image.output_type = gdal_output_type

    # resolve nodata value depend of the output type
    if nodata is not None:
        output_nodata_value = nodata
    else:
        nodata_from_file = {image.nodata_from_file[band] for image in images}
        if len(nodata_from_file) == 1 and None not in nodata_from_file:
            output_nodata_value = nodata_from_file.pop()
        else:
            output_nodata_value = None

    ### process ###
    # Calculate the statistics
    feedback.pushInfo("\nProcessing the {} for band {}:".format(stat, band))
    output_array = statistic(stat, preproc, images, band, num_process, chunksize, feedback)

    if feedback.isCanceled():
        return

    ### save result ###
    # create output raster
    driver = gdal.GetDriverByName('GTiff')
    nbands = 1
    outRaster = driver.Create(output, wrapper_shape[1], wrapper_shape[0],
                              nbands, gdal_output_type)
    outband = outRaster.GetRasterBand(nbands)

    # set nodata value depend of the output type
    if output_nodata_value is not None:
        outband.SetNoDataValue(output_nodata_value)
    elif gdal_output_type in [gdal.GDT_Byte, gdal.GDT_UInt16, gdal.GDT_UInt32, gdal.GDT_Int16, gdal.GDT_Int32]:
        outband.SetNoDataValue(0)
    elif gdal_output_type in [gdal.GDT_Float32, gdal.GDT_Float64]:
        outband.SetNoDataValue(np.nan)

    # For integer outputs, replace NaN with the nodata sentinel before writing
    if gdal_output_type in [gdal.GDT_Byte, gdal.GDT_UInt16, gdal.GDT_UInt32, gdal.GDT_Int16, gdal.GDT_Int32]:
        nodata_write = output_nodata_value if output_nodata_value is not None else 0
        output_array = np.where(np.isnan(output_array), nodata_write, output_array)

    # write band
    outband.WriteArray(output_array)

    # set projection and geotransform
    outRasterSRS = osr.SpatialReference()
    outRasterSRS.ImportFromWkt(Image.projection)
    outRaster.SetProjection(outRasterSRS.ExportToWkt())
    outRaster.SetGeoTransform((Image.wrapper_extent[0], Image.wrapper_x_res, 0,
                               Image.wrapper_extent[1], 0, -Image.wrapper_y_res))

    # clean
    del driver, outRaster, outband, outRasterSRS, output_array
    reset_dataset_cache()
