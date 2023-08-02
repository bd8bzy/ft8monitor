"""
A amazon AWS Lambda function for API Gateway, use Dynamodb storing data.
Note: 
1. You should upload this script together with data_server.py.
2. Need dynamodb's DescribeTable/CreateTable/Query/PutItem policies.
3. First time run take 20~30s to create tables, you should set lambda execute timeout 30s+. Or you can create dynamodb tables manually.
4. You may need to open cors on AWS API gateway service.
"""
import json
from os import environ
from typing import List
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from data_server import Data_Server, Monitor_Message, Minutes_Record, Hours_Record, Minutes_Record_Encoder, Hours_Record_Encoder


class Dynamodb_Server(Data_Server):
    """Data server with AWS Dynamodb as backend.
        Note: Records query api limit to 1 MB of data size(by Dynamodb) AND RETURN_RECORD_LIMIT(by us) maximum count.
        Api user should do paginating on their client side(use ctime in the result set).
    """
    TB_MINUTES = 'ft8mon_minutes'
    TB_HOURS = 'ft8mon_hours'
    RETURN_RECORD_LIMIT = 720 #12 hours of minutes data or 30 days of hours data
    CAPACITY_UNITS = 5

    def __init__(self) -> None:
        super().__init__()
        self.dyn_resource = boto3.resource('dynamodb')
        self.table = {}
        if not self.tb_exists(self.TB_MINUTES):
            self.create_minutes_table()
        if not self.tb_exists(self.TB_HOURS):
            self.create_hours_table()

    def tb_exists(self, table_name):
        try:
            table = self.dyn_resource.Table(table_name)
            table.load()
            exists = True
        except ClientError as err:
            if err.response['Error']['Code'] == 'ResourceNotFoundException':
                exists = False
            else:
                print(f"Error(code {err.response['Error']['Code']}) when check table {table_name} exists: {err.response['Error']['Message']}")
                raise
        else:
            self.table[table_name] = table
        return exists

    def create_minutes_table(self):
        try:
            self.table[self.TB_MINUTES] = self.dyn_resource.create_table(
                TableName = self.TB_MINUTES,
                AttributeDefinitions = [
                    {
                        'AttributeName': 'monitor_band',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'ctime',
                        'AttributeType': 'N'
                    }
                ],
                KeySchema = [
                    {
                        'AttributeName': 'monitor_band',
                        'KeyType': 'HASH'
                    },
                    {
                        'AttributeName': 'ctime',
                        'KeyType': 'RANGE'
                    }
                ],
                ProvisionedThroughput = {
                    'ReadCapacityUnits': self.CAPACITY_UNITS,
                    'WriteCapacityUnits': self.CAPACITY_UNITS
                })
            self.table[self.TB_MINUTES].wait_until_exists()
        except ClientError as err:
            print(f"Error(code {err.response['Error']['Code']}) when create table {self.TB_MINUTES}: {err.response['Error']['Message']}")
            raise
        else:
            return self.table[self.TB_MINUTES]

    def create_hours_table(self):
        try:
            self.table[self.TB_HOURS] =  self.dyn_resource.create_table(
                TableName = self.TB_HOURS,
                AttributeDefinitions = [
                    {
                        'AttributeName': 'monitor_band',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'ctime',
                        'AttributeType': 'N'
                    }
                ],
                KeySchema=[
                    {
                        'AttributeName': 'monitor_band',
                        'KeyType': 'HASH'
                    },
                    {
                        'AttributeName': 'ctime',
                        'KeyType': 'RANGE'
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': self.CAPACITY_UNITS,
                    'WriteCapacityUnits': self.CAPACITY_UNITS
                })
            self.table[self.TB_HOURS].wait_until_exists()
        except ClientError as err:
            print(f"Error(code {err.response['Error']['Code']}) when create table {self.TB_HOURS}: {err.response['Error']['Message']}")
            raise
        else:
            return self.table[self.TB_HOURS]


    def db_upsert_minute(self, monitor:str, band: str, data: Minutes_Record) -> str | None:
        rec = {
            'monitor_band': f'{data.monitor}#{data.band}',
            'ctime': data.ctime,
            'messages': data.messages,
            'total': data.total,
            'snr': data.snr,
            'countries': json.dumps(data.countries),
            'cqs': json.dumps(data.cqs),
            'callers': json.dumps(data.callers)
        }
        try:
            self.table[self.TB_MINUTES].put_item(Item=rec)
        except ClientError as err:
            msg = f"Error(code {err.response['Error']['Code']}) when update table {self.TB_MINUTES}: {err.response['Error']['Message']}"
            print(msg)
            return msg
        else:
            return None


    def db_read_minutes(self, monitor:str, band: str, begin: int, end: int) -> List[Minutes_Record]:
        recs: List[Minutes_Record] = []
        try:
            for row in self.table[self.TB_MINUTES].query(
                KeyConditionExpression=Key('monitor_band').eq(f'{monitor}#{band}') & Key('ctime').between(begin, end),
                Limit=self.RETURN_RECORD_LIMIT
            )['Items']:
                mb = row['monitor_band'].split('#')
                rec = Minutes_Record(
                    ctime=int(row['ctime']), #note DynamoDB return Decimal even with a int(hate this!!!)
                    monitor=mb[0],
                    band=mb[1],
                    messages=row['messages'],
                    total=int(row['total']),
                    snr=int(row['snr']),
                    countries=json.loads(row['countries']),
                    cqs=json.loads(row['cqs']),
                    callers=json.loads(row['callers'])
                )
                recs.append(rec)

        except ClientError as err:
            print(f"Error(code {err.response['Error']['Code']}) when read table {self.TB_MINUTES}: {err.response['Error']['Message']}")
            return []
        return recs


    def db_upsert_hour(self, monitor:str, band: str, data: Hours_Record) -> str | None:
        rec = {
            'monitor_band': f'{data.monitor}#{data.band}',
            'ctime': data.ctime,
            'total': data.total,
            'snr': data.snr,
            'countries': json.dumps(data.countries),
            'cqs': json.dumps(data.cqs)
        }
        try:
            self.table[self.TB_HOURS].put_item(Item=rec)
        except ClientError as err:
            msg = f"Error(code {err.response['Error']['Code']}) when update table {self.TB_HOURS}: {err.response['Error']['Message']}"
            print(msg)
            return msg
        else:
            return None

    def db_read_hours(self, monitor:str, band: str, begin: int, end: int) -> List[Hours_Record]:
        recs: List[Hours_Record] = []
        try:
            for row in self.table[self.TB_HOURS].query(
                KeyConditionExpression=Key('monitor_band').eq(f'{monitor}#{band}') & Key('ctime').between(begin, end),
                Limit=self.RETURN_RECORD_LIMIT
            )['Items']:
                mb = row['monitor_band'].split('#')
                rec = Hours_Record(
                    ctime=int(row['ctime']),
                    monitor=mb[0],
                    band=mb[1],
                    total=int(row['total']),
                    snr=int(row['snr']),
                    countries=json.loads(row['countries']),
                    cqs=json.loads(row['cqs']),
                )
                recs.append(rec)

        except ClientError as err:
            print(f"Error(code {err.response['Error']['Code']}) when read table {self.TB_HOURS}: {err.response['Error']['Message']}")
            return []
        return recs


ROUTE_GET_HOURS = '/hours'
ROUTE_GET_MINUTES = '/minutes'
ROUTE_REPORT = '/report'

#init db, check or create tables
db = Dynamodb_Server()

def errorResp(code, reason):
    return {
        'statusCode': code,
        'headers': {
            "Content-Type": "application/json"
        },
        'body': reason
    }

def dataResp(strData):
    return {
        'statusCode': 200,
        'headers': {
            "Content-Type": "application/json"
        },
        'body': strData
    }

def lambda_handler(event, context): #pylint: disable=W0613
    '''Lambda funtion for ft8mon API gateway'''

    http_method = event['requestContext']['http']['method']
    query_string = event.get('queryStringParameters')
    if query_string is None:
        return errorResp(400, 'Bad Request, query params no found')

    rawPath = event.get('rawPath')
    if rawPath == ROUTE_REPORT:
        if http_method not in ('POST', 'PUT'):
            return errorResp(405, f'Method({http_method}) not allowed at this path {rawPath}')
        monitor = query_string.get('id')
        token = query_string.get('token')
        band = query_string.get('band')
        if monitor is None or len(monitor) == 0 or band is None or len(band) == 0:
            return errorResp(400, 'Bad Request, query params no found')
        token_from_env = environ.get('FT8_REPORT_TOKEN')
        if token_from_env is not None and token != token_from_env:
            return errorResp(401, 'Unauthenticated')

        body = event.get('body')
        try:
            band_data = []
            for m in json.loads(body):
                band_data.append(Monitor_Message(
                        gtime=m['time'],
                        raw=m['raw_message'],
                        snr=m['snr'],
                        dt=m['delta_t'],
                        df=m['delta_f'],
                        lf=m['lf'],
                        mtype=m['mtype'],
                        caller=m['caller'],
                        country=m['country'],
                        cq=m['zone_cq'],
                        itu=m['zone_itu'],
                        continent=m['continent'],
                        lat=m['lat'],
                        lon=m['lon'],
                        gmtoff=m['gmtoff'],
                        grid=m['grid'],
                        peer=m['peer']
                    ))
            r = db.save_monitor_data(monitor=monitor, band=band, data=band_data)
            if r is not None:
                return errorResp(502, f'Error when save data: {r}')
            else:
                return dataResp('"success"')
        except (json.decoder.JSONDecodeError, TypeError, ValueError) as err:
            return errorResp(400, f'Error when decode body: {err}')

    elif rawPath == ROUTE_GET_MINUTES:
        if http_method != 'GET':
            return errorResp(405, f'Method({http_method}) not allowed at this path {rawPath}')

        try:
            monitor = query_string.get('id')
            band = query_string.get('band')
            begin = int(query_string.get('begin'))
            end = int(query_string.get('end'))
            if monitor is None or len(monitor) == 0 or band is None or len(band) == 0:
                return errorResp(400, 'Bad Request with wrong query params')
            return dataResp(json.dumps(db.db_read_minutes(monitor=monitor, band=band, begin=begin, end=end), cls=Minutes_Record_Encoder))
        except (TypeError, ValueError) as err:
            return errorResp(400, f'Error when parse params: {err}')

    elif rawPath == ROUTE_GET_HOURS:
        if http_method != 'GET':
            return errorResp(405, f'Method({http_method}) not allowed at this path {rawPath}')

        try:
            monitor = query_string.get('id')
            band = query_string.get('band')
            begin = int(query_string.get('begin'))
            end = int(query_string.get('end'))
            if monitor is None or len(monitor) == 0 or band is None or len(band) == 0:
                return errorResp(400, 'Bad Request with wrong query params')
            return dataResp(json.dumps(db.db_read_hours(monitor=monitor, band=band, begin=begin, end=end), cls=Hours_Record_Encoder))
        except (TypeError, ValueError) as err:
            return errorResp(400, f'Error when parse params: {err}')
    else:
        return errorResp(404, 'Route not found')
