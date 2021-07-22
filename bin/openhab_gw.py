#!/usr/bin/python3
import argparse
import paho.mqtt.client as mqtt
import datetime
from time import sleep
from binascii import unhexlify
from random import randint
from pycomfoconnect import *
import getopt
import json
import configparser
from mqtt_strings import sensor_name
import logging

def on_publish(client, userdata, mid):
    _LOGGER.debug("Published Data - mid: "+str(mid))
    pass

def on_connect(client, userdata, flags, rc):
    _LOGGER.info("Connection returned result: "+mqtt.connack_string(rc))
    
    client.subscribe(mqtt_topic + "#", qos=2)
    client.message_callback_add(mqtt_topic + "FAN_MODE", on_message_CMD)
    client.message_callback_add(mqtt_topic + "FAN_MODE_AWAY", on_message_CMD)
    client.message_callback_add(mqtt_topic + "FAN_MODE_LOW", on_message_CMD)
    client.message_callback_add(mqtt_topic + "FAN_MODE_MEDIUM", on_message_CMD)
    client.message_callback_add(mqtt_topic + "FAN_MODE_HIGH", on_message_CMD)
    client.message_callback_add(mqtt_topic + "MODE_AUTO", on_message_CMD)
    client.message_callback_add(mqtt_topic + "MODE_MANUAL", on_message_CMD)
    client.message_callback_add(mqtt_topic + "BOOST_MODE_START", on_message_CMD)
    client.message_callback_add(mqtt_topic + "BOOST_MODE_END", on_message_CMD)
    client.message_callback_add(mqtt_topic + "VENTMODE_SUPPLY", on_message_CMD)
    client.message_callback_add(mqtt_topic + "VENTMODE_BALANCE", on_message_CMD)
    client.message_callback_add(mqtt_topic + "TEMPPROF_NORMAL", on_message_CMD)
    client.message_callback_add(mqtt_topic + "TEMPPROF_COOL", on_message_CMD)
    client.message_callback_add(mqtt_topic + "TEMPPROF_WARM", on_message_CMD)
    client.message_callback_add(mqtt_topic + "BYPASS_ON", on_message_CMD)
    client.message_callback_add(mqtt_topic + "BYPASS_OFF", on_message_CMD)
    client.message_callback_add(mqtt_topic + "BYPASS_AUTO", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_TEMP_OFF", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_TEMP_AUTO", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_TEMP_ON", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMC_OFF", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMC_AUTO", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMC_ON", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMP_OFF", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMP_AUTO", on_message_CMD)
    client.message_callback_add(mqtt_topic + "SENSOR_HUMP_ON", on_message_CMD)

def on_disconnect(client, userdata, rc):
    client.loop_stop()
    _LOGGER.info("Disconnection returned result: "+mqtt.connack_string(rc))

def on_message_CMD(client, userdata, msg):
    inputaction.append([msg.topic, msg.qos, str(msg.payload.decode("utf-8"))])  # add command to action list

    _LOGGER.info("from MQTT %s = %s\n" % (msg.topic , msg.payload))
    #_LOGGER.debug("from MQTT %s = %s\n" % (msg.topic , str(msg.payload.decode("utf-8"))))
    _LOGGER.info(list(inputaction))
    pass

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
    
    if debug:
        bridge.debug=True
    else:
        bridge.debug=False
        
    return bridge

def callback_sensor(var, value):
    # for x in unknown:
        # if var == x:
            # print ("unknown:")
            # print (x)
            # print (var)
            # return
            
    (rc, mid) = client.publish(mqtt_topic + sensor_name[var], value)

    _LOGGER.debug("rc: " + str(rc) + "   mid: " + str(mid))
    _LOGGER.debug("%s = %s" % (var, value))
    _LOGGER.debug(mqtt_topic)
    _LOGGER.debug(value)
    _LOGGER.debug("Var: " + str(var))
    _LOGGER.debug(sensor_name[var])
    _LOGGER.debug("---------")
    _LOGGER.debug("to MQTT %s = %s\n" % (mqtt_topic + sensor_name[var], value))

