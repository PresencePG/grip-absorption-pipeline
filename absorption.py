# Our local modules
try:
	from julia_server import JuliaServer
	from julia_client import julia_client
	julia_server = JuliaServer() # create the julia server object
	Islanding = True
except ImportError:
	print('Julia Server files not found. Please add julia_client.py, julia_server.py, and the julia/ codedir to working directory for virtual islanding integration.')
	Islanding = False
try:
	from packetized.virtual_battery import *
	from packetized.vb_device import *
	print('Packetized module found, using virtual battery module for absorption.')
	Packetizing = True
except ImportError:
	print('Packetized module not found, using thermal controls for absorption.')
	Packetizing = False
import data_post_process

# Other needed modules
import os
import re
import csv
import json
import time
import pandas as pd
import numpy as np
import random
import warnings
warnings.filterwarnings('ignore')

# global variables
t_start = 0
t_inc = 3 #minutes
re_island = False
islands = None
all_devices = None
islanded_devices = []
islanded = False
device_map = None
load_per_house = {}
Virtual_Battery = None
setpoint = 600
test_setpoint = False
vb_data_out = False
faulted_nodes = []
total_fault_count = 0
houses_off = []
powerbal = {}

packetize_baseline = False
COMPILE = False

def on_init(t):
	'''
	on_init code runs upon GLM model initialization
	'''
	print(time.ctime())
	global COMPILE
	COMPILE = gridlabd.get_global("compileonly")=="TRUE"
	if not COMPILE:
		global Absorption
		global swing_sn
		global setpoint
		Absorption = gridlabd.get_global("LOAD_CONTROL")=="TRUE"
		Absorption = Islanding and Packetizing and Absorption
		print('LOAD_CONTROL = {}'.format(Absorption))
		print(' - Islanding = {}'.format(Islanding and Absorption))
		print(' - Packetizing = {}'.format(Packetizing and Absorption))
		print(' - testing VB setpoint tracking = {}'.format(test_setpoint))
		if ((Absorption) & (Islanding)):
			print("Initializing the Julia Server for Virtual Islanding optimization")
			global julia_server
			global t_start
			if vb_data_out:
				with open('virtual_battery_timeseries.csv', 'w', newline='') as vbcsv:
					VBcsv_writer = csv.writer(vbcsv)
					VBcsv_writer.writerow(['timestamp','VB_soc','VB_avgsoc','VB_load','VB_setpoint','hvac_avgsoc','wh_avgsoc','avg_hvac_temp','avg_wh_temp','avg_out_temp','hvac_load','wh_load','wh_wdemand','nf_shed'])
			baseload = pd.read_csv(f'Loads_baseline.csv')
			setpoint = baseload[[c for c in baseload.columns if (('hvac' in c) or ('wh' in c))]].sum(axis=1).max()*1.05
			try:
				julia_server.start()
			except:
				print("Julia server couldn't start; turning off all Packetized Integration (Absorption)")
				Absorption=False
		t_start = t
		nodestr = gridlabd.get_value("supernode_list","node_group").replace("'",'').replace(" ","")[2:-2]
		supernodes = nodestr.split(',')
		swing_sn = [int(sn.split('_')[1]) for sn in supernodes if gridlabd.get_value(sn,'bustype')=='SWING'][0]
	return True

def on_term(t):
	'''
	on_term code runs upon GLM model termination
	'''
	if not COMPILE:
		if ((Absorption) & (Islanding)):
			print("Shutting down the Julia Server")
			global julia_server
			julia_server.stop()
	print(time.ctime())
	return None

def find(criteria):
	'''
	find() function takes in a criteria string as "key=value" as looks for objects in GLD that match that criteria
	'''
	finder = criteria.split("=")
	if len(finder) < 2:
		raise Exception("find(criteria='key=value'): criteria syntax error")
	objects = gridlabd.get("objects")
	result = []
	for name in objects:
		item = gridlabd.get_object(name)
		if (finder[0] in item) and (item[finder[0]] == finder[1]):
			if "name" in item.keys():
				result.append(item['name'])
			else:
				result.append("{}_{}".format(item['class'],item['id']))
	return result

## GLD data communications functions for VI ##
def convert(list):
	'''
	convert() converts integer list to string list and joins the list using join() (used to format data to send to Julia)
	'''
	res = " ".join(map(str, list))
	return res

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

def shutoff_loads(node):
	'''
	shutoff_loads(node) shuts down all loads at the given node:
		- shuts down any generator inverters with "supernode_name"==node
		- changes all triplex_meters with "supernode_name"==node to "OUT_OF_SERVICE"
		- all water heaters with "supernode_name"==node will also be manually shut off
	'''
	meters = find('class=triplex_meter')
	inverters = find('class=inverter')
	for inv in inverters:
		if gridlabd.get_value(inv,"supernode_name")==node:
			gridlabd.set_value(inv,"P_Out","0")
			gridlabd.set_value(inv,"generator_status","OFFLINE")
			with open(f'{inv}-P_Out.csv','a+') as file:
				file.write(f'{gridlabd.get_global("clock")}, 0\n')
	for m in meters:
		if gridlabd.get_value(m,'supernode_name')==node:
			gridlabd.set_value(m,'service_status',"OUT_OF_SERVICE")
	if node in device_map:
		for w in device_map[node]['waterheaters']:
			gridlabd.set_value(w,'re_override',"OV_OFF")
	return True

