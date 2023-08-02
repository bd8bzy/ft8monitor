#!/usr/bin/python3
"""
This is an udp server for receiving wsjtx decoded messages.
The purpose is to send the parsed ft8 messages to a remote web server.
"""
import sys
import io
import re
import time
import getopt
import datetime
from socket import socket, AF_INET, SOCK_DGRAM
from struct import pack, unpack
from threading import Thread
from queue import Queue, Empty
import http.client
import json
from urllib.parse import urlparse

def log(msg) -> None:
    print(msg, file=sys.stderr)



class CTY:
    '''
    Parse Country information in cty.dat format. Docs & cty data: https://www.country-files.com
    Piece of code took & modified from https://github.com/agustinmartino/wsjtx_transceiver_interface (author LU2HES).
    
    From docs:
    "Alias DXCC prefixes (including the primary one) follow on consecutive lines, separated by commas (,). 
    Multiple lines are OK; a line to be continued should end with comma (,) though it’s not required. 
    A semi-colon (;) terminates the last alias prefix in the list.

    If an alias prefix is preceded by ‘=’, this indicates that the prefix is to be treated as a full callsign, i.e. must be an exact match.
    The following special characters can be applied after an alias prefix:

    (#)	Override CQ Zone
    [#]	Override ITU Zone
    <#/#>	Override latitude/longitude
    {aa}	Override Continent
    ~#~	Override local time offset from GMT
    "
    Note: Current cty.data(2023-06-30) only contain CQ and ITU override.
    '''
    re_callsign = re.compile(r'(\=)?([A-Z0-9/]+)(\(\d+\))?(\[\d+\])?')

    re_full_callsign = re.compile(r'^((\d|[A-Z])+\/)?([A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z])(\/(\d|[A-Z])+)?(\/(\d|[A-Z])+)?$')
    re_indicator = re.compile(r'^(\d{3})$|^([A-Z]{1,4})$')
    re_grid = re.compile(r'^[A-R][A-R]\d{2}$')

    def __init__ (self, filename: str) :
        self.exact_callsign = {}
        self.prefix         = {}
        self.prf_max        = 0
        self.countries      = {}

        with io.open (filename, 'r') as f :
            current_country: str = None
            alias_lines = ''
            for line in f:
                line = line.strip()
                if current_country is None :
                    assert line.endswith(':')
                    cdata = self.parse_country_line(line.rstrip(':'))
                    current_country = cdata['country']
                    self.countries[current_country] = cdata['data']
                else:
                    assert not line.endswith(':')
                    if line.endswith (';') :
                        alias_lines += line.rstrip (';')
                        self.parse_alias_line(current_country, alias_lines)
                        current_country = None
                        alias_lines = ''
                    else:
                        assert line.endswith(',')
                        alias_lines += line

    def parse_country_line(self, line_text):
        l = [x.lstrip() for x in line_text.split(':')]

        return {'country': l[0],
                'data': {
                    'cq': l[1], 
                    'itu': l[2],
                    'continent': l[3],
                    'lat': float(l[4]),
                    'lon': float(l[5]),
                    'gmtoff': float(l[6]),
                    'pfx': l[7]}
                }

    def parse_alias_line(self, country, line_text):
        c_data = self.countries[country]
        assert c_data is not None
        pfxs = line_text.split (',')
        for pfx in pfxs :
            m = self.re_callsign.match(pfx)
            assert m is not None
            full_callsign, callsign, g_cq, g_itu = m.groups()
            assert callsign is not None
            l = len(callsign)
            if l > self.prf_max:
                self.prf_max = l
            if full_callsign is not None:
                if callsign not in self.exact_callsign:
                    self.exact_callsign[callsign] = {
                        'country': country,
                        'cq': c_data['cq'],
                        'itu': c_data['itu'],
                        'continent': c_data['continent'],
                        'lat': c_data['lat'],
                        'lon': c_data['lon'],
                        'gmtoff': c_data['gmtoff']
                    }
                    if g_cq is not None:
                        self.exact_callsign[callsign]['cq'] = g_cq[1:-1]
                    if g_itu is not None:
                        self.exact_callsign[callsign]['itu'] = g_itu[1:-1]
            else:
                if callsign not in self.prefix:
                    self.prefix[callsign] = {
                        'country': country,
                        'cq': c_data['cq'],
                        'itu': c_data['itu'],
                        'continent': c_data['continent'],
                        'lat': c_data['lat'],
                        'lon': c_data['lon'],
                        'gmtoff': c_data['gmtoff']
                    }
                    if g_cq is not None:
                        self.prefix[callsign]['cq'] = g_cq[1:-1]
                    if g_itu is not None:
                        self.prefix[callsign]['itu'] = g_itu[1:-1]

    def callsign_lookup (self, callsign) :
        '''
        return {
            'country': str,
            'cq': str of integer,
            'itu': str of integer,
            'continent': str of 2 chars,
            'lat': float, + for North
            'lon': float, + for West
            'gmtoff': float
        }
        '''
        if callsign in self.exact_callsign :
            return self.exact_callsign[callsign]
        for n in reversed(range(self.prf_max)) :
            pfx = callsign[:n+1]
            if pfx in self.prefix :
                return self.prefix[pfx]
        return None

    def parse_wsjtx_decode_msg(self, msg):
        '''
        Parse message from wsjt-x app UDP protocal.

        Examples of all supported message types:
        Message                 Decoded                Err? Type
        --------------------------------------------------------------------------
        1.  CQ WB9XYZ EN34          CQ WB9XYZ EN34              1:    Std Msg
        2.  CQ DX WB9XYZ EN34       CQ DX WB9XYZ EN34           1:    Std Msg
        3.  QRZ WB9XYZ EN34         QRZ WB9XYZ EN34             1:    Std Msg
        4.  KA1ABC WB9XYZ EN34      KA1ABC WB9XYZ EN34          1:    Std Msg
        5.  KA1ABC WB9XYZ RO        KA1ABC WB9XYZ RO            1:    Std Msg
        6.  KA1ABC WB9XYZ -21       KA1ABC WB9XYZ -21           1:    Std Msg
        7.  KA1ABC WB9XYZ R-19      KA1ABC WB9XYZ R-19          1:    Std Msg
        8.  KA1ABC WB9XYZ RRR       KA1ABC WB9XYZ RRR           1:    Std Msg
        9.  KA1ABC WB9XYZ 73        KA1ABC WB9XYZ 73            1:    Std Msg
        10.  KA1ABC WB9XYZ           KA1ABC WB9XYZ               1:    Std Msg
        11.  CQ 000 WB9XYZ EN34      CQ 000 WB9XYZ EN34          1:    Std Msg
        12.  CQ 999 WB9XYZ EN34      CQ 999 WB9XYZ EN34          1:    Std Msg
        13.  CQ EU WB9XYZ EN34       CQ EU WB9XYZ EN34           1:    Std Msg
        14.  CQ WY WB9XYZ EN34       CQ WY WB9XYZ EN34           1:    Std Msg
        15.  ZL/KA1ABC WB9XYZ        ZL/KA1ABC WB9XYZ            2:    Type 1 pfx
        16.  KA1ABC ZL/WB9XYZ        KA1ABC ZL/WB9XYZ            2:    Type 1 pfx
        17.  KA1ABC/4 WB9XYZ         KA1ABC/4 WB9XYZ             3:    Type 1 sfx
        18.  KA1ABC WB9XYZ/4         KA1ABC WB9XYZ/4             3:    Type 1 sfx
        19.  CQ ZL4/KA1ABC           CQ ZL4/KA1ABC               4:    Type 2 pfx
        20.  DE ZL4/KA1ABC           DE ZL4/KA1ABC               4:    Type 2 pfx
        21.  QRZ ZL4/KA1ABC          QRZ ZL4/KA1ABC              4:    Type 2 pfx
        22.  CQ WB9XYZ/VE4           CQ WB9XYZ/VE4               5:    Type 2 sfx
        23.  HELLO WORLD             HELLO WORLD                 6:    Free text
        24.  ZL4/KA1ABC 73           ZL4/KA1ABC 73               6:    Free text
        25.  KA1ABC XL/WB9XYZ        KA1ABC XL/WB9            *  6:    Free text
        26.  KA1ABC WB9XYZ/W4        KA1ABC WB9XYZ            *  6:    Free text
        27.  123456789ABCDEFGH       123456789ABCD            *  6:    Free text
        28.  KA1ABC WB9XYZ EN34 OOO  KA1ABC WB9XYZ EN34 OOO      1:    Std Msg
        29.  KA1ABC WB9XYZ OOO       KA1ABC WB9XYZ OOO           1:    Std Msg
        30.  RO                      RO                         -1:    Shorthand
        31.  RRR                     RRR                        -1:    Shorthand
        32.  73                      73                         -1:    Shorthand

        return: 
        {
            'ERROR':            None or str
            'raw_message':      str             the original msg param passed in
            'type':             'CQ'/'QRZ'/'DE'/'REPLAY'/'UNKNOWN'
            'caller':           str  OR None    callsign of the sender
            'country':          str  OR None    sender country
            'zone_cq':          str  OR None    sender cq zone
            'zone_itu':         str  OR None    sender itu zone
            'continent':        str  OR None    sender 2-letter continent abbreviation
            'lat':              float  OR None  sender latitude in degrees, + for North
            'lon':              float  OR None  sender longitude in degrees, + for West
            'gmtoff':           float  OR None  sender local time offset from GMT
            'grid':             str  OR None  sender 4-character grid
            'peer':             str  OR None    callsign of the receiver
        }
        '''
        pm = {
            'ERROR': None,
            'raw_message': msg,
            'mtype': 'UNKNOWN',
            'caller': None,
            'country': None,
            'zone_cq': None,
            'zone_itu': None,
            'continent': None,
            'lat': None,
            'lon': None,
            'gmtoff': None,
            'grid': None,
            'peer': None
        }
        if msg is None or len(msg) == 0:
            pm['ERROR'] = "empty message"
            return pm
        if ';' in msg:
            pm['ERROR'] = "Unknown message: %s" % msg
            return pm
        l = msg.split ()
        if len(l) < 1:
            pm['ERROR'] = "Unknown message: %s" % msg
            return pm
        # Strip off marginal decode info
        if l[-1].startswith('a') or l[-1] == '?':
            l = l[:-1]
        if len(l) < 1:
            pm['ERROR'] = "Unknown message: %s" % msg
            return pm

        #begin parse message...
        #CQ/QRZ/DE first
        if l[0] in ('CQ', 'QRZ', 'DE'):
            pm['mtype'] = l[0]
            if len(l) < 2:
                pm['ERROR'] = "Unknown message: %s" % msg
                return pm
            else:
                l = l[1:]
            if self.re_indicator.match(l[0]):
                if len(l) < 2:
                    pm['ERROR'] = "Unknown message: %s" % msg
                    return pm
                else:
                    l = l[1:]
            #now first word should be a callsign
            if self.re_full_callsign.match(l[0]):
                pm['caller'] = l[0]
                info_data = self.callsign_lookup(pm['caller'])
                if info_data is not None:
                    pm['country'] = info_data['country']
                    pm['zone_cq'] = info_data['cq']
                    pm['zone_itu'] = info_data['itu']
                    pm['continent'] = info_data['continent']
                    pm['lat'] = info_data['lat']
                    pm['lon'] = info_data['lon']
                    pm['gmtoff'] = info_data['gmtoff']
                l = l[1:]
                if len(l) == 0:
                    return pm
                if self.re_full_callsign.match(l[0]):
                    #now this is a peer callsign
                    pm['peer'] = l[0]
                    if len(l) > 1 and self.re_grid.match(l[1]):
                        pm['grid'] = l[1]
                else:
                    if self.re_grid.match(l[0]):
                        pm['grid'] = l[0]
                return pm
            else:
                pm['ERROR'] = "Unknown message: %s" % msg
                return pm

        #now deal with reply
        if len(l) >= 2:
            if self.re_full_callsign.match(l[0]):
                #got sender
                pm['caller'] = l[0]
                info_data = self.callsign_lookup(pm['caller'])
                if info_data is not None:
                    pm['country'] = info_data['country']
                    pm['zone_cq'] = info_data['cq']
                    pm['zone_itu'] = info_data['itu']
                    pm['continent'] = info_data['continent']
                    pm['lat'] = info_data['lat']
                    pm['lon'] = info_data['lon']
                    pm['gmtoff'] = info_data['gmtoff']
                l = l[1:]
                if self.re_full_callsign.match(l[0]):
                    #now this is a peer callsign
                    pm['peer'] = l[0]
                    pm['mtype'] = 'REPLAY'
                    if len(l) > 1 and self.re_grid.match(l[1]) and l[1] != 'RR73':
                        pm['grid'] = l[1]
                else:
                    if self.re_grid.match(l[0]):
                        pm['grid'] = l[0]
                return pm

        #free text and others...
        return pm




