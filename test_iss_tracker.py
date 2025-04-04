import pytest
import numpy as np
from iss_tracker import station_tracker, fetch_orbital_data, database
import redis

@pytest.fixture 
def client():
    """
    Fixture to set up the Flask test client and initialize Redis with ISS data
    """
    database.flushdb()
    fetch_orbital_data()
    with station_tracker.test_client() as client:
        yield client

def test_get_epochs(client):
    """
    Tests the /epochs endpoint along with response limit and offset
    """
    response = client.get('/epochs')
    data = response.get_json()
    assert len(data) > 0

    response_limit = client.get('/epochs?limit=5')
    data_limit = response_limit.get_json()
    assert len(data_limit) == 5

    response_offset = client.get('/epochs?limit=5&offset=2')
    data_offset = response_offset.get_json()
    assert len(data_offset) == 5

def test_get_epoch(client):
    """
    Checks if requesting the first epoch actually returns the first epoch
    """
    response = client.get('/epochs')
    data = response.get_json()
    first_epoch = data[0]['epoch']

    first_response = client.get(f'/epochs/{first_epoch}')
    first_response_data = first_response.get_json()

    assert first_response_data['EPOCH'] == first_epoch

def test_get_epoch_speed(client):
    """
    Checks if the speed of the first epoch is accurate
    """
    response = client.get('/epochs')
    data = response.get_json()
    first_epoch = data[0]['epoch']

    first_response = client.get(f'/epochs/{first_epoch}')
    first_response_data = first_response.get_json()

    X = float(first_response_data['X_DOT']['#text'])
    Y = float(first_response_data['Y_DOT']['#text'])
    Z = float(first_response_data['Z_DOT']['#text'])
    first_speed = np.sqrt(np.square(X) + np.square(Y) + np.square(Z))

    speed_response = client.get(f'/epochs/{first_epoch}/speed')
    speed_data = speed_response.get_json()

    assert float(speed_data['speed']) == float(first_speed)

def test_get_now(client):
    """
    Checks if /now returns valid location and speed data
    """
    now_response = client.get('/now')
    now_data = now_response.get_json()

    assert 'lat' in now_data
    assert 'lon' in now_data
    assert 'alt' in now_data
    assert 'geoloc' in now_data
    assert 'epoch_timestamp' in now_data
    assert 'now_timestamp' in now_data

    # Checks if lat, lon, and alt are valid
    try:
        float(now_data['lat'])
        float(now_data['lon'])
        float(now_data['alt'])
    except (ValueError, TypeError):
        assert False, "Latitude, longitude, or altitude is not a valid float"

    # Checks if geolocation is a string
    assert isinstance(now_data['geoloc'], str)

    # Checks if timestamps are strings
    assert isinstance(now_data['epoch_timestamp'], str)
    assert isinstance(now_data['now_timestamp'], str)

def test_get_epoch_location(client):
    """
    Checks if /epochs/<epoch>/location returns valid location data
    """
    response = client.get('/epochs')
    data = response.get_json()
    first_epoch = data[0]['epoch']

    # Request location data for the first epoch
    location_response = client.get(f'/epochs/{first_epoch}/location')
    location_data = location_response.get_json()

    assert 'lat' in location_data
    assert 'lon' in location_data
    assert 'alt' in location_data
    assert 'geoloc' in location_data
    assert 'epoch_timestamp' in location_data

    # Checks if lat, lon, and alt are valid
    try:
        float(location_data['lat'])
        float(location_data['lon'])
        float(location_data['alt'])
    except (ValueError, TypeError):
        assert False, "Latitude, longitude, or altitude is not a valid float"

    # Checks if geolocation is a string
    assert isinstance(location_data['geoloc'], str)

    # Checks if epoch timestamp is a string
    assert isinstance(location_data['epoch_timestamp'], str)