def shutoff_noislanding(faulted_node):
	'''
	takes in a supernode and shuts off all loads connected to it or downstream in the network in gridlabd
	'''
	branchkind = {'switch':'switch',
				  'overhead_line':'fixed',
				  'underground_line':'fixed'}
	switchstat = {'CLOSED':True,'OPEN':False}
	branches = []
	for cl in branchkind:
		branches += find('class={}'.format(cl))
	openswitches = [br for br in branches if ((gridlabd.get_value(br,'to') == faulted_node) or gridlabd.get_value(br,'from') == faulted_node)]
	turnoff = [faulted_node]
	next = [faulted_node]
	while next:
		new_next = []
		for node in next:
			to_next = [br for br in branches if gridlabd.get_value(br,'from') == node]
			next_nodes = []
			for link in to_next:
				if switchstat[gridlabd.get_value(link,'status')]:
					next_nodes.append(gridlabd.get_value(link,'to'))
			for n in next_nodes:
				turnoff.append(n)
			new_next += next_nodes
		next = new_next
	for node in turnoff:
		shutoff_loads(node)

	openswitches = [s for s in openswitches if (('solar' not in s) and ('battery' not in s) and (gridlabd.get_value(s,"status")=="CLOSED"))]
	return openswitches

def toggle_switches(switchlist):
	'''
	toggles all switches in given switchlist
		OPEN -> CLOSED & CLOSED -> OPEN
	'''
	toggle_switches = ""
	if len(switchlist) > 0:
		for i in switchlist[:-1]:
			toggle_switches += "{}|".format(i)
		toggle_switches += switchlist[-1]
	gridlabd.set_value("scheme_1", "armed", toggle_switches)
	gridlabd.set_value("scheme_1", "status", "TOGGLE")

def new_fault_detected():
	'''
	check all supernodes in model to see if new faults have occurred
	'''
	global faulted_nodes
	nodestr = gridlabd.get_value("supernode_list","node_group").replace("'",'').replace(" ","")[2:-2]
	supernodes = nodestr.split(',')
	faultchange = False
	tobool = {"TRUE":True,"FALSE":False}
	for sn in supernodes:
		# loop through supernodes getting fault status
		faulted = tobool[gridlabd.get_value(sn,"supernode_fault")]
		if faulted:
			if sn not in faulted_nodes:
				faulted_nodes.append(sn)
				shutoff_loads(sn)
				faultchange = True
		else:# if supernode is not currently faulted, but was previously in the simulation
			if sn in faulted_nodes:
				# remove from faulted_nodes list
				faulted_nodes = [n for n in faulted_nodes if n != sn]
				faultchange = True

	return faultchange

