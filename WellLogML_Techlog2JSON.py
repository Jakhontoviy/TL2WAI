# -*- coding: utf-8 -*-
import json
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import logging
import re
import numpy as np
import TechlogDatabase as db

TECHLOG_JSON_ROOT = r'C:\Temp\TL'
TECHLOG_JSON_LOG_DIR = os.path.join(TECHLOG_JSON_ROOT, 'log')


class WellLogMLGenerator:
    """Generates WellLogML JSON files from Techlog data."""

    def __init__(self, techlog_version: str = "2023.1", logger: logging.Logger = None):
        self.techlog_version = techlog_version
        self.data = None
        self.logger = logger
        self.current_dataset_name = None
        self.current_well_name = None

    @staticmethod
    def _parse_history_item(history_string: str) -> Tuple[str, str, str]:
        """
        Parse a Techlog history string.

        Expected format: "History item created at 2025-12-31T02:27:25.028 by user. Created"

        Returns:
            Tuple (timestamp, username, action) where timestamp is a Unix timestamp string.
        """
        pattern = r'at\s+([^\s]+(?:T[^\s]+)?)\s+by\s+([^.]+)\.\s*(.+)'
        match = re.search(pattern, history_string)

        if match:
            datetime_str = match.group(1).strip()
            username = match.group(2).strip()
            action = match.group(3).strip()

            try:
                if 'T' in datetime_str:
                    if '.' in datetime_str:
                        datetime_str = datetime_str.split('.')[0]
                    dt = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')
                    timestamp = str(int(dt.timestamp()))
                else:
                    dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                    timestamp = str(int(dt.timestamp()))
            except Exception:
                timestamp = str(int(datetime.now().timestamp()))

            return timestamp, username, action
        else:
            return str(int(datetime.now().timestamp())), 'unknown', history_string

    def _get_timestamp(self) -> int:
        """Return the current Unix timestamp."""
        return int(datetime.now().timestamp())

    def _get_username(self) -> str:
        """Return the current OS username."""
        return os.getenv('USERNAME', os.getenv('USER', 'user'))


    @staticmethod
    def _is_html_content(text: str) -> Tuple[bool, str]:
        """
        Detect HTML-like content in text properties.

        Returns:
            Tuple (is_html, reason) where is_html is True if the text looks like HTML.
        """
        if not isinstance(text, str):
            return False, ""

        text_stripped = text.strip()
        if not text_stripped:
            return False, ""

        # Check 1: starts with '<' and contains HTML tags
        if text_stripped.startswith('<') and ('>' in text_stripped):
            html_tags = ['<table', '<tr', '<td', '<th', '<div', '<span', '<html', '<body',
                        '<head', '<p>', '<br', '<a href', '<form', '<input', '<script', '<style']
            for tag in html_tags:
                if tag.lower() in text_stripped.lower():
                    return True, f"HTML tag found: {tag}"

        # Check 2: large text (> 500 chars) with HTML structure
        if len(text_stripped) > 500:
            html_indicators = ['<table', '<tr', '<td', '<th', '&nbsp;', '&lt;', '&gt;', '&amp;']
            indicators_found = sum(1 for ind in html_indicators if ind.lower() in text_stripped.lower())
            if indicators_found >= 1:
                return True, f"Large text ({len(text_stripped)} chars) with HTML structure"

        return False, ""

    @staticmethod
    def _detect_data_type(data) -> str:
        """
        Determine data type: 'numeric', 'string', or 'mixed'.

        Returns:
            'numeric' — all values are numeric (int, float, or NaN)
            'string'  — contains string values
            'mixed'   — mixed types
        """
        if data is None or len(data) == 0:
            return 'empty'

        has_numeric = False
        has_string = False

        for val in data:
            if val is None:
                continue

            if isinstance(val, (int, float, np.integer, np.floating)):
                has_numeric = True
                continue

            if isinstance(val, str):
                try:
                    float(val)
                    has_numeric = True
                except (ValueError, TypeError):
                    has_string = True
                continue

            has_string = True

        if has_string and has_numeric:
            return 'mixed'
        elif has_string:
            return 'string'
        elif has_numeric:
            return 'numeric'
        else:
            return 'unknown'



    def _log(self, message: str, level: str = 'info'):
        if self.logger:
            log_fn = getattr(self.logger, level, self.logger.info)
            log_fn(message)

    def _extract_properties(self, prop_list: List[str], get_value_fn, get_unit_fn,
                          get_desc_fn) -> Dict[str, Dict[str, str]]:
        """Generic property extraction from any Techlog entity."""
        properties = {}
        for prop_name in prop_list:
            if prop_name == 'ID':
                continue
            try:
                prop_value = get_value_fn(prop_name)
                if self._is_html_content(str(prop_value) if prop_value is not None else '')[0]:
                    continue
                properties[prop_name] = {
                    "value": str(prop_value) if prop_value is not None else '',
                    "unit": get_unit_fn(prop_name) or '',
                    "description": get_desc_fn(prop_name) or ''
                }
            except Exception:
                pass
        return properties

    def _process_history(self, history_list) -> List[Dict[str, str]]:
        """Generic history processing for any Techlog entity."""
        history = []
        if not history_list:
            return history
        for hist_item in history_list:
            if isinstance(hist_item, dict):
                history.append({
                    "dateTime": str(hist_item.get('dateTime', self._get_timestamp())),
                    "userName": hist_item.get('userName', self._get_username()),
                    "action": hist_item.get('action', '')
                })
            else:
                hist_item_str = str(hist_item).strip()
                if 'History item created at' in hist_item_str and ' by ' in hist_item_str:
                    timestamp, username, action = self._parse_history_item(hist_item_str)
                    history.append({"dateTime": timestamp, "userName": username, "action": action})
                else:
                    history.append({
                        "dateTime": str(self._get_timestamp()),
                        "userName": self._get_username(),
                        "action": hist_item_str
                    })
        return history

    def create_document(self, well_name: str) -> bool:
        """Create the base document structure for a well."""
        try:
            well_name_value = db.wellName(well_name)
        except Exception:
            well_name_value = well_name

        self.current_well_name = well_name_value

        self.data = {
            "WellLogML": {
                "DocumentInformation": {
                    "dtdVersion": {
                        "@extended": "no",
                        "@number": "1.0",
                        "#text": "ContinuFile"
                    },
                    "FileCreationInformation": {
                        "softwareName": {
                            "@version": self.techlog_version,
                            "#text": "Techlog"
                        }
                    }
                },
                well_name_value: {}
            }
        }

        well_info = self.data["WellLogML"][well_name_value]

        try:
            well_color = db.wellColor(well_name)
            if well_color:
                well_info["wellColor"] = well_color
        except Exception:
            pass

        try:
            well_group = db.wellGroup(well_name)
            if well_group:
                if isinstance(well_group, (list, tuple)):
                    well_info["wellGroup"] = ', '.join(str(g) for g in well_group)
                else:
                    well_info["wellGroup"] = str(well_group)
        except Exception:
            pass

        well_info["wellProperties"] = {}

        try:
            prop_list = db.wellPropertyList(well_name)
            well_info["wellProperties"] = self._extract_properties(
                prop_list,
                lambda p: db.wellPropertyValue(well_name, p),
                lambda p: db.wellPropertyUnit(well_name, p),
                lambda p: db.wellPropertyDescription(well_name, p)
            )
        except Exception:
            pass

        well_info["wellHistory"] = []
        try:
            history = db.wellHistory(well_name)
            well_info["wellHistory"] = self._process_history(history)
        except Exception:
            pass

        well_info["datasets"] = {}
        return True

    def add_dataset(self, well_name: str, dataset_name: str) -> bool:
        """
        Add dataset information to the document.

        Returns:
            True if the dataset was added successfully.
        """
        if self.data is None:
            raise ValueError("Call create_document() before add_dataset()")

        try:
            dataset_name_value = db.datasetName(well_name, dataset_name)
        except Exception:
            dataset_name_value = dataset_name

        dataset_dict = {}

        try:
            dataset_type = db.datasetType(well_name, dataset_name)
            if dataset_type:
                dataset_dict["datasetType"] = str(dataset_type)
        except Exception:
            pass

        try:
            dataset_group = db.datasetGroup(well_name, dataset_name)
            if dataset_group:
                if isinstance(dataset_group, (list, tuple)):
                    dataset_dict["datasetGroup"] = ', '.join(str(g) for g in dataset_group)
                else:
                    dataset_dict["datasetGroup"] = str(dataset_group)
        except Exception:
            pass

        index_curve_info = None

        try:
            dataset_size = db.datasetSize(well_name, dataset_name)
            ref_name = db.referenceName(well_name, dataset_name)

            dataset_dict["MeasurementDetails"] = {
                "startIndex": 0,
                "endIndex": dataset_size - 1 if dataset_size > 0 else 0
            }

            try:
                ref_unit = db.variableUnit(well_name, dataset_name, ref_name)
                sampling_rate = db.datasetSamplingRate(well_name, dataset_name, True, ref_unit)

                dataset_dict["MeasurementDetails"]["evenSampling"] = {
                    "@index_curve": ref_name,
                    "stepIncrement": float(sampling_rate) if sampling_rate else 0.1
                }
            except Exception:
                dataset_dict["MeasurementDetails"]["evenSampling"] = {
                    "@index_curve": ref_name,
                    "stepIncrement": 0.1
                }

            try:
                index_data = db.variableLoad(well_name, dataset_name, ref_name)
                if index_data is not None:
                    if not isinstance(index_data, np.ndarray):
                        index_data = np.array(index_data)

                    try:
                        index_unit = db.variableUnit(well_name, dataset_name, ref_name)
                    except Exception:
                        index_unit = ''

                    try:
                        index_desc = db.variableDescription(well_name, dataset_name, ref_name)
                    except Exception:
                        index_desc = ''

                    try:
                        index_type = db.variableType(well_name, dataset_name, ref_name)
                    except Exception:
                        index_type = 'Continuous'

                    try:
                        index_family = db.variableFamily(well_name, dataset_name, ref_name)
                    except Exception:
                        index_family = ''

                    try:
                        index_values = [float(val) for val in np.asarray(index_data, dtype=float)]
                    except (ValueError, TypeError):
                        index_values = [str(val) if val is not None else '' for val in index_data]

                    index_curve_info = {
                        "name": ref_name,
                        "variableUnit": index_unit,
                        "variableDescription": index_desc,
                        "variableType": index_type,
                        "variableFamily": index_family,
                        "variableData": index_values
                    }

                    self._log(f"      Index curve ready: {ref_name} ({len(index_data):,} values)")
            except Exception as e:
                self._log(f"      Could not load index curve {ref_name}: {e}", 'warning')

        except Exception:
            dataset_dict["MeasurementDetails"] = {
                "startIndex": 0,
                "endIndex": 0,
                "evenSampling": {
                    "@index_curve": "MD",
                    "stepIncrement": 0.1
                }
            }

        dataset_dict["datasetProperties"] = {}

        try:
            prop_list = db.datasetPropertyList(well_name, dataset_name)
            if prop_list:
                dataset_dict["datasetProperties"] = self._extract_properties(
                    prop_list,
                    lambda p: db.datasetPropertyValue(well_name, dataset_name, p),
                    lambda p: db.datasetPropertyUnit(well_name, dataset_name, p),
                    lambda p: db.datasetPropertyDescription(well_name, dataset_name, p)
                )
        except Exception:
            pass

        dataset_dict["datasetHistory"] = []
        try:
            history = db.datasetHistory(well_name, dataset_name)
            dataset_dict["datasetHistory"] = self._process_history(history)
        except Exception:
            pass

        if index_curve_info is not None:
            dataset_dict["index"] = index_curve_info
            self._log(f"      Index curve added: {index_curve_info['name']} ({len(index_curve_info['variableData']):,} values)")

        dataset_dict["variables"] = {}

        self.data["WellLogML"][self.current_well_name]["datasets"][dataset_name_value] = dataset_dict
        self.current_dataset_name = dataset_name_value
        return True

    def add_curve(self, well_name: str, dataset_name: str, variable_name: str,
                  data: Optional[np.ndarray] = None, null_value: float = -9999) -> bool:
        """
        Add a variable to the current dataset.

        Returns:
            False if the variable has no valid ID property.
        """
        if self.data is None or self.current_dataset_name is None:
            raise ValueError("Call add_dataset() before add_curve()")

        username = self._get_username()

        try:
            var_type = db.variableType(well_name, dataset_name, variable_name)
        except Exception:
            var_type = 'Continuous'

        try:
            family = db.variableFamily(well_name, dataset_name, variable_name)
        except Exception:
            family = ''

        try:
            unit = db.variableUnit(well_name, dataset_name, variable_name)
        except Exception:
            unit = ''

        try:
            description = db.variableDescription(well_name, dataset_name, variable_name)
        except Exception:
            description = ''

        try:
            group = db.variableGroup(well_name, dataset_name, variable_name)
            if isinstance(group, (list, tuple)):
                group_str = ', '.join(str(g) for g in group) if group else ''
            else:
                group_str = str(group) if group else ''
        except Exception:
            group_str = ''

        try:
            var_name = db.variableName(well_name, dataset_name, variable_name)
        except Exception:
            var_name = variable_name

        data_type = None
        if data is not None and len(data) > 0:
            data_type = self._detect_data_type(data)
            if data_type in ('string', 'mixed'):
                unit = 'unitless'

        variable_dict = {
            "nullValue": null_value,
            "variableType": var_type,
            "variableUnit": unit,
            "variableDescription": description,
            "variableGroup": group_str,
            "variableFamily": family
        }

        try:
            var_history = db.variableHistory(well_name, dataset_name, variable_name)
            history = self._process_history(var_history)
            if not history:
                history = [{"dateTime": str(self._get_timestamp()), "userName": username, "action": "Created"}]
            variable_dict["variableHistory"] = history
        except Exception:
            variable_dict["variableHistory"] = [{"dateTime": str(self._get_timestamp()), "userName": username, "action": "Created"}]

        variable_dict["variableProperties"] = {}

        try:
            prop_list = db.variablePropertyList(well_name, dataset_name, variable_name)
            if prop_list:
                variable_dict["variableProperties"] = self._extract_properties(
                    prop_list,
                    lambda p: db.variablePropertyValue(well_name, dataset_name, variable_name, p),
                    lambda p: db.variablePropertyUnit(well_name, dataset_name, variable_name, p),
                    lambda p: db.variablePropertyDescription(well_name, dataset_name, variable_name, p)
                )
        except Exception:
            pass

        if data is not None and len(data) > 0:
            if data_type in ('numeric', 'mixed'):
                try:
                    data_array = np.asarray(data, dtype=float)
                    data_clean = np.where(
                        (np.isnan(data_array)) | (data_array == null_value),
                        null_value,
                        data_array
                    )
                    variable_dict["variableData"] = [float(val) for val in data_clean]
                except (ValueError, TypeError):
                    variable_dict["variableData"] = [str(val) if val is not None else '' for val in data]
            else:
                variable_dict["variableData"] = [str(val) if val is not None else '' for val in data]
        else:
            variable_dict["variableData"] = []

        self.data["WellLogML"][self.current_well_name]["datasets"][self.current_dataset_name]["variables"][var_name] = variable_dict
        return True

    def save(self, filename: str) -> bool:
        """Save the document to a JSON file."""
        if self.data is None:
            raise ValueError("Call create_document() before save()")

        json_str = json.dumps(self.data, ensure_ascii=False, indent=2)

        def compact_data_array(match):
            indent = match.group(1)
            key_name = match.group(2)
            array_content = match.group(3)

            # Leave string arrays as-is; compact only numeric arrays
            if '"' in array_content:
                return match.group(0)

            values = re.findall(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?', array_content)
            if not values:
                return match.group(0)

            compact = ', '.join(values)
            return f'{indent}"{key_name}": [{compact}]'

        pattern = r'(\s*)"(variableData)":\s*\[((?:[^\[\]]|\n)*?)\]'
        json_str = re.sub(pattern, compact_data_array, json_str)

        target_dir = os.path.dirname(os.path.abspath(filename))
        fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(json_str)
            os.replace(tmp_path, filename)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        file_size = os.path.getsize(filename)
        msg = f"File saved: {filename} (size: {file_size:,} bytes)"
        self._log(msg)
        print(f"  ✓ {msg}")
        return True


def welllogml_write_from_techlog(output_dir: str = None):
    """
    Export all wells from the Techlog database to WellLogML JSON files.
    One file per well named `<WellName>_<timestamp>.json`.

    Args:
        output_dir: Directory for JSON output. Defaults to TECHLOG_JSON_ROOT.
    """
    folderName = output_dir or TECHLOG_JSON_ROOT
    if not os.path.exists(folderName):
        os.makedirs(folderName)
        print(f"Export directory created: {folderName}")
    else:
        print(f"Export directory: {folderName}")

    os.makedirs(TECHLOG_JSON_LOG_DIR, exist_ok=True)
    log_filename = os.path.join(
        TECHLOG_JSON_LOG_DIR, f'{datetime.now().strftime("%Y-%m-%d_%H%M%S")}_TL_export.txt'
    )
    logger = logging.getLogger('WellLogMLExport')
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    export_start_time = datetime.now()

    logger.info("Starting export from Techlog to WellLogML JSON")
    logger.info(f"Start time: {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Export directory: {folderName}")
    logger.info(
        "Export reads only IDs from the DB; entities without an ID are skipped. "
        "Preparation: WellLogML_Techlog_prepare_ids.py"
    )
    print(f"Log file: {log_filename}")
    print(
        "ID properties (24 chars) are required. If needed, run first: "
        "WellLogML_Techlog_prepare_ids.py"
    )

    wells = db.wellList()
    print(f"Wells found: {len(wells)}")
    logger.info(f"Wells to export: {len(wells)}")

    stats = {
        'total': len(wells),
        'created': 0,
        'updated': 0,
        'errors': 0,
        'wells_skipped_no_id': 0,
        'datasets_skipped_no_id': 0,
        'variables_skipped_no_id': 0,
    }

    try:
        for idx, well_name in enumerate(wells, 1):
            well_start_time = datetime.now()

            print(f"\n{'='*60}")
            print(f"[{idx}/{len(wells)}] Processing well: {well_name}")
            print(f"{'='*60}")

            try:
                logger.info(f"{'='*60}")
                logger.info(f"[{idx}/{len(wells)}] Started: {well_name}")
                logger.info(f"  Start time: {well_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*60}")
                generator = WellLogMLGenerator(techlog_version="2023.1", logger=logger)

                if not generator.create_document(well_name):
                    stats['errors'] += 1
                    stats['wells_skipped_no_id'] += 1
                    logger.error(f"Well '{well_name}' skipped: no valid ID property")
                    continue

                datasets = db.datasetList(well_name)
                print(f"  Datasets: {len(datasets)}")
                logger.info(f"  Datasets found: {len(datasets)}")

                well_total_vars = 0
                well_total_data_points = 0

                for ds_idx, dataset_name in enumerate(datasets, 1):
                    print(f"\n  [{ds_idx}/{len(datasets)}] Dataset: {dataset_name}")
                    logger.info(f"  [{ds_idx}/{len(datasets)}] Processing dataset: {dataset_name}")

                    if not generator.add_dataset(well_name, dataset_name):
                        stats['datasets_skipped_no_id'] += 1
                        continue

                    variables = db.variableList(well_name, dataset_name)

                    try:
                        ref_name = db.referenceName(well_name, dataset_name)
                    except Exception:
                        ref_name = None

                    variables_to_export = [v for v in variables if v != ref_name]

                    print(f"      Variables: {len(variables)} (index: {ref_name})")
                    logger.info(f"      Variables found: {len(variables)} (index curve: {ref_name})")
                    logger.info(f"      Variables to export: {len(variables_to_export)}")

                    for var_idx, variable_name in enumerate(variables_to_export, 1):
                        try:
                            try:
                                var_type = db.variableType(well_name, dataset_name, variable_name)
                            except Exception:
                                var_type = 'Continuous'

                            curve_data = db.variableLoad(well_name, dataset_name, variable_name)

                            if curve_data is not None:
                                if not isinstance(curve_data, np.ndarray):
                                    curve_data = np.array(curve_data)

                                if not generator.add_curve(
                                    well_name=well_name,
                                    dataset_name=dataset_name,
                                    variable_name=variable_name,
                                    data=curve_data,
                                    null_value=-9999
                                ):
                                    stats['variables_skipped_no_id'] += 1
                                    continue

                                data_points = len(curve_data)
                                well_total_data_points += data_points
                                well_total_vars += 1

                                try:
                                    var_unit = db.variableUnit(well_name, dataset_name, variable_name)
                                except Exception:
                                    var_unit = ''

                                msg = f"      [{var_idx}/{len(variables_to_export)}] {variable_name}"
                                if var_unit:
                                    msg += f" [{var_unit}]"
                                if var_type:
                                    msg += f" ({var_type})"
                                msg += f" - {data_points:,} values"

                                print(f"    ✓ {msg}")
                                logger.info(f"        Variable loaded: {msg}")
                            else:
                                msg = f"      [{var_idx}/{len(variables_to_export)}] {variable_name} ({var_type}) - no data"
                                print(f"    ⚠ {msg}")
                                logger.warning(f"        {msg}")
                                logger.warning(f"          Possible cause: db.variableLoad() returned None or empty result")
                        except Exception as e:
                            error_msg = f"      [{var_idx}/{len(variables_to_export)}] Error loading {variable_name} ({var_type if 'var_type' in locals() else '?'}): {e}"
                            print(f"    ✗ {error_msg}")
                            logger.error(f"        {error_msg}")

                logger.info(f"  Stats for well {well_name}:")
                logger.info(f"    - Datasets: {len(datasets)}")
                logger.info(f"    - Variables: {well_total_vars}")
                logger.info(f"    - Data points: {well_total_data_points:,}")

                well_name_clean = str(well_name).strip()
                for ch in r'\/:*?"<>|':
                    well_name_clean = well_name_clean.replace(ch, '_')

                timestamp_str = datetime.now().strftime('%y%m%d_%H%M%S')
                output_filename = os.path.join(folderName, f"{well_name_clean}_{timestamp_str}.json")

                file_exists = os.path.exists(output_filename)

                print(f"\n  Saving: {well_name_clean}_{timestamp_str}.json (well '{well_name}')")
                logger.info(f"\n  Saving results:")
                logger.info(f"    File: {output_filename}")
                logger.info(f"    Exists: {'Yes' if file_exists else 'No'}")

                generator.save(output_filename)

                if file_exists:
                    stats['updated'] += 1
                    logger.info(f"    Result: UPDATED")
                else:
                    stats['created'] += 1
                    logger.info(f"    Result: CREATED")

                well_end_time = datetime.now()
                well_duration = (well_end_time - well_start_time).total_seconds()

                logger.info(f"\n  Finished well: {well_name}")
                logger.info(f"    End time: {well_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"    Duration: {well_duration:.2f} s")
                logger.info(f"{'='*60}\n")

                print(f"\n  ⏱ Duration: {well_duration:.2f} s")

            except Exception as e:
                stats['errors'] += 1
                well_end_time = datetime.now()
                well_duration = (well_end_time - well_start_time).total_seconds()

                error_msg = f"Error processing well {well_name}: {e}"
                print(f"\n✗ {error_msg}")
                logger.error(f"\n✗ {error_msg}")
                logger.error(f"  Duration before error: {well_duration:.2f} s")
                logger.error(f"{'='*60}\n")

                import traceback
                traceback.print_exc()
                logger.error(traceback.format_exc())
    finally:
        export_end_time = datetime.now()
        export_duration = (export_end_time - export_start_time).total_seconds()

        print(f"\n{'='*80}")
        print(f"EXPORT SUMMARY:")
        print(f"{'='*80}")
        print(f"Total wells:                     {stats['total']:>4}")
        print(f"New files created:               {stats['created']:>4}")
        print(f"Files updated:                   {stats['updated']:>4}")
        print(f"Errors:                          {stats['errors']:>4}")
        print(f"Wells skipped (no ID):           {stats['wells_skipped_no_id']:>4}")
        print(f"Datasets skipped (no ID):        {stats['datasets_skipped_no_id']:>4}")
        print(f"Variables skipped (no ID):       {stats['variables_skipped_no_id']:>4}")
        print(f"{'='*80}")
        print(f"Start time:          {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End time:            {export_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total duration:      {export_duration:.2f} s ({export_duration/60:.2f} min)")
        if stats['total'] > 0:
            avg_time = export_duration / stats['total']
            print(f"Avg time per well:   {avg_time:.2f} s")
        print(f"{'='*80}")
        print(f"Log file: {log_filename}")

        logger.info(f"\n{'='*60}")
        logger.info(f"EXPORT COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Summary:")
        logger.info(f"  Total wells: {stats['total']}")
        logger.info(f"  New files created: {stats['created']}")
        logger.info(f"  Files updated: {stats['updated']}")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info(f"  Wells skipped (no ID): {stats['wells_skipped_no_id']}")
        logger.info(f"  Datasets skipped (no ID): {stats['datasets_skipped_no_id']}")
        logger.info(f"  Variables skipped (no ID): {stats['variables_skipped_no_id']}")
        logger.info(f"\nDuration:")
        logger.info(f"  Start: {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  End: {export_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Total: {export_duration:.2f} s ({export_duration/60:.2f} min)")
        if stats['total'] > 0:
            avg_time = export_duration / stats['total']
            logger.info(f"  Avg per well: {avg_time:.2f} s")
        logger.info(f"{'='*60}")

        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


if __name__ == '__main__':
    welllogml_write_from_techlog()
