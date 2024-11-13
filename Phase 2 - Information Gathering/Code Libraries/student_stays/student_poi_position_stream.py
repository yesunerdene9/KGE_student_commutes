import pandas as pd
import numpy as np
from datetime import timedelta

# -------------------- Configuration --------------------
# Parameters
MIN_DURATION_MINUTES = 10 # Example: 5 minutes
MATCHED_DATA_CSV = './user_poi_matches.csv'
FINAL_OUTPUT_CSV = './user_poi_stays.csv'
BUFFER_GAP_THRESHOLD_MINUTES = 10  # Threshold to determine if a new stay starts after a gap
# -------------------------------------------------------

# Step 1: Load the matched data
print("Loading matched user-PoI data...")
matched_df = pd.read_csv(MATCHED_DATA_CSV, parse_dates=['user_timestamp'])
print(f"Matched data loaded with {len(matched_df)} records.")
# interpret osm_id and user_id as integers
matched_df['osm_id'] = matched_df['osm_id'].astype(int)
matched_df['userid'] = matched_df['userid'].astype(int)

# Step 2: Sort the data
matched_df.sort_values(by=['userid', 'osm_id', 'user_timestamp'], inplace=True)
matched_df.reset_index(drop=True, inplace=True)
print("Data sorted by 'userid', 'osm_id', and 'user_timestamp'.")

# Step 3: Identify consecutive stays
matched_df['prev_osm_id'] = matched_df.groupby('userid')['osm_id'].shift(1)
matched_df['prev_timestamp'] = matched_df.groupby('userid')['user_timestamp'].shift(1)

# Determine if the current row is a continuation of the previous stay
matched_df['new_stay'] = np.where(
    (matched_df['osm_id'] != matched_df['prev_osm_id']) | 
    (matched_df['user_timestamp'] - matched_df['prev_timestamp'] > timedelta(minutes=BUFFER_GAP_THRESHOLD_MINUTES)),
    1,
    0
)

# Assign a unique identifier to each stay
matched_df['stay_id'] = matched_df.groupby('userid')['new_stay'].cumsum()
print("Assigned unique 'stay_id' to each consecutive stay within the same PoI.")

# Step 4: Calculate duration of each stay
stay_df = matched_df.groupby(['userid', 'osm_id', 'stay_id']).agg(
    timestamp=('user_timestamp', 'first'),
    end_time=('user_timestamp', 'last')
).reset_index()

# Calculate duration in minutes
stay_df['duration_minutes'] = (stay_df['end_time'] - stay_df['timestamp']).dt.total_seconds() / 60
print("Calculated duration for each stay.")

# Step 5: Filter stays by duration
valid_stays = stay_df[stay_df['duration_minutes'] >= MIN_DURATION_MINUTES].copy()
print(f"Filtered stays to retain only those with duration >= {MIN_DURATION_MINUTES} minutes. Total valid stays: {len(valid_stays)}.")

# Step 6: Select and rename required columns
final_stays = valid_stays[['userid', 'osm_id', 'timestamp', 'duration_minutes']].copy()
final_stays.rename(columns={'userid': 'user_id'}, inplace=True)
print("Selected and renamed required columns for the final output.")

# Step 7: Save the results
final_stays.to_csv(FINAL_OUTPUT_CSV, index=False)
print(f"Final stays data saved to '{FINAL_OUTPUT_CSV}'.")
