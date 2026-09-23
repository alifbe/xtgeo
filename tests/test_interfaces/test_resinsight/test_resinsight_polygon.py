"""Tests for the ResInsight polygon interface.

Covers:
- :class:`PolygonDataResInsight` data container (validation, eq, roundtrip)
- :meth:`PolygonDataResInsight.to_xtgeo_polygons`
- :meth:`PolygonDataResInsight.from_xtgeo_polygons`
- :meth:`PolygonDataResInsight.from_xtgeo_polygons_all`
- :class:`PolygonReader` and :class:`PolygonWriter` (live ResInsight tests)
"""

from __future__ import annotations

import pandas as pd
import pytest
from numpy.testing import assert_allclose

import xtgeo
from xtgeo.interfaces.resinsight._polygon import (
    PolygonDataResInsight,
    PolygonReader,
    PolygonWriter,
    _find_polygon,
)

# ---------------------------------------------------------------------------
# PolygonDataResInsight – construction and validation
# ---------------------------------------------------------------------------


def test_empty_coordinates_raises():
    with pytest.raises(ValueError, match="coordinates cannot be empty"):
        PolygonDataResInsight(name="p", coordinates=[])


def test_bad_coordinate_length_raises():
    with pytest.raises(ValueError, match="point 1 has 2 elements"):
        PolygonDataResInsight(name="p", coordinates=[[0.0, 0.0, 0.0], [1.0, 2.0]])


def test_eq_and_ne():
    coords = [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]
    a = PolygonDataResInsight(name="p", coordinates=coords)
    b = PolygonDataResInsight(name="p", coordinates=coords)
    assert a == b
    assert a != PolygonDataResInsight(name="other", coordinates=coords)
    assert a != PolygonDataResInsight(name="p", coordinates=[[1.0, 0.0, 0.0]])
    assert a.__eq__("string") is NotImplemented


def test_unhashable():
    a = PolygonDataResInsight(name="p", coordinates=[[0.0, 0.0, 0.0]])
    with pytest.raises(TypeError):
        hash(a)


def test_find_polygon():
    class Collection:
        @staticmethod
        def polygons():
            return [
                type("Polygon", (), {"name": "same", "value": 1})(),
                type("Polygon", (), {"name": "other", "value": 2})(),
            ]

    collection = Collection()
    assert _find_polygon(collection, "same").value == 1
    assert _find_polygon(collection, "missing") is None


# ---------------------------------------------------------------------------
# to_xtgeo_polygons
# ---------------------------------------------------------------------------


def test_to_xtgeo_polygons():
    # ResInsight coordinates use Z-up: -1000 means 1000m below sea level
    coords = [[100.0, 200.0, -1000.0], [110.0, 210.0, -1010.0]]
    data = PolygonDataResInsight(name="fault", coordinates=coords)
    poly = data.to_xtgeo_polygons()

    assert isinstance(poly, xtgeo.Polygons)
    assert poly.name == "fault"
    df = poly.get_dataframe()
    assert len(df) == 2
    assert list(df["POLY_ID"].unique()) == [0]
    assert_allclose(df["X_UTME"].values, [100.0, 110.0])
    assert_allclose(df["Y_UTMN"].values, [200.0, 210.0])
    # XTGeo uses depth-positive-down, so Z is negated
    assert_allclose(df["Z_TVDSS"].values, [1000.0, 1010.0])


# ---------------------------------------------------------------------------
# from_xtgeo_polygons
# ---------------------------------------------------------------------------


def _make_polygons(n_segments: int = 1, pts_per_seg: int = 3) -> xtgeo.Polygons:
    """Helper: build a Polygons object with n_segments segments."""
    rows = []
    for seg in range(n_segments):
        for i in range(pts_per_seg):
            rows.append(
                {
                    "X_UTME": float(seg * 100 + i),
                    "Y_UTMN": float(seg * 100 + i + 10),
                    "Z_TVDSS": float(-seg * 10 - i),
                    "POLY_ID": seg,
                }
            )
    df = pd.DataFrame(rows)
    return xtgeo.Polygons(values=df, name="test_poly")


def test_from_xtgeo_polygons_default_poly_id():
    """None default selects the first (lowest) POLY_ID."""
    poly = _make_polygons(n_segments=2)
    data = PolygonDataResInsight.from_xtgeo_polygons(poly)
    assert data.name == "test_poly"
    assert len(data.coordinates) == 3
    assert_allclose(data.coordinates[0], [0.0, 10.0, 0.0])


