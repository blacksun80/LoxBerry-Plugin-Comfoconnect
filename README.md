# LoxBerry-Plugin-Comfoconnect
A LoxBerry Plugin


Voraussetzungen:

MQTT Gateway Plugin muss installiert sein.

1.	Zuerst muss die UUID der Zehnder LAN Box C ermittelt werden.
	Dazu muss zuerst mindestens die IP und der PIN eingetragen werden. Standardmäßig ist der PIN der Lan C Box 0000. --> Speichern.
	Danach über den Button "Nach Zehnder Lüftungsanlagen suchen" drücken. Die UUID wird ermittelt und ins Feld UUID eingetragen.
	Schaut ungefähr so aus: 00000000001d10138001155fd71e1e20 
	
2. 	MQTT User, MQTT Passwort und MQTT Server aus dem Plugin MQTT Gateway ablesen und hier eintragen. Der Topicname wird durch Auswahl des Typ der Anlage erstellt.
	Wählt man z. B. Zehnder ComfoAir Q350 aus, ist der MQTT Topic Name 'Zehnder/ComfoAirQ350/'
	Dieses Topic muss man dann im MQTT Gateway Plugin subscriben. Das wird dort so angegeben: 'Zehnder/ComfoAirQ350/#'
	--> Speichern.
	
	Im MQTT Plugin unter Incoming Overview sieht man, wie die Werte eintrudeln.

3. 	Im Miniserver einen Virtuellen Ausgang anlegen, Bezeichung MQTT-Gateway, Adresse /dev/udp/192.168.178.42/11884
	Für jede Lüftergeschwindigkeit einen 'Virtueller Ausgang Befehl' anlegen. Bei Befehl EIN 'Zehnder/ComfoAirQ450/ExecuteFunction x' eintragen

	Zehnder/ComfoAirQ450/ExecuteFunction 0 = AWAY
	Zehnder/ComfoAirQ450/ExecuteFunction 1 = NORMAL
	Zehnder/ComfoAirQ450/ExecuteFunction 2 = HIGH
	Zehnder/ComfoAirQ450/ExecuteFunction 3 = MAX
