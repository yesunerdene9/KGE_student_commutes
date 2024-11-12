import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from datetime import timedelta
import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output
import dash_table
import plotly.express as px
import plotly.graph_objects as go

# -------------------- Configuration --------------------
# File paths
USER_POI_STAYS_CSV = './user_poi_stays.csv'
POI_AND_OSM_CSV = '../Poi_osm/poi_and_osm_full.csv'

# -------------------------------------------------------

# -------------------- Data Loading and Preparation --------------------

# Step 1: Load User PoI Stays Data
print("Loading user PoI stays data...")
try:
    user_stays = pd.read_csv(USER_POI_STAYS_CSV, parse_dates=['timestep'])
    print(f"User PoI stays data loaded with {len(user_stays)} records.")
except FileNotFoundError:
    print(f"Error: The file '{USER_POI_STAYS_CSV}' was not found.")
    exit(1)
except Exception as e:
    print(f"Error loading '{USER_POI_STAYS_CSV}': {e}")
    exit(1)

# Step 2: Load PoI and OSM Data
print("Loading PoI and OSM data...")
try:
    poi_data = pd.read_csv(POI_AND_OSM_CSV)
    print(f"PoI and OSM data loaded with {len(poi_data)} records.")
except FileNotFoundError:
    print(f"Error: The file '{POI_AND_OSM_CSV}' was not found.")
    exit(1)
except Exception as e:
    print(f"Error loading '{POI_AND_OSM_CSV}': {e}")
    exit(1)

# Step 3: Merge User Stays with PoI Data to Get Coordinates and Names
print("Merging user stays with PoI data...")
# Verify column names in poi_data
expected_poi_columns = {'osm_id', 'latitude', 'longitude', 'name'}
actual_poi_columns = set(poi_data.columns)
if not expected_poi_columns.issubset(actual_poi_columns):
    print(f"Error: PoI data is missing expected columns. Expected columns: {expected_poi_columns}")
    exit(1)

merged_data = user_stays.merge(
    poi_data[['osm_id', 'latitude', 'longitude', 'name']],
    on='osm_id',
    how='left'
)

# Drop records with missing PoI information
missing_poi = merged_data['name'].isnull().sum()
if missing_poi > 0:
    print(f"Warning: {missing_poi} user stays have missing PoI information and will be dropped.")
    merged_data = merged_data.dropna(subset=['name'])

print(f"Merged data contains {len(merged_data)} records after dropping missing PoI information.")

# Step 4: Convert Merged Data to GeoDataFrame
print("Converting merged data to GeoDataFrame...")
merged_data['geometry'] = merged_data.apply(lambda row: Point(row['longitude'], row['latitude']), axis=1)
merged_gdf = gpd.GeoDataFrame(merged_data, geometry='geometry', crs="EPSG:4326")
print("Merged data converted to GeoDataFrame.")

# Step 5: Assign Sequence Numbers to Each Stay per User for the same day it should be student_day_sequenceid
print("Assigning sequence numbers to stays...")
merged_gdf['timestep_date'] = merged_gdf['timestep'].dt.date
merged_gdf['sequence'] = merged_gdf.groupby(['user_id', 'timestep_date']).cumcount() + 1
print("Sequence numbers assigned.")

# Step 6: Extract Latitude and Longitude for Plotting
print("Extracting latitude and longitude for plotting...")
merged_gdf['lat'] = merged_gdf.geometry.y
merged_gdf['lon'] = merged_gdf.geometry.x
print("Coordinates extracted.")

# Verify coordinate ranges
print(f"Latitude ranges from {merged_gdf['lat'].min()} to {merged_gdf['lat'].max()}")
print(f"Longitude ranges from {merged_gdf['lon'].min()} to {merged_gdf['lon'].max()}")

# -------------------- Dash App Initialization --------------------

# Convert 'user_id' to string for consistency
merged_gdf['user_id'] = merged_gdf['user_id'].astype(str)

# Ensure 'lat' and 'lon' are numeric and drop any NaNs
merged_gdf['lat'] = pd.to_numeric(merged_gdf['lat'], errors='coerce')
merged_gdf['lon'] = pd.to_numeric(merged_gdf['lon'], errors='coerce')
before_drop = len(merged_gdf)
merged_gdf = merged_gdf.dropna(subset=['lat', 'lon'])
after_drop = len(merged_gdf)
if before_drop != after_drop:
    print(f"Dropped {before_drop - after_drop} records due to invalid coordinates.")

# Create separate color and symbol mappings for user IDs
unique_user_ids = sorted(merged_gdf['user_id'].unique())
colors = px.colors.qualitative.Plotly
symbols = ['circle', 'square', 'diamond', 'star', 'x', 'triangle-up', 'triangle-down']

