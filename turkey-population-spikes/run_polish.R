source("../polish_map.R")
polish_map(
    input_png = "turkey_padded_raw.png",
    output_png = "turkey_population_2022_polished.png",
    country_name = "TURKEY",
    subtitle_text = "POPULATION DENSITY",
    credit_text = "Kontur Population 2022 · rayshader"
)
cat("polished\n")
