import os
import re
import boto3
import time
import json
from datetime import datetime
from urllib import request
from pyquery import PyQuery as pq
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

# Extract table name and database name
timestream_environment = os.environ['TABLE_NAME']
DATABASE_NAME = timestream_environment.split('|')[0]
TABLE_NAME = timestream_environment.split('|')[1]


PATH = "/wp-admin/admin-ajax.php"
PAYLOAD = {'action': 'cxo_get_crowd_indicator'}
CROWD_LEVEL_PATTERN = re.compile("margin-left:\s*(\d+\.?\d*)%")


def get_url():
    return BOULDER_URL + PATH


@tracer.capture_method
def get_crowd_indicator():
    crowd_indicator = fetch_crowd_indicator_from_api()
    if crowd_indicator:
        log.info(f"Fetched crowd indicator from API: {crowd_indicator}")
        return extract_crowd_level_from_api(crowd_indicator)

    html_body = fetch_crowd_indicator_from_html()
    if html_body:
        log.info("Fetched crowd indicator from HTML")
        return extract_crowd_level_from_html(html_body)

    log.error("Crowd indicator couldn't been fetched")
    return None


@tracer.capture_method
def fetch_crowd_indicator_from_html():
    return pq(url=BOULDER_URL)

# Extract from payload: 'margin-left:28.3%'
# => 28.3
@tracer.capture_method
def extract_crowd_level_from_html(html_body):
    if html_body:
        log.debug(f"HTML body: {html_body.html()}")
        style = html_body('#cxo-crowd-indicator .crowd-level-pointer img').attr('style')
        if style:
            log.debug(f"Style is: {style}")
            return re.search(CROWD_LEVEL_PATTERN, style).group(1)

    log.debug("Nothing could be extracted")
    return None

@tracer.capture_method
def fetch_crowd_indicator_from_api():
    try:
        request = request.Request(get_url, data=PAYLOAD, method="POST")
        response = request.urlopen(request)
        response_text = response.read().decode('utf8')

        log.debug("Request completed")

        if response.status == 200:
            log.debug(f"Fetched crowd indicator successful: {response_text}")

            payload = json.loads(response_text)

            if payload['success']:
                log.debug("Request has been successful")

                return payload
            else:
                log.warning(f"Request hasn't been successful: {payload}")

                return None

        else:
            log.warning(f"Request failed with status code {response.status}: {response_text}")

            return None

    except Exception as e:
        log.error(f"An error occurred during the request: {e}")
        return None


# Extract from payload: {"level":11,"success":true}
# => 11
def extract_crowd_level_from_api(crowd_indicator):
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
        crowd_level = get_crowd_indicator()
        log.debug(f"Fetched crowd indicator of {BOULDER_URL} at {time.ctime()}: {crowd_level}")

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
