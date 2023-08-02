# ft8monitor
Yet Another SDR-based ft8 monitor solution for long-term unattended statistics collection.


# Description

The 6-meter band of amateur radio is known as the "magic band", and its propagation window is fleeting.
The intention of this project is to analyze (from minutes to months) some propagation laws of the 6-meter band from a statistical point of view by deploying a set of 24x7 ft8 signal monitor station. It can also be seen as a privatization and expansion of the [pskreporter.info](https://pskreporter.info/) for personal research purposes.
Other bands(10m 15m...) can be deployed in the same way.

A online demo page is [here](https://ft8mon.bd8bzy.net).


# Screenshot
![](https://github.com/bd8bzy/ft8monitor/screenshot.png "Screenshot") 


# Architecture
You have a coax to a fixed antenna, you have an SDR receiver, you have a Raspberry Pi or other low-power computer, and you want to monitor the FT8 signal 24x7 for long periods of time for statistical analysis. OK, glue codes in this project hope to help you.


## Choose SDR
Any dongle is ok, as long as it has driver that can output I/Q sample stream.

I originally bought an RTL-SDR Blog V3 dongle from rtl-sdr.com website (because it supports the HF band below 30Mhz), but it got too hot while running, which is a serious issue in the summer. So I switched to another sdrplay dongle (RSP1 with MSi001), which performed well in terms of power consumption, heat dissipation, and sensitivity.


## Choose computer
For 24x7 uninterrupted monitoring, the ideal device is a small host with low power consumption.

I have a Raspberry Pi 3b+, after some tests I found that although the entire toolchain (sdr -> SSB decoding -> audio output -> WSJTX -> data upload) can run, but the problem is that FT8 decoding is obviously stuttering, with a delay of 2~3 seconds, which is intolerable for FT8 protocol decoding. If you must use it, you need to manually slow down the time of the system by two or three seconds.

So my current solution is a Intel N100 mini pc, with its desktop-level computing speed and the power consumption less than 10W(+ USB power supply to SDR dongle). Bravo~


## Choose database
If it is only for short-term (days and weeks) collection, statistics data can be stored locally on the station if the amount of data is not too large. I wrote a simple SQLite script (sqlite_server.py) as a starting point.

But I want to be able to collect over a long period of time (months and years) and be able to easily access these statistics remotely, anytime, anywhere. The best way is to store data in cloud.

Fortunately, today's cloud providers offer more or less free (or very low-cost) packages for individual developers, which is enough for such a simple application.

In this little project, I used the AWS full-stack solution，dynamodb+lambda computing+api gateway+amplify hosting, all for free(at least for one year). Bravo~

Note: In order to reduce the installation complexity and to improve compatibility, I try not to introduce third-party frameworks/scripts outside the standard library for each script.


# How to deploy


## A. Get ubuntu
Although the toolchain and python scripts in this project are basically platform-independent, compilation under linux is the most convenient.

Moreover, Linux systems are more suitable for long-term operation as server. I initially ran with Windows 11 for a few days, and after a few inexplicable blue screens/reboots, I decisively switched to Ubuntu.

To simplify the installation, I use the latest version of Desktop Ubuntu 22.04 LTS.


## B. Setup a headless unbuntu
Somewhat weirdly, we needed both a GUI version ubuntu (because we need graphical WSJTX) and at the same time we wanted to run unattended without plugging into a hardware monitor.

(I like runlevel 3, but after struggling for a long time to remove WSJTX from toolchain, I open up wsjtx again and compromise with this imperfect world.

I like wsjtx, but it too heavy for this project, especially its GUI that never be used in this toolchain. I tried many ft8 protocal decoders on github, but none of them can meet stability, decoding speed, and decoding sensitivity at the same time. 

The best decoder is, of course, the built-in JT9.exe of WSJTX, but when I detach it out and use it separately, I just can't get it to smoothly decode the 48k audio stream fed to it. Perhaps more time is needed to read the source code of WSJTX.)

So, we need WSJTX, WSJTX(and remote-desktop apps, anydesk/teamviewer) need system GUI, GUI need a hdmi cable connected to a hardware monitor. But we hate latter two things when we setup a unattended monitor station, just running as headless server. 

Solution: 
```bash
sudo apt-get install xserver-xorg-video-dummy
```

And adjust(display resolution, VideoRam...) the dummy display config script in "/usr/share/X11/xorg.conf.d/00-dummy-output.conf"(If it does not exist, create one).
My configuration is as follows：
```bash
# Xorg.conf config for dummy video driver
# For usage with for example TeamViewer on a machine without a monitor attached
# and you wanted more then just 1024x768 ;)
#
# Use at own risk, loosly based on info scattered around but these links really helped
# http://arachnoid.com/modelines/ for the modelines (lot of trial and error to figure out which worked over Teamviewer and Xorg)
# https://www.xpra.org/xorg.conf sample config from xpra who seems to use the dummy driver a lot (thanks guys!)

Section "Device"
	Identifier "dummy_videocard"
	Option "NoDDC" "true"
	Option "IgnoreEDID" "true"

	# Debian: apt-get install xserver-xorg-video-dummy
	Driver "dummy"
	
	# You could lower this to suit your needs, however you will need
	# a quite high amount to run such crazy resolutions
	VideoRam 524288
EndSection

Section "Monitor"
	Identifier "dummy_monitor"

	# 16:9 4k
	Modeline "3840x2160_20.00" 218.15 3840 4016 4416 4992 2160 2161 2164 2185

	# 21:9 "4k"
	Modeline "3440x1440_20.00" 124.95 3440 3520 3864 4288 1440 1441 1444 1457

	# Usual 27" suspect before 4k era
	Modeline "2560x1440" 42.12 2560 2592 2752 2784 1440 1475 1478 1513

	# Oddball 1920 resolution
	Modeline "1920x1440" 69.47 1920 1960 2152 2384 1440 1441 1444 1457

	# 16:10 "Full-HD"
	Modeline "1920x1200" 26.28 1920 1952 2048 2080 1200 1229 1231 1261

	# 16:9 Full HD
	Modeline "1920x1080" 23.53 1920 1952 2040 2072 1080 1106 1108 1135

	# These are just crazy high to ensure stuff works
	HorizSync   5.0 - 1000.0
	VertRefresh 5.0 - 1000.0
EndSection

Section "Screen"
	Identifier "dummy_screen"
	Device "dummy_videocard"
	Monitor "dummy_monitor"
	DefaultDepth 24
	SubSection "Display"
		Depth 24
		Modes "3840x2160_20.00" "3440x1440_20.00" "2650x1440" "1920x1440" "1920x1200" "1920x1080"
		
		# Not sure why, but 3440x1440 won't work when the Virtual is set to "3840 2160"
		# However it will complain in the Xorg.log when you didn't comment out the 3840x2160 resolution at the top
		#
		# Uncomment this for 21:9 4k
		Virtual 3440 1440

		# Uncomment this for 16:9 4k
		#Virtual 3840 2160
	EndSubSection
EndSection
```

Remember to temporary move "00-dummy-output.conf" from the "/usr/share/X11/xorg.conf.d/" directory to elsewhere when you plug hdmi cable back to a real monitor.

**Note for Raspberry Pi**

Raspberry Pi operation system may need not a dummy display solution(headless already), but you may want to consider adjusting the system time to slow down the system clock by two or three seconds when the FT8 decoding stutters.

chrony may help:
```bash
sudo apt-get install chrony
```
Edit /etc/chrony/chrony.conf content:
```bash
pool 2.debian.pool.ntp.org iburst offset -2.5
```


## C. Environment preparation
Open ssh access, install your favorite remote desktop app(teamviewer/anydesk/vnc...).
And you may need following packages:

```bash
sudo apt-get install python3 ncat net-tools libusb-1.0-0-dev git cmake build-essential
```

Then copy(or git clone) the whole monitor/ dir under this project to your station.


## D. build sdr drivers
* For rtl-sdr build & install guide, see [osmocom.org](https://osmocom.org/projects/rtl-sdr/wiki#Building-the-software), [keenerd/rtl-sdr](https://github.com/keenerd/rtl-sdr), or [rtl-sdr-blog](https://github.com/rtlsdrblog/rtl-sdr-blog).

* For SDRplay RSP1, see [API Installation & Build Scripts](https://www.sdrplay.com/dlfinishs/).

**Note**
If you previously installed librtlsdr-dev via the package manager you should remove this first BEFORE installing these drivers. To completely remove these drivers use the following commands:

```bash
sudo apt purge ^librtlsdr
sudo rm -rvf /usr/lib/librtlsdr* /usr/include/rtl-sdr* /usr/local/lib/librtlsdr* /usr/local/include/rtl-sdr* /usr/local/include/rtl_* /usr/local/bin/rtl_*
```

You may also need to disable the following system default drivers:

```bash
vi /etc/modprobe.d/blacklist-sdr.conf 
```
Content:
```bash
blacklist dvb_usb_rtl28xxu
blacklist sdr_msi3101
blacklist msi001
blacklist msi2500
```


## E. build & install CSDR
I don't use any SDR software, such as SDR#/SDR++/SDRUNO etc., because the waterfall of these software consumes a lot of CPU/GPU, which is unnecessary to increase station power consumption.

Instead, I use the applications that came with the SDR driver, such as rtl_sdr/rsp_tcp to output I/Q raw data directly. WSJTX needs demodulated 48k audio stream input, so we need some intermediate conversion tools in our toolchain.

[CSDR](https://github.com/ha7ilm/csdr) is a wonderful software DSP tool, which can cut and convert the audio data from the SSB channel at a suitable sampling rate. For detailed usage, please see its documentation.

```bash
git clone https://github.com/ha7ilm/csdr
cd csdr
make
sudo make install
```

**Note for Raspberry pi 3**

Editing the "Makefile" in csdr source dir and changing the PARAMS_NEON flags to the following:

```bash
-march=armv8-a
-mtune=cortex-a53
-mfpu=neon-fp-armv8
```

Also under PARAMS_RASPI set:

```bash
-mcpu=cortex-a53
-mfpu=neon-fp-armv8
```


## F. install PulseAudio & MPlayer
We need an intermediate audio server to continuously produce 48k audio stream from csdr, and a virtual audio channel to connect this stream and WSJTX:

```bash
sudo apt-get install pulseaudio pavucontrol mplayer
```

And recommend disabling PulseAudio logging, as this seems to be a large user of CPU cycles. 
Edit "/etc/pulse/daemon.conf", find "log-level" and change it to "log-level = error":

```bash
; log-target = auto
log-level = error
; log-meta = no
```


## G. install WSJT-X
Download and install from [WSJT-X Official website](https://wsjt.sourceforge.io/wsjtx.html) 


## H. Run all things up!
1. Setup virtual audio channel
    ```bash
    pulseaudio --start
    pactl load-module module-null-sink sink_name=virtual-cable
    ```

2. Run SDR    
    Connect the antenna coax to your SDR, plug the dongle into your station USB port.    
    2.a If you use rtl-sdr, run:
    ```bash
    rtl_sdr -s 1200000 -f 50400000 - | csdr convert_u8_f | csdr shift_addition_cc `python -c "print(float(50400000-50313000)/1200000)"` | csdr fir_decimate_cc 25 0.05 HAMMING | csdr bandpass_fir_fft_cc 0 0.5 0.05 | csdr realpart_cf | csdr agc_ff | csdr limit_ff | csdr convert_f_s16 | mplayer -nocache -rawaudio samplesize=2:channels=1:rate=48000 -demuxer rawaudio -
    ```

    "-s 1200000" set sample rate to 1.2M, "-f 50400000" set center frequency for 6m band(with DC offset), "(50400000-50313000)/1200000" shift sample frequency to ft8's 50.313Mhz, and "mplayer -nocache..." things setup a audio stream server.
    You may change 50400000/50313000 to your favorite band.

    2.b If you use SDRplay RSP1, which only provided a tcp application officially, run:
    ```bash
    rsp_tcp -E
    ```

    And then open a new terminal, run from monitor/ dir:
    ```bash
    python3 rsp1_forwarder.py -f 50400000 | csdr convert_u8_f | csdr shift_addition_cc `python3 -c "print(float(50400000-50313000)/1200000)"` | csdr fir_decimate_cc 25 0.05 HAMMING | csdr bandpass_fir_fft_cc 0 0.5 0.05 | csdr realpart_cf | csdr agc_ff | csdr limit_ff | csdr convert_f_s16 | mplayer -nocache -rawaudio samplesize=2:channels=1:rate=48000 -demuxer rawaudio -
    ```
    This python script is actually a relay server, extracts raw I/Q data from rsp_tcp stream and outputs to stdout.

    Now open "pulseAudio Volume Control" ubuntu App, checkout "virtual-cable Audio" should show in "Output Devices" tab and "Mplayer" should show in "Playback" tab.

3. Run WSJTX    
    Open wsjtx app, open "File->Settings", in "Audio" tab, set Soundcard Input to "virtual-cable.monitor", and set Soundcard Output to "virtual-cable". Then change to Settings "Reporting" tab, set UDP Server to "127.0.0.1" and UDP Server port number to "2237". Save & Close settings window.
    Change band in wjstx main window to "6m".

4. Run monitor server    
    Open a new terminal, run from monitor/ dir:
    ```bash
    python3 wsjtx_msg_server.py -w 'https://YOUR_WEB_SERVER/report?id=YOUR_STATION_NAME&band=50.313&token=YOUR_ACCESS_TOKEN_FOR_MONITOR'
    ```
    This server receives ft8 report from wsjtx and upload decoded messages to your statistics data receiving server(see below).


## I. Setup statistics data receiving server
The monitor/wsjtx_msg_server.py script sents decoded ft8 messages to your remote web server. The current implementation in the webserver/ directory is very simple, providing three APIs:

+ https://YOUR_SERVER_DOMAIN/report For receiving statistics data from monitor
+ https://YOUR_SERVER_DOMAIN/minutes For querying data in minutes
+ https://YOUR_SERVER_DOMAIN/hours For querying data in hours

If it is used on a small scale, it can be simply run "python3 sqlite_server.py -t YOUR_ACCESS_TOKEN_FOR_MONITOR", and all data will stored locally in sqlite database(file "db.sqlite").

If you plan to run for a long time, or provide public access, I recommend cloud based deploying.

For amazon AWS free plan, I wrote a webserver/aws_server.py as a AWS lambda script, which use dynamodb for persistence and can be setup behind AWS API gateway service. Checkout [AWS docs](https://docs.aws.amazon.com/) for deploying details.

Files under project frontend/ dir is a demonstration [echarts](https://echarts.apache.org/) page, drop those to your web server www/ dir(or to AWS amplify hosting), open browser visit index.html, and then you should see some statistics charts.


# Todos:
- Add a local cache of decoded messages on Monitor to cope with temporary station disconnection.
- Replace all the GUI apps with terminal apps for true headless operation.
- Remote band switching via web server.


# License

MIT.