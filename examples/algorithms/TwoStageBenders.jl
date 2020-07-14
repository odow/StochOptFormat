# TwoStageBenders.jl
#
# Author
#   Oscar Dowson
#
# Description
#   A simple example reading a StochOptFormat file and solving it via Benders
#   decomposition.
#
#   The code is intended for pedagogical use. It does not contain robust checks
#   or nice error messages, preferring to throw assertion errors.
#
# Usage
#   julia TwoStageBenders.jl [problem]
#   julia TwoStageBenders.jl ../problems/newsvendor.sof.json
#
# Notes
#   You need to install Julia, and have the following packages installed:
#       Clp, JSON, JSONSchema, and JuMP.
module TwoStageBenders

import Clp
import JSON
import JSONSchema
import JuMP
import Printf
import SHA

struct TwoStageProblem
    sha256::String
    first::JuMP.Model
    second::JuMP.Model
    state_variables::Set{String}
    test_scenarios::Vector{Vector{Dict{String, Any}}}
end

"""
    TwoStageProblem(filename::String; validate::Bool = true)

Create a two-stage stochastic program by reading `filename` in StochOptFormat.

If `validate`, validate `filename` against the StochOptFormat schema.
"""
function TwoStageProblem(filename::String; validate::Bool = true)
    sha_256 = open(filename) do io
        bytes2hex(SHA.sha2_256(io))
    end
    data = JSON.parsefile(filename)
    if validate
        _validate_stochoptformat(data)
    end
    @assert(data["version"]["major"] == 0)
    @assert(data["version"]["minor"] == 1)
    first, second = _get_stage_names(data)
    problem = TwoStageProblem(
        sha_256,
        _mathoptformat_to_jump(data["nodes"][first]),
        _mathoptformat_to_jump(data["nodes"][second]),
        Set(keys(data["nodes"][first]["state_variables"])),
        data["test_scenarios"],
    )
    _initialize_first_stage(data, first, problem.first)
    return problem
end

function _validate_stochoptformat(
    data::Dict; schema_filename = "../sof.schema.json"
)
    schema = JSONSchema.Schema(JSON.parsefile(schema_filename))
    return JSONSchema.validate(data, schema)
end

function _initialize_first_stage(data::Dict, first::String, sp::JuMP.Model)
    states = data["nodes"][first]["state_variables"]
    for (name, init) in data["root"]["state_variables"]
        x = JuMP.variable_by_name(sp, states[name]["in"])
        JuMP.fix(x, init["initial_value"]; force = true)
    end
    JuMP.@variable(sp, -1e6 <= theta <= 1e6)
    JuMP.set_objective_function(sp, JuMP.objective_function(sp) + theta)
    return
end

function _get_stage_names(data::Dict)
    @assert length(data["nodes"]) == 2
    @assert length(data["edges"]) == 2
    edge_1, edge_2 = data["edges"]
    @assert edge_1["probability"] == 1.0
    @assert edge_2["probability"] == 1.0
    first, second = "", ""
    if edge_1["from"] == data["root"]["name"]
        @assert edge_2["from"] != data["root"]["name"]
        @assert edge_1["to"] == edge_2["from"]
        return edge_1["to"], edge_2["to"]
    else
        @assert edge_2["from"] == data["root"]["name"]
        @assert edge_2["to"] == edge_1["from"]
        return edge_2["to"], edge_1["to"]
    end
end

function _mathoptformat_to_jump(node)
    model = JuMP.MOI.FileFormats.Model(format = JuMP.MOI.FileFormats.FORMAT_MOF)
    io = IOBuffer()
    write(io, JSON.json(node["subproblem"]))
    seekstart(io)
    JuMP.MOI.read!(io, model)
    subproblem = JuMP.Model(Clp.Optimizer)
    JuMP.MOI.copy_to(subproblem, model)
    JuMP.set_silent(subproblem)
    subproblem.ext[:state_variables] = node["state_variables"]
    subproblem.ext[:realizations] = node["realizations"]
    _convert_realizations(subproblem.ext[:realizations])
    return subproblem
end

# These `_convert_realization` functions are Julia-specific helper functions to
# convert the support dictionaries from `Dict{Symbol, Any}` to
# `Dict{Symbol, Float64}`.
function _convert_realizations(realizations)
    for r in realizations
        r["support"] = convert(Dict{String, Float64}, r["support"])
    end
end

# These are helper functions to extract the incoming and outgoing state
# variables from a JuMP model.
function _incoming_state(sp::JuMP.Model, name::String)
    return JuMP.variable_by_name(sp, sp.ext[:state_variables][name]["in"])
end
function _outgoing_state(sp::JuMP.Model, name::String)
    return JuMP.variable_by_name(sp, sp.ext[:state_variables][name]["out"])
end

function _solve_first_stage(problem::TwoStageProblem)
    sp = problem.first
    JuMP.optimize!(sp)
    @assert JuMP.termination_status(sp) == JuMP.MOI.OPTIMAL
    return Dict(
        "objective" => JuMP.objective_value(sp) - JuMP.value(sp[:theta]),
        "primal" => Dict(
            JuMP.name(x) => JuMP.value(x) for x in JuMP.all_variables(sp)
            # Don't leak the cost-to-go variable back to the user.
            if x != sp[:theta]
        )
    )
