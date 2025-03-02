import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from datetime import timedelta
from datetime import datetime
from tqdm import tqdm

# Load bus data
bus_stops = pd.read_json('./bus_stops.json')
bus_routes = pd.read_json('./bus_routes.json')
bus_trips = pd.read_json('./bus_trips.json', dtype={'trip_id': str})

# Parameters
POSITION_BUFFER = 0.05  # in kilometers (50m meters)
TIME_BUFFER = timedelta(minutes=8)  # time buffer around bus arrival times

# Load user data from multiple Parquet files
user_data = pd.concat([
    pd.read_parquet(f"C:/Users/david/Downloads/dataset/Sensors/Sensors/Position/locationeventpertime_rd.parquet/part.{i}.parquet")
    for i in range(4)
], ignore_index=True)

# Preprocess bus arrivals with schedule considerations
bus_arrivals = []

print(f"Processing {len(bus_trips)} bus trips...")
for _, trip in tqdm(bus_trips.iterrows(), total=len(bus_trips)):
    trip_id = trip['trip_id']
    route_id = trip['route_id']
    start_date = trip['start_date']
    end_date = trip['end_date']
    try:
        start_date = pd.to_datetime(start_date, format='%Y%m%d')
        end_date = pd.to_datetime(end_date, format='%Y%m%d')
    except ValueError as e:
        print(f"Error parsing start or end date for trip {trip_id}: {e}")
        continue  # Skip this trip if dates are invalid

    # Parse served_days
    served_days = [trip['monday'], trip['tuesday'], trip['wednesday'], trip['thursday'], trip['friday'], trip['saturday'], trip['sunday']]
    # Map days of week to served_days (assuming Monday=0, Sunday=6)
    served_days_dict = {i: served_days[i] for i in range(7)}  # 0=Monday, ..., 6=Sunday

    # Parse extra_dates and excluded_dates
    def parse_dates(date_str):
        if not date_str:
            return []
        return [datetime.strptime(date, '%Y%m%d').date() for date in date_str]

    extra_dates = trip['extra_dates']
    extra_dates = parse_dates(extra_dates)

    excluded_dates = trip['excluded_dates']
    excluded_dates = parse_dates(excluded_dates)
    
    stops = trip['stops']

    times = trip['times']

    if not stops or not times:
        continue  # Skip if no stops or times

    # For each day in the trip's date range
    date_range = pd.date_range(start_date, end_date)
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

        # For each stop and time, create an arrival entry
        for stop_id, arrival_time in zip(stops, times):
            if not arrival_time:
                continue
            try:
                if arrival_time.startswith('24:'):
                    arrival_time = '00' + arrival_time[2:]
                if arrival_time.startswith('25:'):
                    arrival_time = '01' + arrival_time[2:]
                arrival_time_obj = datetime.strptime(arrival_time, '%H:%M:%S').time()
            except ValueError as e:
                print(f"Error parsing arrival time '{arrival_time}' for trip {trip_id}, stop {stop_id}: {e}")
                continue  # Skip this arrival time if invalid
            arrival_datetime = datetime.combine(trip_date, arrival_time_obj)
            bus_arrivals.append({
                'trip_id': trip_id,
                'route_id': route_id,
                'stop_id': stop_id,
                'arrival_time': arrival_time_obj,
                'arrival_datetime': arrival_datetime
            })

# Convert bus arrivals to DataFrame
bus_arrivals_df = pd.DataFrame(bus_arrivals)
bus_arrivals_df = bus_arrivals_df.merge(bus_stops[['stop_id', 'stop_lat', 'stop_lon']], on='stop_id', how='left')

# Convert bus_arrivals_df to GeoDataFrame   
bus_arrivals_df['date'] = bus_arrivals_df['arrival_datetime'].dt.date

# Convert bus_stops to GeoDataFrame
bus_stops_gdf = gpd.GeoDataFrame(
    bus_stops,
    geometry=gpd.points_from_xy(bus_stops['stop_lon'], bus_stops['stop_lat']),
    crs="EPSG:4326"
)
bus_stops_gdf = bus_stops_gdf.to_crs(epsg=3857)  # Project to meters

# Prepare bus arrivals GeoDataFrame
bus_arrivals_df = bus_arrivals_df.merge(bus_stops_gdf[['stop_id', 'geometry']], on='stop_id', how='left')

# Process user data in chunks to manage memory usage
chunk_size = 100000  # Adjust based on available memory
user_results_list = []

for i in tqdm(range(0, len(user_data), chunk_size)):
    # Process each chunk of user data
    user_chunk = user_data.iloc[i:i+chunk_size].copy()
    
    # Convert user data to GeoDataFrame
    user_chunk['user_timestamp'] = pd.to_datetime(user_chunk['timestamp'])
    user_chunk['date'] = user_chunk['user_timestamp'].dt.date
    user_gdf = gpd.GeoDataFrame(
        user_chunk,
        geometry=gpd.points_from_xy(user_chunk['longitude'], user_chunk['latitude']),
        crs="EPSG:4326"
    )
    user_gdf = user_gdf.to_crs(epsg=3857)  # Project to meters

    # Create buffers around user locations
    user_gdf['geometry'] = user_gdf.geometry.buffer(POSITION_BUFFER * 1000)  # Buffer in meters

    # Spatial join between user locations and bus stops
    user_stops = gpd.sjoin(user_gdf, bus_stops_gdf[['stop_id', 'geometry']], how='left', predicate='intersects')
    
    # Merge with bus arrivals on 'stop_id' and 'date'
    user_stops['date'] = user_stops['user_timestamp'].dt.date
    user_arrivals = user_stops.merge(
        bus_arrivals_df[['stop_id', 'date', 'arrival_datetime', 'arrival_time', 'trip_id']],
        on=['stop_id', 'date'],
        how='left'
    )

    # Filter bus arrivals within the time window
    user_arrivals['time_diff'] = (
        user_arrivals['arrival_datetime'] - user_arrivals['user_timestamp']
    ).dt.total_seconds().abs()
    user_arrivals = user_arrivals[user_arrivals['time_diff'] <= TIME_BUFFER.total_seconds()]
    
    # Append results
    user_results = user_arrivals[['userid', 'stop_id', 'arrival_time', 'trip_id', 'user_timestamp']].copy()
    user_results.rename(columns={'userid': 'user_id'}, inplace=True)
    
    # convert stop_id to int
    user_results['stop_id'] = user_results['stop_id'].astype(int)
    # convert user_timestamp to string
    user_results['user_timestamp'] = user_results['user_timestamp'].astype(str)
    
    user_results_list.append(user_results)

# Concatenate all results and save to JSON 
user_loc_df = pd.concat(user_results_list, ignore_index=True)
user_loc_df.to_json('user_loc.json', orient='records')
