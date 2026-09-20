# 1 PACKAGES

libs <- c(
    "giscoR", "terra", "sf",
    "elevatr", "png", "rayshader"
)

installed_libs <- libs %in% rownames(
    installed.packages()
)

if(any(installed_libs == F)){
    install.packages(
        libs[!installed_libs],
        dependencies = T
    )
}

invisible(
    lapply(
        libs, library,
        character.only = T
    )
)

# 2. SOUTHEAST ASIA SHAPEFILE

southeast_asia_sf <- giscoR::gisco_get_countries(
    country = c(
        "BRN", "KHM", "IDN", "LAO",
        "MYS", "MMR", "PHL", "SGP",
        "THA", "TLS", "VNM"
    ),
    resolution = "3"
) |>
sf::st_union()

plot(sf::st_geometry(southeast_asia_sf))

# 3. SOUTHEAST ASIA OLD TOPO MAP

southeast_asia_topo_tif <- terra::rast(
    "southeast_asia_topo.tif"
)

terra::plotRGB(southeast_asia_topo_tif)

# 4. SOUTHEAST ASIA EXTENT

southeast_asia_bbox <- terra::ext(
    southeast_asia_topo_tif
) |>
    sf::st_bbox(crs = 3857) |>
    sf::st_as_sfc(crs = 3857) |>
    sf::st_transform(crs = 4326) |>
    sf::st_intersection(southeast_asia_sf)

plot(sf::st_geometry(southeast_asia_bbox))

# 5. SOUTHEAST ASIA ELEVATION

southeast_asia_dem <- elevatr::get_elev_raster(
    locations = southeast_asia_bbox |> sf::st_as_sf(),
    z = 5, clip = "bbox"
)

southeast_asia_dem_3857 <- southeast_asia_dem |>
    terra::rast() |>
    terra::project("EPSG:3857")

terra::plot(southeast_asia_dem_3857)

# 6. RESAMPLE OLD TOPO MAP

southeast_asia_topo_resampled <- terra::resample(
    x = southeast_asia_topo_tif,
    y = southeast_asia_dem_3857,
    method = "bilinear"
)

img_file <- "southeast_asia_topo_modified.png"

terra::writeRaster(
    southeast_asia_topo_resampled,
    img_file,
    overwrite = T,
    NAflag = 255
)

southeast_asia_topo_img <- png::readPNG(
    img_file
)

# 7. RENDER SCENE

h <- nrow(southeast_asia_dem_3857)
w <- ncol(southeast_asia_dem_3857)

southeast_asia_matrix <- rayshader::raster_to_matrix(
    southeast_asia_dem_3857
)

southeast_asia_matrix |>
    rayshader::height_shade(
        texture = colorRampPalette(
            c("white", "grey80")
        )(128)
    ) |>
    rayshader::add_overlay(
        southeast_asia_topo_img,
        alphalayer = 1
    ) |>
    rayshader::plot_3d(
        southeast_asia_matrix,
        zscale = 17,
        solid = F,
        shadow = T,
        shadow_darkness = 1,
        background = "white",
        windowsize = c(
            w / 5, h / 5
        ),
        zoom = .42,
        phi = 89,
        theta = 0
    )

# 8. RENDER IMAGE

hdri_url <- "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/air_museum_playground_4k.hdr"
hdri_file <- basename(hdri_url)

if(!file.exists(hdri_file)){
    download.file(
        url = hdri_url,
        destfile = hdri_file,
        mode = "wb",
        method = "libcurl"
    )
}

rayshader::render_highquality(
    filename = "3d_topo_southeast_asia.png",
    preview = T,
    interactive = F,
    light = F,
    environment_light = hdri_file,
    intensity_env = .75,
    rotate_env = 90,
    parallel = T,
    width = w * 1.5,
    height = h * 1.5
)
