include("island_management.jl")
include("test_case_island_management.jl")

# run fire case
println("Running FIRE case optimization:")
input_data = format_fire_case()
manage_island(input_data; testing=true, path="FIRE")

# run ice case
println("Running ICE case optimization:")
input_data = format_ice_case()
manage_island(input_data; testing=true, path="ICE")
