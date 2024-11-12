import pandas as pd
import geopandas as gpd
from tqdm import tqdm

# -------------------- Configuration --------------------
# File paths
POI_CSV_PATH = '../Poi_osm/poi_and_osm_full.csv'
USER_PARQUET_PATH_TEMPLATE = "C:/Users/david/Downloads/dataset/Sensors/Sensors/Position/locationeventpertime_rd.parquet/part.{}.parquet"
OUTPUT_CSV_PATH = './user_poi_matches.csv'

# Parameters
POSITION_BUFFER_KM = 0.05  # 50 meters
POSITION_BUFFER_METERS = POSITION_BUFFER_KM * 1000  # Convert to meters
CHUNK_SIZE = 100000 # Number of records to process at a time
# -------------------------------------------------------

try:
    # Load OSM PoI data
    print("Loading OSM PoI data...")
    osm_data = pd.read_csv(POI_CSV_PATH)
    print(f"OSM PoI data loaded with {len(osm_data)} records.")

    # Convert PoI data to GeoDataFrame
    print("Converting PoI data to GeoDataFrame...")
    osm_data_gdf = gpd.GeoDataFrame(
        osm_data,
        geometry=gpd.points_from_xy(osm_data['longitude'], osm_data['latitude']),
        crs="EPSG:4326"
    )
    osm_data_gdf = osm_data_gdf.to_crs(epsg=3857)  # Project to meters
    print("PoI data converted to GeoDataFrame and projected to EPSG:3857.")

    # Build spatial index for PoIs to speed up spatial joins
    print("Building spatial index for PoIs...")
    osm_data_gdf.sindex
    print("Spatial index built for PoIs.")

    # Load user data from multiple Parquet files
    print("Loading user data from Parquet files...")
    user_data = pd.concat([
        pd.read_parquet(USER_PARQUET_PATH_TEMPLATE.format(i))
        for i in range(4)
    ], ignore_index=True)
    print(f"User data loaded with {len(user_data)} records.")

    # useridConvert 'timestamp' to datetime if not already
    if not pd.api.types.is_datetime64_any_dtype(user_data['timestamp']):
        print("Converting 'timestamp' to datetime...")
        user_data['timestamp'] = pd.to_datetime(user_data['timestamp'], errors='coerce')
        invalid_timestamps = user_data['timestamp'].isnull().sum()
        if invalid_timestamps > 0:
            print(f"Warning: {invalid_timestamps} records have invalid 'timestamp' and will be dropped.")
            user_data = user_data.dropna(subset=['timestamp'])
            print(f"User data after dropping invalid timestamps: {len(user_data)} records.")
    else:
        print("'timestamp' column is already in datetime format.")

    # useridReset index after dropping records
    user_data.reset_index(drop=True, inplace=True)

    # useridProcess user data in chunks for memory efficiency
    print("Processing user data in chunks and performing spatial joins...")
    user_results_list = []

    for start_idx in tqdm(range(0, len(user_data), CHUNK_SIZE), desc="Processing Chunks"):
        end_idx = min(start_idx + CHUNK_SIZE, len(user_data))
        user_chunk = user_data.iloc[start_idx:end_idx].copy()
        # print(f"\nProcessing chunk {start_idx}-{end_idx} with {len(user_chunk)} records.")

        # useridConvert user data to GeoDataFrame
        user_gdf = gpd.GeoDataFrame(
            user_chunk,
            geometry=gpd.points_from_xy(user_chunk['longitude'], user_chunk['latitude']),
            crs="EPSG:4326"
        )
        user_gdf = user_gdf.to_crs(epsg=3857)  # Project to meters
        # print("User data converted to GeoDataFrame and projected to EPSG:3857.")

        # useridRename 'timestamp' to 'user_timestamp' for clarity
        user_gdf = user_gdf.rename(columns={'timestamp': 'user_timestamp'})
        # print("Renamed 'timestamp' column to 'user_timestamp'.")

        user_gdf['buffer_geometry'] = user_gdf.geometry.buffer(POSITION_BUFFER_METERS)
        # print("Buffer geometry created.")

        # useridCreate a temporary GeoDataFrame for buffers
        buffer_gdf = gpd.GeoDataFrame(
            user_gdf[['userid', 'user_timestamp', 'buffer_geometry']],
            geometry='buffer_geometry',
            crs=user_gdf.crs
        )
        # print("Temporary buffer GeoDataFrame created.")

        # useridPerform spatial join between buffer and PoIs
        user_osm_matches = gpd.sjoin(
            buffer_gdf,
            osm_data_gdf[['osm_id', 'geometry']],
            how='left',
            predicate='intersects'
        )
        # print(f"Spatial join completed with {len(user_osm_matches)} records.")

        # useridSelect required columns
        user_osm_matches = user_osm_matches[['userid', 'osm_id', 'user_timestamp']].copy()
        # print("Selected required columns: 'userid', 'osm_id', 'user_timestamp'.")

        # remove where osm_id is null
        user_osm_matches = user_osm_matches.dropna(subset=['osm_id'])

        # useridAppend to results list
        user_results_list.append(user_osm_matches)
        # print(f"Chunk {start_idx}-{end_idx}: {len(user_osm_matches)} matches appended.")

    # useridConcatenate all results
    print("\nConcatenating all matched results...")
    if user_results_list:
        user_osm_df = pd.concat(user_results_list, ignore_index=True)
        print(f"Total matched records: {len(user_osm_df)}.")
    else:
        user_osm_df = pd.DataFrame(columns=['userid', 'poi_id', 'user_timestamp'])
        print("No matches found across all chunks.")

    # interpret id columns as integers
    user_osm_df['userid'] = user_osm_df['userid'].astype(int)
    user_osm_df['osm_id'] = user_osm_df['osm_id'].astype(int)

    # useridSave to CSV
    print(f"Saving results to {OUTPUT_CSV_PATH}...")
    user_osm_df.to_csv(OUTPUT_CSV_PATH, index=False)
    print("Spatial join completed successfully.")

except Exception as e:
    print(f"\nAn error occurred: {e}")
