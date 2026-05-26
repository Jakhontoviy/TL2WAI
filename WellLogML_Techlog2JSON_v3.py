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
    """Класс для генерации файлов WellLogML в JSON формате из данных Techlog."""

    def __init__(self, techlog_version: str = "2023.1", logger: logging.Logger = None):
        self.techlog_version = techlog_version
        self.data = None
        self.logger = logger
        self.current_dataset_name = None
        self.current_well_name = None

    @staticmethod
    def _parse_history_item(history_string: str) -> Tuple[str, str, str]:
        """
        Парсит строку истории из Techlog.

        Формат строки: "History item created at 2025-12-31T02:27:25.028 by user. Created"

        Returns:
            Кортеж (timestamp, username, action), где:
            - timestamp: Unix timestamp в секундах (строка)
            - username: Имя пользователя
            - action: Описание действия
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
        """Получить текущий timestamp Unix."""
        return int(datetime.now().timestamp())

    def _get_username(self) -> str:
        """Получить имя пользователя системы."""
        return os.getenv('USERNAME', os.getenv('USER', 'user'))


    @staticmethod
    def _is_html_content(text: str) -> Tuple[bool, str]:
        """
        Обнаружить HTML-подобное содержимое в текстовых свойствах.

        Возвращает:
            Кортеж (is_html, reason), где:
            - is_html: True если содержимое похоже на HTML
            - reason: Описание обнаруженного HTML признака
        """
        if not isinstance(text, str):
            return False, ""

        text_stripped = text.strip()
        if not text_stripped:
            return False, ""

        # Признак 1: Начинается с < и содержит HTML теги
        if text_stripped.startswith('<') and ('>' in text_stripped):
            html_tags = ['<table', '<tr', '<td', '<th', '<div', '<span', '<html', '<body',
                        '<head', '<p>', '<br', '<a href', '<form', '<input', '<script', '<style']
            for tag in html_tags:
                if tag.lower() in text_stripped.lower():
                    return True, f"Найден HTML тег: {tag}"

        # Признак 2: Очень большой текст (> 500 символов) с HTML структурой
        if len(text_stripped) > 500:
            html_indicators = ['<table', '<tr', '<td', '<th', '&nbsp;', '&lt;', '&gt;', '&amp;']
            indicators_found = sum(1 for ind in html_indicators if ind.lower() in text_stripped.lower())
            if indicators_found >= 1:
                return True, f"Большой текст ({len(text_stripped)} символов) с HTML структурой"

        return False, ""

    @staticmethod
    def _detect_data_type(data) -> str:
        """
        Определить тип данных: 'numeric', 'string', или 'mixed'.

        Возвращает:
            'numeric' - все значения числовые (int, float, или NaN)
            'string' - содержит строки
            'mixed' - смешанные типы
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
        """Универсальное извлечение свойств из любой сущности."""
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
        """Универсальная обработка истории."""
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
        """Создать базовую структуру документа для скважины."""
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
        Добавить информацию о датасете.

        Returns:
            True если датасет добавлен успешно.
        """
        if self.data is None:
            raise ValueError("Сначала создайте документ с помощью create_document()")

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
                        index_type = 'Continu'

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

                    self._log(f"      Подготовлена индексная кривая: {ref_name} ({len(index_data):,} значений)")
            except Exception as e:
                self._log(f"      Не удалось загрузить индексную кривую {ref_name}: {e}", 'warning')

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
            self._log(f"      Добавлена индексная кривая: {index_curve_info['name']} ({len(index_curve_info['variableData']):,} значений)")

        dataset_dict["variables"] = {}

        self.data["WellLogML"][self.current_well_name]["datasets"][dataset_name_value] = dataset_dict
        self.current_dataset_name = dataset_name_value
        return True

    def add_curve(self, well_name: str, dataset_name: str, variable_name: str,
                  data: Optional[np.ndarray] = None, null_value: float = -9999) -> bool:
        """
        Добавить переменную в текущий датасет.

        Returns:
            False, если у переменной нет корректного свойства ID.
        """
        if self.data is None or self.current_dataset_name is None:
            raise ValueError("Сначала добавьте датасет с помощью add_dataset()")

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
        """Сохранить JSON файл."""
        if self.data is None:
            raise ValueError("Сначала создайте документ с помощью create_document()")

        json_str = json.dumps(self.data, ensure_ascii=False, indent=2)

        def compact_data_array(match):
            indent = match.group(1)
            key_name = match.group(2)
            array_content = match.group(3)

            # Проверяем, содержит ли массив текстовые строки (кавычки)
            if '"' in array_content:
                # Это текстовые данные - не компактируем, оставляем как есть
                return match.group(0)

            # Это числовые данные - компактируем
            values = re.findall(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?', array_content)
            if not values:
                # Если ничего не найдено, оставляем как было
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
        msg = f"Файл успешно записан: {filename} (размер: {file_size:,} байт)"
        self._log(msg)
        print(f"  ✓ {msg}")
        return True


def welllogml_write_from_techlog(output_dir: str = None):
    """
    Экспорт всех скважин из БД Techlog в файлы WellLogML JSON.
    Для каждой скважины создаётся отдельный файл `<ID>.json`.

    Args:
        output_dir: Директория для сохранения JSON файлов. По умолчанию используется значение из TECHLOG_JSON_ROOT.
    """
    folderName = output_dir or TECHLOG_JSON_ROOT
    if not os.path.exists(folderName):
        os.makedirs(folderName)
        print(f"Создан каталог для экспорта: {folderName}")
    else:
        print(f"Каталог для экспорта: {folderName}")

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

    logger.info("Начат экспорт данных из Techlog в WellLogML JSON")
    logger.info(f"Время начала: {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Каталог экспорта: {folderName}")
    logger.info(
        "Экспорт только читает ID из БД; при отсутствии ID сущность пропускается. "
        "Подготовка: WellLogML_Techlog_prepare_ids.py"
    )
    print(f"Лог-файл: {log_filename}")
    print(
        "Требуются свойства ID (24 символа). При необходимости сначала: "
        "WellLogML_Techlog_prepare_ids.py"
    )

    wells = db.wellList()
    print(f"Найдено скважин: {len(wells)}")
    logger.info(f"Найдено скважин для экспорта: {len(wells)}")

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
            print(f"[{idx}/{len(wells)}] Обработка скважины: {well_name}")
            print(f"{'='*60}")

            try:
                logger.info(f"{'='*60}")
                logger.info(f"[{idx}/{len(wells)}] Начата обработка скважины: {well_name}")
                logger.info(f"  Время начала: {well_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*60}")
                generator = WellLogMLGenerator(techlog_version="2023.1", logger=logger)

                if not generator.create_document(well_name):
                    stats['errors'] += 1
                    stats['wells_skipped_no_id'] += 1
                    logger.error(f"Скважина «{well_name}» пропущена: нет корректного свойства ID")
                    continue

                datasets = db.datasetList(well_name)
                print(f"  Датасетов: {len(datasets)}")
                logger.info(f"  Найдено датасетов: {len(datasets)}")

                well_total_vars = 0
                well_total_data_points = 0

                for ds_idx, dataset_name in enumerate(datasets, 1):
                    print(f"\n  [{ds_idx}/{len(datasets)}] Датасет: {dataset_name}")
                    logger.info(f"  [{ds_idx}/{len(datasets)}] Обработка датасета: {dataset_name}")

                    if not generator.add_dataset(well_name, dataset_name):
                        stats['datasets_skipped_no_id'] += 1
                        continue

                    variables = db.variableList(well_name, dataset_name)

                    try:
                        ref_name = db.referenceName(well_name, dataset_name)
                    except Exception:
                        ref_name = None

                    variables_to_export = [v for v in variables if v != ref_name]

                    print(f"      Переменных: {len(variables)} (индексная: {ref_name})")
                    logger.info(f"      Найдено переменных: {len(variables)} (индексная кривая: {ref_name})")
                    logger.info(f"      Переменных для экспорта: {len(variables_to_export)}")

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
                                msg += f" - {data_points:,} значений"

                                print(f"    ✓ {msg}")
                                logger.info(f"        Загружена переменная: {msg}")
                            else:
                                msg = f"      [{var_idx}/{len(variables_to_export)}] {variable_name} ({var_type}) - нет данных"
                                print(f"    ⚠ {msg}")
                                logger.warning(f"        {msg}")
                                logger.warning(f"          Возможные причины: db.variableLoad() вернула None или пустой результат")
                        except Exception as e:
                            error_msg = f"      [{var_idx}/{len(variables_to_export)}] Ошибка при загрузке {variable_name} ({var_type if 'var_type' in locals() else '?'}): {e}"
                            print(f"    ✗ {error_msg}")
                            logger.error(f"        {error_msg}")

                logger.info(f"  Статистика по скважине {well_name}:")
                logger.info(f"    - Датасетов: {len(datasets)}")
                logger.info(f"    - Переменных: {well_total_vars}")
                logger.info(f"    - Точек данных: {well_total_data_points:,}")

                well_name_clean = str(well_name).strip()
                for ch in r'\/:*?"<>|':
                    well_name_clean = well_name_clean.replace(ch, '_')

                timestamp_str = datetime.now().strftime('%y%m%d_%H%M%S')
                output_filename = os.path.join(folderName, f"{well_name_clean}_{timestamp_str}.json")

                file_exists = os.path.exists(output_filename)

                print(f"\n  Сохранение файла: {well_name_clean}_{timestamp_str}.json (скважина «{well_name}»)")
                logger.info(f"\n  Сохранение результатов:")
                logger.info(f"    Файл: {output_filename}")
                logger.info(f"    Существует: {'Да' if file_exists else 'Нет'}")

                generator.save(output_filename)

                if file_exists:
                    stats['updated'] += 1
                    logger.info(f"    Результат: ОБНОВЛЕН")
                else:
                    stats['created'] += 1
                    logger.info(f"    Результат: СОЗДАН")

                well_end_time = datetime.now()
                well_duration = (well_end_time - well_start_time).total_seconds()

                logger.info(f"\n  Завершена обработка скважины: {well_name}")
                logger.info(f"    Время окончания: {well_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"    Время выполнения: {well_duration:.2f} сек")
                logger.info(f"{'='*60}\n")

                print(f"\n  ⏱ Время обработки: {well_duration:.2f} сек")

            except Exception as e:
                stats['errors'] += 1
                well_end_time = datetime.now()
                well_duration = (well_end_time - well_start_time).total_seconds()

                error_msg = f"Ошибка при обработке скважины {well_name}: {e}"
                print(f"\n✗ {error_msg}")
                logger.error(f"\n✗ {error_msg}")
                logger.error(f"  Время выполнения до ошибки: {well_duration:.2f} сек")
                logger.error(f"{'='*60}\n")

                import traceback
                traceback.print_exc()
                logger.error(traceback.format_exc())
    finally:
        export_end_time = datetime.now()
        export_duration = (export_end_time - export_start_time).total_seconds()

        print(f"\n{'='*80}")
        print(f"СТАТИСТИКА ЭКСПОРТА:")
        print(f"{'='*80}")
        print(f"Всего скважин:                   {stats['total']:>4}")
        print(f"Создано новых файлов:            {stats['created']:>4}")
        print(f"Обновлено файлов:                {stats['updated']:>4}")
        print(f"Ошибок:                          {stats['errors']:>4}")
        print(f"Скважин без ID (файл не создан): {stats['wells_skipped_no_id']:>4}")
        print(f"Датасетов без ID (пропущено):    {stats['datasets_skipped_no_id']:>4}")
        print(f"Переменных без ID (пропущено):   {stats['variables_skipped_no_id']:>4}")
        print(f"{'='*80}")
        print(f"Время начала:              {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Время окончания:           {export_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Общее время выполнения:    {export_duration:.2f} сек ({export_duration/60:.2f} мин)")
        if stats['total'] > 0:
            avg_time = export_duration / stats['total']
            print(f"Среднее время на скважину: {avg_time:.2f} сек")
        print(f"{'='*80}")
        print(f"Лог-файл: {log_filename}")

        logger.info(f"\n{'='*60}")
        logger.info(f"ЭКСПОРТ ЗАВЕРШЕН")
        logger.info(f"{'='*60}")
        logger.info(f"Статистика:")
        logger.info(f"  Всего скважин: {stats['total']}")
        logger.info(f"  Создано новых файлов: {stats['created']}")
        logger.info(f"  Обновлено файлов: {stats['updated']}")
        logger.info(f"  Ошибок: {stats['errors']}")
        logger.info(f"  Скважин без ID (файл не создан): {stats['wells_skipped_no_id']}")
        logger.info(f"  Датасетов без ID (пропущено): {stats['datasets_skipped_no_id']}")
        logger.info(f"  Переменных без ID (пропущено): {stats['variables_skipped_no_id']}")
        logger.info(f"\nВремя выполнения:")
        logger.info(f"  Начало: {export_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Окончание: {export_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Общее время: {export_duration:.2f} сек ({export_duration/60:.2f} мин)")
        if stats['total'] > 0:
            avg_time = export_duration / stats['total']
            logger.info(f"  Среднее время на скважину: {avg_time:.2f} сек")
        logger.info(f"{'='*60}")

        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


if __name__ == '__main__':
    welllogml_write_from_techlog()