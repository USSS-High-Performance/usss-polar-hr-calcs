library(dplyr)
library(stringr)
library(smartabaseR)
library(load_dotenv)
library(datetime)

load_dotenv(".env")
username <- Sys.getenv("SB_USERNAME")
password <- Sys.getenv("SB_PASSWORD")
url <- Sys.getenv("SB_URL")
form_name <- "Polar Summary - Training"
source_field <- "Heart Rate Samples"
max_field <- "Historical Max HR"
target_field <- "Polar HR Data"

# Load recent Polar Summary - Training

today <- lubridate::today()
yesterday <- today - lubridate::days(1)
# format to dd/mm/yyyy
today_formatted <- format(today, "%d/%m/%Y")
yesterday_formatted <- format(yesterday, "%d/%m/%Y")

sessions <- sb_get_event(
    form = form_name,
    date_range = c(yesterday, today),
    url = url,
    username = username,
    password = password
)

# Filter out sessions that have already been processed (i.e. if field is not empty, blank, or "")
sessions_to_process <- sessions %>%
    filter(is.na(.data[[target_field]]) | .data[[target_field]] == "" | .data[[target_field]] == " ")

# for each session that needs processing, get the source field, and manipulate data to put into target field
    # 1. pull the Historical Max HR field, if it is empty, then pull the max value from Heart Rate Samples csv, Heart Rate column after converted to df
    # 2. pull the Heart Rate Samples field, and convert it from csv with columns Timestamp,Heart Rate to a df
    # 3. add a column called Heart Rate % of Max, which is Heart Rate / Historical Max HR * 100
    # 4. convert the df back to csv 
    # 5. Insert back into the target field and reupload just that field for the session (using event-id to identify)
    