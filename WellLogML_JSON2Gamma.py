"""
Импорт данных из WellLogML JSON файлов в Gamma DB

Скрипт загружает данные, экспортированные WellLogML_Techlog_py3.py, из JSON файлов
в базу данных Gamma DB. Каждый JSON файл представляет одну скважину с её датасетами и кривыми.

Алгоритм:
1. Сканирует каталог SOURCE_DIR на файлы *.json
2. Для каждого файла:
   - Парсит JSON и извлекает имя скважины
   - Создаёт скважину в указанном проекте (если её нет)
   - Для каждого датасета:
     - Пропускает датасеты в списке SKIP_DATASETS
     - Извлекает индексную кривую (глубину)
     - Для каждой переменной:
       - Заменяет null значения (-9999) на NaN
       - Создаёт лог с правильными параметрами
       - Сохраняет в БД
3. Выводит статистику обработки

Входные данные:
- JSON файлы из WellLogML_Techlog_py3.py (формат: <WellID>.json)
- Структура: WellLogML -> <WellName> -> datasets -> <DatasetName> -> variables

Выходные данные:
- Скважины и логи в проекте Gamma DB
- Статистика обработки в консоли

Параметры конфигурации:
- PROJECT_NAME: имя проекта в Gamma DB
- SOURCE_DIR: папка с JSON файлами (C:\\Temp\\TL)
- SKIP_DATASETS: датасеты для пропуска (например, ['Survey', 'MICP'])
- NULL_VALUE: значение, которое считается null в данных (-9999.0)

Примечания:
- Глубина (index) загружается в оригинальных единицах (ft, m и т.д.)
- Группы логов соответствуют имёнам датасетов из Techlog
- Пропускаются датасеты без индексной кривой (не имеющие глубины)
- Многостолбцовые логи (изображения, спектры и т.д.) автоматически преобразуются из 1D в 2D
  если размер данных кратен длине индекса
- Некорректный JSON с ведущими нулями в числах автоматически исправляется перед парсингом
- Опциональная конвертация глубин в метры (параметр CONVERT_DEPTH_TO_METERS)
  поддерживает: ft, m, km, in и другие единицы
"""

import sys
import os

# Установить UTF-8 кодировку для вывода в консоль
if sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавить корневую папку проекта в путь для импорта модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from client.server.remote_server import RemoteServer
import numpy as np
import json
import glob


# ========================
# КОНФИГУРАЦИЯ
# ========================

# Имя проекта в Gamma DB для загрузки
PROJECT_NAME = 'TL_fundTr'

# Папка с JSON файлами для импорта
SOURCE_DIR = r'C:\Temp\TL'

# Датасеты, которые нужно пропустить (например, 'Survey', 'MICP')
# Используйте для пропуска датасетов которые не содержат полезных данных
SKIP_DATASETS = ['Survey']

# Значение, которое считается null/missing в данных Techlog
NULL_VALUE = -9999.0

# Конвертировать глубины в метры при импорте
# Единица глубины берётся из JSON файла для каждого датасета (index.variableUnit)
CONVERT_DEPTH_TO_METERS = False

# Использовать семейство (family) из JSON файла или определять автоматически
# True = загружать variableFamily из JSON файла (как есть)
# False = игнорировать variableFamily из JSON и определять автоматически через prj.family_assigner
USE_FAMILY = False

# Попытаться переподключиться при ошибке подключения
RETRY_CONNECTION = True


# ========================
# ОСНОВНОЙ КОД
# ========================

