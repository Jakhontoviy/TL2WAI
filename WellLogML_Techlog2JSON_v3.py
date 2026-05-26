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
        self.current_well_id = None

    @staticmethod
    def _parse_history_item(history_string: str, debug: bool = False) -> Tuple[str, str, str]:
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

            if debug:
                print(f"      Парсинг истории: datetime='{datetime_str}', user='{username}', action='{action}'")

            try:
                if 'T' in datetime_str:
                    if '.' in datetime_str:
                        datetime_str = datetime_str.split('.')[0]
                    dt = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')
                    timestamp = str(int(dt.timestamp()))
                else:
                    dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                    timestamp = str(int(dt.timestamp()))
            except Exception as e:
                if debug:
                    print(f"      Ошибка парсинга datetime '{datetime_str}': {e}")
                timestamp = str(int(datetime.now().timestamp()))

            return timestamp, username, action
        else:
            if debug:
                print(f"      Не удалось распарсить историю: '{history_string}'")
            return str(int(datetime.now().timestamp())), 'unknown', history_string

    def _get_timestamp(self) -> int:
        """Получить текущий timestamp Unix."""
        return int(datetime.now().timestamp())

    def _get_username(self) -> str:
        """Получить имя пользователя системы."""
        return os.getenv('USERNAME', os.getenv('USER', 'user'))

    @staticmethod
    def _generate_id() -> str:
        """Сгенерировать случайный 24-символьный ID."""
        import uuid
        return str(uuid.uuid4()).replace('-', '')[:24]

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

    def _read_well_id(self, well_name: str) -> str:
        """Прочитать свойство ID скважины или сгенерировать и сохранить новый."""
        try:
            prop_list = db.wellPropertyList(well_name)
            if 'ID' in prop_list:
                existing_id = db.wellPropertyValue(well_name, 'ID')
                if existing_id and len(str(existing_id)) == 24:
                    return str(existing_id)
        except Exception:
            pass
        new_id = self._generate_id()
        try:
            db.setWellPropertyValue(well_name, 'ID', new_id)
        except Exception:
            pass
        return new_id

    def _read_dataset_id(self, well_name: str, dataset_name: str) -> str:
        """Прочитать свойство ID датасета или сгенерировать и сохранить новый."""
        try:
            prop_list = db.datasetPropertyList(well_name, dataset_name)
            if 'ID' in prop_list:
                existing_id = db.datasetPropertyValue(well_name, dataset_name, 'ID')
                if existing_id and len(str(existing_id)) == 24:
                    return str(existing_id)
        except Exception:
            pass
        new_id = self._generate_id()
        try:
            db.setDatasetPropertyValue(well_name, dataset_name, 'ID', new_id)
        except Exception:
            pass
        return new_id

    def _read_variable_id(self, well_name: str, dataset_name: str, variable_name: str) -> str:
        """Прочитать свойство ID переменной или сгенерировать и сохранить новый."""
        try:
            prop_list = db.variablePropertyList(well_name, dataset_name, variable_name)
            if 'ID' in prop_list:
                existing_id = db.variablePropertyValue(well_name, dataset_name, variable_name, 'ID')
                if existing_id and len(str(existing_id)) == 24:
                    return str(existing_id)
        except Exception:
            pass
        new_id = self._generate_id()
        try:
            db.setVariablePropertyValue(well_name, dataset_name, variable_name, 'ID', new_id)
        except Exception:
            pass
        return new_id

    @staticmethod
    def sync_project_ids(logger: logging.Logger = None) -> Dict[str, int]:
        """
        Записать в проект Techlog свойства ID для всех скважин, датасетов и переменных
        (отсутствующие или некорректной длины — создаются и сохраняются).

        Реализация в WellLogML_Techlog_prepare_ids.sync_project_ids (единая точка логики).

        Returns:
            Счётчики обработанных сущностей: wells, datasets, variables
        """
        from WellLogML_Techlog_prepare_ids import sync_project_ids as _sync_project_ids

        return _sync_project_ids(logger=logger)


    def _log(self, message: str, level: str = 'info'):
        if self.logger:
            log_fn = getattr(self.logger, level, self.logger.info)
            log_fn(message)

    def create_document(self, well_name: str) -> bool:
        """
        Создать базовую структуру документа для скважины.

        Returns:
            True если документ создан успешно.
        """
        well_id = self._read_well_id(well_name)

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

        self.current_well_id = well_id
        well_info["@id"] = self.current_well_id

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

        well_info["wellProperties"]["ID"] = {
            "value": self.current_well_id,
            "unit": "",
            "description": "Unique identifier"
        }

        try:
            prop_list = db.wellPropertyList(well_name)
            for prop_name in prop_list:
                if prop_name == 'ID':
                    continue

                try:
                    prop_value = db.wellPropertyValue(well_name, prop_name)

                    # Пропускаем HTML содержимое в свойствах
                    is_html, reason = self._is_html_content(str(prop_value) if prop_value is not None else '')
                    if is_html:
                        self._log(f"      Свойство скважины '{prop_name}': пропущено (HTML контент: {reason})", 'debug')
                        continue

                    prop_unit = db.wellPropertyUnit(well_name, prop_name)
                    prop_description = db.wellPropertyDescription(well_name, prop_name)

                    well_info["wellProperties"][prop_name] = {
                        "value": str(prop_value) if prop_value is not None else '',
                        "unit": prop_unit if prop_unit else '',
                        "description": prop_description if prop_description else ''
                    }
                except Exception:
                    pass
        except Exception:
            pass

        well_info["wellHistory"] = []

        try:
            history = db.wellHistory(well_name)
            if history and len(history) > 0:
                for hist_item in history:
                    if isinstance(hist_item, dict):
                        item_timestamp = hist_item.get('dateTime')
                        if item_timestamp is None or item_timestamp == '':
                            item_timestamp = str(self._get_timestamp())
                        item_username = hist_item.get('userName')
                        if item_username is None or item_username == '':
                            item_username = self._get_username()

                        well_info["wellHistory"].append({
                            "dateTime": str(item_timestamp),
                            "userName": item_username,
                            "action": hist_item.get('action', '')
                        })
                    else:
                        hist_item_str = str(hist_item).strip()

                        if 'History item created at' in hist_item_str and ' by ' in hist_item_str:
                            timestamp, username, action = self._parse_history_item(hist_item_str)
                            well_info["wellHistory"].append({
                                "dateTime": timestamp,
                                "userName": username,
                                "action": action
                            })
                        else:
                            well_info["wellHistory"].append({
                                "dateTime": str(self._get_timestamp()),
                                "userName": self._get_username(),
                                "action": hist_item_str
                            })
        except Exception as e:
            print(f"  Предупреждение: не удалось получить историю скважины: {e}")

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

        dataset_id = self._read_dataset_id(well_name, dataset_name)

        dataset_dict = {
            "@id": dataset_id
        }

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

        dataset_dict["datasetProperties"]["ID"] = {
            "value": dataset_id,
            "unit": "",
            "description": "Unique identifier"
        }

        try:
            prop_list = db.datasetPropertyList(well_name, dataset_name)
            if prop_list:
                for prop_name in prop_list:
                    if prop_name == 'ID':
                        continue

                    try:
                        prop_value = db.datasetPropertyValue(well_name, dataset_name, prop_name)

                        # Пропускаем HTML содержимое в свойствах
                        is_html, reason = self._is_html_content(str(prop_value) if prop_value is not None else '')
                        if is_html:
                            self._log(f"      Свойство датасета '{prop_name}': пропущено (HTML контент: {reason})", 'debug')
                            continue

                        try:
                            prop_unit = db.datasetPropertyUnit(well_name, dataset_name, prop_name)
                        except Exception:
                            prop_unit = ''

                        try:
                            prop_description = db.datasetPropertyDescription(well_name, dataset_name, prop_name)
                        except Exception:
                            prop_description = ''

                        dataset_dict["datasetProperties"][prop_name] = {
                            "value": str(prop_value) if prop_value is not None else '',
                            "unit": prop_unit if prop_unit else '',
                            "description": prop_description if prop_description else ''
                        }
                    except Exception:
                        pass
        except Exception:
            pass

        dataset_dict["datasetHistory"] = []

        try:
            history = db.datasetHistory(well_name, dataset_name)
            if history and len(history) > 0:
                for hist_item in history:
                    if isinstance(hist_item, dict):
                        item_timestamp = hist_item.get('dateTime')
                        if item_timestamp is None or item_timestamp == '':
                            item_timestamp = str(self._get_timestamp())
                        item_username = hist_item.get('userName')
                        if item_username is None or item_username == '':
                            item_username = self._get_username()

                        dataset_dict["datasetHistory"].append({
                            "dateTime": str(item_timestamp),
                            "userName": item_username,
                            "action": hist_item.get('action', '')
                        })
                    else:
                        hist_item_str = str(hist_item).strip()

                        if 'History item created at' in hist_item_str and ' by ' in hist_item_str:
                            timestamp, username, action = self._parse_history_item(hist_item_str)
                            dataset_dict["datasetHistory"].append({
                                "dateTime": timestamp,
                                "userName": username,
                                "action": action
                            })
                        else:
                            dataset_dict["datasetHistory"].append({
                                "dateTime": str(self._get_timestamp()),
                                "userName": self._get_username(),
                                "action": hist_item_str
                            })
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

        variable_id = self._read_variable_id(well_name, dataset_name, variable_name)

        # Если данные содержат строки, установить единицы измерения как 'unitless'
        if data is not None and len(data) > 0:
            data_type = self._detect_data_type(data)
            if data_type in ('string', 'mixed'):
                unit = 'unitless'

        variable_dict = {
            "@id": variable_id,
            "nullValue": null_value,
            "variableType": var_type,
            "variableUnit": unit,
            "variableDescription": description,
            "variableGroup": group_str,
            "variableFamily": family
        }

        variable_dict["variableHistory"] = []

        try:
            var_history = db.variableHistory(well_name, dataset_name, variable_name)
            if var_history and len(var_history) > 0:
                for hist_item in var_history:
                    if isinstance(hist_item, dict):
                        item_timestamp = hist_item.get('dateTime')
                        if item_timestamp is None or item_timestamp == '':
                            item_timestamp = str(self._get_timestamp())

                        variable_dict["variableHistory"].append({
                            "dateTime": str(item_timestamp),
                            "userName": hist_item.get('userName', username),
                            "action": hist_item.get('action', 'Created')
                        })
                    else:
                        hist_item_str = str(hist_item).strip()

                        if 'History item created at' in hist_item_str and ' by ' in hist_item_str:
                            hist_timestamp, hist_username, hist_action = self._parse_history_item(hist_item_str)
                            variable_dict["variableHistory"].append({
                                "dateTime": hist_timestamp,
                                "userName": hist_username,
                                "action": hist_action
                            })
                        else:
                            variable_dict["variableHistory"].append({
                                "dateTime": str(self._get_timestamp()),
                                "userName": username,
                                "action": hist_item_str
                            })
            else:
                variable_dict["variableHistory"].append({
                    "dateTime": str(self._get_timestamp()),
                    "userName": username,
                    "action": "Created"
                })
        except Exception:
            variable_dict["variableHistory"].append({
                "dateTime": str(self._get_timestamp()),
                "userName": username,
                "action": "Created"
            })

        variable_dict["variableProperties"] = {}

        variable_dict["variableProperties"]["ID"] = {
            "value": variable_id,
            "unit": "",
            "description": "Unique identifier"
        }

        try:
            prop_list = db.variablePropertyList(well_name, dataset_name, variable_name)
            if prop_list:
                for prop_name in prop_list:
                    if prop_name == 'ID':
                        continue

                    try:
                        prop_value = db.variablePropertyValue(well_name, dataset_name, variable_name, prop_name)

                        # Пропускаем HTML содержимое в свойствах
                        is_html, reason = self._is_html_content(str(prop_value) if prop_value is not None else '')
                        if is_html:
                            self._log(f"      Свойство переменной '{prop_name}': пропущено (HTML контент: {reason})", 'debug')
                            continue

                        try:
                            prop_unit = db.variablePropertyUnit(well_name, dataset_name, variable_name, prop_name)
                        except Exception:
                            prop_unit = ''

                        try:
                            prop_description = db.variablePropertyDescription(well_name, dataset_name, variable_name, prop_name)
                        except Exception:
                            prop_description = ''

                        variable_dict["variableProperties"][prop_name] = {
                            "value": str(prop_value) if prop_value is not None else '',
                            "unit": prop_unit if prop_unit else '',
                            "description": prop_description if prop_description else ''
                        }
                    except Exception:
                        pass
        except Exception:
            pass

        if data is not None and len(data) > 0:
            data_type = self._detect_data_type(data)
            self._log(f"        Кривая {var_name}: обнаружен тип данных '{data_type}'")

            if data_type in ('numeric', 'mixed'):
                try:
                    data_array = np.asarray(data, dtype=float)
                    data_clean = np.where(
                        (np.isnan(data_array)) | (data_array == null_value),
                        null_value,
                        data_array
                    )
                    variable_dict["variableData"] = [float(val) for val in data_clean]
                    self._log(f"        Кривая {var_name}: сохранено {len(data_clean)} числовых значений")
                except (ValueError, TypeError):
                    variable_dict["variableData"] = [str(val) if val is not None else '' for val in data]
                    self._log(f"        Кривая {var_name}: сохранено {len(data)} значений как текст")
            else:
                variable_dict["variableData"] = [str(val) if val is not None else '' for val in data]
                self._log(f"        Кривая {var_name}: сохранено {len(data)} текстовых значений")
        else:
            variable_dict["variableData"] = []
            self._log(f"        Кривая {var_name}: нет данных", 'warning')

        self.data["WellLogML"][self.current_well_name]["datasets"][self.current_dataset_name]["variables"][var_name] = variable_dict
        return True

    def check_file_changes(self, filename: str) -> Tuple[bool, List[str]]:
        """
        Проверить наличие изменений между текущим документом и существующим файлом.

        Returns:
            Кортеж (has_changes, differences).
        """
        if not os.path.exists(filename):
            msg = "Файл не существует - будет создан новый"
            self._log(f"{filename}: {msg}")
            return True, [msg]

        if self.data is None:
            raise ValueError("Сначала создайте документ с помощью create_document()")

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)

            differences = []

            new_well = self.data.get("WellLogML", {}).get(self.current_well_name, {})
            old_welllogml = existing_data.get("WellLogML", {})
            old_well = old_welllogml.get(self.current_well_name, old_welllogml.get("WellInformation", {}))

            new_datasets = new_well.get("datasets", {})
            old_datasets = old_well.get("datasets", {})

            new_ds_names = set(new_datasets.keys())
            old_ds_names = set(old_datasets.keys())

            added_ds = new_ds_names - old_ds_names
            removed_ds = old_ds_names - new_ds_names

            if added_ds:
                msg = f"Добавлены датасеты: {', '.join(sorted(added_ds))}"
                differences.append(msg)
                self._log(f"{filename}: {msg}")
            if removed_ds:
                msg = f"Удалены датасеты: {', '.join(sorted(removed_ds))}"
                differences.append(msg)
                self._log(f"{filename}: {msg}")

            for ds_name in new_ds_names & old_ds_names:
                new_index = new_datasets[ds_name].get("index")
                old_index = old_datasets[ds_name].get("index")

                if new_index and old_index:
                    new_index_data = new_index.get("variableData", [])
                    old_index_data = old_index.get("variableData", [])

                    if len(new_index_data) != len(old_index_data):
                        msg = f"Изменен размер индексной кривой в {ds_name}: {len(old_index_data)} -> {len(new_index_data)}"
                        differences.append(msg)
                        self._log(f"{filename}: {msg}")
                    elif new_index_data != old_index_data:
                        try:
                            new_arr = np.array(new_index_data)
                            old_arr = np.array(old_index_data)
                            if not np.allclose(new_arr, old_arr, equal_nan=True, rtol=1e-6, atol=1e-12):
                                msg = f"Изменены данные индексной кривой в {ds_name}"
                                differences.append(msg)
                                self._log(f"{filename}: {msg}")
                        except Exception:
                            msg = f"Изменены данные индексной кривой в {ds_name}"
                            differences.append(msg)
                            self._log(f"{filename}: {msg}")
                elif new_index and not old_index:
                    msg = f"Добавлена индексная кривая в {ds_name}"
                    differences.append(msg)
                    self._log(f"{filename}: {msg}")
                elif not new_index and old_index:
                    msg = f"Удалена индексная кривая из {ds_name}"
                    differences.append(msg)
                    self._log(f"{filename}: {msg}")

                new_vars = new_datasets[ds_name].get("variables", {})
                old_vars = old_datasets[ds_name].get("variables", {})

                new_var_names = set(new_vars.keys())
                old_var_names = set(old_vars.keys())

                added_vars = new_var_names - old_var_names
                removed_vars = old_var_names - new_var_names

                if added_vars:
                    msg = f"Добавлены переменные в {ds_name}: {', '.join(sorted(added_vars))}"
                    differences.append(msg)
                    self._log(f"{filename}: {msg}")
                if removed_vars:
                    msg = f"Удалены переменные из {ds_name}: {', '.join(sorted(removed_vars))}"
                    differences.append(msg)
                    self._log(f"{filename}: {msg}")

                for var_name in new_var_names & old_var_names:
                    new_var = new_vars[var_name]
                    old_var = old_vars[var_name]

                    for meta_key in ['variableUnit', 'variableDescription', 'variableType',
                                    'variableGroup', 'variableFamily', 'nullValue']:
                        new_meta = new_var.get(meta_key, '')
                        old_meta = old_var.get(meta_key, '')

                        if str(new_meta) != str(old_meta):
                            msg = f"Изменен {meta_key} переменной {var_name}: '{old_meta}' -> '{new_meta}'"
                            differences.append(msg)
                            self._log(f"{filename}: {msg}")

                    new_data = new_var.get("variableData", [])
                    old_data = old_var.get("variableData", [])

                    if len(new_data) != len(old_data):
                        msg = f"Изменен размер данных переменной {var_name}: {len(old_data)} -> {len(new_data)}"
                        differences.append(msg)
                        self._log(f"{filename}: {msg}")
                    elif new_data != old_data:
                        try:
                            new_arr = np.array(new_data)
                            old_arr = np.array(old_data)
                            if not np.allclose(new_arr, old_arr, equal_nan=True, rtol=1e-6, atol=1e-12):
                                msg = f"Изменены данные переменной: {var_name}"
                                differences.append(msg)
                                self._log(f"{filename}: {msg}")
                        except Exception:
                            msg = f"Изменены данные переменной: {var_name}"
                            differences.append(msg)
                            self._log(f"{filename}: {msg}")

            if differences:
                return True, differences

            msg = "Файл идентичен текущему документу - перезапись не требуется"
            self._log(f"{filename}: {msg}")
            return False, [msg]

        except Exception as e:
            msg = f"Ошибка при сравнении файлов: {e} - файл будет перезаписан"
            self._log(f"{filename}: {msg}", 'error')
            import traceback
            self._log(traceback.format_exc(), 'error')
            return True, [msg]

    def save(self, filename: str, check_changes: bool = True, force: bool = False) -> bool:
        """
        Сохранить JSON файл с проверкой изменений.

        Args:
            filename: Имя файла для сохранения
            check_changes: Проверять наличие изменений перед записью
            force: Принудительная перезапись даже если нет изменений

        Returns:
            True если файл был записан, False если запись пропущена
        """
        if self.data is None:
            raise ValueError("Сначала создайте документ с помощью create_document()")

        if check_changes and not force:
            has_changes, differences = self.check_file_changes(filename)

            if not has_changes:
                msg = f"Файл не изменился - запись пропущена"
                print(f"  ✓ {msg}")
                self._log(msg)
                return False
            else:
                basename = os.path.basename(filename)
                msg = f"Обнаружены изменения в файле: {basename}"
                print(f"\n  ! {msg}")
                self._log(f"\n  {msg}")
                self._log(f"    Обнаружено изменений: {len(differences)}")

                for i, diff in enumerate(differences, 1):
                    print(f"      {i}. {diff}")
                    self._log(f"      {i}. {diff}")

                self._log("")

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