class Protocol_Element:
    """ A single protocol element to be parsed from binary format or
        serialized to binary format.
    """

    def __init__(self, value):
        self.value = value

    @classmethod
    def deserialize(cls, dbytes, length = 0):
        raise NotImplementedError ("Needs to be define in sub-class")

    def serialize (self):
        raise NotImplementedError ("Needs to be define in sub-class")

    @property
    def serialization_size(self):
        raise NotImplementedError ("Needs to be define in sub-class")


class UTF8_String(Protocol_Element):
    """ An UTF-8 string consisting of a length and the string
        Special case is a null string (different from an empty string)
        which encodes the length as 0xffffffff
    >>> v = UTF8_String.deserialize (b'\\x00\\x00\\x00\\x04abcd')
    >>> v.value
    'abcd'
    >>> v.serialize ()
    b'\\x00\\x00\\x00\\x04abcd'
    >>> s = UTF8_String (None)
    >>> s.serialize ()
    b'\\xff\\xff\\xff\\xff'
    """

    @classmethod
    def deserialize(cls, dbytes, length = 0):
        offset = 4
        length = unpack('!L', dbytes[:offset])[0]
        # Special case empty (None?) string
        if length == 0xFFFFFFFF:
            value = None
            return cls(value)
        value  = unpack('%ds' % length, dbytes[offset:offset+length])[0]
        return cls(value.decode ('utf-8'))

    def serialize(self):
        if self.value is None:
            return pack('!L', 0xFFFFFFFF)
        length = len(self.value)
        value  = self.value.encode('utf-8')
        return pack('!L', length) + pack('%ds' % length, value)

    @property
    def serialization_size(self):
        if self.value is None:
            return 4
        return 4 + len(self.value.encode ('utf-8'))


