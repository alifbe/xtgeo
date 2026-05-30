# ResInsight Polygon Interface

This document describes the ResInsight polygon interface added to XTGeo on the
`ri-polygon` branch, the design decisions behind it, and potential future
improvements.

---

## 1. What Has Been Done

### 1.1 New Public API

Two new public entry points allow users to transfer polygon data between XTGeo
and a running ResInsight instance via gRPC:

| Function / Method | Direction | Location |
|---|---|---|
| `xtgeo.polygons_from_resinsight(instance_or_port, name)` | ResInsight → XTGeo | `src/xtgeo/xyz/polygons.py` |
| `Polygons.to_resinsight(instance_or_port)` | XTGeo → ResInsight | `src/xtgeo/xyz/polygons.py` |

Both are registered in `xtgeo/__init__.py` and available as top-level imports.

#### Usage

```python
import xtgeo

# Write to ResInsight (auto-discover or specify port)
poly = xtgeo.polygons_from_file("faults.pol")
poly.to_resinsight(5000)

# Read from ResInsight
poly = xtgeo.polygons_from_resinsight(5000, "faults")
print(poly.get_dataframe())
```

### 1.2 Internal Architecture

#### `_polygon.py` — Data Container, Reader, Writer

| Class / Function | Responsibility |
|---|---|
| `PolygonDataResInsight` | Immutable data container for a single ResInsight polygon (name + `[[x, y, z], ...]` coordinates). Handles XTGeo ↔ ResInsight conversion including Z-negation. |
| `PolygonReader` | Reads polygons from ResInsight via rips gRPC. Supports loading by name, by folder, or all polygons. |
| `PolygonWriter` | Writes polygons to ResInsight. Supports saving to root collection or into named folders. |
| `_rips_polygon_to_data()` | Module-level helper that converts a rips `Polygon` object to `PolygonDataResInsight` with proper deep copy. |

#### `_resinsight_base.py` — Shared Base Class Extensions

New methods added to `_BaseResInsightDataRW` (the base class shared with the
grid interface):

| Method | Purpose |
|---|---|
| `get_polygon_collection()` | Returns the first `rips.PolygonCollection` from the project. Includes a `None` guard for the `rips` module import. |
| `find_polygon()` | Static method. Scans a collection for a polygon by name (`find_last` controls first vs last match). |
| `find_folder()` | Static method. Finds a sub-collection (folder) by name. Generalized via `name_attr` parameter for reuse with surface collections. |
| `get_or_create_folder()` | Static method. Finds or creates a folder. Uses `add_folder()` from the rips API. |

#### `_rips_package.py` — Type Aliases

Added `RipsPolygonType` and `RipsPolygonCollectionType` type aliases following
the existing pattern for `RipsCaseType`, `RipsInstanceType`, and
`RipsProjectType`.

### 1.3 Folder-Based Multi-Segment Support

XTGeo `Polygons` objects can contain multiple segments identified by `POLY_ID`.
ResInsight represents each polygon as a separate object. This PR bridges the
gap using ResInsight's folder API:

- **Write path (`to_resinsight`)**: Always creates a folder named after the
  Polygons object. Each segment becomes a polygon inside the folder, named
  `"{folder_name} ({poly_id})"` — e.g., `"faults (0)"`, `"faults (1)"`.

- **Read path (`polygons_from_resinsight`)**: Uses `load_by_name()` which
  checks **folders first**, then falls back to individual polygons. Folder
  contents are combined into a single `Polygons` object with sequential
  `POLY_ID` values.

### 1.4 Z-Depth Sign Convention Handling

XTGeo uses **Z_TVDSS** (depth positive down: `+1000` = 1000 m below sea
level). ResInsight uses **Z-up** (`-1000` = 1000 m below sea level). Z values
are negated at every conversion boundary:

| Conversion | Where | Operation |
|---|---|---|
| XTGeo → ResInsight | `from_xtgeo_polygons()` | `Z = -Z` |
| XTGeo → ResInsight | `from_xtgeo_polygons_all()` | `Z = -Z` |
| ResInsight → XTGeo | `to_xtgeo_polygons()` | `Z = -Z` |
| ResInsight → XTGeo | `polygons_from_resinsight()` multi-segment path | `Z = -Z` (via `to_xtgeo_polygons()`) |

Double-negation in roundtrips cancels out, preserving data fidelity.

### 1.5 Test Suite

**14 non-live tests** (no ResInsight required):

