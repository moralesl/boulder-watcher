import os
import re
import boto3
import time
import requests
from datetime import datetime
from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit


log = Logger(service=os.environ['LOCATION'], sample_rate=1, level='DEBUG')
tracer = Tracer(service='boulder-watcher')
metrics = Metrics()

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
    log.debug("Request completed")

    if response.ok:
        log.debug(f"Fetched raw crowd indicator succesful: {response.text.encode('utf8')}")
        return response.text

    else:
        log.error("Request failed with status code {response.status_code}: {response.text.encode('utf8')}")

        return None


# Extract from payload: \r\n\t\t\t\t\t<!DOCTYPE html>\r\n\t\t\t\t\t<html lang="de">\r\n\t\t\t\t\t <head>\r\n\t\t\t\t\t <meta charset="utf-8" />\r\n\t\t\t\t\t <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1" />\r\n\t\t\t\t\t\t<meta http-equiv="X-UA-Compatible" content="IE=edge">\r\n\t\t\t\t\t <link rel="stylesheet" type="text/css" href="css/public_ampel.css">\r\n\t\t\t\t<link rel="stylesheet" href="/fonts/asap.css" as="style">\r\n\t\t\t\t <title>Boulderado Counter</title>\r\n\t\t\t\t </head>\r\n\t\t\t\t <body>\r\n\t\t\t\t\t<div id="visitorcount-container" class="freepercent1 ">\r\n\t\t\t\t<div class="actcounter zoom"><div class="actcounter-content"><div class="pointer-container"><div style="position: absolute;\tleft: 24%; top: 50%; transform: translate(-24%, -50%)" class="pointer-image"></div></div></div></div>\r\n\t\t\t\t\t\t</div>\r\n\t\t\t\t\t </body>\r\n\t\t\t\t\t</html>\r\n\t\t\t\t
# => 24
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

    log.debug(f"Is after opening time: {is_after}")
    return is_after


def is_before_closing_time():
    now = datetime.now()
    today10pm = now.replace(hour=22, minute=0, second=0, microsecond=0)

    is_before = today10pm > now

    log.debug(f"Is before closing time: {is_before}")
    return is_before


def is_within_opening_hours():
    return is_after_opening_time() and is_before_closing_time()


@metrics.log_metrics
@tracer.capture_lambda_handler
def handler(event, context):
    log.info("Start checking crowd level")

    if is_within_opening_hours():
        metrics.add_metric(name="WithinOpeningHours", unit=MetricUnit.Percent, value=1)
        log.debug("It is within the opening hours")
        crowd_indicator = get_crowd_indicator()
        log.debug(f"Fetched crowd indicator of {BOULDER_URL} at {time.ctime()}: {crowd_indicator}")

        crowd_level = extract_crowd_level(crowd_indicator)

        if not crowd_level:
            metrics.add_metric(name="ErrorFetchCrowdIndicator", unit=MetricUnit.Count, value=1)
            log.error("No crowd indicator available")
            raise ValueError('No crowd indicator available')

    else:
        metrics.add_metric(name="WithinOpeningHours", unit=MetricUnit.Percent, value=0)
        log.debug("It is outside of the opening hours")
        crowd_level = str(0)

    metrics.add_metric(name="SuccessfulFetchCrowdIndicator", unit=MetricUnit.Count, value=1)
    metrics.add_metric(name="CrowdLevel", unit=MetricUnit.Percent, value=float(crowd_level))

    log.info(f"Current crowd level: {crowd_level}")
    store_crowd_level(crowd_level)
    log.debug("Persisted crowd level")