class Optional_Quint(Protocol_Element):
    """ A quint which is optional, length in deserialize is used
        We encode a missing value as None
    """

    formats = dict \
        (( (1, '!B')
        ,  (4, '!L')
        ,  (8, '!Q')
        ))

    @classmethod
    def deserialize(cls, dbytes, length = 1):
        if len(dbytes) == 0:
            value = None
        else:
            value = unpack(Optional_Quint.formats [length], dbytes)[0]
        dobject = cls(value)
        dobject.size = length #pylint: disable=W0201
        if value is None:
            dobject.size = 0 #pylint: disable=W0201
        return dobject

    def serialize(self):
        if self.value is None:
            return b''
        return pack(self.formats [self.size], self.value)

    @property
    def serialization_size(self):
        if self.value is None:
            return 0
        return self.size


class QDateTime(Protocol_Element):
    """ A QT DateTime object
        The case with a timezone is not used
    """

    def __init__(self, date, dtime, timespec, offset = None): #pylint: disable=W0231
        self.date     = date
        self.time     = dtime
        self.timespec = timespec
        self.offset   = offset
        assert self.offset is None or self.timespec == 2
        if self.timespec == 2 and self.offset is not None:
            raise ValueError("Offset required when timespec=2")

    @classmethod
    def deserialize(cls, dbytes, length = 0):
        date, dtime, timespec = unpack('!qLB', dbytes[:13])
        offset = None
        if timespec == 2:
            offset = unpack('!l', dbytes[13:17])[0]
        return cls(date, dtime, timespec, offset)

    def serialize(self):
        r = [pack('!qLB', self.date, self.time, self.timespec)]
        if self.offset is not None:
            r.append(pack('!l', self.offset))
        return b''.join(r)

    @property
    def serialization_size (self):
        if self.offset is None:
            return 13
        return 13 + 4

    @property
    def value (self):
        return self

    def __str__ (self):
        s = ( 'QDatTime(date=%(date)s time=%(time)s '
            + 'timespec=%(timespec)s offset=%(offset)s)'
            )
        return s % self.__dict__

    __repr__ = __str__



