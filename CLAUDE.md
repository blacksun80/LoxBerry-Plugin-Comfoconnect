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
| `webfrontend/htmlauth/index.cgi` | Weboberfläche, AJAX-Endpunkte |
| `templates/multi/main.html` | Markup, CSS, JavaScript |

## Arbeitsweise mit Michael

Er spielt jede Änderung auf echte Hardware und schickt Logs und Bildschirmfotos
zurück. Vermutungen sind wertlos — belege eine Ursache oder sage, dass du sie
noch nicht kennst. Nach jeder Änderung erwartet er eine **Zusammenfassung mit
Betreff** für die Commit-Nachricht; sie wächst weiter, bis er „gepusht" sagt,
dann fängt sie neu an. Gepusht wird von ihm selbst — nimm **keinen
GitHub-Token** entgegen, der stünde sonst dauerhaft im Gesprächsprotokoll.

Oberfläche, Logmeldungen und neue Kommentare auf Deutsch. Version bleibt
vorerst auf 0.3.

## Die drei AJAX-Endpunkte in `index.cgi`

`ajax_status`, `ajax_control` und `ajax_reset_stats` stehen **ganz oben**, vor
`LOGSTART` und vor jeder HTML-Ausgabe, und beenden das Skript mit `exit`. Wird
vorher irgendetwas gedruckt, ist die JSON-Antwort kaputt. `ajax_control` nimmt
nur POST an — ein Aufruf, der den Betrieb unterbricht, darf nicht durch einen
Link oder den Vorablader des Browsers auslösbar sein.

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

**Hintergrundprozesse aus dem CGI müssen abgenabelt werden.** Ein bloßes
`system("perl wrapper.pl start &")` vererbt die offenen Kanäle des CGI, darunter
die Verbindung zum Browser. Folge: Die Oberfläche meldete „fehlgeschlagen (HTTP
0)", und die ganze Seite fror ein — auch die sekündliche Statusabfrage, weil
Apache an dem Kind hing. Deshalb `setsid ... </dev/null >/dev/null 2>&1 &`.
Sichtbar wird das nur auf echter Hardware; lokal gibt es kein Apache.

**Gesperrte Formularfelder sendet der Browser nicht mit.** IP und PIN waren im
Betrieb per `disabled` gesperrt — beim Speichern kamen sie leer an und
überschrieben die Konfiguration. Für Textfelder immer `readonly` (wird
gesendet), `disabled` nur für Schaltflächen.

**Im `<script>`-Block ist `<!--` ein *einzeiliger* Kommentar.** Ein mehrzeiliger
Block zerlegt das JavaScript, weil nur die erste Zeile auskommentiert ist. Jede
Zeile braucht ihr eigenes `<!-- ... -->`. Eine Klammerbilanz findet das nicht —
nur ein echter Syntaxcheck (siehe unten).

**jQuery Mobile beansprucht den Hash für sich.** Ein Anker in der Formularadresse
(`action="./index.cgi#steuerung"`) wird als Seiten-ID gedeutet, nicht als
Sprungmarke — die Seite landet trotzdem oben. Nachträgliches Zurückrollen per
`setTimeout` ist als Zucken sichtbar. Deshalb speichert das Formular jetzt per
AJAX, ohne Seitenneuaufbau; damit stellt sich die Frage gar nicht.

**`.always()` läuft nach `.done()`.** Eine dort bedingungslos entfernte Sperre
hebt auf, was `.done()` gerade richtig gesetzt hat. Sperren gehören deshalb in
`ccKnoepfe()` und werden über Merker gesteuert, nicht an der Aufrufstelle
gesetzt und wieder entfernt.

**Kein `except: pass` ohne Meldung** bei irgendetwas Diagnostischem. Der
Snapshot-Schreiber hat sein eigenes Versagen einmal komplett verschluckt.

**Vor Änderungen prüfen, auf welchem Zweig das Arbeitsverzeichnis steht.** Ein
Wechsel mit offenen Änderungen hat schon Arbeit gekostet und einen Merge-Konflikt
in `mqtt_data.py` hinterlassen.

## Installation

`dpkg/apt` ist **bewusst leer**. Steht dort etwas, übernimmt LoxBerry die
Paketinstallation — bei jedem Update aufs Neue, samt `apt-get update` gegen alle
Quellen des Systems und erneutem Einspielen unveränderter Pakete (rund
anderthalb Minuten). Stattdessen prüft `postroot.sh` mit `dpkg-query`, was
fehlt, und installiert nur das. Dasselbe für `protobuf` per Importprüfung statt
`pip install`.

