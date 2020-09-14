from typing import NamedTuple, Union
from enum import Enum
from copy import deepcopy
import numpy as np
from random import (
    random as r_random,
    shuffle as r_shuffle,
    randint as r_randint,
    choices as r_choices,
)

def convert_power_units(str_val,in_unit,out_unit):
	'''
	convert_power_units() takes in args:
		str_val: string value from GLD
		in_unit: string of input value units (kW | W | MW)
		out_unit: string of desired output value units (kW | W | MW)
	and returns:
		the float of the converted power value (in out_unit)
	'''
	cnvrt = {'kW':1000,'W':1000000,'VA':1000000, 'MW':1,'Wh':1000000,'MWh':1,}
	if (('j' in str_val) or ('i' in str_val)):
		str_val = str_val.split('+')[1]
		val = float(str_val.strip(' '+in_unit))
	else:
		val = float(str_val.strip(' '+in_unit))
	return val * cnvrt[out_unit]/cnvrt[in_unit]

COMM_EPOCH_SEC = 30 # time step for frequency of device updates and checking current state (sending new requests)
CONTROL_EPOCH_SEC = 180 # time duration device is on for if power request is accepted

class PEM_STATE(Enum):
    PEM_OFF = 'PEM_OFF'
    PEM_ON = 'PEM_ON'
    EXIT_OFF = 'EXIT_OFF'
    EXIT_ON = 'EXIT_ON'

def REQ_die_roll(device):
    # John's original equation:
    #T = device.temperature
    #lT = setpoint - device.pem_range
    #uT = setpoint + device.pem_range
    #return r_random() < (T - lT) / (uT - lT)
    soc = device.soc
    if soc <= 0.0:
        return True
    elif soc>=1.0:
        return False
    # standard calculation
    u = ((1 - soc) / (soc - 0)) * (COMM_EPOCH_SEC / CONTROL_EPOCH_SEC)
    #print('soc:{:.02f}, u={:.02f}, p={:.03f}'.format(soc,u,1-np.exp(-u*COMM_EPOCH_SEC)))
    return r_random() < ( 1.0 - np.exp( -u ) )



# Effects
class PowerRequest():
	'''PEM power request'''
	def __init__(self,device_id,kw,sec=CONTROL_EPOCH_SEC):
		self.device_id = device_id
		self.on = False
		self.kw = kw
		self.sec = sec

class PowerResponse():
	'''PEM power response'''
	def __init__(self,device_id,kw,sec):
		self.device_id = device_id
		self.kw = kw
		self.sec = sec
		self.on = False

class TurnOn():
	'''Request to turn a Gridlabd water heater on'''
	def __init__(self,dev):
		self.gld = dev.gld_dev
		self.kw = dev.last_power_draw_kw
		self.on = True
	def send(self):
		self.gld.turn_on()

class TurnOff():
	'''Request to turn a Gridlabd water heater off'''
	def __init__(self,dev):
		self.gld = dev.gld_dev
		self.kw = 0
		self.on = False
	def send(self):
		self.gld.turn_off()


class Effects():
    '''Container for PEM and gridlabd effects'''
    def __init__(self):
        self.power_requests = []
        self.turn_on = []
        self.turn_off = []

    def append(self, *effects):
        for effect in effects:
            self._append(effect)

    def _append(self, effect):
        if isinstance(effect, PowerRequest):
            self.power_requests.append(effect)
        elif isinstance(effect, TurnOn):
            self.turn_on.append(effect)
        elif isinstance(effect, TurnOff):
            self.turn_off.append(effect)


