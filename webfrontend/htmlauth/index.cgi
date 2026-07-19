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
	my ($status_text, $status_class) = getStatus($psubfolder);
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
	print JSON::PP->new->utf8(0)->encode({ statustext => $status_text, statusclass => $status_class });
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
    my ($status_text, $status_class) = getStatus($psubfolder);

    $maintemplate->param( STATUSTEXT => $status_text );
    $maintemplate->param( STATUSCLASS => $status_class );
    
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

	if (-e $statusfile) {
		local $/ = undef;
		if (open(my $fh, '<', $statusfile)) {
			my $json_text = <$fh>;
			close($fh);
			my $status = eval { decode_json($json_text) };
			if ($status) {
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
	}

	return ($status_text, $status_class);
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
