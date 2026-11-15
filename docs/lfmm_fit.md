# LFMM stand-in fit

Written by `python -m nems_open.lfmm.fit`. See [lfmm_plan.md](lfmm_plan.md) for the model.

## Coefficients

Prices: dP = dBrent/heat + a * P0 * dlog Q_own (US, 1987 $/MMBtu). Crude passes through dollar for dollar per barrel (set); a is fitted on what is left, kept at zero or above. R2 is of that remainder.

| Product | a (own demand) | a before the floor | R2 |
|---|---|---|---|
| Gasoline | 0.57 | 0.57 | 0.54 |
| Diesel | 0.00 | -0.14 | 0.16 |
| Jet fuel | 0.22 | 0.22 | 0.11 |
| Residual | 0.48 | 0.48 | 0.27 |

Refinery fuel.

| Equation | Coefficient | R2 |
|---|---|---|
| dlog total refinery energy = e * dlog liquids demand | 0.51 | 0.73 |
| dlog refinery electricity = e * dlog liquids demand | 1.04 | 0.56 |
| dlog gas share of refinery fuel = e * dlog(gas price to industry / Brent) | -0.98 | 0.68 |

## Held out (leave one case out)

Largest US error 2027-2050, percent, each case predicted from its own end-use demand, Brent and gas price.

| | hm2026 | lm2026 | higheldmd | highogs | lowogs | highztc | lowztc | altelec | electrnp |
|---|---|---|---|---|---|---|---|---|---|
| Gasoline | 3.8 | 2.1 | 0.6 | 5.9 | 15.3 | 0.3 | 0.5 | 0.8 | 18.7 |
| Diesel | 2.1 | 3.7 | 0.3 | 3.6 | 3.6 | 0.3 | 0.6 | 0.6 | 13.0 |
| Jet fuel | 2.3 | 2.1 | 0.3 | 8.8 | 9.5 | 0.4 | 0.7 | 0.9 | 8.0 |
| Residual | 5.8 | 3.4 | 0.5 | 2.2 | 5.5 | 0.8 | 0.8 | 1.0 | 5.5 |
| Refinery petroleum | 1.6 | 1.7 | 1.7 | 12.7 | 25.4 | 2.0 | 2.7 | 1.9 | 7.0 |
| Refinery natural gas | 10.1 | 9.1 | 3.5 | 59.3 | 216.6 | 5.1 | 7.7 | 4.5 | 19.0 |
| Refinery electricity | 6.3 | 3.1 | 0.6 | 28.3 | 6.5 | 1.3 | 1.3 | 0.9 | 7.6 |
| Refinery energy, total | 2.7 | 2.5 | 0.3 | 7.0 | 2.7 | 0.4 | 0.5 | 0.5 | 9.9 |

## In sample

Largest US error 2027-2050, percent, each case predicted from its own end-use demand, Brent and gas price.

| | hm2026 | lm2026 | higheldmd | highogs | lowogs | highztc | lowztc | altelec | electrnp |
|---|---|---|---|---|---|---|---|---|---|
| Gasoline | 3.8 | 2.1 | 0.6 | 5.9 | 15.3 | 0.3 | 0.5 | 0.8 | 3.5 |
| Diesel | 2.1 | 3.7 | 0.3 | 3.6 | 3.6 | 0.3 | 0.6 | 0.6 | 6.5 |
| Jet fuel | 1.4 | 2.0 | 0.3 | 8.8 | 9.5 | 0.4 | 0.7 | 0.9 | 8.0 |
| Residual | 4.8 | 2.6 | 0.5 | 2.2 | 3.3 | 0.8 | 0.8 | 1.0 | 5.4 |
| Refinery petroleum | 1.6 | 1.8 | 1.7 | 10.4 | 9.7 | 2.0 | 2.7 | 1.9 | 5.8 |
| Refinery natural gas | 10.0 | 9.1 | 3.5 | 53.5 | 44.6 | 5.1 | 7.6 | 4.5 | 11.7 |
| Refinery electricity | 6.0 | 3.1 | 0.6 | 28.2 | 6.5 | 1.3 | 1.3 | 0.9 | 7.5 |
| Refinery energy, total | 2.6 | 2.4 | 0.3 | 7.0 | 2.6 | 0.4 | 0.5 | 0.5 | 3.0 |