class gldWaterHeater:
    '''
    This is the python object version of the gridlab-d water heater objects.
        vars: id, lower_temp, upper_temp, temperature, kw (retrieved from gld)
        functions:  update_from_gld : updates current temperature and kw from gridlab simulation
                    check_stat : takes in a status to check (REQUEST | EXIT_ON | EXIT_OFF) and checks if temp is in range for that status; for REQUEST it checks if in PEM range and does the REQ_die_roll to see if it should send a power request : returns bool
                    turn_on : turns on waterheater in gld with re_override
                    turn_off : turns off waterheater in gld with re_override
    '''
    def __init__(self,wh_id,gridlabd):
        # static vars
        self.id = wh_id
        self.gld = gridlabd
        self.setpoint = float(self.gld.get_value(wh_id,'tank_setpoint').split(' ')[0]) #degF
        self.pem_range = 10
        # pem_range = float(self.gld.get_value(wh_id,'thermostat_deadband').split(' ')[0]) # uncomment if we want to use deadband from gld
        self.upper_temp = self.setpoint + self.pem_range
        self.lower_temp = self.setpoint - self.pem_range

        # not static
        self.temperature = float(self.gld.get_value(wh_id,'temperature').split(' ')[0]) #degF
        self.kw = convert_power_units(self.gld.get_value(self.id,'actual_load'),'kW','kW') # actual load in kW in gld
        self.soc = (self.temperature - self.lower_temp) / (self.upper_temp - self.lower_temp)

    def update_from_gld(self):
        self.temperature = float(self.gld.get_value(self.id,'temperature').split(' ')[0]) #degF
        self.kw = convert_power_units(self.gld.get_value(self.id,'actual_load'),'kW','kW') # actual load in kW in gld
        self.soc = (self.temperature - self.lower_temp) / (self.upper_temp - self.lower_temp)
        return self

    def soc_kWh(self,kWh=2,deltaT=20):#degreesF
        self = self.update_from_gld()
        return kWh/deltaT * self.soc * (self.upper_temp - self.lower_temp)

    def check_stat(self,stat,hysteresis=0):
        '''
        enter status you'd like to check device for:
            REQUEST | EXIT_ON | EXIT_OFF
        '''
        setpoint = self.setpoint
        pem_range = self.pem_range
        T = self.temperature
        # checking temp if in PEM REQUEST range
        if ((setpoint - (pem_range + hysteresis) < T < setpoint + (pem_range + hysteresis)) and (stat == "REQUEST")):
            if REQ_die_roll(self):
                return True
        # checking temp if in EXIT_ON range
        elif ((T < setpoint - (pem_range + hysteresis)) and (stat == "EXIT_ON")):
            return True
        # checking temp if in EXIT_OFF range
        elif ((T > setpoint + (pem_range + hysteresis)) and (stat == "EXIT_OFF")):
            return True
        else: # temp not in stat range or request denied
            return False

    def turn_on(self):
        self.gld.set_value(self.id, "tank_setpoint", f'{self.upper_temp+1} degF')
        #print("GLD setpoint =",self.gld.get_value(self.id, "tank_setpoint"))
        #print("VB_dev setpoint =",self.setpoint)
        #self.gld.set_value(self.id, "re_override", "OV_ON")

    def turn_off(self):
        self.gld.set_value(self.id, "tank_setpoint", f'{self.lower_temp-1} degF')
        #self.gld.set_value(self.id, "re_override", "OV_OFF")

class gldHVAC:
	'''
    This is the python object version of the gridlab-d house objects (for manipulating the hvac system).
        vars: id, setpoint_cool, setpoint_heat, temperature, kw (retrieved from gld)
        functions:  update_from_gld : updates current temperature and kw from gridlab simulation
                    check_stat : takes in a status to check (REQUEST | EXIT_ON | EXIT_OFF) and checks if temp is in range for that status; for REQUEST it checks if in PEM range and does the die_roll to see if it should send a power request : returns bool
                    turn_on : turns on hvac in gld with system_mode
                    turn_off : turns off hvac in gld with system_mode
    '''
	def __init__(self,house_id,gridlabd):
		# static vars
		self.id = house_id
		self.gld = gridlabd
		# disables internal controls
		self.setpoint_upp = float(self.gld.get_value(house_id,"cooling_setpoint").split(' ')[0])
		self.setpoint_low = float(self.gld.get_value(house_id,"heating_setpoint").split(' ')[0])
		#pem_range = 10
		self.pem_range =  float(self.gld.get_value(house_id,'thermostat_deadband').split(' ')[0])

		# not static
		self.temperature = T =  float(self.gld.get_value(house_id,'air_temperature').split(' ')[0]) #degF
		self.kw = convert_power_units(self.gld.get_value(self.id,'hvac_load'),'kW','kW') # actual load in kW in gld
		self.outsideT = float(self.gld.get_value(house_id,'outdoor_temperature').split(' ')[0])
		middleT = self.setpoint_low + (self.setpoint_upp - self.setpoint_low)/2
		if (self.outsideT <= middleT): # heating mode
			self.soc = (self.temperature - (self.setpoint_low - self.pem_range)) / (self.pem_range * 2)
		else: # cooling mode
			self.soc = ((self.setpoint_upp + self.pem_range) - self.temperature) / (self.pem_range * 2)
			pass

	def update_from_gld(self):
		self.temperature = T = float(self.gld.get_value(self.id,'air_temperature').split(' ')[0]) #degF
		self.kw = convert_power_units(self.gld.get_value(self.id,'hvac_load'),'kW','kW') # actual load in kW in gld
		self.outsideT = float(self.gld.get_value(self.id,'outdoor_temperature').split(' ')[0])
		middleT = self.setpoint_low + (self.setpoint_upp - self.setpoint_low)/2
		if (self.outsideT <= middleT): # heating mode
			self.soc = (self.temperature - (self.setpoint_low - self.pem_range)) / (self.pem_range * 2)
		else: # cooling mode
			self.soc = ((self.setpoint_upp + self.pem_range) - self.temperature) / (self.pem_range * 2)
		return self

	def soc_kWh(self,kWh=2,deltaT=4):#degreesF
		self = self.update_from_gld()
		return kWh/deltaT * self.soc * (self.pem_range*2)

	def check_stat(self,stat,hysteresis=0):
		'''
        	enter status you'd like to check device for:
            	REQUEST | EXIT_ON | EXIT_OFF
		'''
		pem_range = self.pem_range
		T = self.temperature
		exitoff = True
		# checking temp if in PEM REQUEST range
		for setpoint in [self.setpoint_upp, self.setpoint_low]:
			if (setpoint - (pem_range + hysteresis) < T < setpoint + (pem_range + hysteresis)):
				exitoff = False
				if ((stat == "REQUEST") and (REQ_die_roll(self))):
					return True
		# checking temp if in EXIT_ON range
		for setpoint,dir in [(self.setpoint_upp,+1), (self.setpoint_low,-1)]:
			if (0 > -T*dir + (setpoint + (pem_range + hysteresis)*dir)*dir):
				exitoff = False
				if (stat == "EXIT_ON"):
					return True
		# else:
		if ((exitoff) and (stat == "EXIT_OFF")):
			return True
		return False

	def turn_on(self):
		self.gld.set_value(self.id,"thermostat_control","NONE")
		if (self.temperature > self.setpoint_upp-2):
			self.gld.set_value(self.id, "system_mode", "COOL")
		elif (self.temperature < self.setpoint_low+2):
			self.gld.set_value(self.id, "system_mode", "HEAT")

	def turn_off(self):
		self.gld.set_value(self.id,"thermostat_control","NONE")
		self.gld.set_value(self.id, "system_mode", "OFF")


