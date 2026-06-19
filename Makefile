#/***************************************************************************
# StackComposed
#
#  Compute and generate the composed of a raster images stack
#							 -------------------
#		copyright			: (C) 2026 by Xavier Corredor Llano, SMByC
#		email				: xcorredorl@ideam.gov.co
# ***************************************************************************/
#
#/***************************************************************************
# *																		 *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU General Public License as published by  *
# *   the Free Software Foundation; either version 2 of the License, or	 *
# *   (at your option) any later version.								   *
# *																		 *
# ***************************************************************************/

#################################################
# Edit the following to match your sources lists
#################################################


PLUGINNAME = StackComposed

PY_FILES = \
	__init__.py \
	StackComposed_algorithm.py \
	StackComposed_plugin.py \
	StackComposed_provider.py

EXTRAS = metadata.txt LICENSE

EXTRA_DIRS = core utils icons

#################################################
# Normally you would not need to edit below here
#################################################

PLUGIN_UPLOAD = python3 plugin_upload.py -u xaviercll

EXTLIBS_DEPS = \
	dask==2024.7.1 \
	toolz \
	cloudpickle \
	fsspec \
	packaging \
	partd \
	locket

default: zip

.PHONY: default extlibs zip upload clean

extlibs:
	@echo
	@echo "--------------------------------"
	@echo "Creating extlibs zip bundle."
	@echo "--------------------------------"
	rm -rf extlibs_tmp
	rm -f extlibs.zip
	mkdir -p extlibs_tmp/extlibs
	pip install \
		--target=extlibs_tmp/extlibs \
		--no-deps \
		$(EXTLIBS_DEPS)
	find extlibs_tmp/extlibs -type d \( -name "__pycache__" -o -name "*.dist-info" -o -name "*.egg-info" -o -name "tests" -o -name "test" -o -name "bin" \) -prune -exec rm -rf {} + 2>/dev/null || true
	find extlibs_tmp/extlibs -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.so" -o -name "*.dll" -o -name "*.dylib" \) -delete 2>/dev/null || true
	cd extlibs_tmp && zip -9r ../extlibs.zip extlibs
	rm -rf extlibs_tmp
	@echo "Created package: extlibs.zip"

zip:
	@echo
	@echo "---------------------------"
	@echo "Creating plugin zip bundle."
	@echo "---------------------------"
	rm -f $(PLUGINNAME).zip
	rm -rf .pkg_tmp
	mkdir -p .pkg_tmp/$(PLUGINNAME)
	cp -f $(PY_FILES) $(EXTRAS) .pkg_tmp/$(PLUGINNAME)/
	@for d in $(EXTRA_DIRS); do \
		if [ -d "$$d" ]; then cp -rf $$d .pkg_tmp/$(PLUGINNAME)/; fi; \
	done
	find .pkg_tmp -type d \( -name "__pycache__" -o -name "*.dist-info" -o -name "*.egg-info" -o -name "tests" -o -name "test" -o -name "bin" \) -prune -exec rm -rf {} + 2>/dev/null || true
	find .pkg_tmp -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.sh" -o -name "*.db" -o -name "*.so" -o -name "*.dll" -o -name "*.dylib" \) -delete 2>/dev/null || true
	cd .pkg_tmp && zip -9r ../$(PLUGINNAME).zip $(PLUGINNAME)
	rm -rf .pkg_tmp
	@echo "Created package: $(PLUGINNAME).zip"

upload: zip
	@echo
	@echo "-------------------------------------"
	@echo "Uploading plugin to QGIS Plugin repo."
	@echo "-------------------------------------"
	$(PLUGIN_UPLOAD) $(PLUGINNAME).zip

clean:
	@echo
	@echo "------------------------------------"
	@echo "Removing generated files"
	@echo "------------------------------------"
	rm -rf .pkg_tmp extlibs_tmp
	rm -f $(PLUGINNAME).zip extlibs.zip
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
