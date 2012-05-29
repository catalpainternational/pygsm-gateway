#!/usr/bin/env python
import platform
import logging

from pygsm_gateway.http import PygsmHttpServer
from pygsm_gateway.gsm import GsmPollingThread
from serial.tools import list_ports


logger = logging.getLogger()
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

fabulaws_logger = logging.getLogger('pygsm_gateway')
fabulaws_logger.setLevel(logging.DEBUG)


### Auto detect and configure for Huawei 3G/GSM modem

# get platform name
platform_name = platform.platform()

# If the platform is windows then we cycle through the COM ports
# until we find the right interface
if platform_name.startswith('Windows'):
    for c in list_ports.comports():
        if c[1].find('PC UI Interface') != -1:
            port = c[0]
# If the platform is MacOS X / Darwin then we just set the default name
elif platform.platform().startswith('Darwin'):
    port = '/dev/tty.HUAWEIMobile-Modem'
# Linux should be somethign like this but this still needs to be fleshed out
else:
    port = '/dev/ttyUSB0'


if __name__ == '__main__':
    args = {
        #'url': 'http://localhost:8000/backend/pygsm-gateway/',  # for use with rapidsms-threadless-router
        'url': 'http://localhost:8000/router/receive',  # for use with rapidsms-httprouter
        'url_args': {},
        'modem_args': {
            'port': port,
            'baudrate': 115200,
            'rtscts': 1,
            'timeout': 20,
        }
    }
    gsm_thread = GsmPollingThread(**args)
    gsm_thread.start()

    server = PygsmHttpServer(('localhost', 8080), gsm_thread.send)
    print 'Starting server, use <Ctrl-C> to stop'
    try:
        server.serve_forever()
    except:
        raise
    finally:
        gsm_thread.running = False
        gsm_thread.join()
