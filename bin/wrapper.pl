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

# Verzeichnis für Log-Snapshots. BEWUSST im Datenverzeichnis und nicht beim Log:
# Das Logverzeichnis liegt auf der Ramdisk (nach einem Neustart weg) und wird von
# LoxBerry automatisch aufgeräumt, sobald es zu groß wird - genau das hat bei einem
# nächtlichen Ausfall die entscheidenden Stunden gekostet. Geschrieben wird nur im
# Fehlerfall, die Schreiblast auf der Speicherkarte ist also vernachlässigbar.
my $snapshotdir = "$installfolder/data/plugins/$psubfolder";
system("mkdir -p $snapshotdir > /dev/null 2>&1");

foreach $arg (@ARGV) {
    # Nur anhalten, ohne Neustart. cfc.py bekommt durch SIGTERM die Gelegenheit,
    # sich sauber bei der Anlage abzumelden (Einzelheiten in stop_cfc).
    if ($arg eq "stop") {
        stop_cfc($installfolder, $psubfolder);
        exit(0);
    }

    if (($arg eq "restart") || ($arg eq "start") || ($arg eq "boot") || ($arg eq "search")) {

        stop_cfc($installfolder, $psubfolder);

        if ($arg eq "restart" || $arg eq "start") {
            LOGINF "Starte ComfoConnect...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile --snapshotdir $snapshotdir > /dev/null 2>>$logfile &");
            exit(0);
        }

        # Nur beim Systemstart (@reboot-Cronjob): Netzwerk und Broker sind da noch
        # nicht zwangslaeufig bereit. Ein Klick in der Oberflaeche darf diese
        # Wartezeit NICHT mitnehmen - dort wirkte sie wie ein haengender Start.
        if ($arg eq "boot") {
            LOGINF "Warte bis der Loxberry bereit ist";
            sleep(20);
            LOGINF "Starte ComfoConnect...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile --snapshotdir $snapshotdir > /dev/null 2>>$logfile &");
            exit(0);
        }

        if ($arg eq "search") {
            LOGINF "Suche Lüftungsanlage...";
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile --snapshotdir $snapshotdir --search > /dev/null 2>>$logfile");
            exit(0);
        }
    }

    # Vom Überwachungs-Cronjob aufgerufen. Der Cronjob existiert überhaupt nur, wenn
    # in den Plugin-Einstellungen BEIDES aktiviert ist: die Überwachung der
    # Sensorwerte UND der automatische Neustart (siehe WatchdogCronjob() in
    # index.cgi). Beides wird hier trotzdem nochmal geprüft - der Cronjob könnte aus
    # einer früheren Konfiguration übrig geblieben sein, und ein Neustart gegen den
    # ausdrücklichen Wunsch des Benutzers wäre das Letzte, was passieren darf.
    #
    # Geprüft wird bridge_last_sensor_data: ob überhaupt noch Messwerte von der
    # Anlage ankommen. Das ist bewusst das einzige Kriterium für "hängt" - die
    # Verbindung kann stehen und Keepalives können beantwortet werden, während
    # trotzdem keine Sensordaten mehr fließen (genau der Fall, den man sonst nirgends
    # bemerkt). Nur relevant, wenn schon Sensoren registriert waren, sonst schlüge es
    # direkt nach dem Start an, bevor die erste Registrierung überhaupt durch ist.
    #
    # Ein gar nicht laufender Prozess wird ebenfalls neu gestartet - wer den
    # automatischen Neustart einschaltet, will genau das.
    if ($arg eq "checkwatchdog") {
        my $jsonobj = LoxBerry::JSON->new();
        my $pcfg = $jsonobj->open(filename => "$installfolder/config/plugins/$psubfolder/$psubfolder.json");

        if (!$pcfg || !$pcfg->{'MAIN'}->{'SENSORWATCH_ENABLED'} || !$pcfg->{'MAIN'}->{'SENSORWATCH_RESTART'}) {
            exit(0);
        }

        my $timeout_sec = $pcfg->{'MAIN'}->{'SENSORWATCH_TIMEOUT_SEC'};
        $timeout_sec = 60 if (!$timeout_sec || $timeout_sec !~ /^\d+$/ || $timeout_sec < 10);

        my $running = scalar(cfc_pids($installfolder, $psubfolder));
        my $stale_data = 0;
        my $reason = "sendet seit über ${timeout_sec}s keine Sensordaten mehr (Verbindung hängt vermutlich)";

        if (-e $statusfile) {
            local $/ = undef;
            if (open(my $fh, '<', $statusfile)) {
                my $json_text = <$fh>;
                close($fh);
                my $status = eval { decode_json($json_text) };
                if ($status) {
                    if (($status->{sensors_registered} // 0) > 0 && $status->{bridge_last_sensor_data}) {
                        my $data_age = time() - $status->{bridge_last_sensor_data};
                        $stale_data = ($data_age > $timeout_sec) ? 1 : 0;
                    }
                }
            }
        }

        if (!$running || $stale_data) {
            LOGWARN "Überwachung: ComfoConnect " . ($running ? $reason : "läuft nicht") . " - starte neu.";
            if ($running) {
                stop_cfc($installfolder, $psubfolder);
                # Kurze, best-effort Wartezeit auf den sauberen Shutdown (siehe Kommentar
                # oben bei "restart") - falls der Prozess wirklich haengt (genau der Fall,
                # den der Watchdog hier abfaengt), reagiert er evtl. gar nicht auf SIGTERM;
                # dann verstreicht die Wartezeit einfach ungenutzt und wir starten trotzdem neu.
                wait_for_cfc_exit($installfolder, $psubfolder);
            }
            system("$installfolder/bin/plugins/$psubfolder/cfc.py  --configfile $installfolder/config/plugins/$psubfolder/$psubfolder.json --logfile $logfile --loglevel $loglevel --statusfile $statusfile --snapshotdir $snapshotdir > /dev/null 2>>$logfile &");
        }
        exit(0);
    }
}

