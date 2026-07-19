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
use LoxBerry::JSON;
use JSON::PP;

use warnings;
use strict;
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
my $log = LoxBerry::Log->new(name => 'ComfoConnect', addtime => 1,);
my $restart;
my $arg;

LOGSTART("ComfoConnect Log");
my $logfile = $log->filename();
my $loglevel = $log->loglevel();

if ($loglevel == 7) {
    $log->stdout(1);
    $log->stderr(1);
    LOGINF "Debugging is enabled! This will produce A LOT messages in your logfile!";
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

# Statusdatei liegt auf der Ramdisk (wie das Log-Verzeichnis, siehe postroot.sh) -
# damit wird bei jedem Heartbeat (alle ~5s, siehe cfc.py) nicht auf die SD-Karte
# geschrieben. Verzeichnis hier selbst anlegen, falls index.cgi noch nie aufgerufen
# wurde (z.B. direkt nach einem Reboot via @reboot-Cronjob).
my $statusfile = "/var/run/shm/$psubfolder/status.json";
system("mkdir -p /var/run/shm/$psubfolder > /dev/null 2>&1");

foreach $arg (@ARGV) {
    if (($arg eq "restart") || ($arg eq "start") || ($arg eq "search")) {

        if (scalar(grep{/cfc.py/} `ps aux`)) {
            LOGINF "cfc.py already running.";
            LOGINF "Stoppe ComfoConnect...";
            system("pkill -f $installfolder/bin/plugins/$psubfolder/cfc.py >> $logfile 2>&1");

            # cfc.py bekommt durch pkill (SIGTERM, kein -9) jetzt die Chance, sich per
            # CloseSessionRequest sauber bei der Zehnder-Box abzumelden, bevor der
            # Prozess beendet wird - kurz warten, bis er das tatsächlich getan hat,
            # statt den neuen Prozess sofort parallel dazu zu starten. Sonst trifft der
            # neue Prozess womöglich noch auf eine Box, die die alte Session noch nicht
            # losgelassen hat (der "resumed"-Verzögerungseffekt, den der saubere
            # Shutdown eigentlich vermeiden soll).
            wait_for_cfc_exit($installfolder, $psubfolder);
        }

        if ($arg eq "restart") {
            LOGINF "Starte ComfoConnect...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile > /dev/null 2>>$logfile &");
            exit(0);
        }

        if ($arg eq "start") {
            LOGINF "Starte ComfoConnect...";
            LOGINF "Warte bis der Loxberry bereit ist";
            sleep(20);
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile > /dev/null 2>>$logfile &");
            exit(0);
        }

        if ($arg eq "search") {
            LOGINF "Suche Lüftungsanlage...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile --search > /dev/null 2>>$logfile");
            exit(0);
        }
    }

    # Vom Watchdog-Cronjob aufgerufen (nur wenn in den Plugin-Einstellungen
    # aktiviert). Prüft, ob cfc.py läuft UND sich innerhalb des eingestellten
    # Zeitfensters noch beim Heartbeat gemeldet hat (last_alive_ping in der
    # Statusdatei) - ein Prozess kann laufen, aber trotzdem "hängen" (z.B. wenn der
    # Verbindungs-Thread zur Zehnder-Box gestorben ist), das reine "läuft der
    # Prozess"-Kriterium alleine würde das nicht erkennen.
    #
    # Zusätzlich wird bridge_last_sensor_data geprüft: last_alive_ping bleibt
    # nämlich frisch, solange die Leseschleife im Verbindungs-Thread einfach
    # weiterdreht (sie hat einen 1s-Select-Timeout und aktualisiert den Ping bei
    # jedem Durchlauf, auch wenn dabei nie eine echte Nachricht ankommt) - eine
    # Session, die die Zehnder-Box serverseitig verworfen hat, ohne dass der
    # TCP-Socket das sauber meldet, würde vom alive_ping-Kriterium allein NICHT
    # erkannt. Nur relevant, wenn schon Sensoren registriert waren (sonst schlägt
    # das direkt nach dem Start fälschlich an, bevor die erste Registrierung
    # überhaupt durch ist).
    if ($arg eq "checkwatchdog") {
        my $jsonobj = LoxBerry::JSON->new();
        my $pcfg = $jsonobj->open(filename => "$installfolder/config/plugins/$psubfolder/$psubfolder.json");

        if (!$pcfg || !$pcfg->{'MAIN'}->{'WATCHDOG_ENABLED'}) {
            exit(0);
        }

        my $threshold_min = $pcfg->{'MAIN'}->{'WATCHDOG_THRESHOLD_MIN'};
        $threshold_min = 3 if (!$threshold_min || $threshold_min !~ /^\d+$/);
        my $threshold_sec = $threshold_min * 60;

        my $running = scalar(grep{/cfc.py/} `ps aux`);
        my $stale_alive = 1;
        my $stale_data = 0;
        my $reason = "reagiert seit über $threshold_min Minute(n) nicht mehr";

        if (-e $statusfile) {
            local $/ = undef;
            if (open(my $fh, '<', $statusfile)) {
                my $json_text = <$fh>;
                close($fh);
                my $status = eval { decode_json($json_text) };
                if ($status) {
                    if ($status->{bridge_last_alive_ping}) {
                        my $age = time() - $status->{bridge_last_alive_ping};
                        $stale_alive = ($age > $threshold_sec) ? 1 : 0;
                    }
                    if (($status->{sensors_registered} // 0) > 0 && $status->{bridge_last_sensor_data}) {
                        my $data_age = time() - $status->{bridge_last_sensor_data};
                        $stale_data = ($data_age > $threshold_sec) ? 1 : 0;
                    }
                }
            }
        }

        my $stale = ($stale_alive || $stale_data) ? 1 : 0;
        $reason = "sendet seit über $threshold_min Minute(n) keine Sensordaten mehr (Verbindung hängt vermutlich)" if ($stale_data && !$stale_alive);

        if (!$running || $stale) {
            LOGWARN "Watchdog: ComfoConnect " . ($running ? $reason : "läuft nicht") . " - starte neu.";
            if ($running) {
                system("pkill -f $installfolder/bin/plugins/$psubfolder/cfc.py >> $logfile 2>&1");
                # Kurze, best-effort Wartezeit auf den sauberen Shutdown (siehe Kommentar
                # oben bei "restart") - falls der Prozess wirklich haengt (genau der Fall,
                # den der Watchdog hier abfaengt), reagiert er evtl. gar nicht auf SIGTERM;
                # dann verstreicht die Wartezeit einfach ungenutzt und wir starten trotzdem neu.
                wait_for_cfc_exit($installfolder, $psubfolder);
            }
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile > /dev/null 2>>$logfile &");
        }
        exit(0);
    }
}

