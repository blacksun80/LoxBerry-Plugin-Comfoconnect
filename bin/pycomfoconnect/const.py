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
CMD_VENTMODE_STOP_SUPPLY_FAN_1      = b'\x84\x15\x07\x01\x00\x00\x00\x00\x10\x0e\x00\x00\x01'   # Stoppt Supply-Fan für 1h
CMD_START_EXHAUST_FAN               = b'\x85\x15\x06\x01'
CMD_VENTMODE_STOP_EXHAUST_FAN_1     = b'\x84\x15\x06\x01\x00\x00\x00\x00\x10\x0e\x00\x00\x01'   # Stoppt Exhaust-Fan für 1h
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
CMD_BOOST_MODE_1                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x08\x07\x00\x00\x03'   # Partymode 0.5h 
CMD_BOOST_MODE_2                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x10\x0E\x00\x00\x03'   # Partymode 1h
CMD_BOOST_MODE_3                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x20\x1C\x00\x00\x03'   # Partymode 2h
CMD_BOOST_MODE_4                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x30\x2A\x00\x00\x03'   # Partymode 3h
CMD_BOOST_MODE_5                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x40\x38\x00\x00\x03'   # Partymode 4h
CMD_BOOST_MODE_6                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x50\x46\x00\x00\x03'   # Partymode 5h
CMD_BOOST_MODE_7                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x60\x54\x00\x00\x03'   # Partymode 6h
CMD_BOOST_MODE_8                    = b'\x84\x15\x01\x06\x00\x00\x00\x00\x80\x70\x00\x00\x03'   # Partymode 8h
CMD_BOOST_MODE_0                    = b'\x85\x15\x01\x06'                                       # End Partymode
CMD_READ_CONFIG                     = b'\x87\x15\x01'
CMD_READ_HRU                        = b'\x01\x01\x01\x10\x08'
CMD_BOOST_MODE_START                = b'\x84\x15\x01\x06\x00\x00\x00\x00\x58\x02\x00\x00\x03'   # BOOST MODE 10 MIN
CMD_BOOST_MODE_END                  = b'\x85\x15\x01\x06'

# Sensor locations
SENSOR_TEMPERATURE_SUPPLY = 221
SENSOR_TEMPERATURE_EXTRACT = 274
SENSOR_TEMPERATURE_EXHAUST = 275
SENSOR_TEMPERATURE_OUTDOOR = 276
SENSOR_HUMIDITY_EXTRACT = 290
SENSOR_HUMIDITY_EXHAUST = 291
SENSOR_HUMIDITY_OUTDOOR = 292
SENSOR_HUMIDITY_SUPPLY = 294
SENSOR_FAN_NEXT_CHANGE = 81
SENSOR_FAN_SPEED_MODE = 65
SENSOR_FAN_SUPPLY_DUTY = 117
SENSOR_FAN_EXHAUST_DUTY = 118
SENSOR_FAN_SUPPLY_FLOW = 119
SENSOR_FAN_EXHAUST_FLOW = 120
SENSOR_FAN_SUPPLY_SPEED = 121
SENSOR_FAN_EXHAUST_SPEED = 122
SENSOR_POWER_CURRENT = 128
SENSOR_POWER_TOTAL_YEAR = 129
SENSOR_POWER_TOTAL = 130
SENSOR_AVOIDED_HEATING_CURRENT = 213
SENSOR_AVOIDED_HEATING_TOTAL_YEAR = 214
SENSOR_AVOIDED_HEATING_TOTAL = 215
SENSOR_DAYS_TO_REPLACE_FILTER = 192
SENSOR_BYPASS_STATE = 227
SENSOR_RUNMODE_SUPPLY_BALANCE = 70
SENSOR_AUTO_STATE = 225
SENSOR_AWAY_STATE = 16
SENSOR_TEMP_PROFILE = 67
SETTING_BYPASS = 66
SETTING_HEATING_SEASON = 210
SETTING_RF_PAIRING = 176
OPERATING_MODE_BIS = 49 # 01 = limited manual, 05 = unlimited manual, 06 = party mode, ff = auto)
OPERATING_MODE = 56
FAN_MODE_EXHAUST = 71
PREHEATER_POWER_TOTAL_YEAR = 144
PREHEATER_POWER_TOTAL = 145
PREHEATER_POWER_CURRENT = 146
CURRENT_RMOT = 209
AVOIDED_COOLING_CURRENT = 216
AVOIDED_COOLING_TOTAL_YEAR = 217
AVOIDED_COOLING_TOTAL = 218


