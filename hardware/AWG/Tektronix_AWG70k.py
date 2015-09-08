# -*- coding: utf-8 -*-
"""
Created on Fri Aug 21 12:31:16 2015

@author: s_ntomek
"""

from socket import socket, AF_INET, SOCK_STREAM
from ftplib import FTP
from StringIO import StringIO
import time
from collections import OrderedDict
from core.base import Base
from core.util.mutex import Mutex

#the next import is only needed for the FastWrite method
#import DTG_IO 


class AWG(Base):
    """ UNSTABLE: Nikolas
    """
    _modclass = 'AWG'
    _modtype = 'hardware'
    
    # declare connectors
    _out = {'AWG': 'AWG'}

    def __init__(self,manager, name, config = {}, **kwargs):

        state_actions = {'onactivate'   : self.activation,
                         'ondeactivate' : self.deactivation}

        Base.__init__(self, manager, name, config, state_actions, **kwargs)
        
        if 'awg_IP_address' in config.keys():
            self.ip_address = config['awg_IP_address']
        else:
            self.logMsg("This is AWG: Did not find >>awg_IP_address<< in configuration.", msgType='error')
            
        if 'awg_port' in config.keys():
            self.port = config['awg_port']
        else:
            self.logMsg("This is AWG: Did not find >>awg_port<< in configuration.", msgType='error')
        
    
    def activation(self, e):
        """ Initialisation performed during activation of the module.
        """
        # connect ethernet socket and FTP        
        self.soc = socket(AF_INET, SOCK_STREAM)
        self.soc.connect(self.ip_address, self.port)
        self.ftp = FTP(self.ip_address)
        self.ftp.login()
        self.ftp.cwd('/waves') # hardcoded default folder
        
        self.input_buffer = int(2 ** 11)
        
        self.connected = True
        
    
    def deactivation(self, e):
        '''Tasks that are required to be performed during deactivation of the module.
        '''        
        # Closes the connection to the AWG via ftp and the socket
        self.soc.send('\n')
        self.soc.close()
        self.ftp.close()

        self.connected = False
        pass
    
    def delete(self, filelist):
        
        for filename in filelist:
            self.ftp.delete(filename)
        return
    
    def delete_all(self):
        
        filelist = self.ftp.mlsd()
        for filename in filelist:
            self.ftp.delete(filename)
        return
        
    def tell(self, command):
        """Send a command string to the AWG."""
        if not command.endswith('\n'): # I always forget the line feed.
            command += '\n'
        self.soc.send(command)
        return
        
    def ask(self, question):
        """Asks the AWG a 'question' and receive and return an answer from AWG.
        @param: question: string which has to have a proper format to be able
                            to receive an answer.
        @return: the answer of the AWG to the 'question' in a string
        """
        if not question.endswith('\n'): # I always forget the line feed.
            question += '\n'
        self.soc.send(question)    
        time.sleep(1)                   # you need to wait until AWG generating
                                        # an answer.
        message = self.soc.recv(self.input_buffer)  # receive an answer
        message = message.replace('\r\n','')      # cut away the characters\r and \n.
        return message
    
    def run(self):
        self.soc.send('AWGC:RUN\n')
        
    def stop(self):
        self.soc.send('AWGC:STOP\n')
        
    def get_status(self):
        """ Asks the current state of the AWG.
        @return: an integer with the following meaning: 
                0 indicates that the instrument has stopped.
                1 indicates that the instrument is waiting for trigger.
                2 indicates that the instrument is running.
               -1 indicates that the request of the status for AWG has failed.
                """
        self.soc.send('AWGC:RSTate?\n') # send at first a command to request.
        time.sleep(1)                   # you need to wait until AWG generating
                                        # an answer.
        message = self.soc.recv(self.input_buffer)  # receive an answer
        
        # the output message contains always the string '\r\n' at the end. Use
        # the split command to get rid of this
        try:
            return int(message.split('\r\n',1)[0])
        except:
            # if nothing comes back than the output should be marked as error
            return -1
            
    def get_sequencer_mode(self, output_as_int=False):
        """ Asks the AWG which sequencer mode it is using. It can be either in 
        Hardware Mode or in Software Mode. The optional variable output_as_int
        sets if the returned value should be either an integer number or string.
        
        @param: output_as_int: optional boolean variable to set the output
        @return: an string or integer with the following meaning:
                'HARD' or 0 indicates Hardware Mode
                'SOFT' or 1 indicates Software Mode
                'Error' or -1 indicates a failure of request
        """
        self.soc.send('AWGControl:SEQuencer:TYPE?\n')
        time.sleep(1)
        message = self.soc.recv(self.input_buffer)
        if output_as_int == True:
            if 'HARD' in message:
                return 0
            elif 'SOFT' in message:
                return 1
            else:
                return -1
        else:
            if 'HARD' in message:
                return 'Hardware-Sequencer'
            elif 'SOFT' in message:
                return 'Software-Sequencer'
            else:
                return 'Request-Error'
                
    def set_Interleave(self, state=False):
        """Turns Interleave of the AWG on or off.
            @param state: A Boolean, defines if Interleave is turned on or off, Default=False
        """
        if(state):
            print('interleave is on')
            self.soc.send('AWGC:INT:STAT 1\n')
        else:
            print('interleave is off')
            self.soc.send('AWGC:INT:STAT 0\n')
        return    
    
    def set_output(self, state, channel=3):
        """Set the output state of specified channels.
        
        @param state:  on : 'on', 1 or True; off : 'off', 0 or False
        @param channel: integer,   1 : channel 1; 2 : channel 2; 3 : both (default)
        
        """
        #TODO: AWG.set_output: implement swap
        look_up = {'on' : 1, 1 : 1, True : 1,
                   'off' : 0, 0 : 0, False : 0
                  }
        if channel & 1 == 1:
            self.soc.send('OUTP1 %i\n' % look_up[state])
        if channel & 2 == 2:
            self.soc.send('OUTP2 %i\n' % look_up[state])
        return
        
    def set_mode(self, mode):
        """Change the output mode.

        @param  mode: Options for mode (case-insensitive):
        continuous - 'C'
        triggered  - 'T'
        gated      - 'G'
        sequence   - 'S'
        
        """
        look_up = {'C' : 'CONT',
                   'T' : 'TRIG',
                   'G' : 'GAT' ,
                   'E' : 'ENH' , 
                   'S' : 'SEQ'
                  }
        self.soc.send('AWGC:RMOD %s\n' % look_up[mode.upper()])
        return
        
    def set_sample(self, frequency):
        """Set the output sampling rate.
        
        @param frequency: sampling rate [GHz] - min 5.0E-05 GHz, max 24.0 GHz 
        """
        self.soc.send('SOUR:FREQ %.4GGHz\n' % frequency)
        return
        
    def set_amp(self, voltage, channel=3):
        """Set output peak-to-peak voltage of specified channel.
        
        @param voltage: output Vpp [V] - min 0.05 V, max 2.0 V, step 0.001 V
        @param channel:  1 : channel 1; 2 : channel 2; 3 : both (default)
        
        """
        if channel & 1 == 1:
            self.soc.send('SOUR1:VOLT %.4GV\n' % voltage)
        if channel & 2 == 2:
            self.soc.send('SOUR2:VOLT %.4GV\n' % voltage)
        return
    
    def set_jump_timing(self, synchronous = False):
        """Sets control of the jump timing in the AWG to synchoronous or asynchronous.
        If the Jump timing is set to asynchornous the jump occurs as quickly as possible 
        after an event occurs (e.g. event jump tigger), if set to synchornous 
        the jump is made after the current waveform is output. The default value is asynchornous
        
        @param synchronous: Bool, if True the jump timing will be set to synchornous, 
        if False the jump timing will be set to asynchronous
        """
        if(synchronous):
            self.soc.send('EVEN:JTIM SYNC\n')
        else:
            self.soc.send('EVEN:JTIM ASYNC\n')
        return
            
    def load(self, filename, channel=1, cwd=None):
        """Load sequence or waveform file into RAM, preparing it for output.
        
        Waveforms and single channel sequences can be assigned to each or both
        channels. Double channel sequences must be assigned to channel 1.
        The AWG's file system is case-sensitive.
        
        @param filename:  *.SEQ or *.WFM file name in AWG's CWD
        @param channel: 1 : channel 1 (default); 2 : channel 2; 3 : both
        @param cwd: filepath where the waveform to be loaded is stored. Default: 'C:\InetPub\ftproot\waves'
        """
        if cwd is None:
            cwd = 'C:\\InetPub\\ftproot\\waves' # default
        if channel & 1 == 1:
            self.soc.send('SOUR1:FUNC:USER "%s/%s"\n' % (cwd, filename))
        if channel & 2 == 2:
            self.soc.send('SOUR2:FUNC:USER "%s/%s"\n' % (cwd, filename))
        return
    
    def clear_AWG(self):
        """ Delete all waveforms and sequences from Hardware memory and clear the visual display """
        self.soc.send('WLIS:WAV:DEL ALL\n')
        return
    
    def reset(self):
        """Reset the AWG."""
        self.soc.send('*RST\n')
        return
