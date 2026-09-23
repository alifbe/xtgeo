"""ResInsight API helpers for polygon data via rips."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from xtgeo.common._xyz_enum import _AttrName
from xtgeo.common.log import null_logger

from ._resinsight_base import (
    _BaseResInsightDataRW,
    resolve_folder,
    select_by_name,
)
from ._rips_package import NameConflictPolicy, require_rips

if TYPE_CHECKING:
    from xtgeo.xyz.polygons import Polygons

    from ._rips_package import (
        RipsPolygonCollectionType,
        RipsPolygonType,
        RipsProjectType,
    )

logger = null_logger(__name__)
_NAME_ATTR = "polygon_collection_name"


def _validate_polygon_name(name: str) -> None:
    """Reject names that would resolve to the root collection."""
    if not isinstance(name, str) or not name.strip(" /"):
        raise ValueError("Polygon name must contain a non-whitespace, non-slash value")


def _get_polygon_collection(
    project: RipsProjectType,
) -> RipsPolygonCollectionType:
    """Return the active project's root polygon collection."""
    collections = project.descendants(require_rips().PolygonCollection)
    if not collections:
        raise RuntimeError("No PolygonCollection found in the active project")
    return collections[0]


def _find_polygon(
    collection: RipsPolygonCollectionType,
    name: str,
) -> RipsPolygonType | None:
    """Find a polygon directly in *collection* by name."""
    return select_by_name(collection.polygons(), name, find_last=False)


def _rips_polygon_to_data(polygon: Any) -> PolygonDataResInsight:
    """Convert a rips Polygon object to a :class:`PolygonDataResInsight`."""
    return PolygonDataResInsight(
        name=polygon.name,
        coordinates=[list(pt) for pt in polygon.coordinates],
    )


@dataclass(frozen=True, eq=False)
class PolygonDataResInsight:
    """Immutable data container for a single ResInsight polygon.

    Each instance corresponds to one ``rips.Polygon`` object, which holds a name
    and an ordered list of ``[x, y, z]`` coordinate triples.  When an XTGeo
    :class:`~xtgeo.xyz.polygons.Polygons` contains multiple segments (POLY_ID
    groups), each segment maps to its own :class:`PolygonDataResInsight` instance.
    """

    name: str
    coordinates: list[list[float]]

    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PolygonDataResInsight):
            return NotImplemented
        return self.name == other.name and self.coordinates == other.coordinates

    def __post_init__(self) -> None:
        if not self.coordinates:
            raise ValueError("coordinates cannot be empty")
        for i, pt in enumerate(self.coordinates):
            if len(pt) != 3:
                raise ValueError(
                    f"Each coordinate must have 3 elements [x, y, z], "
                    f"but point {i} has {len(pt)} elements"
                )

    def to_xtgeo_polygons(self) -> Polygons:
        """Convert to an XTGeo :class:`~xtgeo.xyz.polygons.Polygons` object.

        The returned object contains a single polygon segment (POLY_ID = 0).
        Z values are negated to convert from ResInsight's Z-up convention to
        XTGeo's depth-positive-down (Z_TVDSS) convention.
        """
        from xtgeo.xyz.polygons import Polygons

        coords = np.asarray(self.coordinates, dtype=np.float64)
        df = pd.DataFrame(
            {
                _AttrName.XNAME.value: coords[:, 0],
                _AttrName.YNAME.value: coords[:, 1],
                _AttrName.ZNAME.value: -coords[:, 2],
                _AttrName.PNAME.value: np.zeros(len(coords), dtype=np.int32),
            }
        )
        return Polygons(values=df, name=self.name)

    @classmethod
    def from_xtgeo_polygons(
        cls, polygons: Polygons, poly_id: int | None = None
    ) -> PolygonDataResInsight:
        """Create from a single segment in an XTGeo Polygons object.

        Z values are negated to convert from XTGeo's depth-positive-down
        (Z_TVDSS) convention to ResInsight's Z-up convention.

        Args:
            polygons: The source XTGeo :class:`~xtgeo.xyz.polygons.Polygons`.
            poly_id: The ``POLY_ID`` value identifying which segment to extract.
                Defaults to ``None``, which selects the first (lowest) segment.

        Raises:
            ValueError: If the dataframe is empty or no segment with the given
                ``poly_id`` is found.
        """
        df = polygons.get_dataframe(copy=False)
        if df.empty:
            raise ValueError(f"Polygons object '{polygons.name}' contains no data")
        if poly_id is None:
            poly_id = int(df[polygons.pname].min())
        segment = df[df[polygons.pname] == poly_id]
        if segment.empty:
            raise ValueError(
                f"No polygon segment with POLY_ID={poly_id} found in '{polygons.name}'"
            )
        coords = segment[[polygons.xname, polygons.yname, polygons.zname]].to_numpy(
            dtype=np.float64, copy=True
        )
        coords[:, 2] = -coords[:, 2]
        return cls(name=polygons.name, coordinates=coords.tolist())

    @classmethod
    def from_xtgeo_polygons_all(
        cls, polygons: Polygons, name: str | None = None
    ) -> list[PolygonDataResInsight]:
        """Create one instance per POLY_ID segment in an XTGeo Polygons object.

        Polygon names are formed as ``"{name} ({poly_id})"``.

        Z values are negated to convert from XTGeo's depth-positive-down
        (Z_TVDSS) convention to ResInsight's Z-up convention.

        Args:
            polygons: The source XTGeo :class:`~xtgeo.xyz.polygons.Polygons`.
            name: Optional base name override. Defaults to ``polygons.name``.
        """
        df = polygons.get_dataframe(copy=False)
        if df.empty:
            raise ValueError(f"Polygons object '{polygons.name}' contains no data")
        pname = polygons.pname
        if pname not in df.columns:
            raise ValueError(
                f"Polygons object '{polygons.name}' has no '{pname}' column"
            )
        xname, yname, zname = polygons.xname, polygons.yname, polygons.zname
        base_name = name if name is not None else polygons.name
        _validate_polygon_name(base_name)

        result: list[PolygonDataResInsight] = []
        for poly_id in sorted(df[pname].unique()):
            segment = df[df[pname] == poly_id]
            coords = segment[[xname, yname, zname]].to_numpy(
                dtype=np.float64, copy=True
            )
            coords[:, 2] = -coords[:, 2]
            result.append(
                cls(name=f"{base_name} ({poly_id})", coordinates=coords.tolist())
            )
        return result


