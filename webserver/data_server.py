from typing import List, Dict
import json
import time
from dataclasses import dataclass, field, asdict

@dataclass()
class Monitor_Message():
    gtime: int = 0                  #epoch time in second when monitor got this msg
    raw: str = ''                   #raw msg string before decode
    snr: int = 0                    #signal / noise rate
    dt: float = 0.0                 #delta time
    df: int = 0                     #delta frequency
    lf: bool = False                #low_confidence, mean hard to decode this msg
    mtype: str = 'UNKNOWN'          #'CQ'/'QRZ'/'DE'/'REPLAY'/'UNKNOWN'
    caller: str | None = None       #sender_callsign
    country: str | None = None      #sender country
    cq: str | None = None           #sender cq zone
    itu: str | None = None          #sender itu zone
    continent: str | None = None    #sender continent
    lat: float | None = None        #sender latitude in degrees, + for North
    lon: float | None = None        #sender longitude in degrees, + for West
    gmtoff: float | None = None     #sender local time offset from GMT
    grid: str | None = None         #sender 4-character grid
    peer: str | None = None         #callsign of the receiver

@dataclass()
class Minutes_Record():
    ctime: int = 0                          #epoch time in second when monitor got whose messages, but round to minute
    monitor: str  = 'ft8mon'                #monitor station id
    band: str = '50.313'                    #which ft8 band, 14.074 50.313 etc...
    messages: str = '[]'                    #raw messages got from monitor, in JSON string format
    total: int = 0                          #how many messages got in this minute window
    snr: int = 0                            #average snr for those messages
    countries: Dict[str, int] = field(default_factory=Dict[str, int])       #key for country name(Annobon Island, China...), value for how many messages sent from this country(by sender callsign)
    cqs: Dict[str, int] = field(default_factory=Dict[str, int])               #key for cq zone, value for how many messages sent from this cq zone
    callers: Dict[str, int] = field(default_factory=Dict[str, int])            #key for sender callsign, value for how many messages sent from this callsign

@dataclass()
class Hours_Record():
    ctime: int = 0                          #epoch time in second when monitor got whose messages, but round to hour.
    monitor: str  = 'ft8mon'                #monitor station id
    band: str = '50.313'                    #which ft8 band, 14.074 50.313 etc...
    total: int = 0                          #how many messages got in this hour window
    snr: int = 0                            #average snr for those messages
    countries: Dict[str, int] = field(default_factory=Dict[str, int])          #key for country name(Annobon Island, China...), value for how many messages sent from this country(by sender callsign)
    cqs: Dict[str, int] = field(default_factory=Dict[str, int])                #key for cq zone, value for how many messages sent from this cq zone

class Monitor_Message_Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Monitor_Message):
            return asdict(o)
        else:
            return super().default(o)

class Minutes_Record_Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Minutes_Record):
            return asdict(o)
        else:
            return super().default(o)

class Hours_Record_Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Hours_Record):
            return asdict(o)
        else:
            return super().default(o)