def get_islanding_data(faulted_nodes):
	'''
	loops through gridlabd objects to collect and structure data for absorption_ice julia server
	'''
	branchkind = {'switch':'switch',
				  'overhead_line':'fixed',
				  'underground_line':'fixed'}
	switchstat = {'CLOSED':1,'OPEN':0}
	genstat = {'OFFLINE':0,'ONLINE':1}
	branchdata = {}
	gendata = {}
	batdata = {}
	shuntdata = {}
	meter2bus = {}
	# get branch data
	for cl in branchkind:
		branches = find('class={}'.format(cl))
		for bid in branches:
			branchdata[bid] = {}
			branchdata[bid]['t'] = re.search(r'\d+',gridlabd.get_value(bid,'to')).group()
			branchdata[bid]['f'] = re.search(r'\d+',gridlabd.get_value(bid,'from')).group()
			branchdata[bid]['status'] = switchstat[gridlabd.get_value(bid,'status')]
			branchdata[bid]['kind'] = branchkind[cl]
	# get load data
	meters = find('class=meter')
	tmeters = find('class=triplex_meter')
	powerMW = {m:0 for m in meters}
	for t in tmeters:
		Pval = convert_power_units(gridlabd.get_value(t,'measured_real_power'),'W','MW')
		snode = gridlabd.get_value(t,'supernode_name')
		powerMW[snode]+=Pval
	for mid in powerMW:
		shuntdata[mid] = {}
		shuntdata[mid]['bus'] = re.search(r'\d+',mid).group()
		shuntdata[mid]['P'] = powerMW[mid]
	# get gen data
	pvs = find('class=solar')
	batteries = find('class=battery')
	for gid in pvs:
		gendata[gid] = {}
		gendata[gid]['bus'] = re.search(r'\d+',gid).group()
		gendata[gid]['Pmin'] = 0
		Pmax = gridlabd.get_value(gid,'rated_power')
		gendata[gid]['Pmax'] = convert_power_units(Pmax,'W','MW')
		gendata[gid]['status'] = genstat[gridlabd.get_value(gid,'generator_status')]
		gendata[gid]['solar'] = 1
	for bid in batteries:
		batdata[bid] = {}
		batdata[bid]['bus'] = re.search(r'\d+',bid).group()
		b_dict = dict(gridlabd.get_object(bid))
		inv = b_dict['parent']
		Pmax = gridlabd.get_value(inv,'max_charge_rate')
		batdata[bid]['Pmax'] = convert_power_units(Pmax,'W','MW')
		soc = float(gridlabd.get_value(bid,'state_of_charge').split(' ')[0])
		batdata[bid]['soc'] = soc
		Emax = gridlabd.get_value(bid,'battery_capacity')
		batdata[bid]['Emax'] = convert_power_units(Emax,'Wh','MWh')
		batdata[bid]['status'] =  genstat[gridlabd.get_value(bid,'generator_status')]
	nodestr = gridlabd.get_value("supernode_list","node_group").replace("'",'').replace(" ","")[2:-2]
	supernodes = nodestr.split(',')
	for sn in supernodes:
		if gridlabd.get_value(sn,'bustype')=='SWING':
			gendata['swing_'+sn] = {}
			gendata['swing_'+sn]['bus'] = re.search(r'\d+',sn).group()
			gendata['swing_'+sn]['Pmin'] = 0
			gendata['swing_'+sn]['Pmax'] = 1000 # MW
			gendata['swing_'+sn]['status'] = 1
			gendata['swing_'+sn]['solar'] = 0

	# reformat into dataframes
	gen_df = pd.DataFrame(gendata).transpose()
	bat_df = pd.DataFrame(batdata).transpose()
	shunt_df = pd.DataFrame(shuntdata).transpose()
	shunt_df = shunt_df.loc[shunt_df.P>0,:]
	branch_df = pd.DataFrame(branchdata).transpose()
	branch_df = branch_df.loc[branch_df.t!=branch_df.f,:]
	branch_df['X'] = 0.1
	branch_df['R'] = 0
	branch_df['id'] = branch_df.index
	buses = set(list(branch_df.t)+list(branch_df.f))
	# create 1:nbus node indices for optimization
	nbus = len(buses)
	busids = list(range(1,nbus+1))
	busmap = {int(b):i for i,b in zip(busids,sorted(list(buses)))}
	branch_df.t = [busmap[int(t)] for t in branch_df.t]
	branch_df.f = [busmap[int(f)] for f in branch_df.f]
	gen_df.bus = [busmap[int(f)] for f in gen_df.bus]
	bat_df.bus = [busmap[int(f)] for f in bat_df.bus]
	shunt_df.bus  = [busmap[int(f)] for f in shunt_df.bus]

	# format into one datadump for zmq server
	datadump = {'op':'islanding'}
	for c in ['id','t','f','R','X','status','kind']:
		datadump['branch_'+c] = convert(list(branch_df[c]))
	for c in ['bus','Pmin','Pmax','status','solar']:
		datadump['gen_'+c] = convert(list(gen_df[c]))
	for c in ['bus','Pmax','status','Emax','soc']:
		datadump['bat_'+c] = convert(list(bat_df[c]))
	for c in ['bus','P']:
		datadump['shunt_'+c] = convert(list(shunt_df[c]))
	fnodes = [busmap[int(re.search(r'\d+',n).group())] for n in faulted_nodes]
	datadump['faulted_nodes'] = convert(fnodes)

	# save bus map to map indices back to actual node names
	mapback = {busmap[b]:b for b in busmap}

	return datadump,mapback
####

## virtual islanding functions ##
def islanding(t,faulted_nodes):
	'''
	islanding takes in the list of faulted nodes and the time stamp,
		collects the needed data from GLD using get_islanding_data,
		sends the data through the julia server,
		recieves back the results of branch statuses from the server,
		and returns :
					: branch results as a pandas df
					: the list of bus ids with solar generators at them (for plotting purposes)
	'''
	VI_data,busmap = get_islanding_data(faulted_nodes)
	res = julia_client.send_data(VI_data)
	branch_results = json.loads(str(res)[2:-1])
	results = pd.DataFrame(branch_results['columns'],
				index = branch_results['colindex']['names']).transpose()
	results.t = [busmap[t] for t in results.t]
	results.f = [busmap[f] for f in results.f]
	curr_stat = results.st1.astype(bool)
	return results

def get_components(graph):
	'''
	gets the connected components from a graph:
	 	graph as dict: {node:{set of nodes node is connected to}}
	'''
	already_seen = set()
	result = []
	for node in graph:
		if node not in already_seen:
			connected_group, already_seen = get_connected_group(graph, node, already_seen)
			result.append(connected_group)
	return result