def welllogml_write_from_techlog():
    """
    Экспорт всех скважин из БД Techlog в файлы WellLogML JSON.
    Для каждой скважины создаётся отдельный файл `<ID>.json`, где ID — свойство скважины (24 символа).

    Сущности без корректного свойства ID (24 символа) в JSON не попадают; выводятся сообщения об ошибке.
    Подготовка ID: WellLogML_Techlog_prepare_ids.py.
    """
    folderName = TECHLOG_JSON_ROOT
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
        'skipped': 0,
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

                json_stem = str(generator.current_well_id).strip()
                for ch in r'\/:*?"<>|':
                    json_stem = json_stem.replace(ch, '_')

                output_filename = os.path.join(folderName, f"{well_name_clean}_{json_stem}.json")

                file_exists = os.path.exists(output_filename)

                print(f"\n  Сохранение файла: {well_name_clean}_{json_stem}.json (скважина «{well_name}»)")
                logger.info(f"\n  Сохранение результатов:")
                logger.info(f"    Файл: {output_filename}")
                logger.info(f"    Существует: {'Да' if file_exists else 'Нет'}")

                was_saved = generator.save(output_filename, check_changes=True)

                if was_saved:
                    if file_exists:
                        stats['updated'] += 1
                        logger.info(f"    Результат: ОБНОВЛЕН")
                    else:
                        stats['created'] += 1
                        logger.info(f"    Результат: СОЗДАН")
                else:
                    stats['skipped'] += 1
                    logger.info(f"    Результат: ПРОПУЩЕН (нет изменений)")

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
        print(f"Пропущено (без изменений):       {stats['skipped']:>4}")
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
        logger.info(f"  Пропущено (без изменений): {stats['skipped']}")
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


