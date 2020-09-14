from julia_client import julia_client
import os
import subprocess
import time

class JuliaServer:
    def __init__(self, path_to_julia_server = 'julia/server.jl'):
        self._path_to_julia_server = path_to_julia_server
        self._server_process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    def start(self):
        server_process = subprocess.Popen([
            'julia',
            self._path_to_julia_server,
        ])
        try:
            julia_client.connect()
            res = julia_client.send('ping')
            self._server_process = server_process
        except Exception as err:
            server_process.kill()
            raise err

    def stop(self):
        if self._server_process:
            self._server_process.kill()
        self._server_process = None
