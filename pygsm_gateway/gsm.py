import time
import copy
import urllib
import urllib2
import logging
import threading
from pygsm import errors

# modified by Nicolas Hoibian

import pygsm

logger = logging.getLogger('pygsm_gateway.gsm')

# Time to wait on the modem when polling it
# default is 0.1
BLOCK_TIME = 1
BLOCK_TIME_SHORT = 0.5
BLOCK_TIME_LONG = 2

# number of seconds to wait between
# polling the modem for incoming SMS
# (if BLOCK_TIME is 0.1)
POLL_INTERVAL = 5

# time to wait for the start method to
# complete before assuming that it failed
MAX_CONNECT_TIME = 10

class MetaGsmPollingThread(threading.Thread):
    
    def __init__(self,args):
        self.passthrough_args = args
        self.running=True
        self.gsmThread = None
        super(MetaGsmPollingThread, self).__init__()

    def run(self):
        while self.running is True:
            try:
                self.gsmThread = GsmPollingThread(**self.passthrough_args)
                self.gsmThread.start()
                print "########## Started the children thread -- GsmPollingThread"
                while self.running is True and self.gsmThread is not None and self.gsmThread.running is True:
                    time.sleep(BLOCK_TIME_LONG)
            except errors.GsmModemError:
                time.sleep(BLOCK_TIME_LONG*2)
            except KeyboardInterrupt, er:
                print "Keyboard interrupt:",er
                raise(er)
        
    def send(self, identity, text):
        logger.info("Got some send:"+ identity + text)
        # Wait until we have a thread to talk to or MAX_CONNECT_TIME * BLOCK_TIME_SHORT
        n = 0
        while self.gsmThread is None and n < MAX_CONNECT_TIME:
            time.sleep(BLOCK_TIME_SHORT)
            n+=1
            logger.info("The thread is not ready to send yet. ("+str(n)+")")
        # We didn't wait long enough
        if self.gsmThread is None or self.gsmThread.running is False:
            logger.info("The thread was not ready in time")
            return False

        return self.gsmThread.send(identity, text)


