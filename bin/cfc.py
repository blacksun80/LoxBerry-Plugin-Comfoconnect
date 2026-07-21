#!/usr/bin/python3
import paho.mqtt.client as mqtt
import datetime
import collections
import os
import time
import threading
import traceback
import functools
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

# Meldet per MQTT, ob die Anlage noch Sensorwerte liefert. 1 = seit der
# eingestellten Zeit nichts mehr empfangen, 0 = laeuft wieder.
SENSORWATCH_TOPIC = "SENSOR_TIMEOUT"

# Zuletzt auf SENSORWATCH_TOPIC gesendeter Wert. None = noch nichts gesendet.
sensorwatch_published = None

# Zustand der MQTT-Verbindung, gesetzt von on_connect/on_disconnect und vom
# Status-Thread gelesen.
mqtt_connected = False
mqtt_last_change = None

# Betriebsstatistik der MQTT-Seite (die Gegenstuecke zur Anlagenseite stehen in
# comfoconnect.py unter self.stats). Startzeit als Bezugsgroesse: "3 Abbrueche"
# heisst etwas voellig anderes nach einer Stunde als nach drei Wochen.
plugin_start = time.time()
mqtt_abbrueche = 0
mqtt_letzter_abbruch = None

# Wird in setup_logger() gesetzt, sobald ein Verzeichnis für Log-Snapshots
# übergeben wurde. Hier schon definiert, damit der Status-Thread ihn auch dann
# lesen kann, wenn es (noch) keinen gibt.
snapshotschreiber = None

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

# Zuletzt empfangener Befehl je Thema, fuer die Befehlstabelle in der
# Weboberflaeche: (Wert, Zeitpunkt, Fehlertext oder None).
#
# Beantwortet die Frage, die sich sonst nur muehsam aus dem Log beantworten laesst:
# "Ich schicke aus Loxone etwas und nichts passiert" - ist die Nachricht ueberhaupt
# angekommen, und wurde sie verarbeitet oder lief sie auf einen Fehler?
letzte_befehle = {}

# Themen, die tatsaechlich abonniert wurden - die Wahrheit darueber, welche Befehle
# es gibt. Wird in die Statusdatei geschrieben, damit die Weboberflaeche ihre
# Anzeigeliste dagegen pruefen kann.
#
# Hintergrund: Die Anzeigeliste in index.cgi ist zwangslaeufig eine zweite Liste
# derselben Themen - was ein Befehl BEWIRKT, steht in _dispatch_message() und laesst
# sich nicht sinnvoll als Daten ablegen. Statt so zu tun, als gaebe es die Doppelung
# nicht, macht sie sich hier bemerkbar, sobald sie auseinanderlaeuft.
abonnierte_themen = []


def _abonniere(client, name):
    """Abonniert ein Befehlsthema und merkt es sich fuer die Weboberflaeche."""
    client.subscribe(mqtt_topic + name, qos=0)
    if name not in abonnierte_themen:
        abonnierte_themen.append(name)

# Filled in by main() from --statusfile. None until then, so write_status() can no-op
# safely if it is ever called too early.
statusfile = None