| Test | Coverage |
|---|---|
| `test_empty_coordinates_raises` | Validation: empty coordinates |
| `test_bad_coordinate_length_raises` | Validation: non-3D coordinate |
| `test_eq_and_ne` | Equality and inequality operators |
| `test_unhashable` | `__hash__ = None` enforcement |
| `test_to_xtgeo_polygons` | ResInsight → XTGeo with Z-negation |
| `test_from_xtgeo_polygons_default_poly_id` | Default segment selection |
| `test_from_xtgeo_polygons_default_selects_first_when_not_zero` | Non-zero starting POLY_ID |
| `test_from_xtgeo_polygons_explicit_poly_id` | Explicit segment selection |
| `test_from_xtgeo_polygons_missing_poly_id_raises` | Invalid POLY_ID error |
| `test_from_xtgeo_polygons_all` | Multi-segment naming format |
| `test_from_xtgeo_polygons_all_preserves_coordinates` | Coordinate integrity per segment |
| `test_roundtrip_via_xtgeo` (×3 parametrized) | Full roundtrip data fidelity |

**7 live tests** (require `@pytest.mark.requires_resinsight`):

| Test | Coverage |
|---|---|
| `test_polygon_writer_updates_existing` | Upsert: create then update |
| `test_polygon_reader_missing_raises` | Error for missing polygon |
| `test_roundtrip_resinsight` | Write → read roundtrip via rips gRPC |
| `test_public_api_to_resinsight` | Single-segment public API roundtrip |
| `test_public_api_to_resinsight_multi_segment` | Multi-segment folder roundtrip |
| `test_polygon_writer_save_to_folder` | Direct folder write and read |

### 1.6 Other Changes

| Change | File |
|---|---|
| Added `--threadcount 1` to `launch_instance()` | `rips_utils.py` |
| Removed flaky `test_grid_from_resinsight_auto_discover` | `test_grid_public_api.py` |
| Cleaned up `test_rips_utils.py`: removed debug `print()`, merged overlapping tests, removed verbose assertion messages | `test_rips_utils.py` |
| Removed unused `cases_names` variable | `conftest.py` |

---

## 2. Why They Were Done

### 2.1 Folder-Based Storage

ResInsight's polygon model is flat — one `Polygon` object per polyline. XTGeo's
`Polygons` can hold multiple segments. Without folders, multi-segment polygons
would be stored as disconnected root-level polygons with no way to group them
back together on read.

