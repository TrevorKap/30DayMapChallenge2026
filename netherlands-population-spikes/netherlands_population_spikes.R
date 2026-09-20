#######################################################
#                 Making crisp spike maps with R
#                 Milos Popovic
#                 2023/03/12
#                 Adapted for the Netherlands
#                 (adds a country boundary + red palette)
########################################################
# install rayshader & rayrender from the source
# devtools::install_github("tylermorganwall/rayshader")
# devtools::install_github("tylermorganwall/rayrender")

# libraries we need
libs <- c(
    "tidyverse", "R.utils",
    "httr", "sf", "stars",
    "rayshader", "giscoR"
)

# install missing libraries
installed_libs <- libs %in% rownames(installed.packages())
if (any(installed_libs == F)) {
    install.packages(libs[!installed_libs])
}

# load libraries
invisible(lapply(libs, library, character.only = T))

# Off: everything below is reprojected into a planar CRS anyway, and
# the s2 (spherical) backend has a known crash manipulating raw sfc
# ring structures directly (used below to strip interior holes/lakes
# out of the country boundary before drawing it).
sf::sf_use_s2(FALSE)

### 1. DOWNLOAD & UNZIP DATA
### ------------------------
url <-
    "https://geodata-eu-central-1-kontur-public.s3.amazonaws.com/kontur_datasets/kontur_population_NL_20220630.gpkg.gz"
file_name <- "netherlands-population.gpkg.gz"

get_population_data <- function() {
    res <- httr::GET(
        url,
        write_disk(file_name, overwrite = T),
        progress()
    )

    R.utils::gunzip(file_name, remove = F, overwrite = T)
}

get_population_data()

### 2. LOAD DATA
### -------------
load_file_name <- gsub(".gz", "", file_name)

# Lambert Azimuthal Equal Area, recentered on the Netherlands
crsLAEA <- "+proj=laea +lat_0=52.1 +lon_0=5.3 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

pop_sf_raw <- sf::st_read(load_file_name) |>
    sf::st_transform(crs = crsLAEA)

### 2b. COUNTRY BOUNDARY
### --------------------
# High-resolution national boundary from GISCO, reprojected to match
country_sf <- giscoR::gisco_get_countries(
    country = "NL",
    resolution = "01"
) |>
    sf::st_transform(crs = crsLAEA)

png("netherlands-borders.png")
plot(sf::st_geometry(country_sf))
dev.off()

# Clip the population hexes to the actual national boundary --
# Kontur's per-country extract includes hexes that straddle the border,
# which would otherwise bleed slightly outside the coastline/land border.
pop_sf <- sf::st_intersection(
    pop_sf_raw,
    sf::st_union(country_sf)
)

head(pop_sf)
ggplot() +
    geom_sf(
        data = pop_sf,
        color = "grey10", fill = "grey10"
    )

### 3. SHP TO RASTER
### ----------------

bb <- sf::st_bbox(pop_sf)

get_raster_size <- function() {
    height <- sf::st_distance(
        sf::st_point(c(bb[["xmin"]], bb[["ymin"]])),
        sf::st_point(c(bb[["xmin"]], bb[["ymax"]]))
    )
    width <- sf::st_distance(
        sf::st_point(c(bb[["xmin"]], bb[["ymin"]])),
        sf::st_point(c(bb[["xmax"]], bb[["ymin"]]))
    )

    if (height > width) {
        height_ratio <- 1
        width_ratio <- width / height
    } else {
        width_ratio <- 1
        height_ratio <- height / width
    }

    return(list(width_ratio, height_ratio))
}
width_ratio <- get_raster_size()[[1]]
height_ratio <- get_raster_size()[[2]]

# Grid resolution for the population raster itself. Kept coarser than a
# typical top-down spike map: at the low, oblique camera angle used
# below, a 3000px-wide grid over a country as small as the Netherlands
# produces spikes only a fraction of a screen pixel wide, which the
# renderer's anti-aliasing washes out to grey/white against the
# background instead of showing red. A coarser grid gives each spike a
# stable footprint several pixels wide even when viewed from the side.
size <- 900
width <- round((size * width_ratio), 0)
height <- round((size * height_ratio), 0)

# Final output image resolution -- kept independent of the data grid
# above so the render is still crisp/high-res despite the coarser mesh
output_size <- 2400
output_width <- round((output_size * width_ratio), 0)
output_height <- round((output_size * height_ratio), 0)

get_population_raster <- function() {
    pop_rast <- stars::st_rasterize(
        pop_sf |>
            dplyr::select(population, geom),
        nx = width, ny = height
    )

    return(pop_rast)
}

pop_rast <- get_population_raster()
plot(pop_rast)

pop_mat <- pop_rast |>
    as("Raster") |>
    rayshader::raster_to_matrix()

### 3b. FILL DATA GAPS *INSIDE* THE COUNTRY (water bodies, hex seams)
### ------------------------------------------------------------------
# Kontur has no population hexes over water, so lakes/coastal seams
# rasterize to NA and, without this fix, punch through to the plain
# background color -- reading as random white speckle. Cells outside
# the country entirely should stay NA (transparent, so only the
# country's own silhouette shows); only interior gaps get filled to
# a 0-population baseline.
#
# st_rasterize(..., template = <stars object>) uses the template's OWN
# attribute values as the background for any cell the new geometry
# doesn't cover -- it does NOT reset untouched cells to NA. Passing
# pop_rast directly as a template means every uncovered cell silently
# inherits its population value instead of becoming NA/0 as intended.
# Wipe a copy of the grid to NA first so it only supplies the grid
# geometry (extent/resolution/CRS), not real values.
blank_template <- pop_rast["population"]
blank_template[[1]][] <- NA_real_

