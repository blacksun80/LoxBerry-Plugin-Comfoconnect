sensor_data = {
    16: {
        'NAME' : 'AWAY'
        },
    49: {
        'NAME' : 'OPERATING_MODE_BIS'
        },
    56: {
        'NAME' : 'OPERATING_MODE'
        },
    65: {
        'NAME' : 'FAN_SPEED_MODE',
        'CONV'  :   'str(%i)[-1:]'
        },
    66: {
        'NAME' : 'BYPASS_MODE'
        },
    67: {
        'NAME' : 'PROFILE_TEMPERATURE'
        },
    70: {
        'NAME' : 'FAN_MODE_SUPPLY'
        },
    71: {
        'NAME' : 'FAN_MODE_EXHAUST'
        },
    81: {
        'NAME' : 'FAN_NEXT_CHANGE'
        },
    # 82: {
        # 'NAME' : 'BYPASS_NEXT_CHANGE'
        # },
    # 86: {
        # 'NAME' : 'SUPPLY_NEXT_CHANGE'
        # },
    # 87: {
        # 'NAME' : 'EXHAUST_NEXT_CHANGE'
        # },
    117: {
        'NAME' : 'FAN_EXHAUST_DUTY'
        },
    118: {
        'NAME' : 'FAN_SUPPLY_DUTY'
        },
    119: {
        'NAME' : 'FAN_EXHAUST_FLOW'
        },
    120: {
        'NAME' : 'FAN_SUPPLY_FLOW'
        },
    121: {
        'NAME' : 'FAN_EXHAUST_SPEED'
        },
    122: {
        'NAME' : 'FAN_SUPPLY_SPEED'
        },
    128: {
        'NAME' : 'POWER_CURRENT'
        },
    129: {
        'NAME' : 'POWER_TOTAL_YEAR'
        },
    130: {
        'NAME' : 'POWER_TOTAL'
        },
    # 144: {
        # 'NAME' : 'PREHEATER_POWER_TOTAL_YEAR'
        # },
    145: {
        'NAME' : 'PREHEATER_POWER_TOTAL'
        },
    146: {
        'NAME' : 'PREHEATER_POWER_CURRENT'
        },
    176: {
        'NAME' : 'SETTING_RF_PAIRING'
        },
    192: {
        'NAME' : 'DAYS_TO_REPLACE_FILTER'
        },
    209: {
        'NAME' : 'CURRENT_RMOT',
        'CONV'  :   "%i / 10"
        },
    210: {
        'NAME' : 'HEATING_SEASON'
        },
    # 211: {
        # 'NAME' : 'COOLING_SEASON'
        # },
    # 212: {
        # 'NAME' : 'TARGET_TEMPERATURE',
        # 'CONV'  :   "%i / 10"
        # },
    213: {
        'NAME' : 'AVOIDED_HEATING_CURRENT'
        },
    214: {
        'NAME' : 'AVOIDED_HEATING_TOTAL_YEAR'
        },
    215: {
        'NAME' : 'AVOIDED_HEATING_TOTAL'
        },
    216: {
        'NAME' : 'AVOIDED_COOLING_CURRENT'
        },
    217: {
        'NAME' : 'AVOIDED_COOLING_TOTAL_YEAR'
        },
    218: {
        'NAME' : 'AVOIDED_COOLING_TOTAL'
        },
    # 219: {
        # 'NAME' : 'AVOIDED_COOLING_CURRENT_TARGET'
        # },
    221: {
        'NAME' : 'TEMPERATURE_SUPPLY',
        'CONV'  :   "%i / 10"
        },
    225: {
        'NAME' : 'COMFORTCONTROL_MODE'
        },
    227: {
        'NAME' : 'BYPASS_STATE'
        },
    # 228: {
        # 'NAME' : 'FROSTPROTECT_UNBALANCE'
        # },
    274: {
        'NAME' : 'TEMPERATURE_EXTRACT',
        'CONV'  :   "%i / 10"
        },
    275: {
        'NAME' : 'TEMPERATURE_EXHAUST',
        'CONV'  :   "%i / 10"
        },
    276: {
        'NAME' : 'TEMPERATURE_OUTDOOR',
        'CONV'  :   "%i / 10"
        },
    # 277: {
        # 'NAME' : 'TEMPERATURE_AFTER_PREHEATER',
        # 'CONV'  :   "%i / 10"
        # },
    290: {
        'NAME' : 'HUMIDITY_EXTRACT'
        },
    291: {
        'NAME' : 'HUMIDITY_EXHAUST'
        },
    292: {
        'NAME' : 'HUMIDITY_OUTDOOR'
        },
    # 293: {
        # 'NAME' : 'HUMIDITY_AFTER_PREHEATER'
        # },
    294: {
        'NAME' : 'HUMIDITY_SUPPLY'
        },
    }