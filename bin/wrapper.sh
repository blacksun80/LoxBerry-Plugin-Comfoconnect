#!/bin/bash

PLUGINNAME=REPLACELBPPLUGINDIR
PATH="/sbin:/bin:/usr/sbin:/usr/bin:$LBHOMEDIR/bin:$LBHOMEDIR/sbin"

ENVIRONMENT=$(cat /etc/environment)
export $ENVIRONMENT

# Logfile
. $LBHOMEDIR/libs/bashlib/loxberry_log.sh
PACKAGE=${PLUGINNAME}
NAME=${PLUGINNAME}_MQTT
LOGDIR=$LBPLOG/${PLUGINNAME}

# Debug output
#STDERR=0
#DEBUG=0
# if [[ ${LOGLEVEL} -eq 7 ]]; then
	# LOGINF "Debugging is enabled! This will produce A LOT messages in your logfile!"
	# STDERR=1
	# DEBUG=1
# fi
	
	#LOGINF "Starting comfoconnect..."
	$LBHOMEDIR/bin/plugins/comfoconnect/openhab_gw.py

	#LOGEND "gpio2mqtt"
        exit 0
        ;;