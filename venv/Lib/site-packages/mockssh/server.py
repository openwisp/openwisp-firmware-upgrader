import errno
import logging
import os
import socket
import subprocess
import threading

from mockssh.streaming import StreamTransfer

try:
    from queue import Queue
except ImportError:  # Python 2.7
    from Queue import Queue

try:
    import selectors
except ImportError:  # Python 2.7
    import selectors2 as selectors

import paramiko

from mockssh import sftp

__all__ = [
    "Server",
]

SERVER_KEY_PATH = os.path.join(os.path.dirname(__file__), "server-key")


class Handler(paramiko.ServerInterface):
    log = logging.getLogger(__name__)

    def __init__(self, server, client_conn):
        self.server = server
        self.thread = None
        self.command_queues = {}
        client, _ = client_conn
        self.transport = t = paramiko.Transport(client)
        t.add_server_key(paramiko.RSAKey(filename=SERVER_KEY_PATH))
        t.set_subsystem_handler("sftp", sftp.SFTPServer)

    def run(self):
        self.transport.start_server(server=self)
        while True:
            channel = self.transport.accept()
            if channel is None:
                break
            if channel.chanid not in self.command_queues:
                self.command_queues[channel.chanid] = Queue()
            t = threading.Thread(target=self.handle_client, args=(channel,))
            t.setDaemon(True)
            t.start()

    def handle_client(self, channel):
        try:
            command = self.command_queues[channel.chanid].get(block=True)
            self.log.debug("Executing %s", command)
            p = subprocess.Popen(command, shell=True,
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            StreamTransfer(channel, p).run()
            channel.send_exit_status(p.returncode)
        except Exception:
            self.log.error("Error handling client (channel: %s)", channel,
                           exc_info=True)
        finally:
            try:
                channel.close()
            except EOFError:
                self.log.debug("Tried to close already closed channel")

    def check_auth_publickey(self, username, key):
        try:
            _, known_public_key = self.server._users[username]
        except KeyError:
            self.log.debug("Unknown user '%s'", username)
            return paramiko.AUTH_FAILED
        if known_public_key == key:
            self.log.debug("Accepting public key for user '%s'", username)
            return paramiko.AUTH_SUCCESSFUL
        self.log.debug("Rejecting public ley for user '%s'", username)
        return paramiko.AUTH_FAILED

    def check_channel_exec_request(self, channel, command):
        self.command_queues.setdefault(channel.get_id(), Queue()).put(command)
        return True

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def get_allowed_auths(self, username):
        return "publickey"


class Server(object):
    host = "127.0.0.1"
    handler_cls = Handler

    log = logging.getLogger(__name__)

    def __init__(self, users):
        self._socket = None
        self._thread = None
        self._users = {}
        for uid, private_key_path in users.items():
            self.add_user(uid, private_key_path)

    def add_user(self, uid, private_key_path, keytype="ssh-rsa"):
        if keytype == "ssh-rsa":
            key = paramiko.RSAKey.from_private_key_file(private_key_path)
        elif keytype == "ssh-dss":
            key = paramiko.DSSKey.from_private_key_file(private_key_path)
        elif keytype in paramiko.ECDSAKey.supported_key_format_identifiers():
            key = paramiko.ECDSAKey.from_private_key_file(private_key_path)
        elif keytype == "ssh-ed25519":
            key = paramiko.Ed25519Key.from_private_key_file(private_key_path)
        else:
            raise Exception("Unable to handle key of type {}".format(keytype))

        self._users[uid] = (private_key_path, key)

    def __enter__(self):
        self._socket = s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((self.host, 0))
        s.listen(5)
        self._thread = t = threading.Thread(target=self._run)
        t.setDaemon(True)
        t.start()
        return self

    def _run(self):
        sock = self._socket
        selector = selectors.DefaultSelector()
        selector.register(sock, selectors.EVENT_READ)
        while sock.fileno() > 0:
            self.log.debug("Waiting for incoming connections ...")
            events = selector.select(timeout=1.0)
            if events:
                try:
                    conn, addr = sock.accept()
                except OSError as ex:
                    if ex.errno in (errno.EBADF, errno.EINVAL):
                        break
                    raise
                self.log.debug("... got connection %s from %s", conn, addr)
                handler = self.handler_cls(self, (conn, addr))
                t = threading.Thread(target=handler.run)
                t.setDaemon(True)
                t.start()

    def __exit__(self, *exc_info):
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()
        except Exception:
            pass
        self._socket = None
        self._thread = None

    def client(self, uid):
        private_key_path, _ = self._users[uid]
        c = paramiko.SSHClient()
        host_keys = c.get_host_keys()
        key = paramiko.RSAKey.from_private_key_file(SERVER_KEY_PATH)
        host_keys.add(self.host, "ssh-rsa", key)
        host_keys.add("[%s]:%d" % (self.host, self.port), "ssh-rsa", key)
        c.set_missing_host_key_policy(paramiko.RejectPolicy())
        c.connect(hostname=self.host,
                  port=self.port,
                  username=uid,
                  key_filename=private_key_path,
                  allow_agent=False,
                  look_for_keys=False)
        return c

    @property
    def port(self):
        return self._socket.getsockname()[1]

    @property
    def users(self):
        return self._users.keys()
