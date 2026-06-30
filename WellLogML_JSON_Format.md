# WellLogML JSON Format Specification

**Version:** 1.0  
**Status:** Stable  
**Last updated:** 2026-06-02  

---

## 1. Overview

**WellLogML JSON** is a hierarchical, human-readable exchange format for well-log data exported from Schlumberger Techlog and imported into WAI DB. The format preserves:

- Well metadata, properties and history
- Datasets (log families / groups)
- Index curves (depth or time)
- Individual log curves (variables) with full metadata, properties and data arrays

Each file represents **one well**. Files are encoded in UTF-8.

---

## 2. Top-Level Structure

```json
{
  "WellLogML": {
    "DocumentInformation": { ... },
    "<WellName>": { ... }
  }
}
```

| Key | Type | Description |
|-----|------|-------------|
| `WellLogML` | `object` | Root container. Always a single key at the top level. |

---

## 3. DocumentInformation

Contains provenance and format-version metadata.

```json
"DocumentInformation": {
  "dtdVersion": {
    "@extended": "no",
    "@number": "1.0",
    "#text": "ContinuFile"
  },
  "FileCreationInformation": {
    "softwareName": {
      "@version": "2023.1",
      "#text": "Techlog"
    }
  }
}
```

| Path | Type | Description |
|------|------|-------------|
| `dtdVersion.@extended` | `string` | Whether the DTD is extended (`"no"` or `"yes"`). |
| `dtdVersion.@number` | `string` | Format version string, e.g. `"1.0"`. |
| `dtdVersion.#text` | `string` | File-type token, e.g. `"ContinuFile"`. |
| `softwareName.@version` | `string` | Version of the originating software. |
| `softwareName.#text` | `string` | Name of the originating software, e.g. `"Techlog"`. |

---

## 4. Well Object (`<WellName>`)

The well object uses the **well name itself** as the key. It is the sibling of `DocumentInformation` inside `WellLogML`.

