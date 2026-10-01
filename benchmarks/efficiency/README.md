# Efficiency Benchmark 1

This is a measurement instrument, not a product demo. It compares a fresh
supervisor session working directly against a synthetic Git repository with a
fresh supervisor session using the bounded Deputy Agents/Workers interfaces.
The expected answer is fixed, grading is deterministic, and an unfavorable
Deputy result is valid. Correctness and protocol compliance precede efficiency.

## Metrics and limits

Supervisor input/output usage, supervisor active context, delegated usage,
total inference, interaction counts, and wall time are separate measures.
Cached input accounting and active-context occupancy are not the same metric.
Missing authoritative token/context telemetry is reported as unmeasured rather
than estimated. Do not estimate occupancy from bytes, characters, cumulative
API token totals, or a tokenizer guess. No percentages are meaningful from
fixture-only or smoke runs.

The Codex task interface does not expose authoritative per-session active
context, context-window, compaction, or complete supervisor usage events to
this local harness. Those fields remain null until an approved first-party
telemetry source is wired in. Child token usage is likewise unmeasured unless
complete authoritative OpenCode usage events are captured locally.

## Cases

* E1: exact file existence, byte length, and SHA-256; one bounded Workers job
  in DEPUTY.
* E2: clean Git state and diff check; one Workers job in DEPUTY.
* E3: two synthetic JUnit XML reports with pass, skip, failure, error, and
  fixed duration; the grader uses its own standard-library XML parser.
* E4: authority architecture, evidence paths checked against assertion-specific
  fixture allowlists; Agents only in DEPUTY.
* E5: source selection through provider invocation ordering, checked against
  the fixture implementation; Agents only in DEPUTY.
* E6: two-stage mixed evidence and decision task. Workers establish repo/file/
  hash facts, Agents investigate architecture, and the supervisor makes the
  final decision in the same session after the decision boundary.

Prompts in `cases/` are versioned benchmark inputs. Any change requires a
benchmark version bump and invalidates earlier measurements for the changed
version. Graders do not use an LLM and compare exact typed values. E4 evidence
must be an actually present path in the corresponding assertion allowlist.

## Synthetic fixture and isolation

The committed fixture contains only synthetic text and source. The harness
copies it into a caller-selected *local test output directory*, creates the two
JUnit reports at runtime under ignored `app/build/`, initializes a deterministic
Git repository with fixed branch, identity, and commit timestamp, and confirms
the repository is clean. It never imports the production Workers execution
engine. E3 output is ignored by Git, so E2 starts clean.

DIRECT must run in a clean Codex context with ordinary access to the generated
target repository and no Deputy MCP servers. DEPUTY must run in a separate
clean context with only Deputy MCP access; use a separate empty/minimal client
workspace and server-owner configuration pointing Agents/Workers to the
generated target. Do not expose or mount the target in the DEPUTY client
workspace. Do not edit production MCP registrations for a benchmark run.
Existing environment variables `DEPUTYAGENTS_DEPUTY_SHELL_ROOT` and
`DEPUTYWORKERS_DEPUTY_SHELL_ROOT` are server-owned configuration; no benchmark
tool accepts a path or changes server configuration. The current live server
registrations are not automatically rebound by this harness. If an isolated
server-owned MCP instance cannot be safely prepared, mark those live smokes
BLOCKED rather than using the production Deputy Shell root.

Protocol records must truthfully report direct target access and subsystem
usage. `protocol-check` rejects DIRECT MCP use, DEPUTY target access, and wrong
Agents/Workers participation. This is a mechanical record validator, not proof
of operating-system isolation; the operator must enforce separate client
workspaces and MCP inventories.

## Reproduction

From the repository root (Python standard library only):

