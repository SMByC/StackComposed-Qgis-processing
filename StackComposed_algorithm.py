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
import os
from multiprocessing import cpu_count

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (Qgis,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterMultipleLayers,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterString)

from StackComposed.core import stack_composed


class StackComposedAlgorithm(QgsProcessingAlgorithm):
    """
    This algorithm compute a specific statistic using the time
    series of all pixels across (the time) all raster in the specific band
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    INPUTS = 'INPUTS'
    STAT = 'STAT'
    BAND = 'BAND'
    NODATA_INPUT = 'NODATA_INPUT'
    DATA_TYPE = 'DATA_TYPE'
    NUM_PROCESS = 'NUM_PROCESS'
    CHUNKS = 'CHUNKS'
    PREPROC = 'PREPROC'
    OUTPUT = 'OUTPUT'

    STAT_KEYS = ['median', 'mean', 'gmean', 'max', 'min', 'sum', 'std', 'valid_pixels', 'last_pixel', 'jday_last_pixel',
                 'jday_median', 'linear_trend']
    STAT_DESC = ['Median', 'Arithmetic mean', 'Geometric mean', 'Maximum value', 'Minimum value', 'Sum',
                 'Standard deviation', 'Number of valid pixels', 'Last valid pixel (required filename as metadata)',
                 'Julian day of the last valid pixel (required filename as metadata)',
                 'Julian day of the median value (required filename as metadata)',
                 'Linear trend least-squares method (required filename as metadata)']

    TYPES = ['Default', 'Byte', 'UInt16', 'Int16', 'UInt32', 'Int32', 'Float32', 'Float64']

    def __init__(self):
        super().__init__()

    def tr(self, string, context=''):
        if context == '':
            context = self.__class__.__name__
        return QCoreApplication.translate(context, string)

    def shortHelpString(self):
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and outputs associated with it.
        """
        html_help = (
            "<p>StackComposed computes a per-pixel statistic over a stack of "
            "georeferenced raster images, such as a Landsat time series. Input "
            "images can cover different scenes, tiles, or partially overlapping "
            "areas. It builds one wrapper extent that covers all inputs, reads "
            "each processing chunk from every image, masks nodata values as "
            "<code>NaN</code>, and writes the selected statistic to a GeoTIFF.</p>"

            "<p><b>Input requirements</b><br>"
            "All input rasters must:<br>"
            "&bull; use the same projection<br>"
            "&bull; use the same pixel size<br>"
            "&bull; be aligned to the same pixel grid<br>"
            "&bull; have at least the requested band number<br><br>"
            "At least two images are required. Inputs are loaded raster layers "
            "in the QGIS project; any format that QGIS can read through GDAL is "
            "accepted (most commonly <code>.tif</code>, <code>.img</code>, and "
            "<code>.hdr</code> for ENVI datasets).</p>"

            "<p><b>Important: mask your input nodata</b><br>"
            "StackComposed relies on nodata metadata to distinguish valid pixels "
            "from missing observations along the Z-axis. If your rasters do not "
            "declare a nodata value, set it explicitly with the <b>Nodata value</b> "
            "parameter &mdash; otherwise pixels that should be ignored (background, "
            "fill, or out-of-scene areas) will enter the statistic as real values "
            "and skew the result. Always confirm that each input "
            "either has a correct nodata value in its metadata or supplies one "
            "through this parameter before running the statistic.</p>"

            "<p><b>Statistics</b> (computed along the Z-axis, ignoring nodata/NaN)<br>"
            "&bull; <b>Median</b> &mdash; median of valid values<br>"
            "&bull; <b>Arithmetic mean</b> &mdash; arithmetic mean of valid values<br>"
            "&bull; <b>Geometric mean</b> &mdash; geometric mean, uses positive values only<br>"
            "&bull; <b>Maximum value</b> &mdash; maximum valid value<br>"
            "&bull; <b>Minimum value</b> &mdash; minimum valid value<br>"
            "&bull; <b>Sum</b> &mdash; sum of valid values<br>"
            "&bull; <b>Standard deviation</b> &mdash; standard deviation of valid values<br>"
            "&bull; <b>Number of valid pixels</b> &mdash; count of valid observations<br>"
            "&bull; <b>Last valid pixel</b> &mdash; pixel value from the most recent valid "
            "dated image (requires filename metadata)<br>"
            "&bull; <b>Julian day of the last valid pixel</b> &mdash; Julian day of the most "
            "recent valid dated image (requires filename metadata)<br>"
            "&bull; <b>Julian day of the median value</b> &mdash; Julian day of the temporal "
            "median position (requires filename metadata)<br>"
            "&bull; <b>Linear trend</b> &mdash; ordinary least squares slope multiplied by "
            "1e6 (requires filename metadata)</p>"

            "<p><b>Preprocessing filter</b> (optional, applied to each pixel's stack "
            "of values before the statistic; values that fail the condition become "
            "nodata/NaN)<br>"
            "&bull; <code>&gt;N</code>, <code>&gt;=N</code>, <code>&lt;N</code>, "
            "<code>&lt;=N</code>, <code>==N</code>, <code>!=N</code> &mdash; keep values "
            "matching a comparison<br>"
            "&bull; <code>&gt;A and &lt;B</code> &mdash; keep values matching both "
            "comparisons (only <code>and</code> is supported)<br>"
            "&bull; <code>percentile_LL_UL</code> &mdash; keep values between per-pixel "
            "percentile bounds (e.g. <code>percentile_10_90</code>)<br>"
            "&bull; <code>NN_std_devs</code> &mdash; keep values within <code>NN</code> "
            "standard deviations of the per-pixel mean (e.g. <code>2.5_std_devs</code>)<br>"
            "&bull; <code>NN_IQR</code> &mdash; keep values within <code>NN</code> "
            "interquartile ranges of the per-pixel median (e.g. <code>1.5_IQR</code>)</p>"

            "<p><b>Filename metadata</b><br>"
            "The date-dependent statistics (Last valid pixel, Julian day of the last "
            "valid pixel, Julian day of the median value, Linear trend) require date "
            "metadata parsed from the filename. Supported Landsat filename styles:<br>"
            "&bull; Old Landsat IDs: <code>LC80070592016320LGN00_band1.tif</code><br>"
            "&bull; New Landsat product IDs: "
            "<code>LC08_L1TP_007059_20161115_20170318_01_T2_b1.tif</code><br>"
            "&bull; SMByC format: <code>Landsat_8_53_020601_7ETM_Reflec_SR_Enmask.tif</code></p>"

            "<p>See the plugin README for full documentation on output data types, "
            "chunk sizing, and examples.</p>"
        )
        return html_help

    def createInstance(self):
        return StackComposedAlgorithm()

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'assemble_reduce_image_stack'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Assemble and reduce an image stack')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return None

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return None

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "stack_composed.svg")
        return QIcon(icon_path)

    def initAlgorithm(self, config=None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        parameter_input = \
            QgsProcessingParameterMultipleLayers(
                self.INPUTS,
                self.tr('Input raster layers to process (two or more)'),
                Qgis.ProcessingSourceType.Raster,
            )
        parameter_input.setMinimumNumberInputs(2)
        self.addParameter(parameter_input)

        self.addParameter(
            QgsProcessingParameterEnum(
                self.STAT,
                self.tr('Statistic to compute along the Z-axis'),
                self.STAT_DESC,
                allowMultiple=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BAND,
                self.tr('Band number to process'),
                type=Qgis.ProcessingNumberParameterType.Integer,
                minValue=1,
                defaultValue=1,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.NODATA_INPUT,
                self.tr('Input pixel value to treat as nodata (overrides file metadata)'),
                type=Qgis.ProcessingNumberParameterType.Integer,
                defaultValue=None,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DATA_TYPE,
                self.tr('Output data type (Default selects automatically based on the statistic)'),
                self.TYPES,
                allowMultiple=False,
                defaultValue='Default',
            )
        )

        parameter_num_process = \
            QgsProcessingParameterNumber(
                self.NUM_PROCESS,
                self.tr('Number of parallel worker threads'),
                type=Qgis.ProcessingNumberParameterType.Integer,
                defaultValue=cpu_count(),
                optional=True
            )
        parameter_num_process.setFlags(parameter_num_process.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(parameter_num_process)

        parameter_chunks = \
            QgsProcessingParameterNumber(
                self.CHUNKS,
                self.tr('Chunk size in pixels (larger chunks reduce overhead but use more memory)'),
                type=Qgis.ProcessingNumberParameterType.Integer,
                defaultValue=500,
                optional=True
            )
        parameter_chunks.setFlags(parameter_chunks.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(parameter_chunks)

        self.addParameter(
            QgsProcessingParameterString(
                self.PREPROC,
                self.tr('Preprocessing filter expression (optional)'),
                defaultValue='',
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                self.tr('Output raster (GeoTIFF)')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        layers = self.parameterAsLayerList(parameters, self.INPUTS, context)
        images_files = [os.path.realpath(layer.source().split("|layername")[0]) for layer in layers]

        output_file = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        # Parse preprocessing argument (same logic as CLI preproc_validator)
        preproc_str = self.parameterAsString(parameters, self.PREPROC, context)
        preproc = self._parse_preproc(preproc_str) if preproc_str else None

        stack_composed.run(
            stat=self.STAT_KEYS[self.parameterAsEnum(parameters, self.STAT, context)],
            preproc=preproc,
            band=self.parameterAsInt(parameters, self.BAND, context),
            nodata=self.parameterAsInt(parameters, self.NODATA_INPUT, context),
            output=output_file,
            output_type=self.TYPES[self.parameterAsEnum(parameters, self.DATA_TYPE, context)],
            num_process=self.parameterAsInt(parameters, self.NUM_PROCESS, context),
            chunksize=self.parameterAsInt(parameters, self.CHUNKS, context),
            images_files=images_files,
            feedback=feedback)

        return {self.OUTPUT: output_file}

    @staticmethod
    def _parse_preproc(preproc_str):
        """Parse a preprocessing expression string into the form expected by ChunkProcessor."""
        # Named preprocessors (percentile, std_devs, IQR) are passed through as strings
        if preproc_str.startswith("percentile_") or preproc_str.endswith("_std_devs") or preproc_str.endswith("_IQR"):
            return preproc_str

        # Comparison expressions: e.g. '>3', '>=1 and <=5'
        _CMP_OPS = {"<", "<=", ">", ">=", "==", "!="}

        def _split_condition(s):
            s = s.strip().replace(" ", "")
            if not s:
                raise ValueError
            if len(s) > 1 and s[1] == "=":
                op = s[0:2]
                value = s[2:]
            else:
                op = s[0:1]
                value = s[1:]
            if op not in _CMP_OPS:
                raise ValueError
            return [op, float(value)]

        try:
            if "and" in preproc_str:
                return [_split_condition(c) for c in preproc_str.split("and")]
            return [_split_condition(preproc_str)]
        except Exception:
            raise ValueError(
                f"'{preproc_str}' is not a valid preprocessing expression. "
                "Examples: '>3', '>=1 and <=5', 'percentile_10_90', '2.5_std_devs', '1.5_IQR'"
            )
