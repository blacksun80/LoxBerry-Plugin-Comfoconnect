# API contants

FAN_MODE_AWAY = 'away'
FAN_MODE_LOW = 'low'
FAN_MODE_MEDIUM = 'medium'
FAN_MODE_HIGH = 'high'

# Commands
CMD_FAN_MODE_AWAY                   = b'\x84\x15\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00\x00'
CMD_FAN_MODE_LOW                    = b'\x84\x15\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00\x01'
CMD_FAN_MODE_MEDIUM                 = b'\x84\x15\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00\x02'
CMD_FAN_MODE_HIGH                   = b'\x84\x15\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00\x03'
CMD_MODE_AUTO                       = b'\x85\x15\x08\x01'                                       #AUTO !!!
CMD_MODE_MANUAL                     = b'\x84\x15\x08\x01\x00\x00\x00\x00\x01\x00\x00\x00\x01'   # MANUAL !!!
CMD_START_SUPPLY_FAN                = b'\x85\x15\x07\x01'
CMD_START_EXHAUST_FAN               = b'\x85\x15\x06\x01'
CMD_TEMPPROF_NORMAL                 = b'\x84\x15\x03\x01\x00\x00\x00\x00\xff\xff\xff\xff\x00'
CMD_TEMPPROF_COOL                   = b'\x84\x15\x03\x01\x00\x00\x00\x00\xff\xff\xff\xff\x01'
CMD_TEMPPROF_WARM                   = b'\x84\x15\x03\x01\x00\x00\x00\x00\xff\xff\xff\xff\x02'
CMD_BYPASS_ON                       = b'\x84\x15\x02\x01\x00\x00\x00\x00\x10\x0e\x00\x00\x01'
CMD_BYPASS_OFF                      = b'\x84\x15\x02\x01\x00\x00\x00\x00\x10\x0e\x00\x00\x02'
CMD_BYPASS_AUTO                     = b'\x85\x15\x02\x01'
CMD_SENSOR_TEMP_OFF                 = b'\x03\x1d\x01\x04\x00'
CMD_SENSOR_TEMP_AUTO                = b'\x03\x1d\x01\x04\x01'
CMD_SENSOR_TEMP_ON                  = b'\x03\x1d\x01\x04\x02'
CMD_SENSOR_HUMC_OFF                 = b'\x03\x1d\x01\x06\x00'
CMD_SENSOR_HUMC_AUTO                = b'\x03\x1d\x01\x06\x01'
CMD_SENSOR_HUMC_ON                  = b'\x03\x1d\x01\x06\x02'
CMD_SENSOR_HUMP_OFF                 = b'\x03\x1d\x01\x07\x00'
CMD_SENSOR_HUMP_AUTO                = b'\x03\x1d\x01\x07\x01'
CMD_SENSOR_HUMP_ON                  = b'\x03\x1d\x01\x07\x02'
CMD_READ_CONFIG                     = b'\x87\x15\x01'
CMD_READ_HRU                        = b'\x01\x01\x01\x10\x08'
CMD_BOOST_MODE_END                  = b'\x85\x15\x01\x06'

