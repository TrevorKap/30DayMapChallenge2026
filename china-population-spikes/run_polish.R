source("../polish_map.R")
polish_map(
    input_png = "china_population_2022.png",
    output_png = "china_population_2022_polished.png",
    country_name = "CHINA",
    subtitle_text = "POPULATION DENSITY",
    credit_text = "Kontur Population 2022 · rayshader"
)
cat("polished\n")
