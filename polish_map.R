#######################################################
#  Polish pass for rayshader spike maps: title, subtitle,
#  and credit line, composited on top of a finished render.
#
#  Fonts are drawn via ggplot2 + showtext (works cross-platform
#  and doesn't depend on ImageMagick resolving font family names),
#  saved as a transparent overlay, then merged onto the base
#  image with magick.
#######################################################

libs <- c("ggplot2", "showtext", "sysfonts", "magick")
installed_libs <- libs %in% rownames(installed.packages())
if (any(installed_libs == F)) {
    install.packages(libs[!installed_libs])
}
invisible(lapply(libs, library, character.only = T))

sysfonts::font_add_google("Playfair Display", "title")
sysfonts::font_add_google("Barlow Condensed", "subtitle")
showtext::showtext_auto()
showtext::showtext_opts(dpi = 300)

#' @param input_png path to the rayshader render
#' @param output_png path to write the polished result
#' @param country_name main title, e.g. "NETHERLANDS"
#' @param subtitle_text smaller line under the title, e.g. "POPULATION DENSITY"
#' @param credit_text bottom-left credit/data-source line
#' @param title_color,subtitle_color,credit_color hex colors for each text line
polish_map <- function(input_png, output_png,
                        country_name, subtitle_text, credit_text,
                        title_color = "grey15", subtitle_color = "grey35",
                        credit_color = "grey50") {
    img <- magick::image_read(input_png)
    info <- magick::image_info(img)
    w <- info$width
    h <- info$height

    # ggplot2's `size` for text is in mm, converted to points via the
    # fixed factor .pt (~2.845), then to pixels at the given dpi. Work
    # backwards from a target nominal font size expressed as a fraction
    # of a reference dimension (px_per_mm below already bakes in
    # dpi = 300).
    #
    # That reference dimension -- and the vertical layout below -- is
    # min(w, h), not w alone: a wide landscape render (e.g. Turkey,
    # 2400x1044) has the same width as a tall portrait one, so sizing
    # off width alone made the title/subtitle oversized and crammed
    # into the short frame, overlapping each other and the artwork.
    # Using the smaller dimension keeps text proportional to the
    # actual available space regardless of aspect ratio.
    ref <- min(w, h)
    px_per_mm <- 2.845 * 300 / 72
    mm_for_px_fraction <- function(frac) (frac * ref) / px_per_mm

    # Fractions match the original (portrait-tuned) sizes -- 0.055 of
    # ref for the title, 0.02 for the subtitle, 0.011 for the credit
    # line -- since frac*ref equals the font's actual rendered pixel
    # size, these same fractions drive both the ggplot `size` argument
    # (via mm_for_px_fraction) and the layout spacing below, so the two
    # can't drift out of sync the way title_px/subtitle_px did before.
    title_frac <- 0.055
    subtitle_frac <- 0.02
    title_px <- title_frac * ref
    subtitle_px <- subtitle_frac * ref
    margin_top <- 0.05 * ref
    gap <- 0.025 * ref

    title_y <- h - (margin_top + title_px * 0.7)
    subtitle_y <- h - (margin_top + title_px + gap + subtitle_px * 0.5)

    overlay <- ggplot2::ggplot() +
        ggplot2::xlim(0, w) +
        ggplot2::ylim(0, h) +
        ggplot2::annotate("text",
            x = w / 2, y = title_y, label = country_name,
            family = "title", size = mm_for_px_fraction(title_frac), color = title_color
        ) +
        ggplot2::annotate("text",
            x = w / 2, y = subtitle_y, label = subtitle_text,
            family = "subtitle", size = mm_for_px_fraction(subtitle_frac), color = subtitle_color
        ) +
        ggplot2::annotate("text",
            x = w * 0.02, y = h * 0.02, label = credit_text,
            family = "subtitle", size = mm_for_px_fraction(0.011), color = credit_color, hjust = 0
        ) +
        ggplot2::theme_void() +
        ggplot2::theme(
            plot.background = ggplot2::element_rect(fill = NA, color = NA),
            panel.background = ggplot2::element_rect(fill = NA, color = NA),
            plot.margin = ggplot2::margin(0, 0, 0, 0)
        ) +
        ggplot2::coord_cartesian(expand = FALSE)

    tmp <- tempfile(fileext = ".png")
    ggplot2::ggsave(tmp, overlay,
        width = w / 300, height = h / 300, dpi = 300,
        bg = "transparent", limitsize = FALSE
    )

    overlay_img <- magick::image_read(tmp) |>
        magick::image_scale(paste0(w, "x", h, "!"))

    result <- magick::image_composite(img, overlay_img, operator = "over")
    magick::image_write(result, output_png)
    unlink(tmp)

    invisible(output_png)
}