def test_history_parsing():
    """
    Тестовая функция для проверки парсинга истории.
    """
    print("="*80)
    print("ТЕСТ ПАРСИНГА ИСТОРИИ")
    print("="*80)

    test_history_items = [
        "History item created at 2025-12-31T02:27:48.562 by user. Created",
        "History item created at 2025-12-31T02:27:52.381 by user. Renamed from 'Unknown' to 'GR'",
        "History item created at 2025-12-31T02:27:59.592 by user. Family changed from '' to 'Apparent Clay Gamma Ray'",
        "History item created at 2025-12-31T02:28:01.815 by user. Family changed from 'Apparent Clay Gamma Ray' to 'Gamma Ray'",
        "History item created at 2025-12-31T02:28:06.368 by user. Unit changed from '' to 'gAPI'",
        "History item created at 2025-12-31T02:28:30.436 by user. Saved from data editor ",
        "History item created at 2025-12-31T02:28:38.250 by user. Saved from data editor ",
        "History item created at 2026-01-12T11:05:47.088 by user. Saved from data editor ",
        "History item created at 2026-01-12T11:06:00.999 by user. Saved from data editor ",
    ]

    print("\nПарсинг записей истории:\n")

    for i, hist_item in enumerate(test_history_items, 1):
        print(f"Запись {i}:")
        print(f"  Входная строка: {hist_item}")

        timestamp, username, action = WellLogMLGenerator._parse_history_item(hist_item, debug=False)

        dt = datetime.fromtimestamp(int(timestamp))
        readable_time = dt.strftime('%Y-%m-%d %H:%M:%S')

        print(f"  ✓ dateTime: {timestamp} ({readable_time})")
        print(f"  ✓ userName: {username}")
        print(f"  ✓ action: {action}")
        print()

    print("="*80)
    print("Проверка различий во времени:")
    print("="*80)

    timestamps = []
    for hist_item in test_history_items:
        timestamp, _, _ = WellLogMLGenerator._parse_history_item(hist_item)
        timestamps.append(int(timestamp))

    unique_timestamps = set(timestamps)

    print(f"\nВсего записей: {len(test_history_items)}")
    print(f"Уникальных timestamps: {len(unique_timestamps)}")

    if len(unique_timestamps) == len(test_history_items):
        print("✅ УСПЕХ: Все timestamps уникальны!")
    else:
        print("❌ ОШИБКА: Есть дублирующиеся timestamps!")
        print(f"Дубликаты: {len(test_history_items) - len(unique_timestamps)}")

    print("\nПроверка хронологического порядка:")
    is_sorted = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))

    if is_sorted:
        print("✅ УСПЕХ: Timestamps в хронологическом порядке!")
    else:
        print("❌ ПРЕДУПРЕЖДЕНИЕ: Timestamps не в хронологическом порядке!")

    time_diff = timestamps[-1] - timestamps[0]
    minutes, seconds = divmod(time_diff, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    print(f"\nВременной диапазон:")
    print(f"  Первая запись: {datetime.fromtimestamp(timestamps[0]).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Последняя запись: {datetime.fromtimestamp(timestamps[-1]).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Разница: {days} дн {hours} ч {minutes} мин {seconds} сек")

    print("\n" + "="*80)
    print("ТЕСТ ЗАВЕРШЕН")
    print("="*80)


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        test_history_parsing()
    else:
        welllogml_write_from_techlog()

__author__ = """new USER (Alexey)"""
__date__ = """2026-05-26"""
__version__ = """1.0"""
__pyVersion__ = """3"""
__group__ = """"""
__suffix__ = """"""
__prefix__ = """"""
__applyMode__ = """0"""
__layoutTemplateMode__ = """"""
__includeMissingValues__ = """True"""
__keepPreviouslyComputedValues__ = """True"""
__areInputDisplayed__ = """True"""
__useMultiWellLayout__ = """True"""
__idForHelp__ = """"""
__executionGranularity__ = """full"""