class QColor(Protocol_Element):
    """ A QT color object
        We support only RGB type or invalid
    """

    fmt          = '!BHHHHH'
    spec_rgb     = 1
    spec_invalid = 0
    cmax         = 0xFFFF
    serialization_size = 11

    def __init__ \
        (self, red = 0, green = 0, blue = 0, alpha = cmax, spec = spec_rgb): #pylint: disable=W0231
        self.spec     = spec
        self.red      = red
        self.green    = green
        self.blue     = blue
        self.alpha    = alpha

    @classmethod
    def deserialize(cls, dbytes, length = 0):
        b = dbytes[:cls.serialization_size]
        s, a, r, g, b, dummy = unpack (cls.fmt, b)
        return cls(spec = s, alpha = a, red = r, green = g, blue = b)

    def serialize(self):
        return pack \
            ( self.fmt
            , self.spec
            , self.alpha
            , self.red
            , self.green
            , self.blue
            , 0
            )

    @property
    def value(self):
        return self

    def __str__ (self):
        if self.spec != self.spec_rgb:
            return 'QColor(Invalid)'
        s = ( 'QColor(alpha=%(alpha)s, red=%(red)s, '
            + 'green=%(green)s, blue=%(blue)s)'
            )
        return s % self.__dict__

    __repr__ = __str__


color_red      = QColor(red = QColor.cmax)
color_green    = QColor(green = QColor.cmax)
color_blue     = QColor(blue = QColor.cmax)
color_white    = QColor(QColor.cmax, QColor.cmax, QColor.cmax)
color_black    = QColor()
color_cyan     = QColor(0, 0xFFFF, 0xFFFF)
color_cyan1    = QColor(0x9999, 0xFFFF, 0xFFFF)
color_pink     = QColor(0xFFFF, 0, 0xFFFF)
color_pink1    = QColor(0xFFFF, 0xAAAA, 0xFFFF)
color_orange   = QColor(0xFFFF, 0xA0A0, 0x0000)

color_invalid  = QColor(spec = QColor.spec_invalid)
ctuple_invalid = (color_invalid, color_invalid)

# defaults (fg color, bg color)
ctuple_wbf           = ctuple_invalid
ctuple_dxcc          = (color_black,   color_pink)
ctuple_dxcc_band     = (color_black,   color_pink1)
ctuple_new_call      = (color_black,   color_cyan)
ctuple_new_call_band = (color_black,   color_cyan1)
ctuple_highlight     = (color_black,   color_orange)


# Shortcuts for used data types, also for consistency
quint8     = ('!B', 1)
quint32    = ('!L', 4)
quint64    = ('!Q', 8)
qint32     = ('!l', 4)
qbool      = quint8
qutf8      = (UTF8_String, 0)
qdouble    = ('!d', 8)
opt_quint8 = (Optional_Quint, 1)
qtime      = quint32
qdatetime  = (QDateTime, 0)
qcolor     = (QColor, 0)

