# MQTT-Topics

Alle Topics beginnen mit dem in den Plugin-Einstellungen hinterlegten Präfix,
standardmäßig `ComfoConnect/`. In dieser Übersicht ist es der Lesbarkeit halber
weggelassen — `FAN_MODE` bedeutet also `ComfoConnect/FAN_MODE`.

Im MQTT Gateway Plugin wird die Subscription `ComfoConnect/#` automatisch eingetragen.

---

## 1. Befehle an die Lüftungsanlage

Diese Topics werden vom Plugin abonniert. Was hier ankommt, wird an die Anlage
weitergegeben.

### Lüfterstufe

| Topic | Werte | Bedeutung |
|---|---|---|
| `FAN_MODE` | `0` `1` `2` `3` | Stufe setzen: 0 = Abwesend, 1 = niedrig, 2 = mittel, 3 = hoch |
| `FAN_MODE_AWAY` | `1` | Stufe auf Abwesend |
| `FAN_MODE_LOW` | `1` | Stufe 1 |
| `FAN_MODE_MEDIUM` | `1` | Stufe 2 |
| `FAN_MODE_HIGH` | `1` | Stufe 3 |

Die Stufe gilt bis zum nächsten Punkt im Zeitplan der Anlage. Wer die Anlage für
einen längeren, definierten Zeitraum herunterfahren will, nimmt die Abwesenheit
(siehe unten) — das ist eine andere Funktion.

### Abwesenheit (Urlaub)

