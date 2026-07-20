# Sensoren, die das Plugin von der Lueftungsanlage abonniert.
#
#   NAME    Name des Messwerts - zugleich das MQTT-Topic (hinter dem eingestellten
#           Praefix) und der Schluessel, unter dem der Wert in Loxone ankommt.
#   INFO    Klartextbeschreibung samt Einheit fuer die Sensorliste in der
#           Weboberflaeche. Rein informativ.
#   GRUPPE  Ueberschrift, unter der der Sensor in der Weboberflaeche einsortiert
#           wird. Die Reihenfolge der Gruppen ergibt sich aus dem ersten Auftreten
#           in dieser Datei - Eintraege einer Gruppe also beisammen lassen.
#   PUSH    Mindestabstand in Sekunden zwischen zwei Sendungen desselben Werts.
#           Ohne Angabe wird jede Aenderung sofort weitergegeben.
#   CONV    Umrechnung des Rohwerts, z.B. "%i / 10" fuer Zehntelgrad.
#
# Zubehoer (ComfoCool, ComfoFond, Optionsbox) steht in eigenen Gruppen. Fehlt das
# Geraet, nimmt die Anlage die Anmeldung trotzdem an und antwortet mit 0 - wen der
# nichtssagende Wert stoert, waehlt die Gruppe in den Einstellungen ab.
#
# Ein zusaetzlicher Messwert braucht einen Eintrag HIER - ueber die Weboberflaeche
# laesst sich nur an- und abwaehlen, nichts ergaenzen. Grund: Der Rohwert wird nach
# Byte-Laenge dekodiert, nicht nach PDO-Typ (siehe _handle_rpdo_notification in
# comfoconnect.py). Vierbyte-Werte kaemen als Hex-Zeichenkette an - deshalb fehlen
# hier bewusst die pdids 230, 338, 342 und 343, die die Referenzbibliothek zwar
# kennt, die wir aber nicht sinnvoll uebertragen koennten.
#
# Jede pdid braucht zusaetzlich einen Eintrag in RPDO_TYPE_MAP (comfoconnect.py),
# sonst lehnt register_sensor() sie ab.

