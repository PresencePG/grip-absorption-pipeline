def find(criteria) :
    finder = criteria.split("=")
    if len(finder) < 2 :
      raise Exception("find(criteria='key=value'): criteria syntax error")
    objects = gridlabd.get("objects")
    result = []
    for name in objects :
      item = gridlabd.get_object(name)
      if finder[0] in item and item[finder[0]] == finder[1] :
        if "name" in item.keys() :
          result.append(item["name"])
        else :
          result.append("%s:%s" % (item["class"],item["id"]))
    return result

def on_init(t) :
	return True 

def on_commit(t) :
  houses = find("class=house") #finds all the house names 
  for house_id in houses : 
    absorption(house_id, t)
  return t

def absorption(house_id,t) : 

#  houses = find("class=house") #finds all the house names 
#  for house_id in houses : 
    # SET FLAG FOR HVAC
  gridlabd.set_value(house_id,"thermostat_control","NONE") #disables internal controls
    #print(house_id, "Air temperature ->", gridlabd.get_value(house_id,"air_temperature"), "Setpoint (heat) ->", gridlabd.get_value(house_id,"heating_setpoint"),"Setpoint (cool) ->", gridlabd.get_value(house_id,"cooling_setpoint"))
  T_air = gridlabd.get_value(house_id,"air_temperature")
  T_heat = gridlabd.get_value(house_id,"heating_setpoint")
  T_cool = gridlabd.get_value(house_id,"cooling_setpoint")
  if T_air < T_heat :
    gridlabd.set_value(house_id, "system_mode", "HEAT") 
  elif T_air >= T_heat and T_air <= T_cool : 
    gridlabd.set_value(house_id, "system_mode", "OFF") 
  if T_air > T_cool : 
    gridlabd.set_value(house_id, "system_mode", "COOL") 
    #print("System mode ->", gridlabd.get_value(house_id,"system_mode"))
    # SET FLAG FOR WH 
  return True

def balancing(name,t) : 
	return True