##########################################################################
# wait_for_cfc_exit - best-effort, kurze Wartezeit nach dem SIGTERM auf
# cfc.py, bevor ein neuer Prozess gestartet wird. cfc.py bekommt durch das
# reine SIGTERM (statt -9) inzwischen einen Moment, sich per
# CloseSessionRequest sauber bei der Zehnder-Box abzumelden (siehe der
# SIGTERM-Handler in cfc.py) - ohne diese Wartezeit wuerde der naechste
# Prozess sofort parallel dazu starten und moeglicherweise noch auf eine
# Session treffen, die die Box noch nicht losgelassen hat.
#
# Bricht spaetestens nach $max_wait Sekunden ab und laesst den Aufrufer
# einfach weitermachen - haengt der alte Prozess wirklich (z.B. der Fall, den
# der Watchdog behandelt), soll das den Neustart nicht blockieren.
##########################################################################

# Liefert die PIDs der laufenden cfc.py-Prozesse.
#
# BEWUSST nicht mehr `grep{/cfc.py/} `ps aux``: Dieses Muster trifft auch auf die
# eigenen Hilfsprozesse zu. system("pkill -f .../cfc.py >> $logfile") enthaelt
# Umleitungszeichen, Perl startet dafuer eine Shell - und deren Kommandozeile
# enthaelt den Pfad und damit "cfc.py". Dasselbe gilt fuer den Startbefehl mit
# "&". Ergebnis: Die Pruefung sah Prozesse, die gar keine Anlage bedienen, pkill
# erschlug die eigene Shell mit, und ob ein Start oder Neustart durchkam, war
# Glueckssache. Deshalb hier ueber /proc gehen und nur echte Python-Prozesse
# zaehlen - eine Shell hat als argv[0] nie "python".
sub cfc_pids
{
    my ($installfolder, $psubfolder) = @_;
    my $skript = "$installfolder/bin/plugins/$psubfolder/cfc.py";
    my @pids;
    opendir(my $dh, "/proc") or return @pids;
    foreach my $pid (grep { /^\d+$/ } readdir($dh)) {
        next if ($pid == $$);
        open(my $fh, '<', "/proc/$pid/cmdline") or next;
        local $/ = undef;
        my $cmd = <$fh>;
        close($fh);
        next if (!defined($cmd));
        my @argv = split(/\0/, $cmd);
        next if (scalar(@argv) < 2);
        # argv[0] muss der Interpreter sein und argv[1] unser Skript - so kann
        # weder eine Shell noch ein Editor mit derselben Datei mitgezaehlt werden.
        next if ($argv[0] !~ m{(^|/)python[\d.]*$});
        next if ($argv[1] ne $skript);
        push @pids, $pid;
    }
    closedir($dh);
    return @pids;
}

# Beendet alle cfc.py-Prozesse und wartet, bis sie wirklich weg sind.
# Rueckgabe: 1 = beendet, 0 = liefen nicht.
sub stop_cfc
{
    my ($installfolder, $psubfolder) = @_;
    my @pids = cfc_pids($installfolder, $psubfolder);
    if (!scalar(@pids)) {
        LOGINF "ComfoConnect laeuft nicht.";
        return 0;
    }
    LOGINF "Stoppe ComfoConnect (PID " . join(", ", @pids) . ")...";
    # SIGTERM, damit cfc.py sich per CloseSessionRequest sauber bei der Anlage
    # abmelden kann. kill() statt pkill: kein Shell-Aufruf, keine Selbsttreffer.
    kill('TERM', @pids);
    if (!wait_for_cfc_exit($installfolder, $psubfolder)) {
        # Haengt der Prozess wirklich, muss er weg - sonst startet gleich ein
        # zweiter daneben und welcher von beiden die Anlage bedient, ist Zufall.
        # Genau das war als "mal geht es, mal nicht" zu sehen.
        @pids = cfc_pids($installfolder, $psubfolder);
        if (scalar(@pids)) {
            LOGWARN "ComfoConnect reagiert nicht auf SIGTERM - erzwinge das Ende (PID "
                . join(", ", @pids) . ").";
            kill('KILL', @pids);
            wait_for_cfc_exit($installfolder, $psubfolder);
        }
    }
    return 1;
}

sub wait_for_cfc_exit
{
    my ($installfolder, $psubfolder) = @_;
    my $max_wait = 5; # Sekunden. Im Normalfall ist cfc.py nach wenigen
                       # Millisekunden weg: die Zehnder-Box beantwortet den
                       # CloseSessionRequest, indem sie die Verbindung schliesst,
                       # und cfc.py wacht dadurch sofort auf statt sein Timeout
                       # abzuwarten. Die 5s greifen nur, wenn die Box weder
                       # antwortet noch die Verbindung kappt - dann startet der
                       # neue Prozess eben parallel an, was dank eindeutiger
                       # MQTT-Client-ID und takeover=True unkritisch ist.

    for (my $i = 0; $i < $max_wait * 5; $i++) {
        return 1 if (!scalar(cfc_pids($installfolder, $psubfolder)));
        select(undef, undef, undef, 0.2); # 200ms
    }
    return 0;
}

