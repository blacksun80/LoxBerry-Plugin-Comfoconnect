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
        self._connected = threading.Event()
        self._stopping = False          # signals stopping message handling
        self._disconnecting = False     # signals intended disconnection in progress
        self._message_thread = None
        self._connection_thread = None

        self.sensors = {}

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
            self._connection_thread = None

    def is_connected(self):
        """Returns whether there is a connection with the bridge."""

        return self._bridge.is_connected()

    def register_sensor(self, sensor_id: int, sensor_type: int = None, retries: int = 3):
        """Register a sensor on the bridge and keep it in memory that we are registered to this sensor.

        A single CnRpdoConfirm going missing (observed in practice as occasional, seemingly
        random timeouts on otherwise perfectly working sensors during the fast back-to-back
        registration burst at startup) does not mean the sensor/pdid is unsupported. Retry a
        few times before giving up - this recovers the vast majority of cases that used to be
        permanent failures (or, before that, crashed the whole plugin) after a single timeout.
        """

        if not sensor_type:
            sensor_type = RPDO_TYPE_MAP.get(sensor_id)
        if sensor_type is None:
            raise Exception("Registering sensor %d with unknown type" % sensor_id)

        # Register on bridge
        attempt = 0
        while True:
            attempt += 1
            is_last_attempt = attempt >= retries
            try:
                # While retries remain, ask _get_reply() to log a plain timeout as WARNING
                # instead of ERROR - it isn't a real failure yet, just a dropped reply we're
                # about to retry. Only the final, exhausted attempt should read as ERROR.
                reply = self.cmd_rpdo_request(sensor_id, sensor_type, quiet_timeout=not is_last_attempt)
                break

            except PyComfoConnectNotAllowed:
                return None

            except OSError:
                # The connection itself is gone (write failed, socket dead) - no
                # amount of local retrying fixes that, only a full reconnect will.
                # Give up on this sensor immediately and propagate, instead of
                # burning through 3 local retries (and then doing the same for
                # every remaining sensor) against a socket that is never coming
                # back on its own. _connection_thread_loop already catches OSError
                # here and triggers a proper reconnect.
                _LOGGER.error("Sensor %d: Verbindung verloren beim Registrieren." % sensor_id)
                raise

            except ValueError:
                # Timeout waiting for CnRpdoConfirm.
                if is_last_attempt:
                    _LOGGER.error("Sensor %d konnte nach %d Versuchen nicht registriert werden - Gerät hat nicht geantwortet." % (sensor_id, attempt))
                    return None
                _LOGGER.warning("Sensor %d: keine Antwort (Versuch %d/%d), erneuter Versuch..." % (sensor_id, attempt, retries))
                time.sleep(0.2)

        # Register in memory
        self.sensors[sensor_id] = sensor_type

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

    def _command(self, command, params=None, use_queue=True, quiet_timeout=False):
        """Sends a command and wait for a response if the request is known to return a result."""

        # Construct the message
        message = Message.create(
            self._local_uuid,
            self._bridge.uuid,
            command,
            {'reference': self._reference},
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
            reply = self._get_reply(confirm_type, use_queue=use_queue, quiet_timeout=quiet_timeout)

            return reply

        except KeyError:
            return None

        except OSError:
            # Same %-formatting trap as described in _connection_thread_loop: these
            # must be concatenated into one string, not passed as extra positional
            # args, otherwise logging itself raises TypeError and spams the log.
            _LOGGER.error("Unexpected error in _command._get_reply for confirm type " + str(confirm_type) + ": " + sys.exc_info()[0].__name__)
            raise

    def _get_reply(self, confirm_type=None, timeout=5, use_queue=True, quiet_timeout=False):
        """Pops a message of the queue, optionally looking for a specific type.

        quiet_timeout: if True, log a timeout on confirm_type as WARNING instead of
        ERROR. Used by callers (e.g. register_sensor()) that will retry the command
        themselves, so a single dropped reply isn't misreported as a hard error while
        a retry is still pending - only the final, exhausted attempt should read as ERROR.
        """

        start = time.time()

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
                elif message.msg.__class__ == confirm_type:
                    # We need the message with the correct type
                    return message
                else:
                    # We got a message with an incorrect type. Hopefully, this doesn't happen to often,
                    # since we just put it back on the queue.
                    self._queue.put(message)
                    _LOGGER.warning("We got a message with an incorrect type." + str(message.msg.__class__))

            if time.time() - start > timeout:
                if str(confirm_type) == "<class 'zehnder_pb2.CnRmiResponse'>":
                    # We got no message for confirm_type CnRmiResponse
                    _LOGGER.error("Timeout waiting for response." + str(confirm_type))
                    return False
                else:
                    if quiet_timeout:
                        _LOGGER.warning("Timeout waiting for response." + str(confirm_type))
                    else:
                        _LOGGER.error("Timeout waiting for response." + str(confirm_type))
                    raise ValueError('Timeout waiting for response.')

    # ==================================================================================================================
    # Connection thread
    # ==================================================================================================================
    def _connection_thread_loop(self):
        """Makes sure that there is a connection open."""

        self._disconnecting = False     # no intended disconnection in progress
        while not self._disconnecting:

            # Start connection
            if not self.is_connected():

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
                # Start background thread
                self._message_thread = threading.Thread(target=self._message_thread_loop)
                self._message_thread.start()

                # Re-register for sensor updates
                if len(self.sensors)>0:
                    _LOGGER.info('Reconnected to Bridge. Registering sensors...')
                    # need to handle exceptions during sensor re-registration to have a robust library
                    try:
                        # register_sensor() already retries a few times on a plain response
                        # timeout (ValueError) and logs+skips that one sensor if it keeps
                        # failing, instead of raising - so one dropped reply can no longer
                        # kill this whole thread. A genuine connection failure still raises
                        # OSError and is handled below (triggers a fresh reconnect).
                        #
                        # list(...) takes a snapshot of the dict before iterating: cfc.py's
                        # main thread can concurrently add entries to self.sensors (e.g. the
                        # startup registration loop pre-remembering not-yet-attempted sensors
                        # after losing the connection), and iterating a dict directly while
                        # another thread changes its size raises "RuntimeError: dictionary
                        # changed size during iteration" - which used to kill this thread the
                        # same way the bugs fixed earlier did.
                        for sensor_id, sensor_type in list(self.sensors.items()):
                            self.register_sensor(sensor_id, sensor_type)

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
                        self._stopping = True   # Set stop handling message flag because of this error in connection

                    else:
                        _LOGGER.info(str(len(self.sensors)) + ' sensor(s) registered, ready event set.')

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

        # Reinitialise the queues
        self._queue = queue.Queue()

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
                # Close this thread. The connection_thread will restart us.
                _LOGGER.warning("The connection was broken. We will try to reconnect." + str(exc))
                self._bridge.disconnect()
                self._queue.put(_CONNECTION_LOST)
                return
            except ConnectionResetError as exc:
                _LOGGER.warning("The connection was reseted. " + str(exc))
                self._bridge.disconnect()
                self._queue.put(_CONNECTION_LOST)
                return
            except ConnectionError as exc:
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
                    _LOGGER.info('The Bridge has asked us to close the connection. We will try to reconnect later.')
                    # Close this thread. The connection_thread will restart us.
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
        """Stops the current session."""

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

    def cmd_rpdo_request(self, pdid: int, type: int = 1, zone: int = 1, timeout=None, use_queue: bool = True,
                          quiet_timeout: bool = False):
        """Register a RPDO request."""

        reply = self._command(
            CnRpdoRequest,
            {
                'pdid': pdid,
                'type': type,
                'zone': zone or 1,
                'timeout': timeout
            },
            use_queue=use_queue,
            quiet_timeout=quiet_timeout
        )
        return reply

    def cmd_keepalive(self, use_queue: bool = True):
        """Sends a keepalive."""

        self._command(
            KeepAlive,
            use_queue=use_queue
        )
        return True