class GsmPollingThread(threading.Thread):
    _title = "pyGSM"

    # number of seconds to wait between
    # polling the modem for incoming SMS
    POLL_INTERVAL = 5

    

    def __init__(self, url, url_args, modem_args):
        self.url = url
        self.url_args = url_args
        self.modem_kwargs = modem_args
        self.modem = None

        # set a default timeout if it wasn't specified in localsettings.py;
        # otherwise read() will hang forever if the modem is powered off
        if "timeout" not in self.modem_kwargs:
            self.modem_kwargs["timeout"] = '3'
        super(GsmPollingThread, self).__init__()

    def _wait_for_modem(self):
        """
        Blocks until this backend has connected to and initialized the modem,
        waiting for a maximum of MAX_CONNECT_TIME (default=10) seconds.
        Returns true when modem is ready, or false if it times out.
        """

        # if the modem isn't present yet, this message is probably being sent by
        # an application during startup from the main thread, before this thread
        # has connected to the modem. block for a short while before giving up.
        for n in range(0, MAX_CONNECT_TIME * 10):
            if self.modem is not None: return True
            time.sleep(BLOCK_TIME)

        # timed out. we're still not connected
        # this is bad news, but not fatal, so warn
        logger.warning("Timed out while waiting for modem")
        return False

    def get_inbox_ids(self,):
        """
        For figuring out message box size
        """

        boxdata = self.modem.query('AT+CMGD=?')

        if "error" in boxdata.lower():
            print "Error - phone not supported"
            exit()

        message_ids = boxdata.split("(")[1].split(")")[0].split("-")[0].split(',')

        logger.debug('SIM Inbox size: %s message ids: %s' % (message_ids.__len__(), message_ids))

        return message_ids

    def clean_up_inbox(self,):
        """
        The Clean up / delete every message routine
        """

        message_ids = self.get_inbox_ids()

        for message_id in message_ids:
            try:
                self.modem.command('AT+CMGD=' + str(message_id))
                logger.debug('Cleaned read message %s from inbox' % message_id)
            except:
                pass

    def send(self, identity, text):

        print "My sending"
        # if this message is being sent from the start method of
        # an app (which is run in the main thread), this backend
        # may not have had time to start up yet. wait for it
        if not self._wait_for_modem():
            logger.debug('Modem was not ready when tried to send')
            return False
            
        # attempt to send the message
        # failure is bad, but not fatal
        try:
            if str(identity).startswith('+') == False:
                identity = '+' + str(identity)
            was_sent = self.modem.send_sms(str(identity), text)
            print "Was sent - a -",was_sent
            if was_sent:
                self.sent_messages += 1
            else:
                self.failed_messages += 1
        except errors.GsmError, err:
            print "some kind of error"
            print err
            return False
        print "Was sent:",was_sent
        return was_sent

    def message(self, identity, text):
        """ handle SMS from modem """
        url_args = copy.copy(self.url_args)
        url_args['identity'] = identity
        url_args['text'] = text

        # For compatibility with rapidsms-httprouter
        url_args['backend'] = 'console'
        url_args['sender'] = identity
        url_args['message'] = text

        try:
            # First we try a GET for httprouter
            logger.debug('Opening URL: %s' % self.url)
            response = urllib2.urlopen(self.url + '/?' + urllib.urlencode(url_args))  # This does a GET and likes rapidsms-httprouter
        except urllib2.HTTPError:
            # If that doesn't work we try a POST for threadless router
            try:
                response = urllib2.urlopen(self.url, urllib.urlencode(url_args))  # This does a POST and likes threadless_router
            except Exception, e:
                logger.exception(e)
                return False
        except Exception, e:
            logger.exception(e)
            return False

        logger.info('SENT')
        logger.debug('response: %s' % response.read())

    def gsm_log(self, modem, str, level):
        logger.debug("%s: %s" % (level, str))

    def status(self):

        # abort if the modem isn't connected
        # yet. there's no status to fetch
        if not self._wait_for_modem():
            return None

        csq = self.modem.signal_strength()

        # convert the "real" signal
        # strength into a 0-4 scale
        if   not csq:   level = 0
        elif csq >= 30: level = 4
        elif csq >= 20: level = 3
        elif csq >= 10: level = 2
        else:           level = 1

        vars = {
            "_signal":  level,
            "_title":   self.title,
            "Messages Sent": self.sent_messages,
            "Messages Received": self.received_messages}

        # pygsm can return the name of the network
        # operator since b19cf3. add it if we can
        if hasattr(self.modem, "network"):
            vars["Network Operator"] = self.modem.network

        return vars

    def start(self):
        self.init_modem()
        # Now that the modem has been booted, start the thread
        super(GsmPollingThread, self).start()
        logger.info("READ run loop started")

    def init_modem(self):
        try:
            self.sent_messages = 0
            self.failed_messages = 0
            self.received_messages = 0

            logger.info("Connecting and booting via pyGSM...")
            self.modem = pygsm.GsmModem(logger=self.gsm_log,
                                        **self.modem_kwargs)
            self.modem.boot()

            # Clean up (delete) all read messages from the SIM so it doesn't get filled up.
            # Don't do this unless we can't be both clever and on schedule
            # self.clean_up_inbox() # we're attempting to be clever (see above comment)

            if getattr(self, 'service_center', None) is not None:
                self.modem.service_center = self.service_center
        except:
            logger.exception('Caught exception booting modem')
            self.stop()
            raise

    def run(self):
        # lets be short lived. 
        MAX_ITER = 5
        it = 0
        try:
            self.running = True
            while self.running:
                logger.info("Polling modem for messages")
                msg = self.modem.next_message()

                if msg is not None:
                    self.received_messages += 1

                    # we got an sms! hand it off to the
                    # router to be dispatched to the apps
                    success = self.message(msg.sender, msg.text)

                    # if the message was processed successfully remove it from the sim card
                    if success != False:
                        id = self.get_inbox_ids().pop(0)
                        self.modem.command('AT+CMGD=' + str(id))
                        logger.debug("Deleted message id: %s" % id)
                
                # wait for POLL_INTERVAL seconds before continuing
                # (in a slightly bizarre way, to ensure that we abort
                # as soon as possible when the backend is asked to stop)
                for n in range(0, POLL_INTERVAL * 10):
                    if not self.running: return None
                    time.sleep(BLOCK_TIME_SHORT)
                it +=1
                print it
                if it == 5:
                    raise
        except:
            logger.exception('Caught exception in GSM polling loop')
            raise
        finally:
            self.stop()
            
        logger.info("Run loop terminated.")

    def stop(self):

        self.running = False
        # disconnect from modem
        if self.modem is not None:
            self.modem.disconnect()
