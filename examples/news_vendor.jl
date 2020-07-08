# A simple example reading a StochOptFormat file and solving it via Benders
# decomposition.
#
# The code is demonstration only, and does not contain robust checks or many
# nice error messages, preferring to throw assertion errors.

using JuMP
import Clp
import JSON
import JSONSchema

function mathoptformat_to_jump(node)
    io = IOBuffer()
    write(io, JSON.json(node["subproblem"]))
    seekstart(io)
    model = MOI.FileFormats.Model(format = MOI.FileFormats.FORMAT_MOF)
    MOI.read!(io, model)
    jmp = Model()
    MOI.copy_to(jmp, model)
    set_optimizer(jmp, Clp.Optimizer)
    set_silent(jmp)
    return Dict(
        "prob" => jmp,
        "vars" => Dict(name(v) => v for v in all_variables(jmp)),
        "state_variables" => node["state_variables"],
        "noise_term" => get(node, "noise_terms", Any[])
    )
end

function solve_second_stage(node, state, noise)
    for (name, s) in node["state_variables"]
        fix(node["vars"][s["in"]], state[name]; force = true)
    end
    for (name, w) in noise
        fix(node["vars"][name], w; force = true)
    end
    optimize!(node["prob"])
    return Dict(
        "objective" => objective_value(node["prob"]),
        "pi" => Dict(
            name => shadow_price(FixRef(node["vars"][s["in"]]))
            for (name, s) in node["state_variables"]
        )
    )
end

function solve_first_stage(node)
    optimize!(node["prob"])
    return Dict(
        name => value(node["vars"][s["out"]])
        for (name, s) in node["state_variables"]
    )
end

function add_cut(first_stage, x, ret)
    cut_term = @expression(
        first_stage["prob"],
        sum(
            p * r["objective"] +
            p * sum(
                r["pi"][name] * (first_stage["vars"][s["out"]] - x[name])
                for (name, s) in first_stage["state_variables"]
            )
            for (p, r) in ret
        )
    )
    if objective_sense(first_stage["prob"]) == MOI.MAX_SENSE
        @constraint(first_stage["prob"], first_stage["theta"] <= cut_term)
    else
        @constraint(first_stage["prob"], first_stage["theta"] >= cut_term)
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
        name => mathoptformat_to_jump(node)
        for (name, node) in data["nodes"]
    )
    first_stage, second_stage = nothing, nothing
    for edge in data["edges"]
        if edge["from"] == data["root"]["name"]
            first_stage = nodes[edge["to"]]
        else
            second_stage = nodes[edge["to"]]
        end
    end
    for (name, init) in data["root"]["state_variables"]
        x = first_stage["vars"][first_stage["state_variables"][name]["in"]]
        fix(x, init["initial_value"]; force = true)
    end
    first_stage["theta"] = @variable(first_stage["prob"], -1e6 <= theta <= 1e6)
    set_objective_function(
        first_stage["prob"],
        objective_function(first_stage["prob"]) + first_stage["theta"]
    )
    return first_stage, second_stage
end

function benders(first_stage, second_stage, iteration_limit = 20)
    bounds = []
    for iter = 1:iteration_limit
        x = solve_first_stage(first_stage)
        det_bound = objective_value(first_stage["prob"])
        ret = [(
            noise["probability"],
            solve_second_stage(second_stage, x, noise["support"])
        ) for noise in second_stage["noise_term"]]
        stat_bound = det_bound - value(first_stage["theta"]) + sum(
            p * r["objective"] for (p, r) in ret
        )
        add_cut(first_stage, x, ret)
        push!(bounds, (det_bound, stat_bound))
        if abs(det_bound - stat_bound) < 1e-6
            break
        end
    end
    return bounds
end

function validate(filename)
    schema = JSONSchema.Schema(JSON.parsefile("../sof.schema.json"))
    return JSONSchema.validate(JSON.parsefile(filename), schema)
end

validate("news_vendor.sof.json")
first_stage, second_stage = load_two_stage_problem("news_vendor.sof.json")
ret = benders(first_stage, second_stage)

# Check solution!
x = solve_first_stage(first_stage)
@assert(x["x"] ≈ 10)
