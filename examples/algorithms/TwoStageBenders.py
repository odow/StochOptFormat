# TwoStageBenders.py
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
#   python TwoStageBenders.py [problem]
#   python TwoStageBenders.py ../problems/newsvendor.sof.json
#
# Notes
#   You need to install python, and have the following packages installed:
#       jsonschema, and pulp.

import json
import jsonschema
import math
from pulp import *

class TwoStageProblem:

    def __init__(self, filename, validate = True):
        with open(filename, 'r') as io:
            self.data = json.load(io)
        if validate:
            self._validate_stochoptformat()
        first, second = self._get_stage_names()
        self.first = self._mathoptformat_to_pulp(first)
        self.second = self._mathoptformat_to_pulp(second)
        self._initialize_first_stage(first)

    def train(self, iteration_limit):
        print('Iteration | Lower Bound | Upper Bound | Gap (abs)')
        for iter in range(iteration_limit):
            ret_first = self._solve_first_stage()
            probabilities = []
            objectives = []
            dual_variables = []
            x = {
                name: ret_first['primal'][s['out']]
                for (name, s) in self.second['state_variables'].items()
            }
            for realization in self.second['realizations']:
                ret = self._solve_second_stage(x, realization['support'])
                probabilities.append(realization['probability'])
                objectives.append(ret['objective'])
                dual_variables.append({
                    name: self._incoming_state(self.second, name).dj
                    for name in self.second['state_variables']
                })
            deterministic_bound = value(self.first['subproblem'].objective)
            stat_bound = ret_first['objective'] + sum(
                p * o for (p, o) in zip(probabilities, objectives)
            )
            is_min = self.first['subproblem'].sense == 1
            gap = abs(deterministic_bound - stat_bound)
            print(
                '%9d | % 5.4e | % 5.4e | %4.3e' % (
                    iter + 1,
                    deterministic_bound if is_min else stat_bound,
                    stat_bound if is_min else deterministic_bound,
                    gap
                )
            )
            if abs(deterministic_bound - stat_bound) < 1e-6:
                print('Terminating training: convergence')
                return
            self._add_benders_optimality_cut(
                x, probabilities, objectives, dual_variables
            )
        print('Terminating training: iteration limit')
        return

    def evaluate(self, scenarios = None):
        if scenarios is None:
            scenarios = self.data['test_scenarios']
        solutions = []
        for scenario in scenarios:
            assert(len(scenario) == 2)
            first_sol = self._solve_first_stage()
            incoming_state = {
                name: first_sol['primal'][s['out']]
                for (name, s) in self.second['state_variables'].items()
            }
            second_sol = self._solve_second_stage(
                incoming_state, scenario[1]['support']
            )
            solutions.append([first_sol, second_sol])
        return solutions

    def _validate_stochoptformat(self):
        with open('../sof.schema.json', 'r') as io:
            schema = json.load(io)
        jsonschema.validate(instance = self.data, schema = schema)

    def _get_stage_names(self):
        data = self.data
        assert(len(data['nodes']) == 2)
        assert(len(data['edges']) == 2)
        edge_1, edge_2 = data['edges']
        assert(edge_1['probability'] == 1.0)
        assert(edge_2['probability'] == 1.0)
        first, second = '', ''
        if edge_1['from'] == data['root']['name']:
            assert(edge_2['from'] != data['root']['name'])
            assert(edge_1['to'] == edge_2['from'])
            return edge_1['to'], edge_2['to']
        else:
            assert(edge_2['from'] == data['root']['name'])
            assert(edge_2['to'] == edge_1['from'])
            return edge_2['to'], edge_1['to']

    def _mathoptformat_to_pulp(self, name):
        node = self.data['nodes'][name]
        sp = node['subproblem']
        # Create the problem
        sense = LpMaximize if sp['objective']['sense'] == 'max' else LpMinimize
        prob = LpProblem(name, sense)
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
        return {
            'subproblem': prob,
            'vars': vars,
            'state_variables': node['state_variables'],
            'realizations': node['realizations'],
        }

    def _incoming_state(self, sp, name):
        return sp['vars'][sp['state_variables'][name]['in']]

    def _outgoing_state(self, sp, name):
        return sp['vars'][sp['state_variables'][name]['out']]

    def _initialize_first_stage(self, name):
        for (name, init) in self.data['root']['state_variables'].items():
            x = self.first['vars'][self.first['state_variables'][name]['in']]
            x.lowBound = init['initial_value']
            x.upBound = init['initial_value']
        self.first['theta'] = LpVariable('theta', -10**6, 10**6)
        self.first['subproblem'].objective += self.first['theta']
        return

    def _solve_first_stage(self):
        solver = coin_api.PULP_CBC_CMD(msg = 0)
        self.first['subproblem'].solve(solver)
        return {
            'objective': value(self.first['subproblem'].objective) -  self.first['theta'].varValue,
            'primal': {v.name: v.varValue for v in self.first['subproblem'].variables()}
        }

    def _solve_second_stage(self, state_variables, random_variables):
        node = self.second
        for (name, val) in state_variables.items():
            v = self._incoming_state(node, name)
            v.lowBound = state_variables[name]
            v.upBound = state_variables[name]
        for (name, w) in random_variables.items():
            p = node['vars'][name]
            p.lowBound = w
            p.upBound = w
        solver = coin_api.PULP_CBC_CMD(msg = 0)
        node['subproblem'].solve(solver)
        return {
            'objective': value(node['subproblem'].objective),
            'primal': {v.name: v.varValue for v in self.first['subproblem'].variables()}
        }

    def _add_benders_optimality_cut(
        self, state_variables, probabilities, objectives, dual_variables
    ):
        cut_term = lpSum(
            p * (
                o + lpSum(
                    d[name] * (self._outgoing_state(self.first, name) - x_val)
                    for (name, x_val) in state_variables.items()
                )
            )
            for (p, o, d) in zip(probabilities, objectives, dual_variables)
        )
        if self.first['subproblem'].sense == -1:
            self.first['subproblem'] += self.first['theta'] <= cut_term
        else:
            self.first['subproblem'] += self.first['theta'] >= cut_term

if __name__ == "__main__":
    import sys
    assert(len(sys.argv) == 2)
    filename = sys.argv[1]
    problem = TwoStageProblem(filename)
    problem.train(iteration_limit = 20)
    solutions = problem.evaluate()
    if filename.endswith('news_vendor.sof.json'):
        # Check solutions
        assert(solutions[0][0]['objective'] == -10)
        assert(solutions[0][1]['objective'] == 15)
        assert(solutions[1][1]['objective'] == 15)
        assert(solutions[2][1]['objective'] == 13.5)

