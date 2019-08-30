# StochOptFormat

This repository describes a file-format for stochastic optimziation problems
called _StochOptFormat_ with the file extension `.sof.json`.

Is is an extension of the [MathOptFormat (`.mof.json`) file format](https://github.com/odow/MathOptFormat)
for single-stage mathematical optimization problems.

_Note: this file format is in development. Things may change!_

## Standard form

The format is based on the _Policy Graph_ formulation of a multistage stochastic
program.

A pre-print of a paper describing the policy graph framework is available on
Optimization Online:
http://www.optimization-online.org/DB_HTML/2018/11/6914.html

**We highly recommend that you read the paper before looking at this format!**

## Implementations

### In progress

- Julia
    - The [SDDP.jl](https://github.com/odow/SDDP.jl) package supports reading
      and writing StochOptFormat files.

### Complete

- Nothing, yet :(
