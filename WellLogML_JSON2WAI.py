"""
Import WellLogML JSON files into WAI DB

Loads data exported by WellLogML_Techlog2JSON.py from JSON files
into WAI DB. Each JSON file represents one well with its datasets and curves.

Algorithm:
1. Scans SOURCE_DIR for *.json files
2. For each file:
   - Parses JSON and extracts the well name
   - Creates the well in the target project (if absent)
   - For each dataset:
     - Skips datasets listed in SKIP_DATASETS
     - Extracts the index curve (depth)
     - For each variable:
       - Replaces null values (-9999) with NaN
       - Creates a log with correct parameters
       - Saves to DB
3. Prints processing statistics

Input:
- JSON files from WellLogML_Techlog2JSON.py (format: <WellID>.json)
- Structure: WellLogML -> <WellName> -> datasets -> <DatasetName> -> variables

Output:
- Wells and logs in the WAI DB project
- Processing statistics in the console

Configuration parameters:
- PROJECT_NAME: WAI DB project name
- SOURCE_DIR: folder with JSON files (C:\\Temp\\TL)
- SKIP_DATASETS: datasets to skip (e.g. ['Survey', 'MICP'])
- NULL_VALUE: value treated as null in the data (-9999.0)

Notes:
- Depth (index) is loaded in original units (ft, m, etc.)
- Log groups correspond to dataset names from Techlog
- Datasets without an index curve are skipped
- Multi-column logs (images, spectra, etc.) are automatically reshaped from 1D to 2D
  if the data length is a multiple of the index length
- Malformed JSON with leading zeros in numbers is automatically fixed before parsing
- Optional depth conversion to metres (CONVERT_DEPTH_TO_METERS parameter)
  supports: ft, m, km, in and other units
"""

import sys
import os

# Ensure UTF-8 encoding for console output
if sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from client.server.remote_server import RemoteServer
import numpy as np
import json
import glob


# ========================
# CONFIGURATION
# ========================

# WAI DB project name to import into
PROJECT_NAME = 'Techlog_project'

# Folder containing JSON files to import
SOURCE_DIR = r'C:\Temp\TL'

# Datasets to skip (e.g. 'Survey', 'MICP')
# Use to exclude datasets that contain no useful log data
SKIP_DATASETS = ['Survey']

# Value treated as null/missing in Techlog data
NULL_VALUE = -9999.0

# Convert depths to metres on import
# Depth unit is read from each dataset's index.variableUnit field
CONVERT_DEPTH_TO_METERS = False

# Use the family from the JSON file or determine it automatically
# True  = load variableFamily from the JSON file as-is
# False = ignore variableFamily from JSON and auto-detect via prj.family_assigner
USE_FAMILY = False

# Retry connection on failure
RETRY_CONNECTION = True


# ========================
# MAIN CODE
# ========================

def replace_null_values(data, null_value=NULL_VALUE):
    """
    Replace null values in an array with np.nan.

    Handles both string ("-9999") and numeric (-9999) null values.

    Parameters:
    - data: numpy array or list (1D or 2D)
    - null_value: value to treat as null (default -9999.0)

    Returns:
    - numpy array with null values replaced by np.nan
    """
    if not isinstance(data, np.ndarray):
        data = np.array(data)

    # Try direct float conversion first
    try:
        data_float = data.astype(float, copy=True)

        # Replace values close to null_value with np.nan using isclose
        # Works for -9999, -9999.0, -9999e0, etc.
        mask = np.isclose(data_float, null_value, rtol=1e-5, atol=1e-8)
        data_float[mask] = np.nan

        return data_float

    except (ValueError, TypeError):
        # Direct conversion failed — fall through to string handling
        pass

    # Handle string data: replace null strings with 'nan' before converting
    try:
        null_str = str(null_value)  # e.g. "-9999.0"

        data_obj = data.astype(object, copy=True)
        original_shape = data_obj.shape

        def is_null_value(val):
            try:
                return np.isclose(float(val), float(null_value), rtol=1e-5, atol=1e-8)
            except (ValueError, TypeError):
                return str(val).strip() == null_str.strip()

        flat_data = data_obj.ravel()
        null_mask = np.zeros(len(flat_data), dtype=bool)

        # Fast path: try as float
        try:
            null_mask = np.isclose(flat_data.astype(float), float(null_value), rtol=1e-5, atol=1e-8)
        except (ValueError, TypeError):
            # Slow path: check element by element
            for i in range(len(flat_data)):
                if is_null_value(flat_data[i]):
                    null_mask[i] = True

        flat_data[null_mask] = np.nan

        data_obj = flat_data.reshape(original_shape)
        return data_obj.astype(float)

    except Exception as e:
        # Nothing worked — return data unchanged
        return data


