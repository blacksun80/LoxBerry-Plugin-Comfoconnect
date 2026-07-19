#!/usr/bin/python3
import paho.mqtt.client as mqtt
import datetime
import os
import time
import threading
import signal
from pycomfoconnect import *
import getopt
import sys
import json
from mqtt_data import sensor_data
import logging

interval = [0 for x in range(300)]

# Set once in main() as the registration phase progresses, read by
# write_status_loop() (-> status.json -> index.cgi's getStatus()). One of:
# "in_progress" (still registering), "timeout" (a sensor didn't answer within the
# standard reply timeout - fatal, process exits), "done" (all sensors registered,
# or the sweep was interrupted by a connection loss that the background reconnect
# is already recovering from).
#
# There is deliberately no overall deadline across the whole sweep anymore: each
# individual request already has the standard 5s reply timeout, and a sensor
# failing that aborts the phase immediately - so the sweep can't silently drag on
# regardless. On real hardware all 50 sensors register in well under a second.
registration_state = "in_progress"

# Sensor-data monitoring, read from the plugin config in main(). Mirrored into the
# status file so index.cgi's getStatus() (polled every second via AJAX) can evaluate
# it without having to open and parse the config file on every single request, and
# evaluated in write_status_loop() to publish SENSORWATCH_TOPIC (below).
sensorwatch_enabled = False
sensorwatch_timeout_sec = 60

# MQTT topic reporting whether the ventilation unit has stopped sending sensor data:
# "1" = timeout detected, "0" = data is flowing (or monitoring is switched off).
#
# Without this the timeout was only ever visible in the plugin's own web page, or
# indirectly through the plugin restarting itself - so with monitoring enabled but
# automatic restart switched off, nothing outside the browser noticed at all. As a
# retained topic it can be wired straight into Loxone like any other sensor value.
#
# Published only on change (plus once per MQTT (re)connect, see on_connect) rather
# than every second, so it doesn't add a message per second to the broker forever.
SENSORWATCH_TOPIC = "SENSOR_TIMEOUT"

