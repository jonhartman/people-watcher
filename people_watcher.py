#!./bin/python

# Monitors for people.
# In detection mode, light is red if no people detected, green if a person is detected.
# In alarm mode, light will latch on and flash furiously, if a person is detected.
# To install, change the following configuration parameters, as desired:


import sys
import os
import json
import paho.mqtt.client as mqtt
import requests
import time


# Static configuration parameters

MQTT_SERVER_PROD = '127.0.0.1'
MQTT_SERVER_DEV = '127.0.0.1'
MQTT_MERAKI_NETWORK = 'insertMerakiNetworkIdHere'
MQTT_MERAKI_MT30_MAC = 'MA:CA:DD:RE:SS:SS'
LED_API_URL = 'http://127.0.0.1:8888/light/0/'
PID_FILE = './.pid'


# Configuration parameters based on environment

MQTT_TOPIC = [('/merakimv/+/0', 0),
              ('meraki/v1/mt/' + MQTT_MERAKI_NETWORK + '/ble/+/buttonReleased', 0),
              ('meraki/v1/mt/' + MQTT_MERAKI_NETWORK + '/ble/' + MQTT_MERAKI_MT30_MAC + '/button released', 0)
              ]

environment = os.getenv('ENV')
if environment is None:
    raise Exception('HARD STOP: No production indicator in environmental variables.')
elif environment == 'dev':
    MQTT_ADDRESS = MQTT_SERVER_DEV
    MQTT_CLIENT_ID = 'people_watcher_dev'
elif environment == 'prod':
    MQTT_ADDRESS = MQTT_SERVER_PROD
    MQTT_CLIENT_ID = 'people_watcher_prod'
else:
    raise Exception('HARD STOP: Invalid production indicator in environmental variables.')

try:
    response = requests.request('GET', LED_API_URL + "off", data=None, timeout=5)
except Exception as error:
    raise Exception('HARD STOP: No communication with indication target.')

# Functions

triggered = False
currentColor = None
mode = 'undeclared'
transitionLatch = False
lastColorSecond = 0
peopleCount = 0


def on_connect(client, userdata, flags, rc):
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    global mode

    if msg.topic.split('/')[2] == 'mt' and msg.retain == 0:
        button_press(msg)
    else:
        if mode == 'alarm':
            mode_alarm(msg)
        elif mode == 'detection':
            mode_detection(msg)
        elif mode == 'undeclared':
            mode_undeclared()
        else:
            raise Exception('HARD STOP: Invalid operating mode detected.')


def debug_message(localError):
    if environment == 'dev':
        timeStampUnix = int(time.time())
        print(timeStampUnix, localError)


def button_press(msg):
    # If the MT30 was pressed, reset the light and status.
    global mode
    global triggered

    payload = json.loads(msg.payload.decode('utf-8'))
    debug_message(payload['action'])

    try:
        requests.request('GET', LED_API_URL + "off", data=None, timeout=5)
    except Exception as localError:
        pass
    else:
        triggered = False
        if payload['action'] == 'short press' or payload['action'] == 'shortPress':
            mode = 'detection'
        elif payload['action'] == 'long press' or payload['action'] == 'longPress':
            mode = 'alarm'


def mode_detection(msg):
    global currentColor
    global lastColorSecond
    global peopleCount
    # Pull the people count value and set the color.

    if msg is not None:
        payload = json.loads(msg.payload.decode('utf-8'))
        currentSecond = int(time.time())

        # If it's the same second as last time, let's tally the visible people.
        # If it's a new second, let's evaluate that number, act upon a non-zero number, and reset the count

        if lastColorSecond == currentSecond:
            peopleCount += int(payload['counts']['person'])
            debug_message("New peoplecount is: " + str(peopleCount))
        else:
            lastColorSecond = currentSecond
            debug_message("ACT!")

            if peopleCount > 0 and currentColor != "red":
                try:
                    requests.request('GET', LED_API_URL + "on/red", data=None, timeout=5)
                except Exception as localError:
                    debug_message("COLOR CHANGE: failed to change to red" + str(localError))
                else:
                    currentColor = "red"
                    debug_message("COLOR CHANGE: red")
            elif peopleCount > 0 and currentColor == 'red':
                peopleCount = 0
            elif peopleCount == 0 and currentColor != "green":
                try:
                    requests.request('GET', LED_API_URL + "on/green", data=None, timeout=5)
                except Exception as error:
                    debug_message("COLOR CHANGE: failed to change to green" + str(error))
                else:
                    currentColor = "green"
                    debug_message("COLOR CHANGE: green")
            else:
                debug_message("HEARTBEAT... count: " +
                              str(payload['counts']['person']) +
                              " color: " + currentColor +
                              " total count: " + str(peopleCount))


def mode_alarm(msg):
    global triggered

    if msg.topic.split('/')[1] == 'merakimv':

        if not triggered:
            payload = json.loads(msg.payload.decode('utf-8'))

            if payload['counts']['person'] > 0 and triggered is False:
                try:
                    requests.request('GET', LED_API_URL + "fli", data=None, timeout=5)
                except Exception:
                    pass
                else:
                    triggered = True
                    debug_message("ACTION: Person detected by " + msg.topic.split('/')[2])

            debug_message("HEARTBEAT... triggered: " + str(triggered) + "\tpayload: " + str(payload))
        else:
            debug_message("HEARTBEAT... triggered: " + str(triggered) + " type is: " + msg.topic.split('/')[1])
    else:
        debug_message('ERROR: Non-MV data fed to alarm function.')


def mode_undeclared():
    global triggered

    if not triggered:
        try:
            requests.request('GET', LED_API_URL + "pulse/blue", data=None, timeout=5)
        except Exception:
            pass
        else:
            triggered = True

# Main


if environment == 'prod':
    # Fork a child process and exit
    pid = os.fork()
    pidFile = open(PID_FILE, "w")
    pidFile.writelines(str(os.getpid()))
    pidFile.close()

    if pid > 0:
        sys.exit(1)

# Initialize MQTT
mqtt_client = mqtt.Client(MQTT_CLIENT_ID)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_ADDRESS, 1883)
mqtt_client.loop_forever()