def test_from_xtgeo_polygons_default_selects_first_when_not_zero():
    """When POLY_ID numbering starts at a value other than 0 the default still works."""
    rows = [
        {"X_UTME": 5.0, "Y_UTMN": 15.0, "Z_TVDSS": -5.0, "POLY_ID": 1},
        {"X_UTME": 6.0, "Y_UTMN": 16.0, "Z_TVDSS": -6.0, "POLY_ID": 2},
    ]
    poly = xtgeo.Polygons(values=pd.DataFrame(rows), name="well_poly")
    data = PolygonDataResInsight.from_xtgeo_polygons(poly)
    assert len(data.coordinates) == 1
    # XTGeo Z_TVDSS=-5.0 becomes ResInsight Z-up=5.0 (negated)
    assert_allclose(data.coordinates[0], [5.0, 15.0, 5.0])


def test_from_xtgeo_polygons_explicit_poly_id():
    poly = _make_polygons(n_segments=2)
    data = PolygonDataResInsight.from_xtgeo_polygons(poly, poly_id=1)
    assert len(data.coordinates) == 3
    assert_allclose(data.coordinates[0], [100.0, 110.0, 10.0])


def test_from_xtgeo_polygons_missing_poly_id_raises():
    poly = _make_polygons(n_segments=1)
    with pytest.raises(ValueError, match="POLY_ID=99"):
        PolygonDataResInsight.from_xtgeo_polygons(poly, poly_id=99)


# ---------------------------------------------------------------------------
# from_xtgeo_polygons_all
# ---------------------------------------------------------------------------


def test_from_xtgeo_polygons_all():
    """Naming uses '{name} ({poly_id})' format, one entry per segment."""
    single = _make_polygons(n_segments=1)
    result = PolygonDataResInsight.from_xtgeo_polygons_all(single)
    assert len(result) == 1
    assert result[0].name == "test_poly (0)"

    multi = _make_polygons(n_segments=3)
    result = PolygonDataResInsight.from_xtgeo_polygons_all(multi)
    assert len(result) == 3
    assert [r.name for r in result] == [
        "test_poly (0)",
        "test_poly (1)",
        "test_poly (2)",
    ]


def test_from_xtgeo_polygons_all_preserves_coordinates():
    poly = _make_polygons(n_segments=2, pts_per_seg=4)
    result = PolygonDataResInsight.from_xtgeo_polygons_all(poly)
    for item in result:
        assert len(item.coordinates) == 4
        for pt in item.coordinates:
            assert len(pt) == 3


# ---------------------------------------------------------------------------
# Roundtrip: PolygonDataResInsight → XTGeo Polygons → PolygonDataResInsight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "coords",
    [
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
        [[100.0, 200.0, -500.0], [110.0, 210.0, -510.0]],
        [[0.0, 0.0, 1000.0]],
    ],
    ids=["triangle", "two-points", "single-point"],
)
def test_roundtrip_via_xtgeo(coords: list[list[float]]):
    original = PolygonDataResInsight(name="rt", coordinates=coords)
    poly = original.to_xtgeo_polygons()
    recovered = PolygonDataResInsight.from_xtgeo_polygons(poly)
    assert recovered.name == original.name
    assert_allclose(recovered.coordinates, original.coordinates)


# ---------------------------------------------------------------------------
# Live ResInsight tests (require @pytest.mark.requires_resinsight)
# ---------------------------------------------------------------------------


@pytest.mark.requires_resinsight
def test_polygon_writer_updates_existing(resinsight_instance):
    """PolygonWriter.save creates and then updates a polygon."""
    initial = PolygonDataResInsight(
        name="UPDATE_POLY", coordinates=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    )
    PolygonWriter(resinsight_instance).save(initial)

    updated_coords = [[5.0, 5.0, 5.0], [6.0, 5.0, 5.0], [6.0, 6.0, 5.0]]
    updated = PolygonDataResInsight(name="UPDATE_POLY", coordinates=updated_coords)
    PolygonWriter(resinsight_instance).save(updated)

    loaded = PolygonReader(resinsight_instance).load("UPDATE_POLY")
    assert_allclose(loaded.coordinates, updated_coords)


