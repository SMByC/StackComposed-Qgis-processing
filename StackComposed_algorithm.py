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
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterMultipleLayers,
                       QgsProcessingParameterRasterDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum, QgsProcessingParameterDefinition,
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
        html_help = '''
        <p>StackComposed is a Qgis plugin processing that compute the stack composed (assemble and reduce) using a \
        statistic to get the final value. The input stack layers is, for example a time series of georeferenced data \
        (such as Landsat images) and they can be different scenes or have different extents to generate a mosaic. \
        The result is an assembled image, with a  wrapper extent for all input data, with the pixel values resulting \
        from the statistic for the specific band for all the valid pixels across the time axis (z-axis), in a parallel \
        process.</p>
        <h3 id="recommendation-for-data-input">Recommendation for input data</h3>
        <p>There are some recommendation for input data for process it, all input images need:</p>
        - To be in the same projection
        - Have the same pixel size
        - Have pixel registration
        <p>For the moment, the image formats support are: <code>tif</code>, <code>img</code> and <code>ENVI</code> (hdr)</p>
        '''
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
        return 'Assemble and reduce an image stack'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr(self.name())

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
        return QIcon(":/plugins/StackComposed/icons/stack_composed.svg")

    def initAlgorithm(self, config=None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        parameter_input = \
            QgsProcessingParameterMultipleLayers(
                self.INPUTS,
                self.tr('All input raster files to process'),
                QgsProcessing.SourceType.TypeRaster,
            )
        parameter_input.setMinimumNumberInputs(2)
        self.addParameter(parameter_input)

        self.addParameter(
            QgsProcessingParameterEnum(
                self.STAT,
                self.tr('Statistic for compute the composed'),
                self.STAT_DESC,
                allowMultiple=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BAND,
                self.tr('Set the band number to process'),
                type=QgsProcessingParameterNumber.Type.Integer,
                minValue=1,
                defaultValue=1,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.NODATA_INPUT,
                self.tr('Input pixel value to treat as "nodata"'),
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=None,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DATA_TYPE,
                self.tr('Output data type'),
                self.TYPES,
                allowMultiple=False,
                defaultValue='Default',
            )
        )

        parameter_num_process = \
            QgsProcessingParameterNumber(
                self.NUM_PROCESS,
                self.tr('Set the number of process'),
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=cpu_count(),
                optional=True
            )
        parameter_num_process.setFlags(parameter_num_process.flags() | QgsProcessingParameterDefinition.Flag.FlagAdvanced)
        self.addParameter(parameter_num_process)

        parameter_chunks = \
            QgsProcessingParameterNumber(
                self.CHUNKS,
                self.tr('Chunks size for parallel process'),
                type=QgsProcessingParameterNumber.Type.Integer,
                defaultValue=500,
                optional=True
            )
        parameter_chunks.setFlags(parameter_chunks.flags() | QgsProcessingParameterDefinition.Flag.FlagAdvanced)
        self.addParameter(parameter_chunks)

        self.addParameter(
            QgsProcessingParameterString(
                self.PREPROC,
                self.tr('Preprocessing filter (optional)'),
                defaultValue='',
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                self.tr('Output raster stack composed')
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
        # Plain numeric threshold
        try:
            return float(preproc_str)
        except ValueError:
            pass

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