def get_connected_group(graph, node, already_seen):
	'''
	gets connected group for node in graph, given a set of already visited nodes connected to root node
	'''
	result = []
	nodes = set([node])
	while nodes:
		node = nodes.pop()
		already_seen.add(node)
		nodes.update(graph[node] - already_seen)
		result.append(node)
	return result, already_seen

def process_islands(t,results):
	'''
	takes in branch results and generators and performs switching operations to create islands in gridlabd
	returns :
			: new_islands = list of lists of all supernodes in each island
	'''
	switches_to_open = list(results.loc[results.st00!=results.st1,'id'])
	toggle_switches(switches_to_open)

	supernodes = set(list(results.t)+list(results.f))
	# figure out if the network is islanded and get new_islands
	links = [(results.loc[i,'t'],results.loc[i,'f']) for i in results.index if results.loc[i,'st1']]
	net = {n:[[l[0],l[1]] for l in links if n in l] for n in supernodes}
	net = {n:[[l for l in net[n][i] if l != n] for i in range(len(net[n]))] for n in supernodes}
	net = {n:set([l[0] for l in net[n]]) for n in supernodes}
	new_islands = get_components(net)
	inverters = find('class=inverter')
	virtual_islands = []
	for island in new_islands:
		if (swing_sn not in island):
			for i in inverters:
				if int(re.search(r'\d+',i).group()) in island:
					gridlabd.set_value(i,'islanded_state','TRUE')
		if ((swing_sn not in island) and ("supernode_{:03d}".format(island[0]) not in faulted_nodes)):
			virtual_islands.append(island)

	return virtual_islands
####

## absorption functions ##
def temp_control_absorption(house_id,t):
	'''
	turns on basic GLD temperature control logic, responding to air temp and heating and cooling set points for each household
	'''
	gridlabd.set_value(house_id,"thermostat_control","FULL")
	return True

# virtual battery functions for packetized absorption #
def map_devices_to_nodes():
	'''
	creates and returns a dict to map all houses and waterheaters to the supernodes they are connected to
	'''
	houses = find("class=house")
	waterheaters = find("class=waterheater")
	nodestr = gridlabd.get_value("supernode_list","node_group").replace("'",'').replace(" ","")[2:-2]
	supernodes = nodestr.split(',')
	device_map = {n:{} for n in supernodes}
	for node in supernodes:
		device_map[node]['houses'] = set([h for h in houses if gridlabd.get_value(h,"supernode_name") == node])
		device_map[node]['waterheaters'] = set([w for w in waterheaters if gridlabd.get_value(w,"supernode_name") == node])
	return device_map

def initialize_devices(t):
	'''
	intialized GLD / VB devices by creating device map and all virtual battery device objects for water heaters and hvac systems in GLD model
	'''
	global all_devices
	global device_map
	device_map = map_devices_to_nodes()
	waterheaters = find('class=waterheater')
	houses = find('class=house')
	if ((Packetizing) and (Absorption)):
		all_devices = {wh:vb_device(gldWaterHeater(wh,gridlabd),
			state_ends_at=t-t_start) for wh in waterheaters}
		all_devices.update({h:vb_device(gldHVAC(h,gridlabd),
			state_ends_at=t-t_start) for h in houses})

def update_VB(islands):
	'''
	recreate and returns new dict of Virtual Battery objects, one for each island of supernodes
	'''
	global islanded_devices
	global device_map
	if not device_map:
		device_map = map_devices_to_nodes()

	# get swing bus:
	nodestr = gridlabd.get_value("supernode_list","node_group").replace("'",'').replace(" ","")[2:-2]
	supernodes = nodestr.split(',')

	new_Virtual_Battery = {}
	islanded_devices = []
	for i,island in enumerate(islands):
		i_houses = set([])
		i_waterheaters = set([])
		for node in island:
			i_houses.update(device_map['supernode_{:03d}'.format(node)]['houses'])
			i_waterheaters.update(device_map['supernode_{:03d}'.format(node)]['waterheaters'])
		devices = [all_devices[wh] for wh in i_waterheaters] + [all_devices[h] for h in i_houses]
		islanded_devices += i_houses
		islanded_devices += i_waterheaters
		new_Virtual_Battery[tuple(island)] = VirtualBattery(devices=devices)
	if len(new_Virtual_Battery.keys())==0 : return None
	else : return new_Virtual_Battery

def packetize_island(t,island):
	'''
	uses code from packetized module implement virtual batteries from all HVAC systems and water heaters in the model for a particular island
	'''
	global t_start
	global Virtual_Battery
	load = 0
	i = tuple(island)
	device_updates = [d.update() for d in Virtual_Battery[i].devices.values()]
	effects, load = Virtual_Battery[i].next(
					device_updates=device_updates,
					setpoint=Virtual_Battery[i].setpoint,
					time=t-t_start
					)
	for effect in effects.turn_on+effects.turn_off:
		effect.send()

	load = np.sum([d.gld_dev.update_from_gld().kw for d in Virtual_Battery[i].devices.values()])

	return load

