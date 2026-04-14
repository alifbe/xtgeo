import xtgeo

PORT = 43197

grid = xtgeo.grid_from_file(
    "/private/alifb/git/fmu-orion-playground/drogon/grids/simgrid.roff"
)

polygon = grid.get_boundary_polygons()

polygon.to_file("/private/alifb/test.pol")


# df = polygon.get_dataframe(copy=True)

# print (df)
# df[polygon.zname] = min(df[polygon.zname])
# polygon.set_dataframe(df)


# print (polygon.get_dataframe(copy=True))




# polygon.to_resinsight(PORT, name="POLYGON_TEST", find_last=True)