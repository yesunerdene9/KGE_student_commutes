import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import combinations
from tqdm import tqdm  # Import tqdm for progress bars

MIN_STOPS = 3  # Minimum number of stops to consider a trip
MAX_TIME_DIFF = 600  # Maximum average time difference in seconds (10 minutes)

# Enable nested progress bars
tqdm.pandas()

# Load user location data
print("Loading user location data...")
user_loc_df = pd.read_json('user_loc.json', dtype={'trip_id': str})
user_loc_df['user_timestamp'] = pd.to_datetime(user_loc_df['user_timestamp'])
user_loc_df['date'] = user_loc_df['user_timestamp'].dt.date

# Load bus trip data
print("Loading bus trip data...")
bus_trips = pd.read_json('./bus_trips.json', dtype={'trip_id': str})

# Prepare bus trip stop sequences with scheduled arrival datetimes
print("Preparing bus trip stop sequences...")
trip_stop_sequences = {}  # Key: (trip_id, date), Value: list of dicts with 'stop_id' and 'arrival_datetime'

# Iterate over bus trips with a progress bar
for _, trip in tqdm(bus_trips.iterrows(), total=bus_trips.shape[0], desc="Processing Bus Trips"):
    trip_id = trip['trip_id']
    start_date_str = trip['start_date']
    end_date_str = trip['end_date']
    try:
        start_date = pd.to_datetime(start_date_str, format='%Y%m%d').date()
        end_date = pd.to_datetime(end_date_str, format='%Y%m%d').date()
    except ValueError as e:
        print(f"Error parsing start or end date for trip {trip_id}: {e}")
        continue  # Skip this trip if dates are invalid

    # Parse served_days
    served_days = trip['served_days']

    # Map days of week to served_days (Monday=0, Sunday=6)
    served_days_dict = {i: served_days[i] for i in range(7)}

    # Parse extra_dates and excluded_dates
    def parse_dates(date_str):
        if not date_str:
            return []
        return [datetime.strptime(date, '%Y%m%d').date() for date in date_str]

    extra_dates = parse_dates(trip['extra_dates'])
    excluded_dates = parse_dates(trip['excluded_dates'])

    # Parse stops
    stops = trip['stops']

    # Parse times
    times = trip['times']

    if len(stops) != len(times):
        continue  # Skip trips with mismatched stops and times

    # Generate dates this trip operates on
    date_range = pd.date_range(start=start_date, end=end_date).date
    for trip_date in date_range:
        weekday = trip_date.weekday()  # Monday=0, Sunday=6

        # Check if trip runs on this date
        runs_today = False
        if trip_date in extra_dates:
            runs_today = True
        elif trip_date in excluded_dates:
            runs_today = False
        elif served_days_dict.get(weekday, 0) == 1:
            runs_today = True

        if not runs_today:
            continue  # Skip this date

        # Build stop sequence with scheduled arrival datetimes
        stop_times = []
        for stop_id, arrival_time in zip(stops, times):
            if not arrival_time:
                continue
            try:
                if arrival_time.startswith('24:'):
                    arrival_time = '00' + arrival_time[2:]
                if arrival_time.startswith('25:'):
                    arrival_time = '01' + arrival_time[2:]
                arrival_time = datetime.strptime(arrival_time, '%H:%M:%S').time()
                arrival_datetime = datetime.combine(trip_date, arrival_time)
                stop_times.append({'stop_id': stop_id, 'arrival_datetime': arrival_datetime})
            except ValueError as e:
                print(f"Error parsing arrival time '{arrival_time}' for trip {trip_id}, stop {stop_id}: {e}")
                continue  # Skip invalid times

        if stop_times:
            trip_stop_sequences[(trip_id, trip_date)] = stop_times

print("Finished preparing trip stop sequences.\n")

# Initialize a list to hold users' likely trips
user_likely_trips = []

# Get unique users for progress tracking
unique_users = user_loc_df['user_id'].unique()

