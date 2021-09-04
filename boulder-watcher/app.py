import os
import boto3
import time
import requests
import json
from aws_lambda_powertools import Tracer

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
        print("Fetched crowd indicator succesful: {}".format(
            response.text.encode('utf8')))
        return json.loads(response.text.encode('utf8'))

    else:
        print("Request failed with: {}".format(response.status_code))
        print("And body: " + response.text.encode('utf8'))

        return None


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


@tracer.capture_lambda_handler
def handler(event, context):
    print("Started fetching of {} at {}".format(BOULDER_URL, time.ctime()))
    crowd_indicator = get_crowd_indicator()

    crowd_level = extract_crowd_level(crowd_indicator)
    print("Current crowd level: {}".format(crowd_level))

    store_crowd_level(crowd_level)
