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

# 2. CHINA, MONGOLIA, RUSSIA SHAPEFILE

inner_asia_sf <- giscoR::gisco_get_countries(
    country = c(
        "CHN", "MNG", "RUS"
    ),
    resolution = "3"
) |>
sf::st_union()

plot(sf::st_geometry(inner_asia_sf))

# 3. INNER ASIA OLD TOPO MAP

inner_asia_topo_tif <- terra::rast(
    "inner_asia_topo.tif"
)

terra::plotRGB(inner_asia_topo_tif)

# 4. INNER ASIA EXTENT

sf::sf_use_s2(FALSE)

inner_asia_bbox <- terra::ext(
    inner_asia_topo_tif
) |>
    sf::st_bbox(crs = 3857) |>
    sf::st_as_sfc(crs = 3857) |>
    sf::st_transform(crs = 4326) |>
    sf::st_intersection(inner_asia_sf)

plot(sf::st_geometry(inner_asia_bbox))

# 5. INNER ASIA ELEVATION

inner_asia_dem <- elevatr::get_elev_raster(
    locations = inner_asia_bbox |> sf::st_as_sf(),
    z = 5, clip = "bbox"
)

inner_asia_dem_3857 <- inner_asia_dem |>
    terra::rast() |>
    terra::project("EPSG:3857")

terra::plot(inner_asia_dem_3857)

# 6. RESAMPLE OLD TOPO MAP

inner_asia_topo_resampled <- terra::resample(
    x = inner_asia_topo_tif,
    y = inner_asia_dem_3857,
    method = "bilinear"
)

img_file <- "inner_asia_topo_modified.png"

terra::writeRaster(
    inner_asia_topo_resampled,
    img_file,
    overwrite = T,
    NAflag = 255
)

inner_asia_topo_img <- png::readPNG(
    img_file
)

# 7. RENDER SCENE

h <- nrow(inner_asia_dem_3857)
w <- ncol(inner_asia_dem_3857)

inner_asia_matrix <- rayshader::raster_to_matrix(
    inner_asia_dem_3857
)

inner_asia_matrix |>
    rayshader::height_shade(
        texture = colorRampPalette(
            c("white", "grey80")
        )(128)
    ) |>
    rayshader::add_overlay(
        inner_asia_topo_img,
        alphalayer = 1
    ) |>
    rayshader::plot_3d(
        inner_asia_matrix,
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
    filename = "3d_topo_inner_asia.png",
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
