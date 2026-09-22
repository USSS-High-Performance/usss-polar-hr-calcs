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

source_form_name <- "Polar Summary - Training"
target_form_name <- "Polar Summary - Training - HR R"
source_field <- "Heart Rate Samples"
max_field <- "Max HR - All Time" # histortical calc from Polar HR data
target_field <- "Polar HR Data"
id_field <- "ID" # unique key present on both forms, used to prevent duplicate processing

# fields carried over unchanged from the source form to the target form
passthrough_fields <- c(
  "Detailed Sport Info",
  "Duration (txt)",
  "Heart Rate Maximum",
  "Edwards' TRiMP",
  "Z1 Mins",
  "Z2 Mins",
  "Z3 Mins",
  "Z4 Mins",
  "Z5 Mins"
)

# Load recent Polar Summary - Training
today <- lubridate::today()
yesterday <- today - lubridate::days(3)

# format to dd/mm/yyyy
today_formatted <- as.character(format(today, "%d/%m/%Y"))
yesterday_formatted <- as.character(format(yesterday, "%d/%m/%Y"))

date_range <- c(yesterday_formatted, today_formatted)

sessions <- sb_get_event(
  form = source_form_name,
  date_range = date_range,
  url = url,
  username = username,
  password = password,
  filter = sb_get_event_filter(
    user_key = "group",
    user_value = group
  )
)

# keep only rows with a usable ID
sessions <- sessions %>%
  filter(!is.na(.data[[id_field]]) & .data[[id_field]] != "")

# if there are no sessions with an ID, exit script
if (nrow(sessions) == 0) {
  message("No source sessions with a valid ID. Exiting script.")
  quit(save = "no", status = 0)
}

# Pull already processed sessions from the target form over the same lookback
# so we can skip any source ID that has already been pushed there.
target_sessions <- sb_get_event(
  form = target_form_name,
  date_range = date_range,
  url = url,
  username = username,
  password = password,
  filter = sb_get_event_filter(
    user_key = "group",
    user_value = group
  )
)

processed_ids <- if (id_field %in% names(target_sessions)) {
  target_sessions[[id_field]]
} else {
  character(0)
}

# filter down to source sessions that have not yet been processed
sessions <- sessions %>%
  filter(!.data[[id_field]] %in% processed_ids)

# if all sessions have been processed exit script
if (nrow(sessions) == 0) {
  message("No new sessions to process. Exiting script.")
  quit(save = "no", status = 0)
}

#function to transform hr
transform_hr <- function(hr_csv, max_hr) {

  # Skip sessions with nothing to transform: blank or missing samples, or a
  # missing max HR. Returning NA lets the run continue instead of erroring.
  if (is.na(hr_csv) || !nzchar(trimws(hr_csv)) || is.na(max_hr)) {
    return(NA_character_)
  }

  # Wrap parsing so one malformed session (e.g. no Heart Rate column) is
  # skipped rather than halting the whole job.
  tryCatch({
    # manipulate the HR Data, splitting text into df
    hr_data <- read.csv(
      text = gsub("<\\s*br\\s*/?>", "\n", hr_csv),
      check.names = FALSE
    )

    if (!"Heart Rate" %in% names(hr_data)) {
      warning("Heart Rate column not found in samples; skipping session.")
      return(NA_character_)
    }

    hr_data <- hr_data %>% mutate(
       "% of Max HR" = round(`Heart Rate` / max_hr, 4) * 100 # take % of max HR
    )

    # convert hr_data back into text csv
    paste(
      capture.output(
        write.csv(
          hr_data,
          row.names = FALSE,
          quote = FALSE
        )
      ),
      collapse = "\n"
    )
  }, error = function(e) {
    warning("Failed to transform heart rate samples: ", conditionMessage(e))
    NA_character_
  })
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
    start_date,
    user_id,
    .data[[id_field]], # carried over from the source form to prevent duplication
    all_of(passthrough_fields), # carried over unchanged from the source form
    .data[[target_field]]
  )

# Drop and log any sessions that could not be transformed (blank or malformed
# samples), so a few bad records do not block the rest of the upload.
skipped <- sessions_upload %>%
  filter(is.na(.data[[target_field]]))

if (nrow(skipped) > 0) {
  message(
    "Skipped ", nrow(skipped), " session(s) with blank or invalid heart rate ",
    "samples (ID: ", paste(skipped[[id_field]], collapse = ", "), ")."
  )
}

sessions_upload <- sessions_upload %>%
  filter(!is.na(.data[[target_field]]))

# Exit cleanly if nothing is left to upload. sb_insert_event errors on an
# empty data frame, so guard against it here.
if (nrow(sessions_upload) == 0) {
  message("No sessions to upload after processing. Exiting script.")
  quit(save = "no", status = 0)
}

# Upload data to Smartabase as new events on the target form
sb_insert_event(
  df = sessions_upload,
  form = target_form_name,
  url = url,
  username = username,
  password = password,
  option = sb_insert_event_option(
    interactive_mode = FALSE # to prevent console internaction
  )
)