print("Processing user observations to identify likely trips...")
# Iterate over users with a progress bar
for user_id in tqdm(unique_users, desc="Processing Users"):
    user_group = user_loc_df[user_loc_df['user_id'] == user_id]
    for date, date_group in user_group.groupby('date'):
        # Get user's observations for this date
        user_stops = date_group[['stop_id', 'user_timestamp', 'trip_id']].sort_values('user_timestamp')

        # Get the list of trips operating on this date
        trips_on_date = [tid for (tid, d) in trip_stop_sequences.keys() if d == date]

        # Initialize a list to hold candidate trips with their total time difference
        candidate_trips = []

        # Iterate over trips with a progress bar (nested tqdm)
        for trip_id in trips_on_date:
            if (trip_id, date) not in trip_stop_sequences:
                continue  # Should not happen

            # Get the trip's stop sequence with arrival_datetimes
            trip_stops = trip_stop_sequences[(trip_id, date)]

            # Build a mapping from stop_id to arrival_datetime
            stop_id_to_arrival = {st['stop_id']: st['arrival_datetime'] for st in trip_stops}

            # Get the user's observed stops for this trip and reset index
            trip_user_stops = user_stops[user_stops['trip_id'] == trip_id].reset_index(drop=True)

            # Map user's observed stops to their indices in the trip's stop sequence, and get scheduled arrival times
            stop_indices = []
            time_diffs = []

            for idx, row in trip_user_stops.iterrows():
                stop_id = row['stop_id']
                user_time = row['user_timestamp']
                if stop_id in stop_id_to_arrival:
                    index_in_trip = next((i for i, st in enumerate(trip_stops) if st['stop_id'] == stop_id), None)
                    if index_in_trip is not None:
                        scheduled_arrival = stop_id_to_arrival[stop_id]
                        time_diff = abs((user_time - scheduled_arrival).total_seconds())
                        stop_indices.append(index_in_trip)
                        time_diffs.append(time_diff)

            if len(stop_indices) < MIN_STOPS:
                continue  # Need at least MIN_STOPS stops to consider the trip

            # Find the longest increasing subsequence
            def longest_increasing_subsequence(seq):
                lengths = [1]*len(seq)
                for i in range(len(seq)):
                    for j in range(i):
                        if seq[j] < seq[i] and lengths[j] + 1 > lengths[i]:
                            lengths[i] = lengths[j] + 1
                return max(lengths)

            lis_length = longest_increasing_subsequence(stop_indices)

            if lis_length >= MIN_STOPS:
                # Compute total time difference for the matched stops in the LIS
                def extract_lis_indices(seq):
                    lengths = [1]*len(seq)
                    predecessors = [-1]*len(seq)
                    for i in range(len(seq)):
                        for j in range(i):
                            if seq[j] < seq[i] and lengths[j] + 1 > lengths[i]:
                                lengths[i] = lengths[j] + 1
                                predecessors[i] = j
                    # Find the index of the maximum length
                    max_len = max(lengths)
                    max_index = lengths.index(max_len)
                    # Reconstruct the subsequence indices
                    lis_indices = []
                    while max_index != -1:
                        lis_indices.append(max_index)
                        max_index = predecessors[max_index]
                    return lis_indices[::-1]

                lis_indices = extract_lis_indices(stop_indices)
                # Now, get the total time difference for the stops in the LIS
                total_time_diff = sum(time_diffs[i] for i in lis_indices)

                # Record this candidate trip
                candidate_trips.append({
                    'trip_id': trip_id,
                    'lis_indices': lis_indices,
                    'stop_indices': stop_indices,
                    'time_diffs': time_diffs,
                    'total_time_diff': total_time_diff,
                    'lis_length': lis_length,
                    'trip_user_stops': trip_user_stops  # Save for later use
                })

        if not candidate_trips:
            continue  # No candidate trips found

        # Select the trip with minimal total time difference
        best_trip = min(candidate_trips, key=lambda x: x['total_time_diff'])

        # Extract boarding and alighting info
        trip_id = best_trip['trip_id']
        trip_stops = trip_stop_sequences[(trip_id, date)]
        lis_indices = best_trip['lis_indices']
        stop_indices_in_trip = [best_trip['stop_indices'][i] for i in lis_indices]
        stop_ids_in_lis = [trip_stops[idx]['stop_id'] for idx in stop_indices_in_trip]
        # Use the trip_user_stops from best_trip
        trip_user_stops = best_trip['trip_user_stops']

        # Safely index into trip_user_stops
        try:
            user_times_in_lis = [trip_user_stops.iloc[i]['user_timestamp'] for i in lis_indices]
        except IndexError as e:
            print(f"IndexError for user_id {user_id}, trip_id {trip_id} on {date}: {e}")
            continue  # Skip this trip for this user

        scheduled_arrivals_in_lis = [trip_stops[idx]['arrival_datetime'] for idx in stop_indices_in_trip]

        boarding_stop_id = stop_ids_in_lis[0]
        alighting_stop_id = stop_ids_in_lis[-1]
        boarding_time = user_times_in_lis[0]
        alighting_time = user_times_in_lis[-1]
        duration = (alighting_time - boarding_time).total_seconds() / 60  # Duration in minutes

        # Optionally, check if the average time difference is within a reasonable threshold
        avg_time_diff = best_trip['total_time_diff'] / len(lis_indices)

        if avg_time_diff > MAX_TIME_DIFF:
            continue  # The time difference is too large, skip this trip

        # Append to user_likely_trips
        user_likely_trips.append({
            'user_id': user_id,
            'date': date.strftime('%Y-%m-%d'),
            'trip_id': trip_id,
            'boarding_stop_id': boarding_stop_id,
            'alighting_stop_id': alighting_stop_id,
            'boarding_time': boarding_time.strftime('%H:%M:%S'),
            'alighting_time': alighting_time.strftime('%H:%M:%S'),
            'duration_minutes': duration,
            'number_of_stops': best_trip['lis_length'],
            'total_time_difference_seconds': best_trip['total_time_diff'],
            'average_time_difference_seconds': avg_time_diff
        })

# Create DataFrame and save to CSV
print("\nSaving the identified trips to 'user_likely_trips.json'...")
user_trips_df = pd.DataFrame(user_likely_trips)
user_trips_df.to_json('user_likely_trips.json', orient='records')
print("Process completed successfully.")
