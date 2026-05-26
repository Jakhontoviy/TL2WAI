# HTML Content Filter for Export

## Problem
Well, dataset, and variable properties sometimes contain large HTML content (typically tables, formatted reports, etc.) that:
- Bloats the JSON file size significantly
- Is not useful in the export
- Creates visual clutter in the data

Example:
```html
<table border=1 cellpadding=0 cellspacing=0 align=center width=100%>
<tr><td colspan=20 align=center valign=middle><b>PAY RESULT</b></td></tr>
<tr><td>...</td>...
```

## Solution

Automatic HTML content detection and filtering in both export scripts:
- `WellLogML_Techlog_py3.py`
- `WellLogML_Techlog_export_v2.py`

## How It Works

### 1. Detection Method

The `_is_html_content()` function checks for:

**Pattern 1: HTML tags**
- Text starts with `<` and contains `>`
- Contains common HTML tags like: `<table>`, `<tr>`, `<td>`, `<div>`, `<form>`, `<script>`, etc.

**Pattern 2: Large text with HTML structure**
- Text > 1000 characters
- Contains 2+ HTML indicators: `<table`, `<tr`, `<td`, `&nbsp;`, `&lt;`, `&gt;`, `&amp;`, etc.

### 2. Where It's Applied

Filters HTML from properties of:
- **Wells**: `wellProperties`
- **Datasets**: `datasetProperties`
- **Variables**: `variableProperties`

### 3. Processing

When HTML is detected:
1. Property is **skipped** (not exported)
2. Debug log entry created: `"Свойство 'PropertyName' пропущено (HTML содержимое): <reason>"`
3. Export continues normally

## Example Output

Before filter:
```
wellProperties: {
  "Description": "Long HTML table with 5000+ characters...",
  "Location": "Well Location",
  "PayResult": "Another big HTML table...",
  ...
}
File size: 2.5 MB
```

After filter:
```
wellProperties: {
  "Location": "Well Location",
  ...
}
File size: 450 KB  ← 82% reduction!
```

## Configuration

To adjust HTML detection thresholds, modify the `_is_html_content()` method:

```python
# Current settings:
- Min text length for structure check: 1000 characters
- Min HTML indicators needed: 2
- HTML tags checked: table, tr, td, th, div, span, etc.

# To be more aggressive (filter more):
if len(text_stripped) > 500:  # Lower threshold
    if indicators_found >= 1:  # Fewer indicators needed

# To be less aggressive (filter less):
if len(text_stripped) > 2000:  # Higher threshold
    if indicators_found >= 3:  # More indicators needed
```

## Log Output

Example debug logs when running export:

```
Свойство 'PayResult' пропущено (HTML содержимое): Найден HTML тег: <table
Датасет 'Index': свойство 'Description' пропущено (HTML): Большой текст (5234 символов) с HTML структурой
Переменная 'ZONE_NAME': свойство 'Remarks' пропущено (HTML): Найден HTML тег: <div
```

## Benefits

✅ Reduced file size (often 50-80% smaller)
✅ Cleaner data - only useful properties exported
✅ Faster export/import
✅ Better data quality
✅ Automatic - no manual configuration needed

## Limitations

- Only filters HTML in **properties** (not in log curve data)
- Very short HTML snippets might not be detected
- Custom HTML patterns might need additional configuration

## Testing

Run the export script and check the log output:
1. Look for "пропущено (HTML)" messages
2. Check file size reduction
3. Verify important properties are still present
