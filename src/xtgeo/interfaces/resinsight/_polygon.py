"""ResInsight API helpers for polygon data via rips."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from xtgeo.common._xyz_enum import _AttrName
from xtgeo.common.log import null_logger

from ._resinsight_base import _BaseResInsightDataRW

if TYPE_CHECKING:
    from xtgeo.xyz.polygons import Polygons

    from ._rips_package import ResInsightInstanceOrPortType

logger = null_logger(__name__)


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
        coords = segment[
            [polygons.xname, polygons.yname, polygons.zname]
        ].to_numpy(dtype=np.float64, copy=True)
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
        pname = polygons.pname
        xname, yname, zname = polygons.xname, polygons.yname, polygons.zname
        base_name = name if name is not None else polygons.name

        result: list[PolygonDataResInsight] = []
        for poly_id in sorted(df[pname].unique()):
            segment = df[df[pname] == poly_id]
            coords = segment[[xname, yname, zname]].values.copy()
            coords[:, 2] = -coords[:, 2]
            result.append(
                cls(name=f"{base_name} ({poly_id})", coordinates=coords.tolist())
            )
        return result


class PolygonReader(_BaseResInsightDataRW):
    """Read polygon data from ResInsight using rips."""

    def __init__(
        self,
        instance_or_port: ResInsightInstanceOrPortType | None = None,
    ) -> None:
        super().__init__(instance_or_port)

    def _load_polygons_from(
        self, collection: Any
    ) -> list[PolygonDataResInsight]:
        """Convert all polygons in a collection/folder to data objects."""
        return [_rips_polygon_to_data(p) for p in collection.polygons()]

    def load(self, polygon_name: str, find_last: bool = True) -> PolygonDataResInsight:
        """Load a polygon by name from the ResInsight project.

        Args:
            polygon_name: Name of the polygon to load.
            find_last: When multiple polygons share the same name, select the
                last match if ``True`` (default) or the first match if ``False``.

        Raises:
            RuntimeError: If no polygon with ``polygon_name`` is found.
        """
        collection = self.get_polygon_collection()
        polygon = self.find_polygon(collection, polygon_name, find_last)
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
        collection = self.get_polygon_collection()
        folder = self.find_folder(collection, folder_name)
        if folder is None:
            raise RuntimeError(
                f"Cannot find any polygon folder with name '{folder_name}'"
            )
        return self._load_polygons_from(folder)

    def load_by_name(
        self, name: str, find_last: bool = True
    ) -> list[PolygonDataResInsight]:
        """Load polygon(s) by name, checking folders first then individual polygons.

        If a folder with ``name`` exists, all polygons from it are returned.
        Otherwise, a single polygon with that name is returned as a one-element
        list.

        Args:
            name: Name of the folder or polygon to load.
            find_last: When looking up a single polygon and multiple polygons
                share the same name, select the last match if ``True`` (default)
                or the first match if ``False``.

        Raises:
            RuntimeError: If no folder or polygon with ``name`` is found.
        """
        collection = self.get_polygon_collection()
        folder = self.find_folder(collection, name)
        if folder is not None:
            return self._load_polygons_from(folder)
        polygon = self.find_polygon(collection, name, find_last)
        if polygon is not None:
            return [_rips_polygon_to_data(polygon)]
        raise RuntimeError(
            f"Cannot find any polygon or polygon folder with name '{name}'"
        )

    def load_all(self) -> list[PolygonDataResInsight]:
        """Load all polygons from the root of the polygon collection.

        Does not recurse into sub-folders.
        """
        return self._load_polygons_from(self.get_polygon_collection())


class PolygonWriter(_BaseResInsightDataRW):
    """Write polygon data to ResInsight using rips."""

    def __init__(
        self,
        instance_or_port: ResInsightInstanceOrPortType | None = None,
    ) -> None:
        super().__init__(instance_or_port)

    def _upsert_polygon(
        self, collection: Any, data: PolygonDataResInsight, find_last: bool = True
    ) -> None:
        """Create or update a polygon in a rips collection or folder."""
        existing = self.find_polygon(collection, data.name, find_last)
        if existing is not None:
            logger.debug("Updating polygon '%s'.", data.name)
            existing.coordinates = data.coordinates
            existing.update()
        else:
            logger.debug("Creating polygon '%s'.", data.name)
            collection.create_polygon(name=data.name, coordinates=data.coordinates)

    def save(self, data: PolygonDataResInsight, find_last: bool = True) -> None:
        """Save a single polygon to the root of the polygon collection.

        If a polygon with the same name already exists, its coordinates are
        updated in place. Otherwise a new polygon is created.

        Args:
            data: The polygon data to save.
            find_last: When multiple polygons share the same name, replace the
                last match if ``True`` (default) or the first match if ``False``.
        """
        try:
            self._upsert_polygon(self.get_polygon_collection(), data, find_last)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save ResInsight polygon data: {exc}"
            ) from exc

    def save_to_folder(
        self, folder_name: str, data_list: list[PolygonDataResInsight]
    ) -> None:
        """Save multiple polygons into a named folder in the polygon collection.

        A folder is created (or reused) with ``folder_name``, and each polygon
        is placed inside it. Existing polygons with matching names are updated.

        Args:
            folder_name: Name of the folder (sub-collection) to write into.
            data_list: List of polygon data to save inside the folder.
        """
        try:
            collection = self.get_polygon_collection()
            folder = self.get_or_create_folder(collection, folder_name)
            for data in data_list:
                self._upsert_polygon(folder, data)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save ResInsight polygon data to folder "
                f"'{folder_name}': {exc}"
            ) from exc
