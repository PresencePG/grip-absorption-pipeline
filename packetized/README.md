# PACKETIZED VIRTUAL BATTERY CODE

## For Gridlab-D integration

> `vb_device.py` defines the device objects, currently for both waterheater and house (hvac system) objects in gridlab-d

>> `REQ_die_roll()` defines the probability function for device power requests

>> All GLD specific code, getting or setting values, is done within the `gldWaterHeater` and `gldHVAC` object functions.

> `virtual_battery.py` defines the Virtual Battery python objects and the algorithm for device management

>`island_management.jl` contains the Julia Jump optimization code for managing the islanded devices in a network 

#### For questions, feel free to email `sarah@packetizedenergy.com`
