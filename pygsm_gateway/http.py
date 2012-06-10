import socket
import cgi
import logging
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn
from urlparse import urlparse, parse_qs
import time

logger = logging.getLogger('pygsm_gateway.http')


class PygsmHttpServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""

    def __init__(self, address, enqueue_method, status_method):
        class Handler(BaseHTTPRequestHandler):
            _enqueue_send = enqueue_method
            _enqueue_status = status_method

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
                    task = self._enqueue_status(self)
                    while not task.is_done:
                        time.sleep(0.25)
                        
                    logger.debug(task.result)
                    self.send_response(200) # request was processed succesfully
                    
                    if task.result is "NOK":
                        self.send_header("_status","Not OK")
                    else:
                        self.send_header("_status","Maybe ok")
                        for key,value in task.result.items():
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
                    task = self._enqueue_send(form['identity'][0],
                                      form['text'][0],self)
                    while not task.is_done:
                        time.sleep(0.25)
                    
                    if task.result is True:
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
                print "there was an exception:"
                print e
                self.connection_dropped(e)


        HTTPServer.__init__(self, address, Handler)