color_discrete_map = {user_id: colors[i % len(colors)] for i, user_id in enumerate(unique_user_ids)}
symbol_map = {user_id: symbols[i % len(symbols)] for i, user_id in enumerate(unique_user_ids)}
print(f"Color and symbol mappings created for {len(color_discrete_map)} users.")

# Initialize the Dash app with a Bootstrap theme for better styling
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.title = "User PoI Stays Visualization"

# Prepare user options, including 'All Users'
user_options = [{'label': 'All Users', 'value': 'all'}] + [
    {'label': f"User {uid}", 'value': uid} for uid in unique_user_ids
]

# Define the layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("User PoI Stays Visualization"), className="text-center mb-4")
    ]),
    dbc.Row([
        dbc.Col([
            html.Label("Select User:"),
            dcc.Dropdown(
                id='user-dropdown',
                options=user_options,
                value='all',
                clearable=False
            )
        ], width=4),
        dbc.Col([
            html.Label("Select Date:"),
            dcc.DatePickerSingle(
                id='date-picker',
                min_date_allowed=merged_gdf['timestep'].dt.date.min(),
                max_date_allowed=merged_gdf['timestep'].dt.date.max(),
                initial_visible_month=merged_gdf['timestep'].dt.date.min(),
                date=merged_gdf['timestep'].dt.date.min(),
                disabled=False
            )
        ], width=4),
        dbc.Col([
            html.Label(""),
            dbc.Checklist(
                options=[{"label": "Show All Dates", "value": "all_dates"}],
                value=[],
                id="all-dates-checklist",
                inline=True,
            )
        ], width=4, align='center'),
    ], className="mb-4"),
    dbc.Row([
        dbc.Col([
            dcc.Graph(id='user-map')
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            dcc.Graph(id='timeline')
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.H5("Stay Data"),
            dash_table.DataTable(
                id='stay-table',
                columns=[],  # Will be set in the callback
                data=[],
                page_size=10,
                style_table={'overflowX': 'auto'},
                filter_action="native",
                sort_action="native",
                style_cell={
                    'textAlign': 'left',
                    'minWidth': '100px',
                    'width': '150px',
                    'maxWidth': '300px',
                    'whiteSpace': 'normal'
                },
            )
        ], width=12)
    ])
], fluid=True)

# -------------------- Callbacks --------------------

@app.callback(
    Output('date-picker', 'disabled'),
    Input('all-dates-checklist', 'value')
)
def toggle_datepicker(all_dates_value):
    return 'all_dates' in all_dates_value

