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

rd = redis.Redis(host='redis-db', port=6379, db=0)

app = Flask(__name__)

def load_iss_data():  # copied from main() function from previous homework
    '''
    This function loads the data so it's easier for future flask functions to access

    Args: None

    Returns: global variable that has the parsed data
    '''
    url = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml"
    response = requests.get(url)

    # returns error if it's not read in properly
    if response.text == ' ':
        logging.error('Data was not imported successfully')

    data = xmltodict.parse(response.text)
    state_vectors = data['ndm']['oem']['body']['segment']['data']['stateVector']

    # store each state vector in Redis using EPOCH as the key
    for sv in state_vectors:
        epoch = sv['EPOCH']
        rd.set(epoch, json.dumps(sv))  # serialize the state vector as a JSON string

#given in Frequently Encountered Problems
def compute_location_astropy(sv):
    """
    Computes latitude, longitude, and altitude using astropy.

    Args:
        sv (dict): State vector containing X, Y, Z, and EPOCH.

    Returns:
        tuple: (latitude, longitude, altitude)
    """
    x = float(sv['X']['#text'])
    y = float(sv['Y']['#text'])
    z = float(sv['Z']['#text'])

    this_epoch = time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(sv['EPOCH'][:-5], '%Y-%jT%H:%M:%S'))

    cartrep = coordinates.CartesianRepresentation([x, y, z], unit=units.km)
    gcrs = coordinates.GCRS(cartrep, obstime=this_epoch)
    itrs = gcrs.transform_to(coordinates.ITRS(obstime=this_epoch))
    loc = coordinates.EarthLocation(*itrs.cartesian.xyz)

    return loc.lat.value, loc.lon.value, loc.height.value

# returns entire list of epochs
@app.route('/epochs', methods=['GET'])
def get_epochs():
    """
    Returns the list of epochs and their state vectors, with optional limit and offset.

    Args: None

    Returns: List of dictionaries containing epochs and their state vectors.
    """
    limit = request.args.get('limit', default=None, type=int)
    offset = request.args.get('offset', default=0, type=int)

    # get all keys (epochs) from Redis
    epochs = rd.keys()
    epochs = [epoch.decode() for epoch in epochs]

    # Apply limit and offset
    if limit is not None:
        epochs = epochs[offset:offset + limit]
    else:
        epochs = epochs[offset:]

    # get state vectors for each epoch
    result = []
    for epoch in epochs:
        state_vector = json.loads(rd.get(epoch))
        result.append({
            "epoch": epoch,
            "state_vector": state_vector
        })

    return result

# returns state vectors for epoch
@app.route('/epochs/<epoch>', methods=['GET'])
def get_epoch(epoch):
    """
    Returns state vector for specific epoch

    Args: epoch (int): number that specifies which epoch

    Returns: data (List[dict]) dictionary value of that specified epoch
    """
    if not rd.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(rd.get(epoch))
    return state_vector

# returns specific epoch speed
@app.route('/epochs/<epoch>/speed', methods=['GET'])
def get_epoch_speed(epoch):
    """
    Returns speed of specific epoch

    Args: epoch (int): number that specifies which epoch

    Returns: speed (int) calculated speed of specified epoch using the X Y and Z dots
    """
    if not rd.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(rd.get(epoch))

    X = float(state_vector['X_DOT']['#text'])
    Y = float(state_vector['Y_DOT']['#text'])
    Z = float(state_vector['Z_DOT']['#text'])
    speed = np.sqrt(np.square(X) + np.square(Y) + np.square(Z))
    return {"speed": speed}

# returns closest epoch to 'now'
@app.route('/now', methods=['GET'])
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
    for epoch in rd.keys():
        epoch = epoch.decode()
        epoch_str = epoch.split('.')[0]
        epoch_time = time.mktime(time.strptime(epoch_str, '%Y-%jT%H:%M:%S'))
        time_diff = np.abs(current_time - epoch_time)

        if time_diff < closest_diff:
            closest_diff = time_diff
            closest_epoch = epoch

    if closest_epoch:
       
        state_vector = json.loads(rd.get(closest_epoch))

        lat, lon, alt = compute_location_astropy(state_vector)

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

# Returns location for a specific epoch
@app.route('/epochs/<epoch>/location', methods=['GET'])
def get_epoch_location(epoch):
    """
    Returns latitude, longitude, altitude, and geoposition for a given epoch.

    Args: epoch (str): Epoch identifier.

    Returns: dict: Contains latitude, longitude, altitude, and geoposition.
    """
    if not rd.exists(epoch):
        return {"error": "Epoch not found"}, 404

    # retrieve the state vector from Redis and deserialize it
    state_vector = json.loads(rd.get(epoch))

    lat, lon, alt = compute_location_astropy(state_vector)

    geocoder = Nominatim(user_agent='iss_tracker')
    geoloc = geocoder.reverse((lat, lon), zoom=15, language='en')

    return {
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "geoloc": geoloc.address if geoloc else "Unknown location",
        "epoch_timestamp": epoch
    }

# load data into Redis on startup
if not rd.keys():
    load_iss_data()

# loads data first
def main():
    load_iss_data()
    app.run(debug=True, host='0.0.0.0')

if __name__ == '__main__':
    main()