```json
"<WellName>": {
  "wellColor": "#RRGGBB",
  "wellGroup": "GroupA, GroupB",
  "wellProperties": { ... },
  "wellHistory": [ ... ],
  "datasets": { ... }
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `wellColor` | `string` | No | Hex colour code assigned to the well in the source system. |
| `wellGroup` | `string` | No | Comma-separated list of well groups. |
| `wellProperties` | `object` | Yes* | Key/value properties of the well (see §4.1). |
| `wellHistory` | `array` | Yes* | Audit trail for the well (see §4.2). |
| `datasets` | `object` | Yes | Container for all datasets belonging to the well (see §5). |

\* *May be empty (`{}` or `[]`) but the keys must be present.*

### 4.1 Property Object Pattern

Properties are used at the well, dataset and variable levels. All three share the same structure:

```json
"<PropertyName>": {
  "value": "...",
  "unit": "...",
  "description": "..."
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `value` | `string` | Yes | Property value. Numbers and booleans are serialised as strings. |
| `unit` | `string` | No | Physical unit (e.g. `"m"`, `"g/cm3"`). Empty string if absent. |
| `description` | `string` | No | Human-readable description. Empty string if absent. |

> **Note:** The reserved property name `"ID"` is skipped during export. HTML-like property values are also filtered out.

### 4.2 History Entry Pattern

History arrays appear at the well, dataset and variable levels.

```json
[
  {
    "dateTime": "1735604845",
    "userName": "jsmith",
    "action": "Created"
  }
]
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `dateTime` | `string` | Yes | Unix timestamp (seconds since epoch). |
| `userName` | `string` | Yes | User who performed the action. |
| `action` | `string` | Yes | Description of the action (e.g. `"Created"`, `"Modified"`). |

---

## 5. Datasets (`datasets`)

A dataset groups related curves (e.g. `"LQC"`, `"WELL"`, `"Formation_Evaluation"`). The key is the dataset name.

```json
"datasets": {
  "<DatasetName>": {
    "datasetType": "string",
    "datasetGroup": "string",
    "MeasurementDetails": { ... },
    "index": { ... },
    "datasetProperties": { ... },
    "datasetHistory": [ ... ],
    "variables": { ... }
  }
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `datasetType` | `string` | No | Type classification from the source system. |
| `datasetGroup` | `string` | No | Group label (comma-separated if multiple). |
| `MeasurementDetails` | `object` | Yes | Index-range and sampling metadata (see §5.1). |
| `index` | `object` | Yes | The reference (depth/time) curve for this dataset (see §5.2). |
| `datasetProperties` | `object` | Yes* | Dataset-level properties (same schema as §4.1). |
| `datasetHistory` | `array` | Yes* | Dataset-level history (same schema as §4.2). |
| `variables` | `object` | Yes | Container for all curves in the dataset (see §6). |

### 5.1 MeasurementDetails

```json
"MeasurementDetails": {
  "startIndex": 0,
  "endIndex": 12499,
  "evenSampling": {
    "@index_curve": "MD",
    "stepIncrement": 0.1524
  }
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `startIndex` | `integer` | Yes | Zero-based start index of the data range. |
| `endIndex` | `integer` | Yes | Zero-based end index of the data range. |
| `evenSampling.@index_curve` | `string` | Yes | Name of the index curve (e.g. `"MD"`, `"TVD"`, `"TIME"`). |
| `evenSampling.stepIncrement` | `number` | Yes | Sampling step in the units of the index curve. |

### 5.2 Index Curve (`index`)

The index curve is mandatory. It provides the reference axis (most commonly measured depth).

```json
"index": {
  "name": "MD",
  "variableUnit": "m",
  "variableDescription": "Measured Depth",
  "variableType": "Continuous",
  "variableFamily": "Depth",
  "variableData": [1500.0, 1500.5, 1501.0, ...]
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | `string` | Yes | Mnemonic / name of the index curve. |
| `variableUnit` | `string` | Yes | Unit of the index (e.g. `"m"`, `"ft"`). |
| `variableDescription` | `string` | No | Human-readable description. |
| `variableType` | `string` | No | `"Continuous"`, `"Discrete"`, etc. |
| `variableFamily` | `string` | No | Family classification (e.g. `"Depth"`, `"Time"`). |
| `variableData` | `array` | Yes | Array of numeric values (`float`). |

> **Note on import:** If `CONVERT_DEPTH_TO_METERS` is enabled, the importer converts the index values (and unit) to metres using standard conversion factors.

---

## 6. Variables (`variables`)

Variables are the actual log curves. The key is the variable name (mnemonic).

```json
"variables": {
  "<VariableName>": {
    "nullValue": -9999,
    "variableType": "Continuous",
    "variableUnit": "g/cm3",
    "variableDescription": "Bulk Density",
    "variableGroup": "Density",
    "variableFamily": "Density",
    "variableHistory": [ ... ],
    "variableProperties": { ... },
    "variableData": [2.65, 2.66, -9999, 2.64, ...]
  }
}
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `nullValue` | `number` | Yes | Sentinel value representing missing data. Default: **`-9999`**. |
| `variableType` | `string` | Yes | `"Continuous"`, `"Discrete"`, or other type token. |
| `variableUnit` | `string` | Yes | Physical unit. For string/mixed data the exporter forces `"unitless"`. |
| `variableDescription` | `string` | No | Description of the curve. |
| `variableGroup` | `string` | No | Group label for the curve. |
| `variableFamily` | `string` | No | Family classification (e.g. `"Density"`, `"Resistivity"`). Used or overridden on import depending on `USE_FAMILY` setting. |
| `variableHistory` | `array` | Yes* | Audit trail (same schema as §4.2). |
| `variableProperties` | `object` | Yes* | Curve-level properties (same schema as §4.1). |
| `variableData` | `array` | Yes | Data array. Numeric or string. Missing values are encoded as the JSON number matching `nullValue` or as `null` for true `NaN`s. |

### 6.1 Data Types

The exporter detects the data type of each curve and writes it accordingly:

| Detected Type | `variableUnit` | `variableData` Content |
|---------------|----------------|------------------------|
| `numeric` | Original unit | Array of JSON numbers. `NaN` → `null` or `nullValue`. |
| `string` | `"unitless"` | Array of JSON strings. |
| `mixed` | `"unitless"` | Array of JSON strings (fallback). |
| `empty` | Original unit | `[]` |

### 6.2 Multi-Column (Array) Logs

On import, if the length of `variableData` is an exact multiple of the index length, the importer reshapes the 1-D array into a 2-D matrix:

```
shape = (num_columns, len(index))  →  transposed to (len(index), num_columns)
```

This supports multi-channel logs such as image logs, NMR spectra, etc.

---

## 7. Complete Minimal Example

```json
{
  "WellLogML": {
    "DocumentInformation": {
      "dtdVersion": {
        "@extended": "no",
        "@number": "1.0",
        "#text": "ContinuFile"
      },
      "FileCreationInformation": {
        "softwareName": {
          "@version": "2023.1",
          "#text": "Techlog"
        }
      }
    },
    "Well-01": {
      "wellColor": "#FF0000",
      "wellGroup": "Offshore",
      "wellProperties": {
        "Field": {
          "value": "Giant Oil Field",
          "unit": "",
          "description": "Field name"
        }
      },
      "wellHistory": [
        {
          "dateTime": "1735604845",
          "userName": "admin",
          "action": "Created"
        }
      ],
      "datasets": {
        "LQC": {
          "datasetType": "Log",
          "datasetGroup": "Main",
          "MeasurementDetails": {
            "startIndex": 0,
            "endIndex": 3,
            "evenSampling": {
              "@index_curve": "MD",
              "stepIncrement": 0.5
            }
          },
          "index": {
            "name": "MD",
            "variableUnit": "m",
            "variableDescription": "Measured Depth",
            "variableType": "Continuous",
            "variableFamily": "Depth",
            "variableData": [1500.0, 1500.5, 1501.0, 1501.5]
          },
          "datasetProperties": {},
          "datasetHistory": [],
          "variables": {
            "RHOB": {
              "nullValue": -9999,
              "variableType": "Continuous",
              "variableUnit": "g/cm3",
              "variableDescription": "Bulk Density",
              "variableGroup": "Density",
              "variableFamily": "Density",
              "variableHistory": [
                {
                  "dateTime": "1735604845",
                  "userName": "admin",
                  "action": "Created"
                }
              ],
              "variableProperties": {},
              "variableData": [2.65, 2.66, -9999, 2.64]
            }
          }
        }
      }
    }
  }
}
```

---

## 8. Conformance Rules

1. **UTF-8 encoding** is mandatory.
2. **One well per file.** The key immediately inside `WellLogML` that is not `DocumentInformation` is interpreted as the well name.
3. **Mandatory keys** at each level must be present (even if empty) to guarantee parser compatibility:
   - Well: `wellProperties`, `wellHistory`, `datasets`
   - Dataset: `MeasurementDetails`, `index`, `datasetProperties`, `datasetHistory`, `variables`
   - Variable: `nullValue`, `variableHistory`, `variableProperties`, `variableData`
4. **Null handling:** `NaN` and values equal to `nullValue` are written to JSON as `null` or as the number `nullValue` depending on the exporter implementation. Importers must replace both with `NaN`.
5. **HTML filtering:** Property values that contain HTML tags are stripped during export.

---

## 9. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-06-02 | Initial specification based on Techlog ↔ WAI DB exchange scripts. |

---

## 10. References

- `WellLogML_Techlog2JSON.py` — Exporter (Techlog → JSON)
- `WellLogML_JSON2WAI.py` — Importer (JSON → WAI DB)
