# -*- coding: utf-8 -*-
"""
Manager.py -  Defines main Manager class for ACQ4
Copyright 2010  Luke Campagnola
Distributed under MIT/X11 license. See license.txt for more infomation.

This class must be invoked once to initialize the ACQ4 core system.
The class is responsible for:
    - Configuring devices
    - Invoking/managing modules
    - Creating and executing acquisition tasks. 
"""
import os
import sys
import gc
import getopt
import glob
import re

import time
import atexit
import weakref
from pyqtgraph.Qt import QtCore
import pyqtgraph.reload as reload
import pyqtgraph.configfile as configfile

from .util import ptime
from .util.Mutex import Mutex   # Mutex provides access serialization between threads
from collections import OrderedDict
import pyqtgraph as pg
from .Logger import Logger, LOG, printExc
from .ThreadManager import ThreadManager
from .Base import Base

class Manager(QtCore.QObject):
    """Manager class is responsible for:
      - Loading/configuring device modules and storing their handles
      - Providing unified timestamps
      - Making sure all devices/modules are properly shut down
        at the end of the program

      @signal sigConfigChanged
      @signal sigModulesChanged
      @signal sigModuleHasQuit
      @signal sigBaseDirChanged
      @signal sigAbortAll
      """
      

    # Prepare Signal declarations for Qt: Allows Python to interface with Qt 
    # signal and slot delivery mechanisms.
    sigConfigChanged = QtCore.Signal()
    sigModulesChanged = QtCore.Signal() 
    sigModuleHasQuit = QtCore.Signal(object)    # a signal which is connected to
                                                # all objects in python. Here 
                                                # you should receive the
                                                # (module name).
    sigBaseDirChanged = QtCore.Signal()
    sigLogDirChanged = QtCore.Signal(object)    # a signal which is connected to
                                                # all objects in python. Here 
                                                # you should receive the
                                                # (directory name).
    sigAbortAll = QtCore.Signal()
    sigManagerQuit = QtCore.Signal(object)
    
    def __init__(self, configFile=None, argv=None):
        """Constructor for QuDi main management class

          @param string configFile: path to configuration file
          @param list argv: command line arguments
        """
        # used for keeping some basic methods thread-safe
        self.lock = Mutex(recursive=True)
        self.tree = OrderedDict()
        self.tree['config'] = OrderedDict()
        self.tree['start'] = OrderedDict()
        self.tree['defined'] = OrderedDict()
        self.tree['loaded'] = OrderedDict()
        
        self.tree['defined']['hardware'] = OrderedDict()
        self.tree['loaded']['hardware'] = OrderedDict()
        
        self.tree['start']['gui'] = OrderedDict()
        self.tree['defined']['gui'] = OrderedDict()
        self.tree['loaded']['gui'] = OrderedDict()
        
        self.tree['start']['logic'] = OrderedDict()
        self.tree['defined']['logic'] = OrderedDict()
        self.tree['loaded']['logic'] = OrderedDict()

        self.currentDir = None
        self.baseDir = None
        self.disableDevs = []
        self.disableAllDevs = False
        self.alreadyQuit = False

        try:
            # Logging
            global LOG
            LOG = Logger(self)
            #print(LOG)
            self.logger = LOG
            
            # Command Line parameters
            if argv is not None:
                try:
                    opts, args = getopt.getopt(argv, 'c:a:m:b:s:d:nD',
                    ['config=',
                    'config-name=',
                    'module=',
                    'base-dir=',
                    'storage-dir=',
                    'disable=',
                    'no-manager',
                    'disable-all'])
                except getopt.GetoptError as err:
                    print(str(err))
                    print("""
    Valid options are:
        -c --config=       Configuration file to load
        -a --config-name=  Named configuration to load
        -m --module=       Module name to load
        -b --base-dir=     Base directory to use
        -s --storage-dir=  Storage directory to use
        -n --no-manager    Do not load manager module
        -d --disable=      Disable the device specified
        -D --disable-all   Disable all devices
    """)
                    raise
            else:
                opts = []
            
            # Initialize parent class QObject
            QtCore.QObject.__init__(self)
            atexit.register(self.quit)

            # Thread management
            self.tm = ThreadManager()
            self.tm.sigLogMessage.connect(self.logger.queuedLogMsg)
            #mthread = self.tm.newThread('manager')
            #self.moveToThread(mthread)
            #mthread.start()
            
            # Handle command line options
            loadModules = []
            setBaseDir = None
            setStorageDir = None
            loadManager = True
            loadConfigs = []
            for o, a in opts:
                if o in ['-c', '--config']:
                    configFile = a
                elif o in ['-a', '--config-name']:
                    loadConfigs.append(a)
                elif o in ['-m', '--module']:
                    loadModules.append(a)
                elif o in ['-b', '--baseDir']:
                    setBaseDir = a
                elif o in ['-s', '--storageDir']:
                    setStorageDir = a
                elif o in ['-n', '--noManager']:
                    loadManager = False
                elif o in ['-d', '--disable']:
                    self.disableDevs.append(a)
                elif o in ['-D', '--disable-all']:
                    self.disableAllDevs = True
                else:
                    print("Unhandled option", o, a)
            
            # Read in configuration file
            if configFile is None:
                configFile = self._getConfigFile()
            
            self.configDir = os.path.dirname(configFile)
            self.readConfig(configFile)
            
            self.logger.logMsg('QuDi started.', importance=9)
            
            # Act on options if they were specified..
            try:
                for name in loadConfigs:
                    self.loadDefinedConfig(name)
                for m in loadModules:
                    try:
                        self.loadDefinedModule(m)
                    except:
                        raise
            except:
                printExc('\n: Error while acting on command line options: '
                         '(but continuing on anyway..)')
            # Load startup things from config here
            for key in self.tree['start']['gui']:
                try:
                    # self.loadModule( baseclass, module, instanceName, config=None)
                    modObj = self.loadModule('gui',
                                            self.tree['start']['gui'][key]['module'])
                    pkgName = re.escape(modObj.__package__)
                    modName = re.sub('^{0}\.'.format(pkgName), '', modObj.__name__)
                    modName = modObj.__name__.replace(modObj.__package__, '').replace('.', '')
                    
                    self.configureModule(modObj, 'gui', modName, key,
                                         self.tree['start']['gui'][key])
                    self.tree['loaded']['gui'][key].activate()
                except:
                    raise
        except:
            printExc("Error while configuring Manager:")
        finally:
            if len(self.tree['loaded']['logic']) == 0 and len(self.tree['loaded']['gui']) == 0 :
                self.logger.logMsg('No modules loaded during startup. Not '
                                   'is happening.', importance=9)
            
    def _getConfigFile(self):
        """ Search all the default locations to find a configuration file.
          
          @return sting: path to configuration file
        """
        from . import CONFIGPATH
        for path in CONFIGPATH:
            cf = os.path.join(path, 'default.cfg')
            if os.path.isfile(cf):
                return cf
        raise Exception("Could not find config file in: {0}".format(CONFIGPATH) )
    
    def _appDataDir(self):
        """Get the system specific application data directory.

          @return string: path to application directory
        """
        # return the user application data directory
        if sys.platform == 'win32':
            # resolves to "C:/Documents and Settings/User/Application Data/"
            # on XP and "C:\User\Username\AppData\Roaming" on win7
            return os.path.join(os.environ['APPDATA'], 'qudi')
        elif sys.platform == 'darwin':
            return os.path.expanduser('~/Library/Preferences/qudi')
        else:
            return os.path.expanduser('~/.local/qudi')

            
    def readConfig(self, configFile):
        """Read configuration file and sort entries into categories.

          @param string configFile: path to configuration file
        """
        print("============= Starting Manager configuration from {0} =================".format(configFile) )
        self.logger.logMsg("Starting Manager configuration from {0}".format(configFile) )
        cfg = configfile.readConfigFile(configFile)
            
        # Read modules, devices, and stylesheet out of config
        self.configure(cfg)

        self.configFile = configFile
        print("\n============= Manager configuration complete =================\n")
        self.logger.logMsg('Manager configuration complete.')
        
    def configure(self, cfg):
        """Sort modules from configuration into categories

          @param dict cfg: dictionary from configuration file

          There are the main categories hardware, logic, gui, startup
          and global.
          Startup modules can be logic or gui and are loaded
          directly on 'startup'.
          'global' contains settings for the whole application.
          hardware, logic and gui contain configuration of and 
          for loadable modules.
        """
        
        for key in cfg:
            try:
                # hardware
                if key == 'hardware':
                    for m in cfg['hardware']:
                        if self.disableAllDevs or m in self.disableDevs:
                            self.logger.print_logMsg("    --> Ignoring device {0} -- disabled by request".format(m) )
                            continue
                        if 'module' in cfg['hardware'][m]:
                            self.tree['defined']['hardware'][m] = cfg['hardware'][m]
                        else: 
                            self.logger.print_logMsg("    --> Ignoring device {0} -- no module specified".format(m))

                # logic
                elif key == 'logic':
                    for m in cfg['logic']:
                        if 'module' in cfg['logic'][m]:
                            self.tree['defined']['logic'][m] = cfg['logic'][m]
                        else:
                            self.logger.print_logMsg("    --> Ignoring logic {0} -- no module specified".format(m) )
                        
                # GUI
                elif key == 'gui':
                    for m in cfg['gui']:
                        if 'module' in cfg['gui'][m]:
                            self.tree['defined']['gui'][m] = cfg['gui'][m]
                        else:
                            self.logger.print_logMsg("    --> Ignoring GUI {0} -- no module specified".format(m) )

                # Load on startup
                elif key == 'startup':
                    for skey in cfg['startup']:
                        if skey == 'gui':
                            for m in cfg['startup']['gui']:
                                if 'module' in cfg['startup']['gui'][m]:
                                    self.tree['start']['gui'][m] = cfg['startup']['gui'][m]
                                else:
                                    self.logger.print_logMsg("    --> Ignoring startup logic {0} -- no module specified".format(m) )
                        elif skey == 'logic':
                            for m in cfg['startup']['logic']:
                                if 'module' in cfg['startup']['logic'][m]:
                                    self.tree['start']['logic'][m] = cfg['startup']['logic'][m]
                                else:
                                    self.logger.print_logMsg("    --> Ignoring startup GUI {0} -- no module specified".format(m) )

                # global config
                elif key == 'global':
                    for m in cfg['global']:
                        if m == 'storageDir':
                            self.logger.print_logMsg("=== Setting base directory: {0} ===".format(m) + cfg['global']['storageDir'])
                            self.setBaseDir(cfg['global']['storageDir'])
                
                        elif m == 'useOpenGL':
                            pg.setConfigOption('useOpenGL', cfg['global']['useOpenGl'])
                
                # Copy in any other configurations.
                # dicts are extended, all others are overwritten.
                else:
                    if isinstance(cfg[key], dict):
                        if key not in self.tree['config']:
                            self.tree['config'][key] = {}
                        for key2 in cfg[key]:
                            self.tree['config'][key][key2] = cfg[key][key2]
                    else:
                        self.tree['config'][key] = cfg[key]
            except:
                printExc("Error in configuration:")
        # print self.tree['config']
        self.sigConfigChanged.emit()

    def listConfigurations(self):
        """Return a list of the available named configurations.

          @return list: user configurations
        """
        with self.lock:
            if 'configurations' in self.tree['config']:
                return list(self.tree['config']['configurations'].keys())
            else:
                return []

    def loadDefinedConfig(self, name):
        """ Loads the specified configuration file encoded in name parameter.
        
          @param string name: Name of the loadable configuration file.
        """
        with self.lock:
            if name not in self.tree['config']['configurations']:
                raise Exception('Could not find configuration named {0}'.format(name) )
            cfg = self.tree['config']['configurations'].get(name, )
        self.configure(cfg)

    def readConfigFile(self, fileName, missingOk=True):
        """Actually check if the configuration file exists and read it

          @param string fileName: path to configuration file
          @param bool missingOk: suppress exception if file does not exist

          @return dict: configuration from file
        """
        with self.lock:
            fileName = self.configFileName(fileName)
            if os.path.isfile(fileName):
                return configfile.readConfigFile(fileName)
            else:
                if missingOk: 
                    return {}
                else:
                    raise Exception('Config file {0} not found.'.format(fileName) )
            
    def writeConfigFile(self, data, fileName):
        """Write a file into the currently used config directory.

          @param dict data: dictionary to write into file
          @param string fileName: path for filr to be written
        """
        with self.lock:
            fileName = self.configFileName(fileName)
            dirName = os.path.dirname(fileName)
            if not os.path.exists(dirName):
                os.makedirs(dirName)
            configfile.writeConfigFile(data, fileName)
    
    def appendConfigFile(self, data, fileName):
        """Append configuration to a file in the currently used config directory.

          @param dict data: dictionary to write into file
          @param string fileName: path for filr to be written
        """
        with self.lock:
            fileName = self.configFileName(fileName)
            if os.path.exists(fileName):
                configfile.appendConfigFile(data, fileName)
            else:
                raise Exception("Could not find file {0}".format(fileName) )
        
        
    def configFileName(self, name):
        """Get the full path of a configuration file from its filename.

          @param string name: filename of file in configuration directory
          
          @return string: full path to file
        """
        with self.lock:
            return os.path.join(self.configDir, name)

    def setBaseDir(self, path):
        """Set base directory for data

          @param string path: base directory path
        """
        oldBaseDir = self.baseDir
        dirName = os.path.dirName(path)
        
        if not os.path.exists(dirName):
            os.makedirs(dirName)
            
        self.baseDir = dirName
        if(oldBaseDir != dirName):
            # emit a signal to the created Qt signal slot:
            self.sigBaseDirChanged.emit()

    ##################
    # Module loading #
    ##################

    def loadModule(self, baseName, module):
        """Load a python module that is a loadable QuDi module.

          @param string baseName: the module base package (hardware, logic, or gui)
          @param string module: the python module name inside the base package

          @return object: the loaded python module
        """
        
        self.logger.print_logMsg('Loading module ".{0}.{1}"'.format(baseName, module) )
        if baseName not in ['hardware', 'logic', 'gui']:
            raise Exception('You are trying to cheat the '
                            'system with some category {0}'.format(baseName) )
        
        # load the python module
        mod = __import__('{0}.{1}'.format(baseName, module), fromlist=['*'])
        return mod

    def configureModule(self, moduleObject, baseName, className, instanceName, 
                        configuration = {} ):
        """Instantiate an object from the class that makes up a QuDi module
           from a loaded python module object.

          @param object moduleObject: loaded python module
          @param string baseName: module base package (hardware, logic or gui)
          @param string className: name of the class we want an object from 
                                 (same as module name usually)
          @param string instanceName: unique name thet the QuDi module instance
                                 was given in the configuration
          @param dict configuration: configuration options for the QuDi module

          @return object: QuDi module instance (object of the class derived
                          from Base)

          This method will add the resulting QuDi module instance to internal
          bookkeeping.
        """
        self.logger.print_logMsg('Configuring {0} as {1}'.format(className, instanceName) )
        with self.lock:
            if baseName in ['hardware', 'logic', 'gui']:
                if instanceName in self.tree['loaded'][baseName]:
                    raise Exception('{0} already exists with '
                                    'name {1}'.format(baseName, instanceName))
            else:
                raise Exception('You are trying to cheat the system with some '
                                'category {0}'.format(baseName) )
        
        if configuration is None:
            configuration = {}

        # get class from module by name
        modclass = getattr(moduleObject, className)
        
        #FIXME: Check if the class we just obtained has the right inheritance
        if not issubclass(modclass, Base):
            raise Exception('Bad inheritance, for instance %s from %s.%s.' % (instanceName, baseName, className))

        # Create object from class (Manager, Name, config)
        instance = modclass(self, instanceName, configuration)

        # Connect to log
        instance.sigLogMessage.connect(self.logger.queuedLogMsg)

        with self.lock:
            if baseName in ['hardware', 'logic', 'gui']:
                self.tree['loaded'][baseName][instanceName] = instance
            else:
                raise Exception('We checked this already, there is no way that '
                                'we should get base class {0} here'.format(baseName))
        
        self.sigModulesChanged.emit()
        return instance

    def connectModule(self, base, mkey):
        """ Connects the given module in mkey to main object with the help of base.
        
          @param string base: module base package (hardware, logic or gui)  
          @param string mkey: module which you want to connect
        
        """
        thismodule = self.tree['defined'][base][mkey]
        if mkey not in self.tree['loaded'][base]:
            self.logger.logMsg('Loading of {0} module {1} as {2} was not  '
                               'successful, not connecting it.'.format(base, thismodule['module'], mkey),
                               msgType='error')
            return
        if 'connect' not in thismodule:
            return
        if 'in' not in  self.tree['loaded'][base][mkey].connector:
            self.logger.logMsg('{0} module {1} loaded as {2} is supposed to '
                               'get connected but it does not declare any IN '
                               'connectors.'.format(base, thismodule['module'], mkey),
                               msgType='error')
            return
        if 'module' not in thismodule:
            self.logger.logMsg('{0} module {1} ({2}) connection configuration '
                               'is broken: no module defined.'.format(base, mkey, thismodule['module'] ),
                               msgType='error')
            return
        if not isinstance(thismodule['connect'], OrderedDict):
            self.logger.logMsg('{0} module {1} ({2}) connection configuration '
                               'is broken: connect is not a dict.'.format(base, mkey, thismodule['module'] ),
                               msgType='error')
            return

        connections = thismodule['connect']
        for c in connections:
            connectorIn = self.tree['loaded'][base][mkey].connector['in']
            if c not in connectorIn:
                self.logger.logMsg('IN connector {0} of {1} module {2} loaded '
                                   'as {3} is supposed to get connected but '
                                   'is not declared in the module.'.format(c, base, thismodule['module'], mkey),
                                   msgType='error')
                return
            if not isinstance(connectorIn[c], OrderedDict):
                self.logger.logMsg('No dict.', msgType='error')
                return
            if 'class' not in connectorIn[c]:
                self.logger.logMsg('no class key in connection declaration',
                                   msgType='error')
                return
            if not isinstance(connectorIn[c]['class'], str):
                self.logger.logMsg('value for class key is not a string',
                                   msgType='error')
                return
            if 'object' not in connectorIn[c]:
                self.logger.logMsg('no object key in connection declaration',
                                   msgType='error')
                return
            if connectorIn[c]['object'] is not None:
                self.logger.logMsg('object is not None, i.e. is already '
                                   'connected', msgType='error')
                return
            if not isinstance(connections[c], str):
                self.logger.logMsg('{0} module {1} ({2}) connection '
                                   'configuration is broken, value for key '
                                   '{3 }is not a string.'.format(base, mkey, thismodule['module'], c ),
                                   msgType='error')
                return
            if '.' not in connections[c]:
                self.logger.logMsg('{0} module {1} ({2}) connection '
                                   'configuration is broken, value {3} for '
                                   'key {4} does not contain a dot.'.format(base, mkey, thismodule['module'], connections[c], c ),
                                   msgType='error')
                return
            destmod = connections[c].split('.')[0]
            destcon = connections[c].split('.')[1]
            destbase = ''
            if destmod in self.tree['loaded']['hardware'] and destmod in self.tree['loaded']['logic']:
                self.logger.logMsg('Unique name {0} is in both hardware and '
                                   'logic module list. Connection is not well '
                                   'defined, cannot connect {1} ({2}) to  it.'.format(destmod, mkey, thismodule['module']),
                                   msgType='error')
                return
                
            # Connect to hardware module
            elif destmod in self.tree['loaded']['hardware']:
                destbase = 'hardware'
            elif destmod in self.tree['loaded']['logic']:
                destbase = 'logic'
            else:
                self.logger.logMsg('Unique name {0} is neither in hardware or '
                                   'logic module list. Cannot connect {1} ({2}) '
                                   'to it.'.format(connections[c], mkey, thismodule['module']),
                                   msgType='error')
                return

            if 'out' not in self.tree['loaded'][destbase][destmod].connector:
                self.logger.logMsg('Module {0} loaded as {1} is supposed to '
                                   'get connected to module loaded as {2} but '
                                   'that does not declare any OUT '
                                   'connectors.'.format(thismodule['module'], mkey, destmod),
                                   msgType='error')
                return
            outputs = self.tree['loaded'][destbase][destmod].connector['out']
            if destcon not in outputs:
                self.logger.logMsg('OUT connector not declared', 
                                   msgType='error')
                return
            if not isinstance(outputs[destcon], OrderedDict):
                self.logger.logMsg('not a dict', msgType='error')
                return
            if 'class' not in outputs[destcon]:
                self.logger.logMsg(
                    'no class key in dict',
                    msgType='error')
                return
            if not isinstance(outputs[destcon]['class'], str):
                self.logger.logMsg('class value no string', msgType='error')
                return
