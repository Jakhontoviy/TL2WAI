# -*- coding: utf-8 -*-
import json
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import logging
import re
import shutil
import numpy as np
import TechlogDatabase as db

# Photo export helpers
_image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.gif')
_MISSING_VALUE = -9999


def _is_image_filename(value):
    """Check if a value looks like an image filename."""
    if not value or value == str(_MISSING_VALUE) or value == _MISSING_VALUE:
        return False
    if not isinstance(value, str):
        return False
    val_lower = value.lower().replace('/', '\\')
    return val_lower.endswith(_image_extensions)


def _find_photo_variables(well, dataset, pattern=""):
    """Find variables that contain image filenames."""
    photo_vars = []
    for var in db.variableList(well, dataset):
        if pattern and pattern.lower() not in var.lower():
            continue
        try:
            values = db.variableLoad(well, dataset, var)
            if values and len(values) > 0:
                for val in values:
                    if _is_image_filename(val):
                        photo_vars.append(var)
                        break
        except Exception:
            continue
    return photo_vars


def _export_dataset_photos_via_xml(well, dataset, photo_vars, base_output_dir, well_name_clean, index_data):
    """
    Extract photos via db.exportFile(XML) and copy them to the output folder.

    Used as fallback when direct file copy cannot locate photos on disk.
    Photos are stored in: base_output_dir/well_name_clean/dataset/photos/<var_name>/
    Returns a dict ready for JSON serialization under dataset['photos'].
    """
    temp_dir = tempfile.mkdtemp(prefix="techlog_photos_")
    try:
        try:
            db.exportFile(temp_dir, [well + '.' + dataset], 'XML')
        except Exception as e:
            print(f"  Warning: XML export failed for {well}.{dataset}: {e}")
            return {}

        xml_images_path = os.path.join(temp_dir, well, dataset)
        if not os.path.exists(xml_images_path):
            print(f"  Warning: XML export did not create folder: {xml_images_path}")
            return {}

        photos_info = {}
        for var in photo_vars:
            try:
                values = db.variableLoad(well, dataset, var)
            except Exception:
                continue
            if not values:
                continue

            photo_dir = os.path.join(base_output_dir, well_name_clean, dataset, "photos", var)
            os.makedirs(photo_dir, exist_ok=True)

            items = []
            copied = 0

            for i, val in enumerate(values):
                if not _is_image_filename(val):
                    continue

                val_norm = str(val).replace('/', '\\')
                basename = os.path.basename(val_norm)
                src = os.path.join(xml_images_path, basename)

                if not os.path.exists(src):
                    continue

                top = None
                bottom = None
                if index_data is not None and i < len(index_data):
                    try:
                        top = float(index_data[i])
                    except Exception:
                        top = None
                if index_data is not None and (i + 1) < len(index_data):
                    try:
                        bottom = float(index_data[i + 1])
                    except Exception:
                        bottom = None

                dst_name = basename
                dst = os.path.join(photo_dir, dst_name)
                if os.path.exists(dst):
                    base_name, ext = os.path.splitext(dst_name)
                    dst_name = f"{base_name}_{var}{ext}"
                    dst = os.path.join(photo_dir, dst_name)

                try:
                    shutil.copy2(src, dst)
                    copied += 1
                    rel_path = os.path.relpath(dst, base_output_dir).replace('\\', '/')
                    items.append({
                        "top": top,
                        "base": bottom,
                        "filename": dst_name,
                        "path": rel_path
                    })
                except Exception as e:
                    print(f"  Warning: failed to copy photo {src}: {e}")

            if copied > 0:
                photos_info[var] = {
                    "count": copied,
                    "folder": os.path.relpath(photo_dir, base_output_dir).replace('\\', '/'),
                    "items": items
                }

        return photos_info
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass


def _export_dataset_photos(well, dataset, photo_vars, base_output_dir, well_name_clean, index_data):
    """
    Copy photos for a dataset to disk and return metadata for JSON.

    Tries direct copy from <project>/Images/<well>/<dataset>/ first.
    Falls back to XML export via db.exportFile() if no photos are found.

    Photos are stored in: base_output_dir/well_name_clean/dataset/photos/<var_name>/
    Returns a dict ready for JSON serialization under dataset['photos'].
    """
    if not photo_vars:
        return {}

    photos_info = {}
    images_path = os.path.join(db.dirProject(), 'Images', well, dataset)

    for var in photo_vars:
        try:
            values = db.variableLoad(well, dataset, var)
        except Exception:
            continue
        if not values:
            continue

        photo_dir = os.path.join(base_output_dir, well_name_clean, dataset, "photos", var)
        os.makedirs(photo_dir, exist_ok=True)

        items = []
        copied = 0

        for i, val in enumerate(values):
            if not _is_image_filename(val):
                continue

            top = None
            bottom = None
            if index_data is not None and i < len(index_data):
                try:
                    top = float(index_data[i])
                except Exception:
                    top = None
            if index_data is not None and (i + 1) < len(index_data):
                try:
                    bottom = float(index_data[i + 1])
                except Exception:
                    bottom = None

            val_norm = str(val).replace('/', '\\')

            if os.path.isabs(val_norm) and os.path.exists(val_norm):
                src = val_norm
            else:
                src = os.path.join(images_path, val_norm)
                if not os.path.exists(src):
                    basename = os.path.basename(val_norm)
                    src = os.path.join(images_path, basename)

            if os.path.exists(src):
                dst_name = os.path.basename(val_norm)
                dst = os.path.join(photo_dir, dst_name)
                if os.path.exists(dst):
                    base_name, ext = os.path.splitext(dst_name)
                    dst_name = f"{base_name}_{var}{ext}"
                    dst = os.path.join(photo_dir, dst_name)

                try:
                    shutil.copy2(src, dst)
                    copied += 1

                    rel_path = os.path.relpath(dst, base_output_dir).replace('\\', '/')

                    items.append({
                        "top": top,
                        "base": bottom,
                        "filename": dst_name,
                        "path": rel_path
                    })
                except Exception as e:
                    print(f"  Warning: failed to copy photo {src}: {e}")
            else:
                print(f"  Warning: photo file not found: {val}")

        if copied > 0:
            photos_info[var] = {
                "count": copied,
                "folder": os.path.relpath(photo_dir, base_output_dir).replace('\\', '/'),
                "items": items
            }

    if not photos_info and photo_vars:
        print(f"      Direct copy found no photos, trying XML export fallback...")
        photos_info = _export_dataset_photos_via_xml(
            well, dataset, photo_vars, base_output_dir, well_name_clean, index_data
        )

    return photos_info

TECHLOG_JSON_ROOT = r'C:\Temp\TL'
TECHLOG_JSON_LOG_DIR = os.path.join(TECHLOG_JSON_ROOT, 'log')