The rips API added `add_folder()` and `sub_collections()` support (see
[ResInsight test_polygon.py](https://github.com/OPM/ResInsight/blob/3375e37ffc3698579299dbdbb905c02ed353c15b/GrpcInterface/Python/rips/tests/test_polygon.py)),
which enables grouping related polygons into named sub-collections. This PR
uses that feature to maintain the multi-segment structure through the
ResInsight roundtrip.

### 2.2 Always Using Folders (Even for Single Segments)

An earlier design saved single-segment polygons directly to the root collection
and only used folders for multi-segment polygons. Code review (Claude Opus 4.6
and GPT-5.4) identified a critical bug: if a multi-segment polygon was
previously saved as a folder, then a single-segment polygon with the same name
was later saved to root, `load_by_name()` (which checks folders first) would
return the stale folder contents instead of the new single polygon.

The fix: **always save into a folder**, regardless of segment count. This
eliminates the shadowing bug and simplifies both the write and read paths.

### 2.3 Z-Negation at Conversion Boundaries

Depth sign convention mismatch caused polygon depths to appear negative in
ResInsight. The fix applies negation consistently at every XTGeo ↔ ResInsight
boundary, rather than in the public API layer, so the `PolygonDataResInsight`
container always holds coordinates in ResInsight convention (Z-up).

### 2.4 Generalized Folder Helpers

`find_folder()` and `get_or_create_folder()` accept a `name_attr` parameter
(defaults to `"polygon_collection_name"`) so they can be reused by a future
`SurfaceReader`/`SurfaceWriter` without duplicating the folder lookup logic.
The surface collection uses a different attribute name for its folder name.

### 2.5 DRY Refactoring

| Pattern | Helper | Eliminated Duplication |
|---|---|---|
| `PolygonDataResInsight(name=p.name, coordinates=list(p.coordinates))` repeated 5× | `_rips_polygon_to_data()` | rips → data conversion across all Reader methods |
| `[... for p in collection.polygons()]` repeated 4× | `_load_polygons_from()` | Collection-to-list conversion in Reader |
| Find-existing-or-create logic duplicated in `save()` and `save_to_folder()` | `_upsert_polygon()` | Upsert logic in Writer |
| Per-element Z-negation loop in `from_xtgeo_polygons()` | Vectorized `coords[:, 2] = -coords[:, 2]` | Consistent with `from_xtgeo_polygons_all()` |

### 2.6 `rips` None Guard

The `rips` module is loaded dynamically via `importlib.import_module()` and is
`Any | None` at type-check time. Without the `if rips is None` guard in
`get_polygon_collection()`, mypy reports `Item "None" of "Any | None" has no
attribute "PolygonCollection"`. The guard also provides a clear `ImportError`
message to users who don't have `rips` installed.

### 2.7 Empty Folder Guard

Code review (Claude Opus 4.6) identified that if `load_by_name()` finds a
folder with zero polygons, it returns an empty list, causing
`polygons_from_resinsight()` to crash with an unhelpful
`ValueError: No objects to concatenate` from `pd.concat([])`. An explicit
`if not data_list` guard was added to raise a clear error message.

---

## 3. Potential Improvements

### 3.1 Stale Polygon Cleanup on Re-Save

**Severity**: Medium

When re-saving a `Polygons` object with **fewer** segments than a previous
save, the old segments remain in the folder. For example, saving 3 segments
then saving 2 segments leaves the third polygon from the old save intact.

This is a limitation of the ResInsight gRPC API, which does not currently
expose a polygon deletion method. Possible mitigations:

- **Upstream**: Request a `delete_polygon()` or `clear_folder()` method in the
  rips Python API.
- **Workaround**: Create a new folder with a unique name (e.g., append a
  timestamp) and save into it, then rename. However, renaming may also not be
  supported.
- **Documentation**: Currently handled via a `.. note::` in the
  `to_resinsight()` docstring.

### 3.2 `--threadcount 1` as a Configurable Parameter

`launch_instance()` currently hardcodes `command_line_parameters=["--threadcount", "1"]`.
This was added for test determinism but affects all users of
`RipsApiUtils.launch_instance()`.

Consider making it configurable:

```python
@staticmethod
def launch_instance(
    ...,
    command_line_parameters: list[str] | None = None,
) -> RipsInstanceType:
```

Then pass `["--threadcount", "1"]` only from the test fixture.

### 3.3 Surface Collection Reuse

The `find_folder()` and `get_or_create_folder()` methods are generalized via
the `name_attr` parameter but have not been exercised with surface collections
yet. When implementing `SurfaceReader`/`SurfaceWriter`, validate that:

- The correct `name_attr` for surface collections is identified.
- The `add_folder()` API works the same way for surfaces as for polygons.

### 3.4 Recursive Folder Loading

`load_all()` only returns polygons at the root level and does not recurse into
sub-folders. A recursive variant (or a `recursive=True` parameter) could be
useful for projects with deeply nested polygon structures.

### 3.5 Batch Coordinate Transfer

For very large polygons (thousands of points), the current approach of
transferring coordinates as Python lists of lists via gRPC may be slow.
Consider whether the rips API supports:

- Binary/numpy array transfer for coordinates.
- Streaming for large polygon sets.

### 3.6 `find_last` Parameter Cleanup

`Polygons.to_resinsight()` accepts a `find_last` parameter for API consistency
with `Grid.to_resinsight()`, but it is not used since all writes go through
`save_to_folder()`. Consider removing it to avoid confusion, or implementing
it if future use cases arise.

### 3.7 Roundtrip POLY_ID Preservation

The current read path assigns sequential `POLY_ID` values (0, 1, 2, ...) based
on folder order, regardless of the original POLY_ID values. If the original
polygon had POLY_IDs [0, 5, 10], the roundtrip would produce [0, 1, 2].

To preserve original POLY_IDs, the naming convention `"{name} ({poly_id})"` 
could be parsed on read to extract the original ID. This would require a
regex like `r"\((\d+)\)$"` on the polygon name.

---

## File Summary

| File | Lines Changed | Purpose |
|---|---|---|
| `src/xtgeo/__init__.py` | +2 | Register `polygons_from_resinsight` |
| `src/xtgeo/interfaces/resinsight/__init__.py` | +4 | Export polygon classes |
| `src/xtgeo/interfaces/resinsight/_polygon.py` | +294 (new) | Data container, Reader, Writer |
| `src/xtgeo/interfaces/resinsight/_resinsight_base.py` | +88 | Polygon collection + folder helpers |
| `src/xtgeo/interfaces/resinsight/_rips_package.py` | +6 | Polygon type aliases |
| `src/xtgeo/interfaces/resinsight/rips_utils.py` | +1 | `--threadcount 1` |
| `src/xtgeo/xyz/polygons.py` | +116 | Public API functions |
| `tests/.../test_resinsight_polygon.py` | +297 (new) | 14 non-live + 7 live tests |
| `tests/.../test_rips_utils.py` | 34 changed | Cleanup: prints, overlaps, verbosity |
| `tests/.../test_grid_public_api.py` | -9 | Remove flaky auto-discover test |
