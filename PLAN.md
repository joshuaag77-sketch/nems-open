- 2026-11-14 merged integration (d1a3072): whole-model 2-cycle reference run, 145 min, 23/24 years converged, most gaps within 3%; misses coal gen 2040-45 and Henry Hub 2045.
- 2026-11-14 merged lfmm-gams (2b5904c): EIA's real LFMM (GAMS, HiGHS in WSL) solves 2010-2035 optimal on cb2026 with FCRL=1. 2035 prices vs cb2026: diesel -0.1%, jet +1.1%, resid -1.9%, gasoline -13.3% (open). Not yet coupled: run(lfmm='gams') next.

## Product plan (2026-11-14, agreed with Josh)
1. Finish the engine: electricity capacity LP matched to the AIMMS oracle, coal generation 2040-45 fixed. Only active lane: electricity.
2. Run ~30 precomputed full-model scenarios (AI boom, LNG wave, both, carbon price, low gas resource, EV cases) for the showroom.
3. Showroom page on joshagarwal.com/energy (static, precomputed; ZIP to region; animated story; no live solves). Featured card on the front page. Needs Josh's explicit OK to publish.
4. Blog post (BLOG-NOTES.md) links to the tool.
Later: "request a custom scenario" form (Josh runs it; non-commercial while AIMMS/GAMS licenses are academic/free). Paid runs need the Python HiGHS rebuilds to fully replace AIMMS and GAMS. Workbench (all assumptions editable, regional split of data center load explicit) only once someone asks to pay. Mockup: Grid Sandbox artifact. Critic findings: single plants are below NEMS noise; sell build-outs and policies; prove deltas by reproducing EIA's AEO side cases.