class PolygonReader(_BaseResInsightDataRW):
    """Read polygon data from ResInsight using rips."""

    @staticmethod
    def _load_polygons_from(collection: Any) -> list[PolygonDataResInsight]:
        """Convert all polygons in a collection/folder to data objects."""
        return [_rips_polygon_to_data(p) for p in collection.polygons()]

    def _root_collection(self) -> RipsPolygonCollectionType:
        return _get_polygon_collection(self.get_project())

    def load(self, polygon_name: str) -> PolygonDataResInsight:
        """Load a polygon by name from the ResInsight project.

        Args:
            polygon_name: Name of the polygon to load.

        Raises:
            RuntimeError: If no polygon with ``polygon_name`` is found.
        """
        _validate_polygon_name(polygon_name)
        polygon = _find_polygon(self._root_collection(), polygon_name)
        if polygon is None:
            raise RuntimeError(f"Cannot find any polygon with name '{polygon_name}'")
        return _rips_polygon_to_data(polygon)

    def load_folder(self, folder_name: str) -> list[PolygonDataResInsight]:
        """Load all polygons from a named folder in the polygon collection.

        Args:
            folder_name: Name of the folder (sub-collection) to load from.

        Raises:
            RuntimeError: If no folder with ``folder_name`` is found.
        """
        _validate_polygon_name(folder_name)
        folder = resolve_folder(self._root_collection(), folder_name, _NAME_ATTR)
        if folder is None:
            raise RuntimeError(
                f"Cannot find any polygon folder with name '{folder_name}'"
            )
        return self._load_polygons_from(folder)

    def load_by_name(self, name: str) -> list[PolygonDataResInsight]:
        """Load polygon(s) by name, checking folders first then individual polygons.

        If a folder with ``name`` exists, all polygons from it are returned.
        Otherwise, a single polygon with that name is returned as a one-element
        list.

        Args:
            name: Name of the folder or polygon to load.

        Raises:
            RuntimeError: If no folder or polygon with ``name`` is found.
        """
        _validate_polygon_name(name)
        collection = self._root_collection()
        folder = resolve_folder(collection, name, _NAME_ATTR)
        if folder is not None:
            return self._load_polygons_from(folder)
        polygon = _find_polygon(collection, name)
        if polygon is not None:
            return [_rips_polygon_to_data(polygon)]
        raise RuntimeError(
            f"Cannot find any polygon or polygon folder with name '{name}'"
        )

    def load_all(self) -> list[PolygonDataResInsight]:
        """Load all polygons from the root of the polygon collection.

        Does not recurse into sub-folders.
        """
        return self._load_polygons_from(self._root_collection())


class PolygonWriter(_BaseResInsightDataRW):
    """Write polygon data to ResInsight using rips."""

    def _upsert_polygon(self, collection: Any, data: PolygonDataResInsight) -> None:
        """Create or update a polygon in a rips collection or folder."""
        existing = _find_polygon(collection, data.name)
        if existing is not None:
            logger.debug("Updating polygon '%s'.", data.name)
            existing.coordinates = data.coordinates
            existing.update()
        else:
            logger.debug("Creating polygon '%s'.", data.name)
            collection.create_polygon(
                name=data.name,
                coordinates=data.coordinates,
                on_name_conflict=NameConflictPolicy.FAIL,
            )

    def save(self, data: PolygonDataResInsight) -> None:
        """Save a single polygon to the root of the polygon collection.

        If a polygon with the same name already exists, its coordinates are
        updated in place. Otherwise a new polygon is created.

        Args:
            data: The polygon data to save.
        """
        try:
            self._upsert_polygon(_get_polygon_collection(self.get_project()), data)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save ResInsight polygon data: {exc}"
            ) from exc

    def save_to_folder(
        self,
        folder_name: str,
        data_list: list[PolygonDataResInsight],
    ) -> None:
        """Save multiple polygons into a named folder in the polygon collection.

        A folder is created (or reused) with ``folder_name``, and each polygon
        is placed inside it. Existing polygons with matching names are updated.

        Args:
            folder_name: Name of the folder (sub-collection) to write into.
            data_list: List of polygon data to save inside the folder.
        """
        try:
            _validate_polygon_name(folder_name)
            folder = resolve_folder(
                _get_polygon_collection(self.get_project()),
                folder_name,
                _NAME_ATTR,
                create=True,
            )
            expected_names = {data.name for data in data_list}
            existing_names = {polygon.name for polygon in folder.polygons()}
            stale_names = existing_names - expected_names
            if stale_names:
                stale = ", ".join(sorted(stale_names))
                raise RuntimeError(
                    f"Folder '{folder_name}' contains polygons not present in "
                    f"the export: {stale}"
                )
            for data in data_list:
                self._upsert_polygon(folder, data)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save ResInsight polygon data to folder "
                f"'{folder_name}': {exc}"
            ) from exc
