using CSV


function format_fire_case()
    #test setup for island 102 103
    solarmult = 0.06
    println("multiplying solar data by $solarmult")
    island = "2_3_101_103_201_202_203_301_302_303"
    load_baseline = CSV.read("../load_baseline-2_3_101_103_201_202_203_301_302_303.csv")
    Ps_baseline = CSV.read("../solar_baseline-2_3_101_103_201_202_203_301_302_303.csv")
    for col in names(Ps_baseline)
        if col != :timestamp
            Ps_baseline[col] = Ps_baseline[col] .* solarmult
        end
    end
    t0 = "2020-10-15T00:00:00-04:00"
    t_inc = 3
    batteries = ["battery_supernode_103","battery_supernode_203","battery_supernode_303"]
    E0_battery = [3000,3000,3000]
    Emax_battery = [3000,3000,3000]#kWh
    Pmax_battery = [3000,3000,3000]#kW
    E0_virtualb = [1290]#kWh
    Emax_virtualb = [1440.0]#kWh
    gens = []
    Pmax_gens = []

    return t0,t_inc,island,
            load_baseline,Ps_baseline,
            gens,Pmax_gens,
            batteries,Pmax_battery,E0_battery,Emax_battery,
            E0_virtualb,Emax_virtualb
end

function format_ice_case()
    #test setup for island 102 103
    solarmult = 0.4
    println("multiplying solar data by $solarmult")
    island = "202_203_303"
    load_baseline = CSV.read("../load_baseline-202_203_303.csv")
    Ps_baseline = CSV.read("../solar_baseline-202_203_303.csv")
    for col in names(Ps_baseline)
        if col != :timestamp
            Ps_baseline[col] = Ps_baseline[col] .* solarmult
        end
    end
    t0 = "2020-01-30T00:00:00-05:00"
    t_inc = 3
    batteries = ["battery_supernode_203","battery_supernode_303"]
    E0_battery = [3000,3000]
    Emax_battery = [3000,3000]#kWh
    Pmax_battery = [3000,3000]#kW
    E0_virtualb = [415.]#kWh
    Emax_virtualb = [480.]#kWh
    gens = []
    Pmax_gens = []

    return t0,t_inc,island,
            load_baseline,Ps_baseline,
            gens,Pmax_gens,
            batteries,Pmax_battery,E0_battery,Emax_battery,
            E0_virtualb,Emax_virtualb
end