def main():
    global mqtt_topic, client, debug, loglevel, logfile, _LOGGER, inputaction, search, unknown
    
    connected_flag = 0
    connected_flag_old = 0
    inputaction = []
    loglevel=logging.ERROR
    search = False

    opts, args = getopt.getopt(sys.argv[1:],"c:f:l:s:",['configfile=', 'logfile=', 'loglevel=', 'search'])
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
    
    if loglevel == 10: # Level Debug
        debug = True
    else:
        debug = False
    
    # Get configurations from file
    Config = configparser.ConfigParser()
    Config.optionxform = str
    Config.read(configfile)
    
    # Configuration #######################################################################################################
    local_name      = 'ComfoConnect Gateway'                                # Name of the service
    local_uuid      = bytes.fromhex('00000000000000000000000000000005')     # Can be what you want, used to differentiate devices (as only 1 simultaneously connected device is allowed)
    device_ip		= Config.get('MAIN','IPLANC')                           # Look in your router administration and get the ip of the comfoconnect device and set it as static lease
    pin     		= Config.get('MAIN', 'PIN')                             # Set PIN of vent unit !
    
    # Configuration mqtt#######################################################################################################
    mqttBroker   	= Config.get('MAIN', 'MQTTSERVER')                      # Set your MQTT broker here
    mqtt_user 		= Config.get('MAIN', 'MQTTUSER')                        # Set the MQTT user login
    mqtt_passw   	= Config.get('MAIN', 'MQTTPASS')                        # Set the MQTT user password
    mqtt_topic  	= Config.get('MAIN', 'MQTTTOPIC')                       # Set the MQTT root topic
    mqtt_port       = Config.get('MAIN', 'MQTTPORT')                        # Set the MQTT Port

    client                      = mqtt.Client("ComfoConnect", clean_session=True)
    client.on_subscribe         = on_subscribe
    client.on_publish           = on_publish
    client.on_connect           = on_connect
    client.on_disconnect        = on_disconnect
    
    client.username_pw_set(mqtt_user,mqtt_passw)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    _LOGGER = setup_logger("COMFOCONNECT")
    _LOGGER.debug("logfile: " + logfileArg)
    _LOGGER.info("loglevel: " + logging.getLevelName(_LOGGER.level))

#   Connect to Comfocontrol device  #####################################################################################
#   Detect Bridge
    if search:
        bridge = bridge_discovery(device_ip, debug, search)
        _LOGGER.info("Bridge gefunden")
        Config.set('MAIN','IPLANC', bridge.host)
        _LOGGER.info("IP Adresse in Configfile gesichert")
        # save to a file
        with open(configfile, 'w') as config_file:
            Config.write(config_file)
        exit(0)
        
    bridge = bridge_discovery(device_ip, debug, search)

    comfoconnect = ComfoConnect(bridge, local_uuid, local_name, pin)
    comfoconnect.callback_sensor = callback_sensor
    
    # Connect to the broker
    try:
        _LOGGER.info("Connecting to MQTT Broker...")
        client.connect(mqttBroker, mqtt_port)
    except Exception as e:
        _LOGGER.exception(str(e))
        _LOGGER.critical("Not connected to MQTT Broker")
        exit(1)
    client.loop_start()

    # Connect to the bridge
    try:
        _LOGGER.info("Connect to the bridge")
        comfoconnect.connect(True)  # Disconnect existing clients.

    except Exception as e:
        _LOGGER.exception(str(e))
        _LOGGER.critical("Not connected to bridge")
        exit(1)

#    unknown types investigation
    # unknown = [33, 37, 53, 82, 85, 86, 87, 145, 146, 208, 211, 212, 216, 217, 218, 219, 224, 226, 228, 321, 325, 337, 338, 341, 369, 370, 371, 372, 384, 386, 400, 401, 402, 416, 417, 418, 419]
    # for y in unknown:
        # comfoconnect.register_sensor(y)
        # _LOGGER.debug("Unknown Sensor No.: %d" % y)
        
