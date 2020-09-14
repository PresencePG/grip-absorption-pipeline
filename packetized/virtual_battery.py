from enum import Enum
from copy import deepcopy
import numpy as np
from random import (
    random as r_random,
    shuffle as r_shuffle,
    randint as r_randint,
)

prints = False

from packetized.vb_device import *

class VirtualBattery:
    def __init__(self, devices=None, setpoint=100):
        if devices:
            self.devices = {device.device_id: device for device in devices}
        else:
            self.devices = {}
        self.setpoint = setpoint #kW
        self.time_sec = 0
        self.soc = np.sum([d.gld_dev.soc_kWh() for d in self.devices.values()])

    def add_device(self, device):
        self.devices[device.device_id] = device

    def next(self, setpoint=None, device_updates=None, time=None):
        '''Iterate VB given a set of updated device states'''
        if setpoint:
            self.setpoint = setpoint
        if not device_updates:
            device_updates = []
        if time:
            self.time_sec = time
        self.apply_updates(device_updates)
        effects, totalload = self.apply_pem_changes()
        if effects.power_requests:
            additional_turn_on_effects, totalload = self.handle_power_requests(effects.power_requests)
            effects.append(*additional_turn_on_effects)
        return effects, totalload


    def apply_updates(self, device_updates):
        '''Update each device in the virtual battery with new state'''
        for next_state in device_updates:
            device = self.devices.get(next_state.device_id, None)
            if not device:
                continue
            self.devices[device.device_id] = next_state
        self.soc = np.sum([d.gld_dev.soc_kWh() for d in self.devices.values()])

    def apply_pem_changes(self):
        '''Do PEM logic for each device in VB'''
        devices = {}
        effects = Effects()
        totalload = 0
        if prints:
            print("Total number of exit_on devices  = {:.0f}".format(len([device for device in self.devices.values() if device.pem_state == PEM_STATE.EXIT_ON])))
            print("Total number of exit_off devices = {:.0f}".format(len([device for device in self.devices.values() if device.pem_state == PEM_STATE.EXIT_OFF])))
            print("Total number of pem_on devices   = {:.0f} ; avg SOC = {:.02f}".format(len([device for device in self.devices.values() if device.pem_state == PEM_STATE.PEM_ON]),np.mean([device.gld_dev.soc for device in self.devices.values() if device.pem_state == PEM_STATE.PEM_ON])))
            print("Total number of pem_off devices = {:.0f} ; avg SOC = {:.02f}".format(len([device for device in self.devices.values() if device.pem_state == PEM_STATE.PEM_OFF]),np.mean([device.gld_dev.soc for device in self.devices.values() if device.pem_state == PEM_STATE.PEM_OFF])))
            print("Total number of on hvac devices = {} out of {} ; avg SOC = {:.02f}".format(len([device for device in self.devices.values() if (((device.pem_state == PEM_STATE.PEM_ON) or (device.pem_state == PEM_STATE.EXIT_ON)) and ('house' in device.device_id))]),len([device for device in self.devices.values() if ('house' in device.device_id)]),np.mean([device.gld_dev.soc for device in self.devices.values() if (((device.pem_state == PEM_STATE.PEM_ON) or (device.pem_state == PEM_STATE.EXIT_ON)) and ('house' in device.device_id))])))
            print("Total number of pem off hvac devices = {} out of {} ; avg SOC = {:.02f}".format(len([device for device in self.devices.values() if ((device.pem_state == PEM_STATE.PEM_OFF) and ('house' in device.device_id))]),len([device for device in self.devices.values() if ('house' in device.device_id)]),np.mean([device.gld_dev.soc for device in self.devices.values() if ((device.pem_state == PEM_STATE.PEM_OFF) and ('house' in device.device_id))])))
        for device in list(self.devices.values()):
            newdevice, effect = device.pem(self.time_sec)
            if effect:
                if effect.on:
                    if totalload < round(self.setpoint):
                        totalload += effect.kw
                        devices[device.device_id] = newdevice
                        effects.append(effect)
                    else:
                        devices[device.device_id] = device.update(pem_state=PEM_STATE.PEM_OFF)
                        effects.append(TurnOff(device))
                else:
                    effects.append(effect)
                    devices[device.device_id] = newdevice
        self.devices = devices

        return effects, totalload

    def handle_power_requests(self, power_requests):
        '''Respond to power requests'''
        r_shuffle(power_requests) # shuffle power requests to simulate having received them one at a time
        totalkw = sum(map(lambda d: d.kw, self.devices.values()))
        accepted_requests = []
        if prints:
            print('there are {} power requests; starting load = {}'.format(len(power_requests),totalkw))
        for power_request in power_requests:
            if abs(totalkw + power_request.kw - self.setpoint) <= abs(totalkw - self.setpoint):
                device = self.devices.get(power_request.device_id, None)
                if not device:
                    continue
                device, request_accepted = self.devices[power_request.device_id].request_accepted(self.time_sec)
                self.devices[device.device_id] = device
                if request_accepted:
                    #print('\r  power req accepted',totalkw,end='')
                    totalkw += power_request.kw
                    accepted_requests.append(request_accepted)
        if prints:
            print('VB setpoint:',round(self.setpoint,2))
            print("Total kw for all device effects = {:.02f}".format(totalkw))
            print('accepted requests:',len(accepted_requests))
            print(abs(totalkw + power_request.kw - self.setpoint),'<=',abs(totalkw - self.setpoint))
        return accepted_requests, totalkw
