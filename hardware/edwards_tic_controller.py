# -*- coding: utf-8 -*-
"""
This module reads operational parameters from Edwards Vacuum
TIC series controllers for Edwards Vacuum turbomolecular pumps
and backing pumps.

QuDi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

QuDi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with QuDi. If not, see <http://www.gnu.org/licenses/>.

Copyright (C) 2016 Jan M. Binder jan.binder@uni-ulm.de
"""

from core.base import Base
from pyqtgraph.Qt import QtCore
from core.util.mutex import Mutex
import visa

class EdwardsPump(Base):
    """
    This module implements communication with the Edwards turbopump and 
    vacuum equipment.
    """
    _modclass = 'edwards_pump'
    _modtype = 'hardware'

    # connectors
    _out = {'pump': 'Pump'}

    # IDs for communication
    PRIORITY = {
        0: 'OK',
        1: 'Warning',
        2: 'Alarm',
        3: 'Alarm'
    }

    ALERT_ID = {
        0: 'No Alert',
        1: 'ADC Fault',
        2: 'ADC Not Ready',
        3: 'Over Range',
        4: 'Under Range',
        5: 'ADC Invalid',
        6: 'No Gauge',
        7: 'Unknown',
        8: 'Not Supported',
        9: 'New ID',
        10: 'Over Range',
        11: 'Under Range',
        12: 'Over Range',
        13: 'Ion Em Timeout',
        14: 'Not Struck',
        15: 'Filament Fail',
        16: 'Mag Fail',
        17: 'Striker Fail',
        18: 'Not Struck',
        19: 'Filament Fail',
        20: 'Cal Error',
        21: 'Initialising',
        22: 'Emission Error',
        23: 'Over Pressure',
        24: 'ASG Cant Zero',
        25: 'RampUp Timeout',
        26: 'Droop Timeout',
        27: 'Run Hours High',
        28: 'SC Interlock',
        29: 'ID Volts Error',
        30: 'Serial ID Fail',
        31: 'Upload Active',
        32: 'DX Fault',
        33: 'Temp Alert',
        34: 'SYSI Inhibit',
        35: 'Ext Inhibit',
        36: 'Temp Inhibit',
        37: 'No Reading',
        38: 'No Message',
        39: 'NOV Failure',
        40: 'Upload Timeout',
        41: 'Download Failed',
        42: 'No Tube',
        43: 'Use Gauges 4-6',
        44: 'Degas Inhibited',
        45: 'IGC Inhibited',
        46: 'Brownout/Short',
        47: 'Service due'
    }
    
    GAS_TYPE = {
        0: 'Nitrogen',
        1: 'Helium',
        2: 'Argon',
        3: 'Carbon Dioxide',
        4: 'Neon',
        5: 'Krypton',
        6: 'Voltage'
    }    
    
    GAUGE_TYPE = {
        0 : 'Unknown Device',
        1 : 'No Device',
        2 : 'EXP_CM',
        3 : 'EXP_STD',
        4 : 'CMAN_S',
        5 : 'CMAN_D',
        6 : 'TURBO',
        7 : 'APGM',
        8 : 'APGL',
        9 : 'APGXM',
        10: 'APGXH',
        11: 'APGXL',
        12: 'ATCA',
        13: 'ATCD',
        14: 'ATCM',
        15: 'WRG',
        16: 'AIMC',
        17: 'AIMN',
        18: 'AIMS',
        19: 'AIMX',
        20: 'AIGC_I2R',
        21: 'AIGC_2FIL',
        22: 'ION_EB',
        23: 'AIGXS',
        24: 'USER',
        25: 'ASG'
    }
    
    GAUGE_STATE = {
        0:  'Gauge Not connected',
        1:  'Gauge Connected',
        2:  'New Gauge Id',
        3:  'Gauge Change',
        4:  'Gauge In Alert',
        5:  'Off',
        6:  'Striking',
        7:  'Initialising',
        8:  'Calibrating',
        9:  'Zeroing',
        10: 'Degassing',
        11: 'On',
        12: 'Inhibited'
    }
    
    GAUGE_UNIT = {
        66: 'Voltage',
        59: 'Pressure',
        81: 'Percent'
    }

    PUMP_STATE = {
        0: 'Stopped',
        1: 'Starting Delay',
        2: 'Stopping Short Delay',
        3: 'Stopping Normal Delay',
        4: 'Running',
        5: 'Accelerating',
        6: 'Fault Braking',
        7: 'Braking'
    }

    def __init__(self, manager, name, config, **kwargs):
        c_dict = {'onactivate': self.activation, 'ondeactivate': self.deactivation}
        Base.__init__(self, manager, name, configuration=config, callbacks = c_dict)

    def activation(self, e):
        config = self.getConfiguration()
        self.connect(config['interface'])

    def deactivation(self, e):
        self.disconnect()

  def connect(self, interface):
        """ Connect to Instrument.
        
            @param str interface: visa interface identifier

            @return bool: connection success
        """
        try:
            # connect to instrument via VISA
            self.rm = visa.ResourceManager()
            self.inst = self.rm.open_resource(interface, baud_rate=9600, term_chars='\r', send_end=True)
        except visa.VisaIOError as e:
            self.logExc()
            return False

    def disconnect(self):
        """ 
        Close connection to instrument.
        """
        self.inst.close()
        self.rm.close()

    def _parse_gauge_answer(self, answer):
        valuess = answer.split(';')
        parsed = {
            'value': float(valuess[0]),
            'unit': self.GAUGE_UNIT[ int(valuess[1]) ],
            'state': self.GAUGE_STATE[ int(valuess[2]) ],
            'alert': self.ALERT_ID[ int(valuess[3]) ],
            'priority': self.PRIORITY[ int(valuess[4]) ]
        }
        return parsed

    def _get_pstate(self, register):
        g = self.inst.ask('?V{}'.format(register))
        param = g.split()[0]
        value = g.split()[1]
        if param == '=V{}'.format(register):
            values = value.split(';')
            parsed = {
                'state': self.PUMP_STATE[int(values[0])],
                'alert': self.ALERT_ID[int(values[1]) ],
                'priority': self.PRIORITY[int(values[2])]
            }
            return parsed
        else:
            return

    def _get_pval(self, register):
        g = self.inst.ask('?V{}'.format(register))
        param = g.split()[0]
        value = g.split()[1]
        if param == '=V{}'.format(register):
            values = value.split(';')
            parsed = {
                'state': self.PUMP_STATE[int(values[0])],
                'alert': self.ALERT_ID[int(values[1]) ],
                'priority': self.PRIORITY[int(values[2])]
            }
            return parsed
        else:
            return

    def _get_gauge(self, gauge):
         g = self.inst.ask('?V{}'.format(gauge))
         param = g.split()[0]
         values = g.split()[1]
         if param == '=V{}'.format(gauge):
             return self._parse_gauge_answer(values)
         else:
             return

    def get_pressures(self):
        p1 = self._get_gauge(913)['value']
        p2 = self._get_gauge(914)['value']
        p3 = self._get_gauge(915)['value']
        return [p1, p2, p3]
   
    def get_turbo_status(self):
        return self._get_pstate(904)

    def get_turbo_speed(self):
        return self._get_pval(905)

    def get_turbo_power(self):
        return self._get_pval(906)

    def get_backing_status(self):
        return self._get_pstate(910)
    
    def get_backing_speed(self):
        return self._get_pval(911)
 
    def get_backing_power(self):
        return self._get_pval(912)

    def get_gauge1(self):
        return self._get_gauge(913)

    def get_gauge2(self):
        return self._get_gauge(914)

    def get_gauge3(self):
        return self._get_gauge(915)
 