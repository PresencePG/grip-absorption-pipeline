println("Julia is doing prep work...")
using ZMQ
using JSON

include("islanding.jl")
include("read_payload.jl")
include("graph_tools.jl")
include("../packetized/island_management.jl")

ctx = Context()

connection_uri = ENV["SERVER_LISTEN_URI"]

receiver = Socket(ctx, PAIR)
ZMQ.bind(receiver, connection_uri)

println("Julia ready . . .")
# set up virtual battery, define water heater models
while true
    raw_msq = recv(receiver, String)
    msg = JSON.parse(raw_msq)
    # Do work here
    sent_at = msg["at"]
    message = msg["message"]
    # VIRTUAL ISLANDING OPTIMIZATION
    if haskey(msg,"op")
    if msg["op"]=="islanding"
        (branch,T,F,R,X,br_st,switchable,
            G,Pg_min,Pg_max,ge_st,solar,
            B,Pb_max,Eb_max,E0,ba_st,
            D,Pd0,faulted_nodes) = read_VIpayload(msg)
        n_bus = size(unique(vcat(T,F)),1)
        nbr = size(branch,1)
        baseMVA = 1
        br_st00 = copy(br_st) # get copy of original branch switch statuses
        # outages $TODO need to edit isolate_nodes to work if not all branches are switches (current assumption)
        br_failures = isolate_nodes(T,F,switchable,faulted_nodes)
        gen_outages = []
        bat_outages = []
        for n in faulted_nodes
            for i in findall(G.==n)
                push!(gen_outages,i)
            end
            for i in findall(B.==n)
                push!(bat_outages,i)
            end
        end
        # implement line failures
        switchable[br_failures] .= false
        br_st[br_failures] .= false
        ge_st[gen_outages] .= false
        ba_st[bat_outages] .= false
        # look in graph for cycles / loops
        loops = find_cycles(T,F) # still need to test if working correctly
        #print((n_bus,baseMVA, # general case data
            #F,T,R,X,br_st,switchable,loops, # data about branches
            #G,Pg_min,Pg_max,solar,B,Eb_max,E0,Pb_max,D,Pd0 # data about generators and loads
            #))
        (br_status) =
            islanding_core((n_bus,baseMVA, # general case data
            F,T,R,X,br_st,switchable,loops, # data about branches
            G,Pg_min,Pg_max,solar,B,Eb_max,E0,Pb_max,D,Pd0 # data about generators and loads
            )) #,R,Pd,dPd,Pg,dPg,flow,ud)
        branch_results = DataFrame(id=branch, t=T, f=F, st00=br_st00, st0=br_st, st1=br_status)
        send(receiver, JSON.json(branch_results))
        print("ISLANDING OPTIMIZATION COMPLETE\n")
        continue
    end
    # ISLAND MANAGEMENT OPTIMIZATION
    if msg["op"]=="management"
        if ((msg["test_out"]==1) & (false))
            testing=true
        else
            testing=false
        end

        (island,t0,t_inc,batteries,E0_battery,Emax_battery,Pmax_battery,
         E0_virtualb,Emax_virtualb,gens,Pmax_gens, solargens) = read_IMpayload(msg)
         load_baseline = CSV.read("load_baseline-$island.csv")
         Ps_baseline = CSV.read("solar_baseline-$island.csv")
        setpoint_results = manage_island((
                        t0, t_inc, island,
                        load_baseline,Ps_baseline,
                        gens,Pmax_gens,
                        batteries,Pmax_battery,E0_battery,Emax_battery,
                        E0_virtualb,Emax_virtualb
                        );testing=testing)
         send(receiver, JSON.json(setpoint_results))
         continue
    end
    end
    send(receiver, "Recieved message sent at '$(sent_at)'")
    #println("$(sent_at): $(message)")
end
