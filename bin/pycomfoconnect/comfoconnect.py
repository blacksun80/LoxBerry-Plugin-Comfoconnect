import logging
import queue
import struct
import threading
import time
import sys

from .bridge import Bridge
from .error import *
from .message import Message
from .zehnder_pb2 import *
# Gezielt und namentlich, nicht per *: const.py enthaelt auch Namen wie
# SENSOR_* und FAN_MODE_*, die sich sonst mit denen aus zehnder_pb2 ins Gehege
# kommen koennten. const.py importiert selbst nichts, es gibt also keinen Zirkel.
from .const import ALARM_ERRORS, ALARM_ERRORS_140, ALARM_FIRMWARE_140

KEEPALIVE = 60

DEFAULT_LOCAL_UUID = bytes.fromhex('00000000000000000000000000001337')
DEFAULT_LOCAL_DEVICENAME = 'pycomfoconnect'
DEFAULT_PIN = 0

_LOGGER = logging.getLogger('comfoconnect')

# Wird in die Warteschlange gelegt, sobald der Nachrichten-Thread den Verlust
# der Verbindung bemerkt. Weckt einen Wartenden sofort, statt ihn in sein
# Zeitlimit laufen zu lassen.
_CONNECTION_LOST = object()

# Sensor variable size
RPDO_TYPE_MAP = {
    16: 1,
    33: 1,
    37: 1,
    49: 1,
    53: 1,
    56: 1,
    65: 1,
    66: 1,
    67: 1,
    70: 1,
    71: 1,
    81: 3,
    82: 3,
    85: 3,
    86: 3,
    87: 3,
    117: 1,
    118: 1,
    119: 2,
    120: 2,
    121: 2,
    122: 2,
    128: 2,
    129: 2,
    130: 2,
    144: 2,
    145: 2,
    146: 2,
    176: 1,
    192: 2,
    208: 1,
    209: 6,
    210: 0,
    211: 0,
    212: 6,
    213: 2,
    214: 2,
    215: 2,
    216: 2,
    217: 2,
    218: 2,
    219: 2,
    221: 6,
    224: 1,
    225: 1,
    226: 2,
    227: 1,
    228: 1,
    274: 6,
    275: 6,
    276: 6,
    277: 6,
    290: 1,
    291: 1,
    292: 1,
    293: 1,
    294: 1,
    321: 2,
    325: 2,
    337: 3,
    338: 3,
    341: 3,
    369: 1,
    370: 1,
    371: 1,
    372: 1,
    384: 6,
    386: 0,
    400: 6,
    401: 1,
    402: 0,
    416: 6,
    417: 6,
    418: 1,
    419: 0,
    # ComfoCool (optionales Kuehlmodul). Ohne Eintrag hier wuerde register_sensor()
    # mit "unknown type" abbrechen, noch bevor die Anlage ueberhaupt gefragt wird.
    784: 1,     # Zustand (UINT8)
    802: 6,     # Kondensatortemperatur (INT16, Zehntelgrad)
    18: 1,
    54: 1,
    55: 1,
    220: 6,
    278: 6,
    785: 0,
}

# Product ID Map
PRODUCT_ID_MAP = {
    1: "ComfoAirQ",
    2: "ComfoSense",
    3: "ComfoSwitch",
    4: "OptionBox",
    5: "ZehnderGateway",
    6: "ComfoCool",
    7: "KNXGateway",
    8: "Service Tool",
    9: "Production test tool",
    10: "Design verification test tool"
}

