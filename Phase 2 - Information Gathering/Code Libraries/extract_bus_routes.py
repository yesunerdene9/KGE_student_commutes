import pandas as pd
from geopy.geocoders import Nominatim
import os
from tqdm import tqdm

COMPUTE_OSM_IDS = True

# Function to load GTFS data into DataFrames
def load_gtfs_data(gtfs_path):
    gtfs_files = ['stops.txt', 'stop_times.txt', 'trips.txt', 'routes.txt', 'calendar.txt', 'calendar_dates.txt', 'shapes.txt']
    gtfs_data = {}
    for file in gtfs_files:
        file_path = os.path.join(gtfs_path, file)
        if os.path.exists(file_path):
            gtfs_data[file.split('.')[0]] = pd.read_csv(file_path)
        else:
            print(f"Warning: {file} not found in the GTFS data.")
    return gtfs_data

# Function to geocode stops and assign OpenStreetMap IDs
def geocode_stops(stops_df):
    print(f"Geocoding stops to get {len(stops_df)} OpenStreetMap IDs...")
    geolocator = Nominatim(user_agent="gtfs_processor", timeout=60)
    osm_ids = []
    for index, row in tqdm(stops_df.iterrows(), total=len(stops_df)):
        location = geolocator.reverse((row['stop_lat'], row['stop_lon']), exactly_one=True)
        if location and 'osm_id' in location.raw:
            osm_ids.append(location.raw['osm_id'])
        else:
            print(f"Warning: OSM ID not found for stop {row['stop_id']}.")
            osm_ids.append(None)
    stops_df['osm_id'] = osm_ids
    return stops_df

# Function to process bus stops
def process_bus_stops(gtfs_data):
    print("Processing bus stops...")
    stops_df = gtfs_data['stops']
    #remove stop_desc, zone_id, stop_code, and wheelchair_boarding columns
    stops_df = stops_df.drop(columns=['stop_desc', 'zone_id', 'wheelchair_boarding', 'stop_code'])
    
    stop_times_df = gtfs_data['stop_times']
    #remove departure_time column and stop_sequence
    stop_times_df = stop_times_df.drop(columns=['departure_time', 'stop_sequence'])
    
    trips_df = gtfs_data['trips']
    # drop trip_headsign shape_id wheelchair_accessible service_id
    trips_df = trips_df.drop(columns=['trip_headsign', 'shape_id', 'wheelchair_accessible', 'service_id', 'direction_id'])

    # Merge stop_times with trips to get route_id
    stop_times_trips = pd.merge(stop_times_df, trips_df, on='trip_id', how='left')

    # Geocode stops to get OpenStreetMap IDs
    if COMPUTE_OSM_IDS:
        stops_df = geocode_stops(stops_df)

    # Merge with stops to get timetable information, it should be under a column called timetable
    stops_timetable = pd.merge(stops_df, stop_times_trips, on='stop_id', how='left')
    
    #order by arrival_time
    stops_timetable = stops_timetable.sort_values(by=['arrival_time'])
    
    # Group by stop to get unique stops
    time_table = stops_timetable.groupby('stop_id').agg({'route_id': list, 'trip_id': list, 'arrival_time': list}).reset_index()
    
    # add the timetable column to stops_df
    stops_df = pd.merge(stops_df, time_table, on='stop_id', how='left')

    return stops_df

# Function to process bus routes
def process_bus_routes(gtfs_data):
    print("Processing bus routes...")
    routes_df = gtfs_data['routes']
    # remove agency_id route_type route_color route_text_color
    routes_df = routes_df.drop(columns=['agency_id', 'route_type', 'route_color', 'route_text_color'])
    # Merge column route_short_name and route_long_name to get route_name
    routes_df['route_name'] = routes_df['route_short_name'] + ' - ' + routes_df['route_long_name']
    # drop route_short_name and route_long_name
    routes_df = routes_df.drop(columns=['route_short_name', 'route_long_name'])
    
    # Assign unique IDs to each route
    return routes_df

# Function to process individual bus trips
def process_bus_trips(gtfs_data):
    print("Processing bus trips...")
    trips_df = gtfs_data['trips']
    # drop service_id wheelchair_accessible
    trips_df = trips_df.drop(columns=['wheelchair_accessible', 'shape_id', 'direction_id'])
    
    stop_times_df = gtfs_data['stop_times']
    # drop departure_time
    stop_times_df = stop_times_df.drop(columns=['departure_time'])
    
    # Merge trips and stop_times to get the sequence of stops for each trip
    trips_stop_times = pd.merge(trips_df, stop_times_df, on='trip_id', how='left')
    
    # Generate the list of stops for each trip with times
    trips_stop_times = trips_stop_times.sort_values(by=['trip_id', 'stop_sequence'])
    sequence_of_stops = trips_stop_times.groupby('trip_id').agg({'stop_id': list, 'arrival_time': list}).reset_index()
    
    # Trips with sequence of stops
    trips_stops = pd.merge(trips_df, sequence_of_stops, on='trip_id', how='left')
    # rename stop_id to stops and arrival_time to times
    trips_stops = trips_stops.rename(columns={'stop_id': 'stops', 'arrival_time': 'times'})
    trips_stops["start_time"] = trips_stops["times"].apply(lambda x: x[0])
    
    calendar_df = gtfs_data['calendar']
    # make a list of days by using the columns monday, tuesday, wednesday, thursday, friday, saturday, sunday
    calendar_df['running_days'] = calendar_df[['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']].values.tolist()
    calendar_df = calendar_df.drop(columns=['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
    
    # Merge with calendar to get service days
    trips_calendar = pd.merge(trips_stops, calendar_df, on='service_id', how='left')
    
    # include the extra dates (exception_type 1) and excluded (exception_type 2)
    calendar_dates_df = gtfs_data['calendar_dates']
    exception_dates = calendar_dates_df[calendar_dates_df['exception_type'] == 1].groupby('service_id').agg({'date': list}).reset_index()
    exception_dates = exception_dates.rename(columns={'date': 'extra_dates'})
    excluded_dates = calendar_dates_df[calendar_dates_df['exception_type'] == 2].groupby('service_id').agg({'date': list}).reset_index()
    excluded_dates = excluded_dates.rename(columns={'date': 'excluded_dates'})
    
    # Merge with exception dates
    trips_info = pd.merge(trips_calendar, exception_dates, on='service_id', how='left')
    trips_info = pd.merge(trips_info, excluded_dates, on='service_id', how='left')
    
    # remove service_id
    trips_info = trips_info.drop(columns=['service_id'])

    return trips_info

# Main function to execute the processing
def main():
    # Load GTFS data
    gtfs_data = load_gtfs_data("./gtfs")

    # Process bus stops
    bus_stops = process_bus_stops(gtfs_data)
    bus_stops.to_csv('bus_stops.csv', index=False)
    print("Bus stops data saved to bus_stops.csv")

    # Process bus routes
    bus_routes = process_bus_routes(gtfs_data)
    bus_routes.to_csv('bus_routes.csv', index=False)
    print("Bus routes data saved to bus_routes.csv")

    # Process bus trips
    bus_trips = process_bus_trips(gtfs_data)
    bus_trips.to_csv('bus_trips.csv', index=False)
    print("Bus trips data saved to bus_trips.csv")

if __name__ == "__main__":
    main()