# Last value published to SENSORWATCH_TOPIC. None means "nothing published yet on
# this MQTT connection" and forces the next evaluation to publish, whatever it finds.
sensorwatch_published = None

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
    global mqtt_connected, mqtt_last_change, sensorwatch_published, away_active_published, away_remaining_published

    if rc==0:
        _LOGGER.info("Connection returned result: "+mqtt.connack_string(rc))
    else:
        _LOGGER.error("Connection returned result: "+mqtt.connack_string(rc))

    mqtt_connected = (rc == 0)
    mqtt_last_change = time.time()

    # Vergessen, was zuletzt gesendet wurde, damit write_status_loop() den
    # Sensor-Timeout-Zustand auf dieser (neuen) Verbindung einmal frisch sendet.
    # Retained-Nachrichten leben zwar im Broker weiter, aber nach einem
    # Broker-Neustart waeren sie weg - und da wir nur bei Aenderung senden, wuerde
    # das Topic sonst bis zur naechsten echten Zustandsaenderung leer bleiben.
    sensorwatch_published = None
    away_active_published = None
    away_remaining_published = None

    client.publish(mqtt_topic + "Status", payload="Online", qos=0, retain=True)

    client.subscribe(mqtt_topic + "FAN_MODE", qos=0)
    client.subscribe(mqtt_topic + "FAN_MODE_AWAY", qos=0)
    client.subscribe(mqtt_topic + "AWAY_FOR", qos=0)
    client.subscribe(mqtt_topic + "AWAY_END", qos=0)
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
    # NOTE: rc here is NOT a CONNACK code - mqtt.connack_string(rc) used to be called
    # on it, which produces a technically-valid-looking but WRONG message (e.g. rc=1
    # prints "unacceptable protocol version" - a CONNACK-only meaning - even though
    # every single one of these disconnects was directly preceded by a genuinely
    # successful CONNACK 0/Accepted just milliseconds earlier). paho's own docs say
    # this rc is an internal MQTTErrorCode it converts to for MQTT v3.x, not
    # something the broker sent - error_string() is the correct lookup here.
    if rc==0:
        _LOGGER.info("MQTT-Verbindung sauber getrennt.")
    else:
        _LOGGER.error("MQTT-Verbindung unerwartet getrennt (Code %s: %s) - verbindet automatisch neu." % (str(rc), mqtt.error_string(rc)))

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
    elif topic == mqtt_topic + "AWAY_FOR":
        # Abwesenheit fuer eine Dauer ab jetzt, in Sekunden. Bewusst EIN Topic statt
        # des Zwei-Schritt-Musters von BOOST_MODE_TIME/BOOST_MODE: dort muessen zwei
        # Nachrichten in der richtigen Reihenfolge kommen und der Zwischenwert lebt
        # unsichtbar in einer Variablen weiter. Hier steht alles in einer Nachricht,
        # damit gibt es keine Reihenfolge, die man falsch machen kann.
        sek = to_seconds(value)
        if sek <= 0:
            _LOGGER.error("AWAY_FOR: Sekunden muessen groesser als 0 sein - empfangen: '%s'" % value)
        else:
            cmd = send_away(sek)
            _LOGGER.info("Befehl AWAY_FOR (%d Sekunden) an Lueftungsanlage gesendet: %s" % (sek, cmd.hex()))
    elif topic == mqtt_topic + "AWAY_END":
        # Beendet die Abwesenheit vorzeitig. 0x85 loescht den Timer-Eintrag, die
        # Anlage faellt damit auf den normalen Zeitplan zurueck - dasselbe, was die
        # App beim Abschalten des Haus-Symbols macht.
        if int(value) == 1:
            cmd = b'\x85\x15' + AWAY_SUBUNIT
            comfoconnect.cmd_rmi_request(cmd)
            _LOGGER.info("Befehl AWAY_END an Lüftungsanlage gesendet: %s" % cmd.hex())
        else:
            _LOGGER.error("AWAY_END: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
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

def bridge_discovery(ip, search):
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
    """Wandelt eine Sekundenangabe in das 2-Byte-Zeitfeld (little-endian).

    Ueber to_seconds() statt direkt int(): Loxone schickt Zahlen regelmaessig in
    Fliesskommaschreibweise ("600.0"), und int("600.0") wirft ValueError. Das
    landete dann als Fehlermeldung im Log, und die betroffene Zeit (Boost,
    Bypass, Ventilationsmodus) blieb still auf ihrem alten Wert stehen.
    """
    val = to_seconds(val)
    big_hex = val.to_bytes(2, byteorder='little').hex()
    big_hex = bytearray.fromhex(big_hex)
    return big_hex

# Abwesenheit ("Abwesend bis ...") - Unit 0x15 SCHEDULE, SubUnit 01, Eintrag 0x0B.
#
# NICHT zu verwechseln mit 8415 0101, das ist die Luefterstufe: dort ist das
# letzte Byte die Stufe (00 = Away, 01-03 = 1-3), und das Zeitfeld wird von der
# Anlage ignoriert - gemessen: 697 Sekunden gesendet, Countdown lief trotzdem
# unveraendert auf den naechsten Zeitplanpunkt. Genau deshalb sprang beim Testen
# auch eine eingestellte Stufe 2 auf Away zurueck.
#
# Der Eintrag 0x0B ist die eigentliche Abwesenheitsschaltung (in der Zehnder-App
# das Haus-Symbol), die den Zeitplan ueber Tage hinweg ueberschreiben kann.
# Quelle: aiocomfoconnect (michaelarnauts), set_away()/get_away().
AWAY_SUBUNIT = b'\x01\x0b'

# Abfrageintervall fuer den Abwesenheits-Zustand, in Sekunden.
#
# Anders als die Sensoren laesst sich das nicht abonnieren: Sensorwerte (RPDO)
# schickt die Anlage von selbst, sobald sie sich aendern - der Abwesenheits-Timer
# ist dagegen ein RMI-Wert, den man jedes Mal aktiv abholen muss. Deshalb ein
# Kompromiss: 15s ist fuer eine Anzeige, die sich stundenweise aendert, mehr als
# genug und faellt neben dem laufenden Sensorverkehr nicht ins Gewicht.
AWAY_POLL_INTERVAL = 15

# Zuletzt veroeffentlichte Werte, damit nur bei Aenderung gesendet wird.
# None = auf dieser MQTT-Verbindung noch nichts gesendet (siehe on_connect).
away_active_published = None
away_remaining_published = None

def seconds_to_timerfield(seconds):
    """Baut das 4-Byte-Zeitfeld der 0x84-Befehle (Sekunden, little-endian).

    Nachgerechnet an den dokumentierten Beispielen: Boost "10 Minuten" ist
    58020000 = 600, Bypass "1 Stunde" ist 100e0000 = 3600.

    Bewusst 4 echte Bytes statt to_big() + zwei Nullbytes: to_big() kann nur
    65535 Sekunden abbilden (gut 18 Stunden). Gemessen wurde eine Abwesenheit
    von 346091 Sekunden - damit waere daraus still 18411 (gut 5 Stunden)
    geworden, die Anlage haette also eine voellig andere Zeit bekommen.
    """
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    if seconds > 0xFFFFFFFE:
        seconds = 0xFFFFFFFE
    return seconds.to_bytes(4, byteorder='little')

def poll_away_loop():
    """Holt den Abwesenheits-Zustand zyklisch ab und veroeffentlicht ihn per MQTT.

    Laeuft in einem EIGENEN Thread, nicht in write_status_loop(): Ein RMI-Aufruf
    kann im schlechtesten Fall bis zum Antwort-Timeout haengen, und das wuerde dort
    das sekuendliche Schreiben der Statusdatei blockieren - die Weboberflaeche
    zeigte dann faelschlich veraltete Daten an.

    Antwortformat von 0x83 (14 Byte), abgeleitet aus aiocomfoconnect:

        01 00000000 55020000 53020000 00
        ^^          ^^^^^^^^ ^^^^^^^^
        |           gesamt   Rest (jeweils Sekunden, little-endian)
        aktiv (00 = nein, 01 = ja)

    Wie bei allen Diagnosefunktionen hier gilt: Fehler werden geschluckt, das
    darf das eigentliche Plugin niemals mit herunterreissen.
    """
    global away_active_published, away_remaining_published

    while True:
        time.sleep(AWAY_POLL_INTERVAL)

        try:
            if not comfoconnect or not comfoconnect.is_connected() or not mqtt_connected:
                continue

            reply = comfoconnect.cmd_rmi_request(b'\x83\x15' + AWAY_SUBUNIT)
            msg = getattr(getattr(reply, 'msg', None), 'message', None)
            if not msg or len(msg) < 13:
                # Kein Timeout-Drama: beim naechsten Durchlauf nochmal versuchen.
                continue

            aktiv = 1 if msg[0] == 1 else 0
            rest = int.from_bytes(msg[9:13], byteorder='little') if aktiv else 0

            if aktiv != away_active_published:
                client.publish(mqtt_topic + "AWAY_ACTIVE", aktiv, qos=0, retain=True)
                away_active_published = aktiv
                _LOGGER.info("Abwesenheit %s - %sAWAY_ACTIVE = %d gesendet."
                             % ("aktiv" if aktiv else "beendet", mqtt_topic, aktiv))

            # Restzeit nur senden, wenn sie sich sichtbar geaendert hat - sonst
            # ginge bei jedem Durchlauf eine Nachricht raus, obwohl der Wert im
            # Ruhezustand konstant 0 ist.
            if rest != away_remaining_published:
                client.publish(mqtt_topic + "AWAY_REMAINING", rest, qos=0, retain=True)
                away_remaining_published = rest

        except Exception as e:
            _LOGGER.debug("Konnte Abwesenheits-Zustand nicht abfragen: " + str(e))

def send_away(seconds):
    """Schaltet die Abwesenheit fuer die angegebene Dauer ein."""
    cmd = b'\x84\x15' + AWAY_SUBUNIT + b'\x00\x00\x00\x00' + seconds_to_timerfield(seconds) + b'\x00'
    comfoconnect.cmd_rmi_request(cmd)
    return cmd

def to_seconds(value):
    """Wandelt eine MQTT-Nutzlast in ganze Sekunden.

    Ueber float() statt direkt int(): Loxone schickt Zahlen regelmaessig in
    Fliesskommaschreibweise ("240.0"), und int("240.0") wirft ValueError - das
    landete frueher als Fehlermeldung im Log statt als gesetzter Wert.
    """
    return int(float(value))

def on_log(client, userdata, level, buf):
    _LOGGER.debug("Paho: " + buf)

def callback_sensor(var, value):
    # No gating on registration progress here: every value that arrives is published
    # straight away, including during the initial registration sweep and during the
    # re-registration after a reconnect. A sensor only ever sends data once the bridge
    # has confirmed ITS OWN subscription, so an early value is a real, current reading -
    # withholding it just delays fresh data reaching Loxone for no benefit. On real
    # hardware the whole 50-sensor sweep completes in well under a second anyway.
    # comfoconnect.sensors_ready still exists, but purely to drive the status display
    # (see write_status_loop()/index.cgi), not to block anything.
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
                    'registration_state': registration_state,
                    # Mirrored config, see the module-level comment - index.cgi reads
                    # these instead of opening the config file on every status poll.
                    'sensorwatch_enabled': sensorwatch_enabled,
                    'sensorwatch_timeout_sec': sensorwatch_timeout_sec,
                    # True only once (re-)registration has actually finished on the
                    # CURRENT connection - False again for the whole gap during a later
                    # reconnect, even though registration_state itself stays "done"
                    # (that one only ever reflects the one-time startup phase). See the
                    # attribute comment in comfoconnect.py's __init__.
                    'sensors_ready': comfoconnect.sensors_ready if comfoconnect else False,
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
                # restart check) must never be able to read a half-written file.
                tmpfile = statusfile + '.tmp'
                with open(tmpfile, 'w') as f:
                    json.dump(status, f)
                os.replace(tmpfile, statusfile)

        except Exception as e:
            _LOGGER.debug("Konnte Statusdatei nicht schreiben: " + str(e))

        try:
            publish_sensorwatch_state()
        except Exception as e:
            # Wie beim Schreiben der Statusdatei: eine Diagnosefunktion darf das
            # eigentliche Plugin niemals mit in den Abgrund reissen.
            _LOGGER.debug("Konnte Sensor-Timeout-Status nicht veröffentlichen: " + str(e))

        time.sleep(1)


def publish_sensorwatch_state():
    """Publishes SENSORWATCH_TOPIC whenever the sensor-data timeout state changes.

    Bewusst dieselbe Auswertung wie getStatus() in index.cgi: Timeout nur melden,
    wenn die Überwachung eingeschaltet ist UND bereits Sensoren registriert waren
    (sonst würde direkt nach dem Start ein Timeout gemeldet, bevor überhaupt Daten
    kommen konnten). Sind beide Bedingungen erfüllt, aber es kam noch nie ein Wert,
    gilt das ebenfalls als Timeout - genau wie im Webfrontend.

    Ist die Überwachung ausgeschaltet, wird konsequent "0" veröffentlicht statt gar
    nichts: das Topic ist retained, ein hängengebliebenes "1" von früher würde sonst
    für immer eine Störung vortäuschen, die niemand mehr auswertet.
    """
    global sensorwatch_published

    if not comfoconnect or not mqtt_connected:
        return

    timeout_active = 0
    if sensorwatch_enabled and len(comfoconnect.sensors_confirmed) > 0:
        last = comfoconnect.last_sensor_data
        if last is None or (time.time() - last) > sensorwatch_timeout_sec:
            timeout_active = 1

    if timeout_active == sensorwatch_published:
        return

    (rc, mid) = client.publish(mqtt_topic + SENSORWATCH_TOPIC, timeout_active, qos=0, retain=True)
    if rc == 0:
        sensorwatch_published = timeout_active
        if timeout_active:
            _LOGGER.warning(
                "Seit über %ds keine Sensordaten mehr empfangen - %s%s = 1 gesendet."
                % (sensorwatch_timeout_sec, mqtt_topic, SENSORWATCH_TOPIC)
            )
        else:
            _LOGGER.info("Sensordaten fließen (wieder) - %s%s = 0 gesendet." % (mqtt_topic, SENSORWATCH_TOPIC))
    else:
        # Nicht als gesendet vermerken, damit es beim naechsten Durchlauf (1s spaeter)
        # erneut versucht wird, statt den Zustand stillschweigend zu verlieren.
        _LOGGER.error("Konnte %s%s nicht senden, RC=%s" % (mqtt_topic, SENSORWATCH_TOPIC, str(rc)))


def main():
    global mqtt_topic, client, debug, loglevel, logfile, _LOGGER, search, boost_mode_time, ventmode_stop_supply_fan_time, ventmode_stop_exhaust_fan_time, bypass_on_time, bypass_off_time, comfoconnect, statusfile, registration_state, sensorwatch_enabled, sensorwatch_timeout_sec

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
    # logfile statt einer zweiten, identischen Kopie der Option: die gab es hier
    # frueher als eigene Variable, die aber nur gesetzt wurde, WENN --logfile
    # uebergeben wurde - ohne die Option waere diese Zeile mit einem NameError
    # abgestuerzt, noch bevor irgendetwas geloggt werden konnte.
    _LOGGER.debug("logfile: " + str(logfile))
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

        # Sensor-data monitoring - only mirrored into the status file for the web
        # frontend, cfc.py doesn't act on it itself (see the module-level comment).
        # .get() with defaults: a config written by an older plugin version won't have
        # these keys yet, and a missing monitoring setting must not stop the plugin.
        sensorwatch_enabled = str(pcfg['MAIN'].get('SENSORWATCH_ENABLED', '0')) == '1'
        try:
            sensorwatch_timeout_sec = int(pcfg['MAIN'].get('SENSORWATCH_TIMEOUT_SEC', 60))
        except (TypeError, ValueError):
            sensorwatch_timeout_sec = 60

    except Exception as e:
        _LOGGER.exception(str(e))
# ============================
    
    # Configuration #######################################################################################################
    local_name      = 'ComfoConnect Gateway'                                # Name of the service
    local_uuid      = bytes.fromhex('00000000000000000000000000000005')     # Can be what you want, used to differentiate devices (as only 1 simultaneously connected device is allowed)
    
#   Connect to Comfocontrol device  #####################################################################################
#   Detect Bridge
    if search:
        bridge = bridge_discovery(device_ip, search)
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
    # Unique per process (PID suffix), not a fixed "ComfoConnect" - during a
    # "Speichern"-triggered restart, the old and new cfc.py processes can briefly
    # overlap (see wait_for_cfc_exit() in wrapper.pl). Two MQTT clients connecting
    # with the SAME client_id make the broker evict whichever one is already
    # connected every time the other (re)connects - observed in practice as a
    # rapid connect/disconnect loop for several seconds after every restart (each
    # disconnect misleadingly logged, before the on_disconnect fix above, as
    # "unacceptable protocol version"). A unique ID per process avoids the
    # collision entirely, regardless of how long any overlap lasts.
    mqtt_client_id = "ComfoConnect-%d" % os.getpid()
    if hasattr(mqtt, "CallbackAPIVersion"):
        # paho-mqtt >= 2.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, mqtt_client_id, clean_session=True)
    else:
        # paho-mqtt < 2.0
        client = mqtt.Client(mqtt_client_id, clean_session=True)
    client.on_subscribe         = on_subscribe
    client.on_publish           = on_publish
    client.on_connect           = on_connect
    client.on_disconnect        = on_disconnect
    client.on_log               = on_log
    client.on_message           = on_message
    
    client.username_pw_set(mqtt_user,mqtt_passw)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.will_set(mqtt_topic + "Status", payload="Offline", qos=0, retain=True)

        
    bridge = bridge_discovery(device_ip, search)

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

        # Tell the background threads this disconnect is intentional BEFORE sending
        # CloseSessionRequest below - otherwise, once the bridge closes the socket in
        # response (typically within milliseconds), the message thread has no way to
        # tell that apart from a real, unexpected connection loss: it would log a
        # misleading "connection was broken, we will try to reconnect" warning and
        # start a reconnect attempt that os._exit() below cuts off anyway.
        # mark_disconnecting() only sets flags, it doesn't block (unlike
        # comfoconnect.disconnect()), so it's safe to call from this handler.
        comfoconnect.mark_disconnecting()

        try:
            if comfoconnect.is_connected():
                # Plain 5s default like every other command - no special short timeout
                # here. In practice this never waits at all: the bridge answers a
                # CloseSessionRequest by simply closing the TCP socket rather than
                # sending a CloseSessionConfirm, and the message thread turns that into
                # an immediate wake-up (see _CONNECTION_LOST in comfoconnect.py) instead
                # of letting the caller sit out its timeout. Measured end-to-end in the
                # log: request sent and process fully shut down within ~5ms. The timeout
                # only matters if the bridge neither answers nor drops the connection -
                # and takeover=True on the next startup covers that case anyway.
                comfoconnect.cmd_close_session()
                _LOGGER.info("Session bei der Zehnder-Box abgemeldet.")
        except OSError as e:
            # The bridge tends to just close the TCP connection right after
            # processing this request instead of sending an explicit
            # CloseSessionConfirm back first - the connection dying WHILE we're
            # waiting is a pretty strong sign the request was received and acted
            # on (the request itself did get sent - if it hadn't, is_connected()
            # above would already be False). Nothing more to verify here, and it's
            # not an actual problem, so INFO rather than WARNING.
            _LOGGER.info("CloseSessionRequest gesendet, Bridge hat die Verbindung direkt danach getrennt (normal): " + str(e))
        except ValueError as e:
            # Different from the OSError case above: this is a PLAIN timeout - the
            # connection itself did NOT drop, the bridge just never answered within
            # the standard reply timeout. Unlike the OSError case, we genuinely don't know
            # whether the session actually got closed - could still be sitting open
            # on the bridge's side. takeover=True on the next startup is the safety
            # net either way, so there's nothing more to do here, but the log
            # shouldn't claim "normal"/success for something it can't verify.
            _LOGGER.warning("CloseSessionRequest gesendet, aber keine Bestätigung erhalten (Timeout) - Session evtl. noch offen, takeover beim nächsten Start übernimmt das: " + str(e))
        except Exception as e:
            _LOGGER.warning("Konnte Session bei der Zehnder-Box nicht sauber schließen: " + str(e))

        try:
            # disconnect() before loop_stop(): sends the clean DISCONNECT packet
            # while the network thread is still running to actually flush it, then
            # stop the thread. Doing it in the other order risks the DISCONNECT
            # never truly leaving the socket, in which case the broker only notices
            # via the TCP connection dropping - functionally similar, but less clean.
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass

        _LOGGER.info("Sauber heruntergefahren.")

        # NOT sys.exit(0): by the time SIGTERM can arrive here, main() has usually
        # already returned and the interpreter is already inside its own shutdown
        # sequence (threading._shutdown(), waiting for the non-daemon connection
        # thread to finish - that's what has kept the process alive this whole
        # time). Raising SystemExit via sys.exit() from a signal handler firing in
        # the middle of that produces a harmless but ugly "Exception ignored in...
        # SystemExit: 0" traceback in the log. os._exit() terminates the process
        # immediately at the OS level, skipping Python's normal
        # exception-based/atexit shutdown machinery entirely - safe here since
        # everything worth cleaning up (the bridge session, the MQTT connection)
        # was already handled explicitly above; there's nothing left for Python's
        # own shutdown to do that we need.
        os._exit(0)

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

    # Abwesenheits-Zustand zyklisch abholen (eigener Thread, siehe poll_away_loop).
    threading.Thread(target=poll_away_loop, daemon=True).start()

    # Connect to the broker. Deliberately done BEFORE the bridge/sensor registration
    # below, not after: the MQTT connection itself has nothing to do with whether the
    # ventilation data is ready yet, and connecting first means the plugin shows up as
    # "Online" on the broker (and can already receive commands) immediately, plus every
    # sensor value can be published the moment it arrives - including values arriving
    # while the registration sweep is still running (see callback_sensor()). MQTT then
    # stays up across every later bridge reconnect too; only the bridge side goes away
    # and comes back.
    try:
        _LOGGER.info("Connecting to MQTT Broker " + str(mqtt_broker) + ":" + str(mqtt_port))
        client.connect(mqtt_broker, mqtt_port)
    except Exception as e:
        _LOGGER.exception(str(e))
        _LOGGER.critical("Not connected to MQTT Broker")
        os._exit(1)
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
                # os._exit(), not exit(): comfoconnect.connect() may have already started
                # the (non-daemon) connection thread on an earlier attempt even though
                # this last one failed (see connect()'s "didn't reply on time" case) - a
                # plain exit(1) would then just hang forever waiting for that thread to
                # finish instead of actually terminating the process.
                os._exit(1)
            _LOGGER.warning("Verbindung zur Bridge fehlgeschlagen (Versuch %d/%d), erneuter Versuch: %s" % (attempt, bridge_connect_attempts, str(e)))
            time.sleep(2)

#   Register sensors ################################################################################################
    # Single attempt per sensor (see register_sensor()), no retry, and no overall
    # deadline across the sweep - each individual request already has the standard 5s
    # reply timeout, and any single sensor failing to register (that timeout, or the
    # connection dropping outright) ends the phase right there. sensor_data is expected
    # to already reflect the sensors this specific hardware supports, so a failure here
    # is treated as a real problem, not shrugged off and skipped.
    #
    # MQTT is already connected at this point (see above) and publishing is NOT gated on
    # this sweep - values for sensors that are already subscribed go out to Loxone right
    # away while the rest are still being registered (see callback_sensor()).
    # comfoconnect.sensors_ready, set True below once this sweep succeeds, only feeds the
    # status display.
    sensor_ids = list(sensor_data.keys())
    registration_ok = True
    connection_lost = False

    _LOGGER.info("Registriere %d Sensoren..." % len(sensor_ids))

    for i, x in enumerate(sensor_ids):
        try:
            # register_sensor() gives up silently (returns None) on a plain timeout - it
            # does NOT raise in that case, so this has to check the return value, not
            # just "no exception was raised". register_sensor() already logged WHY
            # ("konnte nicht registriert werden") - here we just decide the phase is
            # over: no skipping, no continuing with the rest. This is a plain
            # non-response with the connection still up - genuinely different from the
            # OSError case below, so it still aborts the whole run (nothing will make
            # this particular sensor answer just by reconnecting).
            reply = comfoconnect.register_sensor(x)
            if reply is None:
                _LOGGER.critical(
                    "Sensor %d (%s) konnte nicht registriert werden - breche Sensor-Registrierung ab "
                    "(%d von %d Sensoren noch offen)." % (x, sensor_data[x]['NAME'], len(sensor_ids) - i, len(sensor_ids))
                )
                registration_ok = False
                break
            _LOGGER.info("Register Sensor: %d" % x + " Sensorname: " + sensor_data[x]['NAME'])

        except OSError as e:
            # Connection genuinely gone mid-burst - no point continuing THIS sweep, but
            # unlike the cases above, this is exactly the situation
            # _connection_thread_loop() already exists to handle: it independently
            # notices the same connection loss (via the message thread) and keeps
            # retrying reconnect + re-registration in the background, indefinitely,
            # without any help from here. Restarting the whole process would just
            # reinvent that same recovery a layer higher up, for no benefit - so hand
            # off instead of exiting. The one thing it needs from us: the sensors we
            # hadn't gotten to yet aren't in comfoconnect.sensors (register_sensor()
            # only adds a sensor there on SUCCESS), and _connection_thread_loop() only
            # ever re-registers what's in there - so pre-remember them here, keyed
            # exactly like register_sensor() itself would, or they'd silently never get
            # attempted at all once the reconnect succeeds.
            _LOGGER.warning(
                "Verbindung beim Registrieren verloren (%d von %d Sensoren noch offen): %s - der "
                "automatische Reconnect übernimmt jetzt, kein Neustart des Prozesses nötig." %
                (len(sensor_ids) - i, len(sensor_ids), str(e))
            )
            for remaining in sensor_ids[i:]:
                comfoconnect.sensors.setdefault(remaining, RPDO_TYPE_MAP.get(remaining))
            connection_lost = True
            break

    if connection_lost:
        # Not "timeout": the background reconnect is actively working on this, it's
        # not a dead end waiting for a restart. sensors_ready is left False (it
        # already is - see register_sensor()/comfoconnect.py's __init__) until
        # _connection_thread_loop()'s own reconnect+re-registration sweep succeeds and
        # sets it True itself - the status page keeps showing live "Registriere
        # Sensoren (X von Y)" throughout via that flag, same as during this sweep.
        registration_state = "done"
        _LOGGER.info(
            "Erstregistrierung durch Verbindungsverlust unterbrochen - Fertigstellung läuft im "
            "Hintergrund weiter, sobald die Bridge wieder erreichbar ist."
        )
    elif not registration_ok:
        registration_state = "timeout"
        _LOGGER.critical("Sensor-Registrierung fehlgeschlagen - beende Prozess, Watchdog/Wrapper startet neu.")
        # os._exit(), not exit(): the (non-daemon) connection/message threads are
        # definitely running by this point - see the os._exit() comment above.
        os._exit(1)
    else:
        registration_state = "done"

    if not connection_lost:
        # This first sweep runs here, in cfc.py's main thread, not in comfoconnect.py's
        # _connection_thread_loop() (which only handles LATER reconnects) - so it has
        # to set sensors_ready itself. From here on, every subsequent disconnect/
        # reconnect clears and re-sets this flag automatically (see
        # _connection_thread_loop()). If connection_lost is True, sensors_ready stays
        # False and THAT loop sets it once its own reconnect sweep succeeds instead.
        comfoconnect.sensors_ready = True
        _LOGGER.info("Sensor-Registrierung abgeschlossen: %d von %d Sensoren registriert." % (len(comfoconnect.sensors_confirmed), len(sensor_ids)))

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