def get_island_baseline_data(islands):
	'''
	gets baseline loads and solar generator power from Loads_baseline.csv and Ps_baseline.csv (generated in baseline run with function timeseries_persupernode() in data_post_process.py)
	 	- parses these csv files to aggregate loads for each island that has formed in the circuit for island management optimization
	'''
	for island in islands:
		global load_per_house
		baseline_loads = pd.read_csv("Loads_baseline.csv")
		island_loads = baseline_loads[['timestamp']]
		island_loads.index = island_loads.timestamp
		island_loads['f_baseline'] = 0
		island_loads = island_loads.drop('timestamp',axis=1)
		island_loads['nf_baseline'] = 0
		for n in island:
			if 'hvac_load_{:03d}[kW]'.format(n) in baseline_loads.columns:
				island_loads.f_baseline += baseline_loads['hvac_load_{:03d}[kW]'.format(n)].values
				island_loads.f_baseline += baseline_loads['wh_load_{:03d}[kW]'.format(n)].values
				island_loads.nf_baseline += baseline_loads['total_load_{:03d}[kW]'.format(n)].values
		nhouses = len(island)*60
		load_per_house[tuple(island)] = island_loads.nf_baseline.mean()/nhouses
		island_loads.nf_baseline = island_loads.nf_baseline - island_loads.f_baseline
		baseline_solar = pd.read_csv("Ps_baseline.csv")
		print(baseline_solar.max())
		island_gens = baseline_solar[[c for c in baseline_solar.columns[1:] if ((int(re.search(r'\d+',c).group()) in island) and (gridlabd.get_value(c.split(':')[0].strip(' '),'generator_status')=='ONLINE'))]]
		island_gens.index = baseline_loads.timestamp
		island_str = "_".join(map(str, sorted(island)))
		with open('load_baseline-{}.csv'.format(island_str), mode='w', newline='') as load_baseline_csv_file:
			island_loads.to_csv(load_baseline_csv_file)
		with open('solar_baseline-{}.csv'.format(island_str), mode='w', newline='') as solar_baseline_csv_file:
			island_gens.to_csv(solar_baseline_csv_file)
		# disable reserve soc for batteries
		batteries = find('class=inverter')
		batteries = [b for b in batteries if ((int(re.search(r'\d+',gridlabd.get_value(b,'supernode_name')).group()) in island) and ('battery' in b))]
		for b in batteries:
			gridlabd.set_value(b,'four_quadrant_control_mode','CONSTANT_PQ')
			gridlabd.set_value(b,'soc_reserve','0.0')
		solar = find('class=inverter')
		solar = [b for b in solar if ((int(re.search(r'\d+',gridlabd.get_value(b,'supernode_name')).group()) in island) and ('solar' in b))]
		for s in solar:
			print(s,gridlabd.get_value(s,'rated_power'))
			gridlabd.set_value(s,'four_quadrant_control_mode','CONSTANT_PQ')

	return True

def get_island_management_data(island):
	'''
	retrieves and formats island management optimization data to send to julia server:
	 	island  : island string to match to csv files for baseline loads and solar
		t0 		: start time for optimization (from GLD clock)
		t_inc	: global variable of time step of island management
		solargens: list of online solar generators
		batteries: list of online batteries
		E0_battery: soc of batteries at t0
		Emax_battery: max soc of batteries
		Pmax_battery: max power output of batteries
		E0_virtualb: current soc of virtual battery
		Emax_virtualb: estimated max soc of VB (based on number of devices in island)
		gens 	: list of non-solar generators (not implemented yet)
		Pmax_gens: max power of non-solar generators (not implemented yet)
	'''
	datadump = {'op':'management'}
	island_str = "_".join(map(str, sorted(island)))
	datadump['island'] = island_str
	datadump['t0'] = gridlabd.get_global("clock")
	datadump['t_inc'] = t_inc
	batteries = [b for b in find('class=battery') if ((int(re.search(r'\d+',gridlabd.get_value(b,'supernode_name')).group()) in island) and (gridlabd.get_value(b,'generator_status')=='ONLINE'))]
	solar = [s for s in find('class=solar') if ((int(re.search(r'\d+',gridlabd.get_value(s,'supernode_name')).group()) in island) and (gridlabd.get_value(s,'generator_status')=='ONLINE'))]
	datadump['solargens'] = convert(solar)
	E0_battery = []
	Emax_battery = []
	Pmax_battery = []
	for b in batteries:# need to add check for if battery & solar are online
		E0_battery.append(float(gridlabd.get_value(b,"state_of_charge").split(' ')[0])*convert_power_units(gridlabd.get_value(b,"battery_capacity"),'Wh','kW'))
		Emax_battery.append(convert_power_units(gridlabd.get_value(b,"battery_capacity"),'Wh','kW'))
		b_dict = dict(gridlabd.get_object(b))
		inv = b_dict['parent']
		Pmax = gridlabd.get_value(inv,'max_charge_rate')
		Pmax_battery.append(convert_power_units(Pmax,'W','kW'))
	datadump['batteries'] = convert(batteries)
	datadump['E0_battery'] = convert(E0_battery)
	datadump['Emax_battery'] = convert(Emax_battery)
	datadump['Pmax_battery'] = convert(Pmax_battery)
	datadump['E0_virtualb'] = convert([Virtual_Battery[tuple(island)].soc])
	ndev = len(Virtual_Battery[tuple(island)].devices.keys())
	datadump['Emax_virtualb'] = convert(list([ndev*5]))
	datadump['gens'] = convert([]) # would be where we add other types of generators if they exist in the network model
	datadump['Pmax_gens'] = convert([])

	return datadump

