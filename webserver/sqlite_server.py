"""
This web api server save data to sqlite for tesing or temporary use.
Standard library only, easy to deploy.
"""
import sys
import sqlite3
import json
import getopt
from typing import List
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from data_server import Data_Server, Monitor_Message, Minutes_Record, Hours_Record, Minutes_Record_Encoder, Hours_Record_Encoder


class Sqlite_Server(Data_Server):
    TB_MINUTES = 'ft8mon_minutes'
    TB_HOURS = 'ft8mon_hours'
    RETURN_RECORD_LIMIT = 100

    def __init__(self, dbconn: sqlite3.Connection) -> None:
        super().__init__()
        self.dbconn = dbconn
        #check tables exist...
        for row in dbconn.execute(f"SELECT count(name) FROM sqlite_master WHERE type='table' AND name='{self.TB_MINUTES}'"):
            if row[0] != 1:
                dbconn.execute(f"""CREATE TABLE {self.TB_MINUTES} (
                    ctime int NOT NULL,
                    monitor varchar(255) NOT NULL,
                    band varchar(32) NOT NULL,
                    messages varchar(4000) NOT NULL,
                    total int NOT NULL,
                    snr int NOT NULL,
                    countries varchar(1000) NOT NULL,
                    cqs varchar(1000) NOT NULL,
                    callers varchar(1000) NOT NULL,
                    PRIMARY KEY (ctime)
                )""")
                dbconn.commit()
        for row in dbconn.execute(f"SELECT count(name) FROM sqlite_master WHERE type='table' AND name='{self.TB_HOURS}'"):
            if row[0] != 1:
                dbconn.execute(f"""CREATE TABLE {self.TB_HOURS} (
                    ctime int NOT NULL,
                    monitor varchar(255) NOT NULL,
                    band varchar(32) NOT NULL,
                    total int NOT NULL,
                    snr int NOT NULL,
                    countries varchar(1000) NOT NULL,
                    cqs varchar(1000) NOT NULL,
                    PRIMARY KEY (ctime)
                )""")
                dbconn.commit()

    def db_upsert_minute(self, monitor:str, band: str, data: Minutes_Record) -> str | None:
        rec = {
            'ctime': data.ctime,
            'monitor': data.monitor,
            'band': data.band,
            'messages': data.messages,
            'total': data.total,
            'snr': data.snr,
            'countries': json.dumps(data.countries),
            'cqs': json.dumps(data.cqs),
            'callers': json.dumps(data.callers)
        }
        try:
            row = self.dbconn.execute(f"SELECT COUNT(*) FROM {self.TB_MINUTES} WHERE ctime=:ctime AND monitor=:monitor AND band=:band", rec).fetchone()
            if row[0] == 0:
                self.dbconn.execute(f"INSERT INTO {self.TB_MINUTES} VALUES(:ctime, :monitor, :band, :messages, :total, :snr, :countries, :cqs, :callers)", rec)
            else:
                self.dbconn.execute(f"""UPDATE {self.TB_MINUTES}
                                    SET 
                                    messages=:messages,
                                    total=:total,
                                    snr=:snr,
                                    countries=:countries,
                                    cqs=:cqs,
                                    callers=:callers
                                    WHERE 
                                    ctime=:ctime AND monitor=:monitor AND band=:band
                                    """, rec)
            self.dbconn.commit()
        except sqlite3.Error as err:
            return f'sqlite err: {err}'

        return None


    def db_read_minutes(self, monitor:str, band: str, begin: int, end: int) -> List[Minutes_Record]:
        recs: List[Minutes_Record] = []
        try:
            p = {
                'monitor': monitor,
                'band': band,
                'begin': begin,
                'end': end
            }
            for row in self.dbconn.execute(f"SELECT * FROM {self.TB_MINUTES} WHERE ctime>=:begin AND ctime<=:end AND monitor=:monitor AND band=:band LIMIT {self.RETURN_RECORD_LIMIT}", p):
                rec = Minutes_Record(
                    ctime=row['ctime'],
                    monitor=row['monitor'],
                    band=row['band'],
                    messages=row['messages'],
                    total=row['total'],
                    snr=row['snr'],
                    countries=json.loads(row['countries']),
                    cqs=json.loads(row['cqs']),
                    callers=json.loads(row['callers'])
                )
                recs.append(rec)

        except (ValueError, sqlite3.Error):
            return []
        return recs


    def db_upsert_hour(self, monitor:str, band: str, data: Hours_Record) -> str | None:
        rec = {
            'ctime': data.ctime,
            'monitor': data.monitor,
            'band': data.band,
            'total': data.total,
            'snr': data.snr,
            'countries': json.dumps(data.countries),
            'cqs': json.dumps(data.cqs)
        }
        try:
            row = self.dbconn.execute(f"SELECT COUNT(*) FROM {self.TB_HOURS} WHERE ctime=:ctime AND monitor=:monitor AND band=:band", rec).fetchone()
            if row[0] == 0:
                self.dbconn.execute(f"INSERT INTO {self.TB_HOURS} VALUES(:ctime, :monitor, :band, :total, :snr, :countries, :cqs)", rec)
            else:
                self.dbconn.execute(f"""UPDATE {self.TB_HOURS}
                                    SET 
                                    total=:total, snr=:snr, countries=:countries, cqs=:cqs
                                    WHERE 
                                    ctime=:ctime AND monitor=:monitor AND band=:band
                                    """, rec)
            self.dbconn.commit()
        except sqlite3.Error as err:
            return f'sqlite err: {err}'

        return None

    def db_read_hours(self, monitor:str, band: str, begin: int, end: int) -> List[Hours_Record]:
        recs: List[Hours_Record] = []
        try:
            p = {
                'monitor': monitor,
                'band': band,
                'begin': begin,
                'end': end
            }
            for row in self.dbconn.execute(f"SELECT * FROM {self.TB_HOURS} WHERE ctime>=:begin AND ctime<=:end AND monitor=:monitor AND band=:band LIMIT {self.RETURN_RECORD_LIMIT}", p):
                recs.append(Hours_Record(
                    ctime=row['ctime'],
                    monitor=row['monitor'],
                    band=row['band'],
                    total=row['total'],
                    snr=row['snr'],
                    countries=json.loads(row['countries']),
                    cqs=json.loads(row['cqs'])
                ))
        except (ValueError, sqlite3.Error):
            return []
        return recs

