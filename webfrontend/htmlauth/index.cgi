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

use CGI::Carp qw(fatalsToBrowser);
use CGI qw/:standard/;
use Config::Simple;
use Config::Crontab;
use LoxBerry::Log;
use File::HomeDir;
#use HTML::Entities;
use String::Escape qw( unquotemeta );
use Cwd 'abs_path';
use HTML::Template;
use LoxBerry::System;
use LoxBerry::JSON;
use LoxBerry::IO;
use LoxBerry::Web;
use JSON::PP;
# Kernmodul. Ohne Import-Liste, damit das eingebaute time() unangetastet bleibt
# (der Rest des Skripts erwartet dort ganze Sekunden) - fuer die Altersanzeige der
# Sensordaten wird gezielt Time::HiRes::time() aufgerufen, siehe getStatus().
use Time::HiRes ();
#use warnings;
#use strict;
#no strict "refs"; # we need it for template system and for contructs like ${"skalar".$i} in loops

##########################################################################
# Variables
##########################################################################
my  $cgi = new CGI;
my  $cfg;
my  $lang;
my  $installfolder;
my  $languagefile;
my  $version;
my  $home = File::HomeDir->my_home;
my  $psubfolder;
my  $languagefileplugin;
my  %TPhrases;
my  @heads;
my  %head;
my  @rows;
my  %hash;
my  $maintemplate;
my  $template_title;
my  $phrase;
my  $helplink;
my  @help;
my  $helptext;
my  $saveformdata;
my  $clearcache;
my  %plugin_config;
my  $name;
my  $device;
my  $serial;
my  $crontabtmp = "$lbplogdir/crontab.temp";

##########################################################################
# Read Settings
##########################################################################

# Version of this script
$version = "2.0.0.1";

# Figure out in which subfolder we are installed
$psubfolder = abs_path($0);
$psubfolder =~ s/(.*)\/(.*)\/(.*)$/$2/g;

##########################################################################
# AJAX-Status-Endpoint
##########################################################################
# Wird von main.html per JS jede Sekunde gepollt, damit sich die Statusanzeige
# aktualisiert ohne die ganze Seite (und damit ungespeicherte Formulareingaben)
# neu zu laden.
#
# Steht bewusst so früh wie möglich - noch VOR dem Einlesen der Crontab und vor
# LOGSTART. Beides wird hier nicht gebraucht ($psubfolder ist alles, was
# getStatus() braucht), kostet aber bei jedem einzelnen Aufruf einen Dateizugriff
# samt Parsen, und LOGSTART schreibt zusätzlich bei jedem Aufruf ins CGI-Log -
# einmal pro Sekunde, solange die Seite offen ist, wäre das reine Verschwendung
# und würde das Log zumüllen. Alles Weitere (general.cfg, MQTT-Credentials,
# Template-Laden) liegt ohnehin dahinter.
if ( $cgi->param('ajax_status') || $cgi->url_param('ajax_status') ) {
	my ($status_text, $status_class, $diagnostics, $status_daten) = getStatus($psubfolder);
	print $cgi->header( -type => 'application/json', -charset => 'utf-8' );
	# NOTE: encode_json() (and JSON::PP->new with the default utf8(1)) expects a
	# proper Perl-internal Unicode string and UTF-8-*encodes* it. This script has
	# no "use utf8;" pragma, so string literals like "Läuft" are just the raw
	# UTF-8 *bytes* from the source file (each byte already its own "char", no
	# Unicode flag) - exactly like everywhere else in this script, where that's
	# fine because the bytes get printed through unchanged. encode_json() doesn't
	# know that though: it takes those raw bytes and UTF-8-encodes them *again*,
	# double-encoding every umlaut (e.g. "Läuft" -> "LÃ¤uft" in the browser).
	# utf8(0) tells JSON::PP the strings are already the bytes we want in the
	# output - it only handles the JSON structure (quotes, braces, escaping) and
	# passes string content through untouched, consistent with how the rest of
	# this script (and the HTML::Template output) already handles UTF-8.
	# Sensorwerte separat: Die Tabelle wird BEWUSST nicht bei jedem Abruf neu
	# gebaut und ersetzt - das würde Haken und Eingaben zerstören, die gerade
	# bearbeitet, aber noch nicht gespeichert wurden. Stattdessen kommen nur die
	# Werte, und das JS schreibt sie in die jeweilige Zelle.
	my $werte = {};
	if ($status_daten && ref($status_daten->{werte}) eq 'HASH') {
		for my $pdid (keys %{ $status_daten->{werte} }) {
			my $w = $status_daten->{werte}->{$pdid};
			$werte->{$pdid} = $w->[0] if (ref($w) eq 'ARRAY');
		}
	}

	print JSON::PP->new->utf8(0)->encode({ statustext => $status_text, statusclass => $status_class, diagnostics => $diagnostics, werte => $werte });
	exit;
}

##########################################################################
# Diagnose-Statistik zurücksetzen
##########################################################################
# Hier wird nur eine Markierung abgelegt - das eigentliche Zurücksetzen erledigt
# cfc.py (siehe Langzeitstatistik.reset_angefordert()). Grund: Der laufende Prozess
# hält den Stand ohnehin im Speicher und würde eine hier gelöschte Datei beim
# nächsten Schreiben einfach wiederherstellen. Außerdem gehören die Zähler des
# laufenden Betriebs mit zurückgesetzt, und an die kommt nur er heran.
#
# Nur per POST: Ein Aufruf, der Daten verwirft, darf nicht durch einen simplen
# Link-Aufruf oder den Vorablader des Browsers ausgelöst werden können.
if ( $cgi->param('ajax_reset_stats') ) {
	my $ok = 0;
	my $meldung = "Nur per POST erlaubt.";

	if ((($ENV{'REQUEST_METHOD'} || '') eq 'POST')) {
		my $verzeichnis = "$lbhomedir/data/plugins/$psubfolder";
		if (open(my $fh, '>', "$verzeichnis/statistik.reset")) {
			close($fh);
			$ok = 1;
			# Der Status-Thread von cfc.py sieht die Markierung im Sekundentakt. Läuft
			# das Plugin gerade nicht, bleibt sie liegen und greift beim nächsten Start -
			# beides in Ordnung, deshalb hier kein Fehler.
			$meldung = "Statistik wird zurückgesetzt.";
		} else {
			$meldung = "Konnte nicht schreiben: $!";
		}
	}

	print $cgi->header( -type => 'application/json', -charset => 'utf-8' );
	print JSON::PP->new->utf8(0)->encode({ ok => $ok, meldung => $meldung });
	exit;
}

##########################################################################
# Read crontab
##########################################################################
# Erst hier, nach dem AJAX-Endpoint oben - für den reinen Statusabruf wird die
# Crontab nicht gebraucht.

