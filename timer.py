import esp32
import gc
import machine
import network
import ntptime
import st7789
import utime as time
import uasyncio.core as asyncio
from machine import Pin, SPI, RTC
from umqtt_simple import MQTTClient
from ucollections import OrderedDict
import vga1_bold_16x32 as font1
import vga1_bold_16x16 as font2


loop = asyncio.get_event_loop()
machine.freq(160000000)
backlight = Pin(4, Pin.OUT, None)
rtc = RTC()
SPI2 = SPI(2, baudrate=30000000, polarity=1, phase=1, sck=Pin(18), mosi=Pin(19))
MQTT_SERVER = "10.0.40.183"
MQTT_CLIENT = None
WIFI = network.WLAN(network.STA_IF)
AP = network.WLAN(network.AP_IF)
AP.active(False)

TASKS = OrderedDict()
TASKS['CAPEX'] = {}
TASKS['CAPEX']['desc'] = 'Capex work'
TASKS['CAPEX']['time'] = []
TASKS['OPEX'] = {}
TASKS['OPEX']['desc'] = 'Opex work'
TASKS['OPEX']['time'] = []
TASKS['JIRA123'] = {}
TASKS['JIRA123']['desc'] = 'desc3 sadsf sdf eerr'
TASKS['JIRA123']['time'] = []


class Timer:
    scan_ms = 50
    debounce_ms = 100
    refresh_sec = 3
    running = None
    current = None
    key_pressed = None
    key1 = None
    key2 = None
    key3 = None
    start_init = None
    start_ts = None
    stop_ts = None
    refresh_ts = None
    delta = None
    index = None
    select_counter = None
    total_time = None

    def __init__(self, tft):
        self.tft = tft
        self.running = None
        self.key1 = Pin(33, Pin.IN, Pin.PULL_DOWN)
        self.key2 = Pin(25, Pin.IN, Pin.PULL_DOWN)
        self.key3 = Pin(26, Pin.IN, Pin.PULL_DOWN)
        self.start_init = None
        self.start_ts = None
        self.stop_ts = None
        self.refresh_ts = time.ticks_ms()
        self.delta = None
        self.current = None  # current jira selected
        self.index = 0
        self.select_counter = 0
        self.total_time = (0, 0, 0)
        self.start_screen()

    def start_screen(self):
        self.tft.text(font1, 'Select Jira.', 0, 0, st7789.WHITE, st7789.BLACK)

    async def refresh(self):
        while True:
            if not self.start_init:
                await asyncio.sleep(1)
                continue
            if time.ticks_diff(time.ticks_ms(), self.key_pressed) < 1500:
                await asyncio.sleep_ms(10)
                continue
            print('refresh')

            if time.ticks_diff(time.ticks_ms(), self.key_pressed) < 5000:
                self.tft.fill_rect(0, 0, 240, 80, st7789.BLACK)
                self.tft.hline(0, 32, 249, st7789.BLUE)
                self.tft.hline(0, 33, 249, st7789.BLUE)
                jira = list(TASKS.keys())[self.index]
                #  Header
                self.tft.text(font1, list(TASKS.keys())[self.index], 0, 0, st7789.WHITE, st7789.MAGENTA)
                #  Description
                desc1, desc2 = TASKS[jira]['desc'][:14], TASKS[jira]['desc'][14:]
                self.tft.text(font2, desc1, 0, 40, st7789.WHITE, st7789.BLACK)
                if desc2:
                    self.tft.text(font2, desc2[:15], 0, 60, st7789.WHITE, st7789.BLACK)

            #  Clock
            self.tft.text(font1, '{:02d}:{:02d}'.format(time.localtime()[3], time.localtime()[4]), 0, 100, st7789.WHITE, st7789.BLACK)
            # Timer
            self.update_total_time()
            h, m, s = self.total_time
            if self.running:
                self.tft.text(font1, '{:02d}h{:02d}m{:02d}s'.format(h, m, s), 100, 100, st7789.GREEN, st7789.BLUE)
            else:
                self.tft.text(font1, '{:02d}h{:02d}m{:02d}s'.format(h, m, s), 100, 100, st7789.BLACK, st7789.YELLOW)

            await asyncio.sleep(Timer.refresh_sec)

    async def check_pressed(self):
        while True:
            await asyncio.sleep_ms(Timer.scan_ms)
            keys = [self.key1.value(), self.key2.value(), self.key3.value()]
            if any(keys):
                self.key_pressed = time.ticks_ms()
                getattr(Timer, 'key' + str(keys.index(1) + 1))(self)
                await asyncio.sleep_ms(Timer.debounce_ms)

    def update_total_time(self):
        if self.running:
            h, m, s = convert_ticks(self.refresh_ts, time.ticks_ms())
            ch, cm, cs = self.total_time

            sn = (s + cs) % 60
            s_rest = int((s + cs) / 60)
            mn = (m + cm + s_rest) % 60
            m_rest = int((m + cm + s_rest) / 60)
            hn = h + ch + m_rest

            self.total_time = (hn, mn, sn)
        self.refresh_ts = time.ticks_ms()

    def key1(self):
        if self.running:
            self.running = False
            self.tft.fill(0)
            self.tft.text(font1, 'Stopping', 0, 0, st7789.WHITE, st7789.BLACK)
            self.stop_ts = time.ticks_ms()
            self.update_total_time()
            self.publish('STOP ' + str(list(TASKS.keys())[self.index]) + ' ' + str(self.stop_ts) + ' ' + str(rtc.datetime()))

    def key2(self):
        if self.running:
            self.tft.fill(0)
            self.tft.text(font1, 'Stop first.', 0, 0, st7789.WHITE, st7789.BLACK)
        else:
            self.select_counter += 1

            self.index = self.select_counter % len(TASKS)
            print(self.index)
            self.tft.fill_rect(0, 0, 240, 100, st7789.BLACK)
            jira = list(TASKS.keys())[self.index]
            self.tft.text(font1, list(TASKS.keys())[self.index], 0, 0, st7789.WHITE, st7789.BLACK)
            desc1, desc2 = TASKS[jira]['desc'][:14], TASKS[jira]['desc'][14:]
            self.tft.text(font2, desc1, 0, 40, st7789.WHITE, st7789.BLACK)
            if desc2:
                self.tft.text(font2, desc2[:15], 0, 60, st7789.WHITE, st7789.BLACK)

    def key3(self):
        if not self.start_init:
            self.start_init = True
        if not self.running:
            self.running = True
            self.tft.fill(0)
            self.tft.text(font1, 'Starting:', 0, 0, st7789.WHITE, st7789.BLACK)
            self.tft.text(font1, str(list(TASKS.keys())[self.index]), 0, 34, st7789.WHITE, st7789.BLACK)
            self.start_ts = time.ticks_ms()
            self.publish('START ' + str(list(TASKS.keys())[self.index]) + ' ' + str(self.start_ts) + ' ' + str(rtc.datetime()))

    def publish(self, value):
        print('publish mqtt {}'.format(str(value)))
        try:
            MQTT_CLIENT.publish(b'/work/timer/temp', str(value))
        except OSError:
            self.tft.text(font1, 'MQTT!', 0, 0, st7789.WHITE, st7789.BLACK)
            self.tft.text(font1, 'Error!', 0, 34, st7789.WHITE, st7789.BLACK)