statusmsg = b'\xad\xbc\xcb\xda\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x14WSJT-X - TS590S-klbg\x00\x00\x00\x00\x00k\xf0\xd0\x00\x00\x00\x03FT8\x00\x00\x00\x06XAMPLE\x00\x00\x00\x02-2\x00\x00\x00\x03FT8\x00\x00\x01\x00\x00\x02\xcb\x00\x00\x04n\x00\x00\x00\x06OE3RSU\x00\x00\x00\x06JN88DG\x00\x00\x00\x04JO21\x00\xff\xff\xff\xff\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x0bTS590S-klbg\x00\x00\x00%XAMPLE OE3RSU 73                     '
clearmsg = b'\xad\xbc\xcb\xda\x00\x00\x00\x03\x00\x00\x00\x03\x00\x00\x00\x14WSJT-X - TS590S-klbg'

class WSJTX_Telegram():
    """ Base class of WSJTX Telegram
        Note that we a list of (name, format, len) tuples as the format
        specification. The name is the name of the variable, the format
        is either a struct.pack compatible format specifier or an
        instance of Protocol_Element which knows how to deserialize (or
        serialize) itself. The len is the length to parse from the
        string. If 0 the Protocol_Element will know its serialization
        size.
    >>> WSJTX_Telegram.from_bytes (statusmsg)
    Status dial_frq=7074000 mode=FT8 dx_call=XAMPLE report=-2 tx_mode=FT8 tx_enabled=0 xmitting=0 decoding=1 rx_df=715 tx_df=1134 de_call=OE3RSU de_grid=JN88DG dx_grid=JO21 tx_watchdog=0 sub_mode=None fast_mode=0 special_op=0 frq_tolerance=4294967295 t_r_period=4294967295 config_name=TS590S-klbg tx_message=XAMPLE OE3RSU 73
    >>> WSJTX_Telegram.from_bytes (clearmsg)
    Clear window=None
    """

    schema_version_number = 3
    magic  = 0xadbccbda
    type   = None
    format = \
        [ ('magic',          quint32)
        , ('version_number', quint32)
        , ('type',           quint32)
        , ('id',             qutf8)
        ]
    defaults = dict(magic = magic, version_number = 3, id = 'wsjt-server')
    suppress = dict.fromkeys(('magic', 'version_number', 'id', 'type'))

    # Individual telegrams register here:
    type_registry = {}

    def __init__ (self, **kw) :
        params = {}
        params.update(self.defaults)
        params.update(kw)
        if 'type' not in params:
            params['type'] = self.type
        assert params['magic'] == self.magic
        assert self.schema_version_number >= params['version_number']
        # Thats for sub-classes, they have their own format
        for name, (_, _) in self.format:
            setattr(self, name, params [name])
        if self.__class__.type is not None:
            assert self.__class__.type == self.type


    @classmethod
    def from_bytes(cls, dbytes):
        kw   = cls.deserialize(dbytes)
        dtype = kw['type']
        self = cls(** kw)
        if dtype in cls.type_registry:
            c = cls.type_registry[dtype]
            kw.update(c.deserialize (dbytes))
            return c(** kw)
        else :
            return self


    @classmethod
    def deserialize(cls, dbytes):
        b  = dbytes
        kw = {}
        for name, (dformat, length) in cls.format:
            # Due to compatibility reasons new message fields are added to
            # the end of the messsage. The buffer is empty when the message
            # is older format and a field is missing.
            if len(b) == 0:
                kw[name] = None
                continue
            if isinstance(dformat, type('')):
                kw[name] = unpack(dformat, b[:length])[0]
                b = b[length:]
            else :
                value = dformat.deserialize(b, length)
                b = b[value.serialization_size:]
                kw[name] = value.value
        return kw


    def as_bytes(self):
        r = []
        for name, (fmt, _) in self.format:
            v = getattr(self, name)
            if isinstance(v, Protocol_Element):
                r.append (v.serialize ())
            elif isinstance(fmt, type('')):
                r.append(pack(fmt, v))
            else:
                r.append(fmt (v).serialize())
        return b''.join(r)


    def __str__ (self):
        r = [self.__class__.__name__.split('_', 1) [-1]]
        for n, (_, _) in self.format:
            if n not in self.suppress:
                r.append('%s=%s' % (n, getattr(self, n)))
        return ' '.join(r)

    __repr__ = __str__


class WSJTX_Heartbeat(WSJTX_Telegram):

    type   = 0

    format = WSJTX_Telegram.format + \
        [('max_schema',     quint32)
        , ('version',        qutf8)
        , ('revision',       qutf8)
        ]
    defaults = dict \
        ( max_schema = 3
        , version    = ''
        , revision   = ''
        , ** WSJTX_Telegram.defaults
        )

WSJTX_Telegram.type_registry[WSJTX_Heartbeat.type] = WSJTX_Heartbeat

