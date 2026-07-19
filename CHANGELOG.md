# Änderungen gegenüber Version 0.3

## Behobene Fehler

**Das Plugin startete auf neueren Systemen gar nicht.** Seit paho-mqtt 2.0 muss
beim Verbindungsaufbau die Callback-Version angegeben werden — ohne diese Angabe
brach das Plugin beim Start ab und baute keine MQTT-Verbindung auf. Betraf unter
anderem LoxBerry 3.0. Der Fix funktioniert weiterhin auch mit älteren
paho-Versionen. *(GitHub-Issues #13 und #14)*

**Ein einziger nicht unterstützter Sensor legte das ganze Plugin lahm.** Meldete
sich beim Start auch nur ein Sensor nicht zurück, brach das komplette Skript ab —
danach wurde kein einziger Wert mehr übertragen. Nicht jede Anlage und nicht jeder
Firmware-Stand kennt alle Messwerte; solche Sensoren werden jetzt übersprungen und
in der Statusanzeige als „46 von 50 Sensoren aktiv" ausgewiesen.

**Abstürze beim Senden von Befehlen.** Wurde ein Befehl geschickt, den die Anlage
nicht beantwortete (zum Beispiel „Abwesend", wenn sie bereits abwesend war),
starb der MQTT-Empfangsthread. Das Plugin lief weiter und lieferte Sensorwerte,
reagierte aber auf keinen Befehl mehr — ohne erkennbare Ursache. *(Issue #11)*

**Endlosschleife mit vollem Datenträger.** Unter bestimmten Umständen drehte das
Plugin mit voller CPU-Last im Kreis und schrieb dabei Logdateien von über 100 MB.

**Abstürze und hängende Verbindungen beim Reconnect.** Riss die Verbindung zur
Lüftungsanlage ab, konnte sich das Plugin dabei aufhängen, ohne es zu bemerken.
Mehrere Ursachen behoben (Wettlaufsituationen zwischen den Threads, falsch
zugeordnete Antworten der Anlage, verschluckte Fehlermeldungen).

**Fehlermeldungen waren unlesbar.** Ausgerechnet im Fehlerfall schrieb das Plugin
statt der Ursache einen 15-zeiligen Programmierfehler ins Log.

**Installation dauerte unnötig lange.** Bei jeder Installation und jedem Update
wurden rund zwei Minuten mit einer überflüssigen Internetabfrage verbracht.

---

## Neue Funktionen

**Statusanzeige in der Weboberfläche.** Zeigt sekündlich aktualisiert, ob alles
läuft, wie viele Sensoren aktiv sind und wann zuletzt Daten von der Anlage kamen.
Bei Störungen erscheint im Klartext, was nicht stimmt.

**Überwachung der Sensorwerte.** Erkennt den Fall, dass die Verbindung zwar steht
und die Anlage antwortet, aber keine Messwerte mehr ankommen — bisher fiel das
niemandem auf. Zeitspanne einstellbar, auf Wunsch mit automatischem Neustart.
Wird zusätzlich als `SENSOR_TIMEOUT` per MQTT gemeldet, ist also auch in Loxone
auswertbar.

**Störungsmeldungen im Klartext.** Meldet die Anlage einen Fehler, stand bisher
nur „Unhandled" im Log. Jetzt erscheint die Ursache ausformuliert, zum Beispiel
*„Fortluftdruck zu hoch. Luftauslässe, Kanäle und Filter auf Verschmutzung
prüfen"*. Über `ERROR_COUNT` und `ERROR_TEXT` auch per MQTT verfügbar, und mit
`ERROR_RESET` lassen sich Störungen quittieren.

**Abwesenheit / Urlaubsschaltung.** Die Anlage lässt sich jetzt für einen frei
wählbaren Zeitraum in den Abwesenheitsbetrieb schicken — auch über mehrere Tage,
so wie in der Zehnder-App. Über `AWAY_FOR` (Dauer in Sekunden) und `AWAY_END`
zum vorzeitigen Beenden. Der aktuelle Zustand wird über `AWAY_ACTIVE` und die
Restzeit über `AWAY_REMAINING` zurückgemeldet.

**Sauberes Beenden.** Beim Neustart meldet sich das Plugin jetzt ordentlich bei
der Lüftungsanlage ab. Vorher hielt die Anlage die alte Verbindung noch mehrere
Sekunden fest, was den Neustart verzögerte.

**Dokumentation aller MQTT-Topics** in der Datei `MQTT-TOPICS.md`.

---

## Hinweise zum Update

Die Einstellungen für die Überwachung sind nach dem Update **ausgeschaltet**. Wer
sie nutzen möchte, aktiviert sie in den Plugin-Einstellungen. Der frühere
Watchdog-Schwellwert wird nicht übernommen, da er anders funktioniert (Sekunden
statt Minuten, und er achtet jetzt auf die Sensordaten statt nur auf die
Verbindung).

Alle bisherigen MQTT-Topics funktionieren unverändert weiter. Die neuen kommen
nur hinzu.
