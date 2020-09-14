import CSV
using DataFrames
using LightGraphs
using SparseArrays

function read_graph(nodes::String,links::String)
    nodes_df = CSV.read(nodes)
    links_df = CSV.read(links)
    n = size(nodes_df,1)
    m = size(links_df,1)
    g = SimpleGraph(n)
    for i = 1:size(links_df,1)
        add_edge!(g,Edge(links_df[i,1],links_df[i,2]))
    end
    return g
end

function read_graph(nodes::Array,links::Array)
    error("not done yet")
end

# find the links that are ajacent to each node in an undirected graph
function adj_links(nodes,links)
    n = size(nodes,1)
    adj = Array{Array{Int64},1}(undef,n)
    for i = 1:n
        id = nodes[i,1]
        a = links[:,1].==id
        b = links[:,2].==id
        adj[i] = findall( a .| b )
    end
    return adj
end

@doc """`i = find_in(a, b)`

An implementation of findin() from Julia versions <= 0.6.x.""" ->
function find_in(a, b)
	return findall(.!isnothing.(indexin(a, b)))
end

function getset(d::Dict,k::Array,v::Any)
    n = length(k)
    result = Array{typeof(d[k[1]]),1}(undef,n)
    for i = 1:n
        result[i] = get(d,k[i],v)
    end
    return result
end

function adjacency(nodes_in::DataFrame,links_in::DataFrame)
    nodes = Array{Int64,1}(nodes_in[:,1])
    links = Array{Int64,2}(links_in[:,1:2])
    return adjacency(nodes,links)
end

function adjacency(nodes::Array{Int64,1},T::Array{Int64,1},F::Array{Int64,1})
    n = size(nodes,1)
    ei = Dict(nodes .=> collect(1:n))
    subset = in.(T,[nodes]) .& in.(F,[nodes]) # link indices for which (from_node,to_node) belong to nodes
    f  = getset(ei,F[subset],0)
    t  = getset(ei,T[subset],0)
    A = sparse([f;t], [t;f], 1, n, n)
    return (A,ei)
end

# find the nodes that are ajacent to each node in an undirected graph
function adj_nodes(nodes,links)
    error("not done yet")
end

# return a random integer up to size n
function randi(n)
    return rem(abs(rand(Int)),n) + 1
end

function unvisited_neighbors(adj,id,visited)
    neighbors = find(adj[:,id])
end


function find_cycles(T,F;n_iter=0)
    # prep work
	nodes = unique(vcat(T,F))
    n = size(nodes,1)
    m = size(T,1)
    if n_iter==0
        n_iter = n*2
    end
    # pre-find all of the neighbors for all of the nodes
    neighbors = Array{Array{Int64,1},1}(undef,n)
    (adj,ei) = adjacency(nodes,T,F)
    for i = 1:n
        neighbors[i] = findnz(adj[:,i])[1]
    end
    #println("neighbors: $neighbors")
    # find the cycles
    cycles = []
    for iter = 1:n_iter
        visited = Array{Int64,1}(undef,0)
        origin = randi(n)
        #println("origin: $origin")
        id = origin
        i=0
        #println("origin: $origin")
        while true
            i+=1
            if i>n
                error("error in find_cycles. Traversed the whole graph???")
            end
            #println("visited: $visited")
            # find neighbors of id
            near = neighbors[id]
            #println("i: $i, id: $id, near: $near, visited: $visited")
            # figure out which of these we have already visited
            if i>2
                not_visited_neighbors = setdiff(near,visited)
            elseif i==2
                # don't immediately go back to the origin
                not_visited_neighbors = setdiff(near,union(visited,origin))
            else #i==1
                not_visited_neighbors = near
            end
            #println("not_visited_neighbors: $not_visited_neighbors")
            n_nvn = length(not_visited_neighbors)
            if n_nvn == 0 # we didnt find a cycle
                #println("None left to visit")
                break
            end
            # randomly select one of the unvisited neighbors
            ix = randi(n_nvn)
            next = not_visited_neighbors[ix]
            #println("next: $next")
            # if the new node is the origin, then we have found a cycle
            if next==origin
                cycle = sort!(union(origin,visited))
                #println("cycle: $cycle")
                new_cycle=true
                for k = 1:length(cycles)
                    if cycles[k]==cycle
                        new_cycle = false
                        break
                    end
                end
                if new_cycle
                    push!(cycles,cycle)
                end
                break
            end
            # add next to the set of nodes visited
            visited = union(visited,next)
            id = next
        end
    end
    # now translate the internal numbers to external ones
    cycles_t = Array{Any,1}(undef,length(cycles))
    for i = 1:length(cycles)
        #println(cycles[i])
        cycles_t[i] = nodes[cycles[i]]
    end
    return sort!(cycles_t)
end
