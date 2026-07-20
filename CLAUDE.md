# Projektnotizen

Arbeitsnotizen für die Weiterentwicklung. Kein Benutzerhandbuch — das ist die
README.

## Was das Plugin ist

LoxBerry-Plugin, das eine Zehnder-Lüftungsanlage über die ComfoConnect LAN C per
MQTT an Loxone anbindet. Sprache der Oberfläche und der Logmeldungen: **Deutsch**.
Kommentare im Code ebenfalls deutsch (ältere Bestandteile sind englisch, das darf
so bleiben — nicht flächendeckend übersetzen).

## Aufbau

| Datei | Aufgabe |
|---|---|
| `bin/cfc.py` | Hauptprogramm: MQTT, Sensorregistrierung, Befehlsverarbeitung, Statusdatei |
| `bin/mqtt_data.py` | Sensorkatalog: pdid → NAME, INFO, CONV, PUSH. **Einzige Quelle**, welche Sensoren es gibt |
| `bin/pycomfoconnect/` | Protokollschicht (Fork von michaelarnauts/pycomfoconnect, stark überarbeitet) |
| `bin/wrapper.pl` | Start/Stopp, Überwachungs-Cronjob |
| `webfrontend/htmlauth/index.cgi` | Weboberfläche, AJAX-Endpunkt |
| `templates/multi/main.html` | Markup, CSS, JavaScript |

**Threads:** Hauptprogramm, Verbindungs-Thread und Nachrichten-Thread
(`comfoconnect.py`), Status-Thread und Abwesenheits-Thread (`cfc.py`), dazu der
Netzwerk-Thread von paho. Rückrufe laufen in **fremden** Threads — dort darf keine
Ausnahme durchschlagen, sonst stirbt der Thread und das Plugin läuft als Hülle
weiter. Abgesichert über `@thread_sicher` (MQTT) und an der Aufrufstelle von
`callback_sensor`.

## Ablageorte

* `/var/run/shm/<plugin>/status.json` — Ramdisk, sekündlich neu geschrieben. Verbindet
  `cfc.py` mit der Oberfläche.
* `data/plugins/<plugin>/statistik.json` — Langzeitzähler, überlebt Neustart und Update.
* `data/plugins/<plugin>/snapshot_*.log` — Log-Snapshots, max. 5.
* Das Logverzeichnis liegt auf der **Ramdisk** und wird von LoxBerry aufgeräumt.
  Deshalb gibt es die Snapshots.

Konfiguration und Datenverzeichnis überstehen ein Plugin-Update (belegt durch
`preupgrade.sh`/`postupgrade.sh` und `plugininstall.pl`). Nur eine Deinstallation
räumt auf.

## Fallstricke, die schon zugeschlagen haben

**Rohwerte werden nach Byte-Länge dekodiert, nicht nach PDO-Typ**
(`_handle_rpdo_notification`). Folgen: 4-Byte-Werte kommen als Hex-Zeichenkette an
(deshalb die Sonderfälle für pdid 81/82/86/87 in `callback_sensor`), und
vorzeichenlose Werte über 127 bzw. 32767 kippen ins Negative — `OPERATING_MODE`
liefert `-1` statt `255`. Eine Korrektur würde veröffentlichte Werte ändern und
Loxone-Konfigurationen brechen. Bewusst offen.

**Zähler in Wiederholschleifen.** `verbindungsabbrueche` zählte einst jeden
Wiederholversuch — ein Ausfall ergab 2099 „Abbrüche". Merker `_abbruch_gemeldet`,
zurückgesetzt erst bei erfolgreicher Verbindung.

**Loglevel gehört an die Handler, nicht an den Logger.** Sonst entstehen
DEBUG-Meldungen gar nicht erst und der Snapshot-Ringpuffer bleibt leer. Siehe
`setup_logger`.

**jQuery Mobile setzt `fieldset` per Tag-Selektor zurück.** Deshalb `div` +
`!important` für die gerahmten Blöcke.

**Jedes `<input>` braucht `data-role="none"`.** Sonst baut jQuery Mobile daraus ein
eigenes Bedienelement mit eigenem Kastenmodell. In einer Tabelle sprengt das die
Zeilenhöhe, und Kontrollkästchen schieben sich über die Überschrift darüber. Galt
schon für die beiden Kästchen im Überwachungsblock — beim Bau der Sensorliste
trotzdem vergessen und dadurch erneut zugeschlagen.

**Kein `except: pass` ohne Meldung** bei irgendetwas Diagnostischem. Der
Snapshot-Schreiber hat sein eigenes Versagen einmal komplett verschluckt.

**Vor Änderungen prüfen, auf welchem Zweig das Arbeitsverzeichnis steht.** Ein
Wechsel mit offenen Änderungen hat schon Arbeit gekostet und einen Merge-Konflikt
in `mqtt_data.py` hinterlassen.

## Prüfen vor dem Abschluss

```bash
python3 -m py_compile bin/*.py bin/pycomfoconnect/*.py
perl -c webfrontend/htmlauth/index.cgi        # braucht LoxBerry-Module
perl -c bin/wrapper.pl
```

Textmuster (`grep`) reichen **nicht**, um zu belegen, dass etwas funktioniert. Zwei
Fehler in diesem Projekt entstanden genau so: Ein Suchmuster fand Zuweisungen, die
in der falschen Methode standen, und ein anderes übersah maskierte Anführungszeichen.
Im Zweifel das Objekt tatsächlich erzeugen und die Attribute abfragen.

## Doppelte Listen

Die Befehlsübersicht in `index.cgi` (`@COMMANDS`) ist zwangsläufig eine zweite
Fassung der Topics aus `_dispatch_message`. Was ein Befehl *bewirkt*, lässt sich
nicht als Daten ablegen — deshalb keine eigene Katalogdatei, die Erweiterbarkeit
vortäuschen würde. Stattdessen schreibt `cfc.py` die tatsächlich abonnierten Topics
in die Statusdatei, und die Oberfläche meldet Abweichungen selbst.

## Referenz

`aiocomfoconnect` desselben Autors ist die aktuellere Bibliothek und half mehrfach
weiter (Sensornamen, Einheiten, PDO-Typen, der Away-Befehl `8415 010B`). Sie sendet
**kein** periodisches Keepalive mehr und erkennt Ausfälle rein passiv — an einigen
Stellen sind wir inzwischen weiter, etwa bei der Reaktion auf `NOT_ALLOWED`.

## Offen

* Zweig `sensorliste` ist noch **nicht auf echter Hardware gelaufen**.
* Versionsnummer steht in `plugin.cfg` und `release.cfg` weiterhin auf 0.3.
* `last_keepalive_ok` in `status.json` ist inhaltsleer — das Protokoll kennt keine
  Antwort auf ein Keepalive. Besser wäre der Zeitpunkt der letzten beantworteten
  RMI-Anfrage.
* ComfoCool-Befehle sind ungetestet (keine Hardware vorhanden).