def turn_off_house(island,h):
	'''
	turns off house h and water heater in house and removes both devices from the Virtual_Battery for given island
	'''
	wh = 'waterheater_{}'.format(h.strip('house_'))
	try:
		Virtual_Battery[tuple(island)].devices[h].gld_dev.turn_off()
		Virtual_Battery[tuple(island)].devices.pop(h)
		Virtual_Battery[tuple(island)].devices[wh].gld_dev.turn_off()
		Virtual_Battery[tuple(island)].devices.pop(wh)
	except:
		print(h,' or ',wh, 'not found in VB devices...')
	gridlabd.set_value('meter_{}'.format(h.split('_')[1]),'customer_interrupted','TRUE')

def turn_on_house(island,h,t):
	'''
	turns on house h and water heater in house and adds both devices to the Virtual_Battery for given island
	'''
	wh = 'waterheater_{}'.format(h.strip('house_'))
	all_devices[h].state_ends_at=t-t_start
	all_devices[wh].state_ends_at=t-t_start

	Virtual_Battery[tuple(island)].add_device(all_devices[h])
	Virtual_Battery[tuple(island)].add_device(all_devices[wh])
	gridlabd.set_value('meter_{}'.format(h.split('_')[1]),'customer_interrupted','FALSE')

def island_management(t):
	'''
	runs island management julia optimization for each island not attached to the SWING bus
	'''
	global houses_off
	global Virtual_Battery
	global powerbal
	for island in islands:
		# aggregate load data from baseline
		island_data = get_island_management_data(island)
		if t==t_start:
			island_data["test_out"]=1
		else:
			island_data["test_out"]=0
		res = julia_client.send_data(island_data)
		results = json.loads(str(res)[2:-1])
		results = pd.DataFrame(results['columns'], index = results['colindex']['names']).transpose()
		#print('DATA:',island_data)
		#print('RESULTS:',results)
		Pbal = {'solarP':0, 'nfload':results.nfload.values[0], 'battP':{}, 'VBload':0}
		for c in sorted(results.columns,reverse=True):
			if ('solar' in c):
				Pout = float(results[c].values[0]) # kW
				inv = c.split(":")[0].strip(' ')
				gridlabd.set_value(inv, "P_Out", '{:.02f} kW'.format(Pout))
				with open(f'{inv}-P_Out.csv','a+') as file:
					file.write(f'{gridlabd.get_global("clock")}, {Pout}\n')
				Pbal['solarP'] += Pout
			elif ('shed' in c):
				load_shed = float(results[c].values[0])
				Pbal['nfload'] = Pbal['nfload']-load_shed
				if load_shed>0:
					if round(Virtual_Battery[tuple(island)].setpoint - load_shed) >= 0:
						Virtual_Battery[tuple(island)].setpoint = Virtual_Battery[tuple(island)].setpoint - load_shed
						disconnect_houses = 0
					elif (bool(results["sh_all"].values[0]) and (round(Virtual_Battery[tuple(island)].setpoint)==0)):
						disconnect_houses = np.sum([len(device_map['supernode_{:03d}'.format(n)]['houses']) for n in island])
					else:
						disconnect_houses = int(round(load_shed/load_per_house[tuple(island)]))
					reconnect_houses = 0
					if disconnect_houses >= len(houses_off):
						disconnect_houses = disconnect_houses - len(houses_off)
					elif disconnect_houses < len(houses_off):
						reconnect_houses = len(houses_off) - disconnect_houses
					for n in range(disconnect_houses):
						i = np.random.choice([i for i in island if i >= 100])
						if len([d for d in Virtual_Battery[tuple(island)].devices.keys() if 'house' in d]) > 0:
							h = np.random.choice([d for d in Virtual_Battery[tuple(island)].devices.keys() if 'house' in d],size=1)[0]
							turn_off_house(island,h)
							houses_off.append(h)
					for n in range(reconnect_houses):
						h = np.random.choice(houses_off)
						turn_on_house(island,h,t)
						houses_off = [i for i in houses_off if i!=h]
					print('disconnect houses:',disconnect_houses)
					print('reconnect houses:',reconnect_houses)
			elif ('i_' in c):
				VB_load = float(results[c].values[0])
				Virtual_Battery[tuple(island)].setpoint = VB_load
				newVBload = packetize_island(t,island)
				Pbal['VBload'] = newVBload
			elif ('battery' in c):
				b_dict = dict(gridlabd.get_object(c))
				inv = b_dict['parent']
				Pout = -float(results[c].values[0])
				gridlabd.set_value(inv, "P_Out", '{:.02f} kW'.format(Pout))
				with open(f'{inv}-P_Out.csv','a+') as file:
					file.write(f'{gridlabd.get_global("clock")}, {Pout}\n')
				Pbal['battP'][inv] = Pout
		Pbal = check_power_balance(Pbal)
		powerbal[tuple(island)] = Pbal
		if vb_data_out:
			save_VB_data(Pbal,island)

	return Virtual_Battery
