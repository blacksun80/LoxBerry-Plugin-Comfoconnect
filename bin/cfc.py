#!/usr/bin/python3
import paho.mqtt.client as mqtt
import datetime
import collections
import os
import time
import threading
import traceback
import signal
from pycomfoconnect import *
import getopt
import sys
import json
from mqtt_data import sensor_data
import logging

# Naechster erlaubter Sendezeitpunkt je Sensor (pdid -> Zeitstempel), fuer die
# 'PUSH'-Mindestpause aus mqtt_data.py.
#
# Bewusst ein Dictionary und KEINE Liste fester Groesse: Frueher stand hier
# "[0 for x in range(300)]", also 300 Plaetze, indiziert nach pdid. Das ging so
# lange gut, wie alle pdids unter 300 lagen - beim Eintragen der ComfoCool-Werte
# (pdid 784 und 802) warf interval[802] dann einen IndexError, der den
# Message-Thread beendete und das Plugin in eine Reconnect-Schleife schickte.
# Mit einem Dictionary gibt es diese stille Obergrenze nicht mehr.
interval = {}

# Anzahl der Sensoren, die auf DIESER Anlage ueberhaupt registriert werden sollen.
# Nicht einfach len(sensor_data): Sensoren fuer nicht angeschlossenes Zubehoer (siehe
# 'ONLY_WITH_PRODUCT' in mqtt_data.py) werden gar nicht erst versucht und duerfen in
# der Statusanzeige auch nicht als fehlend gelten - sonst staende dort dauerhaft
# "50 von 52" in Gelb, obwohl alles in Ordnung ist. Wird in main() gesetzt.
sensors_expected = len(sensor_data)

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

# Betriebsstatistik der MQTT-Seite (die Gegenstuecke zur Anlagenseite stehen in
# comfoconnect.py unter self.stats). Startzeit als Bezugsgroesse: "3 Abbrueche"
# heisst etwas voellig anderes nach einer Stunde als nach drei Wochen.
plugin_start = time.time()
mqtt_abbrueche = 0
mqtt_letzter_abbruch = None

# Wird in setup_logger() gesetzt, sobald ein Verzeichnis für Störungsberichte
# übergeben wurde. Hier schon definiert, damit der Status-Thread ihn auch dann
# lesen kann, wenn es (noch) keinen gibt.
stoerungsschreiber = None

# Führt dieselben Zähler zusätzlich über Neustarts hinweg fort (siehe Klasse
# Langzeitstatistik). Wird in main() angelegt, sobald das Datenverzeichnis bekannt
# ist; bleibt None, wenn keines übergeben wurde.
langzeit = None

# Sensorauswahl des Benutzers, in main() aus der Konfiguration gefuellt (siehe
# sensorauswahl_anwenden). Hier schon definiert, damit der Status-Thread sie auch
# dann lesen kann, wenn die Konfiguration noch nicht eingelesen ist.
sensoren_aus = set()

# Zuletzt an MQTT gesendeter Wert je pdid, fuer die Sensortabelle in der
# Weboberflaeche. Bewusst nur der Wert und sein Zeitpunkt, kein Verlauf: Das hier
# ist eine Anzeige, keine Datenhaltung - dafuer gibt es MQTT und Loxone.
letzte_werte = {}

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
    client.subscribe(mqtt_topic + "ERROR_RESET", qos=0)
    client.subscribe(mqtt_topic + "COMFOCOOL", qos=0)
    client.subscribe(mqtt_topic + "COMFOCOOL_AUTO", qos=0)
    client.subscribe(mqtt_topic + "COMFOCOOL_OFF", qos=0)
    client.subscribe(mqtt_topic + "COMFOCOOL_OFF_TIME", qos=0)
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
    global mqtt_connected, mqtt_last_change, mqtt_abbrueche, mqtt_letzter_abbruch

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
        mqtt_abbrueche += 1
        mqtt_letzter_abbruch = time.time()
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
        _LOGGER.error("Fehler bei Verarbeitung von MQTT %s = '%s': %s" % (topic, value, fehlertext(e)))

