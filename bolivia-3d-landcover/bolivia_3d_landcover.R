# 3D Land Cover Map of Bolivia
# Adapted from the Bosnia & Herzegovina tutorial workflow
# (giscoR borders + Esri/Impact Observatory 10m LULC + elevatr DEM + rayshader)

# 1. PACKAGES
#----------------

libs <- c(
    "terra",
    "giscoR",
    "sf",
    "tidyverse",
    "ggtern",
    "elevatr",
    "png",
    "rayshader",
    "magick"
)

installed_libraries <- libs %in% rownames(
    installed.packages()
)

if(any(installed_libraries == F)){
    install.packages(
        libs[!installed_libraries]
    )
}

invisible(
    lapply(
        libs, library, character.only = T
    )
)

# 2. COUNTRY BORDERS
#----------------

country_sf <- giscoR::gisco_get_countries(
    country = "BO",
    resolution = "1"
)

plot(sf::st_geometry(country_sf))

png("bolivia-borders.png")
plot(sf::st_geometry(country_sf))
dev.off()

# 3. DOWNLOAD ESRI LAND COVER TILES
#----------------
# Bolivia spans UTM zones 19-21 and latitude bands K-L
# (bbox roughly -69.6 to -57.5 lon, -22.9 to -9.7 lat)

urls <- c(
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/19K_20220101-20230101.tif",
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/19L_20220101-20230101.tif",
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/20K_20220101-20230101.tif",
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/20L_20220101-20230101.tif",
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/21K_20220101-20230101.tif",
    "https://lulctimeseries.blob.core.windows.net/lulctimeseriesv003/lc2022/21L_20220101-20230101.tif"
)

for(url in urls){
    destfile <- basename(url)
    if(!file.exists(destfile)){
        download.file(
            url = url,
            destfile = destfile,
            mode = "wb"
        )
    }
}

# 4. LOAD TILES
#----------------

raster_files <- list.files(
    path = getwd(),
    pattern = "20230101.tif$",
    full.names = T
)

crs <- "EPSG:4326"

for(raster in raster_files){
    out_file <- paste0(raster, "_bolivia", ".tif")
    if(file.exists(out_file)) next

    rasters <- terra::rast(raster)

    country <- country_sf |>
        sf::st_transform(
            crs = terra::crs(
                rasters
            )
        )

    # Aggregate BEFORE cropping/masking to the country boundary. A raw
    # GZD tile at 10m resolution has 5-6 billion cells, and Bolivia's
    # bounding box within a single tile still exceeds 2^31 cells --
    # terra 1.7.71's crop(..., mask=TRUE) silently corrupts output
    # above that threshold (every cell collapses to the same class).
    # aggregate() handles the full multi-billion-cell input correctly,
    # and shrinks it 25x before the country mask is ever applied.
    aggregated <- terra::aggregate(
        rasters,
        fact = 5,
        fun = "modal",
        filename = tempfile(fileext = ".tif"),
        overwrite = T
    )

    cropped <- terra::crop(
        aggregated,
        terra::vect(
            country
        ),
        snap = "in",
        mask = T,
        filename = tempfile(fileext = ".tif"),
        overwrite = T
    )

    land_cover <- terra::project(cropped, crs)

    terra::writeRaster(
        land_cover,
        out_file
    )

    rm(rasters, aggregated, cropped, land_cover)
    gc()
    terra::tmpFiles(remove = T)
}

# 5. LOAD VIRTUAL LAYER
#----------------

# Built from the known per-tile outputs rather than a directory glob --
# a glob on "_bolivia" also matches unrelated cached files (e.g. the DEM
# cache below) and silently pollutes the land-cover mosaic with them.
r_list <- paste0(raster_files, "_bolivia", ".tif")

land_cover_vrt <- terra::vrt(
    r_list,
    "bolivia_land_cover_vrt.vrt",
    overwrite = T
)

# 6. FETCH ORIGINAL COLORS
#----------------

ras <- terra::rast(
    raster_files[[1]]
)

raster_color_table <- do.call(
    data.frame,
    terra::coltab(ras)
)

head(raster_color_table)

hex_code <- ggtern::rgb2hex(
    r = raster_color_table[,2],
    g = raster_color_table[,3],
    b = raster_color_table[,4]
)

# 7. ASSIGN COLORS TO RASTER
#----------------
# Esri LULC classes: 1 Water, 2 Trees, 4 Flooded Vegetation, 5 Crops,
# 7 Built Area, 8 Bare ground, 9 Snow/Ice, 10 Clouds, 11 Rangeland
# (classes 3 and 6 are unused in this scheme)

cols <- hex_code[c(2:3, 5:6, 8:12)]

from <- c(1:2, 4:5, 7:11)
to <- t(col2rgb(cols))
land_cover_vrt <- na.omit(land_cover_vrt)

land_cover_bolivia <- terra::subst(
    land_cover_vrt,
    from = from,
    to = to,
    names = cols
)

terra::plotRGB(land_cover_bolivia)

# 8. DIGITAL ELEVATION MODEL
#----------------

# Deliberately does NOT contain "_bolivia" -- that substring is used to
# glob the land-cover tile outputs in step 5, and a DEM cache file
# matching it would get silently mixed into the land-cover mosaic.
elev_cache <- "dem_cache.tif"
elev_cache_raw <- "dem_cache_raw.tif"

# Bolivia is ~20x the area of Bosnia, so the same z=9 zoom level used in
# the original tutorial produces a ~90 million cell DEM -- far too large
# for rayshader/rgl to turn into a 3D mesh. Downsample to a workable size.
target_max_dim <- 2200

