#!/bin/bash

# Shell script which is executed by bash *BEFORE* installation is started
# (*BEFORE* preinstall and *BEFORE* preupdate). Use with caution and remember,
# that all systems may be different!
#
# Exit code must be 0 if executed successfull. 
# Exit code 1 gives a warning but continues installation.
# Exit code 2 cancels installation.
#
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# Will be executed as user "root".
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#
# You can use all vars from /etc/environment in this script.
#
# We add 5 additional arguments when executing this script:
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
#
# For logging, print to STDOUT. You can use the following tags for showing
# different colorized information during plugin installation:
#
# <OK> This was ok!"
# <INFO> This is just for your information."
# <WARNING> This is a warning!"
# <ERROR> This is an error!"
# <FAIL> This is a fail!"

# To use important variables from command line use the following code:
COMMAND=$0    # Zero argument is shell command
PTEMPDIR=$1   # First argument is temp folder during install
PSHNAME=$2    # Second argument is Plugin-Name for scipts etc.
PDIR=$3       # Third argument is Plugin installation folder
PVERSION=$4   # Forth argument is Plugin version
#LBHOMEDIR=$5 # Comes from /etc/environment now. Fifth argument is
              # Base folder of LoxBerry
PTEMPPATH=$6  # Sixth argument is full temp path during install (see also $1)

# Combine them with /etc/environment
PCGI=$LBPCGI/$PDIR
PHTML=$LBPHTML/$PDIR
PTEMPL=$LBPTEMPL/$PDIR
PDATA=$LBPDATA/$PDIR
PLOG=$LBPLOG/$PDIR # Note! This is stored on a Ramdisk now!
PCONFIG=$LBPCONFIG/$PDIR
PSBIN=$LBPSBIN/$PDIR
PBIN=$LBPBIN/$PDIR

#. $LBHOMEDIR/libs/bashlib/loxberry_log.sh
#PACKAGE=${PSHNAME}
#NAME=preroot_install
#FILENAME=${LBPLOG}/${PSHNAME}/preroot_install.log
#APPEND=1
#STDERR=1
  
echo "<INFO> Installation as root user started."

# ---------------------------------------------------------------------------
# Systempakete: erst pruefen, dann erst installieren.
#
# Frueher standen diese drei Pakete in dpkg/apt. Dann uebernimmt LoxBerry die
# Installation - und zwar bei JEDEM Update aufs Neue: Apt-Datenbank aufraeumen,
# "apt-get update" gegen alle konfigurierten Quellen, danach die Pakete
# neu einspielen ("3 reinstalled"), obwohl sie unveraendert vorhanden sind.
# Das waren rund anderthalb Minuten je Installation, und der Umweg ueber
# "apt-get update" holte sich nebenbei die Fehlermeldungen fremder Paketquellen
# ins Plugin-Log, mit denen dieses Plugin nichts zu tun hat.
#
# Hier wird stattdessen nachgesehen, was fehlt. Im Regelfall fehlt nichts, dann
# passiert auch nichts. Nur beim ersten Mal - oder wenn jemand ein Paket
# entfernt hat - wird tatsaechlich installiert.
BENOETIGT="libstring-escape-perl python3-paho-mqtt python3-setuptools"
FEHLEND=""
for PAKET in $BENOETIGT; do
	if ! dpkg-query -W -f='${Status}' "$PAKET" 2>/dev/null | grep -q "ok installed"; then
		FEHLEND="$FEHLEND $PAKET"
	fi
done

if [ -n "$FEHLEND" ]; then
	echo "<INFO> Fehlende Systempakete werden installiert:$FEHLEND"
	apt-get update
	if DEBIAN_FRONTEND=noninteractive apt-get -y install $FEHLEND; then
		echo "<OK> Systempakete installiert."
	else
		echo "<ERROR> Systempakete konnten nicht installiert werden:$FEHLEND"
		echo "<ERROR> Ohne diese Pakete laeuft das Plugin nicht."
		exit 2
	fi
else
	echo "<OK> Alle benoetigten Systempakete sind vorhanden."
fi

echo "<INFO> Checking pip..."
# NOTE: no --upgrade here (see protobuf comment below) - just make sure pip is
# present, don't force a slow version check against PyPI on every single install.
if ! python3 -m pip --version >/dev/null 2>&1; then
	echo "<INFO> pip fehlt und wird installiert."
	python3 -m pip install pip
fi

echo "<INFO> Start installing protobuf..."
# NOTE: must be quoted - unquoted "protobuf>=3.20.3" is parsed by bash as a
# redirection (">") into a file literally named "=3.20.3", silently dropping
# the version constraint and hiding pip's output.
#
# NOTE: deliberately no --upgrade. "pip install X" when X is already installed
# and satisfies the version constraint is a fast local check ("Requirement
# already satisfied") - "pip install --upgrade X" always queries PyPI for the
# latest available version first, even when nothing needs to change. That
# forced network round-trip was adding ~2 minutes to every single install or
# update, even when protobuf was already correctly installed. Without
# --upgrade we still get protobuf>=3.20.3 installed/upgraded automatically the
# one time it's actually missing or too old - just not on every run after that.
# Dieselbe Ueberlegung wie oben bei den Systempaketen: Ist eine passende Fassung
# schon da, entfaellt der pip-Aufruf komplett. Die Pruefung laeuft rein lokal.
if python3 -c 'import google.protobuf, sys; from google.protobuf import __version__ as v; sys.exit(0 if tuple(int(x) for x in v.split(".")[:3]) >= (3,20,3) else 1)' 2>/dev/null; then
	echo "<OK> protobuf ist bereits in passender Fassung vorhanden."
	exit 0
fi

python3 -m pip install "protobuf>=3.20.3"
INSTALLED=$(pip3 list --format=columns | grep "protobuf" | grep -v grep | wc -l)
if [ ${INSTALLED} -ne "0" ]; then
	echo "<OK> protobuf installed successfully."
else
	echo "<WARNING> protobuf installation failed! The plugin will not work without."
	echo "<WARNING> Giving up."
	exit 2;
fi 

exit 0