def convert_ticks(start, stop):
    delta = int(time.ticks_diff(stop, start) / 1000)
    hours = int(delta / 3600)
    rest = delta % 3600
    minutes = int(rest / 60)
    rest = rest % 60
    seconds = int(rest)
    print('{}h {}m {}s'.format(hours, minutes, seconds))
    return hours, minutes, seconds


def init_oled():
    tft = st7789.ST7789(
        SPI2,
        135,
        240,
        reset=Pin(23, Pin.OUT, None),
        cs=Pin(5, Pin.OUT, None),
        dc=Pin(16, Pin.OUT, None),
        backlight=backlight,
        rotation=1)
    tft.init()
    return tft


async def update_time():
    while True:
        if WIFI.isconnected():
            ntptime.settime()
            time_cet = list(rtc.datetime())
            week = int(time.localtime()[7]/7)
            if week < 13 or week > 44:
                time_cet[4] += 1
            else:
                time_cet[4] += 2
            rtc.datetime(tuple(time_cet))
        await asyncio.sleep(3600)


async def a_do_connect():
    print('connecting to network...')
    while True:
        global MQTT_CLIENT
        if not WIFI.isconnected():
            WIFI.active(True)
            WIFI.connect('', '')
            while not WIFI.isconnected():
                await asyncio.sleep_ms(100)
                pass
        MQTT_CLIENT = MQTTClient("timer", MQTT_SERVER)
        MQTT_CLIENT.connect(clean_session=False)
        MQTT_CLIENT.publish(b'/work/timer/temp/telemetry', str('a_do_connect()'))
        await asyncio.sleep(100)


def main(timer):
    loop.create_task(a_do_connect())
    loop.create_task(update_time())
    loop.create_task(timer.check_pressed())
    loop.create_task(timer.refresh())
    loop.run_forever()


print('starting')
gc.enable()
led = init_oled()
timer = Timer(led)
main(timer)
