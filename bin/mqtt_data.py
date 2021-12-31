sensor_data = {
    16: {
        'NAME' : 'AWAY',
        'PUSH'  :  0
        },
    49: {
        'NAME' : 'OPERATING_MODE_BIS',
        'PUSH'  :  0
        },
    56: {
        'NAME' : 'OPERATING_MODE',
        'PUSH'  :  0
        },
    65: {
        'NAME' : 'FAN_SPEED_MODE',
        'CONV'  :   'str(%i)[-1:]',
        'PUSH'  :  0
        },
    66: {
        'NAME' : 'BYPASS_MODE',
        'PUSH'  :  0
        },
    67: {
        'NAME' : 'PROFILE_TEMPERATURE',
        'PUSH'  :  0
        },
    70: {
        'NAME' : 'FAN_MODE_SUPPLY',
        'PUSH'  :  0
        },
    71: {
        'NAME' : 'FAN_MODE_EXHAUST',
        'PUSH'  :  0
        },
    81: {
        'NAME' : 'FAN_NEXT_CHANGE',
        'PUSH'  :  2
        },
    82: {
        'NAME' : 'BYPASS_NEXT_CHANGE',
        'PUSH'  :  2
        },
    86: {
        'NAME' : 'SUPPLY_NEXT_CHANGE',
        'PUSH'  :  2
        },
    87: {
        'NAME' : 'EXHAUST_NEXT_CHANGE',
        'PUSH'  :  2
        },
    117: {
        'NAME' : 'FAN_EXHAUST_DUTY',
        'PUSH'  :  3
        },
    118: {
        'NAME' : 'FAN_SUPPLY_DUTY',
        'PUSH'  :  3
        },
    119: {
        'NAME' : 'FAN_EXHAUST_FLOW',
        'PUSH'  :  3
        },
    120: {
        'NAME' : 'FAN_SUPPLY_FLOW',
        'PUSH'  :  3
        },
    121: {
        'NAME' : 'FAN_EXHAUST_SPEED',
        'PUSH'  :  3
        },
    122: {
        'NAME' : 'FAN_SUPPLY_SPEED',
        'PUSH'  :  3
        },
    128: {
        'NAME' : 'POWER_CURRENT',
        'PUSH'  :  3
        },
    129: {
        'NAME' : 'POWER_TOTAL_YEAR',
        'PUSH'  :  3
        },
    130: {
        'NAME' : 'POWER_TOTAL',
        'PUSH'  :  3
        },
    144: {
        'NAME' : 'PREHEATER_POWER_TOTAL_YEAR',
        'PUSH'  :  3
        },
    145: {
        'NAME' : 'PREHEATER_POWER_TOTAL',
        'PUSH'  :  3
        },
    146: {
        'NAME' : 'PREHEATER_POWER_CURRENT',
        'PUSH'  :  3
        },
    176: {
        'NAME' : 'SETTING_RF_PAIRING',
        'PUSH'  :  3
        },
    192: {
        'NAME' : 'DAYS_TO_REPLACE_FILTER',
        'PUSH'  :  3
        },
    209: {
        'NAME' : 'CURRENT_RMOT',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    210: {
        'NAME' : 'HEATING_SEASON',
        'PUSH'  :  3
        },
    211: {
        'NAME' : 'COOLING_SEASON',
        'PUSH'  :  3
        },
    212: {
        'NAME' : 'TARGET_TEMPERATURE',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    213: {
        'NAME' : 'AVOIDED_HEATING_CURRENT',
        'PUSH'  :  3
        },
    214: {
        'NAME' : 'AVOIDED_HEATING_TOTAL_YEAR',
        'PUSH'  :  3
        },
    215: {
        'NAME' : 'AVOIDED_HEATING_TOTAL',
        'PUSH'  :  3
        },
    216: {
        'NAME' : 'AVOIDED_COOLING_CURRENT',
        'PUSH'  :  3
        },
    217: {
        'NAME' : 'AVOIDED_COOLING_TOTAL_YEAR',
        'PUSH'  :  3
        },
    218: {
        'NAME' : 'AVOIDED_COOLING_TOTAL',
        'PUSH'  :  3
        },
    219: {
        'NAME' : 'AVOIDED_COOLING_CURRENT_TARGET',
        'PUSH'  :  3
        },
    221: {
        'NAME' : 'TEMPERATURE_SUPPLY',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    225: {
        'NAME' : 'COMFORTCONTROL_MODE',
        'PUSH'  :  0
        },
    227: {
        'NAME' : 'BYPASS_STATE',
        'PUSH'  :  0
        },
    228: {
        'NAME' : 'FROSTPROTECT_UNBALANCE',
        'PUSH'  :  0
        },
    274: {
        'NAME' : 'TEMPERATURE_EXTRACT',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    275: {
        'NAME' : 'TEMPERATURE_EXHAUST',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    276: {
        'NAME' : 'TEMPERATURE_OUTDOOR',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    277: {
        'NAME' : 'TEMPERATURE_AFTER_PREHEATER',
        'CONV'  :   "%i / 10",
        'PUSH'  :  3
        },
    290: {
        'NAME' : 'HUMIDITY_EXTRACT',
        'PUSH'  :  3
        },
    291: {
        'NAME' : 'HUMIDITY_EXHAUST',
        'PUSH'  :  3
        },
    292: {
        'NAME' : 'HUMIDITY_OUTDOOR',
        'PUSH'  :  3
        },
    293: {
        'NAME' : 'HUMIDITY_AFTER_PREHEATER',
        'PUSH'  :  3
        },
    294: {
        'NAME' : 'HUMIDITY_SUPPLY',
        'PUSH'  :  3
        },
    }