#######################################################
#                 Making crisp spike maps with R
#                 Milos Popovic
#                 2023/03/12
#                 Adapted for China
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
sf::sf_use_s2(FALSE)

crsLAEA <- "+proj=laea +lat_0=35 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

# Caches the expensive part (download, reprojecting/rasterizing 3.1M
# features, gap-fill) so an interrupted run -- laptop sleeps, session
# dies, etc. -- can restart straight into the fast final render step
# instead of redoing several minutes of data processing.
pop_mat_cache <- "china_pop_mat_cache.rds"

if (file.exists(pop_mat_cache)) {
    cached <- readRDS(pop_mat_cache)
    pop_mat <- cached$pop_mat
    width <- cached$width
    height <- cached$height
    width_ratio <- cached$width_ratio
    height_ratio <- cached$height_ratio
} else {
    ### 1. DOWNLOAD & UNZIP DATA
    ### ------------------------
    url <-
        "https://geodata-eu-central-1-kontur-public.s3.amazonaws.com/kontur_datasets/kontur_population_CN_20220630.gpkg.gz"
    file_name <- "china-population.gpkg.gz"

    load_file_name_check <- gsub(".gz", "", file_name)

    get_population_data <- function() {
        res <- httr::GET(
            url,
            write_disk(file_name, overwrite = T),
            progress()
        )

        R.utils::gunzip(file_name, remove = F, overwrite = T)
    }

    if (!file.exists(load_file_name_check)) {
        get_population_data()
    }

    ### 2. LOAD DATA
    ### -------------
    load_file_name <- gsub(".gz", "", file_name)

    # (original script used lat_0=52 lon_0=10 for Germany;
    # China needs a center near its geographic middle to avoid distortion)
    get_population_data <- function() {
        pop_df <- sf::st_read(
            load_file_name
        ) |>
            sf::st_transform(crs = crsLAEA)
    }

    pop_sf <- get_population_data()

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

    size <- 3000
    width <- round((size * width_ratio), 0)
    height <- round((size * height_ratio), 0)

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
    # China's real population distribution is extremely uneven -- huge
    # unpopulated deserts and mountain ranges (Taklamakan, Tibetan Plateau,
    # Gobi fringe) have zero Kontur hexes, same as the ocean/foreign
    # territory that falls inside the rectangular bounding box. With
    # solid = FALSE, every NA cell is a literal hole in the mesh: ~92% of
    # this raster is NA, so without this fix the render comes out as a
    # shattered field of disconnected spikes with huge gaps instead of a
    # recognizable country silhouette. Only cells genuinely inside China
    # get filled to a 0-population baseline; cells outside the country
    # stay NA/transparent so the silhouette itself stays correct.
    country_sf <- giscoR::gisco_get_countries(country = "CN", resolution = "01") |>
        sf::st_transform(crs = crsLAEA)

    # st_rasterize(..., template = <stars object>) uses the template's OWN
    # attribute values as the background for any cell the new geometry
    # doesn't cover -- passing pop_rast directly would leak population
    # values into every cell outside the country. Wipe a copy to NA first
    # so it only supplies the grid geometry (extent/resolution/CRS).
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

    saveRDS(
        list(
            pop_mat = pop_mat, width = width, height = height,
            width_ratio = width_ratio, height_ratio = height_ratio
        ),
        pop_mat_cache
    )
}

# Gold base rising through orange into a deep red core at the tallest
# spikes (Thailand-reference palette)
cols <- rev(c(
    "#f9d976", "#f2a750",
    "#d9532b", "#7a1616"
))

texture <- grDevices::colorRampPalette(cols)(256)

# Create the initial 3D object
pop_mat |>
    rayshader::height_shade(texture = texture) |>
    rayshader::plot_3d(
        heightmap = pop_mat,
        solid = F,
        soliddepth = 0,
        zscale = 15,
        shadowdepth = 0,
        shadow_darkness = .95,
        windowsize = round(c(800 * width_ratio, 800 * height_ratio)),
        phi = 65,
        zoom = .65,
        theta = -30,
        background = "white"
    )

# Use this to adjust the view after building the window object
rayshader::render_camera(phi = 75, zoom = .7, theta = 0)

rayshader::render_highquality(
    filename = "china_population_2022.png",
    preview = T,
    light = T,
    lightdirection = 225,
    lightaltitude = 60,
    lightintensity = 400,
    interactive = F,
    width = width, height = height
)

# Close the rgl/OpenGL window explicitly -- without this, Rscript can
# stay resident holding the GPU context open well after the script
# finishes, which risks corrupting a later concurrent render.
rgl::close3d()
