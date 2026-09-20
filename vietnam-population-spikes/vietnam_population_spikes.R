#######################################################
#                 Making crisp spike maps with R
#                 Milos Popovic
#                 2023/03/12
#                 Adapted for Vietnam
########################################################

libs <- c(
    "tidyverse", "R.utils",
    "httr", "sf", "stars",
    "rayshader", "giscoR"
)

installed_libs <- libs %in% rownames(installed.packages())
if (any(installed_libs == F)) {
    install.packages(libs[!installed_libs])
}

invisible(lapply(libs, library, character.only = T))
sf::sf_use_s2(FALSE)

### 1. DOWNLOAD & UNZIP DATA
### ------------------------
url <-
    "https://geodata-eu-central-1-kontur-public.s3.amazonaws.com/kontur_datasets/kontur_population_VN_20220630.gpkg.gz"
file_name <- "vietnam-population.gpkg.gz"

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

# Lambert Azimuthal Equal Area, recentered on Vietnam
crsLAEA <- "+proj=laea +lat_0=16 +lon_0=106 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

pop_sf_raw <- sf::st_read(load_file_name) |>
    sf::st_transform(crs = crsLAEA)

### 2b. COUNTRY BOUNDARY
### --------------------
country_sf <- giscoR::gisco_get_countries(
    country = "VN",
    resolution = "01"
) |>
    sf::st_transform(crs = crsLAEA)

png("vietnam-borders.png")
plot(sf::st_geometry(country_sf))
dev.off()

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

# Coarser data grid than a top-down spike map needs -- at the low,
# oblique camera angle below, a 3000px-wide grid produces spikes only
# a fraction of a screen pixel wide, which the renderer's
# anti-aliasing washes out to grey/white instead of showing color.
size <- 900
width <- round((size * width_ratio), 0)
height <- round((size * height_ratio), 0)

# Final output resolution, independent of the data grid above
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

### 3b. FILL DATA GAPS *INSIDE* THE COUNTRY
### ------------------------------------------------------------------
# st_rasterize(..., template = <stars object>) uses the template's OWN
# attribute values as the background for any cell the new geometry
# doesn't cover -- passing pop_rast directly would leak population
# values into every cell the mask/border geometry doesn't touch. Wipe
# a copy to NA first so it only supplies the grid geometry.
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

border_overlay <- array(0, dim = c(nrow(border_mat), ncol(border_mat), 4))
border_overlay[, , 1] <- 1
border_overlay[, , 2] <- 1
border_overlay[, , 3] <- 1
border_overlay[, , 4] <- ifelse(is.na(border_mat), 0, 1)

### 4. PURPLE / LAVENDER SPIKE PALETTE
### -----------------------------------
# Dark violet base rising to a bright orchid/lavender at the tallest
# spikes (Hanoi, Ho Chi Minh City)
cols <- rev(c(
    "#170821", "#4b1a6b",
    "#9b3fb0", "#e896f0"
))

texture <- grDevices::colorRampPalette(cols)(256)

# Extra 1.3x factor beyond the base grid-resolution scaling: Hanoi's
# single densest hex is such an extreme outlier that the base zscale
# sends its spike tip up through the title/subtitle text at the top
# of the frame. This brings it back down with some clearance.
zscale <- 15 * (3000 / size) * 1.6

# Camera zoom needs to scale with how elongated the country is: a
# fixed zoom tuned for a squarish country like the Netherlands leaves
# a long, narrow country like Vietnam tiny in a mostly-empty frame,
# because the camera still has to back off far enough to fit the long
# dimension's full extent, which is set by the SHORT dimension's ratio
# once the other axis is pegged to `size`. Empirically,
# zoom ~= 0.73 * min(width_ratio, height_ratio) reproduces both the
# Netherlands' working zoom=.6 (ratio ~0.83) and a good full-frame fit
# for Vietnam (ratio ~0.47 -> zoom ~0.34).
# Extra 0.85x safety margin: the raw formula fits the subject snugly
# enough that the near edge (bottom of frame, at this oblique angle)
# can touch or clip the frame boundary -- e.g. Vietnam's Mekong Delta
# tip ran right to the bottom edge with no breathing room.
# width_ratio specifically, not min(width_ratio, height_ratio): the
# oblique phi angle foreshortens the north-south (height) axis but not
# east-west (width). Vietnam is portrait-shaped (height_ratio=1, so
# width_ratio is already the smaller value here) -- this is a no-op
# for this script, kept for consistency with Norway/Turkey where it
# matters (see turkey_population_spikes.R for the landscape case).
zoom_val <- 0.73 * width_ratio * 1.2

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
        # Matching the final render's aspect ratio here matters: a
        # square window used to set up zoom/FOV, followed by a
        # render_highquality() call at a very different (e.g. tall
        # portrait) aspect ratio, produces a severely cropped/zoomed
        # result for elongated countries like Vietnam.
        windowsize = round(c(800 * width_ratio, 800 * height_ratio)),
        phi = 65,
        zoom = zoom_val,
        theta = 0,
        background = "white"
    )

# theta=0 keeps north "up" -- Hanoi/delta to the north, Ho Chi Minh
# City/delta to the south, matching the familiar S-curve map shape
rayshader::render_camera(phi = 35, zoom = zoom_val, theta = 0)

rayshader::render_highquality(
    filename = "vietnam_population_2022.png",
    preview = T,
    light = T,
    lightdirection = 225,
    lightaltitude = 60,
    lightintensity = 400,
    interactive = F,
    width = output_width, height = output_height
)

rgl::close3d()
