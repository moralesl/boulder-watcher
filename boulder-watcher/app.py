import os
import boto3
import time
import requests
import json
from datetime import datetime
from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer


log = Logger(service=os.environ['LOCATION'], sample_rate=1, level='DEBUG')
tracer = Tracer(service='boulder-watcher')

timestream = boto3.client('timestream-write')


BOULDER_URL = os.environ['BOULDER_URL']
LOCATION = os.environ['LOCATION']

# Extract table name and database name
timestream_environment = os.environ['TABLE_NAME']
DATABASE_NAME = timestream_environment.split('|')[0]
TABLE_NAME = timestream_environment.split('|')[1]


PATH = "/wp-admin/admin-ajax.php"
PAYLOAD = {'action': 'cxo_get_crowd_indicator'}


def get_url():
    return BOULDER_URL + PATH


@tracer.capture_method
def get_crowd_indicator():
    response = requests.request("POST", get_url(), data=PAYLOAD)

    if response.ok:
        log.debug("Fetched crowd indicator succesful: {}".format(
            response.text.encode('utf8')))

        payload = json.loads(response.text.encode('utf8'))

        if payload['success']:
            log.debug("Request has been succesful")

            return payload
        else:
            log.warn("Request hasn't been succesful", payload)

            return None

    else:
        log.error("Request failed with status code {}: {}".format(
            response.status_code, response.text.encode('utf8')))

        return None


# Extract from payload: {"level":11,"success":true}
# => 11
def extract_crowd_level(crowd_indicator):
    return str(
        crowd_indicator['level'])


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
    today7am = now.replace(hour=7, minute=0, second=0, microsecond=0)

    is_after = today7am < now

    log.debug("Is after opening time: " + str(is_after))
    return is_after


def is_before_closing_time():
    now = datetime.now()
    today10pm = now.replace(hour=22, minute=0, second=0, microsecond=0)

    is_before = today10pm > now

    log.debug("Is before closing time: " + str(is_before))
    return is_before


def is_within_opening_hours():
    return is_after_opening_time() and is_before_closing_time()


@tracer.capture_lambda_handler
def handler(event, context):
    log.info("Start checking crowd level")

    if is_within_opening_hours():
        crowd_indicator = get_crowd_indicator()
        log.debug("Fetched crowd indicator of {} at {}: {}".format(BOULDER_URL, time.ctime(), crowd_indicator))

        if not crowd_indicator:
            log.error("No crowd indicator available")
            raise ValueError('No crowd indicator available')

        crowd_level = extract_crowd_level(crowd_indicator)
    else:
        log.debug("It is outside of the opening hours")
        crowd_level = str(0)

    log.info("Current crowd level: {}".format(crowd_level))
    store_crowd_level(crowd_level)
    log.debug("Persisted crowd level")