my $crontab = new Config::Crontab;
$crontab->system(1); ## Wichtig, damit der User im File berücksichtigt wird
$crontab->read( -file => "$lbhomedir/system/cron/cron.d/$lbpplugindir" );

#my $log = LoxBerry::Log->new(name => 'CGI',);
LOGSTART("ComfoConnect CGI");

# Start with HTML header
# print $cgi->header(
	# type	=>	'text/html',
	# charset	=>	'utf-8',
# ); 
print "Content-type: text/html\n\n";

# Read general config
$cfg	 	= new Config::Simple("$home/config/system/general.cfg") or die $cfg->error();
$installfolder	= $cfg->param("BASE.INSTALLFOLDER");
$lang		= $cfg->param("BASE.LANG");

# Create temp folder if not already exist
if (!-d "/var/run/shm/$psubfolder") {
	system("mkdir -p /var/run/shm/$psubfolder > /dev/null 2>&1");
}
# Check for temporary log folder
if (!-e "$installfolder/log/plugins/$psubfolder/shm") {
	system("ln -s /var/run/shm/$psubfolder $installfolder/log/plugins/$psubfolder/shm > /dev/null 2>&1");
}
######################################################################
# Read MQTT connection details and credentials from MQTT plugin
######################################################################

my  $mqttcred = LoxBerry::IO::mqtt_connectiondetails();

# Set parameters coming in - get over post
if ( $cgi->url_param('lang') ) {
	$lang = quotemeta( $cgi->url_param('lang') );
}
elsif ( $cgi->param('lang') ) {
	$lang = quotemeta( $cgi->param('lang') );
}
if ( $cgi->url_param('saveformdata') ) {
	$saveformdata = quotemeta( $cgi->url_param('saveformdata') );
}
elsif ( $cgi->param('saveformdata') ) {
	$saveformdata = quotemeta( $cgi->param('saveformdata') );
}
if ( $cgi->url_param('clearcache') ) {
	$clearcache = quotemeta( $cgi->url_param('clearcache') );
}
elsif ( $cgi->param('clearcache') ) {
	$clearcache = quotemeta( $cgi->param('clearcache') );
}	
if ( $cgi->url_param('rescan') ) {
	$rescan = quotemeta( $cgi->url_param('rescan') );
}
elsif ( $cgi->param('rescan') ) {
	$rescan = quotemeta( $cgi->param('rescan') );
}

##########################################################################
# Initialize html templates
##########################################################################

# Header # At the moment not in HTML::Template format
#$headertemplate = HTML::Template->new(filename => "$installfolder/templates/system/$lang/header.html");
  
# Main
$maintemplate = HTML::Template->new(
	filename => "$installfolder/templates/plugins/$psubfolder/multi/main.html",
	global_vars => 1,
	loop_context_vars => 1,
	die_on_bad_params => 0,
	associate => $cgi,
);

# Footer # At the moment not in HTML::Template format
#$footertemplate = HTML::Template->new(filename => "$installfolder/templates/system/$lang/footer.html");

##########################################################################
# Translations
##########################################################################

# Init Language
# Clean up lang variable
$lang         =~ tr/a-z//cd;
$lang         = substr($lang,0,2);

# Read Plugin transations
# Read English language as default
# Missing phrases in foreign language will fall back to English
$languagefileplugin 	= "$installfolder/templates/plugins/$psubfolder/en/language.txt";
Config::Simple->import_from($languagefileplugin, \%TPhrases);

# If there's no language phrases file for choosed language, use english as default
if (!-e "$installfolder/templates/system/$lang/language.dat")
{
  $lang = "en";
}

# Read foreign language if exists and not English
$languagefileplugin = "$installfolder/templates/plugins/$psubfolder/$lang/language.txt";
if ((-e $languagefileplugin) and ($lang ne 'en')) {
	# Now overwrite phrase variables with user language
	Config::Simple->import_from($languagefileplugin, \%TPhrases);
}

# Parse Language phrases to html templates
while (my ($name, $value) = each %TPhrases){
	$maintemplate->param("T::$name" => $value);
	#$headertemplate->param("T::$name" => $value);
	#$footertemplate->param("T::$name" => $value);
}

##########################################################################
# Main program
##########################################################################

&form;

exit;

#####################################################
# 
# Subroutines
#
#####################################################

#####################################################
# Form-Sub
#####################################################