def _dispatch_message(topic, value):
    global boost_mode_time, ventmode_stop_supply_fan_time, ventmode_stop_exhaust_fan_time, bypass_on_time, bypass_off_time, comfocool_off_time

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
    elif topic == mqtt_topic + "COMFOCOOL":
        # Kuehlmodul: 0 = Automatik, 1 = aus.
        #
        # Unit 0x15 SCHEDULE, SubUnit 05 - dasselbe Muster wie Bypass und
        # Abwesenheit. 0x85 loescht den Zeiteintrag (zurueck auf Automatik), 0x84
        # setzt ihn. Die Dauer ffffffff (= -1) bedeutet dauerhaft, sonst schaltet
        # die Anlage nach Ablauf von selbst wieder auf Automatik.
        # Quelle: aiocomfoconnect, set_comfocool_mode().
        #
        # Anlagen ohne ComfoCool lehnen den Befehl ab; das wird als Fehler
        # protokolliert und bleibt folgenlos.
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(b'\x85\x15\x05\x01')
            _LOGGER.info("Befehl COMFOCOOL_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x05\x01\x00\x00\x00\x00\xff\xff\xff\xff\x00')
            _LOGGER.info("Befehl COMFOCOOL_OFF (dauerhaft) an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("COMFOCOOL: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1")
    elif topic == mqtt_topic + "COMFOCOOL_OFF_TIME":
        # Wie bei Bypass/Boost: nur merken, geschaltet wird mit COMFOCOOL_OFF.
        comfocool_off_time = to_seconds(value)
        _LOGGER.info("COMFOCOOL_OFF_TIME " + str(comfocool_off_time) + " sec übernommen")
    elif topic == mqtt_topic + "COMFOCOOL_OFF":
        if int(value) == 1:
            dauer = seconds_to_timerfield(comfocool_off_time) if comfocool_off_time > 0 else b'\xff\xff\xff\xff'
            cmd = b'\x84\x15\x05\x01\x00\x00\x00\x00' + dauer + b'\x00'
            comfoconnect.cmd_rmi_request(cmd)
            _LOGGER.info("Befehl COMFOCOOL_OFF (%s) an Lüftungsanlage gesendet: %s"
                         % ("%d Sekunden" % comfocool_off_time if comfocool_off_time > 0 else "dauerhaft", cmd.hex()))
        else:
            _LOGGER.error("COMFOCOOL_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "COMFOCOOL_AUTO":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x85\x15\x05\x01')
            _LOGGER.info("Befehl COMFOCOOL_AUTO an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("COMFOCOOL_AUTO: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "ERROR_RESET":
        # Quittiert anstehende Stoerungen. Besteht die Ursache weiter, meldet die
        # Anlage den Fehler sofort erneut - das ersetzt also keine Behebung.
        if int(value) == 1:
            comfoconnect.cmd_clear_errors()
            _LOGGER.info("Befehl ERROR_RESET an Lüftungsanlage gesendet (Störungen quittiert)")
        else:
            _LOGGER.error("ERROR_RESET: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
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

def callback_alarm(node_id, errors):
    """Veroeffentlicht die Stoerungsmeldungen der Anlage per MQTT.

    Wird von comfoconnect.py aufgerufen, sobald eine CnAlarmNotification eintrifft -
    also ereignisgesteuert, nicht gepollt. Die Anlage schickt bei jeder Aenderung den
    kompletten aktuellen Fehlerstand, deshalb kann hier direkt ueberschrieben werden,
    ohne alte Meldungen mitfuehren zu muessen.

    ERROR_COUNT ist fuer die Logik in Loxone gedacht (0 = alles gut), ERROR_TEXT fuer
    die Anzeige. Beide retained, damit ein neu verbundener Client den aktuellen Stand
    sofort sieht statt bis zur naechsten Aenderung im Dunkeln zu tappen.
    """
    try:
        anzahl = len(errors)
        text = " | ".join("Fehler %d: %s" % (n, t) for n, t in sorted(errors.items())) if errors else ""

        client.publish(mqtt_topic + "ERROR_COUNT", anzahl, qos=0, retain=True)
        client.publish(mqtt_topic + "ERROR_TEXT", text, qos=0, retain=True)
        _LOGGER.debug("to MQTT %sERROR_COUNT = %d" % (mqtt_topic, anzahl))
    except Exception as e:
        _LOGGER.error("Konnte Störungsmeldung nicht per MQTT senden: " + fehlertext(e))

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
            _LOGGER.debug("Konnte Abwesenheits-Zustand nicht abfragen: " + fehlertext(e))

def send_away(seconds):
    """Schaltet die Abwesenheit fuer die angegebene Dauer ein."""
    cmd = b'\x84\x15' + AWAY_SUBUNIT + b'\x00\x00\x00\x00' + seconds_to_timerfield(seconds) + b'\x00'
    comfoconnect.cmd_rmi_request(cmd)
    return cmd

def sensorauswahl_anwenden(pcfg):
    """Liest, welche Sensoren in den Einstellungen abgewählt wurden.

    Gibt die Menge der abgewaehlten pdids zurueck. Der Katalog in mqtt_data.py ist
    und bleibt die einzige Quelle dafuer, WELCHE Sensoren es gibt - hier steht nur,
    welche davon der Benutzer nicht moechte.

    Bewusst keine Moeglichkeit, eigene pdids zu ergaenzen: Der Rohwert wird nach
    Byte-Laenge dekodiert, nicht nach PDO-Typ (siehe _handle_rpdo_notification in
    comfoconnect.py). Vierbyte-Werte kaemen als Hex-Zeichenkette an, und
    vorzeichenlose Werte oberhalb von 127 bzw. 32767 kippten ins Negative. Ein
    neuer Sensor braucht deshalb ohnehin eine Codeaenderung - dann kann er auch
    gleich richtig in mqtt_data.py stehen.

    Absichtlich nachsichtig: Ein unbrauchbarer Eintrag wird uebersprungen und
    protokolliert, statt den Start zu verhindern. Ein Tippfehler in der Auswahl darf
    nicht die ganze Lueftungssteuerung lahmlegen.
    """
    abschnitt = pcfg.get('SENSORS') or {}

    aus = set()
    for wert in abschnitt.get('aus') or []:
        try:
            aus.add(int(wert))
        except (TypeError, ValueError):
            _LOGGER.warning("Sensorauswahl: '%s' ist keine gueltige pdid - wird ignoriert." % wert)

    unbekannt = aus - set(sensor_data)
    if unbekannt:
        # Kein Fehler: Stand die pdid frueher im Katalog und ist inzwischen
        # entfallen, bleibt sie hier stehen und laeuft einfach ins Leere.
        _LOGGER.debug("Sensorauswahl: %s stehen nicht (mehr) im Katalog."
                      % ", ".join(str(p) for p in sorted(unbekannt)))

    return aus


class Langzeitstatistik:
    """Führt die Ereigniszähler über Neustarts hinweg fort.

    Ohne das wären die Zahlen nach jedem Neustart wieder bei null - und zwar nicht
    nur beim Neustart des LoxBerry, sondern auch beim Klick auf "Speichern" und beim
    automatischen Neustart durch die Überwachung. Gerade Letzteres ist heikel: Der
    greift genau dann, wenn etwas nicht stimmt, und würde damit ausgerechnet die
    Zahlen löschen, die den Vorfall belegen.

    Liegt im Datenverzeichnis (Speicherkarte), nicht auf der Ramdisk - die ist nach
    einem Neustart des Systems leer.

    Geschrieben wird nur, wenn sich tatsächlich etwas geändert hat, und höchstens
    alle paar Minuten. Im Normalbetrieb passiert also über Stunden gar kein Zugriff
    auf die Speicherkarte.
    """

    def __init__(self, verzeichnis, schreibabstand=300):
        self.datei = os.path.join(verzeichnis, "statistik.json") if verzeichnis else None
        # Die Weboberfläche kann die Statistik nicht selbst löschen: Sie würde nur die
        # Datei anfassen, während dieser Prozess den Stand ohnehin im Speicher hält
        # und beim nächsten Schreiben alles wiederherstellte. Stattdessen legt sie
        # diese Markierung an, die hier bemerkt und wieder entfernt wird.
        self.marker = os.path.join(verzeichnis, "statistik.reset") if verzeichnis else None
        self.schreibabstand = schreibabstand
        self.daten = {'seit': None, 'neustarts': 0, 'zaehler': {}}
        self._zuletzt_geschrieben = 0
        self._geaendert = False

        self._laden()

        # Stand aller früheren Läufe festhalten. Der aktuelle Lauf zählt bei null los
        # und wird beim Speichern jeweils daraufaddiert.
        self._frueher = dict(self.daten['zaehler'])

        self.daten['neustarts'] = self.daten.get('neustarts', 0) + 1
        if not self.daten.get('seit'):
            self.daten['seit'] = time.time()
        self._geaendert = True
        self.speichern(erzwingen=True)

    def _laden(self):
        if not self.datei or not os.path.exists(self.datei):
            return
        try:
            with open(self.datei, encoding='utf-8') as f:
                gelesen = json.load(f)
            if isinstance(gelesen, dict):
                self.daten.update(gelesen)
                self.daten.setdefault('zaehler', {})
        except Exception as e:
            # Kaputte Datei darf den Start nicht verhindern - dann eben bei null
            # anfangen. Die Statistik ist ein Diagnosewerkzeug, kein Betriebsmittel.
            _LOGGER.warning("Langzeitstatistik konnte nicht gelesen werden, beginne neu: " + fehlertext(e))

    def uebernehmen(self, zaehler):
        """Bildet die Gesamtsumme aus früheren Läufen plus dem aktuellen.

        Bewusst als Summe statt einzeln hochzuzählen: Fällt das Speichern einmal aus
        oder stürzt der Prozess ab, geht höchstens der letzte Abschnitt verloren -
        es kann aber niemals etwas doppelt gezählt werden.
        """
        for name, wert in zaehler.items():
            if isinstance(wert, (int, float)) and not name.startswith('letzt'):
                gesamt = self._frueher.get(name, 0) + wert
                if self.daten['zaehler'].get(name) != gesamt:
                    self.daten['zaehler'][name] = gesamt
                    self._geaendert = True

    def reset_angefordert(self):
        """True, wenn die Weboberfläche ein Zurücksetzen angefordert hat.

        Entfernt die Markierung dabei gleich wieder, damit nicht bei jedem Durchlauf
        erneut zurückgesetzt wird.
        """
        if not self.marker:
            return False
        try:
            if os.path.exists(self.marker):
                os.remove(self.marker)
                return True
        except Exception:
            pass
        return False

    def zuruecksetzen(self):
        self._frueher = {}
        self.daten = {'seit': time.time(), 'neustarts': 1, 'zaehler': {}}
        self._geaendert = True
        self.speichern(erzwingen=True)

    def speichern(self, erzwingen=False):
        if not self.datei or not self._geaendert:
            return
        if not erzwingen and time.time() - self._zuletzt_geschrieben < self.schreibabstand:
            return
        try:
            os.makedirs(os.path.dirname(self.datei), exist_ok=True)
            # Erst in eine Nebendatei schreiben und dann umbenennen: Ein Stromausfall
            # mitten im Schreiben hinterlässt sonst eine halbe Datei, die beim
            # nächsten Start nicht mehr lesbar ist.
            tmp = self.datei + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.daten, f)
            os.replace(tmp, self.datei)
            self._zuletzt_geschrieben = time.time()
            self._geaendert = False
        except Exception as e:
            _LOGGER.debug("Langzeitstatistik konnte nicht geschrieben werden: " + fehlertext(e))


class StoerungsSchreiber(logging.Handler):
    """Sichert bei einem Fehler die Logzeilen davor und danach in eine eigene Datei.

    Warum das nötig ist: Bei Loglevel DEBUG wachsen die Logdateien schnell, und
    LoxBerry räumt sie automatisch ab ("Log Maintenance cleaned up logfile"). Genau
    der Teil, der eine Störung erklären würde, ist dann weg - beim Ausfall dieser
    Nacht fehlten dadurch die entscheidenden Stunden.

    Deshalb läuft hier ständig ein Ringpuffer der letzten Minuten mit. Sobald eine
    Fehlermeldung auftritt, wird der Puffer weggeschrieben und anschließend noch
    eine Weile weiter mitgeschnitten - man hat also Vorgeschichte UND Nachspiel.

    Abgelegt wird im Datenverzeichnis, nicht im Logverzeichnis: Letzteres liegt auf
    der Ramdisk (nach einem Neustart weg) und ist genau das, was aufgeräumt wird.

    Drei Begrenzungen, damit das nie aus dem Ruder läuft:
      - der Ringpuffer ist nach Zeit UND Zeilenzahl gedeckelt (Speicher)
      - nach einem Bericht gilt eine Sperrzeit (sonst schriebe eine Störung, die
        im Sekundentakt Fehler wirft, den Datenträger voll)
      - es werden nur die neuesten Berichte behalten, ältere werden gelöscht
    """

    def __init__(self, verzeichnis, vorlauf=120, nachlauf=120,
                 max_zeilen=20000, max_dateien=5, sperrzeit=600):
        super().__init__()
        self.verzeichnis = verzeichnis
        self.vorlauf = vorlauf
        self.nachlauf = nachlauf
        self.max_zeilen = max_zeilen
        self.max_dateien = max_dateien
        self.sperrzeit = sperrzeit

        self.puffer = collections.deque()
        self.datei = None
        self.ende = 0
        self.naechster_erlaubt = 0
        self.anzahl_berichte = 0
        self.letzter_bericht = None

    def emit(self, record):
        # Diese Methode läuft in JEDEM Thread, der etwas protokolliert. Sie darf
        # deshalb unter keinen Umständen eine Ausnahme nach oben durchlassen -
        # sonst reißt eine kaputte Diagnosefunktion das Plugin mit.
        try:
            jetzt = time.time()
            zeile = self.format(record)

            self.puffer.append((jetzt, zeile))
            while self.puffer and (jetzt - self.puffer[0][0] > self.vorlauf
                                   or len(self.puffer) > self.max_zeilen):
                self.puffer.popleft()

            if self.datei:
                self.datei.write(zeile + "\n")
                if jetzt > self.ende:
                    self._schliessen()
            elif record.levelno >= logging.ERROR and jetzt >= self.naechster_erlaubt:
                self._starten(jetzt, record)

        except Exception:
            pass

    def _starten(self, jetzt, record):
        os.makedirs(self.verzeichnis, exist_ok=True)
        name = os.path.join(
            self.verzeichnis,
            "stoerung_%s.log" % datetime.datetime.fromtimestamp(jetzt).strftime("%Y%m%d_%H%M%S")
        )
        self.datei = open(name, "w", encoding="utf-8")
        self.ende = jetzt + self.nachlauf
        self.letzter_bericht = jetzt
        self.anzahl_berichte += 1

        self.datei.write("Störungsbericht - ausgelöst durch:\n  %s\n\n" % record.getMessage())
        self.datei.write("Die folgenden Zeilen umfassen etwa %d Sekunden davor und %d danach.\n"
                         % (self.vorlauf, self.nachlauf))
        self.datei.write("=" * 78 + "\n")
        for _, alt in self.puffer:
            self.datei.write(alt + "\n")

    def _schliessen(self):
        try:
            self.datei.write("=" * 78 + "\nEnde des Störungsberichts.\n")
            self.datei.close()
        finally:
            self.datei = None
            self.naechster_erlaubt = time.time() + self.sperrzeit
            self._aufraeumen()

    def _aufraeumen(self):
        """Behält nur die neuesten Berichte."""
        try:
            dateien = sorted(
                (os.path.join(self.verzeichnis, f) for f in os.listdir(self.verzeichnis)
                 if f.startswith("stoerung_") and f.endswith(".log")),
                key=os.path.getmtime, reverse=True
            )
            for alt in dateien[self.max_dateien:]:
                os.remove(alt)
        except Exception:
            pass


def fehlertext(e):
    """Beschreibt eine Ausnahme lesbar - auch wenn sie gar keinen Text hat.

    Die Protokoll-Ausnahmen dieser Bibliothek (PyComfoConnectNotAllowed,
    ...NotExist, ...BadRequest und die uebrigen) sind reine Markierungsklassen
    ohne Meldung, str() liefert dort einen LEEREN String. Wer sie nur mit str(e)
    protokolliert, schreibt "ging nicht: " ins Log und verschweigt die Ursache -
    genau so geschehen bei der Abwesenheitsabfrage, wo 375 Meldungen ohne jede
    Begruendung im Log standen, obwohl der Grund (NOT_ALLOWED) eine Zeile darueber
    stand.
    """
    text = str(e)
    return "%s: %s" % (type(e).__name__, text) if text else type(e).__name__

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

    # Fuer die Sensortabelle in der Weboberflaeche mitschreiben. BEWUSST hier, nach
    # der Umrechnung und VOR der PUSH-Drosselung: Angezeigt werden soll der Wert, den
    # die Anlage gerade meldet - nicht der, den wir zuletzt weitergegeben haben. Sonst
    # stuende bei einem Sensor mit langem Sendeintervall minutenlang ein veralteter
    # Wert in der Tabelle, obwohl laengst frische Daten da sind.
    letzte_werte[var] = (value, time.time())

    # Senden an den MQTT Broker nur bei Änderungen und nach Ablauf der PUSH Zeit, parametriert in mqtt_data.py
    if 'PUSH' in sensor_data[var]:
        # .get() mit Vorgabewert: beim allerersten Wert eines Sensors gibt es noch
        # keinen Eintrag, und 0 bedeutet "darf sofort gesendet werden".
        if (time.time() > interval.get(var, 0)):
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
            # Zurücksetzen auf Wunsch aus der Weboberfläche. Bewusst hier und nicht
            # dort erledigt: Nur dieser Prozess kennt den vollständigen Stand, und
            # zurückgesetzt gehören BEIDE Spalten - eine Statistik, in der die
            # Gesamtzahl bei null steht und der laufende Betrieb noch die alten Werte
            # zeigt, wäre schlimmer als gar keine.
            if langzeit and langzeit.reset_angefordert():
                if comfoconnect:
                    for name in list(comfoconnect.stats):
                        comfoconnect.stats[name] = None if name.startswith('letzt') else 0
                globals()['mqtt_abbrueche'] = 0
                globals()['mqtt_letzter_abbruch'] = None
                if stoerungsschreiber:
                    stoerungsschreiber.anzahl_berichte = 0
                    stoerungsschreiber.letzter_bericht = None
                langzeit.zuruecksetzen()
                _LOGGER.info("Diagnose-Statistik wurde über die Weboberfläche zurückgesetzt.")
        except Exception as e:
            _LOGGER.debug("Zurücksetzen der Statistik fehlgeschlagen: " + fehlertext(e))

        try:
            if statusfile:
                status = {
                    'pid': os.getpid(),
                    'now': time.time(),
                    # Mirrored config, see the module-level comment - index.cgi reads
                    # these instead of opening the config file on every status poll.
                    'sensorwatch_enabled': sensorwatch_enabled,
                    'sensorwatch_timeout_sec': sensorwatch_timeout_sec,
                    # True only once (re-)registration has actually finished on the
                    # CURRENT connection - False again for the whole gap during a later
                    # reconnect. Siehe den Kommentar zum Attribut in
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
                    'sensors_expected': sensors_expected,

                    # Betriebsstatistik fuer die Diagnoseanzeige. Zaehlt die
                    # Aussetzer, die im laufenden Betrieb bewusst abgefangen und
                    # nicht als Stoerung gemeldet werden - sonst waeren sie
                    # unsichtbar, und eine Anlage, die schleichend haeufiger
                    # zickt, fiele erst auf, wenn gar nichts mehr geht.
                    'plugin_start': plugin_start,
                    'mqtt_abbrueche': mqtt_abbrueche,
                    'mqtt_letzter_abbruch': mqtt_letzter_abbruch,
                    'stats': dict(comfoconnect.stats) if comfoconnect else {},
                    'stoerungsberichte': stoerungsschreiber.anzahl_berichte if stoerungsschreiber else 0,
                    'letzter_stoerungsbericht': stoerungsschreiber.letzter_bericht if stoerungsschreiber else None,

                    # Sensortabelle der Weboberflaeche. Als Zeichenkette, nicht als
                    # Zahl: In der Tabelle wird der Wert nur angezeigt, und so bleibt
                    # er exakt so stehen, wie er auch auf MQTT gegangen ist - ohne
                    # dass JSON aus 21.0 eine 21 macht.
                    'werte': {str(p): [str(w), t] for p, (w, t) in list(letzte_werte.items())},
                    'sensoren_aus': sorted(sensoren_aus),
                }

                # Dieselben Zaehler zusaetzlich als Langzeitwert. Die Zahlen oben
                # beziehen sich immer nur auf den laufenden Prozess und stehen nach
                # jedem Neustart wieder auf null - auch nach einem Klick auf
                # "Speichern" und nach einem Neustart durch die Ueberwachung. Genau
                # der letzte Fall greift aber dann, wenn etwas nicht stimmt, und
                # wuerde ohne das hier ausgerechnet die belastenden Zahlen loeschen.
                if langzeit:
                    laufend = dict(status['stats'])
                    laufend['mqtt_abbrueche'] = mqtt_abbrueche
                    laufend['stoerungsberichte'] = status['stoerungsberichte']
                    langzeit.uebernehmen(laufend)
                    langzeit.speichern()
                    status['gesamt'] = dict(langzeit.daten['zaehler'])
                    status['gesamt_seit'] = langzeit.daten.get('seit')
                    status['gesamt_neustarts'] = langzeit.daten.get('neustarts', 0)

                # Write to a tmp file and rename over the real one - index.cgi (or the
                # restart check) must never be able to read a half-written file.
                tmpfile = statusfile + '.tmp'
                with open(tmpfile, 'w') as f:
                    json.dump(status, f)
                os.replace(tmpfile, statusfile)

        except Exception as e:
            _LOGGER.debug("Konnte Statusdatei nicht schreiben: " + fehlertext(e))

        try:
            publish_sensorwatch_state()
        except Exception as e:
            # Wie beim Schreiben der Statusdatei: eine Diagnosefunktion darf das
            # eigentliche Plugin niemals mit in den Abgrund reissen.
            _LOGGER.debug("Konnte Sensor-Timeout-Status nicht veröffentlichen: " + fehlertext(e))

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
    global mqtt_topic, client, debug, loglevel, logfile, _LOGGER, search, boost_mode_time, ventmode_stop_supply_fan_time, ventmode_stop_exhaust_fan_time, bypass_on_time, bypass_off_time, comfoconnect, statusfile, sensorwatch_enabled, sensorwatch_timeout_sec, comfocool_off_time, sensors_expected

    loglevel=logging.ERROR
    search = False
    snapshotdir = ""

    boost_mode_time = b'\x84\x03'
    ventmode_stop_supply_fan_time = b'\x10\x0e'
    ventmode_stop_exhaust_fan_time = b'\x10\x0e'
    bypass_on_time = b'\x10\x0e'
    bypass_off_time = b'\x10\x0e'
    # Sekunden; 0 = keine Zeit gesetzt, dann schaltet COMFOCOOL_OFF dauerhaft.
    comfocool_off_time = 0
    configfile = ""

    opts, args = getopt.getopt(sys.argv[1:],"c:f:l:s:",['configfile=', 'logfile=', 'loglevel=', 'search', 'statusfile=', 'snapshotdir='])
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
        elif opt == "--snapshotdir":
            snapshotdir = args
    
    if loglevel == 7: # Level Debug
        debug = True
    else:
        debug = False

    _LOGGER = setup_logger("COMFOCONNECT", snapshotdir)
    # logfile statt einer zweiten, identischen Kopie der Option: die gab es hier
    # frueher als eigene Variable, die aber nur gesetzt wurde, WENN --logfile
    # uebergeben wurde - ohne die Option waere diese Zeile mit einem NameError
    # abgestuerzt, noch bevor irgendetwas geloggt werden konnte.
    _LOGGER.debug("logfile: " + str(logfile))
    _LOGGER.info("loglevel: " + logging.getLevelName(_LOGGER.level))

    # Abstuerze in Hintergrund-Threads in unser Logging holen.
    #
    # Python meldet einen abgestuerzten Thread von sich aus nur direkt auf stderr -
    # am Logger vorbei. Folge: kein ERROR, kein Stoerungsbericht, kein Zaehler, und
    # die Statusanzeige merkt nichts. Genau so ist am 20.07. der Verbindungsthread
    # gestorben, waehrend nach aussen alles normal aussah; der Traceback stand nur
    # deshalb im Log, weil wrapper.pl stderr dort hineinleitet.
    #
    # Ein sterbender Thread ist immer ein Fehler - der Prozess laeuft dann als Huelle
    # weiter, ohne noch irgendetwas zu tun.
    def thread_absturz(args):
        if args.exc_type is SystemExit:
            return
        _LOGGER.error(
            "Thread '%s' ist abgestuerzt - das Plugin arbeitet ab jetzt nur noch "
            "eingeschraenkt:\n%s"
            % (getattr(args.thread, 'name', '?'),
               "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)).rstrip())
        )

    threading.excepthook = thread_absturz

    # Erst hier, nicht in setup_logger(): braucht einen funktionierenden Logger, um
    # eine unlesbare Datei melden zu koennen.
    if snapshotdir:
        try:
            global langzeit
            langzeit = Langzeitstatistik(snapshotdir)
        except Exception as e:
            _LOGGER.warning("Langzeitstatistik nicht verfuegbar: " + fehlertext(e))
    
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

        # Sensorauswahl des Benutzers. mqtt_data.py bleibt der mitgelieferte Katalog
        # und wird nur gelesen - hier steht ausschliesslich die ABWEICHUNG davon.
        #
        # Bewusst so herum: Kaeme ein Plugin-Update mit neuen Sensoren, wuerde eine in
        # der Config eingefrorene Vollkopie der Liste diese neuen Eintraege dauerhaft
        # verdecken. So kommen sie automatisch dazu, und die eigene Auswahl bleibt
        # trotzdem erhalten (die Config wird beim Update gesichert und
        # zurueckgespielt, siehe preupgrade.sh/postupgrade.sh).
        global sensoren_aus, sensors_expected
        sensoren_aus = sensorauswahl_anwenden(pcfg)

        # Erwarteten Zaehlerstand SOFORT festlegen, nicht erst kurz vor der
        # Registrierung. Der Status-Thread laeuft schon, waehrend die Verbindung
        # aufgebaut wird - stand hier noch der Vorgabewert (der volle Katalog),
        # zeigte die Weboberflaeche in dieser Zeit "Registriere Sensoren (0 von 52)",
        # obwohl nur 48 angehakt waren.
        sensors_expected = len([p for p in sensor_data if p not in sensoren_aus])

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
    comfoconnect.callback_alarm = callback_alarm

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
            _LOGGER.warning("Konnte Session bei der Zehnder-Box nicht sauber schließen: " + fehlertext(e))

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

        # Letzter Stand der Zaehler auf die Speicherkarte, bevor os._exit() unten den
        # Prozess hart beendet. Zwischendurch wird nur alle paar Minuten geschrieben -
        # ohne das hier ginge bei einem Neustart regelmaessig der letzte Abschnitt
        # verloren, und ausgerechnet der ist der interessante, wenn die Ueberwachung
        # wegen einer Stoerung neu startet.
        if langzeit:
            try:
                laufend = dict(comfoconnect.stats) if comfoconnect else {}
                laufend['mqtt_abbrueche'] = mqtt_abbrueche
                laufend['stoerungsberichte'] = stoerungsschreiber.anzahl_berichte if stoerungsschreiber else 0
                langzeit.uebernehmen(laufend)
                langzeit.speichern(erzwingen=True)
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
            _LOGGER.warning("Verbindung zur Bridge fehlgeschlagen (Versuch %d/%d), erneuter Versuch: %s" % (attempt, bridge_connect_attempts, fehlertext(e)))
            time.sleep(2)

#   Register sensors ################################################################################################
    # Ein Versuch pro Sensor (siehe register_sensor()), kein Retry, kein Gesamtlimit -
    # jede einzelne Anfrage hat bereits ihr Antwort-Timeout.
    #
    # Sensoren, die diese Anlage nicht kennt, werden UEBERSPRUNGEN und nicht als Fehler
    # behandelt. Das ist kein Schoenreden, sondern der Normalfall: sensor_data ist eine
    # Liste aller bekannten pdids ueber alle Comfo-Modelle und Firmware-Staende hinweg,
    # und kein einzelnes Geraet unterstuetzt sie alle. Wuerde hier abgebrochen, koennte
    # das Plugin auf fremder Hardware ueberhaupt nicht starten - und mit aktiviertem
    # automatischem Neustart in einer Neustartschleife landen.
    #
    # Der einzige Abbruchgrund ist ein echter Verbindungsverlust (OSError), und der
    # fuehrt nicht zum Prozessende, sondern uebergibt an den automatischen Reconnect.
    #
    # MQTT ist zu diesem Zeitpunkt bereits verbunden und das Veroeffentlichen haengt
    # nicht an diesem Durchlauf - Werte bereits registrierter Sensoren gehen sofort
    # raus, waehrend die uebrigen noch angemeldet werden (siehe callback_sensor()).
    #
    # Keine Pruefung mehr, ob Zubehoer wie das ComfoCool ueberhaupt angeschlossen
    # ist. Die Anlage nimmt das Abonnement auch ohne Modul an und antwortet mit 0 -
    # es entsteht also kein Fehler, nur ein nichtssagender Wert. Wen das stoert, der
    # waehlt die beiden Eintraege in den Einstellungen ab; das ist ehrlicher als
    # eine automatische Erkennung, die beim Start jedes Mal auf eine Antwort wartet
    # und dabei den erwarteten Zaehlerstand erst spaet kennt (siehe unten).
    sensor_ids = [pdid for pdid in sensor_data if pdid not in sensoren_aus]

    abgewaehlt = [sensor_data[p]['NAME'] for p in sensor_data if p in sensoren_aus]
    if abgewaehlt:
        _LOGGER.info("In den Einstellungen abgewählt (%d): %s"
                     % (len(abgewaehlt), ", ".join(abgewaehlt)))

    connection_lost = False
    uebersprungen = []

    _LOGGER.info("Registriere %d Sensoren..." % len(sensor_ids))

    for i, x in enumerate(sensor_ids):
        try:
            # register_sensor() liefert None, wenn die Anlage den Sensor nicht kennt
            # (keine Antwort oder ausdrueckliche Ablehnung) - es wirft in dem Fall
            # nicht. Die Begruendung hat es selbst schon protokolliert, hier wird nur
            # mitgezaehlt, damit am Ende eine Gesamtbilanz im Log steht.
            reply = comfoconnect.register_sensor(x)
            if reply is None:
                uebersprungen.append("%d (%s)" % (x, sensor_data[x]['NAME']))
                continue
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

        except Exception as e:
            # Auffangnetz fuer alles Uebrige. Konkret bekannt: steht ein Sensor in
            # mqtt_data.py, fehlt aber in RPDO_TYPE_MAP (comfoconnect.py), wirft
            # register_sensor() eine nackte Exception - ohne diesen Zweig wuerde ein
            # solcher Eintragsfehler den kompletten Start abbrechen, statt nur diesen
            # einen Sensor zu kosten. Aktuell sind alle Sensoren vollstaendig
            # eingetragen; das hier schuetzt kuenftige Ergaenzungen.
            _LOGGER.error("Sensor %d (%s) konnte nicht registriert werden (%s: %s) - wird übersprungen."
                          % (x, sensor_data[x]['NAME'], type(e).__name__, str(e)))
            uebersprungen.append("%d (%s)" % (x, sensor_data[x]['NAME']))
            continue

    if connection_lost:
        # sensors_ready bleibt False (ist es bereits), bis der Reconnect-Durchlauf in
        # _connection_thread_loop() selbst durch ist und die Kennung setzt - die
        # Statusseite zeigt so lange "Registriere Sensoren (X von Y)".
        _LOGGER.info(
            "Erstregistrierung durch Verbindungsverlust unterbrochen - Fertigstellung läuft im "
            "Hintergrund weiter, sobald die Bridge wieder erreichbar ist."
        )
    elif uebersprungen:
        # Gesamtbilanz auf einen Blick, statt die einzelnen Warnungen im Log
        # zusammensuchen zu muessen. Kein Fehler: siehe Kommentar an der Schleife.
        _LOGGER.warning(
            "%d von %d Sensoren werden von dieser Anlage nicht unterstützt und übersprungen: %s"
            % (len(uebersprungen), len(sensor_ids), ", ".join(uebersprungen))
        )

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
        _LOGGER.error("Diagnose-Abfragen (Version/RegisteredApps/Time) fehlgeschlagen, vermutlich Verbindung gerade unterbrochen: %s" % fehlertext(e))
    

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

def setup_logger(name, snapshotdir=""):
    global logfile
    
    logging.captureWarnings(1)
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)

    # Die Loglevel-Einstellung des LoxBerry wird bewusst NICHT mehr am Logger
    # gesetzt, sondern an den ausgebenden Handlern. Das klingt nach Haarspalterei,
    # macht aber den entscheidenden Unterschied für die Störungsberichte:
    #
    # Ein Logger verwirft Meldungen unterhalb seines Levels sofort - sie entstehen
    # gar nicht erst und erreichen KEINEN Handler. Stand der LoxBerry also auf
    # "Fehler", lief der Ringpuffer des StoerungsSchreibers leer mit, und ein
    # Bericht enthielt am Ende nur die Fehlerzeile selbst. Ausgerechnet die
    # Vorgeschichte, die den Fehler erklärt, fehlte.
    #
    # Jetzt entstehen intern immer alle Meldungen bis DEBUG hinunter; welche davon
    # tatsächlich in Logdatei und stdout landen, entscheiden die Handler. Nach außen
    # ändert sich dadurch nichts - die Logdatei bleibt genauso knapp wie eingestellt.
    # Der Ringpuffer sieht aber alles und kann im Fehlerfall die vollständige
    # Vorgeschichte sichern, ohne dass dauerhaft auf DEBUG gestellt werden muss.
    handler.setLevel(loglevel)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    if not logfile:
        logfile="/tmp/"+datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]+"_comfoconnect.log"
    # Root auf DEBUG (siehe oben) - sonst wären die Meldungen der Bibliothek
    # (Logger "comfoconnect" und "bridge", die ihr Level von hier erben) schon
    # wieder gefiltert, und gerade die erklären eine Störung meistens.
    logging.basicConfig(filename=logfile,level=logging.DEBUG,format='%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s',datefmt='%H:%M:%S')

    # ...und die Begrenzung stattdessen an die Logdatei selbst.
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            h.setLevel(loglevel)

    # Störungsberichte (siehe StoerungsSchreiber). Bewusst am ROOT-Logger und nicht
    # an unserem eigenen: So werden auch die Meldungen der Bibliothek
    # (pycomfoconnect, eigener Logger "comfoconnect") mitgeschnitten - und gerade
    # die erklären eine Störung meistens.
    #
    # Der Handler bekommt dasselbe Format wie die Logdatei, damit ein Bericht
    # aussieht wie ein Ausschnitt daraus und sich direkt vergleichen lässt.
    global stoerungsschreiber
    stoerungsschreiber = None
    if snapshotdir:
        try:
            stoerungsschreiber = StoerungsSchreiber(snapshotdir)
            stoerungsschreiber.setFormatter(logging.Formatter(
                '%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s', datefmt='%H:%M:%S'))
            stoerungsschreiber.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(stoerungsschreiber)
        except Exception as e:
            logger.error("Konnte Störungsberichte nicht einrichten: " + str(e))

    return logger

if __name__ == "__main__":
    main()