country_mask_rast <- stars::st_rasterize(
    country_sf |> sf::st_geometry() |> sf::st_sf(value = 1, geometry = _),
    template = blank_template
)
country_mask_mat <- country_mask_rast |>
    as("Raster") |>
    rayshader::raster_to_matrix()

pop_mat[is.na(pop_mat) & !is.na(country_mask_mat)] <- 0

### 3c. BOUNDARY LINE, RASTERIZED ONTO THE SAME GRID
### -------------------------------------------------
# The Netherlands' GISCO polygon has several interior rings (IJsselmeer,
# Markermeer, and other large lakes are holes in the mainland part, not
# separate features). st_boundary() on the polygon as-is traces those
# lake shorelines too -- buffered and rasterized, that paints dense
# white line-work across the water-rich central Netherlands, which is
# exactly the population-dense area and reads as a "whiteout" over the
# tallest spikes. Strip interior rings first so only the true coastline
# is drawn.
strip_holes <- function(geom) {
    sf::st_sfc(
        lapply(geom, function(part) {
            if (inherits(part, "MULTIPOLYGON")) {
                sf::st_multipolygon(lapply(unclass(part), function(p) p[1]))
            } else if (inherits(part, "POLYGON")) {
                sf::st_polygon(unclass(part)[1])
            } else {
                part
            }
        }),
        crs = sf::st_crs(geom)
    )
}

# Rasterizing onto the same blank template as the country mask above
# guarantees the border lines up pixel-for-pixel with the population
# surface below, WITHOUT leaking population values into the (vast
# majority of) cells the thin border line doesn't cover -- that leak
# was the actual cause of the whole-map whiteout: with a populated
# template, nearly every non-border cell inherited a real (non-NA)
# population value, so `is.na(border_mat)` was false almost everywhere
# and the opaque white overlay covered nearly the entire render.
# Buffered a bit so the line survives as a visible band rather than a
# single anti-aliased pixel once the high-quality render's lighting/AA
# are applied.
border_lines <- country_sf |>
    sf::st_geometry() |>
    strip_holes() |>
    sf::st_boundary() |>
    sf::st_buffer(400) |>
    sf::st_sf(value = 1, geometry = _)

border_rast <- stars::st_rasterize(
    border_lines,
    template = blank_template
)

border_mat <- border_rast |>
    as("Raster") |>
    rayshader::raster_to_matrix()

# White border overlay: opaque white where a border cell was rasterized,
# fully transparent everywhere else
border_overlay <- array(0, dim = c(nrow(border_mat), ncol(border_mat), 4))
border_overlay[, , 1] <- 1
border_overlay[, , 2] <- 1
border_overlay[, , 3] <- 1
border_overlay[, , 4] <- ifelse(is.na(border_mat), 0, 1)

### 4. BLUE SPIKE PALETTE
### --------------------
# Kept strictly within the blue hue -- dark navy base rising to a
# vivid, saturated blue at the tallest (highest-population) spikes
cols <- rev(c(
    "#050a1f", "#0d2b5e",
    "#1565c0", "#29b6f6"
))

texture <- grDevices::colorRampPalette(cols)(256)

# zscale=15 was tuned for the original 3000px-wide data grid. zscale
# divides population counts into the matrix's index-space units, which
# are shared with x/y -- so coarsening the grid (fewer index units
# across the same physical extent) without rescaling zscale makes the
# spikes' height-to-footprint ratio blow up, which both wrecks the
# camera framing and causes extreme, near-vertical thin columns to
# render as blown-out white/grey. Scale it with the grid resolution to
# keep the original proportions.
zscale <- 15 * (3000 / size)

# Create the initial 3D object
pop_mat |>
    rayshader::height_shade(texture = texture) |>
    rayshader::add_overlay(
        border_overlay,
        alphalayer = 1
    ) |>
    rayshader::plot_3d(
        heightmap = pop_mat,
        solid = F,
        soliddepth = 0,
        zscale = zscale,
        shadowdepth = 0,
        shadow_darkness = .95,
        windowsize = round(c(800 * width_ratio, 800 * height_ratio)),
        phi = 65,
        zoom = .65,
        theta = 0,
        background = "white"
    )

# Lower, more oblique angle than the original top-down composition so
# the spike heights actually read instead of flattening into a texture.
# theta=0 keeps north "up" to match the familiar map orientation
# (Hague/coast on the west/left, Amsterdam/IJsselmeer to the northeast).
rayshader::render_camera(phi = 35, zoom = .6, theta = 0)

rayshader::render_highquality(
    filename = "netherlands_population_2022.png",
    preview = T,
    light = T,
    lightdirection = 225,
    lightaltitude = 60,
    lightintensity = 400,
    interactive = F,
    width = output_width, height = output_height
)

# Close the rgl/OpenGL window explicitly -- without this, Rscript can
# stay resident holding the GPU context open well after the script
# finishes, which risks corrupting a later concurrent render.
rgl::close3d()
