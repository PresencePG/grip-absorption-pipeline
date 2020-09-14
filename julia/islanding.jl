# tools for separating a power system into islands
#using Gurobi
using JuMP
using Cbc
using DataFrames
using CSV
using SparseArrays

# random number generator
#rng = MersenneTwister(1);

"""
function find_islands(ps)
    Determine how to divide the system described in the structure ps into islands
"""
function find_islands(ps)
    # get information about the problem
    # call the core solver
end

"""
isolate_nodes(T,F,fnodes)
    Determine which branches to switch off to isolate faulted nodes
        *** ASSUMPTION that all branches can be switched ***
    inputs:
        T,F are vectors where each indices is a branch and the values of T & F are the to and from nodes of each branch, respectively
        fnodes is a list of faulted nodes
    outputs:
        br_out is a vector of the branch indices where either the to or from node is faulted
"""
function isolate_nodes(T,F,switchable,fnodes)
    br_out = []
    for n in fnodes # find all branch indices that point to or from faulted nodes to isolate nodes
        for i in findall(T.==n)
            push!(br_out,i)
        end
        for i in findall(F.==n)
            push!(br_out,i)
        end
    end
    return unique(br_out)
end


"""
islanding_core(
    n_bus,baseMVA,                       # general case data
    F,T,R,X,br_status0,switchable,loops, # data about branches
    G,Pg_min,Pg_max,                     # data about generators
    B,Eb_max,E0,Pb_max,                  # data about batteries
    D,Pd0                                # data about loads
)
  inputs:
    baseMVA is the baseMVA value for per unit calcs
    F,T,R,X are standard transmission line parameters.
        F,T are the node indices of branch end points (starting at 1)
        R,X are in per unit on the MVA base
    switchable is a vector of bools indicating if the line segment is switchable
    G,Pg_min,Pg_max are standard generation parameters.
    solar is a bool for whether each generator is solar or not
    B,Pb_max,Eb_max,E0 are standard battery parameters.
    D,Pd are the node indices and amount of load at each node
    All power units should be in MW unless otherwise specified
  outputs:
    br_status, which will indicate where switching events need to occur
"""

test_tup = (12, 1, [1, 2, 3, 4, 5, 3, 7, 8, 3, 10, 11, 6, 12], [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 9, 9], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1], Bool[false, true, true, false, false, true, true, true, true, true, true, false, false], Bool[false, true, true, false, false, true, true, true, true, true, true, true, true], Any[[3, 4, 5, 6, 7, 8, 9], [3, 4, 5, 6, 9, 10, 11, 12], [3, 7, 8, 9, 10, 11, 12]], [5, 8, 11, 1], [0.0, 0.0, 0.0, 0.0], [0.54, 0.54, 0.54, 1000.0], Bool[true, true, true, false], [6, 9, 12], [3.0, 3.0, 3.0], [3.0, 3.0, 3.0], [3.0, 3.0, 3.0], [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0], [0.0710081, 0.0754654, 0.0665306, 0.0991438, 0.0428724, 0.0575823, 0.0531115, 0.0575756, 0.0665306])