sub form 
{
	# ReScan Zehnder UUID
	if ( $rescan ) {
		system("perl $installfolder/bin/plugins/$psubfolder/wrapper.pl search > /dev/null 2>&1");
    }
    
    # Read plugin config
    my $cfgfile = "$lbpconfigdir/comfoconnect.json";
    LOGINF $cfgfile;

    my $jsonobj = LoxBerry::JSON->new();
    my $pcfg = $jsonobj->open(filename => $cfgfile);
        
    if (!$pcfg) {
        LOGERR "No configfile found";
        exit;
    }
    
    # Speichere die MQTT Credentials
    $pcfg->{'MAIN'}->{'MQTTUSER'} = $mqttcred->{brokeruser};
    $pcfg->{'MAIN'}->{'MQTTPASS'} = $mqttcred->{brokerpass};
    $pcfg->{'MAIN'}->{'MQTTSERVER'} = $mqttcred->{brokerhost};
    $pcfg->{'MAIN'}->{'MQTTPORT'} = $mqttcred->{brokerport};
    $pcfg->{'MAIN'}->{'MQTTTOPIC'} = "ComfoConnect/";
    # use Data::Dumper;               # Perl core module
    # print Dumper($pcfg);
    $jsonobj->write();

	# If the form was saved, update config file
    if ( $saveformdata ) {
        $pcfg->{'MAIN'}->{'IPLANC'} = $cgi->param('iplanc');
        $pcfg->{'MAIN'}->{'PIN'} = $cgi->param('pin');

        # Überwachung der Sensorwerte. Checkboxen liefern nur einen Wert, wenn sie
        # angehakt sind.
        $pcfg->{'MAIN'}->{'SENSORWATCH_ENABLED'} = $cgi->param('sensorwatch_enabled') ? "1" : "0";

        # Zeitfeld und Neustart-Checkbox sind im Formular deaktiviert, solange die
        # Überwachung aus ist - deaktivierte Felder sendet der Browser gar nicht mit.
        # Deshalb nur übernehmen, wenn die Überwachung aktiv ist, sonst würde die
        # gespeicherte Zeit bei jedem Speichern mit ausgeschalteter Überwachung auf den
        # Standardwert zurückfallen und die Neustart-Option stillschweigend verloren gehen.
        if ($pcfg->{'MAIN'}->{'SENSORWATCH_ENABLED'} eq "1") {
            my $sensorwatch_timeout = $cgi->param('sensorwatch_timeout');
            if (!$sensorwatch_timeout || $sensorwatch_timeout !~ /^\d+$/ || $sensorwatch_timeout < 10) {
                $sensorwatch_timeout = 60;
            }
            $pcfg->{'MAIN'}->{'SENSORWATCH_TIMEOUT_SEC'} = $sensorwatch_timeout;
            $pcfg->{'MAIN'}->{'SENSORWATCH_RESTART'} = $cgi->param('sensorwatch_restart') ? "1" : "0";
        }

        # Reste der früheren Watchdog-Einstellungen aus Configs vorheriger Versionen
        # entfernen. Sie werden nirgends mehr gelesen (die Überwachung heißt jetzt
        # SENSORWATCH_* und zählt in Sekunden statt Minuten) und würden sonst
        # dauerhaft als toter Ballast in der Datei stehen bleiben.
        delete $pcfg->{'MAIN'}->{'WATCHDOG_ENABLED'};
        delete $pcfg->{'MAIN'}->{'WATCHDOG_THRESHOLD_MIN'};

        # ------------------------------------------------------------------
        # Sensorauswahl
        # ------------------------------------------------------------------
        # Gespeichert wird bewusst nur die ABWEICHUNG vom mitgelieferten Katalog
        # (bin/mqtt_data.py): welche Sensoren abgewählt sind und welche eigenen
        # hinzugefügt wurden. Eine Vollkopie der Liste in der Konfiguration würde
        # neue Sensoren aus einem künftigen Plugin-Update dauerhaft verdecken.
        #
        # Die Formularfelder heißen sensor_on_<pdid>. Ein nicht angehakter Kasten
        # sendet gar nichts - deshalb wird über den Katalog iteriert und nicht über
        # die eingegangenen Parameter, sonst wäre "alles abgewählt" nicht von
        # "Formular kam nie an" zu unterscheiden.
        my $katalog = readSensorCatalog($installfolder, $psubfolder);

        # Eigene Zeilen zuerst: Sie sind ebenfalls an-/abwählbar und müssen dafür
        # unten wie Katalogeinträge behandelt werden.
        my @eigene;
        my %eigene_pdids;
        for my $i (sort { $a <=> $b } map { /^sensor_new_pdid_(\d+)$/ ? $1 : () } $cgi->param) {
            my $pdid = $cgi->param("sensor_new_pdid_$i");
            my $name = $cgi->param("sensor_new_name_$i");
            my $typ  = $cgi->param("sensor_new_type_$i");
            my $push = $cgi->param("sensor_new_push_$i");

            $name = "" if (!defined($name));
            $name =~ s/^\s+|\s+$//g;
            # Nur Zeichen, die als MQTT-Thema unbedenklich sind. Ein "/" oder "#"
            # im Namen würde die Themenstruktur zerlegen bzw. mit den Platzhaltern
            # der Abonnements kollidieren.
            $name =~ s/[^A-Za-z0-9_\-]//g;

            next if (!defined($pdid) || $pdid !~ /^\d+$/ || $name eq "");
            next if (exists $katalog->{$pdid} || $eigene_pdids{$pdid});

            my %e = ( pdid => $pdid + 0, name => $name );
            $e{type} = $typ + 0 if (defined($typ) && $typ =~ /^\d+$/);
            $e{push} = $push + 0 if (defined($push) && $push =~ /^\d+$/ && $push > 0);
            push @eigene, \%e;
            $eigene_pdids{$pdid} = 1;
        }

        my @aus;
        for my $pdid (sort { $a <=> $b } (keys %$katalog, keys %eigene_pdids)) {
            push @aus, $pdid + 0 if (!$cgi->param("sensor_on_$pdid"));
        }

        $pcfg->{'SENSORS'} = { 'aus' => \@aus, 'eigene' => \@eigene };

        $jsonobj->write();

		Cronjob("Uninstall");

		if (($cgi->param('iplanc') ne "") && ($cgi->param('pin') ne "")) {
			system("perl $installfolder/bin/plugins/$psubfolder/wrapper.pl  restart > /dev/null 2>&1");

			# Create Cronjob
			Cronjob("Install");
		}

		# Neustart-Cronjob unabhängig vom Startup-Cronjob verwalten. Nur nötig, wenn
		# die Überwachung läuft UND daraus auch ein Neustart folgen soll - ohne
		# Neustart-Option wertet nur die Statusanzeige aus, dafür braucht es keinen Cron.
		WatchdogCronjob("Uninstall");
		if ($pcfg->{'MAIN'}->{'SENSORWATCH_ENABLED'} eq "1" && $pcfg->{'MAIN'}->{'SENSORWATCH_RESTART'} eq "1") {
			WatchdogCronjob("Install");
		}
	}
	
	# Navbar
	our %navbar;

	$navbar{10}{Name} = "Test";
	$navbar{10}{URL} = 'index.cgi?form=owfs';
	$navbar{10}{active} = 1 if $q->{form} eq "owfs";
	
	$navbar{20}{Name} = "Test2";
	$navbar{20}{URL} = 'index.cgi?form=devices';
	$navbar{20}{active} = 1 if $q->{form} eq "devices";
	
	$navbar{30}{Name} = "$L{'COMMON.LABEL_MQTT'}";
	$navbar{30}{URL} = 'index.cgi?form=mqtt';
	$navbar{30}{active} = 1 if $q->{form} eq "mqtt";
	
	$navbar{98}{Name} = "$L{'COMMON.LABEL_LOG'}";
	$navbar{98}{URL} = 'index.cgi?form=log';
	$navbar{98}{active} = 1 if $q->{form} eq "log";

	$navbar{99}{Name} = "$L{'COMMON.LABEL_CREDITS'}";
	$navbar{99}{URL} = 'index.cgi?form=credits';
	$navbar{99}{active} = 1 if $q->{form} eq "credits";

	# Print Template header
	&lbheader;

	# # Read options and set them for template
	$maintemplate->param( PSUBFOLDER	=> $psubfolder );
	$maintemplate->param( HOST 			=> $ENV{HTTP_HOST} );
	$maintemplate->param( LOGINNAME		=> $ENV{REMOTE_USER} );
	$maintemplate->param( IPLANC 		=> $pcfg->{'MAIN'}->{'IPLANC'});
    $maintemplate->param( PIN 		    => $pcfg->{'MAIN'}->{'PIN'});
    $maintemplate->param( TOPIC 		=> $pcfg->{'MAIN'}->{'MQTTTOPIC'} . "#");

    # Überwachungs-Einstellungen fürs Formular
    $maintemplate->param( SENSORWATCH_ENABLED_CHECKED => ($pcfg->{'MAIN'}->{'SENSORWATCH_ENABLED'} eq "1") ? "checked" : "" );
    $maintemplate->param( SENSORWATCH_RESTART_CHECKED => ($pcfg->{'MAIN'}->{'SENSORWATCH_RESTART'} eq "1") ? "checked" : "" );
    $maintemplate->param( SENSORWATCH_TIMEOUT => $pcfg->{'MAIN'}->{'SENSORWATCH_TIMEOUT_SEC'} || "60" );

    ##
    # Statusanzeige - Logik steckt in getStatus() weiter unten, damit sich der
    # AJAX-Endpoint oben (fürs Live-Polling) und dieser initiale Seitenaufbau
    # dieselbe Auswertung teilen statt sie zweimal zu pflegen.
    ##
    my ($status_text, $status_class, $diagnostics, $status_daten) = getStatus($psubfolder);

    $maintemplate->param( STATUSTEXT => $status_text );
    $maintemplate->param( STATUSCLASS => $status_class );
    $maintemplate->param( DIAGNOSTICS => $diagnostics );

    # Sensortabelle. Wird nur beim Seitenaufbau erzeugt - der 1s-Abruf aktualisiert
    # danach ausschließlich die Wertespalte, damit unbestätigte Änderungen an den
    # Haken und Eingabefeldern nicht überschrieben werden.
    my ($sensortable, $sensors_aktiv, $sensors_gesamt) =
        getSensorTable($installfolder, $psubfolder, $pcfg, $status_daten);
    $maintemplate->param( SENSORTABLE => $sensortable );
    $maintemplate->param( SENSORSAKTIV => $sensors_aktiv );
    $maintemplate->param( SENSORSGESAMT => $sensors_gesamt );
    
    ##
    #handle Template and render index page
    ##
    # handle MQTT details
    my $mqttsubscription =  $pcfg->{'MAIN'}->{'MQTTTOPIC'} . "#";
    my $mqtthint = "Alle Daten werden per MQTT übertragen. Die Subscription dafür lautet <span class='mono'>
                                    $mqttsubscription</span> und wird im MQTT Gateway Plugin automatisch eingetragen.";
    my $mqtthintclass = "hint";

    if(!$mqttcred){
        $mqtthint = "MQTT Gateway Plugin wurde nicht gefunden oder ist nicht konfiguriert.
                                    Das Plugin ComfoConnect funktioniert nur mit korrekt installiertem MQTT Gateway Plugin";
        $mqtthintclass = "notityRedMqtt";
    }

    $maintemplate->param("mqtthint" => $mqtthint);
    $maintemplate->param("mqtthintclass" => $mqtthintclass);

	$maintemplate->param( ROWS => \@rows );

	# Print Template
	print $maintemplate->output;

	# Parse page footer		
	&lbfooter;

	exit;

}