end

function _solve_second_stage(
    problem::TwoStageProblem,
    state_variables::Dict{String, Float64},
    random_variables::Dict{String, Float64},
)
    sp = problem.second
    for name in problem.state_variables
        JuMP.fix(_incoming_state(sp, name), state_variables[name]; force = true)
    end
    for (name, w) in random_variables
        JuMP.fix(JuMP.variable_by_name(sp, name), w; force = true)
    end
    JuMP.optimize!(sp)
    return Dict(
        "objective" => JuMP.objective_value(sp),
        "primal" => Dict(
            JuMP.name(x) => JuMP.value(x) for x in JuMP.all_variables(sp)),
    )
end

function _add_benders_optimality_cut(
    problem::TwoStageProblem,
    state_variables::Dict{String, Float64},
    probabilities::Vector{Float64},
    objectives::Vector{Float64},
    dual_variables::Vector{Dict{String, Float64}},
)
    cut_term = JuMP.@expression(problem.first, sum(
            p * (
                y + sum(
                    π[name] * (_outgoing_state(problem.first, name) - x_val)
                    for (name, x_val) in state_variables
                )
            ) for (π, y, p) in zip(dual_variables, objectives, probabilities)
        )
    )
    if JuMP.objective_sense(problem.first) == JuMP.MOI.MAX_SENSE
        JuMP.@constraint(problem.first, problem.first[:theta] <= cut_term)
    else
        JuMP.@constraint(problem.first, problem.first[:theta] >= cut_term)
    end
    return
end

"""
    train(problem::TwoStageProblem; iteration_limit = 20)

Train a two-stage problem using Benders decomposition.
"""
function train(problem::TwoStageProblem; iteration_limit = 20)
    println("Iteration | Lower Bound | Upper Bound | Gap (abs)")
    for iter = 1:iteration_limit
        ret_first = _solve_first_stage(problem)
        probabilities = Float64[]
        objectives = Float64[]
        dual_variables = Dict{String, Float64}[]
        x = Dict(
            name => ret_first["primal"][s["out"]]
            for (name, s) in problem.second.ext[:state_variables]
        )
        for realization in problem.second.ext[:realizations]
            ret = _solve_second_stage(problem, x, realization["support"])
            push!(probabilities, realization["probability"])
            push!(objectives, ret["objective"])
            push!(dual_variables, Dict(
                name => JuMP.shadow_price(
                    JuMP.FixRef(_incoming_state(problem.second, name))
                ) for name in problem.state_variables
            ))
        end
        deterministic_bound = JuMP.objective_value(problem.first)
        stat_bound = ret_first["objective"] +
            sum(p * o for (p, o) in zip(probabilities, objectives))
        is_min = JuMP.objective_sense(problem.first) == JuMP.MOI.MIN_SENSE
        gap = abs(deterministic_bound - stat_bound)
        Printf.@printf(
            "%9d | % 5.4e | % 5.4e | %4.3e\n",
            iter,
            is_min ? deterministic_bound : stat_bound,
            is_min ? stat_bound : deterministic_bound,
            gap,
        )
        if gap < 1e-6
            println("Terminating training: convergence")
            return
        end
        _add_benders_optimality_cut(
            problem, x, probabilities, objectives, dual_variables
        )
    end
    println("Terminating training: iteration limit")
    return
end

"""
    evaluate(
        problem::TwoStageProblem;
        scenarios = problem.test_scenarios,
    )

Evaluate the policy after training `problem` on `scenarios`. By default, these
are the `test_scenarios` contained in the StochOptFormat file, but you can pass
a different set if necessary.
"""
function evaluate(
    problem::TwoStageProblem;
    scenarios = problem.test_scenarios,
    filename::Union{Nothing, String} = nothing
)
    solutions = Vector{Dict{String, Any}}[]
    for scenario in scenarios
        @assert length(scenario) == 2
        first_sol = _solve_first_stage(problem)
        incoming_state = Dict(
            name => first_sol["primal"][s["out"]]
            for (name, s) in problem.second.ext[:state_variables]
        )
        second_sol = _solve_second_stage(
            problem,
            incoming_state,
            convert(Dict{String, Float64}, scenario[2]["support"]),
        )
        push!(solutions, [first_sol, second_sol])
    end
    solution = Dict(
        "problem_sha256_checksum" => problem.sha256,
        "scenarios" => solutions,
    )
    if filename !== nothing
        open(filename, "w") do io
            write(io, JSON.json(solution))
        end
    end
    return solution
end

export
    TwoStageProblem,
    train,
    evaluate

end # module TwoStageBenders

if endswith(@__FILE__, PROGRAM_FILE)
    TSSP = TwoStageBenders
    @assert length(ARGS) == 1
    filename = ARGS[1]
    problem = TSSP.TwoStageProblem(filename)
    ret = TSSP.train(problem; iteration_limit = 20)
    solutions = TSSP.evaluate(problem)
    if endswith(filename, "news_vendor.sof.json")
        # Check solutions
        @assert solutions[1][1]["objective"] ≈ -10
        @assert solutions[1][2]["objective"] ≈ 15
        @assert solutions[2][2]["objective"] ≈ 15
        @assert solutions[3][2]["objective"] ≈ 13.5
    end
end