#    Register sensors ################################################################################################
    for x in sensor_name:
        comfoconnect.register_sensor(x)
        _LOGGER.debug("Register Sensor No.: %d" % x)

    ## Executing functions #############################################################################################

    connected_flag=True

    try:
        print('Running... Stop with CTRL+C')
        while True:
            if connected_flag:
                # ---------------------------------------------------------------------------------------
                # Process action list, do one command each itteration until list is empty
                if inputaction:                 # anything to do ?
                    topic = inputaction[0][0]   # yes, extract topic from oldest list item
                    qos = inputaction[0][1]     # extract qos value from oldest list item
                    value = inputaction[0][2]   # extract payload value oldest from list item
                    inputaction.pop(0)          # remove oldest list item from list
                    # now execute matching command
                    print ("was zu tun")
                    if topic == mqtt_topic + "FAN_MODE":
                        if int(value) == 0:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_AWAY)
                            _LOGGER.info("FAN_MODE_AWAY")
                        elif int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_LOW)
                            _LOGGER.info("FAN_MODE_LOW")
                        elif int(value) == 2:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_MEDIUM)
                            _LOGGER.info("FAN_MODE_MEDIUM")
                        elif int(value) == 3:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_HIGH)
                            _LOGGER.info("FAN_MODE_HIGH")
                    elif topic == mqtt_topic + "FAN_MODE_AWAY":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_AWAY)  # Go to away mode
                            _LOGGER.info("FAN_MODE_AWAY")
                    elif topic == mqtt_topic + "FAN_MODE_LOW":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_LOW)  #
                            _LOGGER.info("FAN_MODE_LOW")
                    elif topic == mqtt_topic + "FAN_MODE_MEDIUM":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_MEDIUM)  #
                            _LOGGER.info("FAN_MODE_MEDIUM")
                    elif topic == mqtt_topic + "FAN_MODE_HIGH":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_FAN_MODE_HIGH)  #
                            _LOGGER.info("FAN_MODE_HIGH")
                    elif topic == mqtt_topic + "MODE_AUTO":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_MODE_AUTO)  #
                            _LOGGER.info("MODE_AUTO")
                    elif topic == mqtt_topic + "MODE_MANUAL":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_MODE_MANUAL)  #
                            _LOGGER.info("MODE_MANUAL")
                    elif topic == mqtt_topic + "BOOST_MODE_START":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_BOOST_MODE_START)  #
                            _LOGGER.info("BOOST_MODE_START")
                    elif topic == mqtt_topic + "BOOST_MODE_END":
                        if int(value) == 1:
                            comfoconnect.cmd_rmi_request(CMD_BOOST_MODE_END)  #
                            _LOGGER.info("BOOST_MODE_END")
                    elif topic == mqtt_topic + "VENTMODE_SUPPLY":
                        comfoconnect.cmd_rmi_request(CMD_VENTMODE_SUPPLY)  #
                    elif topic == mqtt_topic + "VENTMODE_BALANCE":
                        comfoconnect.cmd_rmi_request(CMD_VENTMODE_BALANCE)  #
                    elif topic == mqtt_topic + "TEMPPROF_NORMAL":
                        comfoconnect.cmd_rmi_request(CMD_TEMPPROF_NORMAL)  #
                    elif topic == mqtt_topic + "TEMPPROF_COOL":
                        comfoconnect.cmd_rmi_request(CMD_TEMPPROF_COOL)  #
                    elif topic == mqtt_topic + "TEMPPROF_WARM":
                        comfoconnect.cmd_rmi_request(CMD_TEMPPROF_WARM)  #
                    elif topic == mqtt_topic + "BYPASS_ON":
                        comfoconnect.cmd_rmi_request(CMD_BYPASS_ON)  #
                    elif topic == mqtt_topic + "BYPASS_OFF":
                        comfoconnect.cmd_rmi_request(CMD_BYPASS_OFF)  #
                    elif topic == mqtt_topic + "BYPASS_AUTO":
                        comfoconnect.cmd_rmi_request(CMD_BYPASS_AUTO)  #
                    elif topic == mqtt_topic + "SENSOR_TEMP_OFF":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_OFF)  #
                    elif topic == mqtt_topic + "SENSOR_TEMP_AUTO":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_AUTO)  #
                    elif topic == mqtt_topic + "SENSOR_TEMP_ON":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_TEMP_ON)  #
                    elif topic == mqtt_topic + "SENSOR_HUMC_OFF":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_OFF)  #
                    elif topic == mqtt_topic + "SENSOR_HUMC_AUTO":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_AUTO)  #
                    elif topic == mqtt_topic + "SENSOR_HUMC_ON":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMC_ON)  #
                    elif topic == mqtt_topic + "SENSOR_HUMP_OFF":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_OFF)  #
                    elif topic == mqtt_topic + "SENSOR_HUMP_AUTO":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_AUTO)  #
                    elif topic == mqtt_topic + "SENSOR_HUMP_ON":
                        comfoconnect.cmd_rmi_request(CMD_SENSOR_HUMP_ON)  #
            else:
                _LOGGER.critical("Not connected to ComfoConnect ...")
        sleep(1)
    except KeyboardInterrupt:
        pass

    ## Closing the session #############################################################################################
    client.loop_stop()
    client.disconnect()
    comfoconnect.disconnect()

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
    handler = logging.StreamHandler()

    logger.addHandler(handler)
    logger.setLevel(loglevel)

    if not logfile:
        logfile="/tmp/"+datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]+"_comfoconnect.log"
    logging.basicConfig(filename=logfile,level=loglevel,format='%(asctime)s.%(msecs)03d <%(levelname)s> %(message)s',datefmt='%H:%M:%S')

    return logger

if __name__ == "__main__":
    main()