#####################################################
# Status-Sub - liest die Heartbeat-Datei, die cfc.py auf der Ramdisk schreibt.
#
# Prüfreihenfolge (jede Stufe schwerwiegender als eine reine "Warnung"):
#   1. Statusdatei fehlt komplett             -> Plugin läuft nicht
#   2. !sensors_ready                          -> Registriere Sensoren. Gilt fuer die
#                                                 allererste Startphase genauso wie
#                                                 fuer jeden spaeteren Reconnect
#                                                 mitten im Betrieb (siehe
#                                                 comfoconnect.py: sensors_ready).
#   3. MQTT getrennt                          -> kann ohnehin nichts liefern
#   4. last_alive_ping zu alt (>30s)          -> Verbindungs-Thread tot/hängt
#   5. last_sensor_data aelter als der         -> Verbindung/Thread laufen zwar noch,
#      eingestellte Wert, obwohl Sensoren         aber die Anlage schickt nichts mehr.
#      registriert sind UND die Ueberwachung      Der Prozess "lebt" (alive_ping bleibt
#      eingeschaltet ist                          frisch, weil die Leseschleife einfach
#                                                 weiterdreht) und Keepalives werden
#                                                 beantwortet - ohne diese Pruefung
#                                                 saehe das faelschlich wie "laeuft
#                                                 einwandfrei" aus. Ist die Ueberwachung
#                                                 nicht aktiviert, wird hier bewusst gar
#                                                 nichts ausgewertet und der Status
#                                                 bleibt unveraendert.
#   6. Alles obige unauffällig                 -> Laeuft, X Sensoren + Alter der zuletzt
#                                                 empfangenen Sensordaten. Das Alter ist
#                                                 der eigentliche Lebensbeweis: eine
#                                                 statische Meldung wie "X Sensoren
#                                                 registriert" sieht auch dann noch gut
#                                                 aus, wenn laengst nichts mehr fliesst.
#                                                 Wurden Sensoren uebersprungen (von
#                                                 dieser Anlage nicht unterstuetzt),
#                                                 erscheint "X von Y" als Warnung.
#
# Genutzt sowohl beim initialen Seitenaufbau (sub form) als auch vom
# AJAX-Status-Endpoint ganz oben, den main.html per JS periodisch abfragt.
#####################################################