if(file.exists(elev_cache)){
    elev <- terra::rast(elev_cache)
} else {
    if(file.exists(elev_cache_raw)){
        elev_raw <- terra::rast(elev_cache_raw)
    } else {
        elev_raw <- terra::rast(
            elevatr::get_elev_raster(
                locations = country_sf,
                z = 9, clip = "locations"
            )
        )
        terra::writeRaster(
            elev_raw,
            elev_cache_raw,
            overwrite = T
        )
    }

    agg_factor <- max(
        1,
        ceiling(max(nrow(elev_raw), ncol(elev_raw)) / target_max_dim)
    )

    elev <- if(agg_factor > 1){
        terra::aggregate(elev_raw, fact = agg_factor, fun = "mean")
    } else {
        elev_raw
    }

    terra::writeRaster(
        elev,
        elev_cache,
        overwrite = T
    )
}

# Lambert azimuthal equal-area centered on Bolivia
crs_lambert <-
    "+proj=laea +lat_0=-16.68 +lon_0=-64.68 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

land_cover_bolivia_resampled_native <- terra::resample(
    x = land_cover_bolivia,
    y = terra::rast(elev),
    method = "near"
)

land_cover_bolivia_resampled <- terra::project(
    land_cover_bolivia_resampled_native,
    crs_lambert
)

terra::plotRGB(land_cover_bolivia_resampled)

img_file <- "land_cover_bolivia.png"

terra::writeRaster(
    land_cover_bolivia_resampled,
    img_file,
    overwrite = T,
    NAflag = 255
)

img <- png::readPNG(img_file)

# Download the HDRI here, well before plot_3d()/render_camera() set up
# the rgl scene -- doing it between render_camera() and
# render_highquality() (as in the original tutorial) leaves a network
# I/O gap between scene setup and the high-quality render call, which
# on this machine caused render_highquality() to fall back to a blank
# default material instead of the textured surface.
u <- "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/air_museum_playground_4k.hdr"
hdri_file <- basename(u)

if(!file.exists(hdri_file)){
    download.file(
        url = u,
        destfile = hdri_file,
        mode = "wb"
    )
}

# 9. RENDER SCENE
#----------------

# Re-read from disk rather than reusing the in-memory `elev` object --
# it was passed as a resample template earlier and terra's SpatRaster
# handles are not always safe to reuse afterward.
elev_rast <- terra::rast(elev_cache)
elev_lambert_raw <- terra::project(elev_rast, crs_lambert)

elev_lambert_file <- "dem_cache_lambert.tif"
terra::writeRaster(
    elev_lambert_raw,
    elev_lambert_file,
    overwrite = T
)
elev_lambert <- terra::rast(elev_lambert_file)

stopifnot(terra::hasValues(elev_lambert))

elmat <- rayshader::raster_to_matrix(
    elev_lambert
)

h <- nrow(elev_lambert)
w <- ncol(elev_lambert)

elmat |>
    rayshader::height_shade(
        texture = colorRampPalette(
            cols[9]
        )(256)
    ) |>
    rayshader::add_overlay(
        img,
        alphalayer = 1
    ) |>
    rayshader::plot_3d(
        elmat,
        zscale = 40,
        solid = F,
        shadow = T,
        shadow_darkness = 1,
        background = "white",
        windowsize = c(
            w / 5, h / 5
        ),
        zoom = .5,
        phi = 85,
        theta = 0
    )

rayshader::render_camera(
    zoom = .58
)

# Set BOLIVIA_RENDER_FINAL=FALSE to stop after a fast preview snapshot
# (useful for tuning zscale/camera before committing to the slow
# path-traced render below).
run_highquality <- Sys.getenv("BOLIVIA_RENDER_FINAL", "TRUE") == "TRUE"

if(!run_highquality){
    rayshader::render_snapshot("preview_bolivia.png")
    rgl::close3d()
    quit(save = "no")
}

# 10. RENDER OBJECT
#-----------------

filename <- "3d_land_cover_bolivia-dark.png"

rayshader::render_highquality(
    filename = filename,
    preview = T,
    light = F,
    environment_light = hdri_file,
    intensity_env = 1,
    rotate_env = 90,
    interactive = F,
    parallel = T,
    width = w * 1.5,
    height = h * 1.5
)

# 11. PUT EVERYTHING TOGETHER
#-----------------

legend_name <- "land_cover_legend.png"
png(legend_name)
par(family = "mono")

plot(
    NULL,
    xaxt = "n",
    yaxt = "n",
    bty = "n",
    ylab = "",
    xlab = "",
    xlim = 0:1,
    ylim = 0:1,
    xaxs = "i",
    yaxs = "i"
)
legend(
    "center",
    legend = c(
        "Water",
        "Trees",
        "Crops",
        "Built area",
        "Bare ground",
        "Snow/Ice",
        "Rangeland"
    ),
    pch = 15,
    cex = 2,
    pt.cex = 1,
    bty = "n",
    col = c(cols[c(1:2, 4:5, 6:7, 9)]),
    fill = c(cols[c(1:2, 4:5, 6:7, 9)]),
    border = "grey20"
)
dev.off()

lc_img <- magick::image_read(
    filename
)

my_legend <- magick::image_read(
    legend_name
)

my_legend_scaled <- magick::image_scale(
    magick::image_background(
        my_legend, "none"
    ), 2500
)

p <- magick::image_composite(
    magick::image_scale(
        lc_img, "x7000"
    ),
    my_legend_scaled,
    gravity = "southwest",
    offset = "+100+0"
)

magick::image_write(
    p, "3d_bolivia_land_cover_final.png"
)
