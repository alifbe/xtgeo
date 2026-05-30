"""Shared base classes for ResInsight data readers/writers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xtgeo.common.log import null_logger

from ._rips_package import NameConflictPolicy, require_rips
from .rips_utils import RipsApiUtils

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    from ._rips_package import (
        ResInsightInstanceOrPortType,
        RipsCaseType,
        RipsInstanceType,
        RipsPolygonCollectionType,
        RipsPolygonType,
        RipsProjectType,
    )

logger = null_logger(__name__)


def select_by_name(
    items: Iterable[Any],
    name: str,
    find_last: bool = True,
    name_attr: str = "name",
) -> Any | None:
    """Select the item from *items* whose *name_attr* equals *name*.

    Shared lookup helper for the ResInsight readers/writers, which pick a
    named object (case, surface, polygon, folder, ...) from an iterable.
    Returns the last match when *find_last* is ``True`` (default), else the
    first, or ``None`` when nothing matches.
    """
    selected = None
    for item in items:
        if getattr(item, name_attr, None) == name:
            selected = item
            if not find_last:
                break
    return selected


def resolve_folder(
    root: Any,
    folder_path: str,
    name_attr: str,
    create: bool = False,
) -> Any | None:
    """Resolve a ``/``-separated folder path below the *root* collection.

    Works with any ResInsight collection exposing ``sub_collections()`` and
    ``add_folder()`` (e.g. ``SurfaceCollection``, ``PolygonCollection``). An
    empty *folder_path* is *root* itself. Missing segments are created when
    *create* is ``True``, otherwise ``None`` is returned.
    """
    folder = root

    for segment in filter(None, folder_path.split("/")):
        sub = select_by_name(
            folder.sub_collections(), segment, find_last=False, name_attr=name_attr
        )
        if sub is None:
            if not create:
                return None
            # Folders are never overwritten; that would delete their content.
            # require_rips() gives an actionable upgrade message instead of an
            # AttributeError if rips is missing/too old for NameConflictPolicy.
            require_rips()
            sub = folder.add_folder(
                folder_name=segment, on_name_conflict=NameConflictPolicy.FAIL
            )
        folder = sub

    return folder


def validate_case(case: str | RipsCaseType) -> None:
    """Validate a case argument, raising :class:`TypeError` if it is invalid.

    A valid case is either a case name (``str``) or a ``rips`` Case object
    exposing a string ``name`` attribute. This is a cheap, dependency-free guard
    so callers can fail fast before doing expensive work (e.g. extracting grid
    data) or before creating a case with an empty name.

    Args:
        case: A case name (str) or a ``rips`` Case object.

    Raises:
        TypeError: If *case* is neither a string nor an object exposing a string
            ``name`` attribute.
    """
    if isinstance(case, str):
        return
    if not isinstance(getattr(case, "name", None), str):
        raise TypeError(
            "case must be a case name (str) or a rips Case object with a "
            f"'name' attribute, but got {type(case).__name__}"
        )


class _BaseResInsightDataRW:
    """Common init and lookup utilities for ResInsight read/write operations."""

    def __init__(
        self,
        instance_or_port: ResInsightInstanceOrPortType | None = None,
    ) -> None:
        self.instance_or_port = instance_or_port
        self._ripsapi_utils: RipsApiUtils | None = None

    def get_ripsapi_utils(self) -> RipsApiUtils:
        """Create and cache RipsApiUtils."""
        if self._ripsapi_utils is None:
            self._ripsapi_utils = RipsApiUtils(self.instance_or_port)
        return self._ripsapi_utils

    def get_instance(self) -> RipsInstanceType:
        return self.get_ripsapi_utils().instance

    def get_project(self) -> RipsProjectType:
        """Get the active ResInsight project."""
        return self.get_ripsapi_utils().project

    def resolve_case(
        self, case: str | RipsCaseType, find_last: bool = True
    ) -> RipsCaseType | None:
        """Resolve a target case from either a case object or a case name.

        Args:
            case: Either a ``rips`` case object (returned as-is) or the case name
                to look up in the project (see :meth:`get_case`).
            find_last: When *case* is a name and several cases share it, select the
                last match if ``True`` (default), otherwise the first.

        Raises:
            TypeError: If *case* is neither a string nor a rips Case object
                exposing a string ``name`` attribute.
        """
        if isinstance(case, str):
            return self.get_case(case_name=case, find_last=find_last)
        validate_case(case)
        return case

    def get_case(self, case_name: str, find_last: bool = True) -> RipsCaseType | None:
        """Resolve target case from project by its name.

        The case name is not unique in ResInsight, by default it will find the last
        matching case name.
        """
        cases = self.get_project().cases()  # type: ignore[attr-defined]
        logger.debug(
            "Found %d cases in project: %s",
            len(cases),
            [case.name for case in cases],
        )
        if not cases:
            return None

        return select_by_name(cases, case_name, find_last=find_last)

    def get_polygon_collection(self) -> RipsPolygonCollectionType:
        """Return the first PolygonCollection in the active ResInsight project.

        Raises:
            RuntimeError: If no PolygonCollection is present in the project.
        """
        collections = self.get_project().descendants(
            require_rips().PolygonCollection
        )
        if not collections:
            raise RuntimeError(
                "No PolygonCollection found in the active ResInsight project"
            )
        logger.debug("Found %d PolygonCollection(s) in project", len(collections))
        return collections[0]

    @staticmethod
    def find_polygon(
        collection: RipsPolygonCollectionType, name: str, find_last: bool
    ) -> RipsPolygonType | None:
        """Return the first or last polygon with the given name, or ``None``.

        Args:
            collection: The ``rips.PolygonCollection`` to search.
            name: Exact polygon name to match.
            find_last: If ``True``, continue scanning after a match so the last
                match is returned; if ``False``, stop at the first match.
        """
        return select_by_name(collection.polygons(), name, find_last=find_last)

    @staticmethod
    def find_folder(
        collection: Any, name: str, name_attr: str = "polygon_collection_name"
    ) -> Any | None:
        """Return the first sub-collection (folder) with the given name, or ``None``.

        Works with any ResInsight collection that supports ``sub_collections()``
        (e.g. ``PolygonCollection``, ``SurfaceCollection``).

        Args:
            collection: The parent collection to search.
            name: Exact folder name to match.
            name_attr: Attribute on the sub-collection that holds its name.
                Defaults to ``"polygon_collection_name"``.
        """
        return select_by_name(
            collection.sub_collections(),  # type: ignore[attr-defined]
            name,
            find_last=False,
            name_attr=name_attr,
        )

    @staticmethod
    def get_or_create_folder(
        collection: Any, name: str, name_attr: str = "polygon_collection_name"
    ) -> Any:
        """Find an existing folder or create a new one.

        Works with any ResInsight collection that supports ``sub_collections()``
        and ``add_folder()`` (e.g. ``PolygonCollection``, ``SurfaceCollection``).

        Args:
            collection: The parent collection.
            name: Name for the sub-collection folder.
            name_attr: Attribute on the sub-collection that holds its name.
                Defaults to ``"polygon_collection_name"``.

        Returns:
            The existing or newly created sub-collection.
        """
        return resolve_folder(collection, name, name_attr, create=True)
