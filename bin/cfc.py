#!/usr/bin/python3
import argparse
import paho.mqtt.client as mqtt
import datetime
import os
import time
import threading
import signal
from time import sleep
from binascii import unhexlify
from random import randint
from pycomfoconnect import *
import getopt
import sys
import json
import configparser
from mqtt_data import sensor_data
import logging

interval = [0 for x in range(300)]

# Set by on_connect()/on_disconnect() - read by the status-writer thread. paho's own
# reconnect (client.reconnect_delay_set()) already handles recovering the MQTT link by
# itself; this flag only exists so the status file/webfrontend can show whether it is
# currently up, it doesn't trigger any reconnect logic of its own.
mqtt_connected = False
mqtt_last_change = None

# Filled in by main() from --statusfile. None until then, so write_status() can no-op
# safely if it is ever called too early.
statusfile = None

def on_publish(client, userdata, mid):
    _LOGGER.debug("Published Data - mid: "+str(mid))
    pass

def on_connect(client, userdata, flags, rc):
    global mqtt_connected, mqtt_last_change

    if rc==0:
        _LOGGER.info("Connection returned result: "+mqtt.connack_string(rc))
    else:
        _LOGGER.error("Disconnection returned result: "+mqtt.connack_string(rc))

    mqtt_connected = (rc == 0)
    mqtt_last_change = time.time()

    client.publish(mqtt_topic + "Status", payload="Online", qos=0, retain=True)

    client.subscribe(mqtt_topic + "FAN_MODE", qos=0)
    client.subscribe(mqtt_topic + "FAN_MODE_AWAY", qos=0)
    client.subscribe(mqtt_topic + "FAN_MODE_LOW", qos=0)
    client.subscribe(mqtt_topic + "FAN_MODE_MEDIUM", qos=0)
    client.subscribe(mqtt_topic + "FAN_MODE_HIGH", qos=0)
    client.subscribe(mqtt_topic + "MODE", qos=0)
    client.subscribe(mqtt_topic + "MODE_AUTO", qos=0)
    client.subscribe(mqtt_topic + "MODE_MANUAL", qos=0)
    client.subscribe(mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN", qos=0)
    client.subscribe(mqtt_topic + "START_EXHAUST_FAN", qos=0)
    client.subscribe(mqtt_topic + "START_SUPPLY_FAN", qos=0)
    client.subscribe(mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN", qos=0)
    client.subscribe(mqtt_topic + "BOOST_MODE_END", qos=0)
    client.subscribe(mqtt_topic + "TEMPPROF", qos=0)
    client.subscribe(mqtt_topic + "TEMPPROF_NORMAL", qos=0)
    client.subscribe(mqtt_topic + "TEMPPROF_COOL", qos=0)
    client.subscribe(mqtt_topic + "TEMPPROF_WARM", qos=0)
    client.subscribe(mqtt_topic + "BYPASS", qos=0)
    client.subscribe(mqtt_topic + "BYPASS_ON", qos=0)
    client.subscribe(mqtt_topic + "BYPASS_OFF", qos=0)
    client.subscribe(mqtt_topic + "BYPASS_AUTO", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_TEMP", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_TEMP_OFF", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_TEMP_AUTO", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_TEMP_ON", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMC", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMC_OFF", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMC_AUTO", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMC_ON", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMP", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMP_OFF", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMP_AUTO", qos=0)
    client.subscribe(mqtt_topic + "SENSOR_HUMP_ON", qos=0)
    client.subscribe(mqtt_topic + "BOOST_MODE", qos=0)
    client.subscribe(mqtt_topic + "BOOST_MODE_TIME", qos=0)
    client.subscribe(mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN_TIME", qos=0)
    client.subscribe(mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN_TIME", qos=0)
    client.subscribe(mqtt_topic + "BYPASS_ON_TIME", qos=0)
    client.subscribe(mqtt_topic + "BYPASS_OFF_TIME", qos=0)

def on_disconnect(client, userdata, rc):
    global mqtt_connected, mqtt_last_change

    # Closing the session #############################################################################################
    if rc==0:
        _LOGGER.info("Disconnection returned result: "+mqtt.connack_string(rc))
    else:
        _LOGGER.error("Disconnection returned result: "+mqtt.connack_string(rc))

    mqtt_connected = False
    mqtt_last_change = time.time()

def on_message(client, userdata, msg):
    _LOGGER.info("from MQTT %s = %s" % (msg.topic , str(msg.payload.decode("utf-8"))))

    topic = msg.topic
    value = str(msg.payload.decode("utf-8"))

    try:
        _dispatch_message(topic, value)
    except Exception as e:
        # A malformed/empty MQTT payload (e.g. an empty retained message, or a value
        # that isn't a valid number where int(value) is expected) must never crash
        # this callback: paho runs on_message on its network thread, and an uncaught
        # exception here kills that thread - the plugin then silently stops reacting
        # to MQTT until it is manually restarted. Log and ignore instead.
        _LOGGER.error("Fehler bei Verarbeitung von MQTT %s = '%s': %s" % (topic, value, str(e)))

def _dispatch_message(topic, value):
    global boost_mode_time, ventmode_stop_supply_fan_time, ventmode_stop_exhaust_fan_time, bypass_on_time, bypass_off_time

    # execute matching command
    if topic == mqtt_topic + "FAN_MODE":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_AWAY)
            _LOGGER.info("Befehl FAN_MODE_AWAY an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_LOW)
            _LOGGER.info("Befehl FAN_MODE_LOW an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_MEDIUM)
            _LOGGER.info("Befehl FAN_MODE_MEDIUM an Lüftungsanlage gesendet")
        elif int(value) == 3:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_HIGH)
            _LOGGER.info("Befehl FAN_MODE_HIGH an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("FAN_MODE: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2, 3")
    elif topic == mqtt_topic + "FAN_MODE_AWAY":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_AWAY)  # Go to away mode
            _LOGGER.info("Befehl FAN_MODE_AWAY an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("FAN_MODE_AWAY: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "FAN_MODE_LOW":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_LOW)
            _LOGGER.info("Befehl FAN_MODE_LOW an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("FAN_MODE_LOW: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "FAN_MODE_MEDIUM":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_MEDIUM)
            _LOGGER.info("Befehl FAN_MODE_MEDIUM an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("FAN_MODE_MEDIUM: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "FAN_MODE_HIGH":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_HIGH)
            _LOGGER.info("Befehl FAN_MODE_HIGH an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("FAN_MODE_HIGH: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "MODE_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_MODE_AUTO)
            _LOGGER.info("Befehl MODE_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("MODE_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "MODE_MANUAL":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_MODE_MANUAL)
            _LOGGER.info("Befehl MODE_MANUAL an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("MODE_MANUAL: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "MODE":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_MODE_MANUAL)
            _LOGGER.info("Befehl MODE_MANUAL an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_MODE_AUTO)
            _LOGGER.info("Befehl MODE_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("MODE: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 1, 2")
    elif topic == mqtt_topic + "START_EXHAUST_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_START_EXHAUST_FAN)
            _LOGGER.info("Befehl START_EXHAUST_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("START_EXHAUST_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "START_SUPPLY_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_START_SUPPLY_FAN)
            _LOGGER.info("Befehl START_SUPPLY_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("START_SUPPLY_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BOOST_MODE_END":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_BOOST_MODE_END)
            _LOGGER.info("Befehl BOOST_MODE_END an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BOOST_MODE_END: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "TEMPPROF_NORMAL":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_NORMAL)
            _LOGGER.info("Befehl TEMPPROF_NORMAL an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("TEMPPROF_NORMAL: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "TEMPPROF_COOL":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_COOL)
            _LOGGER.info("Befehl TEMPPROF_COOL an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("TEMPPROF_COOL: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "TEMPPROF_WARM":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_WARM)
            _LOGGER.info("Befehl TEMPPROF_WARM an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("TEMPPROF_WARM: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "TEMPPROF":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_NORMAL)
            _LOGGER.info("Befehl TEMPPROF_NORMAL an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_COOL)
            _LOGGER.info("Befehl TEMPPROF_COOL an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(CMD_TEMPPROF_WARM)
            _LOGGER.info("Befehl TEMPPROF_WARM an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("TEMPPROF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")
    elif topic == mqtt_topic + "BYPASS_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_BYPASS_AUTO)
            _LOGGER.info("Befehl BYPASS_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_TEMP_OFF":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_OFF)
            _LOGGER.info("Befehl SENSOR_TEMP_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_TEMP_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_TEMP_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_AUTO)
            _LOGGER.info("Befehl SENSOR_TEMP_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_TEMP_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_TEMP_ON":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_ON)
            _LOGGER.info("Befehl SENSOR_TEMP_ON an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_TEMP_ON: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_TEMP":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_AUTO)
            _LOGGER.info("Befehl SENSOR_TEMP_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_ON)
            _LOGGER.info("Befehl SENSOR_TEMP_ON an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_OFF)
            _LOGGER.info("Befehl SENSOR_TEMP_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_TEMP: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")
    elif topic == mqtt_topic + "SENSOR_HUMC_OFF":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_OFF)
            _LOGGER.info("Befehl SENSOR_HUMC_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMC_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMC_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_AUTO)
            _LOGGER.info("Befehl SENSOR_HUMC_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMC_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMC_ON":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_ON)
            _LOGGER.info("Befehl SENSOR_HUMC_ON an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMC_ON: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMC":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_AUTO)
            _LOGGER.info("Befehl SENSOR_HUMC_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_ON)
            _LOGGER.info("Befehl SENSOR_HUMC_ON an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_OFF)
            _LOGGER.info("Befehl SENSOR_HUMC_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMC: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")
    elif topic == mqtt_topic + "SENSOR_HUMP_OFF":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_OFF)  #
            _LOGGER.info("Befehl SENSOR_HUMP_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMP_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMP_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_AUTO)  #
            _LOGGER.info("Befehl SENSOR_HUMP_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMP_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMP_ON":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_ON)  #
            _LOGGER.info("Befehl SENSOR_HUMP_ON an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMP_ON: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "SENSOR_HUMP":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_AUTO)
            _LOGGER.info("Befehl SENSOR_HUMP_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_ON)
            _LOGGER.info("Befehl SENSOR_HUMP_ON an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_OFF)
            _LOGGER.info("Befehl SENSOR_HUMP_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("SENSOR_HUMP: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")
    elif topic == mqtt_topic + "BOOST_MODE_TIME":
        boost_mode_time=to_big(value)
        _LOGGER.debug("BOOST_MODE_TIME hex: " + str(boost_mode_time))
        _LOGGER.info("BOOST_MODE_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "BOOST_MODE":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x01\x06\x00\x00\x00\x00' + boost_mode_time + b'\x00\x00\x03')
            _LOGGER.info("Befehl BOOST_MODE an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BOOST_MODE: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN_TIME":
        ventmode_stop_supply_fan_time=to_big(value)
        _LOGGER.debug("VENTMODE_STOP_SUPPLY_FAN_TIME hex " + str(ventmode_stop_supply_fan_time))
        _LOGGER.info("VENTMODE_STOP_SUPPLY_FAN_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x07\x01\x00\x00\x00\x00' + ventmode_stop_supply_fan_time + b'\x00\x00\x01')
            _LOGGER.info("Befehl VENTMODE_STOP_SUPPLY_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("VENTMODE_STOP_SUPPLY_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN_TIME":
        ventmode_stop_exhaust_fan_time=to_big(value)
        _LOGGER.debug("VENTMODE_STOP_EXHAUST_FAN_TIME in hex: " + str(ventmode_stop_exhaust_fan_time))
        _LOGGER.info("VENTMODE_STOP_EXHAUST_FAN_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x06\x01\x00\x00\x00\x00' + ventmode_stop_exhaust_fan_time + b'\x00\x00\x01')
            _LOGGER.info("Befehl VENTMODE_STOP_EXHAUST_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("VENTMODE_STOP_EXHAUST_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS_ON_TIME":
        bypass_on_time=to_big(value)
        _LOGGER.debug("BYPASS_ON_TIME in hex: " + str(bypass_on_time))
        _LOGGER.info("BYPASS_ON_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "BYPASS_ON":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_on_time + b'\x00\x00\x01')
            _LOGGER.info("Befehl BYPASS_ON an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS_ON: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS_OFF_TIME":
        bypass_off_time=to_big(value)
        _LOGGER.debug("BYPASS_OFF_TIME in hex: " + str(bypass_off_time))
        _LOGGER.info("BYPASS_OFF_TIME " + str(value) + " sec")
    elif topic == mqtt_topic + "BYPASS_OFF":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_off_time + b'\x00\x00\x02')
            _LOGGER.info("Befehl BYPASS_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_BYPASS_AUTO)
            _LOGGER.info("Befehl BYPASS_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_on_time + b'\x00\x00\x01')
            _LOGGER.info("Befehl BYPASS_ON an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_off_time + b'\x00\x00\x02')
            _LOGGER.info("Befehl BYPASS_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")

def on_subscribe(client, userdata, mid, granted_qos):
    _LOGGER.info("Subscribed: "+str(mid)+" "+str(granted_qos))

def bridge_discovery(ip, debug, search):
    ## Bridge discovery ################################################################################################
    # Method 1: Use discovery to initialise Bridge
    if search:
        bridges = Bridge.discover(timeout=1)
        if bridges:
            bridge = bridges[0]
            _LOGGER.info("Bridge found with discover")
            return bridge
        else:
            bridge = None
            _LOGGER.critical("Bridge not found discover")
            exit(1)
        
    # Method 2: Use direct discovery to initialise Bridge
    bridges = Bridge.discover(ip)
    if bridges:
        bridge = bridges[0]
        _LOGGER.info("Bridge found with IP set")
    else:
        bridge = None
        _LOGGER.critical("Bridge not found with IP set")

    # Method 3: Setup bridge manually
    # bridge = Bridge(args.ip, bytes.fromhex('0000000000251010800170b3d54264b4'))

    if bridge is None:
        _LOGGER.critical("No bridges found!")
        exit(1)

    _LOGGER.info("Bridge found: %s (%s)" % (bridge.uuid.hex(), bridge.host))

    return bridge

def to_little(val):
    little_hex = bytearray.fromhex(val)
    little_hex.reverse()
    #print("Byte array format:", little_hex)

    str_little = ''.join(format(x, '02x') for x in little_hex)

    return str_little

def to_big(val):
    val=int(val)
    big_hex = val.to_bytes(2, byteorder='little').hex()
    big_hex = bytearray.fromhex(big_hex)
    return big_hex

def on_log(client, userdata, level, buf):
    _LOGGER.debug("Paho: " + buf)

def callback_sensor(var, value):
    # for x in unknown:
        # if var == x:
            # print ("unknown:")
            # print (x)
            # print (var)
            # return
    
    if (var == 81 or var == 82 or var == 86 or var == 87):
        value=int(to_little(value), base=16)
        if value == 4294967295:
            value = -1
    elif 'CONV' in sensor_data[var]:
        value = eval(sensor_data[var]['CONV'] % (value))

    # Senden an den MQTT Broker nur bei Änderungen und nach Ablauf der PUSH Zeit, parametriert in mqtt_data.py
    if 'PUSH' in sensor_data[var]:
        if (time.time() > interval[var]):
            (rc, mid) = client.publish(mqtt_topic + sensor_data[var]['NAME'], value, qos=0)
            interval[var] = time.time() + sensor_data[var]['PUSH']
            
            if (rc == 0):
                _LOGGER.info("Erfolgreich published, RC=" + str(rc) + " Sensorname: " + sensor_data[var]['NAME'] + ", " + "Variable " + str(var) + ", Wert: " + str(value) + ", PUSH: " + str(sensor_data[var]['PUSH']) + " sek.")
                _LOGGER.debug("to MQTT %s = %s" % (mqtt_topic + sensor_data[var]['NAME'], value))
            else:
                _LOGGER.error("Fehler published, RC=" + str(rc) + " Sensorname: " + sensor_data[var]['NAME'] + ", " + "Variable " + str(var) + ", Wert: " + str(value) + ", PUSH: " + str(sensor_data[var]['PUSH']) + " sek.")
    else:
        (rc, mid) = client.publish(mqtt_topic + sensor_data[var]['NAME'], value, qos=0)
        
        if (rc == 0):
            _LOGGER.info("Erfolgreich published, RC=" + str(rc) + " Sensorname: " + sensor_data[var]['NAME'] + ", " + "Variable " + str(var) + ", Wert: " + str(value))
            _LOGGER.debug("to MQTT %s = %s" % (mqtt_topic + sensor_data[var]['NAME'], value))
        else:
            _LOGGER.error("Fehler published, RC=" + str(rc) + " Sensorname: " + sensor_data[var]['NAME'] + ", " + "Variable " + str(var) + ", Wert: " + str(value))
    

def write_status_loop():
    """Periodically persist a small health-status JSON to statusfile (ramdisk).

    Runs in its own daemon thread. Deliberately does not import/depend on the
    connection thread's internals beyond reading comfoconnect's plain, cheap
    in-memory timestamps (see comfoconnect.py: last_alive_ping/last_keepalive_ok/
    last_sensor_data) - it just samples and writes them every 1s. This is a
    nice-to-have diagnostic feature: any error here is logged and swallowed, it
    must never be able to take down the actual plugin.

    1s instead of the original 5s: this is a plain JSON write to a ramdisk
    (tmpfs), not real disk I/O, so there's no SD-card-wear concern to weigh
    against faster updates - the only real cost is CPU for a tiny JSON dump,
    which is negligible. Combined with the shorter webfrontend poll interval,
    this brings worst-case status staleness down from ~15s to ~3s.
    """
    while True:
        try:
            if statusfile:
                status = {
                    'pid': os.getpid(),
                    'now': time.time(),
                    'mqtt_connected': mqtt_connected,
                    'mqtt_last_change': mqtt_last_change,
                    'bridge_last_alive_ping': comfoconnect.last_alive_ping if comfoconnect else None,
                    'bridge_last_keepalive_ok': comfoconnect.last_keepalive_ok if comfoconnect else None,
                    'bridge_last_sensor_data': comfoconnect.last_sensor_data if comfoconnect else None,
                    # NOTE: comfoconnect.sensors is a work list (everything we know about
                    # and should try to (re-)register), not a success count - it's already
                    # at its final size as soon as a connection drop pre-remembers the not-
                    # yet-attempted sensors for the reconnect logic, long before most of
                    # them are actually confirmed. sensors_confirmed only contains sensors
                    # the bridge has actually confirmed in the *current* session.
                    'sensors_registered': len(comfoconnect.sensors_confirmed) if comfoconnect else 0,
                    'sensors_expected': len(sensor_data),
                }

                # Write to a tmp file and rename over the real one - index.cgi (or the
                # watchdog script) must never be able to read a half-written file.
                tmpfile = statusfile + '.tmp'
                with open(tmpfile, 'w') as f:
                    json.dump(status, f)
                os.replace(tmpfile, statusfile)

        except Exception as e:
            _LOGGER.debug("Konnte Statusdatei nicht schreiben: " + str(e))

        time.sleep(1)


def main():
    global mqtt_topic, client, debug, loglevel, logfile, _LOGGER, search, unknown, boost_mode_time, ventmode_stop_supply_fan_time, ventmode_stop_exhaust_fan_time, bypass_on_time, bypass_off_time, comfoconnect, statusfile
    
    connected_flag = 0
    loglevel=logging.ERROR
    search = False
    boost_mode_time = b'\x84\x03'
    ventmode_stop_supply_fan_time = b'\x10\x0e'
    ventmode_stop_exhaust_fan_time = b'\x10\x0e'
    bypass_on_time = b'\x10\x0e'
    bypass_off_time = b'\x10\x0e'
    configfile = ""

    opts, args = getopt.getopt(sys.argv[1:],"c:f:l:s:",['configfile=', 'logfile=', 'loglevel=', 'search', 'statusfile='])
    for opt, args in opts:
        if opt in ("-c", "--configfile"):
            configfile = args
        elif opt in ("-f", "--logfile"):
            logfile = args
            logfileArg = args
        elif opt in ("-l", "--loglevel"):
            loglevel = map_loglevel(args)
        elif opt in ("-s", "--search"):
            search = True
        elif opt == "--statusfile":
            statusfile = args
    
    if loglevel == 7: # Level Debug
        debug = True
    else:
        debug = False

    _LOGGER = setup_logger("COMFOCONNECT")
    _LOGGER.debug("logfile: " + logfileArg)
    _LOGGER.info("loglevel: " + logging.getLevelName(_LOGGER.level))
    
    # Get configurations from file
    try:
        with open(configfile) as json_pcfg_file:
            pcfg = json.load(json_pcfg_file)
        _LOGGER.debug("Plugin Config: " + str(pcfg))

        mqtt_broker   	= pcfg['MAIN']['MQTTSERVER']                            # Set your MQTT broker here
        mqtt_user 		= pcfg['MAIN']['MQTTUSER']                              # Set the MQTT user login
        mqtt_passw   	= pcfg['MAIN']['MQTTPASS']                              # Set the MQTT user password
        mqtt_topic  	= pcfg['MAIN']['MQTTTOPIC']                             # Set the MQTT root topic
        mqtt_port       = int(pcfg['MAIN']['MQTTPORT'])                         # Set the MQTT Port

        device_ip		= pcfg['MAIN']['IPLANC']                                # Look in your router administration and get the ip of the comfoconnect device and set it as static lease
        pin     		= int(pcfg['MAIN']['PIN'])                              # Set PIN of vent unit !

    except Exception as e:
        _LOGGER.exception(str(e))
# ============================
    
    # Configuration #######################################################################################################
    local_name      = 'ComfoConnect Gateway'                                # Name of the service
    local_uuid      = bytes.fromhex('00000000000000000000000000000005')     # Can be what you want, used to differentiate devices (as only 1 simultaneously connected device is allowed)
    
#   Connect to Comfocontrol device  #####################################################################################
#   Detect Bridge
    if search:
        bridge = bridge_discovery(device_ip, debug, search)
        _LOGGER.info("Bridge gefunden")
        pcfg['MAIN']['IPLANC'] = bridge.host
        #Config.set('MAIN','IPLANC', bridge.host)
        _LOGGER.info("IP Adresse in Configfile gesichert")
        # save to a file
        with open(configfile, 'w') as outfile:
            json.dump(pcfg, outfile, ensure_ascii=True, indent=4)
        exit(0)
        
    # paho-mqtt >= 2.0 requires an explicit callback_api_version as first argument and
    # changed the on_connect/on_message/... callback signatures. All callbacks in this
    # file (on_connect, on_disconnect, on_message, on_publish, ...) use the legacy (v1)
    # signatures, so we explicitly request VERSION1 when it is available. This keeps the
    # plugin working unchanged on systems that still ship paho-mqtt 1.x (e.g. LoxBerry 3,
    # Debian bullseye's python3-paho-mqtt 1.5.1) as well as on systems where paho-mqtt 2.x
    # is installed (e.g. some LoxBerry 4 setups).
    if hasattr(mqtt, "CallbackAPIVersion"):
        # paho-mqtt >= 2.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "ComfoConnect", clean_session=True)
    else:
        # paho-mqtt < 2.0
        client = mqtt.Client("ComfoConnect", clean_session=True)
    client.on_subscribe         = on_subscribe
    client.on_publish           = on_publish
    client.on_connect           = on_connect
    client.on_disconnect        = on_disconnect
    client.on_log               = on_log
    client.on_message           = on_message
    
    client.username_pw_set(mqtt_user,mqtt_passw)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.will_set(mqtt_topic + "Status", payload="Offline", qos=0, retain=True)

        
    bridge = bridge_discovery(device_ip, debug, search)

    # Connect to the bridge
    try:
        _LOGGER.info("Connecting to the " + local_name + " - PIN: " + str(pin))
        comfoconnect = ComfoConnect(bridge, local_uuid, local_name, pin)

    except Exception as e:
        _LOGGER.exception(str(e))

    comfoconnect.callback_sensor = callback_sensor

    # Graceful shutdown on SIGTERM (wrapper.pl's plain `pkill -f cfc.py`, used both by
    # a "Speichern"-triggered restart and by the watchdog). Without this the process
    # just dies instantly with no warning to the bridge - observed in practice: the
    # bridge then keeps the old session "alive" for several seconds ("resumed: true"
    # on the next StartSessionConfirm), replaying a backlog of leftover messages tied
    # to the old session before it gets around to confirming the NEW process's
    # StartSessionRequest. Explicitly closing the session here lets the next startup
    # connect cleanly and immediately instead of eating into its own connect timeout.
    # Registered here (not earlier) so `comfoconnect` and `client` already exist for
    # every SIGTERM this could plausibly catch - a signal arriving in the brief window
    # before this line has nothing to clean up yet anyway (no session established).
    def handle_sigterm(signum, frame):
        _LOGGER.info("SIGTERM empfangen - fahre sauber herunter (melde Session bei der Zehnder-Box ab)...")

        try:
            if comfoconnect.is_connected():
                # Short, bounded timeout: this must not hold up "Speichern" for the
                # full 10s default if the bridge doesn't answer - takeover=True on
                # the next startup remains the safety net for that case.
                comfoconnect.cmd_close_session(reply_timeout=3)
        except Exception as e:
            _LOGGER.warning("Konnte Session bei der Zehnder-Box nicht sauber schließen: " + str(e))

        try:
            comfoconnect.disconnect()
        except Exception as e:
            _LOGGER.warning("Fehler beim Trennen von der Zehnder-Box: " + str(e))

        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass

        _LOGGER.info("Sauber heruntergefahren.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    # Start writing the health-status file (ramdisk, see --statusfile) in the
    # background. Started early (before the broker/bridge are even connected) so the
    # status file exists and reflects a "not yet connected" state right from the
    # start, instead of only appearing once everything is already up.
    if statusfile:
        try:
            os.makedirs(os.path.dirname(statusfile), exist_ok=True)
        except Exception as e:
            _LOGGER.error("Konnte Ordner für Statusdatei nicht anlegen: " + str(e))
        threading.Thread(target=write_status_loop, daemon=True).start()

    # Connect to the broker
    try:
        _LOGGER.info("Connecting to MQTT Broker " + str(mqtt_broker) + ":" + str(mqtt_port))
        client.connect(mqtt_broker, mqtt_port)
    except Exception as e:
        _LOGGER.exception(str(e))
        _LOGGER.critical("Not connected to MQTT Broker")
        exit(1)
    client.loop_start()

    # Connect to the bridge
    #
    # Retry a few times before giving up: the initial handshake (StartSessionConfirm)
    # can occasionally fail on a plain timeout - e.g. right after a "Speichern"-triggered
    # restart with takeover=True, the bridge may still be flushing CnRpdoNotificationType
    # messages tied to the previous session before it gets around to replying to our new
    # StartSessionRequestType, and that can eat into the handshake's timeout budget. That
    # used to be fatal (exit(1) on the very first failed attempt) even though it's usually
    # a transient, one-off race that a fresh attempt a couple seconds later resolves fine.
    bridge_connect_attempts = 5
    for attempt in range(1, bridge_connect_attempts + 1):
        try:
            _LOGGER.info("Connect to the bridge (Versuch %d/%d)" % (attempt, bridge_connect_attempts))
            comfoconnect.connect(True)  # Disconnect existing clients.
            break

        except Exception as e:
            if attempt >= bridge_connect_attempts:
                _LOGGER.exception(str(e))
                _LOGGER.critical("Not connected to bridge nach %d Versuchen" % bridge_connect_attempts)
                exit(1)
            _LOGGER.warning("Verbindung zur Bridge fehlgeschlagen (Versuch %d/%d), erneuter Versuch: %s" % (attempt, bridge_connect_attempts, str(e)))
            time.sleep(2)

    connected_flag=True

#    unknown types investigation
    # unknown = [33, 37, 53, 82, 85, 86, 87, 145, 146, 208, 211, 212, 216, 217, 218, 219, 224, 226, 228, 321, 325, 337, 338, 341, 369, 370, 371, 372, 384, 386, 400, 401, 402, 416, 417, 418, 419]
    # for y in unknown:
        # comfoconnect.register_sensor(y)
        # _LOGGER.debug("Unknown Sensor No.: %d" % y)
        
#   Register sensors ################################################################################################
    # Not every sensor/pdid in sensor_data is necessarily supported by every Comfo
    # unit/firmware - some (e.g. SETTING_RF_PAIRING) may simply never send a
    # CnRpdoConfirm back, which previously made register_sensor() time out after 5s
    # and crash the ENTIRE script (unhandled exception in the startup loop), so no
    # sensor at all got monitored. Registering each sensor independently means one
    # unsupported/unresponsive pdid is logged and skipped instead of taking down
    # the other 40+ working sensors.
    sensor_ids = list(sensor_data.keys())
    for i, x in enumerate(sensor_ids):
        try:
            # register_sensor() gives up silently (returns None) after exhausting its
            # retries on a plain timeout - it does NOT raise in that case, so the log
            # message here must check the return value, not just "no exception was
            # raised". Logging "Register Sensor: X" unconditionally would contradict
            # the "konnte nicht registriert werden" ERROR register_sensor() already
            # logged for the exact same sensor a moment earlier.
            reply = comfoconnect.register_sensor(x)
            if reply is not None:
                _LOGGER.info("Register Sensor: %d" % x + " Sensorname: " + sensor_data[x]['NAME'])

        except OSError as e:
            # Connection genuinely gone mid-burst (e.g. a reset right during startup).
            # Hammering through the remaining ~40 sensors with the same doomed call
            # just produces one error per sensor for the exact same underlying
            # problem - stop immediately instead. But still remember the sensors we
            # hadn't gotten to yet (comfoconnect.sensors, keyed like register_sensor()
            # itself would) so the background connection thread's automatic reconnect
            # re-registers them once the bridge is reachable again, instead of them
            # silently never being subscribed at all for the rest of this run.
            _LOGGER.error(
                "Verbindung beim Registrieren verloren - breche Erstregistrierung ab (%d von %d Sensoren "
                "noch offen), automatischer Reconnect übernimmt den Rest: %s" % (len(sensor_ids) - i, len(sensor_ids), str(e))
            )
            for remaining in sensor_ids[i:]:
                comfoconnect.sensors.setdefault(remaining, RPDO_TYPE_MAP.get(remaining))
            break

        except Exception as e:
            _LOGGER.error("Sensor %d (%s) konnte nicht registriert werden - Gerät hat nicht geantwortet: %s" % (x, sensor_data[x]['NAME'], str(e)))

    # Diagnostic-only calls - wrapped so a connection hiccup right at this moment
    # (e.g. still mid-reconnect after the loop above gave up early) can't crash the
    # main thread with an uncaught exception. Not fatal to the plugin either way
    # (the background connection/message threads keep running regardless), but an
    # uncaught traceback here is needless noise and skips the remaining diagnostics.
    try:
        # VersionRequest
        version = comfoconnect.cmd_version_request()
        _LOGGER.info("Version :" + str(version))

        # ListRegisteredApps
        for app in comfoconnect.cmd_list_registered_apps():
            _LOGGER.info("Registered Apps (UUID): " + str(app['uuid'].hex()) + ", APP Name: " + str(app['devicename']))

        # TimeRequest
        timeinfo = comfoconnect.cmd_time_request()
        _LOGGER.info("Timeinfo: " + str(timeinfo))

    except Exception as e:
        _LOGGER.error("Diagnose-Abfragen (Version/RegisteredApps/Time) fehlgeschlagen, vermutlich Verbindung gerade unterbrochen: %s" % str(e))
    

def map_loglevel(loxlevel):
##
# Mapping Loglevel from loxberry log to python logging
##
    switcher={
        0:logging.NOTSET,
        3:logging.ERROR,
        4:logging.WARNING,
        6:logging.INFO,
        7:logging.DEBUG
    }
    return switcher.get(int(loxlevel),"unsupported loglevel")

def setup_logger(name):
    global logfile
    
    logging.captureWarnings(1)
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)

    logger.addHandler(handler)
    logger.setLevel(loglevel)

    if not logfile:
        logfile="/tmp/"+datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]+"_comfoconnect.log"
    logging.basicConfig(filename=logfile,level=loglevel,format='%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s',datefmt='%H:%M:%S')

    return logger

if __name__ == "__main__":
    main()
