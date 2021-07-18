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
#use warnings;
#use strict;
#no strict "refs"; # we need it for template system and for contructs like ${"skalar".$i} in loops

##########################################################################
# Variables
##########################################################################
my  $cgi = new CGI;
my  $cfg;
my  $plugin_cfg;
my  $lang;
my  $installfolder;
my  $languagefile;
my  $version;
my  $home = File::HomeDir->my_home;
my  $psubfolder;
my  $pname;
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
# Read crontab
##########################################################################

my $crontab = new Config::Crontab;
$crontab->system(1); ## Wichtig, damit der User im File berücksichtigt wird
$crontab->read( -file => "$lbhomedir/system/cron/cron.d/$lbpplugindir" );


##########################################################################
# Read Settings
##########################################################################

# Version of this script
$version = "2.0.0.1";

# Figure out in which subfolder we are installed
$psubfolder = abs_path($0);
$psubfolder =~ s/(.*)\/(.*)\/(.*)$/$2/g;

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

# Read plugin config
$plugin_cfg 	= new Config::Simple("$installfolder/config/plugins/$psubfolder/comfoconnect.cfg") or die $plugin_cfg->error();
$pname          = $plugin_cfg->param("MAIN.SCRIPTNAME");

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

my $mqttplugindata = LoxBerry::System::plugindata("mqttgateway");
$pluginfolder = $mqttplugindata->{'PLUGINDB_FOLDER'};

if (($pluginfolder)) {
	my $mqttconffile = "$installfolder/config/plugins/$pluginfolder/mqtt.json";
	my $mqttcredfile = "$installfolder/config/plugins/$pluginfolder/cred.json";
	
	$jsonobj = LoxBerry::JSON->new();
	$mqttconf = $jsonobj->open(filename => $mqttconffile);
	$mqttcred = $jsonobj->open(filename => $mqttcredfile);
	
}

# Detect which IR Heads are connected
# my @heads = split(/\n/,`ls /dev/serial/smartmeter/*`);

# Save a config set if it not already exists
# foreach (@heads) {
	# $serial = $_;
	# $serial =~ s%/dev/serial/smartmeter/%%g;
	# if ( !$plugin_cfg->param("$serial.DEVICE") ) {
		# $plugin_cfg->param("$serial.NAME", "$serial");
		# $plugin_cfg->param("$serial.SERIAL", "$serial");
		# $plugin_cfg->param("$serial.DEVICE", "$_");
		# $plugin_cfg->param("$serial.METER", "0");
		# $plugin_cfg->param("$serial.PROTOCOL", "");
		# $plugin_cfg->param("$serial.STARTBAUDRATE", "");
		# $plugin_cfg->param("$serial.BAUDRATE", "");
		# $plugin_cfg->param("$serial.TIMEOUT", "");
		# $plugin_cfg->param("$serial.DELAY", "");
		# $plugin_cfg->param("$serial.HANDSHAKE", "");
		# $plugin_cfg->param("$serial.DATABITS", "");
		# $plugin_cfg->param("$serial.STOPBITS", "");
		# $plugin_cfg->param("$serial.PARITY", "");
	# }
# }
# $plugin_cfg->save;

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
	# If the form was saved, update config file
	if ( $saveformdata ) {
		$plugin_cfg->param( "MAIN.IPLANC", $cgi->param('iplanc') );
		$plugin_cfg->param( "MAIN.PIN", $cgi->param('pin') );
		$plugin_cfg->param( "MAIN.MQTTUSER", $mqttcred->{'Credentials'}->{'brokeruser'});
		$plugin_cfg->param( "MAIN.MQTTPASS", $mqttcred->{'Credentials'}->{'brokerpass'});
		$plugin_cfg->param( "MAIN.MQTTSERVER", $mqttconf->{'Main'}->{'brokeraddress'});
		$plugin_cfg->param( "MAIN.MQTTTOPIC", "ComfoConnect/" );
		
		$plugin_cfg->save;

		Cronjob("Uninstall");
        
		if (($cgi->param('iplanc') ne "") && ($cgi->param('pin') ne "")) {
			system("perl $installfolder/bin/plugins/$psubfolder/wrapper.pl  restart > /dev/null 2>&1 &");

			# Create Cronjob
			Cronjob("Install");
		}
	}
	
	# The page title read from language file + our name
	#$template_title = $phrase->param("TXT0000") . ": " . $pname;
	
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
	$maintemplate->param( IPLANC 		=> $plugin_cfg->param("MAIN.IPLANC") );
	$maintemplate->param( PIN 			=> $plugin_cfg->param("MAIN.PIN") );
	$maintemplate->param( TOPIC			=> $plugin_cfg->param("MAIN.MQTTTOPIC") . "#" ); 
	# $maintemplate->param( UUID 			=> $plugin_cfg->param("MAIN.UUID") );
	# $maintemplate->param( MQTTUSER, 	$mqttcred->{'Credentials'}->{'brokeruser'});
	# $maintemplate->param( MQTTPASS, 	$mqttcred->{'Credentials'}->{'brokerpass'});
	# $maintemplate->param( MQTTSERVER, 	$mqttconf->{'Main'}->{'brokeraddress'});
	# $maintemplate->param( MQTTTOPIC		=> $plugin_cfg->param("MAIN.MQTTTOPIC") );
	$maintemplate->param( ROWS => \@rows );

	# ReScan Zehnder UUID
	if ( $rescan ) {
		system("/opt/loxberry/bin/plugins/comfoconnect/openhab_gw.py  --configfile /opt/loxberry/config/plugins/comfoconnect/comfoconnect.cfg --logfile /opt/loxberry/log/plugins/comfoconnect/comfoconnect.log --loglevel 6 --search");

		# if ($uuid == "") {
			# print $cgi->header(-status => "204 UUID kann nicht ermittelt werden, evtl. IP oder PIN falsch!");
		# }
	}

    ##
    #handle Template and render index page
    ##
    # handle MQTT details
    my $mqttsubscription = $plugin_cfg->param("MAIN.MQTTTOPIC") . "#";
    #my $mqttcred = LoxBerry::IO::mqtt_connectiondetails();
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

	# Print Template
	print $maintemplate->output;

	# Parse page footer		
	&lbfooter;

	exit;

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
		-command =>  "$installfolder/bin/plugins/$psubfolder/wrapper.pl  restart > /dev/null 2>&1 &",
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