class WSJTX_Status(WSJTX_Telegram) :

    type   = 1
    format = WSJTX_Telegram.format + \
        [ ('dial_frq',       quint64)
        , ('mode',           qutf8)
        , ('dx_call',        qutf8)
        , ('report',         qutf8)
        , ('tx_mode',        qutf8)
        , ('tx_enabled',     qbool)
        , ('xmitting',       qbool)
        , ('decoding',       qbool)
        , ('rx_df',          quint32)
        , ('tx_df',          quint32)
        , ('de_call',        qutf8)
        , ('de_grid',        qutf8)
        , ('dx_grid',        qutf8)
        , ('tx_watchdog',    qbool)
        , ('sub_mode',       qutf8)
        , ('fast_mode',      qbool)
        , ('special_op',     quint8)
        , ('frq_tolerance',  quint32)
        , ('t_r_period',     quint32)
        , ('config_name',    qutf8)
        , ('tx_message',     qutf8)
        ]


WSJTX_Telegram.type_registry[WSJTX_Status.type] = WSJTX_Status

class WSJTX_Decode (WSJTX_Telegram) :

    type   = 2
    format = WSJTX_Telegram.format + \
        [ ('is_new',         qbool)
        , ('time',           qtime)
        , ('snr',            qint32)
        , ('delta_t',        qdouble)
        , ('delta_f',        quint32)
        , ('mode',           qutf8)
        , ('message',        qutf8)
        , ('low_confidence', qbool)
        , ('off_air',        qbool)
        ]


WSJTX_Telegram.type_registry[WSJTX_Decode.type] = WSJTX_Decode

class WSJTX_Clear(WSJTX_Telegram) :

    type     = 3
    format   = WSJTX_Telegram.format + [('window', opt_quint8)]
    defaults = dict(window = None, **WSJTX_Telegram.defaults)


WSJTX_Telegram.type_registry[WSJTX_Clear.type] = WSJTX_Clear

class WSJTX_Reply(WSJTX_Telegram) :

    type   = 4
    format = WSJTX_Telegram.format + \
        [ ('time',           qtime)
        , ('snr',            qint32)
        , ('delta_t',        qdouble)
        , ('delta_f',        quint32)
        , ('mode',           qutf8)
        , ('message',        qutf8)
        , ('low_confidence', qbool)
        , ('modifiers',      quint8)
        ]


WSJTX_Telegram.type_registry[WSJTX_Reply.type] = WSJTX_Reply

class WSJTX_QSO_Logged(WSJTX_Telegram) :

    type   = 5
    format = WSJTX_Telegram.format + \
        [ ('time_off',       qdatetime)
        , ('dx_call',        qutf8)
        , ('dx_grid',        qutf8)
        , ('tx_frq',         quint64)
        , ('mode',           qutf8)
        , ('report_sent',    qutf8)
        , ('report_recv',    qutf8)
        , ('tx_power',       qutf8)
        , ('comments',       qutf8)
        , ('name',           qutf8)
        , ('time_on',        qdatetime)
        , ('operator_call',  qutf8)
        , ('my_call',        qutf8)
        , ('my_grid',        qutf8)
        , ('exchange_sent',  qutf8)
        , ('exchange_recv',  qutf8)
        , ('adif_propmode',  qutf8)
        ]


WSJTX_Telegram.type_registry[WSJTX_QSO_Logged.type] = WSJTX_QSO_Logged

class WSJTX_Close(WSJTX_Telegram) :

    type   = 6


WSJTX_Telegram.type_registry[WSJTX_Close.type] = WSJTX_Close

class WSJTX_Replay(WSJTX_Telegram) :

    type   = 7


WSJTX_Telegram.type_registry[WSJTX_Replay.type] = WSJTX_Replay

class WSJTX_Halt_TX(WSJTX_Telegram) :

    type   = 8
    format = WSJTX_Telegram.format + [('auto_tx_only', qbool)]


WSJTX_Telegram.type_registry[WSJTX_Halt_TX.type] = WSJTX_Halt_TX

class WSJTX_Free_Text(WSJTX_Telegram) :

    type   = 9
    format = WSJTX_Telegram.format + \
        [ ('text',   qutf8)
        , ('send',   qbool)
        ]
    defaults = dict(send = False, **WSJTX_Telegram.defaults)


WSJTX_Telegram.type_registry[WSJTX_Free_Text.type] = WSJTX_Free_Text

class WSJTX_WSPR_Decode(WSJTX_Telegram) :

    type   = 10
    format = WSJTX_Telegram.format + \
        [ ('is_new',         qbool)
        , ('time',           qtime)
        , ('snr',            qint32)
        , ('delta_t',        qdouble)
        , ('frq',            quint64)
        , ('drift',          qint32)
        , ('callsign',       qutf8)
        , ('grid',           qutf8)
        , ('power',          qint32)
        , ('off_air',        qbool)
        ]


WSJTX_Telegram.type_registry[WSJTX_WSPR_Decode.type] = WSJTX_WSPR_Decode

class WSJTX_Location(WSJTX_Telegram) :

    type   = 11
    format = WSJTX_Telegram.format + [('location', qutf8)]


WSJTX_Telegram.type_registry[WSJTX_Location.type] = WSJTX_Location