function islanding_core((
    n_bus,baseMVA, # general case data
    F,T,R,X,br_status0,switchable,loops, # data about branches
    G,Pg_min,Pg_max,solar,B,Eb_max,E0,Pb_max,D,Pd0 # data about generators and loads
    ))
    # check things
    @assert(length(F)==length(T)==length(X)==length(br_status0))
    @assert(length(Pd0)==length(D))
    @assert(length(Pg_max)==length(G))
    # count things
    nbr = length(F)
    n   = n_bus
    nd  = length(D)
    ng  = length(G) #TODO separate solar from other potential generators
    nb = length(B)
    # how many switches do we have?
    n_switches = sum(switchable)
    can_switch_on  = switchable .& br_status0 .== false
    can_switch_off = switchable .& br_status0 .== true
    # constants
    switch_const = 10
    bigM = 100
    load_value = 10000 # TODO: Make this an input parameter
    Cd = load_value.*ones(nd) + (rand(nd) .- 0.5).*(load_value/2)
    C_R = sum(Cd)/nd * 0.1 # TODO: Make this an input parameter
    C_B = 100
    # get solar gen indices
    solar_i = findall(solar.== true)
    # create two different time periods of the op (night/day)
    avg_CF = 0.2
    delta_t = [avg_CF*24,(1-avg_CF)*24] # time of day day/night
    K = length(delta_t)
    CF = ones(ng,K) # capacity factors day/night for each gen
    for i in solar_i
        CF[i,K] = 0 # only make capacity factor go down for solar gens
    end
    # initiate the model
    m = Model(Cbc.Optimizer)
    MOI.set(m, MOI.Silent(), true)

    ## set up the variables
    @variable(m,switch_on[1:nbr])
    @variable(m,switch_off[1:nbr])
    # fix the variables that we don't need
    for i=1:nbr
        if switchable[i] && br_status0[i]==false
            fix(switch_off[i],0)
            set_binary(switch_on[i])
        elseif switchable[i] && br_status0[i]==true
            fix(switch_on[i],0)
            set_binary(switch_off[i])
        else
            fix(switch_off[i],0)
            fix(switch_on[i],0)
        end
    end
    # power generation
    @variable(m,Pg[1:ng,1:K])
    @constraint(m,[k=1:K], Pg_min .<= Pg[:,k] .<= Pg_max*CF[k])
    @variable(m,dPg[1:ng,1:K])
    @constraint(m, [k=1:K], Pg_min .<= Pg[:,k] + dPg[:,k] .<= Pg_max*CF[k])
    # battery variables
    @variable(m,Pb[1:nb,1:K])
    @constraint(m,[k=1:K], -Pb_max .<= Pb[:,k] .<= Pb_max)
    @variable(m,dPb[1:nb,1:K])
    @constraint(m,[k=1:K], -Pb_max .<= dPb[:,k] .<= Pb_max)
    @variable(m,Eb[1:nb,1:K])
    @constraint(m,[k=1:K], 0 .<= Eb[:,k] .<= Eb_max)
    @variable(m,dEb[1:nb,1:K])
    @constraint(m,[k=1:K], 0 .<= dEb[:,k] .<= Eb_max)
    for b=1:nb
        @constraint(m, Eb[b,1] == E0[b] + Pb[b,1]*delta_t[1])
        @constraint(m,[k=1:K-1], Eb[b,k+1] == Eb[b,k] + Pb[b,k+1]*delta_t[k+1])
        @constraint(m, dEb[b,1] == E0[b] + (Pb[b,1] + dPb[b,1])*delta_t[1])
        @constraint(m,[k=1:K-1], dEb[b,k+1] == dEb[b,k] + (Pb[b,k+1] + dPb[b,k+1])*delta_t[k+1])
    end
    # load
    @variable(m,Pd[1:nd,1:K])
    @constraint(m,[k=1:K], 0 .<= Pd[:,k] .<= Pd0)
    @variable(m, dPd[1:nd,1:K] )
    @constraint(m, [k=1:K], dPd[:,k] .>= 0)
    @variable(m,ud[1:nd],Bin) # binary variable for loads
    @constraint(m, sum(ud)>=1) # need at least one of the loads on
    @constraint(m, [k=1:K], dPd[:,k] .<= bigM.*ud) # delta-load is zero if ud=0
    # branch-flow variable
    @variable(m,flow[1:nbr,1:K])
    @variable(m,d_flow[1:nbr,1:K])
    # reserve margin variable
    @variable(m,R)

    ## objective(s)
    @objective(m, Max, sum(transpose(Cd)*Pd) # value of load served
                        + sum(C_R*R)  # value of reserves
                        #+ sum(C_R.*dPd) # value of additional load??? < do we need this?
                        + C_B*sum(Eb[:,K])
                        - switch_const*(sum(switch_on) + sum(switch_off)) # minimize switching operations
                        - sum(ud) # reducethe number of locations where we are counting reserves
                    )
    ## constraints
    # branch flow limits (control for switches)
    for i=1:nbr
        for k=1:K
            @constraint(m, -bigM*(br_status0[i] + switch_on[i] - switch_off[i]) <= flow[i,k])
            @constraint(m, flow[i,k] <= bigM*(br_status0[i] + switch_on[i] - switch_off[i]))
            @constraint(m, -bigM*(br_status0[i] + switch_on[i] - switch_off[i]) <= d_flow[i,k])
            @constraint(m, d_flow[i,k] <= bigM*(br_status0[i] + switch_on[i] - switch_off[i]))
        end
    end
    # power balance
    Imat = incidence_matrix(n_bus,F,T)
    Fmat = Imat' # transpose
    Gmat = sparse(G,collect(1:ng),1,n_bus,ng)
    Bmat = sparse(B,collect(1:nb),1,n_bus,nb)
    Dmat = sparse(D,collect(1:nd),1,n_bus,nd)
    @variable(m, GBvec[1:n_bus,1:K])
    @variable(m, GBdvec[1:n_bus,1:K])
    @variable(m, DFdvec[1:n_bus,1:K])
    for k=1:K
        @constraint(m, sum(Bmat*Pb[:,k]) == 0)
        @constraint(m, Gmat*Pg[:,k] + Bmat*Pb[:,k] .== GBvec[:,k])
        @constraint(m, GBvec[:,k] .== Fmat*flow[:,k] + Dmat*Pd[:,k])
        @constraint(m, Gmat*(Pg[:,k]+dPg[:,k]) + Bmat*(Pb[:,k]+dPb[:,k]) .== GBdvec[:,k])
        @constraint(m, Dmat*(Pd[:,k]+dPd[:,k]) + Fmat*(flow[:,k]+d_flow[:,k]) .== DFdvec[:,k])
        @constraint(m, GBdvec[:,k] .== DFdvec[:,k])
    end
    # loop constraint
    for li = 1:length(loops)
        #is_switchable = switchable[loops[li]]
        ix = loops[li] # an index to use locally
        @constraint(m,sum(br_status0[ix] + switch_on[ix] - switch_off[ix]) <= length(ix)-1)
    end
    # reserve margin constraint
    for i = 1:nd
        @constraint(m,[k=1:K],(1-ud[i])*bigM + dPd[i,k] >= R)
    end
    # DEBUG: print the model
    #println(m)
    ## solve the model
    optimize!(m)
    ## extract the results
    stat = termination_status(m)
    if stat==MOI.OPTIMAL || stat==MOI.LOCALLY_SOLVED
        br_status = (br_status0 + value.(switch_on) - value.(switch_off)) .> 0.9
        println(br_status)
        return (br_status)
    else
        error("Failed to find an optimal solution to the islanding problem")
    end
    return "Error in islanding_core() - should not reach this state"
end

function incidence_matrix(n,F,T)
    m = length(F)
    Imat = sparse(collect(1:m),F,1,m,n) + sparse(collect(1:m),T,-1,m,n)
end
