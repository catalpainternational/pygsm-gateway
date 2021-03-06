import time
import copy
import urllib
import urllib2
import logging
import threading
from pygsm import errors
import serial

import pygsm

logger = logging.getLogger('pygsm_gateway.gsm')

# Time to wait on the modem when polling it
# default is 0.1
BLOCK_TIME = 1
BLOCK_TIME_SHORT = 0.5
BLOCK_TIME_LONG = 2
BLOCK_TIME_VERY_LONG = 10

# number of seconds to wait between
# polling the modem for incoming SMS
POLL_INTERVAL = 5

# time to wait for the start method to
# complete before assuming that it failed
MAX_CONNECT_TIME = 10

STATUS_NOK ="NOK"

class MetaGsmPollingThread(threading.Thread):
    _title="metaPyGSM"

    def __init__(self,args):
        self.passthrough_args = args
        self.running=True
        self.gsmThread = None
        super(MetaGsmPollingThread, self).__init__()

    def run(self):
        while self.running is True:
            logger.info("Starting a Polling Thread creation")
            try:
                self.gsmThread = GsmPollingThread(**self.passthrough_args)
                self.gsmThread.start()
                logger.info("########## Started the children thread -- GsmPollingThread")
                while self.running is True and self.gsmThread is not None and self.gsmThread.running is True:
                    time.sleep(BLOCK_TIME_LONG)

                logger.info("## outside the Meta loop. self.running:"+str(self.running)+ " self.gsmThread:"+str(self.gsmThread)+" self.gsmThread.running"+ str(self.gsmThread.running))  
                if self.running is False:
                    self.stop()
            except (errors.GsmModemError, errors.GsmReadTimeoutError, serial.SerialException):
                logger.exception("########## GSM ERROR - cleaning up and starting over")
                try:
                    if self.gsmThread is not None:
                        self.gsmThread.stop()
                    self.gsmThread = None
                    time.sleep(BLOCK_TIME_VERY_LONG)
                    continue
                except errors.GsmModemError, errors.GsmReadTimeoutError:
                    logger.exception("########## GSM ERROR while cleaning up. Sleeping it off")
                    time.sleep(BLOCK_TIME_VERY_LONG)
                    continue
                except KeyboardInterrupt as er:
                    logger.exception("Keyboard interrupt while sleeping after failing to boot the modem")
                    self.stop()
                    raise(er)                    
            except KeyboardInterrupt as er:
                logger.exception("Keyboard interrupt while running normally")
                self.stop()
                raise(er)

    def status(self):
        """
        What is the status?
        """
        
        if self.gsmThread is None:
            return STATUS_NOK
        else:
            status = self.gsmThread.status()
            if status is None:
                return STATUS_NOK
            else:
                return status
        
    def send(self, identity, text):
        logger.info("Got some send:"+ identity + text)
        # Wait until we have a thread to talk to or MAX_CONNECT_TIME * BLOCK_TIME_SHORT
        n = 0
        while self.gsmThread is None and n < MAX_CONNECT_TIME:
            time.sleep(BLOCK_TIME_SHORT)
            n+=1
            logger.warn("The thread is not ready to send yet. ("+str(n)+")")
        # We didn't wait long enough
        if self.gsmThread is None:
            logger.error("The GsmPollingThread is None")
            #was not set / ready in time")
            return False
        if not hasattr(self.gsmThread,"running"):
            logger.error("The GsmPollingThread does not have its running attribute")
            return False
        if  self.gsmThread.running is False:
            logger.error("The GsmPollingThread is not running")
            return False
        return self.gsmThread.send(identity, text)


    def stop(self):
        self.running = False
        logger.debug("Trying to stop the meta thread")
        if self.gsmThread is not None:
            self.gsmThread.stop()
        
class GsmPollingThread(threading.Thread):
    _title = "pyGSM"

    # number of seconds to wait between
    # polling the modem for incoming SMS
    POLL_INTERVAL = 5
    running =False
    

    def __init__(self, url, url_args, modem_args):
        self.url = url
        self.url_args = url_args
        self.modem_kwargs = modem_args
        self.modem = None

        # set a default timeout if it wasn't specified in localsettings.py;
        # otherwise read() will hang forever if the modem is powered off
        if "timeout" not in self.modem_kwargs:
            self.modem_kwargs["timeout"] = '10'
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
        for n in range(0, int(MAX_CONNECT_TIME / BLOCK_TIME)):
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
        try:
            if "error" in boxdata.lower():
                print "Error - phone not responding as expected"
                return []

            message_ids = boxdata.split("(")[1].split(")")[0].split("-")[0].split(',')
            logger.debug('SIM Inbox size: %s message ids: %s' % (message_ids.__len__(), message_ids))
        except:
            logger.exception('Modem not responding as expected to inbox query')
            message_ids = []

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
                logger.exception('During inbox cleaning')
                pass

    def send(self, identity, text):

        logger.info(self._title+" sending a text")
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

            if was_sent:
                self.sent_messages += 1
            else:
                self.failed_messages += 1
        except errors.GsmError, err:
            logger.exception("trying to send a SMS")
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
            except Exception:
                logger.exception("Trying to report the message to an external process")
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
            "_title":   self._title,
            "_sent": self.sent_messages,
            "_failed": self.failed_messages,
            "_received": self.received_messages}

        # pygsm can return the name of the network
        # operator since b19cf3. add it if we can
        if hasattr(self.modem, "network"):
            vars["_network"] = self.modem.network

        return vars

    def start(self):
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
        except :
            logger.exception('Caught exception while booting modem')
            self.stop()
            raise

        # Now that the modem has been booted, start the thread
        super(GsmPollingThread, self).start()
        logger.info("########## GsmPollingThread run loop started")


    def run(self):
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
                        if self.get_inbox_ids():
                            id = self.get_inbox_ids().pop(0)
                            self.modem.command('AT+CMGD=' + str(id))
                            logger.debug("Deleted message id: %s" % id)

                # wait for POLL_INTERVAL seconds before continuing
                # (in a slightly bizarre way, to ensure that we abort
                # as soon as possible when the backend is asked to stop)
                for n in range(0, int(POLL_INTERVAL / BLOCK_TIME_SHORT)):
                    if not self.running: return None
                    time.sleep(BLOCK_TIME_SHORT)
        except (errors.GsmModemError, errors.GsmReadTimeoutError, serial.SerialException):
            logger.exception('## Caught exception in GSM polling loop')
        finally:
            self.stop()
            
        logger.info("########## Read loop terminated.")

    def stop(self):
        logger.info("## Stopping - After "+str(self.sent_messages) +" sent & "+str(self.failed_messages)+" failed message.")
        self.running = False
        # disconnect from modem
        if self.modem is not None:
            self.modem.disconnect()