DEFAULT_ADDR = '0.0.0.0'
DEFAULT_PORT = 8080
DEFAULT_DBFILE = 'db.sqlite'
DEFAULT_TOKEN = '112233445566'

ROUTE_GET_HOURS = '/hours'
ROUTE_GET_MINUTES = '/minutes'
ROUTE_REPORT = '/report'

def usage():
    print(f"""Simple web api server for ft8 monitor, use sqlite as database. Apis:
                http://ip:port{ROUTE_REPORT}?token=xxx&id=xxx                           monitor report api
                http://ip:port{ROUTE_GET_MINUTES}?id=xxx&band=xxx&begin=xxx&end=xxx     get minutes data. xxx is epoch time in second
                http://ip:port{ROUTE_GET_HOURS}?id=xxx&band=xxx&begin=xxx&end=xxx       get hours data. xxx is epoch time in second
                
            Note: The maximum 100 records can be returned in one get.

            -h, --help                      Print this message
            -a, --address={DEFAULT_ADDR}    server listen address
            -p, --port={DEFAULT_PORT}       server listen port
            -f, --dbfile={DEFAULT_DBFILE}   db file path
            -t, --token={DEFAULT_TOKEN}     monitor api password
        """)
def MakeContextHTTPRequestHandler(dbserver: Sqlite_Server, token: str):
    class ApiHandler(BaseHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            self.dbserver = dbserver
            self.token = token
            super().__init__(*args, **kwargs)

        def do_GET(self):
            begin, end, monitor, band = None, None, None, None
            try:
                parse_result = urlparse(self.path)
                dict_result = parse_qs(parse_result.query)
                begin = int(dict_result.get('begin')[0])
                end = int(dict_result.get('end')[0])
                monitor = dict_result.get('id')[0]
                band = dict_result.get('band')[0]
            except (ValueError, TypeError):
                pass
            if monitor is None or band is None or begin > end:
                self.send_response(400)
                self.end_headers()
                self.wfile.write('Bad request params\n'.encode('utf-8'))
                return
            if self.path.startswith(ROUTE_GET_MINUTES):
                recs = self.dbserver.db_read_minutes(monitor=monitor, band=band, begin=begin, end=end)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(recs, cls=Minutes_Record_Encoder).encode('utf-8'))

            elif self.path.startswith(ROUTE_GET_HOURS):
                recs = self.dbserver.db_read_hours(monitor=monitor, band=band, begin=begin, end=end)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(recs, cls=Hours_Record_Encoder).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write('Route not found\n'.encode('utf-8'))


        def do_POST(self):
            monitor, token, band = '', '', ''
            band_data: List[Monitor_Message] = []
            try:
                parse_result = urlparse(self.path)
                dict_result = parse_qs(parse_result.query)
                monitor = dict_result.get('id')[0]
                token = dict_result.get('token')[0]
                band = dict_result.get('band')[0]
            except (ValueError, TypeError) as err:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f'Bad request params:\n{err}'.encode('utf-8'))
                return
            if monitor == '':
                self.send_response(400)
                self.end_headers()
                self.wfile.write('Bad request params:\n lack monitor'.encode('utf-8'))
                return
            if token != self.token:
                self.send_response(401)
                self.end_headers()
                self.wfile.write('Unauthenticated\n'.encode('utf-8'))
                return

            try:
                content_length = int(self.headers['Content-Length'])
                payload = self.rfile.read(content_length)
                payload = json.loads(payload)
                for m in payload:
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
            except (json.JSONDecodeError, ValueError, TypeError) as err:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f'Bad json body:\n{err}'.encode('utf-8'))

            r = self.dbserver.save_monitor_data(monitor=monitor, band=band, data=band_data)
            if r is not None:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f'Server error when save data:\n{r}'.encode('utf-8'))
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write('success'.encode('utf-8'))

    return ApiHandler

def main() -> None:
    try:
        opts, _ = getopt.getopt(sys.argv[1:], "ha:p:f:t:", ["help", "address=", "port=", "dbfile=", "token="])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    addr = DEFAULT_ADDR
    port = DEFAULT_PORT
    dbfile = DEFAULT_DBFILE
    token = DEFAULT_TOKEN
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-a", "--address"):
            addr = a
        elif o in ("-p", "--port"):
            port = int(a)
        elif o in ("-f", "--dbfile"):
            dbfile = a
        elif o in ("-t", "--token"):
            token = a
        else:
            assert False, "unhandled option!"

    try:
        conn = sqlite3.connect(dbfile)
        conn.row_factory = sqlite3.Row
        ds = Sqlite_Server(conn)
        httpd = HTTPServer((addr, port), MakeContextHTTPRequestHandler(dbserver=ds, token=token))
        print(f'Starts ft8mon api server at {addr}:{port}')
        httpd.serve_forever()
    except KeyboardInterrupt:
        conn.close()
        httpd.server_close()
        print('Stopping ft8mon api server...')


if __name__ == '__main__' :
    main()
