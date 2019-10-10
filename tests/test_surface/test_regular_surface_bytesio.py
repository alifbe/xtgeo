# coding: utf-8
from __future__ import division, absolute_import
from __future__ import print_function

import os
import os.path
import io

import xtgeo
from xtgeo.common import XTGeoDialog
import test_common.test_xtg as tsetup

xtg = XTGeoDialog()
logger = xtg.basiclogger(__name__)

if not xtg.testsetup():
    raise SystemExit

TMPD = xtg.tmpdir
TPATH = xtg.testpath

XTGSHOW = False
if "XTG_SHOW" in os.environ:
    XTGSHOW = True

# =============================================================================
# Do tests
# =============================================================================

TESTSET1 = "../xtgeo-testdata/surfaces/reek/1/topreek_rota.gri"


def test_irapbin_import_bytesio():
    """Import Irap binary via bytesIO"""
    logger.info("Import and export...")

    with open(TESTSET1, "rb") as fin:
        stream = io.BytesIO(fin.read())
    # print(dir(stream))
    # print(type(stream.getvalue()))

    # xsurf = xtgeo.RegularSurface(stream)
    # assert xsurf.ncol == 1264
    # assert xsurf.nrow == 2010
    # tsetup.assert_almostequal(xsurf.values[11, 0], 1678.89733887, 0.00001)
    # tsetup.assert_almostequal(xsurf.values[1263, 2009], 1893.75, 0.01)
    # xsurf.describe()
