import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import dash_table
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# Load data
user_trips = pd.read_json(
    'user_likely_trips.json',
    dtype={'trip_id': str}
)
bus_stops = pd.read_json('bus_stops.json')
bus_trips = pd.read_json('bus_trips.json', dtype={'trip_id': str})
bus_routes = pd.read_json('bus_routes.json')  # Load bus_routes.json

# Convert 'date' column to datetime.date
user_trips['date'] = user_trips['date'].dt.date

# Rename latitude and longitude columns
bus_stops.rename(columns={'stop_lat': 'latitude', 'stop_lon': 'longitude'}, inplace=True)

# Merge bus_trips with bus_routes to get 'route_name'
bus_trips = bus_trips.merge(bus_routes, on='route_id', how='left')

# Create a color mapping for user IDs
unique_user_ids = sorted(user_trips['user_id'].unique())
colors = px.colors.qualitative.Plotly
color_map = {user_id: colors[i % len(colors)] for i, user_id in enumerate(unique_user_ids)}

# Initialize the Dash app with a Bootstrap theme for better styling
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.LUX])
app.title = "Trento Bus Trips Visualization"

# Prepare user options, including 'All Users'
user_options = [{'label': 'All Users', 'value': 'all'}] + [
    {'label': f"User {uid}", 'value': uid} for uid in unique_user_ids
]

