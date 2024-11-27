from tqdm import tqdm
import pandas as pd

USER_PARQUET_PATH_TEMPLATE = "C:/Users/david/Downloads/dataset/Sensors/Sensors/Position/locationeventpertime_rd.parquet/part.{}.parquet"

# Load user data from multiple Parquet files
print("Loading user data from Parquet files...")
user_data = pd.concat([
    pd.read_parquet(USER_PARQUET_PATH_TEMPLATE.format(i))
    for i in range(4)
], ignore_index=True)
print(f"User data loaded with {len(user_data)} records.")

# get all the unique user ids
user_ids = user_data['userid'].unique()

# save the user ids to a csv file
user_ids_df = pd.DataFrame(user_ids, columns=['userid'])
user_ids_df.to_json('user_ids.json', orient='records')