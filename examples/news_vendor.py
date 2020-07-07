# A simple example reading a StochOptFormat file and solving it via Benders
# decomposition.
#
# The code is demonstration only, and does not contain robust checks or many
# nice error messages, preferring to throw assertion errors.

import json
import math
from pulp import *

def mathoptformat_to_pulp(node):
    sp = node['subproblem']
    # Create the problem
    sense = LpMaximize if sp['objective']['sense'] == 'max' else LpMinimize
    prob = LpProblem(node['name'], sense)
    # Initialize the variables
    vars = {}
    for x in sp['variables']:
        vars[x['name']] = LpVariable(x['name'])
    # Add the objective function
    obj = sp['objective']['function']
    if obj['head'] == 'SingleVariable':
        prob += vars[obj['variable']]
    elif obj['head'] == 'ScalarAffineFunction':
        prob += lpSum(
            term['coefficient'] * vars[term['variable']] for term in obj['terms']
        ) + obj['constant']
    else:
        raise(Exception('Unsupported objective: ' + str(obj)))
    # Add the constraints
    for c in sp['constraints']:
        f, s = c['function'], c['set']
        if f['head'] == 'SingleVariable':
            x = f['variable']
            if s['head'] == 'GreaterThan':
                vars[x].lowBound = s['lower']
            elif s['head'] == 'LessThan':
                vars[x].upBound = s['upper']
            elif s['head'] == 'EqualTo':
                vars[x].lowBound = s['value']
                vars[x].upBound = s['value']
            elif s['head'] == 'Interval':
                vars[x].lowBound = s['lower']
                vars[x].upBound = s['upper']
            else:
                raise(Exception('Unsupported set: ' + str(s)))
        elif f['head'] == 'ScalarAffineFunction':
            lhs = lpSum(
                term['coefficient'] * vars[term['variable']] for term in f['terms']
            ) + f['constant']
            if s['head'] == 'GreaterThan':
                prob += lhs >= s['lower']
            elif s['head'] == 'LessThan':
                prob += lhs <= s['upper']
            elif s['head'] == 'EqualTo':
                prob += lhs == s['value']
            elif s['head'] == 'Interval':
                prob += lhs <= s['upper']
                prob += lhs >= s['lower']
            else:
                raise(Exception('Unsupported set: ' + str(s)))
        else:
            raise(Exception('Unsupported function: ' + str(f)))
    # Add the constraints
    noise_terms = []
    if 'noise_terms' in node:
        noise_terms = node['noise_terms']
    return {
        'prob': prob,
        'vars': vars,
        'states': node['states'],
        'noise_term': noise_terms,
    }

def solve_second_stage(node, state, noise):
    for s in node['states']:
        v = node['vars'][s['in']]
        v.lowBound = state[s['name']]
        v.upBound = state[s['name']]
    for w in noise:
        p = node['vars'][w['parameter']]
        p.lowBound = w['value']
        p.upBound = w['value']
    node['prob'].solve()
    return {
        'objective': value(node['prob'].objective),
        'pi': {
            s['name']: node['vars'][s['in']].dj
            for s in node['states']
        }
    }

def solve_first_stage(node):
    node['prob'].solve()
    return {s['name']: node['vars'][s['out']].varValue for s in node['states']}

def add_cut(first_stage, x, ret):
    cut_term = lpSum(
        p * r['objective'] + p * lpSum(
            r['pi'][s['name']] * (first_stage['vars'][s['out']] - x[s['name']])
            for s in first_stage['states']
        )
        for (p, r) in ret
    )
    if first_stage['prob'].sense == -1:
        first_stage['prob'] += first_stage['theta'] <= cut_term
    else:
        first_stage['prob'] += first_stage['theta'] >= cut_term

def load_two_stage_problem(filename):
    with open(filename, 'r') as io:
        data = json.load(io)
    assert(data['version']['major'] == 0)
    assert(data['version']['minor'] == 1)
    assert(len(data['nodes']) == 2)
    assert(len(data['edges']) == 2)
    nodes = {}
    for node in data['nodes']:
        nodes[node['name']] = mathoptformat_to_pulp(node)
    first_stage, second_stage = None, None
    for edge in data['edges']:
        if edge['from'] == data['root']['name']:
            first_stage = nodes[edge['to']]
        else:
            second_stage = nodes[edge['to']]

    for s in data['root']['states']:
        for st in first_stage['states']:
            if s['name'] == st['name']:
                x = first_stage['vars'][st['in']]
                x.lowBound = s['initial_value']
                x.upBound = s['initial_value']
    first_stage['theta'] = LpVariable("theta", -10**6, 10**6)
    first_stage['prob'].objective += first_stage['theta']
    return first_stage, second_stage

def benders(first_stage, second_stage, iteration_limit = 20):
    bounds = []
    for iter in range(iteration_limit):
        x = solve_first_stage(first_stage)
        ret = [(
            noise['probability'],
            solve_second_stage(second_stage, x, noise['support'])
        ) for noise in second_stage['noise_term']]
        add_cut(first_stage, x, ret)
        det_bound = value(first_stage['prob'].objective)
        stat_bound = det_bound - first_stage['theta'].varValue + sum(
            p * value(r['objective']) for (p, r) in ret
        )
        bounds.append((det_bound, stat_bound))
        if abs(det_bound - stat_bound) < 1e-6:
            break
    return bounds

first_stage, second_stage = load_two_stage_problem('news_vendor.sof.json')
ret = benders(first_stage, second_stage)

# Check solution!
x = solve_first_stage(first_stage)
assert(x['x'] == 10)
