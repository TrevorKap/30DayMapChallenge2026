#######################################################
#                 Making crisp spike maps with R
#                 Milos Popovic
#                 2023/03/12
#                 Adapted for Norway
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
    "https://geodata-eu-central-1-kontur-public.s3.amazonaws.com/kontur_datasets/kontur_population_NO_20220630.gpkg.gz"
file_name <- "norway-population.gpkg.gz"

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

# Lambert Azimuthal Equal Area, recentered on mainland Norway
crsLAEA <- "+proj=laea +lat_0=65 +lon_0=17 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

pop_sf_raw <- sf::st_read(load_file_name) |>
    sf::st_transform(crs = crsLAEA)

### 2b. COUNTRY BOUNDARY
### --------------------
# Norway's GISCO polygon includes Svalbard/Jan Mayen way up in the
# Arctic, which would massively stretch the bounding box and shrink
# mainland Norway to a sliver. Crop to a geographic bounding box around
# the mainland (done in lon/lat, before reprojecting) -- much faster
# than a pairwise-distance filter across Norway's thousands of small
# coastal skerries/islands, which was slow enough to look hung.
# Resolution "03" (1:3M) also cuts the vertex count a lot versus the
# highest-detail "01" boundary, with no visible loss at map scale.
country_sf_geo <- giscoR::gisco_get_countries(
    country = "NO",
    resolution = "03"
)
mainland_bbox <- sf::st_bbox(
    c(xmin = 0, ymin = 57, xmax = 32, ymax = 71.5),
    crs = sf::st_crs(country_sf_geo)
)
country_sf <- sf::st_crop(country_sf_geo, mainland_bbox) |>
    sf::st_transform(crs = crsLAEA)

png("norway-borders.png")
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

size <- 900
width <- round((size * width_ratio), 0)
height <- round((size * height_ratio), 0)

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

### 4. TEAL / AURORA SPIKE PALETTE
### --------------------------------
# The color at the end of this list (before rev()) is what covers most
# of the map -- Norway's vast, mostly-0-population interior -- so it
# needs to be a saturated, rich color, not a pale tint: the earlier
# pale mint (#7dffcf) as that dominant color read as a washed-out,
# flat map instead of a moody dark landmass with spikes popping out of
# it. A vivid, saturated emerald teal here fixes that.
cols <- rev(c(
    "#020a0a", "#0a4a48",
    "#0fae8a", "#00c9a3"
))

texture <- grDevices::colorRampPalette(cols)(256)

# Halved vs. the base grid-resolution scaling (i.e. doubled height):
# Norway's population is far less concentrated into extreme outlier
# hexes than Vietnam/China, so the base zscale left the whole map
# looking nearly flat outside the Oslo area.
zscale <- 15 * (3000 / size) * 0.5

# Camera zoom scaled to how elongated the country is -- see the
# Vietnam/Netherlands scripts for the derivation. Norway is far more
# extreme (mainland is roughly 13:1 north-south vs east-west), so this
# matters even more here.
# Extra 0.85x safety margin so the near edge of the frame (at this
# oblique angle) doesn't touch or clip the subject.
# width_ratio specifically, not min(width_ratio, height_ratio) -- see
# turkey_population_spikes.R for why (a landscape-shaped country
# breaks min()). No-op here since Norway is portrait-shaped.
zoom_val <- 0.73 * width_ratio

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
        # result for elongated countries like Norway.
        windowsize = round(c(800 * width_ratio, 800 * height_ratio)),
        phi = 65,
        zoom = zoom_val,
        theta = 0,
        background = "white"
    )

# theta=0 keeps north "up" -- the familiar elongated fjord coastline
# running north-south
rayshader::render_camera(phi = 35, zoom = zoom_val, theta = 0)

rayshader::render_highquality(
    filename = "norway_population_2022.png",
    preview = T,
    light = T,
    lightdirection = 225,
    lightaltitude = 60,
    lightintensity = 400,
    interactive = F,
    width = output_width, height = output_height
)

rgl::close3d()