class vb_device():
	'''Packetization state of an individual device'''
	def __init__(self, gld_dev, pem_state=PEM_STATE.PEM_OFF, state_ends_at=0, last_power_draw_kw=4.5):
		self.gld_dev = gld_dev
		self.device_id = gld_dev.id
		self.pem_state = pem_state
		self.state_ends_at = state_ends_at
		self.last_power_draw_kw = last_power_draw_kw
		self.kw = gld_dev.kw

	def update(self, pem_state=None, state_ends_at=None, last_power_draw_kw=None):
		if not pem_state:
			pem_state = self.pem_state
		if not state_ends_at:
			state_ends_at = self.state_ends_at
		if not last_power_draw_kw:
			if self.kw > 0:
				last_power_draw_kw = self.kw
			else:
				last_power_draw_kw = self.last_power_draw_kw
		gld = self.gld_dev.update_from_gld()
		next = vb_device(gld_dev=gld, pem_state=pem_state, state_ends_at=state_ends_at, last_power_draw_kw=last_power_draw_kw)
		return next

	def pem(self, time_sec):
		effect = None
		if self.pem_state is PEM_STATE.PEM_OFF:
			next, effect = self.pem_off(time_sec)
		elif self.pem_state is PEM_STATE.PEM_ON:
			next, effect = self.pem_on(time_sec)
		elif self.pem_state is PEM_STATE.EXIT_OFF:
			next, effect = self.exit_off(time_sec)
		elif self.pem_state is PEM_STATE.EXIT_ON:
			next, effect = self.exit_on(time_sec)
		else:
			next, effect = self.update(pem_state=PEM_STATES.PEM_OFF).pem_off(time_sec)
		next, exit_effect = next.check_exits()
		return next, exit_effect if exit_effect else effect

	def pem_off(self, time_sec):
		if time_sec < self.state_ends_at: return self, None
		if self.gld_dev.check_stat("REQUEST",):
			effect = PowerRequest(self.device_id, self.last_power_draw_kw, sec=CONTROL_EPOCH_SEC)
			return self.update(state_ends_at=time_sec + COMM_EPOCH_SEC), effect
		else:
			return self.update(state_ends_at=time_sec + COMM_EPOCH_SEC), TurnOff(self)

	def pem_on(self, time_sec):
		if time_sec < self.state_ends_at:
			return self, TurnOn(self)
		next, effect = self.update(pem_state=PEM_STATE.PEM_OFF, state_ends_at=time_sec).pem(time_sec)
		return next, effect

	def exit_off(self, time_sec):
		if not self.gld_dev.check_stat("EXIT_OFF",hysteresis=2):
			next = self.update(pem_state=PEM_STATE.PEM_OFF, state_ends_at=time_sec)
			next, effect = next.pem(time_sec)
			return next, effect if effect else TurnOff(self)
		else:
			return self, None

	def exit_on(self, time_sec):
		if not self.gld_dev.check_stat("EXIT_ON",hysteresis=2):
			next = self.update(pem_state=PEM_STATE.PEM_OFF, state_ends_at=time_sec)
			next, effect = next.pem(time_sec)
			return next, effect if effect else TurnOff(self)
		else:
			return self, None

	def check_exits(self):
		if self.gld_dev.check_stat("EXIT_ON"):
			return self.update(
                pem_state=PEM_STATE.EXIT_ON,
                state_ends_at=0,
            ), TurnOn(self)
		if self.gld_dev.check_stat("EXIT_OFF"):
			return self.update(
                pem_state=PEM_STATE.EXIT_OFF,
                state_ends_at=0), TurnOff(self)
		return self, None

	def request_accepted(self,time):
		if self.pem_state is not PEM_STATE.PEM_OFF:
			return self, TurnOn(self)
		return self.update(
            pem_state=PEM_STATE.PEM_ON,
			state_ends_at=time+CONTROL_EPOCH_SEC
        ), TurnOn(self)