def load_json_file(filepath):
    """
    Safely load a JSON file with error handling.

    Attempts to fix malformed JSON containing leading-zero integers (e.g. 03, 04).

    Parameters:
    - filepath: path to the JSON file

    Returns:
    - dict (parsed JSON) or None on error
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try parsing as-is
        try:
            return json.loads(content)
        except json.JSONDecodeError as json_err:
            # If leading-zero numbers are the problem, attempt to fix them
            if 'leading zeros' in str(json_err) or 'Expecting' in str(json_err):
                print(f'  ℹ Attempting to fix malformed JSON with leading zeros...')
                fixed_content = content
                import re
                # Fix ", 0N" → ", N" inside arrays
                fixed_content = re.sub(r',\s+0(\d)', r', \1', fixed_content)
                # Fix "[0N" → "[N" for the first element
                fixed_content = re.sub(r'\[\s*0(\d)', r'[\1', fixed_content)
                return json.loads(fixed_content)
            else:
                raise
    except Exception as e:
        print(f'✗ Error reading file {filepath}: {e}')
        return None


def convert_depth_to_meters(depth_array, from_unit):
    """
    Convert depth values from various units to metres.

    Parameters:
    - depth_array: numpy array of depth values
    - from_unit: source unit ('ft', 'm', 'km', etc.)

    Returns:
    - tuple: (converted_array, result_unit, factor_used)
      where result_unit is always 'm'
    """
    from_unit_lower = str(from_unit).lower().strip()

    conversion_factors = {
        'ft': 0.3048,
        'feet': 0.3048,
        'feetбез': 0.3048,
        'm': 1.0,
        'meter': 1.0,
        'meters': 1.0,
        'km': 1000.0,
        'kilometer': 1000.0,
        'kilometers': 1000.0,
        'in': 0.0254,
        'inch': 0.0254,
        'inches': 0.0254,
    }

    if from_unit_lower in conversion_factors:
        factor = conversion_factors[from_unit_lower]
        converted = depth_array * factor
        return converted, 'm', factor
    else:
        print(f'    ⚠ Unknown depth unit: {from_unit} — conversion skipped')
        return depth_array, from_unit, 1.0


def extract_well_name(welllogml_dict):
    """
    Extract the well name from a WellLogML dictionary.

    The WellLogML structure contains a 'DocumentInformation' key and one well key.

    Parameters:
    - welllogml_dict: contents of the WellLogML field from JSON

    Returns:
    - str: well name, or None if not found
    """
    for key in welllogml_dict:
        if key != 'DocumentInformation':
            return key
    return None


def apply_properties(obj, properties_dict):
    """
    Apply properties from JSON to a WAI DB object (well, log, etc.) via update_meta().

    Parameters:
    - obj: WAI DB object (well, log, etc.) with an update_meta() method
    - properties_dict: property dictionary from JSON in the form:
      {"propName": {"value": "...", "unit": "...", "description": "..."}}

    Returns:
    - number of properties applied
    """
    if not properties_dict or not isinstance(properties_dict, dict):
        return 0

    meta_patch = {}
    for prop_name, prop_data in properties_dict.items():
        try:
            # Extract value from Techlog format: {"value": "...", "unit": "...", "description": "..."}
            if isinstance(prop_data, dict) and 'value' in prop_data:
                prop_value = prop_data.get('value')
                prop_unit = prop_data.get('unit', '')

                # If unit is present, store as {value, unit}; otherwise store value directly
                if prop_unit:
                    meta_patch[prop_name] = {'value': prop_value, 'unit': prop_unit}
                else:
                    meta_patch[prop_name] = prop_value
            elif isinstance(prop_data, dict):
                # Other dict format — store as-is
                meta_patch[prop_name] = prop_data
            else:
                # Plain value
                meta_patch[prop_name] = prop_data
        except Exception:
            pass

    if meta_patch:
        try:
            if hasattr(obj, 'update_meta'):
                obj.update_meta(meta_patch)
                return len(meta_patch)
        except Exception:
            pass

    return 0


def import_well_from_json(prj, filepath):
    """
    Import one well from a JSON file.

    Parameters:
    - prj: WAI DB Project object
    - filepath: path to the JSON file

    Returns:
    - dict: import statistics for this file
      { 'well': name, 'file': filename, 'datasets_ok': count, 'curves_ok': count,
        'curves_skipped': count, 'errors': count, 'error_list': list }
    """
    stats = {
        'well': None,
        'file': os.path.basename(filepath),
        'datasets_ok': 0,
        'curves_ok': 0,
        'curves_skipped': 0,
        'errors': 0,
        'error_list': []
    }

    data = load_json_file(filepath)
    if data is None:
        return stats

    welllogml = data.get('WellLogML')
    if not welllogml:
        stats['error_list'].append('WellLogML block not found')
        return stats

    well_name = extract_well_name(welllogml)
    if not well_name:
        stats['error_list'].append('Well name not found')
        return stats

    stats['well'] = well_name
    well_data = welllogml[well_name]

    print(f'\n  Processing well: {well_name}')

    try:
        well = prj.wells.get_by_name(well_name, create_if_absent=True)
        well.save()

        well_properties = well_data.get('wellProperties', {})
        if well_properties:
            props_count = apply_properties(well, well_properties)
            if props_count > 0:
                well.save()
                print(f'    ℹ Well properties loaded: {props_count}')

        print(f'    ✓ Well retrieved/created')
    except Exception as e:
        stats['error_list'].append(f'Error creating well: {e}')
        stats['errors'] += 1
        return stats

    datasets = well_data.get('datasets', {})
    for dataset_name, dataset in datasets.items():

        if dataset_name in SKIP_DATASETS:
            print(f'    ⊘ Dataset skipped: {dataset_name}')
            stats['curves_skipped'] += 1
            continue

        print(f'    Dataset: {dataset_name}')

        index = dataset.get('index')
        if not index:
            print(f'      ✗ No index curve (depth)')
            stats['error_list'].append(f'{dataset_name}: no index curve')
            stats['errors'] += 1
            continue

        index_name = index.get('name', 'MD')
        index_unit = index.get('variableUnit', 'm')
        index_data = np.array(index.get('variableData', []))

        if len(index_data) == 0:
            print(f'      ✗ Index curve is empty')
            stats['error_list'].append(f'{dataset_name}: index curve is empty')
            stats['errors'] += 1
            continue

        reference_unit = index_unit
        if CONVERT_DEPTH_TO_METERS and index_unit.lower() != 'm':
            index_data, reference_unit, factor = convert_depth_to_meters(index_data, index_unit)
            print(f'      Index: {index_name} ({len(index_data)} points, unit: {index_unit} → {reference_unit}, factor: {factor})')
        else:
            print(f'      Index: {index_name} ({len(index_data)} points, unit: {index_unit})')

        variables = dataset.get('variables', {})
        for var_name, var_data in variables.items():

            try:
                var_data_raw = var_data.get('variableData', [])
                var_unit = var_data.get('variableUnit', 'unitless')
                var_family = var_data.get('variableFamily', '')
                var_type = var_data.get('variableType', 'Continu')
                null_value = var_data.get('nullValue', NULL_VALUE)

                # Guard: np.array('string') would split the string into individual characters
                if isinstance(var_data_raw, (str, int, float, bool)):
                    var_data_raw = [var_data_raw]

                var_values = np.array(var_data_raw)

                # Detect accidental char-array from a single string value
                if var_values.dtype.kind == 'U' and len(var_values) > 1:
                    if all(len(str(v)) == 1 for v in var_values):
                        print(f'        ⚠ {var_name} ({var_type}): possible string-to-char-array conversion (skipped)')
                        stats['curves_skipped'] += 1
                        continue

                if len(var_values) == 0:
                    # Likely an annotation (Zone Name, Marker Name) or empty field
                    print(f'        ⊘ {var_name} ({var_type}): no data (skipped)')
                    stats['curves_skipped'] += 1
                    continue

                # Length must match the index, or be an exact multiple (multi-column log)
                if len(var_values) != len(index_data):
                    if len(var_values) > 0 and len(var_values) % len(index_data) == 0:
                        num_columns = len(var_values) // len(index_data)
                        if num_columns > 1:
                            print(f'        ℹ {var_name}: multi-column data — reshaping {len(var_values)} → ({len(index_data)}\xd7{num_columns})')
                            try:
                                # Data is column-major: [col1_all, col2_all, col3_all]
                                # Reshape to (num_columns, num_points) then transpose to (num_points, num_columns)
                                reshaped = var_values.reshape((num_columns, len(index_data))).T
                                print(f'          After reshape: shape {reshaped.shape}, dtype {reshaped.dtype}')
                                var_values = reshaped
                            except Exception as e:
                                print(f'        ✗ {var_name}: reshape error: {e}')
                                stats['curves_skipped'] += 1
                                continue
                        else:
                            print(f'        - {var_name}: data length {len(var_values)} does not match index {len(index_data)} (skipped)')
                            stats['curves_skipped'] += 1
                            continue
                    else:
                        print(f'        - {var_name}: data length {len(var_values)} does not match index {len(index_data)}, not a multiple (skipped)')
                        stats['curves_skipped'] += 1
                        continue

                var_values = replace_null_values(var_values, null_value)

                if var_values.ndim == 2:
                    print(f'          After replace_null_values: shape {var_values.shape}, NaN count {np.sum(np.isnan(var_values))}')

                original_family = var_family

                if not USE_FAMILY or not var_family:
                    try:
                        mnemonic_info = prj.family_assigner.assign_family(var_name, var_unit)
                        var_family = mnemonic_info.family
                        if not USE_FAMILY:
                            print(f'        ℹ {var_name}: family auto-detected = {var_family}')
                    except Exception:
                        var_family = original_family
                        if not USE_FAMILY and not var_family:
                            print(f'        ⚠ {var_name}: could not determine family, left empty')

                log = well.logs.create(
                    name=var_name,
                    group=[dataset_name],        # group = dataset name
                    values_family=var_family,
                    values_unit=var_unit,
                    reference_unit=index_unit    # depth unit from the index curve
                )

                var_properties = var_data.get('variableProperties', {})
                if var_properties:
                    props_count = apply_properties(log, var_properties)
                    if props_count > 0:
                        print(f'        ℹ Log properties loaded: {props_count}')

                if var_values.ndim == 2:
                    num_nan = np.sum(np.isnan(var_values))
                    print(f'          Before set_rvalues: index {index_data.shape}, values {var_values.shape}, NaN={num_nan}')
                    if var_values.shape[0] != len(index_data):
                        print(f'          ✗ ERROR: shape mismatch! index={len(index_data)}, values[0]={var_values.shape[0]}')
                        stats['curves_skipped'] += 1
                        continue

                log.set_rvalues(index_data, var_values)
                log.save()

                if var_values.ndim == 2:
                    print(f'        ✓ {var_name} ({var_family}, {var_unit}) {var_values.shape[0]} points \xd7 {var_values.shape[1]} columns')
                else:
                    print(f'        ✓ {var_name} ({var_family}, {var_unit}, {len(var_values)} points)')
                stats['curves_ok'] += 1

            except Exception as e:
                err_msg = f'{var_name}: {e}'
                print(f'        ✗ {err_msg}')
                stats['error_list'].append(err_msg)
                stats['errors'] += 1
                continue

        stats['datasets_ok'] += 1

    return stats


def main():
    """Main import function."""
    print('=' * 70)
    print('WellLogML JSON → WAI DB Importer')
    print('=' * 70)

    print(f'\nConnecting to server...')
    try:
        gc = RemoteServer(user='alex', password='pass')
        print(f'✓ Connected')
    except Exception as e:
        print(f'✗ Connection error: {e}')
        return

    print(f'\nOpening project: {PROJECT_NAME}')
    try:
        prj = gc.projects.get_by_name(PROJECT_NAME)
        if not prj:
            print(f'✗ Project {PROJECT_NAME} not found')
            return
        print(f'✓ Project found')
    except Exception as e:
        print(f'✗ Error opening project: {e}')
        return

    print(f'\nScanning directory: {SOURCE_DIR}')
    json_files = sorted(glob.glob(os.path.join(SOURCE_DIR, '*.json')))
    print(f'JSON files found: {len(json_files)}')

    if not json_files:
        print('No files found')
        return

    print('\n' + '=' * 70)
    print('IMPORT')
    print('=' * 70)

    all_stats = []
    for i, filepath in enumerate(json_files, 1):
        print(f'\n[{i}/{len(json_files)}] {os.path.basename(filepath)}')
        stats = import_well_from_json(prj, filepath)
        all_stats.append(stats)

    print('\n' + '=' * 70)
    print('SUMMARY')
    print('=' * 70)

    total_files = len(json_files)
    total_wells = len([s for s in all_stats if s['well']])
    total_datasets = sum(s['datasets_ok'] for s in all_stats)
    total_curves = sum(s['curves_ok'] for s in all_stats)
    total_skipped = sum(s['curves_skipped'] for s in all_stats)
    total_errors = sum(s['errors'] for s in all_stats)

    print(f'\nFiles processed:         {total_files}')
    print(f'Wells created:           {total_wells}')
    print(f'Datasets processed:      {total_datasets}')
    print(f'Curves loaded:           {total_curves}')
    print(f'Curves skipped:          {total_skipped}')
    print(f'Errors:                  {total_errors}')

    error_wells = [s for s in all_stats if s['error_list']]
    if error_wells:
        print('\nWells with errors:')
        for stats in error_wells:
            print(f'  {stats["file"]} ({stats["well"]}):')
            for error in stats['error_list']:
                print(f'    - {error}')

    print('\n✓ Import complete')


if __name__ == '__main__':
    main()
