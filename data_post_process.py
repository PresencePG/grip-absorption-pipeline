def log_gen() :
	print("Starting the log generation")
	import csv
	fr_name = 'log_rec.csv'
	fw_name = 'log.csv'
	property_type = []
	log_entry = []
	prev_row = []
	log_header = ['timestamp', 'type','name', 'value']
	try :
		with open(fr_name, newline='', mode='r') as csvfile :
			fr = csv.reader(csvfile, delimiter=',', quotechar='|')
			for row in fr :
				if '#' in row[0] and '# timestamp' not in row[0]:
					continue
				elif '# timestamp' in row[0] :
					property_type = row
				else :
					if not prev_row :
						prev_row = row
					else :
						for i, item in enumerate(row) :
							if item not in prev_row[i] :
								if 'status' in property_type[i] :
									log_entry.append([row[0], 'EVENT',property_type[i], item])
								elif 'fault_type' in property_type[i] :
									log_entry.append([row[0], 'FAULT',property_type[i], item])
						prev_row=[]
						prev_row = row[:]
	except :
		print("Running as a compile only option, log will not be generated")

	with open(fw_name, newline='', mode='w') as csvfile :
		fw = csv.writer(csvfile, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
		fw.writerow(log_header)
		for line in log_entry :
			fw.writerow(line)
	return True

def timeseries_gen() :
	print("Starting to produce the timeseries output files")
	import csv
	header = ['timestamp','generation_kW', 'total_load_kW', 'flexible_load_kW', 'unserved_energy_%', 'storage_power_kW','storage_energy_kWh']

	gen_str_csv = 'timeseries_data_gen_strg.csv'
	load_csv = 'total_load.csv'
	flex_HVAC_csv = 'flexible_load_HVAC.csv'
	flex_WH_csv = 'flexible_load_WH.csv'
	# unsrvd_csv = 'unserved_load.csv'
	baseline_csv = 'baseline.csv'
	final_csv = 'timeseries.csv'

	timeseries = []
	generation = []
	storage_power = []
	storage_energy = []
	total_load = [] # kWh, measured by accumulated energy in GLD,
	flexible_load = []
	flexible_load_HVAC = []
	flexible_load_WH = []
	unserved_load = [] # kWh, measured by accumulated energy in GLD
	baseline_load = [] # kWh, measured by accumulated energy in GLD
	# compute the generation data
	try :
		with open(gen_str_csv, newline='',mode='r') as gen_str_csvfile :
			rd_gen_str = csv.reader(gen_str_csvfile, delimiter=',', quotechar='|')
			for row in rd_gen_str :
				if '#' not in row[0] :
					timeseries.append(row[0])
					generation.append(float(row[1].split(" ")[0])+float(row[2].split(" ")[0])+float(row[3].split(" ")[0]))
					storage_power.append((float(row[4].split(" ")[0])+float(row[5].split(" ")[0])+float(row[6].split(" ")[0]))) # -1 for charging is positive
					storage_energy.append(float(row[7].split(" ")[0])*float(row[10].split(" ")[0])+float(row[8].split(" ")[0])*float(row[11].split(" ")[0])+float(row[9].split(" ")[0])*float(row[12].split(" ")[0]))
	except FileNotFoundError:
		print('Missing ', gen_str_csv, ' file')
	# compute the total load data
	try :
		with open(load_csv, newline='',mode='r') as load_csvfile :
			rd_load = csv.reader(load_csvfile, delimiter=',', quotechar='|')
			for row in rd_load :
				if '#' not in row[0]  :
					total_load.append(float(row[1].split(" ")[0]))
	except FileNotFoundError:
		print('Missing ', load_csv, ' file')
	# compute the flexible HVAC load
	try :
		with open(flex_HVAC_csv, newline='',mode='r') as flex_HVAC_csvfile :
			rd_flex_HVAC = csv.reader(flex_HVAC_csvfile, delimiter=',', quotechar='|')
			for row in rd_flex_HVAC :
				if '#' not in row[0] :
					flexible_load_HVAC.append(float(row[1].split(" ")[0]))
	except FileNotFoundError:
		print('Missing ', flex_HVAC_csv, ' file')
	# compute the flexible water heater load data
	try :
		with open(flex_WH_csv, newline='',mode='r') as flex_WH_csvfile :
			rd_flex_WH = csv.reader(flex_WH_csvfile, delimiter=',', quotechar='|')
			for row in rd_flex_WH :
				if '#' not in row[0]  :
					flexible_load_WH.append(float(row[1].split(" ")[0]))
	except FileNotFoundError:
		print('Missing ', flex_WH_csv, ' file')
	# compute the total flexible load
	flexible_load = [x + y for x, y in zip(flexible_load_HVAC, flexible_load_WH)]
	# compute the baseline load in energy (kWh)
	try :
		with open(baseline_csv, newline='',mode='r') as baseline_csv_file :
			rd_baseline = csv.reader(baseline_csv_file, delimiter=',', quotechar='|')
			for row in rd_baseline :
				if '#' not in row[0] :
					for i,time in enumerate(timeseries) :
						if time in row[0] :
							baseline_load.append(float(row[1]))
		# now compute the unserved energy
		last_baseline_E = baseline_load[-1]
		unserved_load = [((base - act)/last_baseline_E)*100 for base,act in zip(baseline_load, total_load)]
	except FileNotFoundError:
		print('Missing ', baseline_csv, ' file')

	# print the finalized csv file
	with open(final_csv, newline='', mode='w') as final_file:
		wr_final = csv.writer(final_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
		wr_final.writerow(header)
		for i in range(len(timeseries)):
			wr_final.writerow([timeseries[i],generation[i],total_load[i],flexible_load[i],unserved_load[i],storage_power[i],storage_energy[i]])
	return True

def timeseries_persupernode(runname=''):
	import pandas as pd
	import re
	timeseries_gen = pd.read_csv('timeseries_data_gen_strg.csv',header=7)
	timeseries_gen['timestamp'] = timeseries_gen['# timestamp']
	timeseries_gen.index = timeseries_gen['timestamp']
	timeseries_gen = timeseries_gen.drop(['timestamp','# timestamp'],axis=1)
	Ps_baseline = timeseries_gen[[c for c in timeseries_gen.columns if 'solar' in c]]
	with open('Ps_{}.csv'.format(runname), mode='w', newline='') as ps_baseline_csv_file:
		Ps_baseline.to_csv(ps_baseline_csv_file)
	baseline_loads = []
	nodes = []
	supernodes = ['supernode_{:03d}'.format(s) for s in [101,102,103,201,202,203,301,302,303]]
	for sn in supernodes:
		node = re.search(r'\d+',sn).group()
		nodes.append(node)
		load = pd.read_csv('total_load_{}.csv'.format(sn),header=8 )
		load.columns = ['timestamp','total_load_{}[kW]'.format(node)]
		hvac = pd.read_csv('hvac_load_{}.csv'.format(sn),header=8)
		hvac.columns = ['timestamp','hvac_load_{}[kW]'.format(node)]
		wh = pd.read_csv('wh_load_{}.csv'.format(sn),header=8)
		wh.columns = ['timestamp','wh_load_{}[kW]'.format(node)]
		loads = pd.concat([load,hvac,wh],axis=1)
		if len(wh.timestamp)==len(hvac.timestamp)==len(load.timestamp):
			pass
		else:
			print('!timestamp mismatch with baseline load output!')
		loads.index = wh.timestamp
		loads = loads.drop('timestamp',axis=1)
		baseline_loads.append(loads)
	baseline_loads = pd.concat(baseline_loads,axis=1)
	with open('Loads_{}.csv'.format(runname), mode='w', newline='') as baseline_loads_csv_file:
		baseline_loads.to_csv(baseline_loads_csv_file)
