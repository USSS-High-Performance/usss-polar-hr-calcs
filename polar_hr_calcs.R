library(dplyr)
library(purrr)
library(readr)
library(smartabaseR)
library(dotenv)
library(lubridate)
# Load .env for local development. In CI the credentials are supplied as
# environment variables, so skip loading when no .env file is present.
if (file.exists(".env")) {
  dotenv::load_dot_env(".env")
}

username <- Sys.getenv("SB_USERNAME")
password <- Sys.getenv("SB_PASSWORD")
url <- Sys.getenv("SB_URL")
group <- Sys.getenv("SB_ATHLETE_GROUP")

form_name <- "Polar Summary - Training"
source_field <- "Heart Rate Samples"
max_field <- "Max HR - All Time" # histortical calc from Polar HR data
target_field <- "Polar HR Data"

# Load recent Polar Summary - Training
today <- lubridate::today()
yesterday <- today - lubridate::days(1)

# format to dd/mm/yyyy
today_formatted <- as.character(format(today, "%d/%m/%Y"))
yesterday_formatted <- as.character(format(yesterday, "%d/%m/%Y"))

sessions <- sb_get_event(
  form = form_name,
  date_range = c(yesterday_formatted, today_formatted),
  url = url,
  username = username,
  password = password,
  filter = sb_get_event_filter(
    user_key = "group",
    user_value = group
  )
) %>%
  filter(!is.na(.data[["ID"]])) %>%
  select(
    about,
    user_id,
    start_date,
    form,
    event_id,
    all_of(c(max_field, source_field, target_field))
  )

# Filter out sessions that have already been processed (i.e. if field is not empty, blank, or "")
sessions <- sessions %>%
    filter(is.na(.data[[target_field]]) | .data[[target_field]] == "" | .data[[target_field]] == " ")

# if all sessions have been processed exit script
if (nrow(sessions) == 0) {
  message("No new sessions to process. Exiting script.")
  quit(save = "no", status = 0)
}

#function to transform hr
transform_hr <- function(hr_csv, max_hr) {
  
  # manipulate the HR Data, splitting text into df
  hr_data <- read.csv(
    text = gsub("<\\s*br\\s*/?>", "\n", hr_csv),
    check.names = FALSE
  ) %>% mutate(
     "% of Max HR" = round(`Heart Rate` / max_hr, 4) * 100 # take % of max HR
  )
  
  # convert hr_data back into text csv
  hr_csv_updated <- paste(
    capture.output(
      write.csv(
        hr_data,
        row.names = FALSE,
        quote = FALSE
      )
    ),
    collapse = "\n"
  )
  
  return(hr_csv_updated)
}

# apply transform_hr to the sessions df
sessions_upload <- sessions %>%
  mutate(
    !!target_field := map2_chr(
      .data[[source_field]], # pull the Heart Rate Samples field
      .data[[max_field]], # pull the Historical Max HR field
      ~ transform_hr(
        hr_csv = .x,
        max_hr = .y
      )
    )
  ) %>% select(
    form,
    start_date,
    user_id,
    event_id,
    .data[[target_field]]
  ) 

# Exit cleanly if nothing is left to upload. sb_update_event errors on an
# empty data frame, so guard against it here.
if (nrow(sessions_upload) == 0) {
  message("No sessions to upload after processing. Exiting script.")
  quit(save = "no", status = 0)
}

# Upload data to Smartabase
sb_update_event(
  df = sessions_upload,
  form = form_name,
  url = url,
  username = username,
  password = password,
  option = sb_update_event_option(
    interactive_mode = FALSE # to prevent console internaction
  )
)
