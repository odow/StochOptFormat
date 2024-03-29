# Copyright (c) 2020: Oscar Dowson, Joaquim Dias Garcia, and contributors
#
# Use of this source code is governed by an MIT-style license that can be found
# in the LICENSE.md file or at https://opensource.org/licenses/MIT.

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
#   python TwoStageBenders.py ../problems/news_vendor.sof.json
#
# Notes
#   You need to install python, and have the following packages installed:
#       hashlib, jsonschema, and pulp.

import hashlib
import json
import jsonschema
import math
import os
import pulp

class TwoStageProblem:
    def __init__(self, filename, validate = True):
        with open(filename, 'rb') as io:
            self.sha256 = hashlib.sha256(io.read()).hexdigest()
        with open(filename, 'r') as io:
            self.data = json.load(io)
        version_dir = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            'schemas',
        )
        self.schema = os.path.join(version_dir, 'sof-1.schema.json')
        self.result_schema = os.path.join(version_dir, 'sof-result.schema.json')
        if validate:
            self._validate_stochoptformat()
        first, second = self._get_stage_names()
        self.first = self._mathoptformat_to_pulp(first)
        self.second = self._mathoptformat_to_pulp(second)
        self._initialize_first_stage(first)
        return

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
            for realization in self.second.get('realizations', []):
                ret = self._solve_second_stage(x, realization['support'])
                probabilities.append(realization['probability'])
                objectives.append(ret['objective'])
                dual_variables.append({
                    name: self._incoming_state(self.second, name).dj
                    for name in self.second['state_variables']
                })
            deterministic_bound = pulp.value(self.first['subproblem'].objective)
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

    def evaluate(self, scenarios = None, filename = None):
        if scenarios is None:
            scenarios = self.data['validation_scenarios']
        solutions = []
        for scenario in scenarios:
            assert len(scenario) == 2
            first_sol = self._solve_first_stage()
            incoming_state = {
                name: first_sol['primal'][s['out']]
                for (name, s) in self.second['state_variables'].items()
            }
            second_sol = self._solve_second_stage(
                incoming_state, scenario[1].get('support', {})
            )
            solutions.append([first_sol, second_sol])
        solution = {
            'problem_sha256_checksum': self.sha256,
            'scenarios': solutions
        }
        with open(self.result_schema, 'r') as io:
            schema = json.load(io)
        jsonschema.validate(instance = solution, schema = schema)
        if filename is not None:
            with open(filename, 'w') as io:
                json.dump(solution, io)
        return solution

    def _validate_stochoptformat(self):
        with open(self.schema, 'r') as io:
            schema = json.load(io)
        return jsonschema.validate(instance = self.data, schema = schema)

    def _get_stage_names(self):
        assert len(self.data['nodes']) == 2
        assert len(self.data['root']['successors']) == 1
        first_node, probability = \
            next(iter(self.data['root']['successors'].items()))
        assert probability == 1.0
        successors = self.data['nodes'][first_node]['successors']
        assert len(successors) == 1
        second_node, probability = next(iter(successors.items()))
        assert probability == 1.0
        assert len(self.data['nodes'][second_node].get('successors', [])) == 0
        return first_node, second_node

    def _mathoptformat_to_pulp(self, name):
        node = self.data['nodes'][name]
        subproblem = self.data['subproblems'][node['subproblem']]
        sp = subproblem['subproblem']
        # Create the problem
        if sp['objective']['sense'] == 'max':
            prob = pulp.LpProblem(name, pulp.LpMaximize)
        else:
            prob = pulp.LpProblem(name, pulp.LpMinimize)        
        # Initialize the variables
        vars = {x['name']: pulp.LpVariable(x['name']) for x in sp['variables']}
        # Add the objective function
        obj = sp['objective']['function']
        if obj['type'] == 'Variable':
            prob += vars[obj['name']]
        elif obj['type'] == 'ScalarAffineFunction':
            prob += obj['constant'] + pulp.lpSum(
                term['coefficient'] * vars[term['variable']] for 
                term in obj['terms']
            )
        else:
            raise(Exception('Unsupported objective: ' + str(obj)))
        # Add the constraints
        for c in sp['constraints']:
            f, s = c['function'], c['set']
            if f['type'] == 'Variable':
                x = f['name']
                if s['type'] == 'GreaterThan':
                    vars[x].lowBound = s['lower']
                elif s['type'] == 'LessThan':
                    vars[x].upBound = s['upper']
                elif s['type'] == 'EqualTo':
                    vars[x].lowBound = s['value']
                    vars[x].upBound = s['value']
                elif s['type'] == 'Interval':
                    vars[x].lowBound = s['lower']
                    vars[x].upBound = s['upper']
                else:
                    raise(Exception('Unsupported set: ' + str(s)))
            elif f['type'] == 'ScalarAffineFunction':
                lhs = f['constant'] + pulp.lpSum(
                    term['coefficient'] * vars[term['variable']] for
                    term in f['terms']
                )
                if s['type'] == 'GreaterThan':
                    prob += lhs >= s['lower']
                elif s['type'] == 'LessThan':
                    prob += lhs <= s['upper']
                elif s['type'] == 'EqualTo':
                    prob += lhs == s['value']
                elif s['type'] == 'Interval':
                    prob += lhs <= s['upper']
                    prob += lhs >= s['lower']
                else:
                    raise(Exception('Unsupported set: ' + str(s)))
            else:
                raise(Exception('Unsupported function: ' + str(f)))
        return {
            'subproblem': prob,
            'vars': vars,
            'state_variables': subproblem['state_variables'],
            'realizations': node.get('realizations', []),
        }

    def _incoming_state(self, sp, name):
        return sp['vars'][sp['state_variables'][name]['in']]

    def _outgoing_state(self, sp, name):
        return sp['vars'][sp['state_variables'][name]['out']]

    def _initialize_first_stage(self, name):
        for (name, init) in self.data['root']['state_variables'].items():
            x = self.first['vars'][self.first['state_variables'][name]['in']]
            x.lowBound = init
            x.upBound = init
        self.first['theta'] = pulp.LpVariable('theta', -10**6, 10**6)
        self.first['subproblem'].objective += self.first['theta']
        return

    def _solve_first_stage(self):
        self.first['subproblem'].solve(pulp.coin_api.PULP_CBC_CMD(msg = 0))
        return {
            'objective': pulp.value(self.first['subproblem'].objective) -
                         self.first['theta'].varValue,
            'primal': {
                v.name: v.varValue for v in self.first['subproblem'].variables()
            }
        }

    def _solve_second_stage(self, state_variables, random_variables):
        for (name, val) in state_variables.items():
            v = self._incoming_state(self.second, name)
            v.lowBound = state_variables[name]
            v.upBound = state_variables[name]
        for (name, w) in random_variables.items():
            p = self.second['vars'][name]
            p.lowBound = w
            p.upBound = w
        solver = pulp.coin_api.PULP_CBC_CMD(msg = 0)
        self.second['subproblem'].solve(solver)
        return {
            'objective': pulp.value(self.second['subproblem'].objective),
            'primal': {
                v.name: v.varValue for v in self.first['subproblem'].variables()
            }
        }

    def _add_benders_optimality_cut(
        self, state_variables, probabilities, objectives, dual_variables
    ):
        cut_term = pulp.lpSum(
            p * o + p * pulp.lpSum(
                d[name] * (self._outgoing_state(self.first, name) - x_val)
                for (name, x_val) in state_variables.items()
            ) for (p, o, d) in zip(probabilities, objectives, dual_variables)
        )
        if self.first['subproblem'].sense == -1:
            self.first['subproblem'] += self.first['theta'] <= cut_term
        else:
            self.first['subproblem'] += self.first['theta'] >= cut_term
        return

if __name__ == '__main__':
    import sys
    assert len(sys.argv) == 2 
    filename = sys.argv[1]
    problem = TwoStageProblem(filename)
    problem.train(iteration_limit = 20)
    solutions = problem.evaluate(filename = 'sol_py.json')
    if filename.endswith('news_vendor.sof.json'):
        assert solutions['scenarios'][0][0]['objective'] == -10
        assert solutions['scenarios'][0][1]['objective'] == 15
        assert solutions['scenarios'][1][1]['objective'] == 15
        assert solutions['scenarios'][2][1]['objective'] == 13.5

