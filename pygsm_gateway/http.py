import socket
import cgi
import logging
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn
from urlparse import urlparse, parse_qs


logger = logging.getLogger('pygsm_gateway.http')


class PygsmHttpServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""

    def __init__(self, address, send_method, status_method):
        class Handler(BaseHTTPRequestHandler):
            _send_method = send_method
            _status_method = status_method

            def request_close(self):
                self.end_headers()
                self.wfile.write('\n')
                self.wfile.close()

            def do_POST(self):
                logger.debug('got POST')
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={'REQUEST_METHOD': 'POST',
                             'CONTENT_TYPE': self.headers['Content-Type'],
                             })
                if 'identity' in form and 'text' in form:
                    ok = self._send_method(form['identity'].value,
                                      form['text'].value)
                    self.send_response(200)
                else:
                    self.send_response(400)
                self.end_headers()
                self.wfile.write('\n')
                self.wfile.close()
                return

            #added to play nicely with rapidsms_httprouter, although this perhaps is semantically incorrect.
            def do_GET(self):
                logger.debug('Got GET:'+self.path)
                if self.path == '/status':
                    status = self._status_method()
                    logger.debug(status)
                    if status is "NOK":
                        self.send_response(200)
                        self.send_header("_status","Not OK")
                        self.request_close()
                        return
                    else:
                        self.send_response(200,str(status))
                        self.send_header("_status","Maybe ok")
                        for key,value in status.items():
                            self.send_header(key,value)
                        self.request_close()
                        return
                form = parse_qs(urlparse(self.path).query)

                ## Next two ifs: handling empty messages
                if 'text' not in form:
                    self.send_response(400)
                    self.request_close()
                    return
                if form['text'][0] is None or form['text'][0]=='':
                    print "Form text:["+form['text']+"]"
                    self.send_response(400)
                    self.request_close()
                    return

                if 'identity' in form and 'text' in form:
                    result = self._send_method(form['identity'][0],
                                      form['text'][0])
                    # This is where we should return 200 / something else
                    if result is True:
                        self.send_response(200)
                    else:
                        self.send_response(424) #method error
                else:
                    self.send_response(400)
                self.end_headers()
                self.wfile.write('\n')
                self.wfile.close()
                return

        def handle(self):
            """Handles a request ignoring dropped connections."""

            try:
                return BaseHTTPRequestHandler.handle(self)
            except (socket.error, socket.timeout) as e:
                self.connection_dropped(e)


        HTTPServer.__init__(self, address, Handler)