####

def check_power_balance(powerbal):
	'''
	after island management is completed, this function checks that the final state of the island is balanced and uses the batteries to balance if not
	'''
	totload = powerbal['nfload']+powerbal['VBload']
	batpwr = np.sum([powerbal['battP'][b] for b in powerbal['battP']])
	solpwr = powerbal['solarP']
	err = 15
	batts = list(powerbal['battP'].keys())
	if totload-err <= (solpwr + batpwr) <= totload+err:
		pass
	elif  (solpwr + batpwr) < totload-err: #too much load
		diff = totload - (solpwr + batpwr)
		random.shuffle(batts)
		for b,kW in zip(batts,[powerbal['battP'][b] for b in batts]):
			if ((kW <= convert_power_units(gridlabd.get_value(b,'max_discharge_rate'), 'W','kW')-diff) and (diff != 0)): # GLD treats discharging as positive
				newkW = kW + diff
				gridlabd.set_value(b,'P_Out','{:.02f} kW'.format(newkW))
				with open(f'{b}-P_Out.csv','a+') as file:
					file.write(f'{gridlabd.get_global("clock")}, {newkW}\n')
				powerbal['battP'][b] = newkW
				diff = 0
		batpwr = np.sum([powerbal['battP'][b] for b in powerbal['battP']])
	elif  (solpwr + batpwr) > totload-err: #too much power ouput
		diff = (solpwr + batpwr) - totload
		random.shuffle(batts)
		for b,kW in zip(batts,[powerbal['battP'][b] for b in batts]):
			if ((-convert_power_units(gridlabd.get_value(b,'max_charge_rate'), 'W','kW')+diff <= kW) and (diff != 0)): # GLD treats discharging as positive
				newkW = kW - diff
				gridlabd.set_value(b,'P_Out','{:.02f} kW'.format(newkW))
				with open(f'{b}-P_Out.csv','a+') as file:
					file.write(f'{gridlabd.get_global("clock")}, {newkW}\n')
				powerbal['battP'][b] = newkW
				diff = 0
		batpwr = np.sum([powerbal['battP'][b] for b in powerbal['battP']])
	if np.sum([convert_power_units(gridlabd.get_value(b,'P_Out'), 'VA','kW') for b in powerbal['battP']])>1000:
		print('Large battery P value(s):')
		print([(b,gridlabd.get_value(b,'P_Out')) for b in powerbal['battP']])
	return powerbal

def update_flexible_load():
	for supernode in device_map:
		flex_kWh = 0
		for dev,prop in [('houses','hvac_load'), ('waterheaters','actual_load')]:
			for dev_id in device_map[supernode][dev]:
				flex_kWh += float(gridlabd.get_value(dev_id,prop).split(' ')[0])
		gridlabd.set_value(supernode,"flexible_load","{:0.1f}".format(flex_kWh)) #units?

def save_VB_data(powerbal,island):

	with open('virtual_battery_timeseries.csv', 'a', newline='') as vbcsv:
		VBcsv_writer = csv.writer(vbcsv)
		# header row: 'timestamp','VB_soc','VB_avgsoc','VB_load','VB_setpoint','hvac_avgsoc','wh_avgsoc','avg_hvac_temp','avg_wh_temp','avg_out_temp','hvac_load','wh_load','wh_wdemand','nf_shed'
		houses = [d.gld_dev.id for d in Virtual_Battery[tuple(island)].devices.values() if 'house' in d.gld_dev.id]
		whs = [d.gld_dev.id for d in Virtual_Battery[tuple(island)].devices.values() if 'waterheater' in d.gld_dev.id]
		whload = np.sum([convert_power_units(gridlabd.get_value(d,'actual_load'),'kW','kW') for d in whs])
		hvacload = np.sum([convert_power_units(gridlabd.get_value(d,'hvac_load'),'kW','kW') for d in houses])
		wh_demand = np.sum([float(gridlabd.get_value(d,'water_demand').strip(' gmp')) for d in whs])
		VBcsv_writer.writerow([gridlabd.get_global('clock'), Virtual_Battery[tuple(island)].soc, np.mean([d.gld_dev.soc for d in Virtual_Battery[tuple(island)].devices.values()]), powerbal['VBload'], Virtual_Battery[tuple(island)].setpoint, np.mean([d.gld_dev.soc for d in Virtual_Battery[tuple(island)].devices.values() if 'house' in d.device_id]), np.mean([d.gld_dev.soc for d in Virtual_Battery[tuple(island)].devices.values()  if 'waterheater' in d.device_id]), np.mean([d.gld_dev.temperature for d in Virtual_Battery[tuple(island)].devices.values() if 'house' in d.device_id]), np.mean([d.gld_dev.temperature for d in Virtual_Battery[tuple(island)].devices.values() if 'waterheater' in d.device_id]), np.mean([d.gld_dev.outsideT for d in Virtual_Battery[tuple(island)].devices.values() if 'house' in d.device_id]), hvacload, whload, wh_demand, round(powerbal.get('nfload',0),2)])