class ComfoConnect(object):
    """Implements the commands to communicate with the ComfoConnect ventilation unit."""

    """Callback function to invoke when sensor updates are received."""
    callback_sensor = None

    """Callback function to invoke when an alarm notification is received.

    Wird mit (node_id, errors) aufgerufen, wobei errors ein Dict
    {Bitnummer: Klartext} der aktuell anstehenden Fehler ist - leer, wenn die
    Anlage keine Fehler (mehr) meldet.
    """
    callback_alarm = None

    def __init__(self, bridge: Bridge, local_uuid=DEFAULT_LOCAL_UUID, local_devicename=DEFAULT_LOCAL_DEVICENAME,
                 pin=DEFAULT_PIN):
        self._bridge = bridge
        self._local_uuid = local_uuid
        self._local_devicename = local_devicename
        self._pin = pin
        self._reference = 1

        self._queue = queue.Queue()

        # Referenzen, deren Antwort wir nicht mehr erwarten (Zeitlimit abgelaufen).
        # Trifft sie doch noch ein, wird sie verworfen - sonst kreiste sie dauerhaft
        # in der Warteschlange.
        self._abandoned_references = set()

        # Schuetzt die Vergabe der Referenznummer und das Schreiben auf den Socket.
        # Haupt- und Nachrichten-Thread senden gleichzeitig; ohne Sperre koennten
        # zwei Befehle dieselbe Nummer bekommen oder ihre Bytes verschraenken.
        self._command_lock = threading.Lock()

        self._connected = threading.Event()
        self._stopping = False          # signals stopping message handling
        self._disconnecting = False     # signals intended disconnection in progress
        self._message_thread = None
        self._connection_thread = None

        self.sensors = {}

        # Sensoren, deren Anmeldung die Anlage bestaetigt hat. Anders als self.sensors
        # (eine Arbeitsliste fuer den Wiederaufbau) taugt das als Zaehler fuer
        # "X Sensoren aktiv".
        self.sensors_confirmed = set()

        # True, solange ein laufender Verbindungsausfall bereits gemeldet und gezaehlt
        # ist. Verhindert, dass jeder Wiederholversuch als eigener Abbruch zaehlt -
        # siehe _connection_thread_loop().
        self._abbruch_gemeldet = False

        # Geraete, die sich nach dem Anmelden gemeldet haben (CnNodeNotification).
        self.knoten = []

        # True, wenn die Anlage unsere Sitzung verworfen hat (NOT_ALLOWED), die
        # TCP-Verbindung aber steht. Dann genuegt eine Neuanmeldung, siehe
        # _session_verloren() und _connection_thread_loop().
        self._session_invalid = False

        # Zeitstempel der letzten Sitzungsverluste, um eine Haeufung zu erkennen
        # (Hinweis auf einen konkurrierenden zweiten Client).
        self._session_verluste = []

        # Betriebsstatistik fuer die Diagnoseanzeige.
        #
        # Sinn: Seit die Aussetzer sauber abgefangen werden (verspaetete Antworten
        # verwerfen, Sitzung erneuern, nicht unterstuetzte Sensoren ueberspringen),
        # laeuft das Plugin darueber hinweg - und niemand sieht mehr, DASS etwas war.
        # Das ist im Betrieb richtig so, macht aber blind fuer schleichende Probleme:
        # eine Anlage, die staendig traege antwortet oder immer wieder die Sitzung
        # verwirft, faellt sonst erst auf, wenn gar nichts mehr geht.
        #
        # Jeweils Anzahl und Zeitpunkt des letzten Vorkommens - eine Zahl allein
        # sagt nicht, ob das Problem heute frueh oder vor drei Wochen war.
        self.stats = {
            'verbindungsabbrueche': 0,      # TCP-Verbindung weg, kompletter Neuaufbau
            'sitzungserneuerungen': 0,      # NOT_ALLOWED, Neuanmeldung ohne TCP-Abbau
            'antwort_timeouts': 0,          # Anlage hat nicht rechtzeitig geantwortet
            'verworfene_antworten': 0,      # verspaetete Antworten, entsorgt
            'uebersprungene_sensoren': 0,   # von dieser Anlage nicht unterstuetzt
            'letzter_verbindungsabbruch': None,
            'letzte_sitzungserneuerung': None,
            'letzter_timeout': None,
        }

        # True, sobald alle bekannten Sensoren auf der aktuellen Verbindung angemeldet
        # sind. Steuert nur die Statusanzeige, nicht das Veroeffentlichen.
        self.sensors_ready = False

        # True ab dem ersten echten Verbindungsverlust. Unterscheidet den Wiederaufbau
        # vom ersten Verbindungsaufbau, bei dem cfc.py die Sensoren selbst anmeldet.
        self._is_reconnect = False

        # Zeitstempel fuer die Statusanzeige. Werden von cfc.py gelesen.
        self.last_alive_ping = None    # updated every message-loop iteration - proves
                                        # the message thread is looping, not hung/dead
        self.last_keepalive_ok = None  # updated when a keepalive to the bridge succeeds
        self.last_sensor_data = None   # updated on any CnRpdoNotificationType, any sensor

    def _zaehle(self, zaehler, zeitstempel=None):
        """Erhoeht einen Statistikzaehler und merkt sich den Zeitpunkt."""
        self.stats[zaehler] = self.stats.get(zaehler, 0) + 1
        if zeitstempel:
            self.stats[zeitstempel] = time.time()

    # ==================================================================================================================
    # Core functions
    # ==================================================================================================================

    def connect(self, takeover=False):
        """Connect to the bridge and login. Disconnect existing clients if needed by default."""

        try:
            # Start connection
            self._connect(takeover=takeover)

        except PyComfoConnectNotAllowed:
            raise Exception('Could not connect to the bridge since the PIN seems to be invalid.')

        except PyComfoConnectOtherSession:
            raise Exception('Could not connect to the bridge since there is already an open session.')

        except OSError:
            #_LOGGER.error("Unexpected error in connect: " + sys.exc_info()[0])
            raise Exception('Could not connect to the bridge.')

        # Set flags to signal messages are being handled and we are not disconnecting
        self._stopping = False
        self._disconnecting = False
        self._connected.clear()

        # Start connection thread
        self._connection_thread = threading.Thread(target=self._connection_thread_loop)
        self._connection_thread.start()

        if not self._connected.wait(10):
            raise Exception('Could not connect to bridge since it didn\'t reply on time.')

        return True

    def disconnect(self):
        """Disconnect from the bridge."""

        # Set the flags to stop message handling and intended disconnection
        self._stopping = True
        self._disconnecting = True

        # Wait for the background thread to finish in case it is still active
        if self._connection_thread != None:
            self._connection_thread.join()

    def mark_disconnecting(self):
        """Markiert das bevorstehende Trennen als beabsichtigt.

        Ohne das werten die Hintergrund-Threads das Schliessen der Verbindung als
        Ausfall und beginnen einen Wiederaufbau.
        """
        self._stopping = True
        self._disconnecting = True

    def is_connected(self):
        """Returns whether there is a connection with the bridge."""

        return self._bridge.is_connected()

    def register_sensor(self, sensor_id: int, sensor_type: int = None):
        """Meldet einen Sensor bei der Anlage an.

        Ein Versuch ohne Wiederholung. Liefert None, wenn die Anlage den Sensor
        nicht kennt; nur OSError wird weitergereicht, weil dann die Verbindung fehlt.
        """

        if not sensor_type:
            sensor_type = RPDO_TYPE_MAP.get(sensor_id)
        if sensor_type is None:
            raise Exception("Registering sensor %d with unknown type" % sensor_id)

        try:
            reply = self.cmd_rpdo_request(sensor_id, sensor_type)

        except OSError:
            # The connection itself is gone (write failed, socket dead) - no amount of
            # local retrying fixes that, only a full reconnect will. Give up on this
            # sensor immediately and propagate. _connection_thread_loop and cfc.py's
            # startup loop already catch OSError here and react accordingly.
            #
            # Dies ist der EINZIGE Fall, der weitergereicht wird - alles andere unten
            # gilt als "dieser Sensor geht auf dieser Anlage nicht" und liefert None.
            _LOGGER.error("Sensor %d: Verbindung verloren beim Registrieren." % sensor_id)
            raise

        except ValueError:
            # Zeitueberschreitung beim Warten auf die Bestaetigung. Kein Grund zur
            # Panik: Nicht jede Anlage und nicht jeder Firmware-Stand kennt jede pdid,
            # und unbekannte werden schlicht ignoriert statt abgelehnt.
            self._zaehle('uebersprungene_sensoren')
            _LOGGER.warning("Sensor %d wird von dieser Anlage nicht unterstützt (keine Antwort) - wird übersprungen." % sensor_id)
            return None

        except PyComfoConnectError as e:
            # Die Anlage hat den Sensor ausdruecklich abgelehnt, z.B. mit NOT_EXIST
            # oder BAD_REQUEST. Frueher flog das als unbehandelte Ausnahme bis nach
            # oben durch und hat den Prozess beendet - fuer eine Anlage, die nur
            # hoeflich mitteilt, dass sie diesen Wert nicht kennt. Ebenfalls
            # ueberspringen.
            self._zaehle('uebersprungene_sensoren')
            _LOGGER.warning("Sensor %d wird von dieser Anlage abgelehnt (%s) - wird übersprungen."
                            % (sensor_id, type(e).__name__))
            return None

        # Register in memory
        self.sensors[sensor_id] = sensor_type
        self.sensors_confirmed.add(sensor_id)

        return reply

    def unregister_sensor(self, sensor_id: int, sensor_type: int = None):
        """Register a sensor on the bridge and keep it in memory that we are registered to this sensor."""

        if sensor_type is None:
            sensor_type = RPDO_TYPE_MAP.get(sensor_id)

        if sensor_type is None:
            raise Exception("Unregistering sensor %d with unknown type" % sensor_id)

        # Unregister in memory
        self.sensors.pop(sensor_id, None)

        # Unregister on bridge
        self.cmd_rpdo_request(sensor_id, sensor_type, timeout=0)

    def _command(self, command, params=None, use_queue=True, context=None):
        """Sendet einen Befehl und wartet auf die zugehoerige Antwort."""

        # Reference-number generation and the actual socket write both have to be
        # atomic across threads - see the _command_lock comment in __init__ for why
        # (main thread's sensor registration/diagnostics vs. the message thread's
        # periodic keepalive both call _command() and can genuinely overlap).
        with self._command_lock:
            # Remember our own reference number so _get_reply() can verify that whatever
            # confirm-type message it later receives actually answers *this* request,
            # not some other, unrelated request that happens to still be in flight (see
            # _get_reply's expected_reference parameter for why that distinction matters).
            my_reference = self._reference

            # Construct the message
            message = Message.create(
                self._local_uuid,
                self._bridge.uuid,
                command,
                {'reference': my_reference},
                params
            )

            # Increase message reference
            self._reference += 1

            # Beim Senden kann die Verbindung wegbrechen - der Fehler wird oben behandelt.
            try:
                self._bridge.write_message(message)

            except OSError:
                _LOGGER.error("Unexpected error in _command._bridge.write_message: " + sys.exc_info()[0].__name__)
                raise

        try:
            # Check if this command has a confirm type set
            confirm_type = message.class_to_confirm[command]

            # Read a message
            reply = self._get_reply(
                confirm_type,
                use_queue=use_queue,
                expected_reference=my_reference,
                context=context
            )

            return reply

        except KeyError:
            return None

        except OSError:
            # Meldungstext ohne %-Formatierung zusammensetzen: Der Inhalt kann Prozent-
            # zeichen enthalten, die logging sonst als Platzhalter deutet.
            if self._disconnecting:
                _LOGGER.info("_command._get_reply für confirm type " + confirm_type.__name__ + " abgebrochen (beabsichtigtes Herunterfahren): " + sys.exc_info()[0].__name__)
            else:
                _LOGGER.error("Unexpected error in _command._get_reply for confirm type " + confirm_type.__name__ + ": " + sys.exc_info()[0].__name__)
            raise

    def _session_verloren(self, grund, use_queue):
        """Behandelt eine von der Anlage verworfene Sitzung.

        Zaehlt die Verluste in einem gleitenden Zeitfenster. Haeufen sie sich, deutet
        das auf einen zweiten Client hin - die Anlage erlaubt nur eine Sitzung.
        """
        if not use_queue:
            return

        # Haeufung erkennen: Die Anlage laesst nur EINE Sitzung gleichzeitig zu. Meldet
        # sich staendig ein zweiter Client an (zweite Plugin-Instanz, Zehnder-App,
        # zweiter LoxBerry), nehmen sich beide abwechselnd die Sitzung weg. Das laesst
        # sich von hier aus nicht loesen - aber man kann es benennen, statt den Nutzer
        # ueber dauernde Neuanmeldungen im Log raetseln zu lassen.
        jetzt = time.time()
        self._session_verluste = [t for t in self._session_verluste if jetzt - t < 600]
        self._session_verluste.append(jetzt)

        # Ebenfalls als Fehler, aus demselben Grund wie beim Verbindungsabriss weiter
        # unten: Es ist eine Stoerung, auch wenn die Neuanmeldung anschliessend
        # gelingt - und der Log-Snapshot soll den Vorgang festhalten.
        if len(self._session_verluste) >= 3:
            _LOGGER.error(
                "Die Lüftungsanlage hat unsere Sitzung innerhalb von 10 Minuten schon %d mal "
                "verworfen (%s). Das deutet auf einen zweiten Client hin, der sich parallel "
                "verbindet - die ComfoConnect LAN C erlaubt nur eine Sitzung gleichzeitig. "
                "Mögliche Ursachen: eine zweite Plugin-Instanz auf einem anderen LoxBerry, "
                "die Zehnder-App im lokalen Netz, oder ein anderes Steuerungssystem."
                % (len(self._session_verluste), grund)
            )
        else:
            _LOGGER.error(
                "Die Lüftungsanlage hat unsere Sitzung verworfen (%s) - melde mich neu an." % grund
            )

        self._zaehle('sitzungserneuerungen', 'letzte_sitzungserneuerung')
        self._session_invalid = True
        self._stopping = True

    def _get_reply(self, confirm_type=None, timeout=5, use_queue=True, expected_reference=None, context=None):
        """Wartet auf die Antwort zu einer Anfrage.

        Ordnet ueber die Referenznummer zu. Antworten auf bereits aufgegebene
        Anfragen werden verworfen, statt spaeteren Wartenden untergeschoben zu werden.
        """

        start = time.time()

        # Nachrichten, die nicht zu dieser Anfrage gehoeren, wandern zurueck in die
        # Warteschlange - ein anderer Aufrufer wartet moeglicherweise darauf.
        deferred = []

        try:
            while True:
                message = None

                if use_queue:
                    try:
                        # Fetch the message from the queue.  The network thread has put it there for us.
                        message = self._queue.get(timeout=timeout)
                        if message:
                            self._queue.task_done()

                            # Der Nachrichten-Thread meldet den Verbindungsverlust - nicht auf das Zeitlimit warten.
                            if message is _CONNECTION_LOST:
                                raise BrokenPipeError('Connection lost while waiting for a reply.')
                    except queue.Empty:
                        # We got no message
                        pass

                else:
                    # Fetch the message directly from the socket
                    message = self._bridge.read_message(timeout=timeout)

                if message:
                    # Passt die Nachricht zu dieser Anfrage? Typ allein genuegt nicht, die
                    # Referenznummer muss stimmen.
                    is_ours = confirm_type is not None and message.msg.__class__ == confirm_type and (
                        expected_reference is None or message.cmd.reference == expected_reference
                    )

                    if confirm_type is None or is_ours:
                        # Check status code
                        if message.cmd.result == GatewayOperation.OK:
                            pass
                        elif message.cmd.result == GatewayOperation.BAD_REQUEST:
                            raise PyComfoConnectBadRequest()
                        elif message.cmd.result == GatewayOperation.INTERNAL_ERROR:
                            raise PyComfoConnectInternalError()
                        elif message.cmd.result == GatewayOperation.NOT_REACHABLE:
                            raise PyComfoConnectNotReachable()
                        elif message.cmd.result == GatewayOperation.OTHER_SESSION:
                            self._session_verloren('OTHER_SESSION', use_queue)
                            raise PyComfoConnectOtherSession(message.msg.devicename)
                        elif message.cmd.result == GatewayOperation.NOT_ALLOWED:
                            self._session_verloren('NOT_ALLOWED', use_queue)
                            raise PyComfoConnectNotAllowed()
                        elif message.cmd.result == GatewayOperation.NO_RESOURCES:
                            raise PyComfoConnectNoResources()
                        elif message.cmd.result == GatewayOperation.NOT_EXIST:
                            raise PyComfoConnectNotExist()
                        elif message.cmd.result == GatewayOperation.RMI_ERROR:
                            raise PyComfoConnectRmiError()

                    if confirm_type is None:
                        # We just need a message
                        return message
                    elif is_ours:
                        # Richtiger Typ und passende Referenz - dann ist es unsere Antwort.
                        return message
                    elif message.msg.__class__ == confirm_type:
                        # Right type, but for a different (older or newer) request than the
                        # one we're currently waiting on - not ours.
                        if message.cmd.reference in self._abandoned_references:
                            # Auf diese Referenz warten wir nicht mehr (Zeitlimit). Verwerfen, damit sie
                            # nicht dauerhaft in der Warteschlange kreist.
                            self._zaehle('verworfene_antworten')
                            _LOGGER.debug(
                                "Discarding orphaned confirm for a reference we already gave up on: "
                                + str(message.cmd.reference)
                            )
                        else:
                            # Defer it (see comment above on `deferred`) instead of putting it
                            # straight back onto self._queue, so this same loop doesn't just
                            # immediately pop it again next iteration.
                            deferred.append(message)
                            _LOGGER.debug(
                                "Ignoring confirm for a different reference while waiting for "
                                + str(expected_reference) + ": got reference " + str(message.cmd.reference)
                            )
                    elif message.cmd.type == GatewayOperation.CnRpdoNotificationType:
                        # Kein verirrter Rueckschein, sondern eine unaufgeforderte Sensormeldung.
                        # Wird direkt verarbeitet statt zurueckgelegt.
                        self._handle_rpdo_notification(message)
                    elif message.cmd.type in (
                        GatewayOperation.GatewayNotificationType,
                        GatewayOperation.CnNodeNotificationType,
                        GatewayOperation.CnAlarmNotificationType,
                    ):
                        # Same idea for the other unsolicited notification types
                        # _message_thread_loop knows about - nothing to reply to, just noise
                        # while we're waiting for our own confirm. Log at debug, not warning.
                        _LOGGER.debug("Ignoring unsolicited notification while waiting for a reply: " + str(message.cmd.type))
                    else:
                        # Antwort eines anderen Befehls, ausser der Reihe eingetroffen.
                        deferred.append(message)
                        _LOGGER.warning("We got a message with an incorrect type." + str(message.msg.__class__))

                if time.time() - start > timeout:
                    # Identify what exactly we were waiting for, so the log line is useful
                    # on its own instead of just naming the confirm class. .__name__ rather
                    # than str() so it stays visible in LoxBerry's HTML log viewer - see the
                    # comment in _command()'s OSError handler.
                    detail = confirm_type.__name__ if confirm_type is not None else "(kein Typ)"
                    if context:
                        detail += " (" + context + ")"
                    if expected_reference is not None:
                        detail += " reference=" + str(expected_reference)

                    # Wir geben diese Referenz endgueltig auf (der Aufrufer mag es erneut
                    # versuchen, aber dann mit einer neuen Nummer) - taucht spaeter doch
                    # noch eine Antwort dazu auf, ist sie herrenlos. Siehe den Zweig
                    # "Discarding orphaned confirm" weiter oben.
                    #
                    # WICHTIG: Das gilt fuer JEDEN Antworttyp. Frueher stand dieser
                    # Eintrag nur im else-Zweig, die CnRmiResponse-Sonderbehandlung
                    # darunter sprang vorher heraus. Jede zeitlich verpasste
                    # RMI-Antwort blieb dadurch dauerhaft in der Warteschlange: Sie
                    # wurde bei jedem folgenden Aufruf erneut hervorgeholt, als fremd
                    # erkannt und zurueckgelegt - endlos. In einem echten Log sammelten
                    # sich so binnen zwei Stunden acht solcher Karteileichen an, jede
                    # davon bei jeder Abfrage aufs Neue durchgesehen.
                    if expected_reference is not None:
                        self._abandoned_references.add(expected_reference)

                    self._zaehle('antwort_timeouts', 'letzter_timeout')
                    _LOGGER.error("Timeout waiting for response. " + detail)

                    # Vergleich mit der Klasse selbst, nicht mit ihrem Namen als Zeichenkette.
                    if confirm_type is CnRmiResponse:
                        # RMI-Aufrufe melden das Ausbleiben ueber den Rueckgabewert
                        # statt ueber eine Ausnahme.
                        return False

                    raise ValueError('Timeout waiting for response.')
        finally:
            # Fremde Nachrichten zurueck in die Warteschlange - ein anderer Aufrufer
            # wartet moeglicherweise darauf.
            for m in deferred:
                self._queue.put(m)

    # ==================================================================================================================
    # Connection thread
    # ==================================================================================================================
    def _connection_thread_loop(self):
        """Makes sure that there is a connection open."""

        self._disconnecting = False     # no intended disconnection in progress
        while not self._disconnecting:

            # Start connection
            if not self.is_connected():
                # Anmeldung der Sensoren steht noch aus; kennzeichnet ausserdem einen echten
                # Wiederaufbau.
                self.sensors_ready = False
                self._is_reconnect = True

                # NUR EINMAL je Ausfall melden und zaehlen, nicht bei jedem
                # Wiederholversuch. Diese Schleife dreht sich waehrend eines Ausfalls
                # etwa alle 5-15 Sekunden; ohne diese Bremse zaehlte ein zweistuendiger
                # Ausfall rund 500 "Abbrueche" (gemessen: 2099 Stueck in 8,5 Stunden)
                # und erzeugte im selben Takt Log-Snapshots. Die Zahl war damit
                # wertlos - sie mass die Dauer des Ausfalls, nicht deren Anzahl.
                #
                # Zurueckgesetzt wird das erst, wenn die Verbindung wieder steht
                # (siehe unten) - dann ist der naechste Verlust wieder ein neuer.
                if not self._abbruch_gemeldet:
                    self._abbruch_gemeldet = True
                    self._zaehle('verbindungsabbrueche', 'letzter_verbindungsabbruch')

                    # BEWUSST als Fehler, obwohl es sich von selbst behebt: Ein Abriss
                    # der Verbindung ist eine Stoerung, auch wenn der Wiederaufbau
                    # gelingt. Das haelt die Regel einfach - was einen Log-Snapshot
                    # verdient, ist ein Fehler, und der Berichtsschreiber braucht keinen
                    # zweiten Einstieg neben der Logstufe. Nebeneffekt: Wer das Loglevel
                    # auf "Fehler" stellt, sieht diese Abbrueche jetzt trotzdem.
                    #
                    # Hier und nicht in _message_thread_loop, wo der Abriss zuerst
                    # auffaellt: Dort gibt es je nach Ursache drei verschiedene
                    # Meldungen, und ein Abriss wuerde dreifach gezaehlt.
                    _LOGGER.error("Verbindung zur Lüftungsanlage abgerissen - baue sie neu auf.")

                # Wait a bit to avoid hammering the bridge
                time.sleep(5)

                _LOGGER.info('Reconnecting to Bridge...')

                try:
                    # Connect or re-connect
                    self._connect()

                except PyComfoConnectOtherSession:
                    self._bridge.disconnect()
                    _LOGGER.error('Could not connect to the bridge since there is already an open session.')
                    continue

                except TimeoutError as exc:
                    self._bridge.disconnect()
                    _LOGGER.error(exc)
                    continue
                
                # OSError: Errno 113, No route to host
                except OSError as exc:
                    self._bridge.disconnect()
                    _LOGGER.error(exc)
                    continue

                except Exception as exc:
                    _LOGGER.error(exc)
                    self._bridge.disconnect() # formally disconnect 
                    raise Exception('Could not connect to the bridge.')

                else: 
                    self._stopping = False  # Clear Stop message handling flag

            # Only start background thread if we truly are connected, otherwise try reconnecting again
            if self.is_connected():
                # Verbindung steht wieder - der naechste Verlust ist damit ein neuer
                # Vorfall und darf erneut gezaehlt und gemeldet werden.
                self._abbruch_gemeldet = False
                self.knoten = []

                # Warteschlange hier leeren, nicht im Nachrichten-Thread: Sonst koennte ein
                # Wartender noch die alte erwischen und ins Leere lauschen.
                self._queue = queue.Queue()

                # Neue Verbindung, neue Referenznummern.
                self._abandoned_references = set()
                self._session_invalid = False

                # Start background thread
                self._message_thread = threading.Thread(target=self._message_thread_loop)
                self._message_thread.start()

                # Re-register for sensor updates
                if len(self.sensors)>0:
                    _LOGGER.info('Reconnected to Bridge. Registering sensors...')
                    # Fresh session - none of the previous confirmations are valid anymore
                    # (RPDO subscriptions don't survive a reconnect), so the "confirmed"
                    # count must start back at 0 and only grow as register_sensor() below
                    # actually succeeds again.
                    self.sensors_confirmed = set()
                    registration_ok = True
                    # need to handle exceptions during sensor re-registration to have a robust library
                    try:
                        # Kopie der Liste vor dem Durchlauf: cfc.py kann waehrenddessen Sensoren
                        # ergaenzen, was sonst den Durchlauf abbrechen wuerde.
                        for sensor_id, sensor_type in list(self.sensors.items()):
                            self.register_sensor(sensor_id, sensor_type)

                    except OSError:
                        # Text zusammensetzen statt als zweites Argument uebergeben - logging deutete
                        # Prozentzeichen darin sonst als Platzhalter.
                        _LOGGER.error("Unexpected error in _connection_thread_loop while registering sensors: " + sys.exc_info()[0].__name__)
                        registration_ok = False

                    if not registration_ok:
                        self._stopping = True   # Set stop handling message flag - forces a fresh reconnect below.
                        # sensors_ready deliberately left False here - the loop is about
                        # to reconnect and try the whole sweep again from scratch.
                    else:
                        _LOGGER.info(str(len(self.sensors)) + ' sensor(s) registered, ready event set.')
                        if self._is_reconnect:
                            self.sensors_ready = True
                        # Erster Verbindungsaufbau - cfc.py meldet die Sensoren selbst an.
                else:
                    # Nichts anzumelden, etwa beim Wiederaufbau vor dem ersten Durchlauf in cfc.py.
                    if self._is_reconnect:
                        self.sensors_ready = True

                # Send the event that we are ready
                self._connected.set()
                
                # Wait until the message thread stops working
                self._message_thread.join()

                # Hat die Anlage nur unsere SITZUNG verworfen (NOT_ALLOWED), ist die
                # TCP-Verbindung selbst voellig in Ordnung. Die protokollgerechte
                # Antwort darauf ist, sich neu anzumelden - nicht, die Verbindung
                # wegzuwerfen und alles von vorne aufzubauen. Gelingt die Anmeldung,
                # geht es oben in der Schleife direkt mit Message-Thread und
                # Sensor-Neuregistrierung weiter, ohne TCP-Abbau und ohne die 5s
                # Wartezeit.
                #
                # use_queue=False ist hier zwingend: Der Message-Thread ist gerade
                # beendet, es fuellt also niemand mehr die Warteschlange - die Antwort
                # muss direkt vom Socket gelesen werden.
                if self._session_invalid and self.is_connected() and not self._disconnecting:
                    self._session_invalid = False
                    try:
                        _LOGGER.info("Melde die Sitzung bei der Lüftungsanlage neu an...")
                        self.cmd_start_session(True, use_queue=False)
                        self._stopping = False      # sonst beendet sich der neue Thread sofort
                        self.sensors_ready = False  # Abos sind mit der alten Sitzung verfallen
                        self._is_reconnect = True   # damit sensors_ready danach wieder gesetzt wird
                        _LOGGER.info("Sitzung erneuert - registriere die Sensoren neu.")
                        continue
                    except Exception as e:
                        _LOGGER.warning(
                            "Sitzung konnte nicht erneuert werden (%s) - baue die Verbindung "
                            "komplett neu auf." % type(e).__name__
                        )

                # Close socket connection
                self._bridge.disconnect()
            else:
                _LOGGER.warning('Could not (re)connect to the Bridge. Trying again...')
               
                
    def _connect(self, takeover=False):
        """Connect to the bridge and login. Disconnect existing clients if needed by default."""

        try:
            # Connect to the bridge
            self._bridge.connect()

            # Login
            self.cmd_start_session(takeover, use_queue=False)

        except PyComfoConnectNotAllowed:
            # No dice, maybe we are not registered yet...

            # Register
            self.cmd_register_app(self._local_uuid, self._local_devicename, self._pin, use_queue=False)

            # Login
            self.cmd_start_session(takeover, use_queue=False)

        return True

    # ==================================================================================================================
    # Message thread
    # ==================================================================================================================

    def _message_thread_loop(self):
        """Listen for incoming messages and queue them or send them to a callback method."""

        # Die Warteschlange wird bewusst im Verbindungs-Thread geleert, nicht hier.

        next_keepalive = 0

        while not self._stopping:

            # Jeder Durchlauf belegt, dass dieser Thread noch laeuft.
            self.last_alive_ping = time.time()

            # Sends a keepalive every KEEPALIVE seconds.
            if time.time() > next_keepalive:
                next_keepalive = time.time() + KEEPALIVE
                try:
                    _LOGGER.info('Sending keep alive...' + str(self.cmd_keepalive()))
                    self.last_keepalive_ok = time.time()

                except OSError:
                    # Same %-formatting trap - concatenate, don't pass as extra arg.
                    _LOGGER.error("Wanted to send keep alive, but hit an unexpected error in _message_thread_loop: " + sys.exc_info()[0].__name__)
                    return

            try:
                # Read a message from the bridge.
                message = self._bridge.read_message()

            except BrokenPipeError as exc:
                # Thread beenden; der Verbindungs-Thread startet ihn neu, sofern kein
                # beabsichtigtes Trennen vorliegt.
                if self._disconnecting:
                    _LOGGER.info("Verbindung getrennt (beabsichtigtes Herunterfahren)." + str(exc))
                else:
                    _LOGGER.warning("The connection was broken. We will try to reconnect." + str(exc))
                self._bridge.disconnect()
                self._queue.put(_CONNECTION_LOST)
                return
            except ConnectionResetError as exc:
                if self._disconnecting:
                    _LOGGER.info("Verbindung getrennt (beabsichtigtes Herunterfahren)." + str(exc))
                else:
                    _LOGGER.warning("The connection was reseted. " + str(exc))
                self._bridge.disconnect()
                self._queue.put(_CONNECTION_LOST)
                return
            except ConnectionError as exc:
                if self._disconnecting:
                    _LOGGER.info("Verbindung getrennt (beabsichtigtes Herunterfahren)." + str(exc))
                else:
                    _LOGGER.warning("Connection Error: " + str(exc))
                self._bridge.disconnect()
                self._queue.put(_CONNECTION_LOST)
                return

            if message:
                if message.cmd.type == GatewayOperation.CnRpdoNotificationType:
                    self._handle_rpdo_notification(message)

                elif message.cmd.type == GatewayOperation.GatewayNotificationType:
                    _LOGGER.info('Unhandled GatewayNotificationType')
                    # TODO: We should probably handle these somehow
                    pass

                elif message.cmd.type == GatewayOperation.CnNodeNotificationType:
                    if message.msg.productId != 0:
                        # Nur protokollieren. Frueher wurde die Geraeteliste zusaetzlich
                        # gemerkt, um die ComfoCool-Sensoren nur bei vorhandenem Modul zu
                        # registrieren. Das ist entfallen: Die Anlage nimmt diese
                        # Abonnements auch ohne Modul an und antwortet mit 0, es gibt also
                        # keinen Fehler zu vermeiden - und wen der Wert stoert, der waehlt
                        # den Sensor in den Einstellungen ab.
                        self.knoten.append({
                            'name': PRODUCT_ID_MAP.get(message.msg.productId,
                                                       'Unbekannt (%d)' % message.msg.productId),
                            'node': message.msg.nodeId,
                            'modus': message.msg.NodeModeType.Name(message.msg.mode),
                        })
                        _LOGGER.info('CnNodeNotificationType: %s @ Node Id %d [%s]',
                            PRODUCT_ID_MAP.get(message.msg.productId, 'Unbekannt (%d)' % message.msg.productId),
                            message.msg.nodeId,
                            message.msg.NodeModeType.Name(message.msg.mode))
                    else:
                        _LOGGER.warning('CnNodeNotificationType: Node Id %d [%s]',
                            message.msg.nodeId,
                            message.msg.NodeModeType.Name(message.msg.mode))

                elif message.cmd.type == GatewayOperation.CnAlarmNotificationType:
                    self._handle_alarm_notification(message)

                elif message.cmd.type == GatewayOperation.CloseSessionRequestType:
                    if self._disconnecting:
                        _LOGGER.info('Bridge hat die Session geschlossen (beabsichtigtes Herunterfahren).')
                    else:
                        _LOGGER.info('The Bridge has asked us to close the connection. We will try to reconnect later.')
                    # Thread beenden; der Verbindungs-Thread startet ihn neu.
                    return

                else:
                    # Send other messages to a queue
                    self._queue.put(message)

        return

    def _handle_rpdo_notification(self, message):
        """Wertet einen eingehenden Sensorwert aus und reicht ihn an den Rueckruf weiter."""

        # Only process CnRpdoNotificationType
        if message.cmd.type != GatewayOperation.CnRpdoNotificationType:
            return False

        # Beleg, dass Daten fliessen - unabhaengig davon, welcher Sensor gesendet hat.
        self.last_sensor_data = time.time()

        # Extract data
        data = message.msg.data.hex()
        if len(data) == 2:
            val = struct.unpack('b', message.msg.data)[0]
        elif len(data) == 4:
            val = struct.unpack('h', message.msg.data)[0]
        elif len(data) == 8:
            val = data
        else:
            val = data

        # Update local state
        # self.sensors[message.msg.pdid] = val

        if self.callback_sensor:
            # Abgesichert, weil dieser Aufruf im NACHRICHTEN-THREAD laeuft: Wirft der
            # Rueckruf, stirbt der Thread - und damit kommen keine Sensordaten mehr an
            # und es geht kein Keepalive mehr raus, obwohl der Prozess weiterlaeuft
            # und nach aussen gesund aussieht. Genau diese Art von Ausfall haben wir
            # mehrfach gesucht.
            #
            # Ein einzelner Messwert, der Aerger macht, darf hoechstens sich selbst
            # kosten. Der Fehler wird protokolliert (und loest damit auch einen
            # Log-Snapshot aus), die Schleife laeuft weiter.
            try:
                self.callback_sensor(message.msg.pdid, val)
            except Exception as e:
                _LOGGER.error("Verarbeitung des Sensorwerts pdid %s fehlgeschlagen (%s: %s) - "
                              "übersprungen, die Verbindung bleibt bestehen."
                              % (message.msg.pdid, type(e).__name__, e))

    def _handle_alarm_notification(self, message):
        """Wertet eine Stoerungsmeldung aus und uebersetzt die Fehlerbits in Klartext."""

        errors = {}
        try:
            rohbits = getattr(message.msg, 'errors', b'') or b''

            # Ab Firmware 1.4.0 haben sich die Bedeutungen ab Bit 70 verschoben.
            version = getattr(message.msg, 'swProgramVersion', 0) or 0
            tabelle = ALARM_ERRORS_140 if version <= ALARM_FIRMWARE_140 else ALARM_ERRORS

            nummer = 0
            for byte in rohbits:
                for bit in range(8):
                    if byte & (1 << bit):
                        errors[nummer] = tabelle.get(nummer, "Unbekannter Fehler %d" % nummer)
                    nummer += 1

        except Exception as e:
            # Eine Stoerungsmeldung darf niemals den Message-Thread mitreissen -
            # dann liefe gar nichts mehr, nur weil ein Feld anders aussieht als
            # erwartet.
            # Typ mit ausgeben: viele Ausnahmen dieser Bibliothek haben gar keinen
            # Text, str(e) alleine ergaebe eine Meldung ohne jede Ursache.
            _LOGGER.error("Konnte Alarmmeldung nicht auswerten (%s): %s" % (type(e).__name__, str(e)))
            return

        node_id = getattr(message.msg, 'nodeId', 0)

        if errors:
            for nummer, text in sorted(errors.items()):
                _LOGGER.error("Störung der Lüftungsanlage (Fehler %d): %s" % (nummer, text))
        else:
            _LOGGER.info("Lüftungsanlage meldet keine Störungen mehr.")

        if self.callback_alarm:
            self.callback_alarm(node_id, errors)

    def cmd_clear_errors(self):
        """Quittiert die an der Anlage anstehenden Stoerungen."""
        return self.cmd_rmi_request(b'\x82\x03\x01')

        return True

    # ==================================================================================================================
    # Commands
    # ==================================================================================================================

    def cmd_start_session(self, take_over=False, use_queue: bool = True):
        """Starts the session on the device by logging in and optionally disconnecting an already existing session."""

        reply = self._command(
            StartSessionRequest,
            {
                'takeover': take_over
            },
            use_queue=use_queue
        )
        return reply  # TODO: parse output

    def cmd_close_session(self, use_queue: bool = True):
        """Meldet die Sitzung bei der Anlage ab."""

        reply = self._command(
            CloseSessionRequest,
            use_queue=use_queue
        )
        return reply  # TODO: parse output

    def cmd_list_registered_apps(self, use_queue: bool = True):
        """Returns a list of all the registered clients."""

        reply = self._command(
            ListRegisteredAppsRequest,
            use_queue=use_queue
        )
        return [
            {'uuid': app.uuid, 'devicename': app.devicename} for app in reply.msg.apps
        ]

    def cmd_register_app(self, uuid, device_name, pin, use_queue: bool = True):
        """Register a new app by specifying our own uuid, device_name and pin code."""

        reply = self._command(
            RegisterAppRequest,
            {
                'uuid': uuid,
                'devicename': device_name,
                'pin': pin,
            },
            use_queue=use_queue
        )
        return reply  # TODO: parse output

    def cmd_deregister_app(self, uuid, use_queue: bool = True):
        """Remove the specified app from the registration list."""

        if uuid == self._local_uuid:
            raise Exception('You should not deregister yourself.')

        try:
            self._command(
                DeregisterAppRequest,
                {
                    'uuid': uuid
                },
                use_queue=use_queue
            )
            return True

        except PyComfoConnectBadRequest:
            return False

    def cmd_version_request(self, use_queue: bool = True):
        """Returns version information."""

        reply = self._command(
            VersionRequest,
            use_queue=use_queue
        )
        return {
            'gatewayVersion': reply.msg.gatewayVersion,
            'serialNumber': reply.msg.serialNumber,
            'comfoNetVersion': reply.msg.comfoNetVersion,
        }

    def cmd_time_request(self, use_queue: bool = True):
        """Returns the current time on the device."""

        reply = self._command(
            CnTimeRequest,
            use_queue=use_queue
        )
        return reply.msg.currentTime

    def cmd_rmi_request(self, message, node_id: int = 1, use_queue: bool = True):
        """Sendet eine RMI-Anfrage und liefert die Antwort zurueck."""

        reply = self._command(
            CnRmiRequest,
            {
                'nodeId': node_id or 1,
                'message': message
            },
            use_queue=use_queue
        )
        return reply

    def cmd_rpdo_request(self, pdid: int, type: int = 1, zone: int = 1, timeout=None, use_queue: bool = True):
        """Register a RPDO request.

        NOTE: `timeout` here is the SUBSCRIPTION lifetime sent to the bridge inside the
        request (timeout=0 cancels an existing subscription) - it has nothing to do with
        how long we wait for the reply.
        """

        reply = self._command(
            CnRpdoRequest,
            {
                'pdid': pdid,
                'type': type,
                'zone': zone or 1,
                'timeout': timeout
            },
            use_queue=use_queue,
            context="pdid=%d" % pdid
        )
        return reply

    def cmd_keepalive(self, use_queue: bool = True):
        """Sendet ein Keepalive. Die Anlage beantwortet es nicht."""

        self._command(
            KeepAlive,
            use_queue=use_queue
        )
        return True