class WellLogMLGenerator:
    """Generates WellLogML JSON files from Techlog data using true streaming."""

    def __init__(self, techlog_version: str = "2023.1", logger: logging.Logger = None):
        self.techlog_version = techlog_version
        self.logger = logger
        self.current_dataset_name = None
        self.current_well_name = None
        self.f = None
        self.filename = None
        self._tmp_path = None
        self._first_dataset = True
        self._first_variable = True

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

        # Fast path for numpy numeric arrays (most common case for curves)
        if isinstance(data, np.ndarray):
            if np.issubdtype(data.dtype, np.number):
                return 'numeric'
            # Fast path for fixed-width string dtypes
            if np.issubdtype(data.dtype, np.character):
                has_numeric = False
                has_string = False
                for val in np.nditer(data, flags=['refs_ok']):
                    v = val.item()
                    if v is None:
                        continue
                    try:
                        float(v)
                        has_numeric = True
                    except (ValueError, TypeError):
                        has_string = True
                    if has_string and has_numeric:
                        return 'mixed'
                return 'numeric' if has_numeric else 'string'
            # Object arrays and other dtypes — scan element-wise
            flat = data.flat
            has_numeric = False
            has_string = False
            for val in flat:
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
                if has_numeric and has_string:
                    return 'mixed'
            if has_string and has_numeric:
                return 'mixed'
            elif has_string:
                return 'string'
            elif has_numeric:
                return 'numeric'
            else:
                return 'unknown'

        # Fallback for Python lists / other iterables
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

    def _write_json_value_inline(self, value):
        """Write a single JSON scalar value to the open file."""
        if value is None:
            self.f.write('null')
        elif isinstance(value, bool):
            self.f.write('true' if value else 'false')
        elif isinstance(value, (int, float, np.integer, np.floating)):
            if isinstance(value, (float, np.floating)):
                if np.isnan(value):
                    self.f.write('null')
                else:
                    self.f.write(json.dumps(float(value)))
            else:
                self.f.write(str(int(value)))
        elif isinstance(value, str):
            self.f.write(json.dumps(value, ensure_ascii=False))
        else:
            self.f.write(json.dumps(value, ensure_ascii=False))

    def _write_dict_inline(self, d, base_indent):
        """Write a dict inline with indentation, streaming directly to file."""
        self.f.write('{\n')
        items = list(d.items())
        next_indent = base_indent + '  '
        for i, (k, v) in enumerate(items):
            comma = ',' if i < len(items) - 1 else ''
            self.f.write(f'{next_indent}{json.dumps(k, ensure_ascii=False)}: ')
            if isinstance(v, dict):
                self._write_dict_inline(v, next_indent)
            elif isinstance(v, list):
                self._write_list_inline(v, next_indent)
            else:
                self._write_json_value_inline(v)
            self.f.write(f'{comma}\n')
        self.f.write(f'{base_indent}}}')

    def _write_list_inline(self, lst, base_indent):
        """Write a list inline with indentation, streaming directly to file."""
        self.f.write('[\n')
        next_indent = base_indent + '  '
        for i, item in enumerate(lst):
            comma = ',' if i < len(lst) - 1 else ''
            self.f.write(f'{next_indent}')
            if isinstance(item, dict):
                self._write_dict_inline(item, next_indent)
            elif isinstance(item, list):
                self._write_list_inline(item, next_indent)
            else:
                self._write_json_value_inline(item)
            self.f.write(f'{comma}\n')
        self.f.write(f'{base_indent}]')

    def _write_numeric_array_compact(self, arr, null_value=None):
        """Write a numeric array in compact [1, 2, 3] format, streaming.

        If null_value is provided, NaN and values equal to null_value are
        replaced with null_value during writing (no full-array copy).
        """
        self.f.write('[')
        n = len(arr)
        if n > 0:
            chunk_size = 4096
            first = True
            for i in range(0, n, chunk_size):
                chunk = arr[i:i+chunk_size]
                parts = []
                for val in chunk:
                    if not first:
                        parts.append(', ')
                    first = False
                    v = float(val)
                    if null_value is not None and (np.isnan(v) or v == null_value):
                        parts.append(json.dumps(float(null_value)))
                    else:
                        parts.append(json.dumps(v))
                self.f.write(''.join(parts))
        self.f.write(']')

    def _write_string_array_compact(self, arr):
        """Write a string array in compact ["a", "b"] format, streaming."""
        self.f.write('[')
        n = len(arr)
        if n > 0:
            chunk_size = 4096
            first = True
            for i in range(0, n, chunk_size):
                chunk = arr[i:i+chunk_size]
                parts = []
                for val in chunk:
                    if not first:
                        parts.append(', ')
                    first = False
                    parts.append(json.dumps(str(val) if val is not None else '', ensure_ascii=False))
                self.f.write(''.join(parts))
        self.f.write(']')

    def create_document(self, well_name: str, filename: str) -> bool:
        """Create the base document structure and open the output file for streaming."""
        try:
            well_name_value = db.wellName(well_name)
        except Exception:
            well_name_value = well_name

        self.current_well_name = well_name_value
        self.filename = filename

        target_dir = os.path.dirname(os.path.abspath(filename))
        fd, self._tmp_path = tempfile.mkstemp(dir=target_dir, suffix='.tmp')
        self.f = os.fdopen(fd, 'w', encoding='utf-8', buffering=65536)

        # Root and DocumentInformation
        self.f.write('{\n')
        self.f.write('  "WellLogML": {\n')
        self.f.write('    "DocumentInformation": {\n')
        self.f.write('      "dtdVersion": {\n')
        self.f.write('        "@extended": "no",\n')
        self.f.write('        "@number": "1.0",\n')
        self.f.write('        "#text": "ContinuFile"\n')
        self.f.write('      },\n')
        self.f.write('      "FileCreationInformation": {\n')
        self.f.write('        "softwareName": {\n')
        self.f.write(f'          "@version": {json.dumps(self.techlog_version, ensure_ascii=False)},\n')
        self.f.write('          "#text": "Techlog"\n')
        self.f.write('        }\n')
        self.f.write('      }\n')
        self.f.write('    },\n')

        # Well start
        self.f.write(f'    {json.dumps(well_name_value, ensure_ascii=False)}: {{\n')

        # wellColor
        try:
            well_color = db.wellColor(well_name)
            if well_color:
                self.f.write(f'      "wellColor": {json.dumps(well_color, ensure_ascii=False)},\n')
        except Exception:
            pass

        # wellGroup
        try:
            well_group = db.wellGroup(well_name)
            if well_group:
                if isinstance(well_group, (list, tuple)):
                    well_group_str = ', '.join(str(g) for g in well_group)
                else:
                    well_group_str = str(well_group)
                self.f.write(f'      "wellGroup": {json.dumps(well_group_str, ensure_ascii=False)},\n')
        except Exception:
            pass

        # wellProperties
        self.f.write('      "wellProperties": ')
        well_props = {}
        try:
            prop_list = db.wellPropertyList(well_name)
            well_props = self._extract_properties(
                prop_list,
                lambda p: db.wellPropertyValue(well_name, p),
                lambda p: db.wellPropertyUnit(well_name, p),
                lambda p: db.wellPropertyDescription(well_name, p)
            )
        except Exception:
            pass
        self._write_dict_inline(well_props, '      ')
        self.f.write(',\n')

        # wellHistory
        self.f.write('      "wellHistory": ')
        well_history = []
        try:
            well_history = self._process_history(db.wellHistory(well_name))
        except Exception:
            pass
        self._write_list_inline(well_history, '      ')
        self.f.write(',\n')

        # datasets start
        self.f.write('      "datasets": {\n')
        self._first_dataset = True
        return True

    def add_dataset(self, well_name: str, dataset_name: str) -> bool:
        """
        Add dataset information to the document, streaming directly to file.

        Returns:
            True if the dataset was added successfully.
        """
        if self.f is None:
            raise ValueError("Call create_document() before add_dataset()")

        try:
            dataset_name_value = db.datasetName(well_name, dataset_name)
        except Exception:
            dataset_name_value = dataset_name

        self.current_dataset_name = dataset_name_value

        if not self._first_dataset:
            self.f.write(',\n')
        self._first_dataset = False

        self.f.write(f'        {json.dumps(dataset_name_value, ensure_ascii=False)}: {{\n')

        # datasetType
        try:
            dataset_type = db.datasetType(well_name, dataset_name)
            if dataset_type:
                self.f.write(f'          "datasetType": {json.dumps(str(dataset_type), ensure_ascii=False)},\n')
        except Exception:
            pass

        # datasetGroup
        try:
            dataset_group = db.datasetGroup(well_name, dataset_name)
            if dataset_group:
                if isinstance(dataset_group, (list, tuple)):
                    dataset_group_str = ', '.join(str(g) for g in dataset_group)
                else:
                    dataset_group_str = str(dataset_group)
                self.f.write(f'          "datasetGroup": {json.dumps(dataset_group_str, ensure_ascii=False)},\n')
        except Exception:
            pass

        # MeasurementDetails + index curve
        try:
            dataset_size = db.datasetSize(well_name, dataset_name)
            ref_name = db.referenceName(well_name, dataset_name)

            self.f.write('          "MeasurementDetails": {\n')
            self.f.write('            "startIndex": 0,\n')
            end_idx = dataset_size - 1 if dataset_size > 0 else 0
            self.f.write(f'            "endIndex": {end_idx},\n')

            try:
                ref_unit = db.variableUnit(well_name, dataset_name, ref_name)
                sampling_rate = db.datasetSamplingRate(well_name, dataset_name, True, ref_unit)
                step = float(sampling_rate) if sampling_rate else 0.1
                self.f.write('            "evenSampling": {\n')
                self.f.write(f'              "@index_curve": {json.dumps(ref_name, ensure_ascii=False)},\n')
                self.f.write(f'              "stepIncrement": {json.dumps(step)}\n')
                self.f.write('            }\n')
            except Exception:
                self.f.write('            "evenSampling": {\n')
                self.f.write(f'              "@index_curve": {json.dumps(ref_name, ensure_ascii=False)},\n')
                self.f.write('              "stepIncrement": 0.1\n')
                self.f.write('            }\n')
            self.f.write('          },\n')

            # index curve
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

                    self.f.write('          "index": {\n')
                    self.f.write(f'            "name": {json.dumps(ref_name, ensure_ascii=False)},\n')
                    self.f.write(f'            "variableUnit": {json.dumps(index_unit, ensure_ascii=False)},\n')
                    self.f.write(f'            "variableDescription": {json.dumps(index_desc, ensure_ascii=False)},\n')
                    self.f.write(f'            "variableType": {json.dumps(index_type, ensure_ascii=False)},\n')
                    self.f.write(f'            "variableFamily": {json.dumps(index_family, ensure_ascii=False)},\n')
                    self.f.write('            "variableData": ')

                    try:
                        index_values = np.asarray(index_data, dtype=float)
                        self._write_numeric_array_compact(index_values)
                    except (ValueError, TypeError):
                        self._write_string_array_compact(index_data)

                    self.f.write('\n')
                    self.f.write('          },\n')

                    self._log(f"      Index curve ready: {ref_name} ({len(index_data):,} values)")
            except Exception as e:
                self._log(f"      Could not load index curve {ref_name}: {e}", 'warning')

        except Exception:
            self.f.write('          "MeasurementDetails": {\n')
            self.f.write('            "startIndex": 0,\n')
            self.f.write('            "endIndex": 0,\n')
            self.f.write('            "evenSampling": {\n')
            self.f.write('              "@index_curve": "MD",\n')
            self.f.write('              "stepIncrement": 0.1\n')
            self.f.write('            }\n')
            self.f.write('          },\n')

        # datasetProperties
        self.f.write('          "datasetProperties": ')
        ds_props = {}
        try:
            prop_list = db.datasetPropertyList(well_name, dataset_name)
            if prop_list:
                ds_props = self._extract_properties(
                    prop_list,
                    lambda p: db.datasetPropertyValue(well_name, dataset_name, p),
                    lambda p: db.datasetPropertyUnit(well_name, dataset_name, p),
                    lambda p: db.datasetPropertyDescription(well_name, dataset_name, p)
                )
        except Exception:
            pass
        self._write_dict_inline(ds_props, '          ')
        self.f.write(',\n')

        # datasetHistory
        self.f.write('          "datasetHistory": ')
        ds_history = []
        try:
            ds_history = self._process_history(db.datasetHistory(well_name, dataset_name))
        except Exception:
            pass
        self._write_list_inline(ds_history, '          ')
        self.f.write(',\n')

        # variables start
        self.f.write('          "variables": {\n')
        self._first_variable = True

        return True

    def finalize_dataset(self):
        """Close the current dataset's variables block and the dataset object."""
        if self.f is None:
            return
        self.f.write('\n          }')   # close variables
        self.f.write('\n        }')     # close dataset

    def write_photos(self, photos_dict: Dict[str, Any]):
        """Write a photos block to the current dataset (after variables, before close)."""
        if not photos_dict or self.f is None:
            return
        self.f.write(',\n')
        self.f.write('          "photos": ')
        self._write_dict_inline(photos_dict, '          ')

    def add_curve(self, well_name: str, dataset_name: str, variable_name: str,
                  data: Optional[np.ndarray] = None, null_value: float = -9999) -> bool:
        """
        Add a variable to the current dataset, streaming directly to file.

        Returns:
            True (always, for compatibility).
        """
        if self.f is None or self.current_dataset_name is None:
            raise ValueError("Call add_dataset() before add_curve()")

        if not self._first_variable:
            self.f.write(',\n')
        self._first_variable = False

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

        self.f.write(f'            {json.dumps(var_name, ensure_ascii=False)}: {{\n')
        self.f.write(f'              "nullValue": {json.dumps(null_value)},\n')
        self.f.write(f'              "variableType": {json.dumps(var_type, ensure_ascii=False)},\n')
        self.f.write(f'              "variableUnit": {json.dumps(unit, ensure_ascii=False)},\n')
        self.f.write(f'              "variableDescription": {json.dumps(description, ensure_ascii=False)},\n')
        self.f.write(f'              "variableGroup": {json.dumps(group_str, ensure_ascii=False)},\n')
        self.f.write(f'              "variableFamily": {json.dumps(family, ensure_ascii=False)},\n')

        # variableHistory
        self.f.write('              "variableHistory": ')
        try:
            var_history = db.variableHistory(well_name, dataset_name, variable_name)
            history = self._process_history(var_history)
            if not history:
                history = [{"dateTime": str(self._get_timestamp()), "userName": username, "action": "Created"}]
        except Exception:
            history = [{"dateTime": str(self._get_timestamp()), "userName": username, "action": "Created"}]
        self._write_list_inline(history, '              ')
        self.f.write(',\n')

        # variableProperties
        self.f.write('              "variableProperties": ')
        var_props = {}
        try:
            prop_list = db.variablePropertyList(well_name, dataset_name, variable_name)
            if prop_list:
                var_props = self._extract_properties(
                    prop_list,
                    lambda p: db.variablePropertyValue(well_name, dataset_name, variable_name, p),
                    lambda p: db.variablePropertyUnit(well_name, dataset_name, variable_name, p),
                    lambda p: db.variablePropertyDescription(well_name, dataset_name, variable_name, p)
                )
        except Exception:
            pass
        self._write_dict_inline(var_props, '              ')
        self.f.write(',\n')

        # variableData
        self.f.write('              "variableData": ')
        if data is not None and len(data) > 0:
            if data_type in ('numeric', 'mixed'):
                try:
                    data_array = np.asarray(data, dtype=float)
                    self._write_numeric_array_compact(data_array, null_value=null_value)
                except (ValueError, TypeError):
                    self._write_string_array_compact(data)
            else:
                self._write_string_array_compact(data)
        else:
            self.f.write('[]')

        self.f.write('\n')
        self.f.write('            }')

        return True

    def save(self) -> bool:
        """Finalize and close the streaming JSON file."""
        if self.f is None:
            raise ValueError("Call create_document() before save()")

        try:
            self.f.write('\n      }\n')   # close datasets
            self.f.write('    }\n')       # close well
            self.f.write('  }\n')         # close WellLogML
            self.f.write('}\n')           # close root
            self.f.close()
            os.replace(self._tmp_path, self.filename)
        except Exception:
            self._cleanup()
            raise

        self.f = None
        file_size = os.path.getsize(self.filename)
        msg = f"File saved: {self.filename} (size: {file_size:,} bytes)"
        self._log(msg)
        print(f"  ✓ {msg}")
        return True

    def _cleanup(self):
        """Close file handle and remove temp file on error."""
        if self.f:
            try:
                self.f.close()
            except Exception:
                pass
            self.f = None
        if self._tmp_path and os.path.exists(self._tmp_path):
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass


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

                well_name_clean = str(well_name).strip()
                for ch in r'\/*?"<>|':
                    well_name_clean = well_name_clean.replace(ch, '_')

                timestamp_str = datetime.now().strftime('%y%m%d_%H%M%S')
                output_filename = os.path.join(folderName, f"{well_name_clean}_{timestamp_str}.json")

                generator = WellLogMLGenerator(techlog_version="2023.1", logger=logger)

                if not generator.create_document(well_name, output_filename):
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

                    # Load index data for photo depth association
                    index_data = None
                    if ref_name:
                        try:
                            index_data = db.variableLoad(well_name, dataset_name, ref_name)
                            if index_data is not None and not isinstance(index_data, np.ndarray):
                                index_data = np.array(index_data)
                        except Exception:
                            index_data = None

                    # Detect photo variables
                    photo_vars = _find_photo_variables(well_name, dataset_name)
                    if photo_vars:
                        print(f"      Photo variables detected: {', '.join(photo_vars)}")
                        logger.info(f"      Photo variables detected: {', '.join(photo_vars)}")

                    variables_to_export = [v for v in variables if v != ref_name and v not in photo_vars]

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
                                del curve_data

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

                    # Export photos
                    if photo_vars:
                        photos_info = _export_dataset_photos(
                            well_name, dataset_name, photo_vars,
                            folderName, well_name_clean, index_data
                        )
                        if photos_info:
                            generator.write_photos(photos_info)
                            total_photos = sum(p['count'] for p in photos_info.values())
                            print(f"      Photos exported: {total_photos}")
                            logger.info(f"      Photos exported: {total_photos}")
                        else:
                            print(f"      Photos: none found on disk")
                            logger.info(f"      Photos: none found on disk")

                    if index_data is not None:
                        del index_data

                    generator.finalize_dataset()

                logger.info(f"  Stats for well {well_name}:")
                logger.info(f"    - Datasets: {len(datasets)}")
                logger.info(f"    - Variables: {well_total_vars}")
                logger.info(f"    - Data points: {well_total_data_points:,}")

                file_exists = os.path.exists(output_filename)

                print(f"\n  Saving: {well_name_clean}_{timestamp_str}.json (well '{well_name}')")
                logger.info(f"\n  Saving results:")
                logger.info(f"    File: {output_filename}")
                logger.info(f"    Exists: {'Yes' if file_exists else 'No'}")

                generator.save()

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

                try:
                    if 'generator' in locals():
                        generator._cleanup()
                except Exception:
                    pass
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