class WSJTX_Logged_ADIF(WSJTX_Telegram) :

    type   = 12
    format = WSJTX_Telegram.format + [('adif_txt', qutf8)]


WSJTX_Telegram.type_registry[WSJTX_Logged_ADIF.type] = WSJTX_Logged_ADIF

class WSJTX_Highlight_Call(WSJTX_Telegram) :
    """ Highlight a callsign in WSJTX
    >>> kw = dict (id = 'test', version_number = 2)
    >>> whc = WSJTX_Highlight_Call \\
    ...     ( callsign = 'OE3RSU'
    ...     , bg_color = color_white
    ...     , fg_color = color_red
    ...     , highlight_last = 1
    ...     , **kw
    ...     )
    >>> b = whc.as_bytes ()
    >>> WSJTX_Telegram.from_bytes (b)
    Highlight_Call callsign=OE3RSU bg_color=QColor(alpha=65535, red=65535, green=65535, blue=65535) fg_color=QColor(alpha=65535, red=65535, green=0, blue=0) highlight_last=1
    """

    type   = 13
    format = WSJTX_Telegram.format + \
        [ ('callsign',       qutf8)
        , ('bg_color',       qcolor)
        , ('fg_color',       qcolor)
        , ('highlight_last', qbool)
        ]
    defaults = dict \
        ( fg_color       = color_black
        , bg_color       = color_white
        , highlight_last = False
        , ** WSJTX_Telegram.defaults
        )


WSJTX_Telegram.type_registry[WSJTX_Highlight_Call.type] = WSJTX_Highlight_Call

class WSJTX_Switch_Config(WSJTX_Telegram) :

    type   = 14
    format = WSJTX_Telegram.format + [('adif_txt', qutf8)]


WSJTX_Telegram.type_registry[WSJTX_Switch_Config.type] = WSJTX_Switch_Config

class WSJTX_Configure(WSJTX_Telegram) :

    type   = 15
    format = WSJTX_Telegram.format + \
        [ ('mode',           qutf8)
        , ('frq_tolerance',  quint32)
        , ('sub_mode',       qutf8)
        , ('fast_mode',      qbool)
        , ('t_r_period',     quint32)
        , ('rx_df',          quint32)
        , ('dx_call',        qutf8)
        , ('dx_grid',        qutf8)
        , ('gen_messages',   qbool)
        ]


WSJTX_Telegram.type_registry[WSJTX_Configure.type] = WSJTX_Configure




class UDP_Connector:
    '''
    Receive ft8 decoded message from wsjt-x app, then send parsed info to a thread queue.
    '''

    def __init__ (self, cty_parser, msg_pipe, ip = '127.0.0.1', port = 2237, did = None):
        self.cty_parser = cty_parser
        self.msg_pipe = msg_pipe
        self.ip      = ip
        self.port    = port
        self.socket  = socket(AF_INET, SOCK_DGRAM)
        self.peer    = {}
        self.adr     = None
        self.id      = did
        self.dx_call = None
        self.socket.bind((self.ip, self.port))
        if did is None:
            self.id = WSJTX_Telegram.defaults['id']
        self.heartbeat_seen = False


    def handle (self, tel):
        """ Handle given telegram.
            We send a heartbeat whenever we receive one.
            In addition we parse Decode messages, extract the call sign
            and determine worked-before and coloring.
        """
        if not self.heartbeat_seen or isinstance(tel, WSJTX_Heartbeat):
            self.heartbeat()
        if isinstance(tel, WSJTX_Decode):
            self.handle_decode (tel)
        if isinstance(tel, WSJTX_Close):
            self.handle_close (tel)

    def handle_close(self, tel):
        """ Just exit when wsjtx exits
        """
        assert self.peer[tel.id] == self.adr
        log('wsjt_srv udp server exit.')
        sys.exit(0)


    def handle_decode(self, tel):
        if tel.off_air or not tel.is_new:
            return
        msg = self.cty_parser.parse_wsjtx_decode_msg(tel.message or '')
        if msg['ERROR'] is not None:
            log(f"wsjt_srv error when decode message: {msg['ERROR']}")
            return
        msg['time'] = int(time.time())
        msg['snr'] = tel.snr
        msg['delta_t'] = tel.delta_t
        msg['delta_f'] = tel.delta_f
        msg['lf'] = tel.low_confidence
        #msg['mode'] = tel.mode
        self.msg_pipe.put(msg)

    def heartbeat(self, **kw) :
        tel = WSJTX_Heartbeat(version = '4711', **kw)
        self.socket.sendto(tel.as_bytes(), self.adr)


    # Some regexes for matching
    re_report = re.compile(r'[R]?[-+][0-9]{2}')
    re_loc    = re.compile(r'[A-Z]{2}[0-9]{2}')
    re_call   = re.compile \
        (r'(([A-Z])|([A-Z][A-Z0-9])|([0-9][A-Z]))[0-9][A-Z]{1,3}')

    def is_locator(self, s) :
        """ Check if s is a locator
        >>> u = UDP_Connector (port = 4711, wbf = None)
        >>> u.is_locator ('-2')
        False
        >>> u.is_locator ('JN88')
        True
        >>> u.is_locator ('kk77')
        False
        >>> u.socket.close ()
        """
        return bool(self.re_loc.match(s))


    def is_report(self, s) :
        """ Check if s is a report
        >>> u = UDP_Connector (port = 4711, wbf = None)
        >>> u.is_report ('-2')
        False
        >>> u.is_report ('-02')
        True
        >>> u.is_report ('+20')
        True
        >>> u.is_report ('R+20')
        True
        >>> u.socket.close ()
        """
        return bool(self.re_report.match(s))


    def is_stdcall(self, s) :
        """ Check if s is a standard callsign
        >>> u = UDP_Connector (port = 4711, wbf = None)
        >>> u.is_stdcall ('D1X')
        True
        >>> u.is_stdcall ('JN88')
        False
        >>> u.is_stdcall ('OE3RSU')
        True
        >>> u.socket.close ()
        """
        return bool(self.re_call.match(s))


    def receive(self) :
        dbytes, address = self.socket.recvfrom(4096)
        tel = WSJTX_Telegram.from_bytes(dbytes)
        if tel.id not in self.peer:
            self.peer[tel.id] = address
        if not self.adr:
            self.adr = address
        # Only handle messages from preferred peer for now
        if self.adr == address:
            self.handle(tel)
        return tel


    def set_peer(self, peername):
        if peername in self.peer:
            self.adr = self.peer[peername]