Überschreibt den Zeitplan über Stunden oder Tage hinweg. Entspricht dem
Haus-Symbol („Abwesend bis …") in der Zehnder-App.

| Topic | Werte | Bedeutung |
|---|---|---|
| `AWAY_FOR` | Sekunden | Abwesend für diese Dauer ab jetzt |
| `AWAY_END` | `1` | Abwesenheit vorzeitig beenden |

Gängige Werte: 1 Tag = `86400`, 7 Tage = `604800`, 10 Tage = `864000`,
14 Tage = `1209600`.

### Betriebsart

| Topic | Werte | Bedeutung |
|---|---|---|
| `MODE` | `0` `1` | 0 = manuell, 1 = automatisch |
| `MODE_AUTO` | `1` | Automatik |
| `MODE_MANUAL` | `1` | Handbetrieb |

### Lüftungsmodus (Zu-/Abluft)

| Topic | Werte | Bedeutung |
|---|---|---|
| `VENTMODE_STOP_SUPPLY_FAN` | `1` | Zuluftventilator aus |
| `VENTMODE_STOP_SUPPLY_FAN_TIME` | Sekunden | Dauer dafür, **vorher** senden |
| `VENTMODE_STOP_EXHAUST_FAN` | `1` | Abluftventilator aus |
| `VENTMODE_STOP_EXHAUST_FAN_TIME` | Sekunden | Dauer dafür, **vorher** senden |
| `START_SUPPLY_FAN` | `1` | Zuluftventilator wieder ein |
| `START_EXHAUST_FAN` | `1` | Abluftventilator wieder ein |

### Boost

| Topic | Werte | Bedeutung |
|---|---|---|
| `BOOST_MODE_TIME` | Sekunden | Dauer, **vorher** senden |
| `BOOST_MODE` | `1` | Boost starten |
| `BOOST_MODE_END` | `1` | Boost beenden |

### Bypass

| Topic | Werte | Bedeutung |
|---|---|---|
| `BYPASS` | `0` `1` `2` | 0 = Automatik, 1 = offen, 2 = geschlossen |
| `BYPASS_AUTO` | `1` | Automatik |
| `BYPASS_ON` | `1` | Bypass öffnen |
| `BYPASS_ON_TIME` | Sekunden | Dauer für „offen", **vorher** senden |
| `BYPASS_OFF` | `1` | Bypass schließen |
| `BYPASS_OFF_TIME` | Sekunden | Dauer für „geschlossen", **vorher** senden |

### Temperaturprofil

| Topic | Werte | Bedeutung |
|---|---|---|
| `TEMPPROF` | `0` `1` `2` | 0 = normal, 1 = kühl, 2 = warm |
| `TEMPPROF_NORMAL` | `1` | Profil normal |
| `TEMPPROF_COOL` | `1` | Profil kühl |
| `TEMPPROF_WARM` | `1` | Profil warm |

### Sensorgeführte Lüftung

| Topic | Werte | Bedeutung |
|---|---|---|
| `SENSOR_TEMP` | `0` `1` `2` | Temperatur passiv: 0 = Automatik, 1 = ein, 2 = aus |
| `SENSOR_TEMP_AUTO` / `_ON` / `_OFF` | `1` | einzeln schalten |
| `SENSOR_HUMC` | `0` `1` `2` | Feuchtekomfort: 0 = Automatik, 1 = ein, 2 = aus |
| `SENSOR_HUMC_AUTO` / `_ON` / `_OFF` | `1` | einzeln schalten |
| `SENSOR_HUMP` | `0` `1` `2` | Feuchteschutz: 0 = Automatik, 1 = ein, 2 = aus |
| `SENSOR_HUMP_AUTO` / `_ON` / `_OFF` | `1` | einzeln schalten |

### ComfoCool (optionales Kühlmodul)

| Topic | Werte | Bedeutung |
|---|---|---|
| `COMFOCOOL` | `0` `1` | 0 = Automatik, 1 = dauerhaft aus |
| `COMFOCOOL_AUTO` | `1` | Automatik |
| `COMFOCOOL_OFF` | `1` | Ausschalten |
| `COMFOCOOL_OFF_TIME` | Sekunden | Dauer fürs Ausschalten, **vorher** senden. Ohne Angabe dauerhaft |

Nur bei Anlagen mit angeschlossenem ComfoCool. Ohne das Modul werden die Befehle
von der Anlage abgelehnt und der Fehlschlag im Log vermerkt, sonst passiert nichts.

### Störungen

| Topic | Werte | Bedeutung |
|---|---|---|
| `ERROR_RESET` | `1` | Anstehende Störungen quittieren |

Besteht die Ursache weiter, meldet die Anlage den Fehler sofort erneut.
Quittieren ersetzt keine Behebung.

---

## 2. Zustandsmeldungen des Plugins

Diese Topics veröffentlicht das Plugin. Alle sind **retained**, ein neu
verbundener Client sieht den aktuellen Stand also sofort.

| Topic | Werte | Bedeutung |
|---|---|---|
| `Status` | `Online` / `Offline` | Läuft das Plugin. `Offline` setzt der Broker automatisch, wenn die Verbindung abreißt (Last Will) |
| `AWAY_ACTIVE` | `0` / `1` | Läuft gerade eine Abwesenheit |
| `AWAY_REMAINING` | Sekunden | Restdauer der Abwesenheit, `/86400` = Tage. `0` wenn keine läuft |
| `ERROR_COUNT` | Anzahl | Anstehende Störungen, `0` = keine |
| `ERROR_TEXT` | Text | Störungen im Klartext, mehrere durch ` \| ` getrennt |
| `SENSOR_TIMEOUT` | `0` / `1` | `1` = seit der eingestellten Zeit keine Sensordaten mehr. Nur aktiv, wenn die Überwachung in den Plugin-Einstellungen eingeschaltet ist |

`AWAY_ACTIVE` und `AWAY_REMAINING` werden alle 15 Sekunden von der Anlage
abgeholt — nach einem Schaltbefehl dauert die Rückmeldung also bis zu 15s.
Grund: Die Anlage bietet für diesen Wert kein Push an, anders als bei den
Sensoren unten.

---

## 3. Sensorwerte

Diese Topics veröffentlicht das Plugin, sobald die Anlage einen neuen Wert
schickt. Die Anlage sendet von sich aus bei jeder Änderung, es wird nicht
gepollt. Bei einigen Werten ist zusätzlich eine Mindestpause hinterlegt
(Spalte „Pause"), damit schnell schwankende Werte den Broker nicht fluten.

### Betriebszustand

| Topic | pdid | Werte | Pause |
|---|---|---|---|
| `AWAY` | 16 | `1` = Stufe 1–3, `7` = Abwesend | — |
| `OPERATING_MODE` | 56 | `1` = Handbetrieb unbegrenzt, `-1` = Automatik | — |
| `OPERATING_MODE_BIS` | 49 | `1` = Handbetrieb begrenzt, `5` = unbegrenzt, `-1` = Automatik | — |
| `FAN_SPEED_MODE` | 65 | `0`–`3` = Stufe | — |
| `FAN_MODE_SUPPLY` | 70 | Zuluftventilator-Modus | — |
| `FAN_MODE_EXHAUST` | 71 | Abluftventilator-Modus | — |
| `COMFORTCONTROL_MODE` | 225 | Sensorgeführte Lüftung | — |
| `SETTING_RF_PAIRING` | 176 | Funk-Anlernmodus | 3s |

### Countdowns bis zur nächsten Änderung (Sekunden)

| Topic | pdid | Pause |
|---|---|---|
| `FAN_NEXT_CHANGE` | 81 | 2s |
| `BYPASS_NEXT_CHANGE` | 82 | 2s |
| `SUPPLY_NEXT_CHANGE` | 86 | 2s |
| `EXHAUST_NEXT_CHANGE` | 87 | 2s |

### Ventilatoren

| Topic | pdid | Einheit | Pause |
|---|---|---|---|
| `FAN_SUPPLY_DUTY` | 118 | % | 3s |
| `FAN_EXHAUST_DUTY` | 117 | % | 3s |
| `FAN_SUPPLY_FLOW` | 120 | m³/h | 3s |
| `FAN_EXHAUST_FLOW` | 119 | m³/h | 3s |
| `FAN_SUPPLY_SPEED` | 122 | U/min | 3s |
| `FAN_EXHAUST_SPEED` | 121 | U/min | 3s |

### Temperaturen (°C)

| Topic | pdid | Ort | Pause |
|---|---|---|---|
| `TEMPERATURE_SUPPLY` | 221 | Zuluft | 3s |
| `TEMPERATURE_EXTRACT` | 274 | Abluft aus den Räumen | 3s |
| `TEMPERATURE_EXHAUST` | 275 | Fortluft nach draußen | 3s |
| `TEMPERATURE_OUTDOOR` | 276 | Außenluft | 3s |
| `TEMPERATURE_AFTER_PREHEATER` | 277 | Außenluft nach Vorheizregister | 3s |
| `TARGET_TEMPERATURE` | 212 | Solltemperatur | 3s |
| `CURRENT_RMOT` | 209 | Gleitender Außentemperatur-Mittelwert | 3s |

### Feuchte (%)

| Topic | pdid | Ort | Pause |
|---|---|---|---|
| `HUMIDITY_SUPPLY` | 294 | Zuluft | 3s |
| `HUMIDITY_EXTRACT` | 290 | Abluft | 3s |
| `HUMIDITY_EXHAUST` | 291 | Fortluft | 3s |
| `HUMIDITY_OUTDOOR` | 292 | Außenluft | 3s |
| `HUMIDITY_AFTER_PREHEATER` | 293 | nach Vorheizregister | 3s |

### Bypass und Jahreszeit

| Topic | pdid | Werte | Pause |
|---|---|---|---|
| `BYPASS_MODE` | 66 | `0` = Automatik, `1` = offen, `2` = geschlossen | — |
| `BYPASS_STATE` | 227 | Öffnungsgrad in % | — |
| `PROFILE_TEMPERATURE` | 67 | `0` = normal, `1` = kühl, `2` = warm | — |
| `HEATING_SEASON` | 210 | Heizperiode aktiv | 3s |
| `COOLING_SEASON` | 211 | Kühlperiode aktiv | 3s |
| `FROSTPROTECT_UNBALANCE` | 228 | Unwucht durch Frostschutz | — |

### Energie

| Topic | pdid | Einheit | Pause |
|---|---|---|---|
| `POWER_CURRENT` | 128 | W | 3s |
| `POWER_TOTAL_YEAR` | 129 | kWh laufendes Jahr | 3s |
| `POWER_TOTAL` | 130 | kWh gesamt | 3s |
| `PREHEATER_POWER_CURRENT` | 146 | W Vorheizregister | 3s |
| `PREHEATER_POWER_TOTAL_YEAR` | 144 | kWh Vorheizregister, Jahr | 3s |
| `PREHEATER_POWER_TOTAL` | 145 | kWh Vorheizregister, gesamt | 3s |
| `AVOIDED_HEATING_CURRENT` | 213 | W eingesparte Heizleistung | 3s |
| `AVOIDED_HEATING_TOTAL_YEAR` | 214 | kWh, Jahr | 3s |
| `AVOIDED_HEATING_TOTAL` | 215 | kWh gesamt | 3s |
| `AVOIDED_COOLING_CURRENT` | 216 | W eingesparte Kühlleistung | 3s |
| `AVOIDED_COOLING_TOTAL_YEAR` | 217 | kWh, Jahr | 3s |
| `AVOIDED_COOLING_TOTAL` | 218 | kWh gesamt | 3s |
| `AVOIDED_COOLING_CURRENT_TARGET` | 219 | — | 3s |

### Wartung

| Topic | pdid | Bedeutung | Pause |
|---|---|---|---|
| `DAYS_TO_REPLACE_FILTER` | 192 | Tage bis zum Filterwechsel | 3s |

### ComfoCool (nur mit angeschlossenem Kühlmodul)

| Topic | pdid | Bedeutung | Pause |
|---|---|---|---|
| `COMFOCOOL_STATE` | 784 | Zustand des Kühlmoduls | — |
| `COMFOCOOL_TEMPERATURE_CONDENSOR` | 802 | Kondensatortemperatur in °C | 3s |

Ohne ComfoCool erscheinen diese Topics nicht — die Anlage kennt die Werte dann
nicht, die Sensoren werden beim Start übersprungen und in der Statusanzeige als
„X von Y Sensoren aktiv" ausgewiesen. Das ist der Normalfall und kein Fehler.

---

## Hinweise

**Topics mit `_TIME` im Namen** setzen nur einen Wert und schalten nichts. Sie
müssen **vor** dem zugehörigen Schaltbefehl gesendet werden. Beispiel Boost für
10 Minuten:

```
ComfoConnect/BOOST_MODE_TIME  =  600
ComfoConnect/BOOST_MODE       =  1
```

Ausnahme ist `AWAY_FOR`: Dort steckt beides in einer Nachricht, es gibt also
keine Reihenfolge, die man falsch machen kann.

**Kommazahlen sind erlaubt.** Loxone sendet Zahlen häufig als `600.0` — das wird
korrekt als 600 verstanden.

**Ungültige Werte** werden nicht an die Anlage weitergegeben, sondern als Fehler
im Plugin-Log vermerkt.