##########################################################################
# wait_for_cfc_exit - best-effort, kurze Wartezeit nach einem pkill auf
# cfc.py, bevor ein neuer Prozess gestartet wird. cfc.py bekommt durch das
# reine pkill (SIGTERM statt -9) inzwischen einen Moment, sich per
# CloseSessionRequest sauber bei der Zehnder-Box abzumelden (siehe der
# SIGTERM-Handler in cfc.py) - ohne diese Wartezeit wuerde der naechste
# Prozess sofort parallel dazu starten und moeglicherweise noch auf eine
# Session treffen, die die Box noch nicht losgelassen hat.
#
# Bricht spaetestens nach $max_wait Sekunden ab und laesst den Aufrufer
# einfach weitermachen - haengt der alte Prozess wirklich (z.B. der Fall, den
# der Watchdog behandelt), soll das den Neustart nicht blockieren.
##########################################################################

sub wait_for_cfc_exit
{
    my ($installfolder, $psubfolder) = @_;
    my $max_wait = 5; # Sekunden - deckt cfc.py's eigenes 3s-Timeout fuer die
                       # CloseSessionRequest-Antwort plus etwas Puffer ab.

    for (my $i = 0; $i < $max_wait * 5; $i++) {
        return 1 if (!scalar(grep{/cfc.py/} `ps aux`));
        select(undef, undef, undef, 0.2); # 200ms
    }
    return 0;
}

