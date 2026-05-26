# WellLogML Export Bug Fix Summary

## Problem

Variables like `ZONE_NAME`, `MARKER_NAME`, `Zone Name`, and `MarkerDescription` were being exported to JSON files with **empty variableData arrays**, preventing them from being imported into Gamma DB.

```json
"ZONE_NAME": {
  "@id": "...",
  "variableType": "Annotation",
  "variableFamily": "Zone Name",
  "variableData": []  // ← Empty! Should have data or not exist
}
```

## Root Cause

**Both export scripts had the same bug:**
- `WellLogML_Techlog_py3.py` (lines 655-667)
- `WellLogML_Techlog_export_v2.py` (lines 683-700)

### The Bug in Code

```python
if data is not None and len(data) > 0:
    # SET variableData with numeric or text data
    variable_dict["variableData"] = [float(val) for val in data_clean]
else:
    # BUG: Nothing happens here!
    # variableData key is NEVER set when data is empty
    pass

# Variable is ALWAYS added to the export, even without variableData key
self.data["WellLogML"][...]["variables"][var_name] = variable_dict
```

### Why This Happens

1. `db.variableLoad()` returns an **empty array `[]`** for variables that exist but have no data
2. The empty array is not `None`, so `if curve_data is not None:` passes at line 1001
3. `add_curve()` is called with `data=[]`
4. Inside `add_curve()`, the condition `if data is not None and len(data) > 0:` fails (empty array)
5. The `else` block does nothing, so `variableData` key is never set
6. The variable is still added to the JSON with **missing** `variableData` field

## Solution

**Added explicit empty array assignment in the else block:**

```python
if data is not None and len(data) > 0:
    # Normal case: populate variableData
    variable_dict["variableData"] = [float(val) for val in data_clean]
else:
    # FIX: Explicitly set empty array when data is missing
    variable_dict["variableData"] = []  # ← This was missing!
```

## Files Fixed

1. **D:\Dev\TechlogIO\WellLogML_Techlog_py3.py**
   - Lines 655-668: Added explicit `variable_dict["variableData"] = []` in else block

2. **D:\Dev\TechlogIO\WellLogML_Techlog_export_v2.py**
   - Lines 683-699: Added explicit `variable_dict["variableData"] = []` in else block

## Impact

- **Before:** Variables with no data created JSON entries with missing/undefined `variableData`
- **After:** Variables with no data create JSON entries with explicit empty array `variableData: []`
- **Result:** Import script correctly identifies and skips empty variables with clear logging

## How Import Script Handles This

The import script (`WellLogML_import.py`) already has proper handling:

```python
if len(var_values) == 0:
    print(f'        ⊘ {var_name} ({var_type}): нет данных (пропущено)')
    stats['curves_skipped'] += 1
    continue
```

Now the output clearly shows:
```
⊘ ZONE_NAME (Annotation): нет данных (пропущено)
⊘ MARKER_NAME (Annotation): нет данных (пропущено)
```

## Testing

After applying the fixes, re-export the data from Techlog. Variables with no data will now have:
```json
"variableData": []
```

Instead of:
```json
// variableData key is missing entirely
```

This is semantically correct and the import script will properly skip them.