sensor_data = {

    # ---- Betrieb und Lüfterstufe -----------------------------------
    16: {
        'NAME' : 'AWAY',
        'INFO' : 'Abwesenheitsanzeige: 1 = normale Stufe, 7 = abwesend',
        'GRUPPE' : 'Betrieb und Lüfterstufe'
    },
    49: {
        'NAME' : 'OPERATING_MODE_BIS',
        'INFO' : 'Betriebsart: 1 = Hand befristet, 5 = Hand unbefristet, 255 = Automatik',
        'GRUPPE' : 'Betrieb und Lüfterstufe'
    },
    56: {
        'NAME' : 'OPERATING_MODE',
        'INFO' : 'Betriebsart: 1 = Hand unbefristet, 255 = Automatik',
        'GRUPPE' : 'Betrieb und Lüfterstufe'
    },
    65: {
        'NAME' : 'FAN_SPEED_MODE',
        'INFO' : 'Eingestellte Lüfterstufe: 0 = abwesend, 1 = niedrig, 2 = mittel, 3 = hoch',
        'GRUPPE' : 'Betrieb und Lüfterstufe',
        'CONV' : "str(%i)[-1:]"
    },
    67: {
        'NAME' : 'PROFILE_TEMPERATURE',
        'INFO' : 'Temperaturprofil: 0 = normal, 1 = kühl, 2 = warm',
        'GRUPPE' : 'Betrieb und Lüfterstufe'
    },
    225: {
        'NAME' : 'COMFORTCONTROL_MODE',
        'INFO' : 'Betriebsart der sensorgeführten Lüftung - gehört zu den Befehlen SENSOR_TEMP, SENSOR_HUMC und SENSOR_HUMP',
        'GRUPPE' : 'Betrieb und Lüfterstufe'
    },
    226: {
        'NAME' : 'FAN_SPEED_MODULATED',
        'INFO' : 'Modulierende Lüfterstufe, feiner abgestuft als FAN_SPEED_MODE',
        'GRUPPE' : 'Betrieb und Lüfterstufe',
        'PUSH' : 3
    },
    81: {
        'NAME' : 'FAN_NEXT_CHANGE',
        'INFO' : 'Restzeit bis zum nächsten Wechsel der Lüfterstufe (Sekunden, -1 = kein Wechsel geplant)',
        'GRUPPE' : 'Betrieb und Lüfterstufe',
        'PUSH' : 2
    },

    # ---- Ventilatoren ----------------------------------------------
    70: {
        'NAME' : 'FAN_MODE_SUPPLY',
        'INFO' : 'Betriebsart Zuluftventilator',
        'GRUPPE' : 'Ventilatoren'
    },
    71: {
        'NAME' : 'FAN_MODE_EXHAUST',
        'INFO' : 'Betriebsart Abluftventilator',
        'GRUPPE' : 'Ventilatoren'
    },
    54: {
        'NAME' : 'FAN_MODE_SUPPLY_2',
        'INFO' : 'Betriebsart Zuluftventilator (zweite Meldestelle der Anlage)',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    55: {
        'NAME' : 'FAN_MODE_EXHAUST_2',
        'INFO' : 'Betriebsart Abluftventilator (zweite Meldestelle der Anlage)',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    86: {
        'NAME' : 'SUPPLY_NEXT_CHANGE',
        'INFO' : 'Restzeit, bis der Zuluftventilator wieder anläuft (Sekunden, -1 = keine)',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 2
    },
    87: {
        'NAME' : 'EXHAUST_NEXT_CHANGE',
        'INFO' : 'Restzeit, bis der Abluftventilator wieder anläuft (Sekunden, -1 = keine)',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 2
    },
    117: {
        'NAME' : 'FAN_EXHAUST_DUTY',
        'INFO' : 'Auslastung des Abluftventilators in Prozent',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    118: {
        'NAME' : 'FAN_SUPPLY_DUTY',
        'INFO' : 'Auslastung des Zuluftventilators in Prozent',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    119: {
        'NAME' : 'FAN_EXHAUST_FLOW',
        'INFO' : 'Abluftmenge in m³/h',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    120: {
        'NAME' : 'FAN_SUPPLY_FLOW',
        'INFO' : 'Zuluftmenge in m³/h',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    121: {
        'NAME' : 'FAN_EXHAUST_SPEED',
        'INFO' : 'Drehzahl des Abluftventilators in U/min',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },
    122: {
        'NAME' : 'FAN_SUPPLY_SPEED',
        'INFO' : 'Drehzahl des Zuluftventilators in U/min',
        'GRUPPE' : 'Ventilatoren',
        'PUSH' : 3
    },

    # ---- Temperaturen ----------------------------------------------
    209: {
        'NAME' : 'CURRENT_RMOT',
        'INFO' : 'Gleitender Außentemperatur-Mittelwert, Grundlage der Bypass-Regelung, in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    212: {
        'NAME' : 'TARGET_TEMPERATURE',
        'INFO' : 'Solltemperatur des eingestellten Temperaturprofils in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    221: {
        'NAME' : 'TEMPERATURE_SUPPLY',
        'INFO' : 'Zulufttemperatur nach dem Nachheizregister in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    274: {
        'NAME' : 'TEMPERATURE_EXTRACT',
        'INFO' : 'Ablufttemperatur, also die Raumtemperatur, in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    275: {
        'NAME' : 'TEMPERATURE_EXHAUST',
        'INFO' : 'Fortlufttemperatur, also die nach draußen abgeführte Luft, in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    276: {
        'NAME' : 'TEMPERATURE_OUTDOOR',
        'INFO' : 'Außentemperatur in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    277: {
        'NAME' : 'TEMPERATURE_AFTER_PREHEATER',
        'INFO' : 'Außentemperatur nach dem Vorheizregister in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    220: {
        'NAME' : 'TEMPERATURE_OUTDOOR_2',
        'INFO' : 'Außentemperatur, zweite Meldestelle der Anlage, in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    278: {
        'NAME' : 'TEMPERATURE_SUPPLY_2',
        'INFO' : 'Zulufttemperatur, zweite Meldestelle der Anlage, in °C',
        'GRUPPE' : 'Temperaturen',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },

    # ---- Luftfeuchte -----------------------------------------------
    290: {
        'NAME' : 'HUMIDITY_EXTRACT',
        'INFO' : 'Luftfeuchte der Abluft, also im Raum, in Prozent',
        'GRUPPE' : 'Luftfeuchte',
        'PUSH' : 3
    },
    291: {
        'NAME' : 'HUMIDITY_EXHAUST',
        'INFO' : 'Luftfeuchte der Fortluft in Prozent',
        'GRUPPE' : 'Luftfeuchte',
        'PUSH' : 3
    },
    292: {
        'NAME' : 'HUMIDITY_OUTDOOR',
        'INFO' : 'Luftfeuchte der Außenluft in Prozent',
        'GRUPPE' : 'Luftfeuchte',
        'PUSH' : 3
    },
    293: {
        'NAME' : 'HUMIDITY_AFTER_PREHEATER',
        'INFO' : 'Luftfeuchte der Außenluft nach dem Vorheizregister in Prozent',
        'GRUPPE' : 'Luftfeuchte',
        'PUSH' : 3
    },
    294: {
        'NAME' : 'HUMIDITY_SUPPLY',
        'INFO' : 'Luftfeuchte der Zuluft in Prozent',
        'GRUPPE' : 'Luftfeuchte',
        'PUSH' : 3
    },

    # ---- Bypass und Jahreszeit -------------------------------------
    66: {
        'NAME' : 'BYPASS_MODE',
        'INFO' : 'Bypass-Vorgabe: 0 = Automatik, 1 = geöffnet, 2 = geschlossen',
        'GRUPPE' : 'Bypass und Jahreszeit'
    },
    82: {
        'NAME' : 'BYPASS_NEXT_CHANGE',
        'INFO' : 'Restzeit bis zur nächsten Bypass-Änderung (Sekunden, -1 = keine geplant)',
        'GRUPPE' : 'Bypass und Jahreszeit',
        'PUSH' : 2
    },
    227: {
        'NAME' : 'BYPASS_STATE',
        'INFO' : 'Tatsächlicher Bypass-Zustand: 0 = geschlossen, 100 = ganz geöffnet',
        'GRUPPE' : 'Bypass und Jahreszeit'
    },
    210: {
        'NAME' : 'HEATING_SEASON',
        'INFO' : 'Heizperiode aktiv: 0 = nein, 1 = ja',
        'GRUPPE' : 'Bypass und Jahreszeit',
        'PUSH' : 3
    },
    211: {
        'NAME' : 'COOLING_SEASON',
        'INFO' : 'Kühlperiode aktiv: 0 = nein, 1 = ja',
        'GRUPPE' : 'Bypass und Jahreszeit',
        'PUSH' : 3
    },

    # ---- Stromverbrauch --------------------------------------------
    128: {
        'NAME' : 'POWER_CURRENT',
        'INFO' : 'Aktuelle Leistungsaufnahme der Lüftung in Watt',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },
    129: {
        'NAME' : 'POWER_TOTAL_YEAR',
        'INFO' : 'Stromverbrauch der Lüftung im laufenden Jahr in kWh',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },
    130: {
        'NAME' : 'POWER_TOTAL',
        'INFO' : 'Stromverbrauch der Lüftung seit Inbetriebnahme in kWh',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },
    146: {
        'NAME' : 'PREHEATER_POWER_CURRENT',
        'INFO' : 'Aktuelle Leistungsaufnahme des Vorheizregisters in Watt',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },
    144: {
        'NAME' : 'PREHEATER_POWER_TOTAL_YEAR',
        'INFO' : 'Stromverbrauch des Vorheizregisters im laufenden Jahr in kWh',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },
    145: {
        'NAME' : 'PREHEATER_POWER_TOTAL',
        'INFO' : 'Stromverbrauch des Vorheizregisters seit Inbetriebnahme in kWh',
        'GRUPPE' : 'Stromverbrauch',
        'PUSH' : 3
    },

    # ---- Eingesparte Energie ---------------------------------------
    213: {
        'NAME' : 'AVOIDED_HEATING_CURRENT',
        'INFO' : 'Momentan eingesparte Heizleistung in Watt',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    214: {
        'NAME' : 'AVOIDED_HEATING_TOTAL_YEAR',
        'INFO' : 'Eingesparte Heizenergie im laufenden Jahr in kWh',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    215: {
        'NAME' : 'AVOIDED_HEATING_TOTAL',
        'INFO' : 'Eingesparte Heizenergie seit Inbetriebnahme in kWh',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    216: {
        'NAME' : 'AVOIDED_COOLING_CURRENT',
        'INFO' : 'Momentan eingesparte Kühlleistung in Watt',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    217: {
        'NAME' : 'AVOIDED_COOLING_TOTAL_YEAR',
        'INFO' : 'Eingesparte Kühlenergie im laufenden Jahr in kWh',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    218: {
        'NAME' : 'AVOIDED_COOLING_TOTAL',
        'INFO' : 'Eingesparte Kühlenergie seit Inbetriebnahme in kWh',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },
    219: {
        'NAME' : 'AVOIDED_COOLING_CURRENT_TARGET',
        'INFO' : 'Bedeutung unbekannt - weder im Zehnder-Protokoll noch in der Referenzbibliothek benannt. Der Name hier ist geraten',
        'GRUPPE' : 'Eingesparte Energie',
        'PUSH' : 3
    },

    # ---- Filter und Frostschutz ------------------------------------
    18: {
        'NAME' : 'FILTER_CHANGING',
        'INFO' : 'Filterwechsel läuft gerade: 0 = nein, 1 = ja',
        'GRUPPE' : 'Filter und Frostschutz',
        'PUSH' : 3
    },
    192: {
        'NAME' : 'DAYS_TO_REPLACE_FILTER',
        'INFO' : 'Verbleibende Tage bis zum Filterwechsel',
        'GRUPPE' : 'Filter und Frostschutz',
        'PUSH' : 3
    },
    228: {
        'NAME' : 'FROSTPROTECT_UNBALANCE',
        'INFO' : 'Unwucht der Ventilatoren durch den Frostschutz - Bedeutung der Werte weder im Protokoll noch in der Referenzbibliothek beschrieben',
        'GRUPPE' : 'Filter und Frostschutz'
    },

    # ---- Geräteeinstellungen ---------------------------------------
    208: {
        'NAME' : 'UNIT_TEMPERATURE',
        'INFO' : 'Temperatureinheit der Anlage: 0 = Celsius, 1 = Fahrenheit',
        'GRUPPE' : 'Geräteeinstellungen',
        'PUSH' : 3
    },
    224: {
        'NAME' : 'UNIT_AIRFLOW',
        'INFO' : 'Einheit des Luftvolumenstroms: 3 = m³/h, sonst l/s',
        'GRUPPE' : 'Geräteeinstellungen',
        'PUSH' : 3
    },
    176: {
        'NAME' : 'SETTING_RF_PAIRING',
        'INFO' : 'Zustand der Funk-Anlernung, etwa beim Verbinden einer Fernbedienung',
        'GRUPPE' : 'Geräteeinstellungen',
        'PUSH' : 3
    },

    # ---- ComfoCool (Kühlmodul) -------------------------------------
    784: {
        'NAME' : 'COMFOCOOL_STATE',
        'INFO' : 'Betriebszustand des ComfoCool: 0 = aus, 1 = kühlt',
        'GRUPPE' : 'ComfoCool (Kühlmodul)'
    },
    785: {
        'NAME' : 'COMFOCOOL_COMPRESSOR',
        'INFO' : 'ComfoCool: Verdichter läuft: 0 = nein, 1 = ja',
        'GRUPPE' : 'ComfoCool (Kühlmodul)',
        'PUSH' : 3
    },
    802: {
        'NAME' : 'COMFOCOOL_TEMPERATURE_CONDENSOR',
        'INFO' : 'Kondensatortemperatur des ComfoCool in °C',
        'GRUPPE' : 'ComfoCool (Kühlmodul)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },

    # ---- ComfoFond (Erdwärmetauscher) ------------------------------
    416: {
        'NAME' : 'COMFOFOND_TEMPERATURE_OUTDOOR',
        'INFO' : 'ComfoFond: Außentemperatur in °C - nur mit Erdwärmetauscher',
        'GRUPPE' : 'ComfoFond (Erdwärmetauscher)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    417: {
        'NAME' : 'COMFOFOND_TEMPERATURE_GROUND',
        'INFO' : 'ComfoFond: Erdreichtemperatur in °C - nur mit Erdwärmetauscher',
        'GRUPPE' : 'ComfoFond (Erdwärmetauscher)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    418: {
        'NAME' : 'COMFOFOND_GHE_STATE',
        'INFO' : 'ComfoFond: Auslastung des Erdwärmetauschers in Prozent',
        'GRUPPE' : 'ComfoFond (Erdwärmetauscher)',
        'PUSH' : 3
    },
    419: {
        'NAME' : 'COMFOFOND_PRESENT',
        'INFO' : 'ComfoFond: Erdwärmetauscher vorhanden: 0 = nein, 1 = ja',
        'GRUPPE' : 'ComfoFond (Erdwärmetauscher)',
        'PUSH' : 3
    },

    # ---- Optionsbox (Analogeingänge) -------------------------------
    369: {
        'NAME' : 'ANALOG_INPUT_1',
        'INFO' : 'Analogeingang 1 der Optionsbox in Volt',
        'GRUPPE' : 'Optionsbox (Analogeingänge)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    370: {
        'NAME' : 'ANALOG_INPUT_2',
        'INFO' : 'Analogeingang 2 der Optionsbox in Volt',
        'GRUPPE' : 'Optionsbox (Analogeingänge)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    371: {
        'NAME' : 'ANALOG_INPUT_3',
        'INFO' : 'Analogeingang 3 der Optionsbox in Volt',
        'GRUPPE' : 'Optionsbox (Analogeingänge)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
    372: {
        'NAME' : 'ANALOG_INPUT_4',
        'INFO' : 'Analogeingang 4 der Optionsbox in Volt',
        'GRUPPE' : 'Optionsbox (Analogeingänge)',
        'CONV' : "%i / 10",
        'PUSH' : 3
    },
}
