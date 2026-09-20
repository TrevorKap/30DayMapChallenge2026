source("../polish_map.R")
polish_map(
    input_png = "norway_population_2022.png",
    output_png = "norway_population_2022_polished.png",
    country_name = "NORWAY",
    subtitle_text = "POPULATION DENSITY",
    credit_text = "Kontur Population 2022 · rayshader"
)
cat("polished\n")