GPG-Fehler im Installationslog (`sury.org`, `yarnpkg`) stammen aus fremden
Paketquellen des LoxBerry und haben mit dem Plugin nichts zu tun. Seit die
Paketinstallation nur noch bei Bedarf läuft, tauchen sie im Normalfall gar
nicht mehr auf.

## Prüfen vor dem Abschluss

```bash
python3 -m py_compile bin/*.py bin/pycomfoconnect/*.py
perl -c webfrontend/htmlauth/index.cgi        # braucht LoxBerry-Module
perl -c bin/wrapper.pl

# JavaScript aus main.html herausschneiden und wirklich pruefen.
# Die TMPL_VAR-Platzhalter vorher ersetzen, sonst stolpert der Parser darueber.
sed -n '/<script>/,/<\/script>/p' templates/multi/main.html | sed '1d;$d' \
  | sed 's/<TMPL_VAR NAME=[A-Z_]*>/0/g' > /tmp/cc.js && node --check /tmp/cc.js
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

## Bedienung der Oberfläche

Speichern und Prozesssteuerung sind **getrennt**. Früher startete jedes
Speichern das Plugin neu, auch wenn sich nur ein Haken in der Sensorliste
geändert hatte.

* Drei Schaltflächen in einer Zeile: Starten/Stoppen, Neu starten, Speichern.
* Speichern ist nur bei echter Änderung aktiv (`ccStand()` vergleicht den
  Formularinhalt mit dem Stand beim Laden).
* Das Formular wird ganz normal abgeschickt, die Seite also neu aufgebaut.
  Deshalb zielt es auf den Anker `#steuerung` — sonst springt die Ansicht nach
  oben und die Schaltflächen sind weg. Der Merker „eben gespeichert" überlebt
  den Neuaufbau über `sessionStorage`; danach bietet ein Dialog den Neustart an.
* `ccFrage()` ersetzt `confirm()` — eigener Kasten, gestaltbar. Bitte kein
  `confirm()` mehr einbauen.
* IP und PIN sind im Betrieb `readonly`, Suchen nur im Stillstand.
* Die Statuszeile prüft **zuerst das Alter der Statusdatei** (`laeuftNoch`,
  5 Sekunden). Die Datei liegt auf der Ramdisk und bleibt nach dem Anhalten
  liegen — ohne diese Prüfung stünde dort weiter „Läuft".

## Offen

* Zweig `sensorliste` ist noch **nicht vollständig auf echter Hardware
  bestätigt**. Zuletzt in Arbeit: Start/Stopp meldete „fehlgeschlagen (HTTP 0)"
  und die Seite fror ein — Ursache und Behebung siehe `setsid` oben, **die
  Wirkung ist noch nicht bestätigt**. Falls es weiter klemmt: `perl wrapper.pl
  start` von Hand auf dem LoxBerry aufrufen und das Plugin-Log ansehen.
* Versionsnummer steht in `plugin.cfg` und `release.cfg` weiterhin auf 0.3.
* Zweig `sensorliste` ist noch nicht nach `master` überführt.
* `last_keepalive_ok` in `status.json` ist inhaltsleer — das Protokoll kennt keine
  Antwort auf ein Keepalive. Besser wäre der Zeitpunkt der letzten beantworteten
  RMI-Anfrage.
* ComfoCool-Befehle sind ungetestet (keine Hardware vorhanden).
* **Drosselung in `callback_sensor` verwirft den letzten Wert.** Fällt eine
  Änderung ins `PUSH`-Sperrfenster, wird sie weggeworfen statt nachgereicht.
  Kommt danach längere Zeit nichts mehr, steht in MQTT dauerhaft der vorletzte
  Wert — ein falscher, nicht nur ein verzögerter. Trifft besonders träge
  Sensoren (Temperatur, Feuchte, Filtertage).

  Geplante Lösung: Drosselung mit Nachlauf. Neuer Wert bei aktiver Sperre wird
  als *ausstehend* gemerkt (immer nur der neueste, spätere überschreiben ihn)
  und gesendet, sobald die Sperre fällt. Dazu ein Vergleich auf Gleichheit —
  identische Werte gar nicht erst senden. Ergibt weniger Verkehr als heute bei
  korrekten Werten; die Sendehäufigkeit bleibt auf eine Nachricht je Intervall
  begrenzt. Das Nachreichen kann der Status-Thread übernehmen, der ohnehin
  sekündlich läuft. Sensoren ohne `PUSH` bleiben unberührt.
