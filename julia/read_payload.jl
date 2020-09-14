
function read_VIpayload(msg)

    # get branch data
    branch = [ss for ss in split(msg["branch_id"])]
    T = [parse(Int, ss) for ss in split(msg["branch_t"])]
    F = [parse(Int, ss) for ss in split(msg["branch_f"])]
    R = [parse(Float64, ss) for ss in split(msg["branch_R"])]
    X = [parse(Float64, ss) for ss in split(msg["branch_X"])]
    br_st = [parse(Int, ss)==1 for ss in split(msg["branch_status"])]
    switchable = [ss=="switch" for ss in split(msg["branch_kind"])]

    # get generator data
    G = [parse(Int, ss) for ss in split(msg["gen_bus"])]
    Pg_min = [parse(Float64, ss) for ss in split(msg["gen_Pmin"])]
    ge_st = [parse(Float64, ss) for ss in split(msg["gen_status"])].==1
    Pg_max = [parse(Float64, ss) for ss in split(msg["gen_Pmax"])].*ge_st
    solar = [parse(Int, ss) for ss in split(msg["gen_solar"])].==1

    # get battery data
    B = [parse(Int, ss) for ss in split(msg["bat_bus"])]
    ba_st = [parse(Float64, ss) for ss in split(msg["bat_status"])].==1
    Pb_max = [parse(Float64, ss) for ss in split(msg["bat_Pmax"])].*ba_st
    Eb_max = [parse(Float64, ss) for ss in split(msg["bat_Emax"])].*ba_st
    E0 = [parse(Float64, ss) for ss in split(msg["bat_soc"])].*Eb_max

    # get load data
    D = [parse(Float64, ss) for ss in split(msg["shunt_bus"])]
    Pd0 = [parse(Float64, ss) for ss in split(msg["shunt_P"])]
    faulted_nodes = [parse(Int, ss) for ss in split(msg["faulted_nodes"])]

    return (branch,T,F,R,X,br_st,switchable,
                G,Pg_min,Pg_max,ge_st,solar,
                B,Pb_max,Eb_max,E0,ba_st,
                D,Pd0,faulted_nodes)
end

function read_IMpayload(msg)
    island = msg["island"]
    t0 = msg["t0"]
    t_inc = convert(Int64, msg["t_inc"])
    # get battery data
    batteries = [ss for ss in split(msg["batteries"])]
    E0_battery = [parse(Float64, ss) for ss in split(msg["E0_battery"])]
    Emax_battery = [parse(Float64, ss) for ss in split(msg["Emax_battery"])]
    Pmax_battery = [parse(Float64, ss) for ss in split(msg["Pmax_battery"])]

    # get virtual battery data
    E0_virtualb = [parse(Float64, ss) for ss in split(msg["E0_virtualb"])]
    Emax_virtualb = [parse(Float64, ss) for ss in split(msg["Emax_virtualb"])]

    gens = [ss for ss in split(msg["gens"])]
    Pmax_gens = [parse(Float64, ss) for ss in split(msg["Pmax_gens"])]

    solargens = [ss for ss in split(msg["solargens"])]

    return (island,t0,t_inc,
            batteries,E0_battery,Emax_battery,Pmax_battery,
            E0_virtualb,Emax_virtualb,
            gens,Pmax_gens,solargens)
end
