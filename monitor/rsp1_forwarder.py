#!/usr/bin/python3
"""
This is a helper script for forwarding sdrplay's rsp_tcp raw sample(dongle info and extended capabilities info removed) stream to stdout.

Note:
1. While the sdrplay receiver model for this script is RSP1, other models should be easily adapted.
2. When run rsp_tcp, RSP extended mode must be enabled(use command 'rsp_tcp -E' to run).
"""
from struct import pack, unpack
from time import sleep
import socket
import sys
import getopt
from threading import Thread
from queue import Queue

MAX_DATA_BUFF = 1024000
job_done = False #pylint: disable=C0103

def log(msg) -> None:
    print(msg, file=sys.stderr)


def write_to_stdout(dataq: Queue) -> None:
    while not job_done:
        data = dataq.get()
        sys.stdout.buffer.write(data)
    log("job done and exit thread...")

def usage():
    print("""RSP1 tcp stream forwarder, print sample data to stdout.
            -h, --help                  Print this message
            -a, --address=127.0.0.1     rsp_tcp server listen address
            -p, --port=1234             rsp_tcp server listen port
            -f, --freq=50400000         frequency_to_tune_to [Hz]
            -s, --samplerate=1200000    samplerate
        """)

def main() -> None:
    tq = Queue(MAX_DATA_BUFF)

    try:
        opts, _ = getopt.getopt(sys.argv[1:], "ha:p:f:s:", ["help", "address=", "port=", "freq=", "samplerate="])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    addr = '127.0.0.1'
    port = 1234
    freq = 50400000
    samplerate = 1200000
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-a", "--address"):
            addr = a
        elif o in ("-p", "--port"):
            port = int(a)
        elif o in ("-f", "--freq"):
            freq = int(a)
        elif o in ("-s", "--samplerate"):
            samplerate = int(a)
        else:
            assert False, "unhandled option!"

    try:
        ts = Thread(target=write_to_stdout, args=(tq,))
        ts.start()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            connected = False
            while not connected:
                sock.connect((addr, port))
                connected = True

            sock.settimeout(None)
            log(f"Connection made with rsp_tcp server at {addr}:{port}.")

            freqb = pack(">ci", b"\x01", freq)
            freqs = ' '.join('{:02x}'.format(x) for x in freqb)
            log(f"Setting center frequency to: {freq}({freqs}).")
            sock.sendall(freqb)
            sleep(2)

            rateb = pack("!ci", b"\x02", samplerate)
            rates = ' '.join('{:02x}'.format(x) for x in rateb)
            log(f"Setting sample rate to: {samplerate} ({rates})")
            sock.sendall(rateb)
            sleep(2)

            tuner_gain_mode_enable = pack(">ci", b"\x03", 0)
            log("Enabling AGC")
            sock.sendall(tuner_gain_mode_enable)
            sleep(2)

            #RPS1 gain within 0~491
            LNA_state = pack(">ci", b"\x04", 300)
            log("Setting gain to 300.")
            sock.sendall(LNA_state)
            sleep(2)

            #LNA GR (dB) by Frequency Range and LNAstate for RSP1: 0:0db, 1-24db, 2-19db, 3-43db
            LNA_state = pack(">ci", b"\x20", 3)
            log("Setting LNA State to 3.")
            sock.sendall(LNA_state)
            sleep(2)

            #Now we start recv bytes from rsp_tcp.
            #Just before sample bytes,let's drop some message from stream.
            #First: rtl dongle info
            dongle_info = unpack('!cccc', sock.recv(4))
            tuner_type = unpack('!I', sock.recv(4))
            tuner_gain_count = unpack('!I', sock.recv(4))
            log(f"""Got some dongle info from rsp device:
    dongle: {b"".join(dongle_info).decode("ascii")}
    tuner_type: {tuner_type[0]}
    tuner_gain_count: {tuner_gain_count[0]}
""")

            #Then: rsp extended_capabilities info
            magic = unpack('!cccc', sock.recv(4))
            version = unpack('!I', sock.recv(4))
            capabilities = unpack('!I', sock.recv(4))
            __reserved__ = unpack('!I', sock.recv(4))
            hardware_version = unpack('!I', sock.recv(4))
            sample_format = unpack('!I', sock.recv(4))
            antenna_input_count = unpack('!B', sock.recv(1))
            third_antenna_name = unpack('!ccccccccccccc', sock.recv(13))
            third_antenna_freq_limit = unpack('!i', sock.recv(4))
            tuner_count = unpack('!B', sock.recv(1))
            ifgr_min = unpack('!B', sock.recv(1))
            ifgr_max = unpack('!B', sock.recv(1))
            log(f"""Got some extended capabilities info from rsp device:
    magic: {b"".join(magic).decode("ascii")}
    version: {version[0]}
    capabilities: {capabilities[0]}
    __reserved__: {__reserved__[0]}
    hardware_version: {hardware_version[0]}
    sample_format: {sample_format[0]}
    antenna_input_count: {antenna_input_count[0]}
    third_antenna_name: {b"".join(third_antenna_name).decode("ascii")}
    third_antenna_freq_limit: {third_antenna_freq_limit[0]}
    tuner_count: {tuner_count[0]}
    ifgr_min: {ifgr_min[0]}
    ifgr_max: {ifgr_max[0]}
""")
            #Finaly, the realtime sample bytes from there...
            log('Begin forwarding sample stream...')
            while True:
                tq.put(sock.recv(512))

    except KeyboardInterrupt:
        global job_done     #pylint: disable=W0603
        job_done = True
        ts.join()


if __name__ == '__main__' :
    main()
