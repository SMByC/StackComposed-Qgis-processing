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
import importlib
import os
import site

from qgis.PyQt.QtWidgets import QMessageBox

from .utils import extlibs


def check_dependencies():
    try:
        importlib.import_module("dask.array")
        callbacks = importlib.import_module("dask.callbacks")
        getattr(callbacks, "Callback")

        return True
    except (AttributeError, ImportError):
        return False


def pre_init_plugin():
    extra_libs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "extlibs"))
    if os.path.isdir(extra_libs_path):
        # add to python path
        site.addsitedir(extra_libs_path)

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load StackComposed class from file StackComposed.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    # load extra python dependencies
    pre_init_plugin()

    if not check_dependencies():
        extlibs.install()
        pre_init_plugin()

        if not check_dependencies():
            msg = (
                "Error loading libraries for StackComposed.\n\n"
                "Read the install instructions here:\n"
                "https://github.com/SMByC/StackComposed-Qgis-processing#installation"
            )
            QMessageBox.critical(
                None,
                "StackComposed: Error loading",
                msg,
                QMessageBox.StandardButton.Ok,
            )

    from .StackComposed_plugin import StackComposedPlugin
    return StackComposedPlugin()
