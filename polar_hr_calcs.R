library(dplyr)
library(readr)
library(smartabaseR)
library(dotenv)
library(lubridate)
dotenv::load_dot_env(".env")

username <- Sys.getenv("SB_USERNAME")
password <- Sys.getenv("SB_PASSWORD")
url <- Sys.getenv("SB_URL")
group <- Sys.getenv("SB_ATHLETE_GROUP")

form_name <- "Polar Summary - Training"
source_field <- "Heart Rate Samples"
max_field <- "Historical Max HR" # histortical calc from Polar HR data
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
    form,
    event_id,
    all_of(c(max_field, source_field, target_field))
  )
names(sessions)

# Filter out sessions that have already been processed (i.e. if field is not empty, blank, or "")
sessions <- sessions %>%
    filter(is.na(.data[[target_field]]) | .data[[target_field]] == "" | .data[[target_field]] == " ")


# for each session that needs processing, get the source field, and manipulate data to put into target field
    # 1. pull the Historical Max HR field
    # 2. pull the Heart Rate Samples field, and convert it from csv with columns Timestamp,Heart Rate to a df
    # 3. add a column called Heart Rate % of Max, which is Heart Rate / Historical Max HR * 100
    # 4. convert the df back to csv 
    # 5. Insert back into the target field and reupload just that field for the session (using event-id to identify)
    