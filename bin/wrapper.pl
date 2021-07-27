#!/usr/bin/perl

# Copyright 2017 Michael Schlenstedt, michael@loxberry.de
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


##########################################################################
# Modules
##########################################################################

use Config::Simple;
use File::HomeDir;
use Cwd 'abs_path';
use Getopt::Long;
use LoxBerry::System;
use LoxBerry::Log;
#use warnings;
#use strict;
no strict "refs"; # we need it for template system and for contructs like ${"skalar".$i} in loops
no strict "subs"; # we need it for template system and for contructs like ${"skalar".$i} in loops

##########################################################################
# Variables
##########################################################################
my  $cfg;
my  $plugin_cfg;
my  %plugin_cfg_hash;
my  $installfolder;
my  $version;
my  $home = $lbhomedir;
my  $psubfolder = $lbpplugindir;
my  $pname;
my  @heads;
my  $name;
my  $serial;
my  $device;
my  $meter;
my  $protocol;
my  $startbaudrate;
my  $baudrate;
my  $timeout;
my  $handshake;
my  $databits;
my  $stopbits;
my  $parity;
my  $delay;
our $miniservers;
our $clouddns;
our $udpport;
our $sendudp;
my  $udpstring;
my  @lines;
my  $i;
my  $verbose;
my  $force;
my $log = LoxBerry::Log->new(name => 'ComfoConnect',);
my $restart;
my $arg;

LOGSTART("ComfoConnect Log");
my $logfile = $log->filename();
my $loglevel = $log->loglevel();

if ($loglevel == 7) {
    LOGINF "Debugging is enabled! This will produce A LOT messages in your logfile!";
    $log->stdout(1);
    $log->stderr(1);
}

##########################################################################
# Read Settings
##########################################################################

# Version of this script
$version = "0.1";

# Read general config
$cfg	 	= new Config::Simple("$home/config/system/general.cfg") or die $cfg->error();
$installfolder	= $cfg->param("BASE.INSTALLFOLDER");
$miniservers	= $cfg->param("BASE.MINISERVERS");
$clouddns	= $cfg->param("BASE.CLOUDDNS");

foreach $arg (@ARGV) {
    if (($arg eq "restart") || ($arg eq "start") || ($arg eq "search")) {

        if (scalar(grep{/cfc.py/} `ps aux`)) {
            LOGINF "cfc.py already running.";
            LOGINF "Stopping ComfoConnect...";
            system("pkill -f $installfolder/bin/plugins/$psubfolder/cfc.py >> $logfile 2>&1");
        }

        if (($arg eq "restart") || ($arg eq "start")) {
            LOGINF "Starting ComfoConnect...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel > /dev/null 2>&1 &");
            exit(0);
        }

        if ($arg eq "search") {
            LOGINF "Suche Lüftungsanlage...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --search > /dev/null 2>&1");
            exit(0);
        }
    }
}

