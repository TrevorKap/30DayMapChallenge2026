# 1. LIBRARIES
#-------------

options(repos = c(CRAN = "https://cloud.r-project.org"))
options(HTTPUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
install.packages("pacman")
pacman::p_load(
    terra,
    sf,
    geodata,
    rayshader,
    elevatr,
    tidyverse
)

sessionInfo()

crs_country <-
    "+proj=laea +lat_0=52 +lon_0=10 +x_0=4321000 +y_0=3210000 +datum=WGS84 +units=m +no_defs"

# 2. COUNTRY BORDERS
#-------------------

get_country_admin1 <- function() {
    main_path <- getwd()
    country_admin1 <- geodata::gadm(
        country = "DEU",
        level = 1,
        path = main_path
    ) |>
        sf::st_as_sf()

    return(country_admin1)
}

country_admin1 <- get_country_admin1()

country_sf <- country_admin1 |>
    sf::st_as_sf() |>
    sf::st_union()

plot(sf::st_geometry(country_sf))

# 3. DOWNLOAD RIVERS
#-------------------

url <- "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_eu_shp.zip"
destfile <- basename(url)

download.file(
    url = url,
    destfile = destfile,
    mode = "wb",
    method = "libcurl"
)

unzip(destfile)

# 4. LOAD RIVERS
#---------------

filename <- list.files(
    path = "HydroRIVERS_v10_eu_shp",
    pattern = ".shp",
    full.names = TRUE
)

country_bbox <- sf::st_bbox(country_sf)
print(country_bbox)

bbox_wkt <- "POLYGON((
    5.8 47.2,
    5.8 55.1,
    15.1 55.1,
    15.1 47.2,
    5.8 47.2
))
"

country_rivers <- sf::st_read(
    filename,
    wkt_filter = bbox_wkt
) |>
    sf::st_intersection(country_sf) |>
    sf::st_collection_extract("LINESTRING") |>
    sf::st_cast("MULTILINESTRING") |>
    sf::st_cast("LINESTRING")

sort(
    unique(
        country_rivers$ORD_FLOW
    )
)

country_river_width <-
country_rivers |>
    dplyr::mutate(
        width = as.numeric(
            ORD_FLOW
        ),
        width = dplyr::case_when(
            width == 4 ~ 16,
            width == 5 ~ 14,
            width == 6 ~ 10,
            width == 7 ~ 8,
            width == 8 ~ 4,
            width == 9 ~ 2,
            TRUE ~ 0
        )
    ) |>
    sf::st_as_sf() |>
    sf::st_transform(
        crs = crs_country)

# 5. ELEVATION DATA
#-------------------

country_sf_poly <- sf::st_sf(geometry = country_sf)

elev <-
elevatr::get_elev_raster(
    locations = country_sf_poly,
    z = 7,
    clip = "locations"
)

elev_rast <- elev |>
    terra::rast() |>
    terra::project(
        crs_country
        )

elmat <-
rayshader::raster_to_matrix(
    elev_rast
)

# 6. RENDER SCENE
#----------------

elmat |>
    rayshader::height_shade(
        texture = colorRampPalette(
            c(
                "#d4e0a8",
                "#5b7a3f"
            )
        )(512)
    ) |>
    rayshader::add_overlay(
        rayshader::generate_line_overlay(
            geometry = country_river_width,
            extent = elev_rast,
            heightmap = elmat,
            color = "#387B9C",
            linewidth = country_river_width$width,
            data_column_width = "width"
        ),
        alphalayer = 1
    ) |>
    rayshader::plot_3d(
        elmat,
        zscale = 15,
        solid = FALSE,
        shadow = TRUE,
        shadow_darkness = 1,
        background = "white",
        windowsize = c(
            600, 600
        ),
        zoom = .5,
        phi = 85,
        theta = 0
    )

rayshader::render_camera(
    phi = 89,
    zoom = .75,
    theta = 0
)

# 7. RENDER OBJECT
#-----------------
u <- "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/photo_studio_loft_hall_4k.hdr"
hdri_file <- basename(u)

download.file(
    url = u,
    destfile = hdri_file,
    mode = "wb",
    method = "libcurl"
)

filename <- "germany-river-elevation.png"

start_time <- Sys.time()
rayshader::render_highquality(
    filename = filename,
    preview = TRUE,
    light = FALSE,
    environment_light = hdri_file,
    intensity_env = 1.25,
    # rotate_env = 90,
    interactive = FALSE,
    parallel = TRUE,
    width = 3000,
    height = 3000
)
end_time <- Sys.time()
end_time - start_time
