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

KEEPALIVE = 60

DEFAULT_LOCAL_UUID = bytes.fromhex('00000000000000000000000000001337')
DEFAULT_LOCAL_DEVICENAME = 'pycomfoconnect'
DEFAULT_PIN = 0

_LOGGER = logging.getLogger('comfoconnect')

# Sentinel pushed onto self._queue by _message_thread_loop the moment it detects
# the connection is dead (BrokenPipeError/ConnectionResetError/ConnectionError).
# Without this, a call blocked in _get_reply()'s self._queue.get(timeout=5) has no
# way to find out the connection already died in the *other* thread - it just sits
# there uselessly until its own independent 5s timeout expires, which is why the
# log used to show the "connection was reseted" warning followed several seconds
# later by a seemingly unrelated "Timeout waiting for response" error for a
# message that could obviously never arrive anymore. Pushing this sentinel wakes
# the waiter up immediately instead.
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

    def __init__(self, bridge: Bridge, local_uuid=DEFAULT_LOCAL_UUID, local_devicename=DEFAULT_LOCAL_DEVICENAME,
                 pin=DEFAULT_PIN):
        self._bridge = bridge
        self._local_uuid = local_uuid
        self._local_devicename = local_devicename
        self._pin = pin
        self._reference = 1

        self._queue = queue.Queue()

        # References we've personally given up on (a plain client-side timeout in
        # _get_reply(), see there) - a confirm for one of these that shows up later
        # is permanently orphaned: whoever originally sent that request has already
        # moved on (retried with a new reference, or given up for good), so nobody
        # will ever be waiting for it again. Without tracking this, such a confirm
        # gets deferred, handed back to self._queue, picked up again by the NEXT
        # unrelated wait, found not to match either, deferred again... forever, for
        # the remaining lifetime of the connection - one harmless but permanently
        # recurring "Ignoring confirm..." log line per subsequent _command() call.
        # Bounded in practice: only grows on a timeout (rare), and is cleared on
        # every reconnect along with self._queue itself.
        self._abandoned_references = set()

        # Guards reference-number generation and the actual socket write in
        # _command() (see there). Two different threads legitimately call _command()
        # concurrently in normal operation - the main thread doing the startup sensor
        # registration burst / diagnostic queries, and the background message thread
        # sending its periodic cmd_keepalive() - and without this lock both the
        # "self._reference += 1" read-modify-write and the raw socket.sendall() call
        # are unsynchronized: two threads could hand out the SAME reference number
        # (breaking the reference-matching in _get_reply()) or interleave their bytes
        # on the wire while writing concurrently (corrupting the message framing).
        # Only covers the write side, not the wait-for-reply side, so two commands can
        # still be in flight and waiting on their own replies at the same time without
        # blocking each other for up to 5s.
        self._command_lock = threading.Lock()

        self._connected = threading.Event()
        self._stopping = False          # signals stopping message handling
        self._disconnecting = False     # signals intended disconnection in progress
        self._message_thread = None
        self._connection_thread = None

        self.sensors = {}

        # self.sensors above is really a work list of "sensors we know about and
        # should (re-)register on every reconnect" - cfc.py pre-populates entries
        # into it for sensors that haven't been attempted yet (so a dropped
        # connection mid-burst doesn't lose track of them), and every reconnect's
        # re-registration pass iterates the whole thing again regardless of
        # whether each entry has actually been confirmed by the bridge yet. That
        # makes len(self.sensors) meaningless as a "how many are really working
        # right now" count - it was already at its final size before most entries
        # were ever confirmed. This separate set only ever gains a sensor_id once
        # the bridge has actually confirmed that specific registration (see
        # register_sensor()), and gets reset at the start of every reconnect's
        # re-registration pass since RPDO subscriptions don't survive a
        # reconnect - cfc.py's status file reads this, not self.sensors, for the
        # "X sensors active" count.
        self.sensors_confirmed = set()

        # True only while a connection is up AND the (re-)registration sweep for all
        # known sensors (self.sensors) has actually finished - False from the moment a
        # disconnect is noticed until the next successful sweep completes.
        #
        # PURELY INFORMATIONAL: this drives the status display only (cfc.py's status
        # file -> index.cgi shows "Registriere Sensoren" while it's False). It does NOT
        # gate MQTT publishing - callback_sensor() publishes every value immediately,
        # including during a registration sweep. A sensor only starts sending data once
        # the bridge has confirmed its own subscription, so such a value is a real,
        # current reading and there's no reason to withhold it.
        #
        # Set by _connection_thread_loop() on every (re)connect; cfc.py additionally
        # sets it True itself after ITS OWN initial registration loop at startup
        # completes (that first pass runs in cfc.py's main thread, not here).
        self.sensors_ready = False

        # True once _connection_thread_loop() has noticed at least one real
        # disconnect and is (re)connecting because of it. Guards sensors_ready so the
        # background loop only ever touches it for a GENUINE reconnect - not for its
        # own very first pass right after the initial connect(), which runs
        # concurrently with cfc.py's own startup registration loop (self.sensors is
        # still empty at that point, since register_sensor() only adds to it on
        # success) and would otherwise hit the "nothing to (re-)register yet" branch
        # and flip sensors_ready True within milliseconds - long before cfc.py's own
        # sweep, or even the MQTT client, are anywhere close to ready. Observed in
        # practice as a flood of "Fehler published, RC=4" (MQTT_ERR_NO_CONN) during
        # every single startup.
        self._is_reconnect = False

        # Heartbeat/health bookkeeping, read from the outside (cfc.py) to build a
        # status file. These are plain timestamps (time.time(), or None until the
        # first occurrence) updated cheaply in memory - the caller decides how often
        # to persist them to disk, so this class doesn't need to know anything about
        # files, paths or LoxBerry conventions.
        self.last_alive_ping = None    # updated every message-loop iteration - proves
                                        # the message thread is looping, not hung/dead
        self.last_keepalive_ok = None  # updated when a keepalive to the bridge succeeds
        self.last_sensor_data = None   # updated on any CnRpdoNotificationType, any sensor

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
        """Flags an intended disconnection without blocking on the background threads.

        disconnect() (above) does the same flag-setting but then joins the connection
        thread - fine for a normal shutdown, but too slow/risky for cfc.py's SIGTERM
        handler, which sends CloseSessionRequest directly via cmd_close_session() and
        then calls os._exit() shortly after (see the handler for why). Without calling
        this first, the message/connection threads have no way to know the socket
        dying moments later (once the bridge processes our CloseSessionRequest) is
        expected - they'd log a misleading "connection was broken, we will try to
        reconnect" warning and kick off a doomed reconnect attempt during an
        intentional shutdown. Call this before cmd_close_session().
        """
        self._stopping = True
        self._disconnecting = True

    def is_connected(self):
        """Returns whether there is a connection with the bridge."""

        return self._bridge.is_connected()

    def register_sensor(self, sensor_id: int, sensor_type: int = None):
        """Register a sensor on the bridge and keep it in memory that we are registered to this sensor.

        Single attempt only - no retry, no cancel-and-retry dance. That used to exist to
        recover from a single dropped CnRpdoConfirm, but retrying introduced its own risk
        (a second CnRpdoRequestType for a pdid whose first request might still be in
        flight, not actually lost, observed to sometimes trigger a bridge-side connection
        reset) and, in practice, often didn't help anyway - a sensor that doesn't answer
        within the standard reply timeout is either genuinely unsupported by this hardware
        or will work fine on the NEXT registration pass (after a reconnect).

        Uses the same plain reply timeout as every other command - on real hardware the
        bridge confirms each subscription within a few milliseconds (a full 50-sensor
        sweep measured at well under a second), so anything approaching seconds here
        already means something is genuinely wrong, not just slow.
        """

        if not sensor_type:
            sensor_type = RPDO_TYPE_MAP.get(sensor_id)
        if sensor_type is None:
            raise Exception("Registering sensor %d with unknown type" % sensor_id)

        try:
            reply = self.cmd_rpdo_request(sensor_id, sensor_type)

        except PyComfoConnectNotAllowed:
            return None

        except OSError:
            # The connection itself is gone (write failed, socket dead) - no amount of
            # local retrying fixes that, only a full reconnect will. Give up on this
            # sensor immediately and propagate. _connection_thread_loop and cfc.py's
            # startup loop already catch OSError here and react accordingly.
            _LOGGER.error("Sensor %d: Verbindung verloren beim Registrieren." % sensor_id)
            raise

        except ValueError:
            # Timeout waiting for CnRpdoConfirm - not necessarily a real problem, could
            # simply be a pdid this hardware doesn't support. Logged and skipped, not fatal.
            _LOGGER.error("Sensor %d konnte nicht registriert werden - Gerät hat nicht geantwortet." % sensor_id)
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
        """Sends a command and wait for a response if the request is known to return a result.

        Every command waits the same standard reply timeout (see _get_reply) - there is
        deliberately no per-call override anymore.

        context: short human-readable label (e.g. "pdid=146") included in _get_reply()'s
        timeout log line, so a timeout message identifies what it was actually waiting for
        instead of just the confirm type.
        """

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

            # Be careful when sending message, we need to catch a broken connection here.
            # Previously this swallowed the error and returned False, which no caller
            # checked - execution just carried on to wait a full timeout for a reply to
            # a message that was never sent. Re-raise instead, so callers that expect
            # OSError (register_sensor, _connection_thread_loop) find out immediately
            # and can trigger a proper reconnect instead of a doomed retry.
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
            # Same %-formatting trap as described in _connection_thread_loop: these
            # must be concatenated into one string, not passed as extra positional
            # args, otherwise logging itself raises TypeError and spams the log.
            #
            # During an intentional shutdown (self._disconnecting, see
            # mark_disconnecting()) this is expected, not an error: cmd_close_session()
            # sends CloseSessionRequest and the bridge closes the socket right after,
            # which surfaces here as exactly this OSError. The caller (the SIGTERM
            # handler in cfc.py) already logs a calm, accurate INFO line for that case -
            # log this one quietly too instead of a scary, redundant ERROR right above it.
            # .__name__, not str(): str() of a protobuf class gives
            # "<class 'zehnder_pb2.CloseSessionConfirm'>" - and LoxBerry's web log viewer
            # renders the log as HTML, so it swallows that whole thing as an unknown tag
            # and the type silently disappears from the displayed line (it IS in the raw
            # file, just invisible where you'd normally read it). The bare name shows up
            # fine and is the only interesting part anyway.
            if self._disconnecting:
                _LOGGER.info("_command._get_reply für confirm type " + confirm_type.__name__ + " abgebrochen (beabsichtigtes Herunterfahren): " + sys.exc_info()[0].__name__)
            else:
                _LOGGER.error("Unexpected error in _command._get_reply for confirm type " + confirm_type.__name__ + ": " + sys.exc_info()[0].__name__)
            raise

    def _get_reply(self, confirm_type=None, timeout=5, use_queue=True, expected_reference=None, context=None):
        """Pops a message of the queue, optionally looking for a specific type.

        context: short human-readable label (e.g. "pdid=146") for the timeout log line -
        see _command()'s docstring.

        expected_reference: the message.cmd.reference value of OUR OWN request. When the
        bridge is backed up (busy flushing notifications for already-registered sensors,
        see the timeout handling above), confirms can arrive many seconds late and out of
        order relative to when we gave up waiting and retried. Without this check, a stale
        confirm belonging to an earlier, already-abandoned attempt - carrying the SAME
        message class (e.g. CnRpdoConfirmType) but a DIFFERENT reference number - used to
        satisfy this wait anyway, since only the class was checked. That silently handed
        register_sensor() a "success" for the wrong request: no timeout, no warning, but
        the confirm for the actual current attempt (and the real sensor data) could still
        be minutes away or never verified at all. Observed directly in a log: retry #2 for
        a sensor's registration was quietly satisfied by a ~9s-late confirm meant for a
        completely different, already-abandoned earlier attempt.
        """

        start = time.time()

        # Messages pulled off self._queue that turn out not to be ours (wrong
        # reference, or a genuine type mismatch) - buffered locally and only put
        # back onto the shared queue once this call is about to return, instead of
        # immediately re-queueing each one on the spot. Immediately re-queueing
        # caused a tight infinite loop in practice: a single orphaned confirm (e.g.
        # a very late reply for an attempt we'd already given up on and retried
        # past) gets popped, found not to match, pushed straight back onto the same
        # queue - which this same loop then immediately pops again, since nothing
        # else is there to get in between. That spins as fast as the CPU allows,
        # burning 100% of a core and flooding the log (observed: tens of thousands
        # of "Ignoring confirm..." lines within a few milliseconds) until the
        # timeout eventually fires. Buffering locally means every pass through the
        # loop makes real progress - either finding our own message further back in
        # the queue, or genuinely blocking in queue.get() for something new to
        # arrive - and nothing is lost: anyone else who still needs one of these
        # gets it back once we're done here (success, timeout, or error).
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

                            # The message thread died because the connection is gone - don't
                            # wait out the rest of our own timeout for a reply that can never
                            # arrive, fail immediately instead.
                            if message is _CONNECTION_LOST:
                                raise BrokenPipeError('Connection lost while waiting for a reply.')
                    except queue.Empty:
                        # We got no message
                        pass

                else:
                    # Fetch the message directly from the socket
                    message = self._bridge.read_message(timeout=timeout)

                if message:
                    # Whether this particular message is actually the one we're waiting for -
                    # right type, and (if we know our own reference) the matching reference too.
                    # Status codes below are only meaningful for OUR OWN request's reply: a
                    # BAD_REQUEST/NOT_EXIST/etc. on some other, unrelated stale/out-of-order
                    # message must not be misattributed to the request we're currently making
                    # (that used to happen here, since the status check ran unconditionally on
                    # every message before the type/reference was even looked at).
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
                            raise PyComfoConnectOtherSession(message.msg.devicename)
                        elif message.cmd.result == GatewayOperation.NOT_ALLOWED:
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
                        # We need the message with the correct type AND, if we know which
                        # reference we're actually waiting for, the matching reference - see
                        # the expected_reference docstring above for why the reference check
                        # matters (right type alone isn't enough once replies can arrive
                        # several seconds late and out of order).
                        return message
                    elif message.msg.__class__ == confirm_type:
                        # Right type, but for a different (older or newer) request than the
                        # one we're currently waiting on - not ours.
                        if message.cmd.reference in self._abandoned_references:
                            # We ourselves already gave up on this exact reference (a plain
                            # timeout, see below) - nobody is ever going to claim it, so
                            # discard it here and now instead of deferring it. Deferring
                            # would just hand it back onto self._queue, where the NEXT
                            # unrelated wait pops it, rejects it again, and defers it again -
                            # forever, for the rest of this connection's lifetime (harmless,
                            # but a permanently recurring log line for something we already
                            # know is dead).
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
                        # Not a mismatched reply - this is a completely normal, unsolicited
                        # sensor-value push that can arrive at any time, including while we're
                        # waiting for an unrelated confirm (e.g. during the initial
                        # StartSessionConfirm handshake right after a reconnect/takeover, before
                        # the bridge has finished flushing notifications tied to the previous
                        # session). _message_thread_loop routes these the same way once it takes
                        # over - do it here too instead of logging a scary "incorrect type"
                        # warning and stranding the message in self._queue (which nobody
                        # drains while use_queue=False, e.g. during cmd_start_session), which
                        # used to eat into this call's own timeout budget for no reason and
                        # could make the initial handshake fail/crash if enough of these arrived
                        # in a row.
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
                        # A genuine mismatch: some other command's reply, unexpectedly out of
                        # order. This is the case the original code was written for - defer it
                        # (see comment above on `deferred`) so whoever is actually waiting for
                        # it can still find it once we're done here, without this loop
                        # immediately re-popping the same message.
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

                    # Identity check against the imported class, not a string comparison
                    # against its repr - the old "<class 'zehnder_pb2.CnRmiResponse'>"
                    # string would silently stop matching if the module/class were ever
                    # renamed or the protobuf runtime changed how it formats a class.
                    if confirm_type is CnRmiResponse:
                        # We got no message for confirm_type CnRmiResponse
                        _LOGGER.error("Timeout waiting for response. " + detail)
                        return False
                    else:
                        # We're giving up on this reference for good here (the caller may
                        # retry, but that happens with a brand-new reference number) - if a
                        # confirm for it still shows up later, it's permanently orphaned. See
                        # the "Discarding orphaned confirm" branch above.
                        if expected_reference is not None:
                            self._abandoned_references.add(expected_reference)

                        _LOGGER.error("Timeout waiting for response. " + detail)
                        raise ValueError('Timeout waiting for response.')
        finally:
            # Give back anything we picked up along the way that wasn't ours, so
            # whoever it actually belongs to (or the next call, or _message_thread_loop's
            # own routing) can still find it - see the `deferred` comment above.
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
                # Not ready for MQTT publishing again until the sensors below have all
                # been (re-)attempted on the new connection - see the attribute comment
                # in __init__ for why. Also marks this as a genuine reconnect, not the
                # initial connect - see the _is_reconnect comment in __init__.
                self.sensors_ready = False
                self._is_reconnect = True

                # Wait a bit to avoid hammering the bridge
                time.sleep(5)
                
                _LOGGER.warning('Reconnecting to Bridge...')

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
                # Reset the queue here, synchronously, BEFORE starting the message
                # thread - not as the first line inside _message_thread_loop() itself.
                # thread.start() returns as soon as the OS has scheduled the new
                # thread, not once it has actually run any code, so this loop carries
                # straight on to register_sensor() below while the new thread's very
                # first instructions are still pending. If _message_thread_loop() were
                # the one resetting self._queue, a _get_reply() call from the
                # registration loop below could grab a reference to the OLD Queue
                # object in that window, then the reset swaps self._queue to a new one
                # out from under it - the waiting call is now stuck listening on an
                # orphaned queue that will never receive anything, and just times out
                # uselessly even though a real reply arrived. Doing the reset here
                # instead, synchronously in this same thread right before start(),
                # closes that window entirely.
                self._queue = queue.Queue()

                # A fresh connection means a fresh set of reference numbers too (see
                # __init__) - any previously abandoned reference can never legitimately
                # reappear on this new connection, so drop the bookkeeping along with it.
                self._abandoned_references = set()

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
                        # list(...) takes a snapshot of the dict before iterating: cfc.py's
                        # main thread can concurrently add entries to self.sensors (e.g. the
                        # startup registration loop pre-remembering not-yet-attempted sensors
                        # after losing the connection), and iterating a dict directly while
                        # another thread changes its size raises "RuntimeError: dictionary
                        # changed size during iteration" - which used to kill this thread the
                        # same way the bugs fixed earlier did.
                        for sensor_id, sensor_type in list(self.sensors.items()):
                            reply = self.register_sensor(sensor_id, sensor_type)
                            if reply is None:
                                # Every sensor in self.sensors already registered successfully
                                # on a PREVIOUS connection (that's the only way it got added
                                # here) - so unlike cfc.py's very first startup sweep, a
                                # failure here isn't "unsupported hardware", it's a sign this
                                # particular reconnect attempt is bad. No skipping: abort the
                                # whole sweep and force a fresh reconnect below, exactly like
                                # an OSError would - it worked before, it should work again.
                                _LOGGER.error(
                                    "Sensor %d konnte bei der Neu-Registrierung nach einem Reconnect "
                                    "nicht registriert werden - breche ab (kein Überspringen) und "
                                    "versuche einen frischen Reconnect." % sensor_id
                                )
                                registration_ok = False
                                break

                    except OSError:
                        # NOTE: string concatenation, NOT a second argument. logging
                        # treats extra positional args as %-format arguments for the
                        # message - passing one without a matching %s in the string
                        # raises "TypeError: not all arguments converted during string
                        # formatting" inside logging itself, which then dumps a full
                        # "--- Logging error ---" block plus two tracebacks into the
                        # log on every single reconnect. Harmless for program flow,
                        # but it buried the actual message in ~35 lines of noise.
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
                        # else: this was the very first connect - self.sensors was (and
                        # still is, most likely) empty because cfc.py's own startup sweep
                        # runs concurrently in the main thread and hasn't populated it
                        # yet. Leave sensors_ready alone; cfc.py sets it itself once ITS
                        # sweep actually finishes (see main()).
                else:
                    # Nothing to (re-)register (e.g. reconnecting before cfc.py's startup
                    # sweep ever ran, or a genuine reconnect with no sensors left to
                    # restore) - nothing is blocking readiness, but only say so for an
                    # actual reconnect. On the very first connect this branch is
                    # basically always taken too (self.sensors starts empty - see
                    # above), and must NOT flip sensors_ready True early - that's
                    # cfc.py's call once its own startup sweep is done.
                    if self._is_reconnect:
                        self.sensors_ready = True

                # Send the event that we are ready
                self._connected.set()
                
                # Wait until the message thread stops working
                self._message_thread.join()

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

        # NOTE: self._queue is deliberately NOT reset here anymore - it's reset
        # synchronously in _connection_thread_loop() right before this thread is
        # started, to avoid a race where a _get_reply() call already running (e.g.
        # from the sensor registration loop right after connect()) could grab a
        # reference to the queue object that's about to be replaced out from under
        # it. See the comment there for details.

        next_keepalive = 0

        while not self._stopping:

            # Every loop iteration proves this thread is alive and not hung/blocked
            # somewhere - the cheapest, most fine-grained "still alive" signal we have
            # (the loop cycles roughly once per second thanks to bridge.read_message()'s
            # internal 1s select timeout). Persisting this to disk is the caller's job.
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
                # Close this thread. The connection_thread will restart us - unless
                # self._disconnecting is set (see mark_disconnecting()/disconnect()),
                # in which case this socket dying is exactly what we asked for by
                # sending CloseSessionRequest, not a real failure to report/recover from.
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
                        _LOGGER.info('CnNodeNotificationType: %s @ Node Id %d [%s]', 
                            PRODUCT_ID_MAP[message.msg.productId], 
                            message.msg.nodeId, 
                            message.msg.NodeModeType.Name(message.msg.mode))
                        # TODO: We should probably handle these somehow
                    else:
                        _LOGGER.warning('CnNodeNotificationType: Node Id %d [%s]', 
                            message.msg.nodeId, 
                            message.msg.NodeModeType.Name(message.msg.mode))
                    pass

                elif message.cmd.type == GatewayOperation.CnAlarmNotificationType:
                    _LOGGER.info('Unhandled CnAlarmNotificationType')
                    # TODO: We should probably handle these somehow
                    pass

                elif message.cmd.type == GatewayOperation.CloseSessionRequestType:
                    if self._disconnecting:
                        _LOGGER.info('Bridge hat die Session geschlossen (beabsichtigtes Herunterfahren).')
                    else:
                        _LOGGER.info('The Bridge has asked us to close the connection. We will try to reconnect later.')
                    # Close this thread. The connection_thread will restart us (unless
                    # self._disconnecting is set, see mark_disconnecting()).
                    return

                else:
                    # Send other messages to a queue
                    self._queue.put(message)

        return

    def _handle_rpdo_notification(self, message):
        """Update internal sensor state and invoke callback."""

        # Only process CnRpdoNotificationType
        if message.cmd.type != GatewayOperation.CnRpdoNotificationType:
            return False

        # Proof that data is actually flowing from the ventilation unit - tracked per
        # notification regardless of which sensor, since any single sensor may
        # legitimately stay silent for a long time (e.g. filter days remaining).
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
            self.callback_sensor(message.msg.pdid, val)

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
        """Tells the bridge we're intentionally ending this session.

        Without ever calling this, the bridge has no way to know a disconnect is
        intentional vs. the client just vanishing (process killed, network drop) -
        it was observed to keep the old session around for several seconds ("resumed:
        true" on the next StartSessionConfirm) before handing over to a reconnecting
        client, flushing a backlog of leftover messages tied to the old session in the
        process. See cfc.py's SIGTERM handler, which calls this during a
        "Speichern"-triggered restart so the bridge can drop the session cleanly before
        the new process connects.

        Uses the standard reply timeout like everything else. That timeout is almost
        never reached: the bridge responds by closing the socket instead of sending a
        CloseSessionConfirm, which wakes the waiting call immediately (see
        _CONNECTION_LOST) rather than letting it run out the clock.
        """

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
        """Sends a RMI request."""

        reply = self._command(
            CnRmiRequest,
            {
                'nodeId': node_id or 1,
                'message': message
            },
            use_queue=use_queue
        )
        return True

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
        """Sends a keepalive."""

        self._command(
            KeepAlive,
            use_queue=use_queue
        )
        return True
