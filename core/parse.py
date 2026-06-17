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
import datetime
import os


_SENSOR_FROM_CODE = {"E": "ETM", "O": "OLI", "C": "OLI", "T": "TM"}


def calc_date(year, jday):
    return (datetime.datetime(year, 1, 1) + datetime.timedelta(jday - 1)).date()


def _sensor_from_code(code: str) -> str:
    try:
        return _SENSOR_FROM_CODE[code]
    except KeyError as err:
        raise ValueError(f"Unknown Landsat sensor code: {code!r}") from err


#### LANDSAT PARSE FILENAME ####


def parse_landsat_ID_oldFilename(file_path):
    """
    Parse the original structure of old Landsat filename

    Examples:
        LC80070592016320LGN00_band1.tif
    """
    filename = os.path.basename(file_path).split("_")[0].split(".")[0].upper()
    sensor = _sensor_from_code(filename[1])
    landsat_version = int(filename[2])
    path = int(filename[3:6])
    row = int(filename[6:9])
    year = int(filename[9:13])
    jday = int(filename[13:16])
    date = calc_date(year, jday)
    return landsat_version, sensor, path, row, date, jday


def parse_landsat_ID_newFilename(file_path):
    """
    Parse the original structure of new Landsat filename

    Examples:
        LC08_L1TP_007059_20161115_20170318_01_T2_b1.tif
    """
    parts = [p.upper() for p in os.path.basename(file_path).split("_")[0:4]]
    sensor = _sensor_from_code(parts[0][1])
    landsat_version = int(parts[0][-1])
    path = int(parts[2][0:3])
    row = int(parts[2][3:6])
    date = datetime.datetime.strptime(parts[3], "%Y%m%d").date()
    jday = date.timetuple().tm_yday
    return landsat_version, sensor, path, row, date, jday


#### SMBYC structure of Landsat filename


def parse_SMBYC_filename(file_path):
    """
    Parse the SMBYC structure of Landsat filename

    Examples:
        Landsat_8_53_020601_7ETM_Reflec_SR_Enmask.tif
    """
    parts = os.path.basename(file_path).split(".")[0].split("_")
    path = int(parts[1])
    row = int(parts[2])
    date = datetime.datetime.strptime(parts[3], "%y%m%d").date()
    jday = date.timetuple().tm_yday
    landsat_version = int(parts[4][0])
    sensor = parts[4][1:]
    return landsat_version, sensor, path, row, date, jday


def parse_filename(file_path):
    """
    Extract metadata from filename
    """
    filename = os.path.basename(file_path)

    try:
        if filename.startswith("Landsat"):
            # SMBYC format
            return parse_SMBYC_filename(file_path)
        elif filename[4] == "_":
            # new ESPA filename
            return parse_landsat_ID_newFilename(file_path)
        else:
            # old filename
            return parse_landsat_ID_oldFilename(file_path)
    except Exception as err:
        raise Exception(f"Cannot parse filename for: {file_path}\n\n{err}") from err