@pytest.mark.requires_resinsight
def test_polygon_reader_missing_raises(resinsight_instance):
    with pytest.raises(RuntimeError, match="Cannot find any polygon with name"):
        PolygonReader(resinsight_instance).load("DOES_NOT_EXIST_XYZ")


@pytest.mark.requires_resinsight
def test_roundtrip_resinsight(resinsight_instance):
    """Full ResInsight roundtrip: write and read back preserves data exactly."""
    coords = [
        [100.0, 200.0, -1000.0],
        [200.0, 200.0, -1000.0],
        [200.0, 300.0, -1000.0],
        [100.0, 200.0, -1000.0],
    ]
    data = PolygonDataResInsight(name="ROUNDTRIP_POLY", coordinates=coords)
    PolygonWriter(resinsight_instance).save(data)
    loaded = PolygonReader(resinsight_instance).load("ROUNDTRIP_POLY")
    assert loaded == data


# ---------------------------------------------------------------------------
# Public API: polygons_from_resinsight / Polygons.to_resinsight
# ---------------------------------------------------------------------------


@pytest.mark.requires_resinsight
def test_public_api_to_resinsight(resinsight_instance):
    """Single-segment polygon is saved directly with the Polygons name."""
    df = pd.DataFrame(
        {
            "X_UTME": [50.0, 60.0, 60.0],
            "Y_UTMN": [50.0, 50.0, 60.0],
            "Z_TVDSS": [-500.0, -500.0, -500.0],
            "POLY_ID": [0, 0, 0],
        }
    )
    poly = xtgeo.Polygons(values=df, name="TO_RESINSIGHT")
    poly.to_resinsight(resinsight_instance)

    loaded = xtgeo.polygons_from_resinsight(resinsight_instance, "TO_RESINSIGHT")
    df_loaded = loaded.get_dataframe()
    assert len(df_loaded) == 3
    assert_allclose(df_loaded["X_UTME"].values, [50.0, 60.0, 60.0])


@pytest.mark.requires_resinsight
def test_public_api_to_resinsight_multi_segment(resinsight_instance):
    """Multi-segment polygon is saved as a folder with individual polygons inside."""
    df = pd.DataFrame(
        {
            "X_UTME": [10.0, 20.0, 30.0, 40.0, 50.0],
            "Y_UTMN": [100.0, 200.0, 300.0, 400.0, 500.0],
            "Z_TVDSS": [-10.0, -20.0, -30.0, -40.0, -50.0],
            "POLY_ID": [0, 0, 0, 1, 1],
        }
    )
    poly = xtgeo.Polygons(values=df, name="MULTI_SEG")
    poly.to_resinsight(resinsight_instance)

    loaded = xtgeo.polygons_from_resinsight(resinsight_instance, "MULTI_SEG")
    df_loaded = loaded.get_dataframe()
    assert loaded.name == "MULTI_SEG"
    assert sorted(df_loaded["POLY_ID"].unique()) == [0, 1]
    seg0 = df_loaded[df_loaded["POLY_ID"] == 0]
    seg1 = df_loaded[df_loaded["POLY_ID"] == 1]
    assert len(seg0) == 3
    assert len(seg1) == 2
    assert_allclose(seg0["X_UTME"].values, [10.0, 20.0, 30.0])
    assert_allclose(seg1["X_UTME"].values, [40.0, 50.0])


@pytest.mark.requires_resinsight
def test_polygon_writer_save_to_folder(resinsight_instance):
    """PolygonWriter.save_to_folder creates polygons inside a named folder."""
    coords_a = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    coords_b = [[5.0, 5.0, 5.0], [6.0, 6.0, 6.0], [7.0, 7.0, 7.0]]
    data_list = [
        PolygonDataResInsight(name="MY_FOLDER (0)", coordinates=coords_a),
        PolygonDataResInsight(name="MY_FOLDER (1)", coordinates=coords_b),
    ]
    writer = PolygonWriter(resinsight_instance)
    writer.save_to_folder("MY_FOLDER", data_list)

    loaded = PolygonReader(resinsight_instance).load_folder("MY_FOLDER")
    assert len(loaded) == 2
    assert loaded[0].name == "MY_FOLDER (0)"
    assert loaded[1].name == "MY_FOLDER (1)"
    assert_allclose(loaded[0].coordinates, coords_a)
    assert_allclose(loaded[1].coordinates, coords_b)
