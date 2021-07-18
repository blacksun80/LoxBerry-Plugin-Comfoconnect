# LoxBerry-Plugin-Comfoconnect
A LoxBerry Plugin


Voraussetzungen:

MQTT Gateway Plugin muss installiert sein.

Entweder muss in der GUI die IP-Adresse der Zehnder ComfoConnect LAN C Box manuell eingetragen werden, oder es wird die IP der Schnittstelle
automatisch über den Button "Nach Zehnder Lüftungsanlage suchen"  ermittelt und in das Feld "IP ComfoConnect LANC:" eingetragen. 
Die automatische Ermittelung kann nur ausgeführt werden, wenn keine IP Adresse eingegeben wurde.
PIN wird vorbesetzt mit 0000, da es sich hier um den Standard-PIN handelt. Sollte der PIN geändert worden sein, bitte hier den richtigen PIN eintragen.
--> Speichern.

Das Topic für das MQTT Gateway lautet ComfoConnect/#. Dieses Topic muss man im MQTT Gateway Plugin subscriben. Das wird dort so angegeben: ' ComfoConnect/#'
Im MQTT Plugin unter Incoming Overview sieht man, wie die Werte eintrudeln.

Falls nicht, müssen die Logfiles überprüft werden. Logfiles kann man über den Menüpunkt "Log Manager/ComfoConnect" aufrufen. 

Die Steuerung der Lüftung muss ich noch anpassen. Sensoren können aber bereits ausgelesen werden.

Im Miniserver einen Virtuellen Ausgang anlegen, Bezeichung MQTT-Gateway, Adresse /dev/udp/192.168.178.42/11884
Für jede Lüftergeschwindigkeit einen 'Virtueller Ausgang Befehl' anlegen. Bei Befehl EIN 'ComfoConnect/???' eintragen

ComfoConnect/??? 0 = AWAY
ComfoConnect/??? 1 = NORMAL
ComfoConnect/??? 2 = HIGH
ComfoConnect/??? 3 = MAX
