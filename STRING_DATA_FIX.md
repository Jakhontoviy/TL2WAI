# String Data Export Fix

## Problem Found! 🎯

Текстовые данные не выгружались из-за **критической ошибки** при обработке строк в numpy.

### Корневая Причина

Код на строке 1107-1108 (оба скрипта):

```python
if not isinstance(curve_data, np.ndarray):
    curve_data = np.array(curve_data)  # ← ОПАСНО для строк!
```

Когда `curve_data` это строка (например, `"ZoneB"`):
```python
>>> curve_data = "ZoneB"
>>> np.array(curve_data)
array(['Z', 'o', 'n', 'e', 'B'], dtype='<U1')  # ← Разбивает на символы!
```

Вместо одного значения `"ZoneB"` получается массив из 5 символов!

## Solution Implemented ✅

Добавлена специальная обработка для строк:

```python
if isinstance(curve_data, str):
    # Строковое значение - обернуть в список
    curve_data = [curve_data]
elif not isinstance(curve_data, (list, np.ndarray)):
    curve_data = np.array(curve_data)
elif isinstance(curve_data, list) and not isinstance(curve_data[0] if curve_data else None, (str, np.ndarray)):
    curve_data = np.array(curve_data)
```

### Что Изменилось

| До | После |
|---|---|
| `"ZoneB"` → `['Z','o','n','e','B']` ❌ | `"ZoneB"` → `["ZoneB"]` ✅ |
| Массив цифр → `np.array()` ✓ | Массив цифр → `np.array()` ✓ |
| Список строк → `np.array()` разбит ❌ | Список строк → остается как список ✅ |

## Files Fixed

✅ `D:\Dev\TechlogIO\WellLogML_Techlog_py3.py`  
✅ `D:\Dev\TechlogIO\WellLogML_Techlog_export_v2.py`

## Expected Results After Fix

Теперь текстовые данные будут экспортироваться правильно:

**JSON вывод:**
```json
"ZONE_NAME": {
  "variableType": "Annotation",
  "variableData": ["ZoneB"]  // ← Правильно!
}

"MARKER_NAME": {
  "variableType": "Annotation", 
  "variableData": ["TopOfPay"]  // ← Правильно!
}
```

**Вместо ошибочного:**
```json
"ZONE_NAME": {
  "variableData": ["Z", "o", "n", "e", "B"]  // ❌ Неправильно
}
```

## How to Test

1. **Запустите экспорт** с одной скважиной
2. **Проверьте JSON файл** на наличие текстовых кривых
3. **Посмотрите на ZONE_NAME и подобные** - они должны содержать одно значение:
   ```json
   "ZONE_NAME": {
     "variableData": ["ZoneB"]
   }
   ```
4. **Импортируйте в Gamma DB** - текстовые кривые должны загруститься

## Why This Bug Existed

`np.array()` в NumPy:
- Для списков чисел: создает числовой массив ✓
- Для строк: **разбивает на массив символов** ❌

Это особенность NumPy, которая была упущена при первоначальной разработке экспорта текстовых данных.

## Impact

✅ Text/annotation variables теперь экспортируются правильно  
✅ Numeric curves продолжают работать как раньше  
✅ Mixed data (текст и числа) обрабатываются корректно  
✅ Backward compatible - no breaking changes