class Data_Server:
    """Base class for messages access. The implementation of the persistence layer should be provided by subclasses.
    
    Data is stored into two tables:
    1. ft8mon_minutes:  This table is used for storing ft8 msg with minute granularity.
                        Exact 1 record should exist every minute as long as the monitor is online. Empty list(messages:[]) for empty minute window.

    2. ft8mon_hours: This table is used for storing ft8 msg with hour granularity.
                    Exact 1 record should exist every hour as long as the monitor is online. total 0 indicates empty hour window.
    """
    def __init__(self) -> None:
        pass

    def db_upsert_minute(self, monitor:str, band: str, data: Minutes_Record) -> str | None:
        """Write a record to db, if already exist, update it."""
        raise NotImplementedError ("Needs to be define in sub-class")

    def db_read_minutes(self, monitor:str, band: str, begin: int, end: int) -> List[Minutes_Record]:
        """fetch records in db gtime betwin [begin, end]."""
        raise NotImplementedError ("Needs to be define in sub-class")

    def db_upsert_hour(self, monitor:str, band: str, data: Hours_Record) -> str | None:
        """Write a record to db, if already exist, update it."""
        raise NotImplementedError ("Needs to be define in sub-class")

    def db_read_hours(self, monitor:str, band: str, begin: int, end: int) -> List[Hours_Record]:
        """fetch records in db gtime betwin [begin, end]."""
        raise NotImplementedError ("Needs to be define in sub-class")



    def save_monitor_data(self, monitor:str, band: str, data: List[Monitor_Message]) -> str | None:
        """Call by monitor web api method, save those msg to minutes table and update hours table.
            Return None when success, or error messages when failure.
        """
        try:
            #do minutes table first...
            minutes = {}
            m_begin, m_end = 0, 0
            for msg in data:
                if msg.caller is None:
                    continue
                mt = msg.gtime - (msg.gtime % 60)
                m_begin = mt if m_begin == 0 else min(m_begin, mt)
                m_end = mt if m_end == 0 else max(m_end, mt)
                d = minutes.get(mt)
                if d is None:
                    minutes[mt] = {'messages': [msg], 'total': 1, 'snr': msg.snr, 'countries': {}, 'cqs': {}, 'callers': {}}
                    minutes[mt]['callers'][msg.caller] = 1
                    if msg.country is not None:
                        minutes[mt]['countries'][msg.country] = 1
                    if msg.cq is not None:
                        minutes[mt]['cqs'][msg.cq] = 1
                else:
                    d['messages'].append(msg)
                    d['total'] += 1
                    d['snr'] += msg.snr
                    d['callers'][msg.caller] = 1 if d['callers'].get(msg.caller) is None else d['callers'][msg.caller] + 1
                    if msg.country is not None:
                        d['countries'][msg.country] = 1 if d['countries'].get(msg.country) is None else d['countries'][msg.country] + 1
                    if msg.cq is not None:
                        d['cqs'][msg.cq] = 1 if d['cqs'].get(msg.cq) is None else d['cqs'][msg.cq] + 1

            if len(minutes.keys()) == 0:
                current_time = int(time.time())
                m_begin = current_time - current_time % 60
                m_end = m_begin
                recs = self.fetch_in_minutes(monitor=monitor, band=band, begin=m_begin, end=m_end)
                if len(recs) == 0:
                    #empty in db, write a idle record(no data yet station alive) for that station & band
                    self.db_upsert_minute(monitor=monitor, band=band, data=Minutes_Record(ctime=m_begin,
                        monitor=monitor,
                        band=band,
                        messages='[]',
                        total=0,
                        snr=0,
                        countries={},
                        cqs={},
                        callers={}
                        ))
            else:
                for mt, r in minutes.items():
                    r['snr'] = round(r['snr'] / r['total'])
                    recs = self.fetch_in_minutes(monitor=monitor, band=band, begin=mt, end=mt)
                    if len(recs) == 0:
                        #empty in db, write a new record
                        self.db_upsert_minute(monitor=monitor, band=band, data=Minutes_Record(
                            ctime=mt,
                            monitor=monitor,
                            band=band,
                            messages=json.dumps(r['messages'], cls=Monitor_Message_Encoder),
                            total=r['total'],
                            snr=r['snr'],
                            countries=r['countries'],
                            cqs=r['cqs'],
                            callers=r['callers']
                            ))
                    else:
                        #should have ONLY one record for that minute
                        dbrec = recs[0]
                        dmj = json.loads(dbrec.messages)
                        dmm: List[Monitor_Message] = []
                        for m in dmj:
                            dmm.append(Monitor_Message(**m))
                        dmm.extend(r['messages'])
                        dbrec.messages = json.dumps(dmm, cls=Monitor_Message_Encoder)
                        dbrec.snr = round((dbrec.snr * dbrec.total + r['snr'] * r['total'])/ (dbrec.total + r['total']))
                        dbrec.total += r['total']
                        for country, n in r['countries'].items():
                            dbrec.countries[country] = n if dbrec.countries.get(country) is None else dbrec.countries[country] + n
                        for cq, n in r['cqs'].items():
                            dbrec.cqs[cq] = n if dbrec.cqs.get(cq) is None else dbrec.cqs[cq] + n
                        for cs, n in r['callers'].items():
                            dbrec.callers[cs] = n if dbrec.callers.get(cs) is None else dbrec.callers[cs]  + n
                        #now we update record in db
                        self.db_upsert_minute(monitor=monitor, band=band, data=dbrec)

            #then hours table...
            m_begin = m_begin - m_begin % 3600
            m_end = m_begin
            recs = self.fetch_in_hours(monitor=monitor, band=band, begin=m_begin, end=m_end)
            hr_db: Dict[int, Hours_Record] = {}
            hr_nm: Dict[int, Hours_Record] = {}
            for r in recs:
                hr_db[r.ctime] = r
            for mt, r in minutes.items():
                r_hour = mt - mt % 3600
                if hr_nm.get(r_hour) is None:
                    hr_nm[r_hour] = Hours_Record(
                        ctime=r_hour,
                        monitor=monitor,
                        band=band,
                        total=0,
                        snr=0,
                        countries={},
                        cqs={}
                    )
                hr_nm[r_hour].total += r['total']
                hr_nm[r_hour].snr = round((hr_nm[r_hour].snr * hr_nm[r_hour].total + r['snr'] * r['total'])/(hr_nm[r_hour].total + r['total']))
                for cn, t in r['countries'].items():
                    hr_nm[r_hour].countries[cn] = t if hr_nm[r_hour].countries.get(cn) is None else hr_nm[r_hour].countries[cn] + t
                for cn, t in r['cqs'].items():
                    hr_nm[r_hour].cqs[cn] = t if hr_nm[r_hour].cqs.get(cn) is None else hr_nm[r_hour].cqs[cn] + t

            if len(hr_nm.keys()) == 0:
                if len(hr_db.keys()) == 0:
                    #empty in db, write a idle record(no data yet station alive) for that station & band
                    self.db_upsert_hour(monitor=monitor, band=band, data=Hours_Record(
                        ctime=m_begin,
                        monitor=monitor,
                        band=band,
                        total=0,
                        snr=0,
                        countries={},
                        cqs={}
                        ))
            else:
                for r_hour, c in hr_nm.items():
                    if hr_db.get(r_hour) is None: #Empty in db, write new one...
                        self.db_upsert_hour(monitor=monitor, band=band, data=c)
                    else: #record exist in db, update...
                        rec = hr_db[r_hour]
                        rec.snr = round((rec.snr * rec.total + c.snr * c.total)/(rec.total + c.total))
                        rec.total += c.total
                        for cn, t in c.countries.items():
                            rec.countries[cn] = t if rec.countries.get(cn) is None else rec.countries[cn] + t
                        for cn, t in c.cqs.items():
                            rec.cqs[cn] = t if rec.cqs.get(cn) is None else rec.cqs[cn] + t
                        self.db_upsert_hour(monitor=monitor, band=band, data=rec)

        except Exception as err: #pylint: disable=W0718
            #raise err #debug
            return f'{err}'
        return None


    def fetch_in_minutes(self, monitor: str, band: str, begin: int, end: int) -> List[Minutes_Record]:
        """Call by web app api method, fetch record in minutes window.
                monitor: str    #monitor station id
                band: str       #which band
                begin: int      #epoch time in second, window time start
                end: int        #epoch time in second, window time end
            Return records found in db.
        """
        begin = begin if begin % 60 == 0 else begin - begin % 60
        end = end if end % 60 == 0 else end - end % 60
        return self.db_read_minutes(monitor=monitor, band=band, begin=begin, end=end)

    def fetch_in_hours(self, monitor: str, band: str, begin: int, end: int) -> List[Hours_Record]:
        """Call by web app api method, fetch record in hours window.
                monitor: str    #monitor station id
                band: str       #which band
                begin: int      #epoch time in second, window time start
                end: int        #epoch time in second, window time end
            Return records found in db.
        """
        begin = begin if begin % 3600 == 0 else begin - begin % 3600
        end = end if end % 3600 == 0 else end - end % 3600
        return self.db_read_hours(monitor=monitor, band=band, begin=begin, end=end)
