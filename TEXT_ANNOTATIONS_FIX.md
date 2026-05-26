# Text/Annotation Data Export Enhancement

## Problem
Text/annotation variables like `ZONE_NAME` with value `'ZoneB'` were being exported with empty `variableData: []` arrays because `db.variableLoad()` doesn't work with Annotation and RichText type variables.

## Root Cause
The Techlog API's `db.variableLoad()` function is designed to load numeric curve data only. For Annotation and RichText type variables, the data is stored differently - typically as properties rather than as numeric arrays.

## Solution

### Changes Made

**Both scripts enhanced:**
- `WellLogML_Techlog_py3.py` (lines ~1000-1025)
- `WellLogML_Techlog_export_v2.py` (lines ~1030-1055)

### How It Works

1. **Check variable type first:**
   ```python
   var_type = db.variableType(well_name, dataset_name, variable_name)
   ```

2. **After normal variableLoad() attempt:**
   - If data is None or empty AND variable type is Annotation/RichText/TopBottomCurve
   - Try to load from variable properties using `db.variablePropertyValue()`

3. **Property name attempts:**
   The code tries multiple property names in order:
   - `Value` / `value`
   - `Text` / `text`
   - `Data` / `data`

4. **Enhanced logging:**
   - Debug logs show available properties for each annotation
   - Shows which property was used to load the value
   - Shows any errors encountered

## Usage

Re-run the export from Techlog with the updated scripts:

```python
# The scripts will now:
# 1. Load numeric curves normally with db.variableLoad()
# 2. For Annotation/RichText types, attempt to load from properties
# 3. Export both with proper variableData content
```

## Example Output

```
Аннотация ZONE_NAME: доступные свойства: ['Value', 'ID', 'Description']
Аннотация ZONE_NAME: загружено значение из свойства 'Value': ZoneB
✓ ZONE_NAME (Annotation) - 1 значений
```

## Testing

After applying the fix:

1. **In Techlog:** Run one of the export scripts
2. **Check the JSON:** 
   ```json
   "ZONE_NAME": {
     "variableType": "Annotation",
     "variableData": ["ZoneB"]  // ← Should have data now!
   }
   ```
3. **Re-import to Gamma DB:** The curves should now load properly

## Debugging

If text data still doesn't load:

1. Check the log output for the property names Techlog uses
2. The debug logs will show: `Аннотация ZONE_NAME: доступные свойства: [...]`
3. If needed, add more property names to the list in the code

## Notes

- This is a non-breaking change - numeric curves continue to work as before
- Backward compatible - handles both empty and populated annotations
- If annotation property isn't found, the variable is still added with empty `variableData: []` (proper fallback)