def replace_null_values(data, null_value=NULL_VALUE):
    """
    Заменить null значения в массиве на np.nan.

    Обрабатывает как текстовые ("-9999") так и числовые (-9999) null значения.

    Параметры:
    - data: numpy array или список (1D или 2D)
    - null_value: значение, которое считается null (по умолчанию -9999.0)

    Возвращает:
    - numpy array с null значениями заменённые на np.nan
    """
    if not isinstance(data, np.ndarray):
        data = np.array(data)

    # Сначала попробовать преобразовать в float напрямую
    try:
        data_float = data.astype(float, copy=True)

        # Заменить значения близкие к null_value на np.nan используя isclose
        # Это работает для чисел как -9999, -9999.0, -9999e0 и т.д.
        mask = np.isclose(data_float, null_value, rtol=1e-5, atol=1e-8)
        data_float[mask] = np.nan

        return data_float

    except (ValueError, TypeError):
        # Если прямое преобразование не сработало, попробовать текстовую обработку
        pass

    # Обработать текстовые данные - создать копию и заменить на 'nan' перед преобразованием
    try:
        null_str = str(null_value)  # Например: "-9999.0"

        # Работать с массивом как с object для гибкости
        data_obj = data.astype(object, copy=True)
        original_shape = data_obj.shape

        # Функция для проверки каждого элемента
        def is_null_value(val):
            # Проверить как числовое значение
            try:
                return np.isclose(float(val), float(null_value), rtol=1e-5, atol=1e-8)
            except (ValueError, TypeError):
                # Проверить как строка (с учетом пробелов)
                return str(val).strip() == null_str.strip()

        # Использовать numpy vectorize для более эффективной обработки
        # или прямой цикл для меньших массивов
        flat_data = data_obj.ravel()
        null_mask = np.zeros(len(flat_data), dtype=bool)

        # Быстрая обработка: попробовать как float
        try:
            null_mask = np.isclose(flat_data.astype(float), float(null_value), rtol=1e-5, atol=1e-8)
        except (ValueError, TypeError):
            # Если это не работает, проверить как строки
            for i in range(len(flat_data)):
                if is_null_value(flat_data[i]):
                    null_mask[i] = True

        # Заменить null значения на 'nan'
        flat_data[null_mask] = np.nan

        # Восстановить исходную форму и преобразовать в float
        data_obj = flat_data.reshape(original_shape)
        return data_obj.astype(float)

    except Exception as e:
        # Если ничего не сработало - вернуть исходные данные
        return data


