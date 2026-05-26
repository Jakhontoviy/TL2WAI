# Debugging Text Data Export Issues

## Problem
Text/annotation variables like `ZONE_NAME` are still not being exported with their actual values.

## Solution
I've added **comprehensive logging** to both export scripts to diagnose exactly what's happening with text data.

## What Changed

Both scripts now have enhanced debugging that:

1. **Logs what `db.variableLoad()` returns** for each variable
   - Numeric curves → logs "variableLoad()"
   - Empty arrays → logs "доступные свойства: [...property list...]"
   - Errors → logs the exception

2. **Logs all available properties** for annotation/text variables
   - Shows exact property names Techlog is storing
   - Example: `доступные свойства: ['Value', 'ID', 'Description']`

3. **Logs each property value** as it's checked
   - Shows what value is in each property
   - Logs successes with "загружено из свойства"

4. **Tries multiple approaches** in order:
   - Direct variableLoad()
   - Load from all available properties
   - Retry variableLoad() as fallback

## How to Use

### 1. Run Export with Debug Logging

Enable debug logging in your export script:

```python
# At the top of the script, set logger to DEBUG level
import logging
logging.basicConfig(level=logging.DEBUG)
```

Or create a log file to capture output:

```python
# In the export main() function
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('export_debug.log'),
        logging.StreamHandler()
    ]
)
```

### 2. Look for These Log Messages

**When it finds an annotation:**
```
INFO: ZONE_NAME (Annotation): variableLoad() вернул пусто, проверяем свойства...
INFO: ZONE_NAME: доступные свойства: ['Value', 'ID', 'Description', 'History']
```

**When it successfully loads a value:**
```
INFO: ZONE_NAME: загружено из свойства 'Value' = ZoneB
```

**When it fails to load:**
```
WARNING: ZONE_NAME: ошибка при обработке свойств: <error description>
```

### 3. Interpret the Output

Look for patterns in the log:

**Pattern 1: Property list is empty**
```
доступные свойства: []
```
→ Annotation exists but has no properties. This is the core issue.

**Pattern 2: Properties exist but no useful value**
```
доступные свойства: ['ID', 'Description']
ZONE_NAME: ошибка при чтении свойства 'ID': ...
ZONE_NAME: ошибка при чтении свойства 'Description': ...
```
→ Properties exist but don't contain the annotation value.

**Pattern 3: variableLoad() returns unexpected type**
```
повторная попытка variableLoad() вернула: <some complex object> (тип: <type>)
```
→ Data is there but in unexpected format.

## Key Files Modified

- `D:\Dev\TechlogIO\WellLogML_Techlog_py3.py`
- `D:\Dev\TechlogIO\WellLogML_Techlog_export_v2.py`

## Next Steps After Debugging

Once we have the logs showing:

1. **What property contains the text value** (e.g., 'Value', 'Remarks', 'Text', etc.)
2. **What format the value is in** (string, array, object, etc.)
3. **Any errors** when accessing it

We can then:
- Update the property name detection in the code
- Add special handling for the specific format
- Ensure the value is properly exported to JSON

## Example Debug Output (Expected)

```
Обработка датасета: Stratigraphy
  Переменных: 10 (индексная: MD)
  Переменных для экспорта: 9
  
  [1/9] ZONE_NAME (Annotation): variableLoad() вернул пусто, проверяем свойства...
  ZONE_NAME: доступные свойства: ['Value', 'ID', 'Description', 'History']
  ZONE_NAME: загружено из свойства 'Value' = ZoneB
  ✓ ZONE_NAME (Zone Name) - 1 значений

  [2/9] MARKER_NAME (Annotation): variableLoad() вернул пусто, проверяем свойства...
  MARKER_NAME: доступные свойства: ['Value', 'ID', 'Description']
  MARKER_NAME: загружено из свойства 'Value' = TopOfPay
  ✓ MARKER_NAME - 1 значений
```

## If Logging Shows Issues

Report findings with these details:

1. **Log excerpt** showing the problem
2. **Variable name** with the issue
3. **Variable type** (Annotation, RichText, etc.)
4. **Available properties** list
5. **What value should be there** (e.g., 'ZoneB')

This will help identify the exact cause and tailor the fix.