######### CODE THAT RUNS ON_COMMIT DURING GRIDLAB-D SIMULATION #########
def on_commit(t):
	global t_start
	global islands
	global islanded
	global re_island
	global Virtual_Battery
	global device_map
	global powerbal
	if t-t_start==0:
		if ((Packetizing) and (Absorption)):
			initialize_devices(t)
		else:
			device_map = map_devices_to_nodes()

	print('\r  t={}'.format(pd.Timestamp(gridlabd.get_global("clock"))),end='')

	if new_fault_detected():
		print('\n ** Faults detected at supernodes:',faulted_nodes)
		if Absorption:
			if Islanding:
				print('Islanding ...')
				results = islanding(t,faulted_nodes)
				new_islands = process_islands(t-t_start,results)
				print(new_islands)
				re_island = (new_islands != islands)
				islands = new_islands.copy()
				islanded = True
				if ((not Virtual_Battery) and (re_island) and (Packetizing) and (Absorption)):
					Virtual_Battery = update_VB(islands) # if sim is restarted and islands are present, need to initialize VB
				houses = find("class=house")
				for house_id in houses:
					if house_id not in islanded_devices:
						temp_control_absorption(house_id,t)
		else:
			# isolate faulted nodes and turn off loads connected
			switches_to_open = []
			for node in faulted_nodes:
				switches_to_open += shutoff_noislanding(node)
			toggle_switches(switches_to_open)

	if Absorption:
		if re_island: # islanding occurred and new Virtual Batterys need to be set up for each island
			Virtual_Battery = update_VB(islands)
			#need to get the baseline data for the new island created (aggregate loads by supernode)
			get_island_baseline_data(islands)
			re_island = False
		if Packetizing:
			# perform island management on each t_inc timestep
			t_manage = t_inc*60 # 3 minute time increment for initial optimization
			if (((t-t_start) % t_manage == 0) and (len(islanded_devices)>0) and (islanded) and (gridlabd.get_global("clock")[:-6]!=gridlabd.get_global("STOPTIME")[:-6])):
				Virtual_Battery = island_management(t)
			elif ((len(islanded_devices)>0) and (islanded)):
				for island in islands:
					powerbal[tuple(island)]['VBload'] = packetize_island(t,island)
					powerbal[tuple(island)] = check_power_balance(powerbal[tuple(island)])
					if vb_data_out:
						save_VB_data(powerbal[tuple(island)],island)
			elif ((not Virtual_Battery) and (packetize_baseline)):
				islands = [[int(re.search(r'\d+',n).group()) for n in device_map if gridlabd.get_value(n,'bustype')!='SWING']]
				powerbal[tuple(islands[0])] = {}
				Virtual_Battery = update_VB(islands)
				powerbal[tuple(islands[0])]['VBload'] = packetize_island(t,islands[0])
				if vb_data_out:
					save_VB_data(powerbal[tuple(islands[0])],islands[0])
			elif packetize_baseline:
				Virtual_Battery[tuple(islands[0])].setpoint = 5000
				powerbal[tuple(islands[0])]['VBload'] = packetize_island(t,islands[0])
				if vb_data_out:
					save_VB_data(powerbal[tuple(islands[0])],islands[0])
			if test_setpoint:
				test_VB_setpoint_tracking(t)


	if gridlabd.get_global("clock")[:-6] == gridlabd.get_global("stoptime")[:-6]:
		update_flexible_load()

	return True


def test_VB_setpoint_tracking(t):
	global t_start
	global Virtual_Battery
	global device_map
	island = [int(k.split('_')[1]) for k in device_map.keys()]
	powerbal[tuple(island)] = {}
	if t-t_start==0:
		Virtual_Battery = update_VB([island])
		Virtual_Battery[tuple(island)].setpoint = setpoint
	if test_setpoint:
		if ((6 <= pd.Timestamp(gridlabd.get_global("clock")).hour <= 9) or (20 <= pd.Timestamp(gridlabd.get_global("clock")).hour <= 22)):
			Virtual_Battery[tuple(island)].setpoint = 0
		else:
			Virtual_Battery[tuple(island)].setpoint = setpoint
		powerbal[tuple(island)]['VBload'] = packetize_island(t,island)
	else:
		powerbal[tuple(island)]['VBload'] = np.nan
	save_VB_data(powerbal[tuple(island)],island)