def thread_sicher(fn):
    """Faengt Fehler in einem MQTT-Rueckruf ab.

    paho ruft diese Funktionen im eigenen Netzwerk-Thread auf. Eine
    durchgereichte Ausnahme wuerde dort die Schleife beenden - die MQTT-Seite
    waere danach still tot.
    """
    @functools.wraps(fn)
    def sicher(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            # ERROR, nicht WARNING: Das ist immer ein Programmierfehler, und der
            # Log-Snapshot soll die Vorgeschichte dazu festhalten.
            _LOGGER.error("Fehler im MQTT-Rückruf %s (%s: %s):\n%s"
                          % (fn.__name__, type(e).__name__, e, traceback.format_exc().rstrip()))
    return sicher


@thread_sicher
def on_publish(client, userdata, mid):
    _LOGGER.debug("Published Data - mid: "+str(mid))
    pass

@thread_sicher
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

    _abonniere(client, "FAN_MODE")
    _abonniere(client, "FAN_MODE_AWAY")
    _abonniere(client, "AWAY_FOR")
    _abonniere(client, "AWAY_END")
    _abonniere(client, "ERROR_RESET")
    _abonniere(client, "COMFOCOOL")
    _abonniere(client, "COMFOCOOL_AUTO")
    _abonniere(client, "COMFOCOOL_OFF")
    _abonniere(client, "COMFOCOOL_OFF_TIME")
    _abonniere(client, "FAN_MODE_LOW")
    _abonniere(client, "FAN_MODE_MEDIUM")
    _abonniere(client, "FAN_MODE_HIGH")
    _abonniere(client, "MODE")
    _abonniere(client, "MODE_AUTO")
    _abonniere(client, "MODE_MANUAL")
    _abonniere(client, "VENTMODE_STOP_SUPPLY_FAN")
    _abonniere(client, "START_EXHAUST_FAN")
    _abonniere(client, "START_SUPPLY_FAN")
    _abonniere(client, "VENTMODE_STOP_EXHAUST_FAN")
    _abonniere(client, "BOOST_MODE_END")
    _abonniere(client, "TEMPPROF")
    _abonniere(client, "TEMPPROF_NORMAL")
    _abonniere(client, "TEMPPROF_COOL")
    _abonniere(client, "TEMPPROF_WARM")
    _abonniere(client, "BYPASS")
    _abonniere(client, "BYPASS_ON")
    _abonniere(client, "BYPASS_OFF")
    _abonniere(client, "BYPASS_AUTO")
    _abonniere(client, "SENSOR_TEMP")
    _abonniere(client, "SENSOR_TEMP_OFF")
    _abonniere(client, "SENSOR_TEMP_AUTO")
    _abonniere(client, "SENSOR_TEMP_ON")
    _abonniere(client, "SENSOR_HUMC")
    _abonniere(client, "SENSOR_HUMC_OFF")
    _abonniere(client, "SENSOR_HUMC_AUTO")
    _abonniere(client, "SENSOR_HUMC_ON")
    _abonniere(client, "SENSOR_HUMP")
    _abonniere(client, "SENSOR_HUMP_OFF")
    _abonniere(client, "SENSOR_HUMP_AUTO")
    _abonniere(client, "SENSOR_HUMP_ON")
    _abonniere(client, "BOOST_MODE")
    _abonniere(client, "BOOST_MODE_TIME")
    _abonniere(client, "VENTMODE_STOP_SUPPLY_FAN_TIME")
    _abonniere(client, "VENTMODE_STOP_EXHAUST_FAN_TIME")
    _abonniere(client, "BYPASS_ON_TIME")
    _abonniere(client, "BYPASS_OFF_TIME")

@thread_sicher
def on_disconnect(client, userdata, rc):
    global mqtt_connected, mqtt_last_change, mqtt_abbrueche, mqtt_letzter_abbruch

    # rc ist hier kein CONNACK-Code, sondern der Grund der Trennung:
    # 0 = von uns veranlasst, alles andere ein Abbruch.
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

    # Kurzname ohne das eingestellte Praefix - die Tabelle in der Weboberflaeche
    # zeigt die Themen genauso an, und das Praefix ist dort ohnehin ueberall gleich.
    kurz = topic[len(mqtt_topic):] if topic.startswith(mqtt_topic) else topic

    try:
        _dispatch_message(topic, value)
        letzte_befehle[kurz] = (value, time.time(), None)
    except Exception as e:
        # Auch den Fehlschlag festhalten. Sonst zeigte die Tabelle den Wert an, als
        # waere er verarbeitet worden - gerade beim Suchen nach "warum passiert
        # nichts" waere das die falsche Faehrte.
        letzte_befehle[kurz] = (value, time.time(), fehlertext(e))
        # Ein unbrauchbarer Payload darf diesen Rueckruf nicht abbrechen: paho ruft ihn
        # im eigenen Thread auf, eine Ausnahme wuerde die MQTT-Seite stilllegen.
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
        boost_mode_time=seconds_to_timerfield(value)
        _LOGGER.debug("BOOST_MODE_TIME hex: " + str(boost_mode_time))
        _LOGGER.info("BOOST_MODE_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "BOOST_MODE":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x01\x06\x00\x00\x00\x00' + boost_mode_time + b'\x03')
            _LOGGER.info("Befehl BOOST_MODE an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BOOST_MODE: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN_TIME":
        ventmode_stop_supply_fan_time=seconds_to_timerfield(value)
        _LOGGER.debug("VENTMODE_STOP_SUPPLY_FAN_TIME hex " + str(ventmode_stop_supply_fan_time))
        _LOGGER.info("VENTMODE_STOP_SUPPLY_FAN_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "VENTMODE_STOP_SUPPLY_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x07\x01\x00\x00\x00\x00' + ventmode_stop_supply_fan_time + b'\x01')
            _LOGGER.info("Befehl VENTMODE_STOP_SUPPLY_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("VENTMODE_STOP_SUPPLY_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN_TIME":
        ventmode_stop_exhaust_fan_time=seconds_to_timerfield(value)
        _LOGGER.debug("VENTMODE_STOP_EXHAUST_FAN_TIME in hex: " + str(ventmode_stop_exhaust_fan_time))
        _LOGGER.info("VENTMODE_STOP_EXHAUST_FAN_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "VENTMODE_STOP_EXHAUST_FAN":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x06\x01\x00\x00\x00\x00' + ventmode_stop_exhaust_fan_time + b'\x01')
            _LOGGER.info("Befehl VENTMODE_STOP_EXHAUST_FAN an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("VENTMODE_STOP_EXHAUST_FAN: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS_ON_TIME":
        bypass_on_time=seconds_to_timerfield(value)
        _LOGGER.debug("BYPASS_ON_TIME in hex: " + str(bypass_on_time))
        _LOGGER.info("BYPASS_ON_TIME " + str(value) + " sec" + " übernommen")
    elif topic == mqtt_topic + "BYPASS_ON":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_on_time + b'\x01')
            _LOGGER.info("Befehl BYPASS_ON an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS_ON: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS_OFF_TIME":
        bypass_off_time=seconds_to_timerfield(value)
        _LOGGER.debug("BYPASS_OFF_TIME in hex: " + str(bypass_off_time))
        _LOGGER.info("BYPASS_OFF_TIME " + str(value) + " sec")
    elif topic == mqtt_topic + "BYPASS_OFF":
        if int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_off_time + b'\x02')
            _LOGGER.info("Befehl BYPASS_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS_OFF: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Wert 1")
    elif topic == mqtt_topic + "BYPASS":
        if int(value) == 0:
            comfoconnect.cmd_rmi_request(CMD_BYPASS_AUTO)
            _LOGGER.info("Befehl BYPASS_AUTO an Lüftungsanlage gesendet")
        elif int(value) == 1:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_on_time + b'\x01')
            _LOGGER.info("Befehl BYPASS_ON an Lüftungsanlage gesendet")
        elif int(value) == 2:
            comfoconnect.cmd_rmi_request(b'\x84\x15\x02\x01\x00\x00\x00\x00' + bypass_off_time + b'\x02')
            _LOGGER.info("Befehl BYPASS_OFF an Lüftungsanlage gesendet")
        else:
            _LOGGER.error("BYPASS: Ungültiger Wert wurde vom MQTT Broker empfangen - gültige Werte 0, 1, 2")

@thread_sicher
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
    """Wandelt Sekunden in das 4-Byte-Zeitfeld der 0x84-Befehle (little-endian)."""
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    if seconds > 0xFFFFFFFE:
        seconds = 0xFFFFFFFE
    return seconds.to_bytes(4, byteorder='little')

def callback_alarm(node_id, errors):
    """Veroeffentlicht die von der Anlage gemeldeten Stoerungen per MQTT.

    Sendet ERROR_COUNT und ERROR_TEXT; ohne anstehende Fehler 0 und Leerstring.
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
    """Fragt den Abwesenheitszustand zyklisch ab und veroeffentlicht ihn.

    Laeuft in einem eigenen Thread, weil die RMI-Abfrage blockiert.
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
    """Liest aus der Konfiguration, welche Sensoren abgewaehlt sind.

    Liefert die Menge der abgewaehlten pdids. Unbrauchbare Eintraege werden
    uebersprungen und protokolliert, damit ein Tippfehler nicht den Start verhindert.
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


class SnapshotSchreiber(logging.Handler):
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
                 max_zeilen=20000, max_dateien=5):
        super().__init__()
        self.verzeichnis = verzeichnis
        self.vorlauf = vorlauf
        self.nachlauf = nachlauf
        self.max_zeilen = max_zeilen
        self.max_dateien = max_dateien

        self.puffer = collections.deque()
        self.datei = None
        self.ende = 0
        self.anzahl_snapshots = 0
        self.letzter_snapshot = None

        # Letzter Schreibfehler, damit er in der Weboberflaeche sichtbar wird statt
        # nur im Log zu stehen (siehe emit()).
        self.fehler = None
        self._fehler_gemeldet = False

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
            elif record.levelno >= logging.ERROR:
                self._starten(jetzt, record.getMessage())

        except Exception as e:
            # Frueher stand hier ein blankes "pass". Das war falsch gedacht: Diese
            # Methode laeuft in jedem Thread, der etwas protokolliert, und darf
            # deshalb nichts nach oben durchlassen - aber sie darf den Fehler auch
            # nicht spurlos verschlucken. Genau das ist passiert: Es wurde kein
            # Bericht geschrieben, und es gab keinerlei Hinweis darauf, warum nicht.
            #
            # Ausgabe direkt auf stderr statt ueber den Logger: Von hier aus zu
            # protokollieren hiesse, waehrend der Zustellung einer Meldung eine neue
            # zu erzeugen. Was auf stderr geht, landet ueber wrapper.pl ohnehin in
            # derselben Logdatei.
            self.fehler = "%s: %s" % (type(e).__name__, e)
            if not self._fehler_gemeldet:
                self._fehler_gemeldet = True
                try:
                    sys.stderr.write(
                        "Log-Snapshot konnte nicht geschrieben werden (%s). "
                        "Ziel: %s\n" % (self.fehler, self.verzeichnis))
                    sys.stderr.flush()
                except Exception:
                    pass

    def _starten(self, jetzt, grund):
        os.makedirs(self.verzeichnis, exist_ok=True)
        name = os.path.join(
            self.verzeichnis,
            "snapshot_%s.log" % datetime.datetime.fromtimestamp(jetzt).strftime("%Y%m%d_%H%M%S")
        )
        # buffering=1 = zeilenweise schreiben. Wichtig fuer genau den Fall, fuer den
        # es diese Berichte gibt: Stuerzt der Prozess ab, wird nichts mehr
        # geschlossen und ein normaler Puffer waere verloren - der Bericht ueber den
        # Absturz waere leer. So steht jede Zeile sofort auf der Platte.
        self.datei = open(name, "w", encoding="utf-8", buffering=1)
        self.ende = jetzt + self.nachlauf
        self.letzter_snapshot = jetzt
        self.anzahl_snapshots += 1

        self.datei.write("Log-Snapshot - ausgelöst durch:\n  %s\n\n" % grund)
        self.datei.write("Die folgenden Zeilen umfassen etwa %d Sekunden davor und %d danach.\n"
                         % (self.vorlauf, self.nachlauf))
        self.datei.write("=" * 78 + "\n")
        for _, alt in self.puffer:
            self.datei.write(alt + "\n")

    def _schliessen(self):
        try:
            self.datei.write("=" * 78 + "\nEnde des Log-Snapshots.\n")
            self.datei.close()
        finally:
            self.datei = None
            self._aufraeumen()

    def _aufraeumen(self):
        """Behält nur die neuesten Berichte."""
        try:
            dateien = sorted(
                (os.path.join(self.verzeichnis, f) for f in os.listdir(self.verzeichnis)
                 if f.startswith("snapshot_") and f.endswith(".log")),
                key=os.path.getmtime, reverse=True
            )
            for alt in dateien[self.max_dateien:]:
                os.remove(alt)
        except Exception:
            pass


def fehlertext(e):
    """Liefert eine lesbare Beschreibung einer Ausnahme.

    Die Ausnahmen der Protokollschicht tragen meist keinen Text - dann bleibt
    nur der Klassenname.
    """
    text = str(e)
    return "%s: %s" % (type(e).__name__, text) if text else type(e).__name__

def to_seconds(value):
    """Wandelt eine Zeitangabe in ganze Sekunden.

    Loxone sendet Zahlen haeufig als "600.0"; int() allein wuerde daran scheitern.
    """
    return int(float(value))

@thread_sicher
def on_log(client, userdata, level, buf):
    _LOGGER.debug("Paho: " + buf)

def callback_sensor(var, value):
    # Jeder eintreffende Wert wird sofort veroeffentlicht, auch waehrend der
    # Anmeldung. Ein Sensor sendet erst, nachdem die Anlage sein Abonnement
    # bestaetigt hat - der Wert ist also gueltig.
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
    """Schreibt sekuendlich die Statusdatei fuer die Weboberflaeche.

    Laeuft in einem eigenen Thread. Fehler werden protokolliert und verschluckt -
    eine Anzeigefunktion darf den Betrieb nicht gefaehrden.
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
                if snapshotschreiber:
                    snapshotschreiber.anzahl_snapshots = 0
                    snapshotschreiber.letzter_snapshot = None
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
                    'snapshots': snapshotschreiber.anzahl_snapshots if snapshotschreiber else 0,
                    'letzter_snapshot': snapshotschreiber.letzter_snapshot if snapshotschreiber else None,

                    # Sensortabelle der Weboberflaeche. Als Zeichenkette, nicht als
                    # Zahl: In der Tabelle wird der Wert nur angezeigt, und so bleibt
                    # er exakt so stehen, wie er auch auf MQTT gegangen ist - ohne
                    # dass JSON aus 21.0 eine 21 macht.
                    'werte': {str(p): [str(w), t] for p, (w, t) in list(letzte_werte.items())},
                    'sensoren_aus': sorted(sensoren_aus),
                    'befehle': {k: [str(w), t, f] for k, (w, t, f) in list(letzte_befehle.items())},
                    'befehlsthemen': list(abonnierte_themen),

                    # Aktuell wirksame Zeitvorgaben. Wichtig, weil Loxone einen Wert
                    # nur bei AENDERUNG sendet: Nach einem Neustart des Plugins
                    # gelten wieder die Vorgaben, waehrend in Loxone noch die alte
                    # Zahl steht. Ohne diese Anzeige liesse sich nicht feststellen,
                    # mit welcher Dauer ein Boost oder Bypass tatsaechlich laeuft.
                    'zeiten': {
                        'BOOST_MODE_TIME': int.from_bytes(boost_mode_time, 'little'),
                        'BYPASS_ON_TIME': int.from_bytes(bypass_on_time, 'little'),
                        'BYPASS_OFF_TIME': int.from_bytes(bypass_off_time, 'little'),
                        'VENTMODE_STOP_SUPPLY_FAN_TIME': int.from_bytes(ventmode_stop_supply_fan_time, 'little'),
                        'VENTMODE_STOP_EXHAUST_FAN_TIME': int.from_bytes(ventmode_stop_exhaust_fan_time, 'little'),
                        'COMFOCOOL_OFF_TIME': comfocool_off_time,
                    },
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
                    laufend['snapshots'] = status['snapshots']
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
    """Veroeffentlicht SENSOR_TIMEOUT, wenn keine Sensordaten mehr eintreffen."""
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

    boost_mode_time = seconds_to_timerfield(900)            # 15 Minuten
    ventmode_stop_supply_fan_time = seconds_to_timerfield(3600)   # 1 Stunde
    ventmode_stop_exhaust_fan_time = seconds_to_timerfield(3600)  # 1 Stunde
    bypass_on_time = seconds_to_timerfield(3600)            # 1 Stunde
    bypass_off_time = seconds_to_timerfield(3600)           # 1 Stunde
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
    # am Logger vorbei. Folge: kein ERROR, kein Log-Snapshot, kein Zaehler, und
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

    # Dasselbe fuer den Haupt-Thread. Ohne das landet ein ungefangener Absturz nur
    # ueber stderr im Log (weil wrapper.pl es dorthin umleitet) - aber eben nicht als
    # Logmeldung. Folge: kein ERROR, kein Log-Snapshot, keine Vorgeschichte, und
    # der Traceback steht irgendwo zwischen den DEBUG-Zeilen statt am Ende einer
    # nachvollziehbaren Kette.
    #
    # KeyboardInterrupt ausgenommen: Das ist ein Abbruch von Hand, kein Fehler.
    def haupt_absturz(typ, wert, spur):
        if issubclass(typ, KeyboardInterrupt):
            sys.__excepthook__(typ, wert, spur)
            return
        _LOGGER.error(
            "Das Plugin ist abgestuerzt und beendet sich:\n%s"
            % "".join(traceback.format_exception(typ, wert, spur)).rstrip()
        )

    sys.excepthook = haupt_absturz

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
        
    # paho-mqtt ab 2.0 verlangt die Angabe der Rueckruf-Schnittstelle. Wir nutzen
    # weiterhin die alte (VERSION1); die Abfrage haelt aeltere paho-Versionen
    # lauffaehig, die das Argument nicht kennen.
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

    # Verbindungsaufbau mit mehreren Versuchen: Direkt nach einem Neustart des
    # LoxBerry ist das Netz manchmal noch nicht bereit.
    try:
        _LOGGER.info("Connecting to the " + local_name + " - PIN: " + str(pin))
        comfoconnect = ComfoConnect(bridge, local_uuid, local_name, pin)

    except Exception as e:
        _LOGGER.exception(str(e))

    comfoconnect.callback_sensor = callback_sensor
    comfoconnect.callback_alarm = callback_alarm

    # Sauberes Herunterfahren bei SIGTERM (wrapper.pl beendet mit pkill).
    # Meldet die Sitzung bei der Anlage ab, damit der naechste Start nicht auf eine
    # noch offene Sitzung trifft.
    def handle_sigterm(signum, frame):
        _LOGGER.info("SIGTERM empfangen - fahre sauber herunter (melde Session bei der Zehnder-Box ab)...")

        # Erst die Threads informieren, dann abmelden - sonst werten sie das Schliessen
        # der Verbindung als Ausfall und starten einen Wiederaufbau.
        comfoconnect.mark_disconnecting()

        try:
            if comfoconnect.is_connected():
                # Ueblicher Zeitrahmen. In der Praxis wartet das nie: Die Anlage beantwortet die
                # Abmeldung, indem sie die Verbindung schliesst.
                comfoconnect.cmd_close_session()
                _LOGGER.info("Session bei der Zehnder-Box abgemeldet.")
        except OSError as e:
            # Die Anlage schliesst die Verbindung meist sofort nach der Abmeldung. Dass sie
            # dabei wegbricht, ist also kein Fehler.
            _LOGGER.info("CloseSessionRequest gesendet, Bridge hat die Verbindung direkt danach getrennt (normal): " + str(e))
        except ValueError as e:
            # Hier kam gar keine Antwort und die Verbindung steht noch - ob die Sitzung
            # wirklich geschlossen wurde, ist offen. takeover beim naechsten Start regelt es.
            _LOGGER.warning("CloseSessionRequest gesendet, aber keine Bestätigung erhalten (Timeout) - Session evtl. noch offen, takeover beim nächsten Start übernimmt das: " + str(e))
        except Exception as e:
            _LOGGER.warning("Konnte Session bei der Zehnder-Box nicht sauber schließen: " + fehlertext(e))

        try:
            # Erst abmelden, dann den Netzwerk-Thread stoppen - sonst verlaesst das
            # DISCONNECT-Paket den Socket womoeglich nicht mehr.
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
                laufend['snapshots'] = snapshotschreiber.anzahl_snapshots if snapshotschreiber else 0
                langzeit.uebernehmen(laufend)
                langzeit.speichern(erzwingen=True)
            except Exception:
                pass

        _LOGGER.info("Sauber heruntergefahren.")

        # os._exit statt sys.exit: Zu diesem Zeitpunkt laeuft bereits Pythons eigene
        # Beendigung. Ein SystemExit daraus erzeugte nur einen irrefuehrenden Traceback;
        # aufzuraeumen gibt es nichts mehr.
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
                # os._exit statt exit: Der Verbindungs-Thread laeuft moeglicherweise schon und
                # wuerde den Prozess sonst am Leben halten.
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
            # Verbindung mitten in der Anmeldung verloren. Der Wiederaufbau im Hintergrund
            # uebernimmt - die noch nicht versuchten Sensoren werden hier vorgemerkt, sonst
            # wuerden sie dabei uebergangen.
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
        # Dieser erste Durchlauf laeuft im Hauptthread; spaetere Wiederholungen
        # uebernimmt der Verbindungs-Thread.
        comfoconnect.sensors_ready = True
        _LOGGER.info("Sensor-Registrierung abgeschlossen: %d von %d Sensoren registriert." % (len(comfoconnect.sensors_confirmed), len(sensor_ids)))

    # Reine Diagnoseabfragen - ein Aussetzer dabei darf den Start nicht verhindern.
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
    # macht aber den entscheidenden Unterschied für die Log-Snapshots:
    #
    # Ein Logger verwirft Meldungen unterhalb seines Levels sofort - sie entstehen
    # gar nicht erst und erreichen KEINEN Handler. Stand der LoxBerry also auf
    # "Fehler", lief der Ringpuffer des SnapshotSchreibers leer mit, und ein
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

    # Log-Snapshots (siehe SnapshotSchreiber). Bewusst am ROOT-Logger und nicht
    # an unserem eigenen: So werden auch die Meldungen der Bibliothek
    # (pycomfoconnect, eigener Logger "comfoconnect") mitgeschnitten - und gerade
    # die erklären eine Störung meistens.
    #
    # Der Handler bekommt dasselbe Format wie die Logdatei, damit ein Bericht
    # aussieht wie ein Ausschnitt daraus und sich direkt vergleichen lässt.
    global snapshotschreiber
    snapshotschreiber = None
    if snapshotdir:
        try:
            snapshotschreiber = SnapshotSchreiber(snapshotdir)
            snapshotschreiber.setFormatter(logging.Formatter(
                '%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s', datefmt='%H:%M:%S'))
            snapshotschreiber.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(snapshotschreiber)

            # Schreibbarkeit sofort pruefen, nicht erst im Fehlerfall. Sonst faellt
            # ein fehlendes Schreibrecht genau dann auf, wenn man den Bericht
            # braucht - und dann ist der Vorfall vorbei.
            probe = os.path.join(snapshotdir, ".schreibprobe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)

            logger.info("Log-Snapshots aktiv (ab Stufe FEHLER, %ds davor und %ds danach): %s"
                        % (snapshotschreiber.vorlauf, snapshotschreiber.nachlauf, snapshotdir))
        except Exception as e:
            snapshotschreiber = None
            logger.error("Log-Snapshots NICHT aktiv - Verzeichnis %s ist nicht beschreibbar (%s: %s)"
                         % (snapshotdir, type(e).__name__, e))
    else:
        # Ohne --snapshotdir gibt es keine Berichte. Das ist kein Fehler (beim
        # Suchlauf etwa gewollt), muss aber sichtbar sein - sonst wartet man
        # vergeblich auf Dateien, die nie entstehen koennen.
        logger.info("Log-Snapshots nicht aktiv (kein Ablageverzeichnis übergeben).")

    return logger

if __name__ == "__main__":
    main()