sub getStatus
{
	my $psubfolder = shift;

	my $statusfile = "/var/run/shm/$psubfolder/status.json";
	my $status_text = "Unbekannt";
	# cc-status-ok (gruen) / cc-status-warn (gelb) / cc-status-error (rot) - eigene
	# Klassen in main.html, da "hint" bei LoxBerry nur ein kleiner grauer Hinweistext
	# ist (keine Farbe) und es keine passende gruene System-Klasse gibt.
	my $status_class = "cc-status-warn";
	my $diagnostics = "";
	# Die rohen Statusdaten werden mit zurückgegeben - die Sensortabelle und der
	# AJAX-Endpoint brauchen daraus die Live-Werte, und die Datei ein zweites Mal
	# zu öffnen wäre bei einem Abruf pro Sekunde reine Verschwendung.
	my $status;

	if (-e $statusfile) {
		local $/ = undef;
		if (open(my $fh, '<', $statusfile)) {
			my $json_text = <$fh>;
			close($fh);
			$status = eval { decode_json($json_text) };
			if ($status) {
				# Betriebsstatistik. Bewusst hier oben und unabhängig von den
				# Statuszweigen weiter unten: Die Diagnose soll auch (und gerade) dann
				# etwas anzeigen, wenn der Status "Gestört" meldet.
				$diagnostics = getDiagnostics($status, $psubfolder);

				# Time::HiRes::time() statt time(): cfc.py schreibt die Zeitstempel als
				# Fliesskommazahl (Python time.time()). Mit dem eingebauten, auf ganze
				# Sekunden abgeschnittenen time() ergaebe die Differenz einen um bis zu
				# einer Sekunde falschen Wert - bei einer Anzeige, die im Normalbetrieb
				# im Millisekundenbereich liegt, ist das der komplette Messbereich.
				my $now = Time::HiRes::time();
				my $alive_age = defined($status->{bridge_last_alive_ping}) ? $now - $status->{bridge_last_alive_ping} : undef;
				my $data_age  = defined($status->{bridge_last_sensor_data}) ? $now - $status->{bridge_last_sensor_data} : undef;
				my $mqtt_ok = $status->{mqtt_connected} ? 1 : 0;
				my $sensors_reg = $status->{sensors_registered} // 0;
				my $sensors_exp = $status->{sensors_expected} // 0;
				# Fehlt das Feld (z.B. Statusdatei eines aelteren Plugin-Stands, noch
				# nicht ueberschrieben) als "fertig" behandeln statt dauerhaft
				# "Registriere Sensoren" vorzutaeuschen - der neue Prozess ueberschreibt
				# die Datei ohnehin binnen 1s mit dem korrekten Feld.
				my $sensors_ready = exists($status->{sensors_ready}) ? ($status->{sensors_ready} ? 1 : 0) : 1;

				# Einstellungen der Sensorwert-Überwachung. cfc.py schreibt sie mit in
				# die Statusdatei, damit dieser (alle 2s per AJAX aufgerufene) Pfad nicht
				# zusätzlich die Config-Datei öffnen muss.
				my $watch_on = $status->{sensorwatch_enabled} ? 1 : 0;
				my $watch_timeout = $status->{sensorwatch_timeout_sec} // 60;

				if (!$sensors_ready) {
					# sensors_registered zaehlt currently bestaetigte Sensoren waehrend
					# die Schleife in cfc.py laeuft (write_status_loop() schreibt jede
					# Sekunde neu) - live mitgezaehlter Fortschritt statt eines
					# statischen Textes, der 60-180s lang unveraendert dasteht.
					$status_text = $sensors_exp > 0
						? "Registriere Sensoren ($sensors_reg von $sensors_exp)"
						: "Registriere Sensoren";
					$status_class = "cc-status-warn";
				} elsif (!$mqtt_ok) {
					$status_text = "MQTT getrennt (verbindet automatisch neu)";
					$status_class = "cc-status-error";
				} elsif (!defined($alive_age) || $alive_age > 30) {
					$status_text = "Gestört - keine Verbindung zur ComfoConnect LAN C";
					$status_class = "cc-status-error";
				} elsif ($watch_on && $sensors_reg > 0 && (!defined($data_age) || $data_age > $watch_timeout)) {
					$status_text = "Gestört - seit über ${watch_timeout}s keine Sensordaten mehr empfangen";
					$status_class = "cc-status-error";
				} else {
					# Alter der letzten Sensordaten mit anzeigen: eine reine
					# "X Sensoren registriert"-Meldung steht auch dann noch unveraendert
					# da, wenn seit Minuten nichts mehr ankommt. Der mitlaufende Zaehler
					# (Seite pollt jede Sekunde) ist der sichtbare Lebensbeweis - und er
					# ist auch dann da, wenn die Ueberwachung ausgeschaltet ist, nur eben
					# ohne dass daraus jemals eine Stoerung wird.
					#
					# Wurden Sensoren uebersprungen, wird das als Warnung angezeigt statt
					# als Fehler: nicht jede Anlage und nicht jeder Firmware-Stand kennt
					# alle bekannten Messwerte, das ist der Normalfall und kein Defekt.
					# Sichtbar sein soll es trotzdem - sonst wundert man sich, warum ein
					# erwarteter Wert in Loxone fehlt.
					if ($sensors_exp > 0 && $sensors_reg < $sensors_exp) {
						$status_text = "Läuft - $sensors_reg von $sensors_exp Sensoren aktiv";
						$status_class = "cc-status-warn";
					} else {
						$status_text = "Läuft - $sensors_reg Sensoren aktiv";
						$status_class = "cc-status-ok";
					}
					if (defined($data_age)) {
						$status_text .= ", letzte Daten " . formatAge($data_age);
					}
				}
			}
		}
	} else {
		$status_text = "Plugin läuft nicht (Statusdatei fehlt)";
		$status_class = "cc-status-error";
		# Sonst bliebe der Diagnose-Kasten hier komplett leer und sähe defekt aus.
		$diagnostics = "<div class=\"cc-diag-runtime\">Keine Diagnosedaten &ndash; das Plugin läuft gerade nicht.</div>";
	}

	return ($status_text, $status_class, $diagnostics, $status);
}

#####################################################
# Alter in lesbarer Form: unter einer Sekunde in Millisekunden ("vor 340ms"),
# darueber in ganzen Sekunden ("vor 12s") bzw. ab einer Minute als "vor 3m 05s".
#
# Der uebergebene Wert ist eine Fliesskommazahl (siehe getStatus) - deshalb
# ueberall explizit runden bzw. abschneiden. Ohne das erschiene im Normalbetrieb,
# wo die Werte im Sekundenbruchteil-Bereich liegen, eine Zahl mit einem Dutzend
# Nachkommastellen.
#
# Negative Werte sind moeglich, wenn die Uhr zwischen dem Schreiben der
# Statusdatei und dem Lesen hier minimal zurueckspringt (NTP) - dann auf 0
# klemmen statt ein unsinniges "vor -1s" anzuzeigen.
#####################################################

