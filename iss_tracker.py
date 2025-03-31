from flask import Flask, request
import requests
import xmltodict
import numpy as np
import logging
import time
import redis
import json
from geopy.geocoders import Nominatim
from astropy import coordinates, units
from astropy.time import Time

# Redis connection with retry mechanism
def establish_database_connection():
    max_attempts = 5
    wait_time = 2
    
    for attempt in range(max_attempts):
        try:
            db_client = redis.Redis(host='redis-db', port=6379, db=0)
            db_client.ping()  # Verify connection
            return db_client
        except redis.exceptions.ConnectionError as e:
            if attempt < max_attempts - 1:
                logging.warning(f"Database connection attempt {attempt+1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logging.error(f"Database connection failed after {max_attempts} attempts")
                raise e

# Initialize database connection
database = establish_database_connection()

# Initialize application
station_tracker = Flask(__name__)

def fetch_orbital_data():
    """
    Retrieve and store orbital data from NASA's public repository
    """
    source_url = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml"
    response = requests.get(source_url)
    
    if not response.text or response.status_code != 200:
        logging.error('Failed to retrieve orbital data')
        return False
        
    parsed_data = xmltodict.parse(response.text)
    orbital_vectors = parsed_data['ndm']['oem']['body']['segment']['data']['stateVector']
    
    # Store each vector in database
    for vector in orbital_vectors:
        timestamp = vector['EPOCH']
        database.set(timestamp, json.dumps(vector))
    
    return True

def calculate_earth_coordinates(vector):
    """
    Transform space coordinates to Earth-based lat/long/alt
    """
    x_pos = float(vector['X']['#text'])
    y_pos = float(vector['Y']['#text'])
    z_pos = float(vector['Z']['#text'])
    
    # Format timestamp for astropy
    formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', 
                                  time.strptime(vector['EPOCH'][:-5], '%Y-%jT%H:%M:%S'))
    
    # Use astropy to calculate Earth-relative position
    cart_coords = coordinates.CartesianRepresentation([x_pos, y_pos, z_pos], unit=units.km)
    space_ref = coordinates.GCRS(cart_coords, obstime=formatted_time)
    earth_ref = space_ref.transform_to(coordinates.ITRS(obstime=formatted_time))
    position = coordinates.EarthLocation(*earth_ref.cartesian.xyz)
    
    return position.lat.value, position.lon.value, position.height.value

# Original route: returns entire list of epochs
@station_tracker.route('/epochs', methods=['GET'])
def get_epochs():
    """
    Returns the list of epochs and their state vectors, with optional limit and offset.

    Args: None

    Returns: List of dictionaries containing epochs and their state vectors.
    """
    limit = request.args.get('limit', default=None, type=int)
    offset = request.args.get('offset', default=0, type=int)

    # get all keys (epochs) from Redis
    epochs = database.keys()
    epochs = [epoch.decode() for epoch in epochs]

    # Apply limit and offset
    if limit is not None:
        epochs = epochs[offset:offset + limit]
    else:
        epochs = epochs[offset:]

    # get state vectors for each epoch
    result = []
    for epoch in epochs:
        state_vector = json.loads(database.get(epoch))
        result.append({
            "epoch": epoch,
            "state_vector": state_vector
        })

    return result

# Original route: returns state vectors for epoch
@station_tracker.route('/epochs/<epoch>', methods=['GET'])
def get_epoch(epoch):
    """
    Returns state vector for specific epoch

    Args: epoch (int): number that specifies which epoch

    Returns: data (List[dict]) dictionary value of that specified epoch
    """
    if not database.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(database.get(epoch))
    return state_vector

# Original route: returns specific epoch speed
@station_tracker.route('/epochs/<epoch>/speed', methods=['GET'])
def get_epoch_speed(epoch):
    """
    Returns speed of specific epoch

    Args: epoch (int): number that specifies which epoch

    Returns: speed (int) calculated speed of specified epoch using the X Y and Z dots
    """
    if not database.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(database.get(epoch))

    X = float(state_vector['X_DOT']['#text'])
    Y = float(state_vector['Y_DOT']['#text'])
    Z = float(state_vector['Z_DOT']['#text'])
    speed = np.sqrt(np.square(X) + np.square(Y) + np.square(Z))
    return {"speed": speed}

# Original route: returns closest epoch to 'now'
@station_tracker.route('/now', methods=['GET'])
def get_now():
    """
    Returns the state vectors of the epoch closest to 'now'

    Args: None

    Returns: closest_data (List[dict]): state vectors of epoch with time closest to 'now'
    """
    current_time = time.mktime(time.gmtime())
    closest_epoch = None
    closest_diff = float('inf')

    # searches all keys in Redis
    for epoch in database.keys():
        epoch = epoch.decode()
        epoch_str = epoch.split('.')[0]
        epoch_time = time.mktime(time.strptime(epoch_str, '%Y-%jT%H:%M:%S'))
        time_diff = np.abs(current_time - epoch_time)

        if time_diff < closest_diff:
            closest_diff = time_diff
            closest_epoch = epoch

    if closest_epoch:
       
        state_vector = json.loads(database.get(closest_epoch))

        lat, lon, alt = calculate_earth_coordinates(state_vector)

        #taken from hint posted
        geocoder = Nominatim(user_agent='iss_tracker')
        geoloc = geocoder.reverse((lat, lon), zoom=15, language='en')

        return {
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "geoloc": geoloc.address if geoloc else "Unknown location",
            "epoch_timestamp": closest_epoch,
            "now_timestamp": time.strftime('%m/%d/%Y, %H:%M:%S', time.gmtime())
        }
    return {"error": "No data available"}, 404

# Original route: Returns location for a specific epoch
@station_tracker.route('/epochs/<epoch>/location', methods=['GET'])
def get_epoch_location(epoch):
    """
    Returns latitude, longitude, altitude, and geoposition for a given epoch.

    Args: epoch (str): Epoch identifier.

    Returns: dict: Contains latitude, longitude, altitude, and geoposition.
    """
    if not database.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(database.get(epoch))

    lat, lon, alt = calculate_earth_coordinates(state_vector)

    geocoder = Nominatim(user_agent='iss_tracker')
    geoloc = geocoder.reverse((lat, lon), zoom=15, language='en')

    return {
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "geoloc": geoloc.address if geoloc else "Unknown location",
        "epoch_timestamp": epoch
    }

# Initialize data on startup if database is empty
if not database.keys():
    fetch_orbital_data()

def main():
    fetch_orbital_data()
    station_tracker.run(debug=True, host='0.0.0.0')

if __name__ == '__main__':
    main()