```powershell
python benchmarks/efficiency/harness/benchmark.py prepare --root "$env:TEMP\deputy-efficiency-fixture"
python benchmarks/efficiency/harness/benchmark.py arm-plan --arm DIRECT --root "$env:TEMP\deputy-efficiency-fixture"
python benchmarks/efficiency/harness/benchmark.py arm-plan --arm DEPUTY --root "$env:TEMP\deputy-efficiency-fixture" --client-root "$env:TEMP\deputy-efficiency-client"
python benchmarks/efficiency/harness/benchmark.py expected --case E1 --root "$env:TEMP\deputy-efficiency-fixture"
python -m unittest discover -s benchmarks/efficiency/tests -q
```

For an observation, save the exact model JSON answer as a local file and invoke
`grade --case E1 --root <fixture> --answer <answer.json>`. Prepare one fresh
fixture per run; do not reuse conversational history between runs. Use
`run-template` to create the bounded record shape, fill only observed telemetry,
then use `protocol-check` before setting a result to PASS. Keep raw transcripts,
local telemetry and run JSON under the ignored `evidence/` directory. Never
commit raw results. Public summaries must remove host paths and identities.

The full campaign is designed for 6 cases × 2 arms × 5 repetitions. Its
deterministic `schedule` command alternates arms for each case/repetition and
rotates case order to reduce time-order bias. Phase 11A does not run that
campaign. Smoke runs validate only the mechanics and must not be reported as
efficiency results. Failed scheduled runs remain in the denominator and are
reported rather than rerun until they pass.

## Telemetry and aggregation

`schemas/run.schema.json` defines the machine-readable record. Token fields are
null when missing. The harness does not infer active context or compaction from
token billing fields. Total inference tokens are produced only when supervisor
total and delegated input/output totals are measured; cache and reasoning
subtotals are not added a second time. `aggregate` reports quality, token/context
summaries when measurable, interaction counts, and latency while retaining
blocked/protocol-violation counts. It explicitly labels unmeasured reductions.

The grader independently computes E1 file facts, E2 Git state, and E3 XML
totals. E4 validates semantic values and allowlisted evidence paths. E5 checks
the expected ordered pipeline and caller pinning facts. E6 stage A verifies
repository/proposal evidence; stage B checks the final decision and sorted
violations. There is no subjective LLM judge.

## Phase 11 result

Phase 11 is complete. The corrected control-tower design reduced the preserved
Workers E1-E3 Deputy campaign from 2,132,559 to 1,023,874 supervisor tokens
(51.99%) and from 39 to 22 model-visible MCP calls. On valid same-repetition
pairs, E1-E5 used 1,409,301 DIRECT versus 1,341,493 DEPUTY supervisor tokens
(DEPUTY -4.81%). Adding the two valid E6 closure pairs yields 1,889,728 DIRECT
versus 1,871,932 DEPUTY (-0.94%); E6 itself was +10.41% for DEPUTY.

These are supervisor-token results only. Active context/compaction telemetry and
child-agent token usage remained unmeasured, so the campaign does not establish
total-inference-token savings. The results also show a workload break-even:
small deterministic facts can cost more through Deputy, while sufficiently
compressive deterministic work (E3) can save substantially. Future routing work
should refuse or redirect below-break-even delegation without weakening the
server-owned authority boundary.

Known reliability limitation: Agents can correctly report insufficient evidence
when authoritative material is excluded by the positive source policy. Phase 11
left that privacy boundary unchanged rather than broadening source exposure to
force benchmark passes.

The frozen Phase 11F runner completed all ten slots but its final aggregation
hit a post-run self-reference bug. `harness/phase11_finalize.py` is the
post-campaign repair path: it reads preserved `result.json` records only and
reconstructs the final disposition without rerunning inference or modifying
frozen inputs. The historical frozen runner bytes remain preserved unchanged.

## Safety and interpretation

Fixture operations are synthetic. No real Gradle, Git mutation, ADB, device,
destructive capability, provider request, or production MCP call is part of
unit tests. The synthetic Git repository is initialized by benchmark-owned
fixture code; the DIRECT task may inspect it read-only. The benchmark does not
change Agents contracts, production MCP tools, or the 22-operation Workers
registry. Efficiency results are valid only for PASS runs that also pass the
arm protocol checks. Interaction reduction is not token reduction.