sub getDiagnostics
{
	my ($status, $psubfolder) = @_;
	return "" if (!$status);

	my $now = Time::HiRes::time();
	my $stats = $status->{stats} || {};

	# Langzeitwerte aus data/plugins/<plugin>/statistik.json (von cfc.py mitgeführt).
	# Fehlen sie, läuft eine ältere Version oder es gibt noch keine Datei - dann
	# entfällt die Spalte einfach, statt überall "0" anzuzeigen.
	my $gesamt = $status->{gesamt};
	my $hat_gesamt = ($gesamt && ref($gesamt) eq 'HASH') ? 1 : 0;

	# Zeile nur zeigen, wenn der Zähler überhaupt schon angesprungen ist - eine
	# Tabelle voller Nullen sagt weniger als eine kurze Liste dessen, was war.
	my @zeilen;
	my $zeile = sub {
		my ($name, $schluessel, $anzahl, $zeitstempel, $hinweis) = @_;
		my $summe = $hat_gesamt ? ($gesamt->{$schluessel} || 0) : 0;
		$anzahl ||= 0;
		return if (!$anzahl && !$summe);
		my $wann = defined($zeitstempel) ? formatSince($now - $zeitstempel) : "&ndash;";
		my $spalte_gesamt = $hat_gesamt
			? "<td class=\"cc-diag-num cc-diag-total\">$summe</td>" : "";
		push @zeilen, "<tr><td>$name</td><td class=\"cc-diag-num\">$anzahl</td>"
			. $spalte_gesamt
			. "<td>$wann</td><td class=\"cc-diag-note\">$hinweis</td></tr>";
	};

	$zeile->("Verbindungsabbrüche", "verbindungsabbrueche",
		$stats->{verbindungsabbrueche}, $stats->{letzter_verbindungsabbruch},
		"Verbindung zur Anlage neu aufgebaut");
	$zeile->("Sitzungserneuerungen", "sitzungserneuerungen",
		$stats->{sitzungserneuerungen}, $stats->{letzte_sitzungserneuerung},
		"Anlage hatte die Sitzung verworfen");
	$zeile->("Zeitüberschreitungen", "antwort_timeouts",
		$stats->{antwort_timeouts}, $stats->{letzter_timeout},
		"Anlage antwortete nicht rechtzeitig");
	$zeile->("Verspätete Antworten", "verworfene_antworten",
		$stats->{verworfene_antworten}, undef,
		"trafen nach der Zeitüberschreitung ein");
	$zeile->("Übersprungene Sensoren", "uebersprungene_sensoren",
		$stats->{uebersprungene_sensoren}, undef,
		"von dieser Anlage nicht unterstützt");
	$zeile->("MQTT-Abbrüche", "mqtt_abbrueche",
		$status->{mqtt_abbrueche}, $status->{mqtt_letzter_abbruch},
		"Verbindung zum Broker");

	my $laufzeit = defined($status->{plugin_start})
		? formatDuration($now - $status->{plugin_start}) : "unbekannt";

	my $html = "<div class=\"cc-diag-runtime\">Laufzeit seit dem letzten Start: <b>$laufzeit</b></div>";

	if (!@zeilen) {
		$html .= "<div class=\"cc-diag-none\">Seit dem Start keine Auffälligkeiten.</div>";
	} else {
		my $kopf_gesamt = $hat_gesamt ? "<th class=\"cc-diag-num\">Gesamt</th>" : "";
		$html .= "<table class=\"cc-diag\">"
			. "<tr><th>Ereignis</th><th class=\"cc-diag-num\">Aktueller Lauf</th>$kopf_gesamt<th>Zuletzt</th><th></th></tr>"
			. join("", @zeilen) . "</table>";
	}

	# Bezugsgröße für die Gesamtspalte. Ohne die ist sie nicht zu deuten: "12
	# Abbrüche" heißt etwas völlig anderes über drei Tage als über ein halbes Jahr.
	# Die Anzahl der Starts gehört mit dazu - häufige Neustarts sind selbst ein
	# Befund, und ohne sie sähe eine hohe Gesamtzahl nach einem Anlagenproblem aus,
	# obwohl in Wahrheit nur oft neu gestartet wurde.
	if ($hat_gesamt && $status->{gesamt_seit}) {
		my $starts = $status->{gesamt_neustarts} || 0;
		$html .= "<div class=\"cc-diag-total-note\">Gesamt erfasst über "
			. formatDuration($now - $status->{gesamt_seit})
			. ($starts ? " und $starts Start" . ($starts == 1 ? "" : "s") : "")
			. " &ndash; diese Werte überstehen einen Neustart.</div>";
	}

	# Hinweis auf gespeicherte Störungsberichte. Wichtig genug für eine eigene
	# Zeile: Diese Dateien überleben das automatische Aufräumen der Logs und sind
	# im Zweifel das Einzige, womit sich ein nächtlicher Ausfall noch nachvollziehen
	# lässt. Ohne diesen Hinweis wüsste niemand, dass es sie überhaupt gibt.
	my $berichte = $status->{stoerungsberichte} || 0;
	if ($berichte) {
		my $wann = defined($status->{letzter_stoerungsbericht})
			? " (zuletzt " . formatSince($now - $status->{letzter_stoerungsbericht}) . ")" : "";
		$html .= "<div class=\"cc-diag-reports\">$berichte Störungsbericht"
			. ($berichte == 1 ? "" : "e") . " gespeichert$wann "
			. "&ndash; unter <span class=\"mono\">data/plugins/$psubfolder/</span></div>";
	}

	return $html;
}

#####################################################
# Den mitgelieferten Sensorkatalog aus bin/mqtt_data.py lesen.
#
# Ja, das ist eine Python-Datei, die hier mit einem regulären Ausdruck gelesen
# wird - und normalerweise wäre das eine schlechte Idee. Hier ist es vertretbar:
# Die Datei gehört zum Plugin, hat ein streng gleichförmiges Format, und die
# Alternative wäre gewesen, den Katalog zusätzlich in einer zweiten Datei zu
# führen. Zwei Quellen, die auseinanderlaufen können, wären der größere Schaden.
#
# Bewusst NICHT aus der Statusdatei: Die Sensortabelle muss sich auch dann
# bedienen lassen, wenn das Plugin gerade nicht läuft - gerade dann will man
# vielleicht etwas abwählen.
#####################################################

