source("../polish_map.R")
polish_map(
    input_png = "vietnam_population_2022.png",
    output_png = "vietnam_population_2022_polished.png",
    country_name = "VIETNAM",
    subtitle_text = "POPULATION DENSITY",
    credit_text = "Kontur Population 2022 · rayshader"
)
cat("polished\n")
