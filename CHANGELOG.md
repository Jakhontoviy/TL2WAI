# Changelog

## [Unreleased] – 2025-05-29

### WellLogML_Techlog2JSON.py

#### Added
- **True streaming JSON writer**: The generator no longer builds the entire document in memory. Instead, it opens a temporary file during `create_document()` and writes every key, dict, list, and scalar directly to disk as the data arrives.
- `_write_json_value_inline`, `_write_dict_inline`, `_write_list_inline` – low-level helpers that emit formatted JSON fragments on the fly.
- `_write_numeric_array_compact` and `_write_string_array_compact` – write `variableData` arrays in compact `[1, 2, 3]` / `["a", "b"]` form in 4096-element chunks, avoiding full-array stringification in RAM.
- `finalize_dataset()` – closes the current dataset's `variables` object and the dataset itself so the next dataset can continue streaming seamlessly.
- `_cleanup()` – closes the file handle and removes the temporary file if an error occurs mid-stream.
- Added `del curve_data` inside the per-curve loop to release curve data immediately after it has been written.

#### Changed
- `create_document()` now accepts a `filename` argument and opens the output stream immediately (it returns `True` on success or raises on failure).
- `add_dataset()` and `add_curve()` append to the open file instead of mutating an in-memory `self.data` dict.
- `save()` finalises the JSON structure, closes the stream, and atomically replaces the temp file with the target file. Removed the old `json.dumps()` + regex post-processing step because arrays are already written compactly.
- `_detect_data_type()` gained a fast path for `np.ndarray` inputs (numeric and fixed-width string dtypes), skipping the slow Python-list fallback for the common case.
- Filename sanitisation: removed `:` from the forbidden-character list and added `*` so names like `well*name` are also cleaned.
- Temporary file creation moved from `save()` to `create_document()` so the stream starts writing as early as possible.

#### Removed
- In-memory `self.data` dict and all intermediate structures that used to hold the full WellLogML document before serialisation.
- Regex-based compacting of `variableData` arrays (`compact_data_array` / `re.sub`).

### WellLogML_JSON2WAI.py

#### Added
- **Streaming import mode via `ijson`** (optional). If the `ijson` package is installed, the importer reads datasets and variables one at a time, keeping the memory footprint low even for multi-gigabyte JSON files.
  - `_get_well_name()` – extracts the well name without loading the whole file.
  - `_load_well_properties()` / `_load_field_name()` – stream well-level metadata.
  - `_load_dataset_index()` – fetches only the depth index for a single dataset.
  - `_stream_dataset_variables()` – yields `(var_name, var_info)` pairs lazily.
  - `_import_well_streaming()` – orchestrates the ijson-based pipeline.
- `_import_well_fallback()` – the original `json.load()` logic, kept for environments where `ijson` is not available.
- `_process_variable()` – refactored common logic shared by both streaming and fallback paths (null-value replacement, multi-column reshaping, family auto-detection, log creation, property application, and saving).
- **Field support**:
  - `USE_FIELD_AS_FIELD` configuration flag (`True` by default). When enabled, the `Field` / `field` value from the JSON file is used as the WAI DB field (place) when creating or matching a well.
  - Wells are looked up by **name + field** combination to avoid ambiguity when multiple wells share the same name in different fields.
  - Import of `WellProperty` from `client.shared.filters.well_filter`.
- **Progress bars**:
  - Optional `tqdm` integration for files, datasets, and curves. Falls back to plain iteration when `tqdm` is not installed.
- **`VERBOSE` flag** (`False` by default):
  - When `False`, only essential messages and progress bars are shown.
  - When `True`, full per-curve diagnostic output is restored.
- `_vprint()` helper – prints only when `VERBOSE` is enabled.

#### Changed
- `import_well_from_json()` now auto-detects the presence of `ijson` and transparently calls the streaming or fallback implementation.
- `replace_null_values()` optimised:
  - Fast path for already-float arrays: works in-place without copying when no nulls are found; copies only when necessary.
  - Removed forced `copy=True` on `astype(float)` – uses `copy=False` where possible.
  - Simplified string/object handling with flattened `ravel()` + vectorised mask instead of element-wise Python loops.
- `load_json_file()` reads the file once with `json.load(f)`; only if a "leading zeros" error occurs does it fall back to `read()` + regex fix.
- Memory hygiene in fallback mode:
  - `well_data.pop('datasets', {})` and `dataset.pop('variables', {})` are used so Python can garbage-collect each dataset/variable dict after processing.
  - Explicit `del` statements for `index_data`, `var_values`, `var_info`, and `data` to reduce peak RAM usage.
- Default values updated:
  - `PROJECT_NAME` changed from `'Techlog_project'` to `'AutoImport_fromTechlog'`.
  - `SKIP_DATASETS` changed from `['Survey']` to `[]`.
- Progress indicator in `main()` uses `tqdm` for the file loop when `VERBOSE` is off.

#### Fixed
- `load_json_file()` no longer reads the entire file into a string twice on the happy path.

---

### Summary
This release refactors both the export (Techlog → JSON) and import (JSON → WAI DB) scripts to use **true streaming I/O**, drastically reducing memory consumption for large well projects. The export side writes JSON directly to disk curve-by-curve; the import side reads JSON lazily variable-by-variable when `ijson` is available. Additional quality-of-life improvements include progress bars, verbose/silent mode, field-aware well matching, and incremental memory cleanup.
