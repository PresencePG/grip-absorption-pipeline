import zmq
from json import dumps as json_dumps
import time
import sys
import os
import subprocess
import time
import asyncio

# launch the python talker
CLIENT_CONNECT_URI = os.environ.get('CLIENT_CONNECT_URI')

class JuliaClient:
    def __init__(self, connection_uri=CLIENT_CONNECT_URI):
        self._connection_uri = connection_uri
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.PAIR)
        self.connected = False

    def connect(self):
        if self.connected: return
        self._socket.connect(self._connection_uri)
        self.connected = True

    def send(self, message):
        timestamp = time.ctime()
        self._socket.send_string(json_dumps({
            'message': message,
            'at': timestamp,
        }))
        response = self._socket.recv()
        return response

    def send_data(self, dict):
        timestamp = time.ctime()
        dict.update({'message':'data collected',
                            'at':timestamp})
        self._socket.send_string(json_dumps(
            dict
        ))
        response = self._socket.recv()
        return response

julia_client = JuliaClient()