# Sensor locations
SENSOR_AWAY = 16
SENSOR_OPERATING_MODE_BIS = 49
SENSOR_OPERATING_MODE = 56
SENSOR_FAN_SPEED_MODE = 65
SENSOR_BYPASS_MODE = 66
SENSOR_PROFILE_TEMPERATURE = 67
SENSOR_FAN_MODE_SUPPLY = 70
SENSOR_FAN_MODE_EXHAUST = 71
SENSOR_FAN_TIME = 81
SENSOR_BYPASS_TIME = 82
SENSOR_SUPPLY_TIME = 86
SENSOR_EXHAUST_TIME = 87
SENSOR_FAN_EXHAUST_DUTY = 117
SENSOR_FAN_SUPPLY_DUTY = 118
SENSOR_FAN_SUPPLY_FLOW = 119
SENSOR_FAN_EXHAUS_FLOW = 120
SENSOR_FAN_EXHAUST_SPEED = 121
SENSOR_FAN_SUPPLY_SPEED = 122
SENSOR_POWER_CURRENT = 128
SENSOR_POWER_TOTAL_YEAR = 129
SENSOR_POWER_TOTAL = 130
SENSOR_PREHEATER_POWER_TOTAL_YEAR = 144
SENSOR_PREHEATER_POWER_TOTAL = 145
SENSOR_PREHEATER_POWER_CURRENT = 146
SENSOR_SETTING_RF_PAIRING = 176
SENSOR_DAYS_TO_REPLACE_FILTER = 192
SENSOR_CURRENT_RMOT = 209
SENSOR_HEATING_SEASON = 210
SENSOR_COOLING_SEASON = 211
SENSOR_TARGET_TEMPERATURE = 212
SENSOR_AVOIDED_HEATING_CURRENT = 213
SENSOR_AVOIDED_HEATING_TOTAL_YEAR = 214
SENSOR_AVOIDED_HEATING_TOTAL = 215
SENSOR_AVOIDED_COOLING_CURRENT = 216
SENSOR_AVOIDED_COOLING_YEAR = 217
SENSOR_AVOIDED_COOLING_TOTAL = 218
SENSOR_AVOIDED_COOLING_CURRENT_TARGET = 219
SENSOR_TEMPERATURE_SUPPLY = 221
SENSOR_COMFORTCONTROL_MODE = 225
SENSOR_BYPASS_STATE = 227
SENSOR_FROSTPROTECTION_UNBALANCE = 228
SENSOR_TEMPERATURE_EXTRACT = 274
SENSOR_TEMPERATURE_EXHAUST = 275
SENSOR_TEMPERATURE_OUTDOOR = 276
SENSOR_TEMPERATURE_AFTER_PREHEATER = 277
SENSOR_HUMIDITY_EXTRACT = 290
SENSOR_HUMIDITY_EXHAUST = 291
SENSOR_HUMIDITY_OUTDOOR = 292
SENSOR_HUMIDITY_AFTER_PREHEATER = 293
SENSOR_HUMIDITY_SUPPLY = 294

# ======================================================================================
# Fehlermeldungen im Klartext
# ======================================================================================
# Die Anlage schickt in der CnAlarmNotification ein 32-Byte-Bitfeld ("errors"). Jedes
# gesetzte Bit steht fuer einen Fehler, die Bitnummer ist der Schluessel hier. Gezaehlt
# wird innerhalb jedes Bytes vom niederwertigsten Bit aufwaerts, also
# Bitnummer = Byte-Index * 8 + Bit-Index.
#
# Gegengerechnet an einem echten Alarm dieser Anlage: Byte 6 = 0x20 (Bit 5 gesetzt)
# ergibt Bitnummer 53 - und genau 53 steht auch im separaten Feld "errorId" derselben
# Nachricht.
#
# ACHTUNG: Ab Bitnummer 70 haben sich die Bedeutungen mit Firmware 1.4.0 verschoben.
# Welche Tabelle gilt, entscheidet swProgramVersion (siehe alarm_errors_to_text).
# Quelle: aiocomfoconnect (michaelarnauts).

