# TL2WAI — WellLogML Data Transfer Toolkit

Python scripts for transferring well log data between **Schlumberger Techlog** and **Wellbore.AI (WAI)** via the WellLogML JSON format.

```
Techlog  →  WellLogML JSON  →  WAI DB
```

## Overview

| Script | Direction | Description |
|--------|-----------|-------------|
| `WellLogML_Techlog2JSON.py` | Techlog → JSON | Exports all wells from a Techlog database to individual WellLogML JSON files |
| `WellLogML_JSON2WAI.py` | JSON → WAI DB | Imports WellLogML JSON files into a WAI DB project |

## Features

- Exports complete well data: logs (1D and multi-column 2D), datasets, well/dataset/variable properties and history
- Handles Techlog-specific null values (`-9999`) and converts them to `NaN` on import
- Optional depth-unit conversion to metres (ft, km, in → m)
- Automatically repairs malformed JSON with leading-zero integers
- Configurable dataset and variable skip lists
- Per-well JSON files — safe to re-run, only changed files are updated
- Detailed console and file logging with processing statistics

## Requirements

- Python 3.6+
- NumPy
- **Techlog Python API** (`TechlogDatabase`) — available inside the Techlog scripting environment
- **WAI DB Python client** (`client.server.remote_server`) — part of the WAI DB distribution

## Usage

### 1. Export from Techlog

Run `WellLogML_Techlog2JSON.py` inside the **Techlog Python3 Interface Window**:

Each well is saved as `<WellName>_<timestamp>.json` in the output directory. A timestamped log file is written to `<output_dir>/log/`.

### 2. Import into WAI DB

Edit the configuration block at the top of `WellLogML_JSON2WAI.py`:

```python
PROJECT_NAME           = 'MyProject'       # target Gamma DB project
SOURCE_DIR             = r'C:\Temp\TL'     # folder with exported JSON files
SKIP_DATASETS          = ['Survey']        # datasets to skip
CONVERT_DEPTH_TO_METERS = False            # convert ft → m if needed
USE_FAMILY             = False             # auto-detect log family
```

Then run the script:

```bash
python WellLogML_JSON2WAI.py
```

## JSON Format

Each exported file follows the WellLogML structure:

```
WellLogML
└── <WellName>
    ├── wellProperties
    ├── wellHistory
    └── datasets
        └── <DatasetName>
            ├── index          # depth curve
            └── variables
                └── <CurveName>
                    ├── variableData   # compact single-line array
                    ├── variableUnit
                    ├── variableFamily
                    └── variableProperties
```

## License

BSD 3-Clause License — see [LICENSE](LICENSE).
