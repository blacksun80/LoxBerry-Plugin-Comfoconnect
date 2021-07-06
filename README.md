# LoxBerry-Plugin-Comfoconnect
A LoxBerry Plugin


Voraussetzungen:

MQTT Gateway Plugin muss installiert sein.

Nachdem das Plugin Comfoconnect installiert wurde, muss noch die pluginconfig.json im Ordner /opt/loxberry/config/comfoconnect parametriert werden.

1.	Zuerst muss die UUID der Zehnder LAN Box C ermittelt werden.
	Dazu über mittels putty diesen Befehl ausführen: /usr/bin/python3 -u /opt/loxberry/bin/plugins/comfoconnect/openhab_gw.py -d 'IP der LAN Box'
		Beispiel: /usr/bin/python3 -u /opt/loxberry/bin/plugins/comfoconnect/openhab_gw.py -d 192.168.178.49
		Ausgabe: Bridge found: 00000000001d10138001144fd71e1e20 (192.168.178.49)
		
		Diese ID nun in der pluginconfig.json in Abschnitt 'zehnder_uuid' einfügen
	
2.	zehnderPIN, zehnderIP, mqtt_broker, mqtt_user, mqttpassw und mqtt_topic befüllen.
	mqtt_topic z. B. auf 'Zehnder/ComfoAirQ450/' festlegen. Dieses Topic muss man dann im MQTT Gateway Plugin subscriben. Das wird dort so angegeben: 'Zehnder/ComfoAirQ450/#'
	
3. 	Danach Plugin mittels '/usr/bin/python3 -u /opt/loxberry/bin/plugins/comfoconnect/openhab_gw.py' zum Testen starten
	
	Ausgabe:
	subscriber connected
	publisher connected
	Waiting... Stop with CTRL+C
	mode:41 speed:0 alt:1
	
	Im MQTT Plugin unter Incoming Overview sieht man, wie die Werte eintrudeln.
	
4. 	Mit STRG+C Plugin beenden
5.	Damit das Plugin im Hintergrund läuft, das Plugin mittels 'nohup /usr/bin/python3 -u /opt/loxberry/bin/plugins/comfoconnect/openhab_gw.py >> /opt/loxberry/log/plugins/comfoconnect/comfoconnect.log &' starten

6. 	Im Miniserver einen Virtuellen Ausgang anlegen, Bezeichung MQTT-Gateway, Adresse /dev/udp/192.168.178.42/11884
	Für jede Lüftergeschwindigkeit einen 'Virtueller Ausgang Befehl' anlegen. Bei Befehl EIN 'Zehnder/ComfoAirQ450/ExecuteFunction x' eintragen

	Zehnder/ComfoAirQ450/ExecuteFunction 0 = AWAY
	Zehnder/ComfoAirQ450/ExecuteFunction 1 = NORMAL
	Zehnder/ComfoAirQ450/ExecuteFunction 2 = HIGH
	Zehnder/ComfoAirQ450/ExecuteFunction 3 = MAX