SENDING_PERIOD = 30     #web report sending period. In second.
job_done = False

def handle_msg(ml, parsed_url):
    print(f'{ml}') #log go to stderr, and msg go to stdout
    try:
        conn = http.client.HTTPSConnection(parsed_url.hostname, port=parsed_url.port or 443) if parsed_url.scheme == 'https' else http.client.HTTPConnection(parsed_url.hostname, port=parsed_url.port or 80)
        headers = {'Content-type': 'application/json'}
        json_data = json.dumps(ml)
        conn.request('POST', f'{parsed_url.path}?{parsed_url.query}', json_data, headers)
        response = conn.getresponse()
        if response.status != 200:
            log(f'Error from web server({response.status}):')
            log(f'{response.read().decode()}')
    except Exception as err: #pylint: disable=W0718
        log(f'Error when send to web server:{err}')


def sender(taskQueue, parsed_url):
    ml = []
    while not job_done:
        for _ in range(SENDING_PERIOD):
            time.sleep(1)
            if job_done:
                return
        isEmpty = False
        while not isEmpty:
            try:
                m = taskQueue.get(False)
                ml.append(m)
            except Empty:
                isEmpty = True
        handle_msg(ml, parsed_url)
        ml = []

def usage():
    print("""Wsjtx message server, send decoded messages to remote web api gateway.
            -h, --help              Print this message
            -c, --ctyfile=cty.dat   File path for cty.dat
            -a, --address=127.0.0.1 Udp server listen address for wsjt-x app
            -p, --port=2237         Udp server listen port for wsjt-x app
            -w, --web=http://ft8mon.bd8bzy.com/report?id=testStation&band=50.313&token=112233445566
                                    Web data server api connection string. "id" for station name, "band", for ft8 band, "token" for password
        
          Note: band string in [.0-9a-zA-Z] 
        """)

def main():
    try:
        opts, _ = getopt.getopt(sys.argv[1:], "hw:a:c:p:", ["help", "web=","ctyfile=", "address=", "port="])
    except getopt.GetoptError as err:
        log(err)
        usage()
        sys.exit(2)
    addr = '127.0.0.1'
    port = 2237
    ctyfile = 'cty.dat'
    web = 'http://ft8mon.bd8bzy.com/report?id=testStation&band=50.313&token=112233445566'

    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-w", "--web"):
            web = a
        elif o in ("-a", "--address"):
            addr = a
        elif o in ("-p", "--port"):
            port = int(a)
        elif o in ("-c", "--ctyfile"):
            ctyfile = a
        else:
            assert False, "unhandled option!"

    parsed_url = urlparse(web)
    if parsed_url.scheme == '':
        log('Error when parse Web data server api connection string!')
        usage()
        sys.exit()

    tq = Queue()
    try:
        ts = Thread(target=sender, args=[tq, parsed_url])
        ts.start()
        cty = CTY(ctyfile)
        udp_srv = UDP_Connector(cty, tq, addr, port)

        log(f'{datetime.datetime.now().strftime("%H:%M:%S")}: ft8 monitor start.')
        while True:
            udp_srv.receive()

    except KeyboardInterrupt:
        log("Caught KeyboardInterrupt, terminating thread...")
        global job_done     #pylint: disable=W0603
        job_done = True
        ts.join()
    log(f'{datetime.datetime.now().strftime("%H:%M:%S")}: ft8 monitor exit.')

if __name__ == '__main__' :
    main()
