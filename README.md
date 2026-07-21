# LoxBerry-Plugin-Comfoconnect

Verbindet eine Zehnder-Lüftungsanlage (ComfoAir Q) über die **ComfoConnect LAN C**
mit dem Loxone Miniserver. Das Plugin liest die Messwerte der Anlage aus und nimmt
Steuerbefehle entgegen — beides per MQTT.

## Voraussetzungen

* Das **MQTT Gateway Plugin** muss installiert sein.
* Eine ComfoConnect LAN C im selben Netz.

## Einrichtung

1. In den Plugin-Einstellungen die **IP-Adresse** der LAN C eintragen — oder
   „IP der ComfoConnect LAN C ermitteln" anklicken. Das geht auch, wenn dort
   bereits eine Adresse steht; die Ermittlung setzt nur voraus, dass das Plugin
   gerade nicht läuft.
2. **PIN** prüfen. Voreingestellt ist `0000`, der Auslieferungszustand.
3. **Speichern**, dann **Starten**. Speichern schreibt nur die Einstellungen —
   wirksam werden sie beim nächsten Start. Liegen beim Starten noch
   ungespeicherte Änderungen vor, fragt das Plugin nach.

Im MQTT Gateway Plugin muss das Topic `ComfoConnect/#` abonniert sein. Das trägt
das Plugin beim Speichern selbst ein. Unter *Incoming Overview* im MQTT-Plugin
sieht man, wie die Werte eintreffen.

Läuft etwas nicht, hilft die Statusanzeige oben in den Plugin-Einstellungen; sie
nennt die Ursache im Klartext. Ausführlicher wird es im Log unter
*Log Manager → ComfoConnect*.

## Was die Oberfläche bietet

**Statusanzeige** — sekündlich aktualisiert: ob die Verbindung steht, wie viele
Sensoren aktiv sind und wie alt die letzten Daten sind.

**Starten, Stoppen und Neu starten** als eigene Schaltflächen, getrennt vom
Speichern. Der Vorgang läuft in einem Dialog ab, der sich schließt, sobald das
Plugin den erwarteten Zustand meldet. Scheitert der Start, nennt der Dialog den
Grund — etwa dass die Anlage unter der eingetragenen Adresse nicht erreichbar
ist.

**Erkannte Geräte** — Modell, Bauart des Wärmetauschers, Firmware-Stand und die
am Bus gemeldeten Komponenten, sobald die Verbindung steht.

**Sensoren** — aufklappbare Liste aller 69 Messwerte mit Beschreibung, Einheit und
aktuellem Wert. Nicht benötigte lassen sich abwählen; sie werden dann bei der
Anlage gar nicht erst angemeldet und erscheinen nicht mehr per MQTT.

**Befehle** — alle 46 Topics, die das Plugin entgegennimmt, mit zulässigen Werten
und dem zuletzt empfangenen Wert. Damit lässt sich prüfen, ob ein Befehl aus
Loxone tatsächlich ankommt.

**Überwachung der Sensorwerte** — erkennt den Fall, dass die Verbindung zwar steht,
aber keine Messwerte mehr eintreffen. Auf Wunsch mit automatischem Neustart. Wird
zusätzlich als `SENSOR_TIMEOUT` per MQTT gemeldet.

**Diagnose** — zählt Verbindungsabbrüche, Zeitüberschreitungen und ähnliche
Aussetzer, die im Betrieb abgefangen werden und sonst unsichtbar blieben. Bei einer
Störung wird zusätzlich ein **Log-Snapshot** gesichert: zwei Minuten Log vor und
nach dem Ereignis, abgelegt unter `data/plugins/comfoconnect/`. Der überlebt das
automatische Aufräumen der Logs und einen Neustart.

## Anbindung an Loxone

Im Miniserver einen **Virtuellen Ausgang** anlegen, Adresse
`/dev/udp/<IP-des-LoxBerry>/11884`.

Darunter je Befehl einen *Virtuellen Ausgang Befehl* mit dem gewünschten Topic,
zum Beispiel für die Lüfterstufe:

```
ComfoConnect/FAN_MODE 0     Abwesend
ComfoConnect/FAN_MODE 1     niedrig
ComfoConnect/FAN_MODE 2     mittel
ComfoConnect/FAN_MODE 3     hoch
```

Die vollständige Liste aller Topics — Messwerte wie Befehle — steht in
**[MQTT-TOPICS.md](MQTT-TOPICS.md)**. Dieselbe Übersicht findet sich auch direkt in
den Plugin-Einstellungen.

## Einen weiteren Messwert ergänzen

Über die Oberfläche lässt sich nur aus- und abwählen. Ein zusätzlicher Sensor
braucht einen Eintrag in `bin/mqtt_data.py` samt passendem Datentyp in
`RPDO_TYPE_MAP` (`bin/pycomfoconnect/comfoconnect.py`) — dort stehen auch
Umrechnung und Beschreibung, ohne die ein Rohwert nicht zu deuten ist.

Welche Kennnummern (pdid) das Zehnder-Protokoll kennt, ist in
[PROTOCOL-PDO.md](PROTOCOL-PDO.md) dokumentiert.

## Dokumentation

* [MQTT-TOPICS.md](MQTT-TOPICS.md) — alle Topics
* [CHANGELOG.md](CHANGELOG.md) — was sich in Version 0.4 geändert hat
* [PROTOCOL.md](PROTOCOL.md), [PROTOCOL-PDO.md](PROTOCOL-PDO.md),
  [PROTOCOL-RMI.md](PROTOCOL-RMI.md) — das Zehnder-Protokoll