@app.callback(
    [
        Output('user-map', 'figure'),
        Output('timeline', 'figure'),
        Output('stay-table', 'data'),
        Output('stay-table', 'columns'),
    ],
    [
        Input('user-dropdown', 'value'),
        Input('date-picker', 'date'),
        Input('all-dates-checklist', 'value')
    ]
)
def update_visualizations(selected_user, selected_date, all_dates_value):
    print(f"Callback triggered with selected_user={selected_user}, selected_date={selected_date}, all_dates_value={all_dates_value}")
    all_dates_selected = 'all_dates' in all_dates_value

    # Filter stays based on user and date
    filtered_data = merged_gdf.copy()
    if selected_user != 'all':
        filtered_data = filtered_data[merged_gdf['user_id'] == selected_user]
        print(f"Filtered data for user {selected_user}: {len(filtered_data)} records")

    if not all_dates_selected:
        if selected_date is not None:
            try:
                selected_date_parsed = pd.to_datetime(selected_date).date()
                print(f"Selected date parsed: {selected_date_parsed}")
                filtered_data = filtered_data[filtered_data['timestep'].dt.date == selected_date_parsed]
                print(f"Filtered data for date {selected_date_parsed}: {len(filtered_data)} records")
            except Exception as e:
                print(f"Error parsing selected_date: {e}")
                filtered_data = pd.DataFrame(columns=merged_gdf.columns)
        else:
            print("No date selected and 'Show All Dates' is not checked.")
            filtered_data = pd.DataFrame(columns=merged_gdf.columns)

    if filtered_data.empty:
        print("Filtered data is empty after applying filters.")
        fig_map = px.scatter_mapbox()
        fig_map.update_layout(
            mapbox_style="open-street-map",
            height=600,
            title="No stays found",
            margin={"r":0,"t":40,"l":0,"b":0}
        )
        fig_timeline = go.Figure()
        fig_timeline.add_annotation(
            text="No stays found",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        fig_timeline.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            plot_bgcolor='white'
        )
        return fig_map, fig_timeline, [], []

    print(f"Filtered data contains {len(filtered_data)} records after filtering.")

    # Create the map figure using Plotly Express
    if selected_user == 'all':
        fig_map = px.scatter_mapbox(
            filtered_data,
            lat="lat",
            lon="lon",
            color="user_id",
            hover_name="name",
            hover_data={
                "user_id": True,
                "name": True,
                "timestep": True,
                "duration": True,
                "sequence": True,
                "lat": False,
                "lon": False
            },
            color_discrete_map=color_discrete_map,
            title="User PoI Stays - All Users",
            mapbox_style="open-street-map"
        )
    else:
        fig_map = px.scatter_mapbox(
            filtered_data,
            lat="lat",
            lon="lon",
            color="sequence",
            color_continuous_scale="Viridis",
            hover_name="name",
            hover_data={
                "user_id": True,
                "name": True,
                "timestep": True,
                "duration": True,
                "sequence": True,
                "lat": False,
                "lon": False
            },
            title=f"User {selected_user} PoI Stays",
            mapbox_style="open-street-map"
        )


    # Convert to a go.Figure to add lines
    fig_map = go.Figure(fig_map)

    # Add lines to represent the sequence of stays
    if selected_user == 'all':
        # Multiple users: add lines per user
        for uid in filtered_data['user_id'].unique():
            user_data = filtered_data[filtered_data['user_id'] == uid].sort_values('timestep')
            if len(user_data) > 1:
                fig_map.add_trace(
                    go.Scattermapbox(
                        lat=user_data['lat'],
                        lon=user_data['lon'],
                        mode='lines',
                        line=dict(width=2, color=color_discrete_map[uid]),
                        hoverinfo='none',
                        name=f"User {uid} Path",
                        showlegend=False
                    )
                )
    else:
        # Single user: add lines connecting their stays
        user_data_sorted = filtered_data.sort_values('timestep')
        if len(user_data_sorted) > 1:
            fig_map.add_trace(
                go.Scattermapbox(
                    lat=user_data_sorted['lat'],
                    lon=user_data_sorted['lon'],
                    mode='lines',
                    line=dict(width=2, color=color_discrete_map.get(selected_user, "blue")),
                    hoverinfo='none',
                    name=f"User {selected_user} Path",
                    showlegend=False
                )
            )

    # Update map layout
    fig_map.update_layout(
        mapbox_style="open-street-map",
        margin={"r":0,"t":40,"l":0,"b":0},
        legend_title="User ID" if selected_user == 'all' else "",
        showlegend=True if selected_user == 'all' else False
    )

    # Adjust center of the map
    center_lat = filtered_data['lat'].mean()
    center_lon = filtered_data['lon'].mean()
    fig_map.update_layout(mapbox_center={"lat": center_lat, "lon": center_lon})

    # Prepare data for timeline
    timeline_data = filtered_data.copy()

    # Create end_time by adding duration to timestep
    timeline_data['end_time'] = timeline_data['timestep'] + pd.to_timedelta(timeline_data['duration'], unit='m')

    # Define labels based on user selection
    if selected_user == 'all':
        y_label = 'user_id'
        color_discrete_map_timeline = color_discrete_map
        fig_timeline = px.timeline(
            timeline_data,
            x_start="timestep",
            x_end="end_time",
            y=y_label,
            color="user_id",
            color_discrete_map=color_discrete_map_timeline,
            hover_data=["name", "timestep", "duration"],
            labels={
                "timestep": "Start Time",
                "end_time": "End Time",
                "duration": "Duration (minutes)",
                "user_id": "User ID",
                "name": "PoI Name"
            },
            title="Stay Durations - All Users"
        )
    else:
        y_label = 'name'  # Use PoI name for individual user
        fig_timeline = px.timeline(
            timeline_data,
            x_start="timestep",
            x_end="end_time",
            y=y_label,
            color="name",
            hover_data=["user_id", "timestep", "duration"],
            labels={
                "timestep": "Start Time",
                "end_time": "End Time",
                "duration": "Duration (minutes)",
                "user_id": "User ID",
                "name": "PoI Name"
            },
            title=f"Stay Durations - User {selected_user}"
        )

    fig_timeline.update_yaxes(autorange="reversed")  # Reverse the y-axis to have earliest stays at the top
    fig_timeline.update_layout(
        height=600,
        showlegend=True if selected_user == 'all' else False,
        margin={"r":0,"t":40,"l":0,"b":0}
    )

    # Prepare data for the table
    table_columns = [{"name": i, "id": i} for i in ['user_id', 'osm_id', 'timestep', 'duration', 'name', 'sequence']]
    table_data = filtered_data[['user_id', 'osm_id', 'timestep', 'duration', 'name', 'sequence']].to_dict('records')

    print("Callback successfully updated outputs.")
    return fig_map, fig_timeline, table_data, table_columns

# -------------------- Run the Dash App --------------------
if __name__ == '__main__':
    app.run_server(debug=True)