ALARM_ERRORS_BASE = {
    21: "GEFAHR! ÜBERHITZUNG! Zwei oder mehr Sensoren messen eine falsche Temperatur. Die Lüftung wurde gestoppt.",
    22: "Temperatur zu hoch für die Lüftungsanlage (TEMP_HRU ERROR)",
    23: "Der Ablufttemperaturfühler hat eine Störung (SENSOR_ETA ERROR)",
    24: "Der Ablufttemperaturfühler misst eine falsche Temperatur (TEMP_SENSOR_ETA ERROR)",
    25: "Der Fortlufttemperaturfühler hat eine Störung (SENSOR_EHA ERROR)",
    26: "Der Fortlufttemperaturfühler misst eine falsche Temperatur (TEMP_SENSOR_EHA ERROR)",
    27: "Der Außenlufttemperaturfühler hat eine Störung (SENSOR_ODA ERROR)",
    28: "Der Außenlufttemperaturfühler misst eine falsche Temperatur (TEMP_SENSOR_ODA ERROR)",
    29: "Der Temperaturfühler für vorkonditionierte Außenluft hat eine Störung",
    30: "Der Temperaturfühler für vorkonditionierte Außenluft misst eine falsche Temperatur (TEMP_SENSOR_P-ODA ERROR)",
    31: "Der Zulufttemperaturfühler hat eine Störung (SENSOR_SUP ERROR)",
    32: "Der Zulufttemperaturfühler misst eine falsche Temperatur (TEMP_SENSOR_SUP ERROR)",
    33: "Die Lüftungsanlage wurde nicht in Betrieb genommen (INIT ERROR)",
    34: "Die Fronttür ist offen",
    35: "Das Vorheizregister ist vorhanden, sitzt aber nicht an der richtigen Position (rechts/links) (PREHEAT_LOCATION ERROR)",
    37: "Das Vorheizregister hat eine Störung (PREHEAT ERROR)",
    38: "Das Vorheizregister hat eine Störung (PREHEAT ERROR)",
    39: "Der Abluftfeuchtefühler hat eine Störung (SENSOR_ETA ERROR)",
    41: "Der Fortluftfeuchtefühler hat eine Störung (SENSOR_EHA ERROR)",
    43: "Der Außenluftfeuchtefühler hat eine Störung (SENSOR_ODA ERROR)",
    45: "Der Außenluftfeuchtefühler hat eine Störung (SENSOR_P-ODA ERROR)",
    47: "Der Zuluftfeuchtefühler hat eine Störung (SENSOR_SUP ERROR)",
    49: "Der Fortluft-Volumenstromsensor hat eine Störung (SENSOR_EHA ERROR)",
    50: "Der Zuluft-Volumenstromsensor hat eine Störung (SENSOR_SUP ERROR)",
    51: "Der Abluftventilator hat eine Störung (FAN_EHA ERROR)",
    52: "Der Zuluftventilator hat eine Störung (FAN_SUP ERROR)",
    53: "Fortluftdruck zu hoch. Luftauslässe, Kanäle und Filter auf Verschmutzung und Verstopfung prüfen, Ventileinstellungen kontrollieren (EXT_PRESSURE_EHA ERROR)",
    54: "Zuluftdruck zu hoch. Luftauslässe, Kanäle und Filter auf Verschmutzung und Verstopfung prüfen, Ventileinstellungen kontrollieren (EXT_PRESSURE_SUP ERROR)",
    55: "Der Abluftventilator hat eine Störung (FAN_EHA ERROR)",
    56: "Der Zuluftventilator hat eine Störung (FAN_SUP ERROR)",
    57: "Der Fortluftvolumenstrom erreicht seinen Sollwert nicht (AIRFLOW_EHA ERROR)",
    58: "Der Zuluftvolumenstrom erreicht seinen Sollwert nicht (AIRFLOW_SUP ERROR)",
    59: "Die geforderte Temperatur für Außenluft nach dem Vorheizregister wurde zu oft nicht erreicht (TEMPCONTROL_P-ODA ERROR)",
    60: "Die geforderte Zulufttemperatur wurde zu oft nicht erreicht. Der modulierende Bypass hat möglicherweise eine Störung (TEMPCONTROL_SUP ERROR)",
    61: "Die Zulufttemperatur ist zu oft zu niedrig (TEMP_SUP_MIN ERROR)",
    62: "Es kam im vergangenen Zeitraum zu oft zu einer Unwucht außerhalb der Toleranz (UNBALANCE ERROR)",
    63: "Das Nachheizregister war vorhanden, wird aber nicht mehr erkannt (POSTHEAT_CONNECT ERROR)",
    64: "Der Grenzwert des Zulufttemperaturfühlers am ComfoCool wurde zu oft überschritten (CCOOL_TEMP ERROR)",
    65: "Der Raumtemperaturfühler war vorhanden, wird aber nicht mehr erkannt (T_ROOM_PRES ERROR)",
    66: "Die Funk-Hardware war vorhanden, wird aber nicht mehr erkannt (RF_PRES ERROR)",
    67: "Die Option Box war vorhanden, wird aber nicht mehr erkannt (OPTION_BOX CONNECT ERROR)",
    68: "Das Vorheizregister war vorhanden, wird aber nicht mehr erkannt (PREHEAT_PRES ERROR)",
    69: "Das Nachheizregister war vorhanden, wird aber nicht mehr erkannt (POSTHEAT_CONNECT ERROR)",
}

