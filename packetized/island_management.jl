# tools for managing islanded dEvbices
using JuMP
using DataFrames
using CSV
using SparseArrays
using Cbc
using Dates
import Base.Filesystem

function manage_island((t0,             # time to start op at
                        t_inc,          # time (min) to increment
                        island,
                        load_baseline,  # baseline dataframe with flexible load, nonflexible load for the island
                        Ps_baseline,    # power output for each solar gen in island
                        gens,
                        Pmax_gens,      # max power output of nonsolar gens in island
                        batteries,
                        Pmax_battery,   # max power for each battery
                        E0_battery,      # soc for each battery at t0
                        Emax_battery,   # max energy for each battery
                        E0_virtualb,     # soc for each virtual battery at t0
                        Emax_virtualb   # max energy for each virtual battery
                        );
                        testing=false, # prints some additional output files
                        path=""
                    )
    """
    After getting resources for each island, iterate through each island using this function to manage the setpoints for solar, batteries, and virtual batteries
        - 3 min increments over 24 hr horizon
            t0              : time step to start op at, then loop full baseline 24hrs
            f_baseline      : baseline flexible load in the island (from virtual battery dEvbices)
            nf_baseline     : baseline nonflexible load in the island
            Ps_baseline         : baseline power output of the solar gens
            gens            : names of the nonsolar gens
            Pmax_gens       : max power output of non-solar gens
            batteries       : names of the batteries
            Pmax_battery    : max power for the batteries
            E0_battery       : current soc of the batteries at t0
            Emax_battery    : max soc of the batteries
            E0_virtualb      : current soc of virtual battery at t0
            Emax_virtualb   : 2kWh per WH 1kWh per HVAC
    """
    # weights for objective function
    shed_val = 1000
    battsoc_val = 0.9
    virtsoc_val = 0.9
    efficiency = 1
    custcomf_val = 0.9

    # get constants from filtered data
    t0_i = convert(Int64,findall(load_baseline.timestamp.==t0)[1])
    K=size(load_baseline)[1]
    new_baseline_load = copy(load_baseline)
    t0_to_eod = load_baseline.nf_baseline[t0_i:K]
    sod_to_t0 = load_baseline.nf_baseline[1:t0_i-1]
    nonflex_load = vcat(t0_to_eod,sod_to_t0)
    new_baseline_load.nf_baseline = nonflex_load
    t0_to_eod = load_baseline.f_baseline[t0_i:K]
    sod_to_t0 = load_baseline.f_baseline[1:t0_i-1]
    flex_load = vcat(t0_to_eod,sod_to_t0)
    new_baseline_load.f_baseline = flex_load
    t0_to_eod = load_baseline.timestamp[t0_i:K]
    sod_to_t0 = load_baseline.timestamp[1:t0_i-1]
    new_baseline_load.timestamp = vcat(t0_to_eod,sod_to_t0)
    t0_to_eod = Ps_baseline[t0_i:K,:]
    sod_to_t0 = Ps_baseline[1:t0_i-1,:]
    Ps_baseline = vcat(t0_to_eod,sod_to_t0)

    # filter the data based on t_inc
    t_index = Dates.value(convert(Dates.Second, Dates.DateTime(load_baseline.timestamp[2][1:end-6], "yyyy-mm-ddTHH:MM:SS")-Dates.DateTime(load_baseline.timestamp[1][1:end-6], "yyyy-mm-ddTHH:MM:SS")))/60 # convert seconds to minutes
    t_inc = convert(Int64,t_inc / t_index)
    load_baseline = load_baseline[1:t_inc:end,:]
    new_baseline_load = new_baseline_load[1:t_inc:end,:]
    delta_t= Dates.value(convert(Dates.Second, Dates.DateTime(load_baseline.timestamp[2][1:end-6], "yyyy-mm-ddTHH:MM:SS")-Dates.DateTime(load_baseline.timestamp[1][1:end-6], "yyyy-mm-ddTHH:MM:SS")))/60/60 # convert seconds to hours

    nonflex_load = nonflex_load[1:t_inc:end]
    flex_load = flex_load[1:t_inc:end]
    Pmax_virtualb = transpose(2 .* flex_load)
    K=size(nonflex_load)[1]

    nsolar = size(Ps_baseline)[2]-1
    if nsolar>0
        solargens = [n for n in names(Ps_baseline)[2:end]]
        P_solar = convert(Matrix,Ps_baseline[solargens])
        P_solar = transpose(convert(Array{Float64},P_solar))
        P_solar = P_solar[:,1:t_inc:end]
    end

    ngens = length(Pmax_gens)
    @assert(length(Pmax_battery)==length(E0_battery)==length(Emax_battery))
    @assert(length(E0_virtualb)==length(Emax_virtualb))
    if E0_virtualb > Emax_virtualb
        println("* Virtual battery Emax estimate error * using E0 as Emax for Op.")
        Emax_virtualb = E0_virtualb
    end
    nbatt = length(Pmax_battery)
    nvirt = size(Pmax_virtualb,1)
    @assert(nvirt==1)

    # initiate the model
    m = Model(Cbc.Optimizer)
    MOI.set(m, MOI.Silent(), true)

    # power variables and limits
    @variable(m,Ps[1:nsolar,1:K])
    @constraint(m,[s=1:nsolar,k=1:K], 0 <= Ps[s,k] <= P_solar[s,k])
    @variable(m,Pg[1:ngens,1:K])
    @constraint(m,[k=1:K], 0 .<= Pg[:,k] .<= Pmax_gens)
    @variable(m,Pb[1:nbatt,1:K])
    @constraint(m,[b=1:nbatt,k=1:K], -Pmax_battery[b] <= Pb[b,k] <= Pmax_battery[b])
    @variable(m,Pvb[1:nvirt,1:K])
    @constraint(m,[v=1:nvirt,k=1:K], 0 <= Pvb[v,k] <= Pmax_virtualb[v,k])
    @variable(m,Dshed[1:K])
    @constraint(m,[k=1:K], 0 <= Dshed[k] <= nonflex_load[k])

    # conventional battery energy - - charging batteries is positive power
    @variable(m,Eb[1:nbatt,1:(K+1)])
    @constraint(m,[b=1:nbatt,k=1:(K+1)], 0 <= Eb[b,k] <= Emax_battery[b])
    @constraint(m,[b=1:nbatt], Eb[b,1] == E0_battery[b])
    @constraint(m,[b=1:nbatt,k=1:K], Eb[b,k+1] == Eb[b,k] + Pb[b,k]*delta_t)
    # virtual battery variables and constraints, Pvb>0 implies charging
    @variable(m,Evb[1:nvirt,1:(K+1)])
    @variable(m,cust_comfort[1:nvirt,1:(K+1)])
    @constraint(m, cust_comfort .<= 0)
    @constraint(m,ccomf[v=1:nvirt,k=1:(K+1)], 0 + cust_comfort[v,k] <= Evb[v,k])
    @constraint(m,[v=1:nvirt,k=1:(K+1)], Evb[v,k] <= Emax_virtualb[v])
    @constraint(m,[v=1:nvirt], Evb[v,1] == E0_virtualb[v])
    # NOTE that the line below will only work if there is exactly 1 virtual battery
    @constraint(m,[v=1:nvirt,k=1:K], Evb[v,k+1] == efficiency*Evb[v,k] + Pvb[v,k]*delta_t - flex_load[k]*delta_t) # flex load is the baseline amount

    # power balance
    @constraint(m,[k=1:K], sum(Pg[:,k]) + sum(Ps[:,k]) == nonflex_load[k] - Dshed[k] + sum(Pvb[:,k]) + sum(Pb[:,k]))

    ## objective
    @objective(m, Min, shed_val * # weight for load shedding
                       sum(Dshed)*delta_t
                        -
                        battsoc_val * # weight for battery soc
                       sum(Eb[b,K+1] for b=1:nbatt)
                        -
                       virtsoc_val * # weight for battery socsum(
                       sum(Evb[v,K+1] for v=1:nvirt)
                        -
                       custcomf_val *
                       sum(sum(cust_comfort))
                )

    optimize!(m)
    status = termination_status(m)
    if (status==MOI.OPTIMAL) || (status==MOI.ALMOST_OPTIMAL) || (status==MOI.LOCALLY_SOLVED)
        Popt_solar = value.(Ps)
        Popt_gens  = value.(Pg)
        Popt_batt  = value.(Pb)
        Popt_virt  = value.(Pvb)
        Dshed_opt  = value.(Dshed)
        Eopt_virt = value.(Evb)
        Eopt_batt = value.(Eb)
    else
        println("Island management optimization did not solve successfully")
        Popt_solar = zeros(nsolar,K)
        Popt_gens  = zeros(ngens,K)
        Popt_batt  = zeros(nbatt,K)
        Popt_virt  = zeros(nvirt,K)
        Dshed_opt  = zeros(K)
    end
    # collect the results into a dataframe
    solarDict = Dict()
    if nsolar>0
        solargens = [string(g) for g in solargens]
        solarDict = Dict(zip(solargens,Popt_solar[1:nsolar,2]))
    end
    genDict = Dict()
    if ngens>0
        genDict = Dict(zip(gens,Popt_gens[1:ngens,2]))
    end
    battDict = Dict()
    if nbatt>0
        battDict = Dict(zip(batteries,Popt_batt[1:nbatt,2]))
    end

    virtDict = Dict(zip([string("i_",island)],Popt_virt[2]))

    shedDict = Dict(zip(["shed"],Dshed_opt[2]))
    shedAllD = Dict(zip(["sh_all"],[convert(Int,Dshed_opt[2]==nonflex_load[2])]))
    loadDict = Dict(zip(["nfload"],nonflex_load[2]))

    dataDict = merge(solarDict,genDict,battDict,virtDict,shedDict,shedAllD,loadDict)
    results = DataFrame(dataDict)


    if testing
        println("outputting CSV files of optimal solution")
        #Filesystem.mkpath("../../testing_output/test_islandmanagement_op_data/")
        costofcomf = sum(dual.(ccomf))
        println("customer comfort dual sum = $costofcomf")
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/solaropt_op.csv",DataFrame(Popt_solar))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/solar_op.csv",DataFrame(P_solar))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/battP_op.csv",DataFrame(Popt_batt))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/battE_op.csv",DataFrame(Eopt_batt))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/virtP_op.csv",DataFrame(Popt_virt))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/virtE_op.csv",DataFrame(Eopt_virt))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/shed_op.csv",DataFrame(transpose(Dshed_opt)))
        CSV.write("../../testing_output/test_islandmanagement_op_data/$path/load_op.csv",new_baseline_load)
        totshed = sum(Dshed_opt)
        println("total load shed = $totshed")
    end
    return results


end
