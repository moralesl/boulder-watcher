import os
import re
import boto3
import time
import requests
import json
from datetime import datetime
from aws_lambda_powertools import Tracer

tracer = Tracer(service='boulder-watcher')

timestream = boto3.client('timestream-write')


BOULDER_URL = os.environ['BOULDER_URL']
LOCATION = os.environ['LOCATION']
JWT_TOKEN = os.environ['JWT_TOKEN']

# Extract table name and database name
timestream_environment = os.environ['TABLE_NAME']
DATABASE_NAME = timestream_environment.split('|')[0]
TABLE_NAME = timestream_environment.split('|')[1]


PATH = "https://www.boulderado.de/boulderadoweb/gym-clientcounter/index.php?mode=get&token={token}&ampel=1"
CROWD_LEVEL_PATTERN = re.compile("left:\s+(\d+)%")

def get_url():
    return PATH.format(token = JWT_TOKEN)


@tracer.capture_method
def get_crowd_indicator():
    response = requests.request("GET", get_url())

    if response.ok:
        print("Fetched raw crowd indicator succesful: {}".format(
            response.text.encode('utf8')))
        return response.text

    else:
        print("Request failed with: {}".format(response.status_code))
        print("And body: " + response.text.encode('utf8'))

        return None


def extract_crowd_level(crowd_indicator):
    return re.search(CROWD_LEVEL_PATTERN, crowd_indicator).group(1)


@tracer.capture_method
def store_crowd_level(crowd_level):
    timestream.write_records(
        DatabaseName=DATABASE_NAME,
        TableName=TABLE_NAME,
        CommonAttributes={},
        Records=[{
            'Dimensions': [
                {'Name': 'location', 'Value': LOCATION}
            ],
            'MeasureName': 'crowd_lvl',
            'MeasureValue': crowd_level,
            'MeasureValueType': 'DOUBLE',
            'Time': current_millis_time()
        }]
    )

def current_millis_time():
        return str(int(round(time.time() * 1000)))


def is_after_opening_time():
    now = datetime.now()
    today5am = now.replace(hour=5, minute=0, second=0, microsecond=0)

    is_after = today5am < now

    print("Is after opening time: " + str(is_after))
    return is_after


def is_before_closing_time():
    now = datetime.now()
    today12am = now.replace(hour=23, minute=59, second=59, microsecond=0)

    is_before = today12am > now

    print("Is before closing time: " + str(is_before))
    return is_before


def is_within_opening_hours():
    return is_after_opening_time() and is_before_closing_time()


@tracer.capture_lambda_handler
def handler(event, context):
    print("Start checking crowd level")

    if is_within_opening_hours():
        print("Started fetching of {} at {}".format(BOULDER_URL, time.ctime()))
        crowd_indicator = get_crowd_indicator()

        crowd_level = extract_crowd_level(crowd_indicator)
    else:
        print("It is outside of the opening hours")
        crowd_level = str(0)

    print("Current crowd level: {}".format(crowd_level))
    store_crowd_level(crowd_level)
