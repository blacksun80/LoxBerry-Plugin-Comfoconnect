sensor_data = {
    16: {
        'NAME' : 'AWAY',
        'INFO' : 'Abwesenheitsanzeige: 1 = normale Stufe, 7 = abwesend'
    },
    49: {
        'NAME' : 'OPERATING_MODE_BIS',
        'INFO' : 'Betriebsart: 1 = Hand befristet, 5 = Hand unbefristet, 255 = Automatik'
    },
    56: {
        'NAME' : 'OPERATING_MODE',
        'INFO' : 'Betriebsart: 1 = Hand unbefristet, 255 = Automatik'
    },
    65: {
        'NAME' : 'FAN_SPEED_MODE',
        'CONV'  :   'str(%i)[-1:]',
        'INFO' : 'Eingestellte Lüfterstufe: 0 = abwesend, 1 = niedrig, 2 = mittel, 3 = hoch'
    },
    66: {
        'NAME' : 'BYPASS_MODE',
        'INFO' : 'Bypass-Vorgabe: 0 = Automatik, 1 = geöffnet, 2 = geschlossen'
    },
    67: {
        'NAME' : 'PROFILE_TEMPERATURE',
        'INFO' : 'Temperaturprofil: 0 = normal, 1 = kühl, 2 = warm'
    },
    70: {
        'NAME' : 'FAN_MODE_SUPPLY',
        'INFO' : 'Betriebsart Zuluftventilator'
    },
    71: {
        'NAME' : 'FAN_MODE_EXHAUST',
        'INFO' : 'Betriebsart Abluftventilator'
    },
    81: {
        'NAME' : 'FAN_NEXT_CHANGE',
        'PUSH'  :  2,
        'INFO' : 'Restzeit bis zum nächsten Wechsel der Lüfterstufe (Sekunden, -1 = kein Wechsel geplant)'
    },
    82: {
        'NAME' : 'BYPASS_NEXT_CHANGE',
        'PUSH'  :  2,
        'INFO' : 'Restzeit bis zur nächsten Bypass-Änderung (Sekunden, -1 = keine geplant)'
    },
    86: {
        'NAME' : 'SUPPLY_NEXT_CHANGE',
        'PUSH'  :  2,
        'INFO' : 'Restzeit, bis der Zuluftventilator wieder anläuft (Sekunden, -1 = keine)'
    },
    87: {
        'NAME' : 'EXHAUST_NEXT_CHANGE',
        'PUSH'  :  2,
        'INFO' : 'Restzeit, bis der Abluftventilator wieder anläuft (Sekunden, -1 = keine)'
    },
    117: {
        'NAME' : 'FAN_EXHAUST_DUTY',
        'PUSH'  :  3,
        'INFO' : 'Auslastung des Abluftventilators in Prozent'
    },
    118: {
        'NAME' : 'FAN_SUPPLY_DUTY',
        'PUSH'  :  3,
        'INFO' : 'Auslastung des Zuluftventilators in Prozent'
    },
    119: {
        'NAME' : 'FAN_EXHAUST_FLOW',
        'PUSH'  :  3,
        'INFO' : 'Abluftmenge in m³/h'
    },
    120: {
        'NAME' : 'FAN_SUPPLY_FLOW',
        'PUSH'  :  3,
        'INFO' : 'Zuluftmenge in m³/h'
    },
    121: {
        'NAME' : 'FAN_EXHAUST_SPEED',
        'PUSH'  :  3,
        'INFO' : 'Drehzahl des Abluftventilators in U/min'
    },
    122: {
        'NAME' : 'FAN_SUPPLY_SPEED',
        'PUSH'  :  3,
        'INFO' : 'Drehzahl des Zuluftventilators in U/min'
    },
    128: {
        'NAME' : 'POWER_CURRENT',
        'PUSH'  :  3,
        'INFO' : 'Aktuelle Leistungsaufnahme der Lüftung in Watt'
    },
    129: {
        'NAME' : 'POWER_TOTAL_YEAR',
        'PUSH'  :  3,
        'INFO' : 'Stromverbrauch der Lüftung im laufenden Jahr in kWh'
    },
    130: {
        'NAME' : 'POWER_TOTAL',
        'PUSH'  :  3,
        'INFO' : 'Stromverbrauch der Lüftung seit Inbetriebnahme in kWh'
    },
    144: {
        'NAME' : 'PREHEATER_POWER_TOTAL_YEAR',
        'PUSH'  :  3,
        'INFO' : 'Stromverbrauch des Vorheizregisters im laufenden Jahr in kWh'
    },
    145: {
        'NAME' : 'PREHEATER_POWER_TOTAL',
        'PUSH'  :  3,
        'INFO' : 'Stromverbrauch des Vorheizregisters seit Inbetriebnahme in kWh'
    },
    146: {
        'NAME' : 'PREHEATER_POWER_CURRENT',
        'PUSH'  :  3,
        'INFO' : 'Aktuelle Leistungsaufnahme des Vorheizregisters in Watt'
    },
    176: {
        'NAME' : 'SETTING_RF_PAIRING',
        'PUSH'  :  3,
        'INFO' : 'Zustand der Funk-Anlernung (Bedeutung im Protokoll nicht dokumentiert)'
    },
    192: {
        'NAME' : 'DAYS_TO_REPLACE_FILTER',
        'PUSH'  :  3,
        'INFO' : 'Verbleibende Tage bis zum Filterwechsel'
    },
    209: {
        'NAME' : 'CURRENT_RMOT',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Gleitender Außentemperatur-Mittelwert, Grundlage der Bypass-Regelung, in °C'
    },
    210: {
        'NAME' : 'HEATING_SEASON',
        'PUSH'  :  3,
        'INFO' : 'Heizperiode aktiv: 0 = nein, 1 = ja'
    },
    211: {
        'NAME' : 'COOLING_SEASON',
        'PUSH'  :  3,
        'INFO' : 'Kühlperiode aktiv: 0 = nein, 1 = ja'
    },
    212: {
        'NAME' : 'TARGET_TEMPERATURE',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Solltemperatur des eingestellten Temperaturprofils in °C'
    },
    213: {
        'NAME' : 'AVOIDED_HEATING_CURRENT',
        'PUSH'  :  3,
        'INFO' : 'Momentan eingesparte Heizleistung in Watt'
    },
    214: {
        'NAME' : 'AVOIDED_HEATING_TOTAL_YEAR',
        'PUSH'  :  3,
        'INFO' : 'Eingesparte Heizenergie im laufenden Jahr in kWh'
    },
    215: {
        'NAME' : 'AVOIDED_HEATING_TOTAL',
        'PUSH'  :  3,
        'INFO' : 'Eingesparte Heizenergie seit Inbetriebnahme in kWh'
    },
    216: {
        'NAME' : 'AVOIDED_COOLING_CURRENT',
        'PUSH'  :  3,
        'INFO' : 'Momentan eingesparte Kühlleistung in Watt'
    },
    217: {
        'NAME' : 'AVOIDED_COOLING_TOTAL_YEAR',
        'PUSH'  :  3,
        'INFO' : 'Eingesparte Kühlenergie im laufenden Jahr in kWh'
    },
    218: {
        'NAME' : 'AVOIDED_COOLING_TOTAL',
        'PUSH'  :  3,
        'INFO' : 'Eingesparte Kühlenergie seit Inbetriebnahme in kWh'
    },
    219: {
        'NAME' : 'AVOIDED_COOLING_CURRENT_TARGET',
        'PUSH'  :  3,
        'INFO' : 'Zielwert der Kühlrückgewinnung (Bedeutung im Protokoll nicht dokumentiert)'
    },
    221: {
        'NAME' : 'TEMPERATURE_SUPPLY',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Zulufttemperatur nach dem Nachheizregister in °C'
    },
    225: {
        'NAME' : 'COMFORTCONTROL_MODE',
        'INFO' : 'Betriebsart der Komfortregelung (Bedeutung im Protokoll nicht dokumentiert)'
    },
    227: {
        'NAME' : 'BYPASS_STATE',
        'INFO' : 'Tatsächlicher Bypass-Zustand: 0 = geschlossen, 100 = ganz geöffnet'
    },
    228: {
        'NAME' : 'FROSTPROTECT_UNBALANCE',
        'INFO' : 'Unwucht der Ventilatoren durch den Frostschutz (Bedeutung im Protokoll nicht dokumentiert)'
    },
    274: {
        'NAME' : 'TEMPERATURE_EXTRACT',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Ablufttemperatur, also die Raumtemperatur, in °C'
    },
    275: {
        'NAME' : 'TEMPERATURE_EXHAUST',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Fortlufttemperatur, also die nach draußen abgeführte Luft, in °C'
    },
    276: {
        'NAME' : 'TEMPERATURE_OUTDOOR',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Außentemperatur in °C'
    },
    277: {
        'NAME' : 'TEMPERATURE_AFTER_PREHEATER',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'INFO' : 'Außentemperatur nach dem Vorheizregister in °C'
    },
    290: {
        'NAME' : 'HUMIDITY_EXTRACT',
        'PUSH'  :  3,
        'INFO' : 'Luftfeuchte der Abluft, also im Raum, in Prozent'
    },
    291: {
        'NAME' : 'HUMIDITY_EXHAUST',
        'PUSH'  :  3,
        'INFO' : 'Luftfeuchte der Fortluft in Prozent'
    },
    292: {
        'NAME' : 'HUMIDITY_OUTDOOR',
        'PUSH'  :  3,
        'INFO' : 'Luftfeuchte der Außenluft in Prozent'
    },
    293: {
        'NAME' : 'HUMIDITY_AFTER_PREHEATER',
        'PUSH'  :  3,
        'INFO' : 'Luftfeuchte der Außenluft nach dem Vorheizregister in Prozent'
    },
    294: {
        'NAME' : 'HUMIDITY_SUPPLY',
        'PUSH'  :  3,
        'INFO' : 'Luftfeuchte der Zuluft in Prozent'
    },

    # ComfoCool (Kuehlmodul, optionales Zubehoer).
    #
    # 'ONLY_WITH_PRODUCT' bedeutet: nur registrieren, wenn sich ein Geraet mit
    # dieser Produkt-ID an der Anlage gemeldet hat (6 = ComfoCool, siehe
    # PRODUCT_ID_MAP in comfoconnect.py).
    #
    # Notwendig, weil die Anlage diese pdids AUCH OHNE angeschlossenes ComfoCool
    # anstandslos annimmt und mit 0 beantwortet - gemessen an einer Anlage ohne
    # Modul. Ohne diese Bremse bekaeme jeder Nutzer zwei Topics mit sinnlosen
    # Nullwerten, und man koennte am Verhalten der Anlage nicht erkennen, ob ein
    # ComfoCool vorhanden ist oder nicht.
    784: {
        'NAME' : 'COMFOCOOL_STATE',
        'ONLY_WITH_PRODUCT' : 6,
        'INFO' : 'Betriebszustand des ComfoCool: 0 = aus, 1 = kühlt'
    },
    802: {
        'NAME' : 'COMFOCOOL_TEMPERATURE_CONDENSOR',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3,
        'ONLY_WITH_PRODUCT' : 6,
        'INFO' : 'Kondensatortemperatur des ComfoCool in °C'
    },
    }