#            if not issubclass(self.tree['loaded'][destbase][destmod].__class__, outputs[destcon]['class']):
#                self.logger.logMsg('not the correct class for declared '
#                                   'interface', msgType='error')
#                return

            # Finally set the connection object
            self.logger.logMsg('Connecting {0} module {1}.IN.{2} to {3} '
                               '{4}.{5}'.format(base, mkey, c, destbase, destmod, destcon),
                               msgType='status')
            connectorIn[c]['object'] = self.tree['loaded'][destbase][destmod]

    def loadConfigureModule(self, base, key):
        """Loads the configuration Module in key with the help of base class.
          
          @param string base: module base package (hardware, logic or gui)  
          @param string key: module which is going to be loaded
          
        """
        if 'module' in self.tree['defined'][base][key]:
            try:
                modObj = self.loadModule(base,
                                         self.tree['defined'][base][key]['module'])
                pkgName = re.escape(modObj.__package__)
                modName = re.sub('^{0}\.'.format(pkgName), '', modObj.__name__)
                self.configureModule(modObj, base, modName, key,
                                     self.tree['defined'][base][key])
                ## start main loop for qt objects
                if base == 'logic':
                    modthread = self.tm.newThread('mod-' + base + '-' + key)
                    self.tree['loaded'][base][key].moveToThread(modthread)
                    modthread.start()
            except:
                self.logger.logExc('Error while loading {0} module: {1}'.format(base, key),
                                   msgType='error')
                return
        else:
            self.logger.logMsg('Not a loadable {0} module: {1}'.format(base, key),
                               msgType='error')

    def activateModule(self, base, key):
        """Activated the module given in key with the help of base class.
          
          @param string base: module base package (hardware, logic or gui)  
          @param string key: module which is going to be activated.
            
        """
        if self.tree['loaded'][base][key].getState() != 'deactivated' and key in self.tree['start'][base]:
            return
        if self.tree['loaded'][base][key].getState() != 'deactivated':
            self.logger.logMsg('{0} module {1} not deactivated anymore'.format(base, key),
                               msgType='error')
            return
        try:
            self.tree['loaded'][base][key].activate()
        except:
            self.logger.logExc('{0} module {1}: error during activation:'.format(base, key),
                               msgType='error')

    def startAllConfiguredModules(self):
        """Connect all QuDi modules from the currently laoded configuration and
            activate them.
        """
        #FIXME: actually load all the modules in the correct order and connect
        # the interfaces
        for thing in ['hardware', 'logic', 'gui']:
            for key in self.tree['defined'][thing]:
                self.loadConfigureModule(thing, key)

        # Connect ALL the things!
        self.logger.print_logMsg('Connecting ALL the things!!')
        for mkey in self.tree['defined']['logic']:
            self.connectModule('logic', mkey)
        for mkey in self.tree['defined']['gui']:
            self.connectModule('gui', mkey)

        # FIXME Check for any disconnected modules and add their dummies
        # FIXME Call Activate on all deactivated modules
        self.logger.print_logMsg('Activation starting!')
        for thing in ['hardware', 'logic', 'gui']:
            for key in self.tree['loaded'][thing]:
                self.activateModule(thing, key)
        self.logger.print_logMsg('Activation finished.')

    def reloadAll(self):
        """Reload all python code."""
        #path = os.path.split(os.path.abspath(__file__))[0]
        #path = os.path.abspath(os.path.join(path, '..'))
        path = '.'
        self.logger.print_logMsg("\n---- Reloading all libraries under {0} ----".format(path),
                                 msgType='status')
        reload.reloadAll(prefix=path, debug=True)
        self.logger.print_logMsg("Reloaded all libraries under {0}.".format(path),
                                 msgType='status')
        
    def quit(self):
        """Nicely request that all modules shut down."""
        self.sigManagerQuit.emit(self)

    # Staticmethods are used to group functions which have some logical 
    # connection with a class but they They behave like plain functions except 
    # that you can call them from an instance or the class. Methods covered 
    # with static decorators are an organization/stylistic feature in python.
    @staticmethod
    def toposort(deps, cost=None):
        """Topological sort. Arguments are:
        
          @param dict deps: Dictionary describing dependencies where a:[b,c]
                            means "a depends on b and c"
          @param dict cost: Optional dictionary of per-node cost values. This
                            will be used to sort independent graph branches by 
                            total cost. 
                
        Examples::

            # Sort the following graph:
            # 
            #   B ──┬─────> C <── D
            #       │       │       
            #   E <─┴─> A <─┘
            #     
            deps = {'a': ['b', 'c'], 'c': ['b', 'd'], 'e': ['b']}
            toposort(deps)
            => ['b', 'e', 'd', 'c', 'a']
            
            # This example is underspecified; there are several orders that 
            # correctly satisfy the graph. However, we may use the 'cost' 
            # argument to impose more constraints on the sort order.
            
            # Let each node have the following cost:
            cost = {'a': 0, 'b': 0, 'c': 1, 'e': 1, 'd': 3}
            
            # Then the total cost of following any node is its own cost plus
            # the cost of all nodes that follow it:
            #   A = cost[a]
            #   B = cost[b] + cost[c] + cost[e] + cost[a]
            #   C = cost[c] + cost[a]
            #   D = cost[d] + cost[c] + cost[a]
            #   E = cost[e]
            # If we sort independent branches such that the highest cost comes 
            # first, the output is:
            toposort(deps, cost=cost)
            => ['d', 'b', 'c', 'e', 'a']
        """
        # copy deps and make sure all nodes have a key in deps
        deps0 = deps
        deps = {}
        for k,v in list(deps0.items()):
            deps[k] = v[:]
            for k2 in v:
                if k2 not in deps:
                    deps[k2] = []

        # Compute total branch cost for each node
        key = None
        if cost is not None:
            order = Manager.toposort(deps)
            allDeps = {n: set(n) for n in order}
            for n in order[::-1]:
                for n2 in deps.get(n, []):
                    allDeps[n2] |= allDeps.get(n, set())
                    
            totalCost = {n: sum([cost.get(x, 0) for x in allDeps[n]]) for n in allDeps}
            key = lambda x: totalCost.get(x, 0)

        # compute weighted order
        order = []
        while len(deps) > 0:
            # find all nodes with no remaining dependencies
            ready = [k for k in deps if len(deps[k]) == 0]
            
            # If no nodes are ready, then there must be a cycle in the graph
            if len(ready) == 0:
                print(deps)
                raise Exception('Cannot resolve requested device '
                                'configure/start order.')
            
            # sort by branch cost
            if key is not None:
                ready.sort(key=key, reverse=True)
            
            # add the highest-cost node to the order, then remove it from the
            # entire set of dependencies
            order.append(ready[0])
            del deps[ready[0]]
            for v in list(deps.values()):
                try:
                    v.remove(ready[0])
                except ValueError:
                    pass
        
        return order
        