# Define the layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Trento Bus Trips Visualization"), className="text-center mb-4")
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
                min_date_allowed=user_trips['date'].min(),
                max_date_allowed=user_trips['date'].max(),
                initial_visible_month=user_trips['date'].min(),
                date=user_trips['date'].min(),
                disabled=False  # Will be toggled based on 'All Dates' checkbox
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
            dcc.Graph(id='bus-map')
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            dcc.Graph(id='timeline')
        ], width=12)
    ]),
    dbc.Row([
        dbc.Col([
            html.H5("Trip Data"),
            dash_table.DataTable(
                id='trip-table',
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

# Define callbacks

@app.callback(
    Output('date-picker', 'disabled'),
    Input('all-dates-checklist', 'value')
)
def toggle_datepicker(all_dates_value):
    return 'all_dates' in all_dates_value

@app.callback(
    Output('bus-map', 'figure'),
    Output('timeline', 'figure'),
    Output('trip-table', 'data'),
    Output('trip-table', 'columns'),
    Input('user-dropdown', 'value'),
    Input('date-picker', 'date'),
    Input('all-dates-checklist', 'value')
)
def update_visualizations(selected_user, selected_date, all_dates_value):
    # Determine whether to use all dates
    all_dates_selected = 'all_dates' in all_dates_value

    # Filter trips based on user and date
    if selected_user == 'all':
        if all_dates_selected:
            filtered_trips = user_trips.copy()
        else:
            selected_date = pd.to_datetime(selected_date).date()
            filtered_trips = user_trips[user_trips['date'] == selected_date]
    else:
        if all_dates_selected:
            filtered_trips = user_trips[user_trips['user_id'] == selected_user]
        else:
            selected_date = pd.to_datetime(selected_date).date()
            filtered_trips = user_trips[
                (user_trips['user_id'] == selected_user) &
                (user_trips['date'] == selected_date)
            ]

    if filtered_trips.empty:
        # Prepare empty figures and data
        fig_map = go.Figure()
        fig_map.update_layout(
            mapbox_style="open-street-map",
            height=600,
            title="No trips found",
            margin={"r":0,"t":40,"l":0,"b":0}
        )
        fig_timeline = go.Figure()
        fig_timeline.add_annotation(
            text=f"No trips found",
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

    # Merge filtered_trips with bus_trips to get route_id, route_name, trip_headsign
    filtered_trips = filtered_trips.merge(
        bus_trips[['trip_id', 'route_id', 'route_name', 'trip_headsign']],
        on='trip_id',
        how='left'
    )

    # Function to get stop names for each trip
    def get_stop_names(row):
        # Get the corresponding bus trip
        bus_trip = bus_trips[bus_trips['trip_id'] == row['trip_id']]
        if bus_trip.empty:
            return ''  # Return empty string if bus trip not found

        bus_trip = bus_trip.iloc[0]

        # Get the list of stops
        trip_stops = bus_trip['stops']

        # Find the indices of boarding and alighting stops in the trip stops
        try:
            boarding_index = trip_stops.index(row['boarding_stop_id'])
            alighting_index = trip_stops.index(row['alighting_stop_id'])
        except ValueError:
            return ''  # Return empty string if stops not found

        # Ensure correct order
        if boarding_index > alighting_index:
            boarding_index, alighting_index = alighting_index, boarding_index

        # Get the sequence of stops between boarding and alighting
        trip_stops_sequence = trip_stops[boarding_index:alighting_index+1]

        # Get stop names
        stops_info = bus_stops[bus_stops['stop_id'].isin(trip_stops_sequence)].copy()
        stops_info['order'] = stops_info['stop_id'].apply(lambda x: trip_stops_sequence.index(x))
        stops_info = stops_info.sort_values('order')
        stop_names = stops_info['stop_name'].tolist()

        # Combine stop names into a string
        return ', '.join(stop_names)

    # Add 'stop_names' column to filtered_trips
    filtered_trips['stop_names'] = filtered_trips.apply(get_stop_names, axis=1)

    # Prepare data for the table
    table_columns = [{"name": i, "id": i} for i in filtered_trips.columns]
    table_data = filtered_trips.to_dict('records')

    # Base map with all bus stops
    fig_map = go.Figure()

    # Add bus stops to the map
    fig_map.add_trace(
        go.Scattermapbox(
            lat=bus_stops['latitude'],
            lon=bus_stops['longitude'],
            mode='markers',
            marker=go.scattermapbox.Marker(
                size=6,
                color='gray'
            ),
            text=bus_stops['stop_name'],
            hoverinfo='text',
            name='Bus Stops'
        )
    )

    # Update the map style and center
    fig_map.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=12,
        mapbox_center={"lat": bus_stops['latitude'].mean(), "lon": bus_stops['longitude'].mean()},
        height=600,
        title=f"Trips {'for User ' + str(selected_user) if selected_user != 'all' else 'for All Users'}{' on ' + str(selected_date) if not all_dates_selected else ''}",
        margin={"r":0,"t":40,"l":0,"b":0},
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
    )

    # Merge boarding and alighting stops with coordinates
    boarding = filtered_trips.merge(bus_stops, left_on='boarding_stop_id', right_on='stop_id', how='left', suffixes=('', '_boarding'))
    alighting = filtered_trips.merge(bus_stops, left_on='alighting_stop_id', right_on='stop_id', how='left', suffixes=('', '_alighting'))

    # Add boarding points
    fig_map.add_trace(
        go.Scattermapbox(
            lat=boarding['latitude'],
            lon=boarding['longitude'],
            mode='markers',
            marker=go.scattermapbox.Marker(
                size=12,
                color=boarding['user_id'].map(color_map),
                symbol='marker'
            ),
            text=boarding.apply(lambda row: f"User {row['user_id']}<br>Trip ID: {row['trip_id']}<br>Route: {row['route_name']}<br>Head Sign: {row['trip_headsign']}", axis=1),
            hoverinfo='text',
            name='Boarding Points',
            showlegend=False
        )
    )

    # Add alighting points
    fig_map.add_trace(
        go.Scattermapbox(
            lat=alighting['latitude'],
            lon=alighting['longitude'],
            mode='markers',
            marker=go.scattermapbox.Marker(
                size=12,
                color=alighting['user_id'].map(color_map),
                symbol='cross'
            ),
            text=alighting.apply(lambda row: f"User {row['user_id']}<br>Trip ID: {row['trip_id']}<br>Route: {row['route_name']}<br>Head Sign: {row['trip_headsign']}", axis=1),
            hoverinfo='text',
            name='Alighting Points',
            showlegend=False
        )
    )

    # Draw lines and plot all stops between boarding and alighting
    for idx, row in filtered_trips.iterrows():
        # Get the corresponding bus trip
        bus_trip = bus_trips[bus_trips['trip_id'] == row['trip_id']]
        if bus_trip.empty:
            continue  # Skip if bus trip not found

        bus_trip = bus_trip.iloc[0]

        # Get the list of stops
        trip_stops = bus_trip['stops']

        # Find the indices of boarding and alighting stops in the trip stops
        try:
            boarding_index = trip_stops.index(row['boarding_stop_id'])
            alighting_index = trip_stops.index(row['alighting_stop_id'])
        except ValueError:
            continue  # Skip if stops not found

        # Ensure correct order
        if boarding_index > alighting_index:
            boarding_index, alighting_index = alighting_index, boarding_index

        # Get the sequence of stops between boarding and alighting
        trip_stops_sequence = trip_stops[boarding_index:alighting_index+1]

        # Get coordinates for these stops
        stops_coordinates = bus_stops[bus_stops['stop_id'].isin(trip_stops_sequence)].copy()
        stops_coordinates['order'] = stops_coordinates['stop_id'].apply(lambda x: trip_stops_sequence.index(x))
        stops_coordinates = stops_coordinates.sort_values('order')

        # Assign color based on user ID
        color = color_map[row['user_id']]

        # Plot the line connecting all stops
        fig_map.add_trace(
            go.Scattermapbox(
                lat=stops_coordinates['latitude'],
                lon=stops_coordinates['longitude'],
                mode='lines+markers',
                line=dict(width=6, color=color),
                marker=go.scattermapbox.Marker(size=8, color=color),
                text=stops_coordinates['stop_name'],
                hoverinfo='text',
                name=f"Trip {row['trip_id']}",
                showlegend=False
            )
        )

    # Prepare data for timeline
    timeline_data = filtered_trips.copy()
    timeline_data['alighting_time'] = pd.to_datetime(timeline_data['alighting_time'])
    timeline_data['boarding_time'] = pd.to_datetime(timeline_data['boarding_time'])
    timeline_data['trip_info'] = timeline_data.apply(
        lambda row: f"User {row['user_id']} - Trip {row['trip_id']}<br>Route: {row['route_name']}<br>Head Sign: {row['trip_headsign']}", axis=1
    )

    fig_timeline = px.timeline(
        timeline_data,
        x_start="boarding_time",
        x_end="alighting_time",
        y="trip_info",
        color="user_id" if selected_user == 'all' else None,
        color_discrete_map=color_map,
        hover_data=["boarding_stop_id", "alighting_stop_id", "duration_minutes", "route_name", "trip_headsign"],
        title=f"Trips Timeline {'for User ' + str(selected_user) if selected_user != 'all' else 'for All Users'}{' on ' + str(selected_date) if not all_dates_selected else ''}"
    )

    fig_timeline.update_yaxes(autorange="reversed")  # Reverse the y-axis to have earliest trips at the top
    fig_timeline.update_layout(
        height=600,
        showlegend=False,
        margin={"r":0,"t":40,"l":0,"b":0}
    )

    return fig_map, fig_timeline, table_data, table_columns

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