def load_json_file(filepath):
    """
    Безопасно загрузить JSON файл с обработкой ошибок.

    Пытается исправить некорректный JSON (числа с ведущими нулями типа 03, 04).

    Параметры:
    - filepath: путь к JSON файлу

    Возвращает:
    - dict (распарсенный JSON) или None при ошибке
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Попытка парсить как есть
        try:
            return json.loads(content)
        except json.JSONDecodeError as json_err:
            # Если ошибка с числами, попытаться исправить ведущие нули
            # Паттерн: [: после которого идут числа с ведущими нулями типа 0N, 0N, 0N
            if 'leading zeros' in str(json_err) or 'Expecting' in str(json_err):
                print(f'  ℹ Попытка исправить некорректный JSON с ведущими нулями...')
                # Заменить паттерны вроде "[0N" на "[N", ", 0N" на ", N"
                # Но не трогать строки
                fixed_content = content
                # Найти variableData массивы и исправить ведущие нули в них
                import re
                # Заменить , 0N на , N (для чисел с ведущими нулями внутри массива)
                fixed_content = re.sub(r',\s+0(\d)', r', \1', fixed_content)
                # Заменить [0N на [N (для первого элемента)
                fixed_content = re.sub(r'\[\s*0(\d)', r'[\1', fixed_content)

                return json.loads(fixed_content)
            else:
                raise
    except Exception as e:
        print(f'✗ Ошибка при чтении файла {filepath}: {e}')
        return None


def convert_depth_to_meters(depth_array, from_unit):
    """
    Конвертировать глубины из различных единиц в метры.

    Параметры:
    - depth_array: numpy array с значениями глубины
    - from_unit: исходная единица ('ft', 'm', 'km', и т.д.)

    Возвращает:
    - tuple: (converted_array, result_unit, factor_used)
      где converted_array - сконвертированный массив
      result_unit - всегда 'm'
      factor_used - коэффициент конвертации
    """
    from_unit_lower = str(from_unit).lower().strip()

    # Коэффициенты конвертации в метры
    conversion_factors = {
        'ft': 0.3048,           # футы → метры
        'feet': 0.3048,
        'feetбез': 0.3048,
        'm': 1.0,               # метры (без изменения)
        'meter': 1.0,
        'meters': 1.0,
        'km': 1000.0,           # километры → метры
        'kilometer': 1000.0,
        'kilometers': 1000.0,
        'in': 0.0254,           # дюймы → метры
        'inch': 0.0254,
        'inches': 0.0254,
    }

    if from_unit_lower in conversion_factors:
        factor = conversion_factors[from_unit_lower]
        converted = depth_array * factor
        return converted, 'm', factor
    else:
        # Единица не распознана - вернуть без изменений
        print(f'    ⚠ Неизвестная единица глубины: {from_unit} - конвертация пропущена')
        return depth_array, from_unit, 1.0


def extract_well_name(welllogml_dict):
    """
    Извлечь имя скважины из словаря WellLogML.

    В структуре WellLogML есть ключ "DocumentInformation" и один ключ для скважины.

    Параметры:
    - welllogml_dict: содержимое поля WellLogML из JSON

    Возвращает:
    - str: имя скважины или None если не найдено
    """
    for key in welllogml_dict:
        if key != 'DocumentInformation':
            return key
    return None


def apply_properties(obj, properties_dict):
    """
    Применить свойства из JSON к объекту Gamma DB (скважина, лог и т.д.) через update_meta().

    Параметры:
    - obj: объект Gamma DB (well, log и т.д.) с методом update_meta()
    - properties_dict: словарь свойств из JSON вида:
      {"propName": {"value": "...", "unit": "...", "description": "..."}}

    Возвращает:
    - кол-во применённых свойств
    """
    if not properties_dict or not isinstance(properties_dict, dict):
        return 0

    # Построить патч для update_meta()
    meta_patch = {}
    for prop_name, prop_data in properties_dict.items():
        try:
            # Извлечь значение из формата Techlog: {"value": "...", "unit": "...", "description": "..."}
            if isinstance(prop_data, dict) and 'value' in prop_data:
                prop_value = prop_data.get('value')
                prop_unit = prop_data.get('unit', '')

                # Если есть unit, сохранить как объект {value, unit}, иначе просто значение
                if prop_unit:
                    meta_patch[prop_name] = {'value': prop_value, 'unit': prop_unit}
                else:
                    meta_patch[prop_name] = prop_value
            elif isinstance(prop_data, dict):
                # Другой формат словаря - сохранить как есть
                meta_patch[prop_name] = prop_data
            else:
                # Простое значение
                meta_patch[prop_name] = prop_data
        except Exception:
            # Игнорировать ошибки при обработке отдельных свойств
            pass

    # Если есть свойства для добавления, обновить и сохранить
    if meta_patch:
        try:
            if hasattr(obj, 'update_meta'):
                obj.update_meta(meta_patch)
                return len(meta_patch)
        except Exception:
            # Если update_meta не удался, игнорировать
            pass

    return 0


def import_well_from_json(prj, filepath):
    """
    Импортировать одну скважину из JSON файла.

    Параметры:
    - prj: объект Project из Gamma DB
    - filepath: путь к JSON файлу

    Возвращает:
    - dict: статистика импорта для этого файла
      { 'well': имя, 'file': имя файла, 'datasets_ok': кол-во, 'curves_ok': кол-во,
        'curves_skipped': кол-во, 'errors': кол-во, 'error_list': список ошибок }
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

    # Загрузить JSON
    data = load_json_file(filepath)
    if data is None:
        return stats

    # Извлечь WellLogML блок
    welllogml = data.get('WellLogML')
    if not welllogml:
        stats['error_list'].append('WellLogML блок не найден')
        return stats

    # Найти имя скважины
    well_name = extract_well_name(welllogml)
    if not well_name:
        stats['error_list'].append('Имя скважины не найдено')
        return stats

    stats['well'] = well_name
    well_data = welllogml[well_name]

    print(f'\n  Обработка скважины: {well_name}')

    # Получить или создать скважину
    try:
        well = prj.wells.get_by_name(well_name, create_if_absent=True)
        well.save()

        # Загрузить свойства скважины
        well_properties = well_data.get('wellProperties', {})
        if well_properties:
            props_count = apply_properties(well, well_properties)
            if props_count > 0:
                well.save()
                print(f'    ℹ Загружено свойств скважины: {props_count}')

        print(f'    ✓ Скважина получена/создана')
    except Exception as e:
        stats['error_list'].append(f'Ошибка при создании скважины: {e}')
        stats['errors'] += 1
        return stats

    # Обработать датасеты
    datasets = well_data.get('datasets', {})
    for dataset_name, dataset in datasets.items():

        # Пропустить датасеты в списке SKIP_DATASETS
        if dataset_name in SKIP_DATASETS:
            print(f'    ⊘ Датасет пропущен: {dataset_name}')
            stats['curves_skipped'] += 1
            continue

        print(f'    Датасет: {dataset_name}')

        # Извлечь индексную кривую (глубину)
        index = dataset.get('index')
        if not index:
            print(f'      ✗ Нет индексной кривой (глубины)')
            stats['error_list'].append(f'{dataset_name}: нет индексной кривой')
            stats['errors'] += 1
            continue

        # Параметры индексной кривой
        index_name = index.get('name', 'MD')
        index_unit = index.get('variableUnit', 'm')
        index_data = np.array(index.get('variableData', []))

        if len(index_data) == 0:
            print(f'      ✗ Индексная кривая пустая')
            stats['error_list'].append(f'{dataset_name}: индексная кривая пустая')
            stats['errors'] += 1
            continue

        # Конвертация глубин если требуется
        reference_unit = index_unit
        if CONVERT_DEPTH_TO_METERS and index_unit.lower() != 'm':
            index_data, reference_unit, factor = convert_depth_to_meters(index_data, index_unit)
            print(f'      Индекс: {index_name} ({len(index_data)} точек, единица: {index_unit} → {reference_unit}, коэфф: {factor})')
        else:
            print(f'      Индекс: {index_name} ({len(index_data)} точек, единица: {index_unit})')

        # Обработать переменные (кривые)
        variables = dataset.get('variables', {})
        for var_name, var_data in variables.items():

            try:
                # Извлечь параметры переменной
                var_data_raw = var_data.get('variableData', [])
                var_unit = var_data.get('variableUnit', 'unitless')
                var_family = var_data.get('variableFamily', '')
                var_type = var_data.get('variableType', 'Continu')
                null_value = var_data.get('nullValue', NULL_VALUE)

                # Проверить что это список, а не одиночная строка/число
                # np.array('string') преобразует строку в array символов, что неправильно
                if isinstance(var_data_raw, (str, int, float, bool)):
                    var_data_raw = [var_data_raw]

                var_values = np.array(var_data_raw)

                # Дополнительная защита: если это массив символов (array(['Z','o','n','e']))
                # то это была одна строка, неправильно обработанная
                if var_values.dtype.kind == 'U' and len(var_values) > 1:
                    # Проверить - это должна быть одна строка, а не массив из символов
                    # Если строки в массиве это одиночные символы, это признак неправильного преобразования
                    if all(len(str(v)) == 1 for v in var_values):
                        print(f'        ⚠ {var_name} ({var_type}): возможна ошибка преобразования строки в массив символов (пропущено)')
                        stats['curves_skipped'] += 1
                        continue

                # Если нет данных, пропустить
                if len(var_values) == 0:
                    # Это может быть аннотация (Zone Name, Marker Name) или пусто поле
                    print(f'        ⊘ {var_name} ({var_type}): нет данных (пропущено)')
                    stats['curves_skipped'] += 1
                    continue

                # Проверить размер: должен совпадать с индексом или быть кратным (для многостолбцовых данных)
                if len(var_values) != len(index_data):
                    # Может быть это многостолбцовый лог (например, изображение)
                    if len(var_values) > 0 and len(var_values) % len(index_data) == 0:
                        num_columns = len(var_values) // len(index_data)
                        if num_columns > 1:  # Убедиться что это действительно многостолбцовые данные
                            print(f'        ℹ {var_name}: многостолбцовые данные - переформатирование {len(var_values)} → ({len(index_data)}×{num_columns})')
                            try:
                                # Данные приходят упорядочены ПО СТОЛБЦАМ: [col1_all, col2_all, col3_all]
                                # Сначала reshape в (num_columns, num_points), потом транспонируем в (num_points, num_columns)
                                reshaped = var_values.reshape((num_columns, len(index_data))).T
                                print(f'          После reshape: форма {reshaped.shape}, тип {reshaped.dtype}')
                                var_values = reshaped
                                # Продолжить с загрузкой многостолбцового лога
                            except Exception as e:
                                print(f'        ✗ {var_name}: ошибка при переформатировании: {e}')
                                stats['curves_skipped'] += 1
                                continue
                        else:
                            # Это не многостолбцовые данные
                            print(f'        - {var_name}: размер данных {len(var_values)} не совпадает с индексом {len(index_data)} (пропущено)')
                            stats['curves_skipped'] += 1
                            continue
                    else:
                        print(f'        - {var_name}: размер данных {len(var_values)} не совпадает с индексом {len(index_data)}, не кратен (пропущено)')
                        stats['curves_skipped'] += 1
                        continue

                # Заменить null значения
                var_values = replace_null_values(var_values, null_value)

                # Логирование для многостолбцовых данных
                if var_values.ndim == 2:
                    print(f'          После replace_null_values: форма {var_values.shape}, содержит {np.sum(np.isnan(var_values))} NaN значений')

                # Определение семейства (family) логирования
                original_family = var_family  # Сохранить оригинальное значение из JSON

                if not USE_FAMILY or not var_family:
                    # Если флаг USE_FAMILY=False или семейство не указано, используем автоматическое определение
                    try:
                        mnemonic_info = prj.family_assigner.assign_family(var_name, var_unit)
                        var_family = mnemonic_info.family
                        if not USE_FAMILY:
                            print(f'        ℹ {var_name}: family определено автоматически = {var_family}')
                    except Exception:
                        # Если автоматическое определение не удалось, вернуться к оригинальному значению
                        var_family = original_family
                        if not USE_FAMILY and not var_family:
                            print(f'        ⚠ {var_name}: не удалось определить family, оставлено пусто')

                # Создать лог в Gamma DB
                log = well.logs.create(
                    name=var_name,
                    group=[dataset_name],        # группа = имя датасета
                    values_family=var_family,
                    values_unit=var_unit,
                    reference_unit=index_unit    # единица глубины из индексной кривой
                )

                # Загрузить свойства переменной (логирования)
                var_properties = var_data.get('variableProperties', {})
                if var_properties:
                    props_count = apply_properties(log, var_properties)
                    if props_count > 0:
                        print(f'        ℹ Загружено свойств логирования: {props_count}')

                # Установить значения
                # Для многостолбцовых данных (2D массивов) логировать размеры и проверку
                if var_values.ndim == 2:
                    num_nan = np.sum(np.isnan(var_values))
                    print(f'          До set_rvalues: index {index_data.shape}, values {var_values.shape}, NaN={num_nan}')
                    # Убедиться что первая размерность совпадает с индексом
                    if var_values.shape[0] != len(index_data):
                        print(f'          ✗ ОШИБКА: размеры не совпадают! index={len(index_data)}, values[0]={var_values.shape[0]}')
                        stats['curves_skipped'] += 1
                        continue

                log.set_rvalues(index_data, var_values)

                # Сохранить
                log.save()

                # Логирование результата
                if var_values.ndim == 2:
                    print(f'        ✓ {var_name} ({var_family}, {var_unit}) {var_values.shape[0]} точек × {var_values.shape[1]} столбцов')
                else:
                    print(f'        ✓ {var_name} ({var_family}, {var_unit}, {len(var_values)} точек)')
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
    """Главная функция импорта."""
    print('=' * 70)
    print('WellLogML JSON → Gamma DB Импортер')
    print('=' * 70)

    # Подключение к серверу
    print(f'\nПодключение к серверу...')
    try:
        gc = RemoteServer(user='alex', password='pass')
        print(f'✓ Подключено')
    except Exception as e:
        print(f'✗ Ошибка подключения: {e}')
        return

    # Получить проект
    print(f'\nПолучение проекта: {PROJECT_NAME}')
    try:
        prj = gc.projects.get_by_name(PROJECT_NAME)
        if not prj:
            print(f'✗ Проект {PROJECT_NAME} не найден')
            return
        print(f'✓ Проект найден')
    except Exception as e:
        print(f'✗ Ошибка при получении проекта: {e}')
        return

    # Сканирование файлов
    print(f'\nСканирование каталога: {SOURCE_DIR}')
    json_files = sorted(glob.glob(os.path.join(SOURCE_DIR, '*.json')))
    print(f'Найдено JSON файлов: {len(json_files)}')

    if not json_files:
        print('Файлы не найдены')
        return

    # Импорт каждого файла
    print('\n' + '=' * 70)
    print('ИМПОРТ')
    print('=' * 70)

    all_stats = []
    for i, filepath in enumerate(json_files, 1):
        print(f'\n[{i}/{len(json_files)}] {os.path.basename(filepath)}')
        stats = import_well_from_json(prj, filepath)
        all_stats.append(stats)

    # Статистика
    print('\n' + '=' * 70)
    print('ИТОГОВАЯ СТАТИСТИКА')
    print('=' * 70)

    total_files = len(json_files)
    total_wells = len([s for s in all_stats if s['well']])
    total_datasets = sum(s['datasets_ok'] for s in all_stats)
    total_curves = sum(s['curves_ok'] for s in all_stats)
    total_skipped = sum(s['curves_skipped'] for s in all_stats)
    total_errors = sum(s['errors'] for s in all_stats)

    print(f'\nФайлы обработаны:        {total_files}')
    print(f'Скважины созданы:         {total_wells}')
    print(f'Датасеты обработаны:      {total_datasets}')
    print(f'Кривые загружены:         {total_curves}')
    print(f'Кривые пропущены:         {total_skipped}')
    print(f'Ошибок при загрузке:      {total_errors}')

    # Список скважин с ошибками
    error_wells = [s for s in all_stats if s['error_list']]
    if error_wells:
        print('\nСкважины с ошибками:')
        for stats in error_wells:
            print(f'  {stats["file"]} ({stats["well"]}):')
            for error in stats['error_list']:
                print(f'    - {error}')

    print('\n✓ Импорт завершён')


if __name__ == '__main__':
    main()
