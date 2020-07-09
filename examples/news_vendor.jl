# A simple example reading a StochOptFormat file and solving it via Benders
# decomposition.
#
# The code is demonstration only, and does not contain robust checks or many
# nice error messages, preferring to throw assertion errors.

using JuMP
import Clp
import JSON
import JSONSchema

"""
    mathoptformat_to_jump(node)

Convert a MathOptFormat model in `node["subproblem"]` into a JuMP equivalent
using the Clp optimizer.
"""
function mathoptformat_to_jump(node)
    # Read the problem into a MOI model first.
    model = MOI.FileFormats.Model(format = MOI.FileFormats.FORMAT_MOF)
    io = IOBuffer()
    write(io, JSON.json(node["subproblem"]))
    seekstart(io)
    MOI.read!(io, model)
    # Then copy it to a JuMP model.
    subproblem = Model(Clp.Optimizer)
    MOI.copy_to(subproblem, model)
    set_silent(subproblem)
    node["subproblem"] = subproblem
    return node
end

"""
    solve_first_stage(node)

Solve the first stage problem.
"""
function solve_first_stage(node)
    sp = node["subproblem"]
    optimize!(sp)
    if termination_status(sp) != MOI.OPTIMAL
        error("Unable to solve first stage to optimality!")
    end
    return (
        obj = objective_value(sp),
        x = Dict(
            name => value(variable_by_name(sp, s["out"]))
            for (name, s) in node["state_variables"]
        ),
        sol = Dict(name(x) => value(x) for x in all_variables(sp))
    )
end

"""
    solve_second_stage(node, state, noise)
"""
function solve_second_stage(node, state, noise)
    sp = node["subproblem"]
    for (name, s) in node["state_variables"]
        fix(variable_by_name(sp, s["in"]), state[name]; force = true)
    end
    for (name, w) in noise["support"]
        fix(variable_by_name(sp, name), w; force = true)
    end
    optimize!(sp)
    return Dict(
        "probability" => noise["probability"],
        "objective" => objective_value(sp),
        "pi" => Dict(
            name => shadow_price(FixRef(variable_by_name(sp, s["in"])))
            for (name, s) in node["state_variables"]
        )
    )
end

function add_cut(first_stage, x, ret_second)
    sp = first_stage["subproblem"]
    cut_term = @expression(
        sp,
        sum(
            ret["probability"] * (
                ret["objective"] +
                sum(
                    ret["pi"][name] * (variable_by_name(sp, s["out"]) - x[name])
                    for (name, s) in first_stage["state_variables"]
                )
            ) for ret in ret_second
        )
    )
    if objective_sense(sp) == MOI.MAX_SENSE
        @constraint(sp, first_stage["theta"] <= cut_term)
    else
        @constraint(sp, first_stage["theta"] >= cut_term)
    end
    return
end

function load_two_stage_problem(filename)
    data = JSON.parsefile(filename)
    @assert(data["version"]["major"] == 0)
    @assert(data["version"]["minor"] == 1)
    @assert(length(data["nodes"]) == 2)
    @assert(length(data["edges"]) == 2)
    nodes = Dict(
        name => mathoptformat_to_jump(node) for (name, node) in data["nodes"]
    )
    first_stage, second_stage = nothing, nothing
    for edge in data["edges"]
        if edge["from"] == data["root"]["name"]
            first_stage = nodes[edge["to"]]
        else
            second_stage = nodes[edge["to"]]
        end
    end
    sp = first_stage["subproblem"]
    for (name, init) in data["root"]["state_variables"]
        x = variable_by_name(sp, first_stage["state_variables"][name]["in"])
        fix(x, init["initial_value"]; force = true)
    end
    first_stage["theta"] = @variable(sp, -1e6 <= theta <= 1e6)
    set_objective_function(sp, objective_function(sp) + first_stage["theta"])
    return first_stage, second_stage
end

function benders(first_stage, second_stage, iteration_limit = 20)
    bounds = Tuple{Float64, Float64}[]
    # Collect the names of the outgoing state variables in the first stage.
    x_out = Set(s["out"] for s in values(first_stage["state_variables"]))
    for iter = 1:iteration_limit
        # Forward pass. Solve the first stage problem.
        ret_first = solve_first_stage(first_stage)
        ret_second = [
            solve_second_stage(second_stage, ret_first.x, noise)
            for noise in second_stage["realizations"]
        ]
        stat_bound = ret_first.obj - value(first_stage["theta"]) +
            sum(ret["probability"] * ret["objective"] for ret in ret_second)
        add_cut(first_stage, ret_first.x, ret_second)
        push!(bounds, (ret_first.obj, stat_bound))
        if abs(ret_first.obj - stat_bound) < 1e-6
            break
        end
    end
    return bounds, solve_first_stage(first_stage)
end

function validate(filename; schema_filename = "../sof.schema.json")
    schema = JSONSchema.Schema(JSON.parsefile(schema_filename))
    return JSONSchema.validate(JSON.parsefile(filename), schema)
end

validate("news_vendor.sof.json")
first_stage, second_stage = load_two_stage_problem("news_vendor.sof.json")
ret = benders(first_stage, second_stage)

# Check solution!
ret = solve_first_stage(first_stage)
@show ret
@assert(ret.x["x"] ≈ 10)