sub readSensorCatalog
{
	my ($installfolder, $psubfolder) = @_;
	my %katalog;

	my $datei = "$installfolder/bin/plugins/$psubfolder/mqtt_data.py";
	open(my $fh, '<', $datei) or return \%katalog;
	local $/ = undef;
	my $inhalt = <$fh>;
	close($fh);

	# Kommentarzeilen entfernen, damit auskommentierte Beispiele nicht als
	# echte Einträge gelesen werden.
	$inhalt =~ s/^\s*#.*$//mg;

	while ($inhalt =~ /(\d+)\s*:\s*\{(.*?)\}/gs) {
		my ($pdid, $rumpf) = ($1, $2);
		my %e;
		$e{NAME} = $1 if ($rumpf =~ /'NAME'\s*:\s*'([^']*)'/);
		$e{PUSH} = $1 if ($rumpf =~ /'PUSH'\s*:\s*(\d+)/);
		$e{CONV} = $1 if ($rumpf =~ /'CONV'\s*:\s*['"](.*?)['"]/);
		$e{PRODUCT} = $1 if ($rumpf =~ /'ONLY_WITH_PRODUCT'\s*:\s*(\d+)/);
		$katalog{$pdid} = \%e if ($e{NAME});
	}

	return \%katalog;
}

#####################################################
# Nachschlagewerk aus bin/pdo_katalog.txt (aus PROTOCOL-PDO.md erzeugt).
#
# Nur Komfort: Trägt jemand eine eigene pdid ein, die im Zehnder-Protokoll
# dokumentiert ist, kann die Oberfläche Typ und Bedeutung vorschlagen, statt
# raten zu lassen. Fehlt die Datei, entfällt der Vorschlag - mehr nicht.
#####################################################

sub readPdoDocs
{
	my ($installfolder, $psubfolder) = @_;
	my %doku;

	open(my $fh, '<', "$installfolder/bin/plugins/$psubfolder/pdo_katalog.txt") or return \%doku;
	while (my $z = <$fh>) {
		next if ($z =~ /^\s*#/);
		chomp $z;
		my ($pdid, $typ, $beschr) = split(/\|/, $z, 3);
		next if (!defined($typ) || $pdid !~ /^\d+$/);
		$doku{$pdid} = { typ => $typ, beschr => (defined($beschr) ? $beschr : "") };
	}
	close($fh);

	return \%doku;
}

#####################################################
# Die Sensortabelle aufbauen.
#
# Liefert (html, anzahl_aktiv, anzahl_gesamt) - die beiden Zahlen stehen im
# zugeklappten Zustand in der Kopfzeile, damit man ohne Aufklappen sieht, wie
# viele Sensoren überhaupt aktiv sind.
#####################################################

sub getSensorTable
{
	my ($installfolder, $psubfolder, $pcfg, $status) = @_;

	my $katalog = readSensorCatalog($installfolder, $psubfolder);
	my $doku    = readPdoDocs($installfolder, $psubfolder);

	my %aus = map { $_ => 1 } @{ $pcfg->{'SENSORS'}->{'aus'} || [] };
	my @eigene = @{ $pcfg->{'SENSORS'}->{'eigene'} || [] };

	# Live-Werte aus der Statusdatei. Fehlen sie (Plugin gestoppt, oder ein Sensor
	# hat noch nie gesendet), bleibt die Spalte leer statt eine Null vorzutäuschen.
	my $werte = ($status && ref($status->{werte}) eq 'HASH') ? $status->{werte} : {};

	my @zeilen;
	my $aktiv = 0;
	my $gesamt = 0;

	my $zeile = sub {
		my ($pdid, $name, $push, $hinweis, $eigen, $typ, $idx) = @_;
		$gesamt++;
		my $an = $aus{$pdid} ? 0 : 1;
		$aktiv++ if ($an);

		my ($wert, $alter) = ("", "");
		if (ref($werte->{$pdid}) eq 'ARRAY') {
			$wert = $werte->{$pdid}->[0];
			$wert = "" if (!defined($wert));
			$wert =~ s/</&lt;/g;
		}

		my $klasse = $an ? "" : " cc-sensor-aus";
		my $html = "<tr class=\"cc-sensor-row$klasse\" data-pdid=\"$pdid\">";
		$html .= "<td><input type=\"checkbox\" name=\"sensor_on_$pdid\" "
			. ($an ? "checked " : "") . "/></td>";
		$html .= "<td class=\"cc-sensor-pdid\">$pdid</td>";

		if ($eigen) {
			# Eigene Zeilen bleiben bearbeitbar - sonst müsste man sie zum Korrigieren
			# eines Tippfehlers löschen und neu anlegen.
			$html .= "<td><input type=\"text\" class=\"cc-sensor-name\" "
				. "name=\"sensor_new_name_$idx\" value=\"$name\" /></td>";
			$html .= "<td><input type=\"number\" class=\"cc-sensor-push\" min=\"0\" "
				. "name=\"sensor_new_push_$idx\" value=\"" . ($push || "") . "\" /></td>";
			$html .= "<td class=\"cc-sensor-val\" id=\"sv$pdid\">$wert</td>";
			$html .= "<td class=\"cc-sensor-note\">$hinweis"
				. "<input type=\"hidden\" name=\"sensor_new_pdid_$idx\" value=\"$pdid\" />"
				. "<input type=\"hidden\" name=\"sensor_new_type_$idx\" value=\"$typ\" />"
				. " <a href=\"#\" class=\"cc-sensor-del\" title=\"Zeile entfernen\">&#10005;</a></td>";
		} else {
			$html .= "<td class=\"cc-sensor-name-fix\">$name</td>";
			$html .= "<td class=\"cc-sensor-push-fix\">" . ($push ? "${push}s" : "&ndash;") . "</td>";
			$html .= "<td class=\"cc-sensor-val\" id=\"sv$pdid\">$wert</td>";
			$html .= "<td class=\"cc-sensor-note\">$hinweis</td>";
		}
		$html .= "</tr>";
		push @zeilen, $html;
	};

	for my $pdid (sort { $a <=> $b } keys %$katalog) {
		my $e = $katalog->{$pdid};
		my $hinweis = "";
		$hinweis = "nur mit ComfoCool" if (($e->{PRODUCT} || 0) == 6);
		$zeile->($pdid, $e->{NAME}, $e->{PUSH}, $hinweis, 0);
	}

	my $idx = 0;
	for my $e (@eigene) {
		# Kollidierende Einträge überspringen. Über die Oberfläche können sie gar
		# nicht entstehen (das Speichern weist sie ab, cfc.py ebenso), wohl aber
		# durch eine von Hand bearbeitete Konfiguration - dann stünde die pdid hier
		# zweimal, mit zwei Haken, die sich gegenseitig überschreiben.
		next if (exists $katalog->{ $e->{pdid} });
		$zeile->($e->{pdid}, $e->{name}, $e->{push}, "eigener Eintrag", 1,
			(defined($e->{type}) ? $e->{type} : 1), $idx++);
	}

	my $html = "<table class=\"cc-sensors\">"
		. "<tr><th></th><th>pdid</th><th>Name (MQTT-Thema)</th><th>Intervall</th>"
		. "<th>Wert</th><th></th></tr>"
		. join("", @zeilen) . "</table>";

	# Vorlage für neue Zeilen: liegt versteckt im Formular und wird von JS geklont.
	# Der Zähler startet hinter den bereits vorhandenen eigenen Zeilen, damit die
	# Feldnamen eindeutig bleiben.
	$html .= "<div class=\"cc-sensor-add\">"
		. "<a href=\"#\" id=\"btnsensoradd\">+ Sensor hinzufügen</a>"
		. "<span class=\"cc-sensor-addhint\">pdid eingeben &ndash; Typ und Bedeutung "
		. "werden vorgeschlagen, sofern im Zehnder-Protokoll dokumentiert.</span>"
		. "<input type=\"hidden\" id=\"sensornextidx\" value=\"$idx\" />"
		. "</div>";

	# Die Doku als JSON für das Formular. Nur die pdids, die noch nicht in Gebrauch
	# sind - für alles andere gäbe es ohnehin schon eine Zeile.
	my %frei;
	for my $pdid (keys %$doku) {
		next if (exists $katalog->{$pdid});
		$frei{$pdid} = $doku->{$pdid};
	}
	$html .= "<script>var ccPdoDocs = " . JSON::PP->new->utf8(0)->canonical->encode(\%frei) . ";</script>";

	return ($html, $aktiv, $gesamt);
}

#####################################################
# "Wie lange ist das her" in grober, lesbarer Form.
#
# Getrennt von formatAge(): Das dort ist auf den Sekundenbereich ausgelegt
# (Altersanzeige der Sensordaten, im Normalbetrieb Millisekunden). Für Ereignisse,
# die auch Tage zurückliegen können, käme dort "vor 2880m 00s" heraus - formal
# richtig, aber niemand rechnet das im Kopf in zwei Tage um.
#####################################################

sub formatSince
{
	my $s = shift;
	return "unbekannt" if (!defined($s));
	$s = 0 if ($s < 0);

	return sprintf("vor %ds", int($s))      if ($s < 60);
	return sprintf("vor %dm", int($s / 60)) if ($s < 3600);
	return sprintf("vor %dh", int($s / 3600)) if ($s < 86400);

	my $tage = int($s / 86400);
	return $tage == 1 ? "vor 1 Tag" : "vor $tage Tagen";
}

#####################################################
# Laufzeit in lesbarer Form ("3h 12m" / "2 Tage 4h").
#####################################################

sub formatDuration
{
	my $s = shift;
	return "unbekannt" if (!defined($s) || $s < 0);

	my $tage = int($s / 86400);
	my $std  = int(($s % 86400) / 3600);
	my $min  = int(($s % 3600) / 60);

	return sprintf("%d Tage %dh", $tage, $std) if ($tage > 1);
	return sprintf("1 Tag %dh", $std)          if ($tage == 1);
	return sprintf("%dh %dm", $std, $min)      if ($std > 0);
	return "1 Minute"                          if ($min == 1);
	return sprintf("%d Minuten", $min)         if ($min > 0);
	return "wenige Sekunden";
}

#####################################################
# Kleines Alter in lesbarer Form - siehe Kommentarblock oben.
#####################################################

sub formatAge
{
	my $age = shift;

	return "unbekannt" if (!defined($age));
	$age = 0 if ($age < 0);

	return sprintf("vor %dms", int($age * 1000 + 0.5)) if ($age < 1);
	return sprintf("vor %ds", int($age))               if ($age < 60);

	my $min = int($age / 60);
	my $sec = int($age) % 60;
	return sprintf("vor %dm %02ds", $min, $sec);
}

#####################################################
# Page-Header-Sub
#####################################################

sub lbheader 
{
	 # Create Help page
  $helplink = "https://www.loxwiki.eu/x/mA-L";
  open(F,"$installfolder/templates/plugins/$psubfolder/multi/help.html") || die "Missing template plugins/$psubfolder/$lang/help.html";
    @help = <F>;
    foreach (@help)
    {
      $_ =~ s/<!--\$psubfolder-->/$psubfolder/g;
      s/[\n\r]/ /g;
      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
      $helptext = $helptext . $_;
    }
  close(F);
  
  open(F,"$installfolder/templates/system/$lang/header.html") || die "Missing template system/$lang/header.html";
    while (<F>) 
    {
      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
      print $_;
    }
  close(F);
}

sub Cronjob 
{
	my $Job = shift;
		
	# Remove Cronjob
	if ($Job eq "Uninstall")
	{
		if (-e $crontabtmp) {
			unlink $crontabtmp;
		}
	
		my ($comment) = $crontab->select( -type => 'comment', -data => '## Startup ComfoConnect');
					
		#Schedule does not exist and should be removed --> nothing to do
		if (! $comment ) {
			return;
		}
		
		#We fully remove the old block
		if ($comment) {
			my ($block) = $crontab->block($comment);
			$crontab->remove($block);
		}
		
		#We are finished, write the crontab
		$crontab->write($crontabtmp);
	
		if (installcrontab()) {
			return;
		} else {
			print $cgi->header(-status => "204 Cannot remove cronjob");
			exit(0);
		}
	}
	
	# Install Cronjob
	if ($Job eq "Install")
	{
		#Check if Cronjob exist already
		my ($comment) = $crontab->select( -type => 'comment', -data => '## Startup ComfoConnect');
		
		if ($comment) {
			return;
		}
		
		# Create the event
		my $event = new Config::Crontab::Event (
		-command =>  "$installfolder/bin/plugins/$psubfolder/wrapper.pl start > /dev/null 2>&1 &",
		-user => 'loxberry',
		-system => 1,
		);
		
		$event->datetime('@reboot');
		
		# Insert block and event to crontab
		my $block = new Config::Crontab::Block;
		$block->last( new Config::Crontab::Comment( -data => '## Startup ComfoConnect') );
		$block->last($event);
		$crontab->last($block); 
		
		$crontab->write($crontabtmp);
		
		if (installcrontab()) {
			return;
		} else {
			print $cgi->header(-status => "204 Cannot remove cronjob");
			exit(0);
		}
	}	
	return;
}
	
	
#####################################################
# Watchdog-Cronjob-Sub - unabhaengig vom Startup-Cronjob (Cronjob-Sub oben), damit
# er sich per Checkbox in den Einstellungen separat an-/abschalten laesst.
#####################################################

sub WatchdogCronjob
{
	my $Job = shift;

	# Remove Cronjob
	if ($Job eq "Uninstall")
	{
		if (-e $crontabtmp) {
			unlink $crontabtmp;
		}

		my ($comment) = $crontab->select( -type => 'comment', -data => '## Watchdog ComfoConnect');

		#Schedule does not exist and should be removed --> nothing to do
		if (! $comment ) {
			return;
		}

		#We fully remove the old block
		if ($comment) {
			my ($block) = $crontab->block($comment);
			$crontab->remove($block);
		}

		#We are finished, write the crontab
		$crontab->write($crontabtmp);

		if (installcrontab()) {
			return;
		} else {
			print $cgi->header(-status => "204 Cannot remove cronjob");
			exit(0);
		}
	}

	# Install Cronjob
	if ($Job eq "Install")
	{
		#Check if Cronjob exist already
		my ($comment) = $crontab->select( -type => 'comment', -data => '## Watchdog ComfoConnect');

		if ($comment) {
			return;
		}

		# Create the event - checkwatchdog entscheidet selbst anhand von Config und
		# Statusdatei, ob tatsaechlich ein Neustart noetig ist.
		my $event = new Config::Crontab::Event (
		-command =>  "$installfolder/bin/plugins/$psubfolder/wrapper.pl checkwatchdog > /dev/null 2>&1 &",
		-user => 'loxberry',
		-system => 1,
		);

		$event->datetime('* * * * *');

		# Insert block and event to crontab
		my $block = new Config::Crontab::Block;
		$block->last( new Config::Crontab::Comment( -data => '## Watchdog ComfoConnect') );
		$block->last($event);
		$crontab->last($block);

		$crontab->write($crontabtmp);

		if (installcrontab()) {
			return;
		} else {
			print $cgi->header(-status => "204 Cannot remove cronjob");
			exit(0);
		}
	}
	return;
}


sub installcrontab
{
	if (! -e $crontabtmp) {
		return (0);
	}
	qx ( $lbhomedir/sbin/installcrontab.sh $lbpplugindir $crontabtmp );
	if ($!) {
		print $cgi->header(-status => "500 Error activating new crontab");
		return(0);
	}
	return(1);
}

#####################################################
# Footer
#####################################################

sub lbfooter 
{
  open(F,"$installfolder/templates/system/$lang/footer.html") || die "Missing template system/$lang/footer.html";
    while (<F>) 
    {
      $_ =~ s/<!--\$(.*?)-->/${$1}/g;
      print $_;
    }
  close(F);
}