# Firmware neuer als 1.4.0
ALARM_ERRORS = dict(ALARM_ERRORS_BASE)
ALARM_ERRORS.update({
    70: "Analogeingang 1 war vorhanden, wird aber nicht mehr erkannt (ANALOG_1_PRES ERROR)",
    71: "Analogeingang 2 war vorhanden, wird aber nicht mehr erkannt (ANALOG_2_PRES ERROR)",
    72: "Analogeingang 3 war vorhanden, wird aber nicht mehr erkannt (ANALOG_3_PRES ERROR)",
    73: "Analogeingang 4 war vorhanden, wird aber nicht mehr erkannt (ANALOG_4_PRES ERROR)",
    74: "Die ComfoHood war vorhanden, wird aber nicht mehr erkannt (HOOD_CONNECT ERROR)",
    75: "Das ComfoCool war vorhanden, wird aber nicht mehr erkannt (CCOOL_CONNECT ERROR)",
    76: "Das ComfoFond war vorhanden, wird aber nicht mehr erkannt (GROUND_HEAT_CONNECT ERROR)",
    77: "Die Filter der Lüftungsanlage müssen jetzt gewechselt werden",
    78: "Der externe Filter muss ersetzt oder gereinigt werden",
    79: "Neue Filter bestellen - die Restlaufzeit der Filter ist begrenzt",
    80: "Der Servicemodus ist aktiv (SERVICE MODE)",
    81: "Das Vorheizregister hat keine Verbindung zur Lüftungsanlage (PREHEAT ERROR, 1081)",
    82: "ComfoHood-Temperaturfehler (HOOD_TEMP ERROR)",
    83: "Nachheizregister-Temperaturfehler (POSTHEAT_TEMP ERROR)",
    84: "Außentemperaturfehler des ComfoFond (GROUND_HEAT_TEMP ERROR)",
    85: "Fehler Analogeingang 1 (ANALOG_1_IN ERROR)",
    86: "Fehler Analogeingang 2 (ANALOG_2_IN ERROR)",
    87: "Fehler Analogeingang 3 (ANALOG_3_IN ERROR)",
    88: "Fehler Analogeingang 4 (ANALOG_4_IN ERROR)",
    89: "Der Bypass ist im Handbetrieb",
    90: "Das ComfoCool überhitzt",
    91: "ComfoCool-Kompressorfehler (CCOOL_COMPRESSOR ERROR)",
    92: "ComfoCool-Raumtemperaturfühler defekt (CCOOL_TEMP ERROR)",
    93: "ComfoCool-Kondensatortemperaturfühler defekt (CCOOL_TEMP ERROR)",
    94: "ComfoCool-Zulufttemperaturfühler defekt (CCOOL_TEMP ERROR)",
    95: "Die ComfoHood-Temperatur ist zu hoch (HOOD_TEMP ERROR)",
    96: "Die ComfoHood ist aktiviert",
    97: "QM_Constraint_min_ERR (unbekannter Fehler)",
    98: "H_21_qm_min_ERR (unbekannter Fehler)",
    99: "Konfigurationsfehler",
    100: "Fehleranalyse läuft ...",
    101: "ComfoNet-Fehler",
    102: "Die Anzahl der CO2-Sensoren hat abgenommen - ein oder mehrere Sensoren werden nicht mehr erkannt",
    103: "Mehr als 8 Sensoren in einer Zone erkannt",
    104: "CO2-Sensor-C-Fehler",
})

# Firmware 1.4.0 und aelter - ab Bit 70 andere Bedeutung
ALARM_ERRORS_140 = dict(ALARM_ERRORS_BASE)
ALARM_ERRORS_140.update({
    70: "Die ComfoHood war vorhanden, wird aber nicht mehr erkannt (HOOD_CONNECT ERROR)",
    71: "Das ComfoCool war vorhanden, wird aber nicht mehr erkannt (CCOOL_CONNECT ERROR)",
    72: "Das ComfoFond war vorhanden, wird aber nicht mehr erkannt (GROUND_HEAT_CONNECT ERROR)",
    73: "Die Filter der Lüftungsanlage müssen jetzt gewechselt werden",
    74: "Der externe Filter muss ersetzt oder gereinigt werden",
    75: "Neue Filter bestellen - die Restlaufzeit der Filter ist begrenzt",
    76: "Der Servicemodus ist aktiv (SERVICE MODE)",
    77: "Das Vorheizregister hat keine Verbindung zur Lüftungsanlage (PREHEAT ERROR, 1081)",
    78: "ComfoHood-Temperaturfehler (HOOD_TEMP ERROR)",
    79: "Nachheizregister-Temperaturfehler (POSTHEAT_TEMP ERROR)",
    80: "Außentemperaturfehler des ComfoFond (GROUND_HEAT_TEMP ERROR)",
    81: "Der Bypass ist im Handbetrieb",
    82: "Das ComfoCool überhitzt",
    83: "ComfoCool-Kompressorfehler (CCOOL_COMPRESSOR ERROR)",
    84: "ComfoCool-Raumtemperaturfühler defekt (CCOOL_TEMP ERROR)",
    85: "ComfoCool-Kondensatortemperaturfühler defekt (CCOOL_TEMP ERROR)",
    86: "ComfoCool-Zulufttemperaturfühler defekt (CCOOL_TEMP ERROR)",
})

# Firmware-Grenze: alles darueber benutzt ALARM_ERRORS, alles bis einschliesslich
# diesen Wert die 1.4.0-Tabelle.
ALARM_FIRMWARE_140 = 3222278144
