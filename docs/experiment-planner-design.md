# User-designed experiments and backward planning

Status: design proposal, not an implemented feature.

Scope confirmed September 10, 2026: prioritize first-instar (L1) and third-instar (L3) dissection planning. Transgenesis is a future project whose workflow will be designed by the researcher; no transgenesis steps or timings are specified here. Support switching between cloud and local AI providers through one application interface, connecting one provider first.

## Product contract

The researcher owns the experimental workflow. They can create, copy, remove, reorder, and connect steps; choose materials; define time ranges and conditions; and lock decisions. AI can translate a goal into a draft, identify missing decisions, search the available records, compare alternatives, and explain conflicts. A deterministic scheduling engine calculates and validates the times. A reviewed plan creates future work; actual operations remain separately recorded facts.

The existing application remains local-first and single-user. AI is optional. Workflow editing, deterministic scheduling, saved plans, and in-app reminders must remain usable when a model is disconnected.

## What exists and what is missing

Existing containers, source links, selected-parent/offspring provenance, timed egg batches, dish links, actual temperature history, activity, reminders, and availability provide a useful foundation. Current `Workflow` settings describe a container purpose; current `plans` describe a cooling interval. Neither represents an experiment spanning several containers with a target operation.

The current APIs deliberately require an active egg-laying container before creating an egg batch and a collected batch before linking a Petri dish. A future experiment therefore needs planned material outputs in its own draft graph. It must not bypass those checks or create fictitious eggs and physical dishes.

Other required additions:

- Preserve planned, estimated, and actual timestamps separately. Current container activation replaces its setup fields, so experiment plan versions must retain the original plan.
- Record hands-on duration separately from unattended incubation. The existing generic 15-minute availability check is insufficient for dissections and longer procedures.
- Express stage assessment as an explicit prerequisite when the researcher requires it. A forecast is not an observation.
- Represent quantities as unknown, estimated, or counted. Current notes and lineage do not prove that enough suitable adults, eggs, or larvae are available.
- Provide a consistent read-only planning snapshot with a revision, schema description, laboratory time zone, and generation time. `/api/state` currently reconciles reminders while reading and is not this interface.

## User-facing workflow

Add an **Experiments** area with **New experiment** and **Workflow library**.

1. **Target**: select the intended operation, genotype, stage/substage, desired quantity, target date/window, and expected hands-on duration. Unspecified quantity remains unknown. Clarify whether the target is an operation start, a whole work session, or a deadline.
2. **Workflow**: select a researcher-authored version or start from editable L1/L3 examples. Each step exposes its inputs, outputs, dependencies, time anchor, duration/wait range, and required observations. An ordered card editor can show dependencies before a full graphical editor is necessary.
3. **Materials**: link existing containers/batches or planned outputs. Parents and offspring are explicit selections; selecting material never means moving all adults. Source genotypes, target cross genotypes, and verified selected genotypes are different facts.
4. **Schedule**: calculate candidate timelines, highlight workday conflicts, and show missing inputs. Offer alternatives only within the researcher's permitted changes. Show the consequences of moving a target or changing a laying window.
5. **Review plan**: show the selected sources, assumptions, unresolved requirements, new reminders, and any existing planned work affected. **Apply plan** uses one atomic operation and preserves actual history.
6. **Execution**: record actual work and stage checks. Recalculate affected unfinished steps after delays or observations. Keep manually locked steps fixed and explain when they make the remaining target infeasible.

The **AI assistant** panel works on this same visible experiment. Its suggestions are editable draft changes, with the supporting records and protocol assumptions available beside them. It never silently replaces the researcher's workflow.

## Two initial planning examples

These are editable planning outlines based on the user's requested material paths, not complete laboratory protocols. Hands-on durations, adult suitability criteria, laying-window width, stage acceptance criteria, and optional preparatory steps are entered by the researcher.

| Target | Material and operation dependencies | Timing anchors |
| --- | --- | --- |
| L1 dissection | Source vial/bottle → select suitable adults → egg-laying container → timed egg batch → Petri dish incubation → assess L1 → dissection | Source availability, actual egg-laying interval, egg pickup, dish setup, stage assessment, target work window |
| L3 dissection | Existing suitable vial/bottle, or planned fresh culture → assess/select L3 larvae → collection → dissection | New culture D0 or existing culture history, provisional D5 collection date, collection-to-dissection lag, target work window |

For L1, reuse an already suitable egg-laying container, collected batch, or dish when the researcher chooses one. Backward planning starts from the most advanced usable material; it does not recreate every upstream step. If the source is offspring that have not emerged, retain source eclosion as an estimate and require actual selection/start before creating real downstream material. An unknown adult preparation interval remains unresolved rather than being assumed zero.

For L3, retain the user's current **calendar D5** preset. A target collection on September 28 maps to a proposed new culture setup date of September 23. This is a calendar relation, not a validated universal L3-age model and not a requirement to create a new culture if a suitable one already exists. If dissection follows collection after a delay, solve for the collection step from that dependency before deriving D0. More specific L3 staging and temperature-sensitive rules require a separately selected, documented protocol version.

## Time semantics and uncertainty

Every rule names its anchor: culture D0, laying start, laying end, observed hatch, actual collection, previous operation completion, or target date. It also names its clock: calendar dates, elapsed hours, or a protocol-specific developmental estimate. A container change never resets egg age. Moving a reminder changes the work plan, not a recorded biological event.

The current editable 24–30 h preset describes an estimated hatch envelope. For laying interval `[Lstart, Lend]` and hatch-age bounds `[Hmin, Hmax]`, that envelope is:

```text
earliest estimated hatch = Lstart + Hmin
latest estimated hatch  = Lend + Hmax
```

That interval alone cannot establish that selected larvae will be L1 throughout a requested dissection session. Planning also needs the researcher's acceptable stage/age criteria and an assessment step. It must not subtract 30 hours from dish setup or label an overlapping hatch interval as a confirmed L1-dissection window.

An optional conservative calculation could require `Lend + Hmax <= dissection_start` and `Lstart + earliest_L1_exit_age >= dissection_end`, using compatible, documented age anchors. Without a supported L1 exit bound, this test is unresolved. Even when model bounds fit, the result is conditional on those bounds and sufficient suitable larvae; actual assessment remains necessary. A protocol based on selecting newly hatched larvae uses the selected cohort's recorded hatch interval instead.

Time ranges represent supplied bounds or estimates, not statistical confidence intervals unless a calibrated model explicitly supplies that interpretation. Do not invent a success percentage. Return separate scheduling and biological-readiness states, for example **Schedule fits**, **Requires stage verification**, **Missing material count**, or **No feasible schedule**.

## Scheduling responsibilities

The solver receives a workflow version, target constraints, selected material, permitted alternatives, and a workspace snapshot. It should:

1. Validate the dependency graph, references, time units, and clock anchors. Reject cycles and unsupported operations.
2. Fix completed operations, historical observations, physical material already present, and user-locked work.
3. Propagate time ranges backward from the target and forward from actual upstream facts. A range of possible schedules is not automatically robust against every biological delay.
4. Check hands-on steps against laboratory availability for their full duration. Unattended incubation can span non-working hours when the selected protocol permits it. Detect overlapping work assigned to the same researcher; equipment reservations can be added when modeled.
5. Check material compatibility and existing allocations. Report unknown quantity, genotype selection, or suitability explicitly rather than assuming supply.
6. Rank feasible candidates using visible preferences: respect fixed targets, preserve existing commitments, minimize permitted temperature intervention, then reduce new containers and handling. The researcher can change these priorities.
7. When infeasible, return the conflicting steps/constraints and concrete alternatives. Do not quietly relax a fixed date or replace a user-defined procedure.

The first solver should use bounded interval propagation and search with a disclosed horizon/resolution. Claim feasibility and ranking within that search, not global optimality. Reuse existing temperature calculations only for rules that explicitly allow that model; hourly L1 work and the current calendar L3 preset do not inherit automatic cooling effects.

## Minimal data additions

Keep SQLite. The following are logical entities; initial payloads can follow the application's existing validated JSON approach, with relational IDs and foreign keys for references.

| Entity | Main fields |
| --- | --- |
| Workflow version | Stable ID/version, author, display name, steps/dependencies, material requirements, timing rules, applicability, references; immutable once used |
| Experiment | Goal, target window/meaning, time zone, workflow-version snapshot, status, revision, chosen inputs, unresolved facts |
| Experiment step | Stable ID, operation key, input/output links, planned/estimated/actual start/end, hands-on duration, wait bounds, conditions, observations, lock state, reminder link |
| Material link | Existing container/batch or planned output, source and destination step, Parents/Offspring if relevant, known/target/selected genotype, optional quantity and its evidence state, allocation notes |
| Plan version | Experiment revision, source snapshot fingerprint, proposed schedule, assumptions, solver version, changes from prior plan, applied status |
| Reference entry | User protocol or external source, title, identifier/URL, version, applicability, access/verification date, supported claims, local notes and attribution |

A planned output has a planning ID, not an assertion that physical material exists. Recording the real operation binds that output to the actual container or batch through the existing validated operations. Preserve the step and reminder identities during that binding so the container and experiment views show one task. Applying a plan twice must not create duplicate containers, batches, or reminders.

Material references must participate in permanent-deletion checks. A container used by an experiment cannot be removed without explicitly resolving those links. Cancelling an experiment cancels future work and releases planned allocations; it does not delete actual cultures or observations.

## What the AI can know

Give the model access to an explicit domain contract and typed retrieval, rather than expecting it to infer the whole database from free text.

- A workspace index summarizes containers, experiments, availability, and unresolved issues, with coverage information if any records were excluded.
- Detailed retrieval expands the chosen material's ancestors, descendants, egg batches, actual temperature history, observations, active commitments, pinned reminders, and relevant archived records.
- Every returned value identifies its basis: researcher-entered fact, observed measurement, lab preset, literature estimate, derived forecast, draft proposal, or unknown.
- The model sees the laboratory time zone and exact D0/egg-age semantics, plus the source IDs and version of every planning rule it invokes.
- Missing or truncated context is reported. Information found in notes can be proposed for structured entry but is not silently promoted to verified fact.

Suggested capabilities are `describe_domain`, `read_planning_snapshot`, `find_materials`, `get_workflow_version`, `find_references`, `propose_draft_changes`, `validate_plan`, and `solve_plan`. These names describe proposed application APIs, not tools already implemented. AI gets no arbitrary SQL or shell access. Retrieved documents and notes are evidence, not instructions that can change tool permissions or recorded facts.

At apply time, the backend checks the relevant source, calendar, workflow, and experiment revisions. A stale plan gets a fresh comparison before any changes are saved. Stable request keys and a transaction make repeated requests idempotent. Model text alone never marks an operation complete.

## Local reference library

Start with a small curated library of the researcher's own protocols, current lab presets, verified external references, and local observations. Record rule applicability, including genotype/background, temperature, staging criteria, and culture conditions where known. User-selected rules stay selected until explicitly changed; new literature or AI suggestions create proposed revisions.

SQLite metadata and text search are sufficient for this initial library. Semantic retrieval can be added if the collection grows, while time calculations and material checks remain structured. A downloaded ontology supplies consistent stage names and synonyms; it does not supply an automatically valid laboratory workflow.

Source verification should be visible. A source record distinguishes accessible content, abstract-only review, blocked retrieval, and locally verified material. Store a permitted excerpt or original summary with attribution, not an unrestricted copy of a paper. Re-check changed sources without silently rewriting saved experiments.

## Cloud and local AI

Use a provider-neutral backend interface with configurable provider type, endpoint, model, credentials reference, and capability checks. Both cloud and local adapters produce the same validated draft-change schema and invoke the same planner. A model without native structured output can supply a proposed object for validation; malformed or unsupported output must not execute.

In **AI settings**, expose named connection profiles with **Connection type**, **Endpoint**, **Model**, **Credential**, **Test connection**, and **Active connection**. Implement and verify one adapter first; display a second connection type as unavailable until its adapter is implemented. Saving a profile does not connect or submit experiment data. Testing a connection uses a minimal request without laboratory records. Changing the active profile applies to new requests; an in-flight request retains its original provider identity or can be cancelled. Workflow and experiment records remain provider-independent.

All settings, workflow-editor labels, and planner messages start in English and use translation keys. Domain identifiers, timing units, proposal schemas, and stored operation keys remain stable across languages. Researcher-authored protocols, genotypes, and notes retain their original text.

Model choice and credentials remain unconfigured at this design stage. Connect one user-selected provider after the workflow and planner are usable. Credentials belong in backend secret storage, not browser code, database exports, git, or prompts. Cloud requests use the relevant planning context under the user's chosen data scope; switching provider does not itself send historical data. A local-only setting must not silently fall back to a cloud endpoint.

Use request timeouts, cancellation, bounded context and response sizes, and a visible record of which model proposed a change. A provider failure leaves the draft intact. Neither an AI connection nor background model availability is required to execute a saved plan.

## Implementation order and acceptance

1. **User workflow and experiment model**: versioned definitions, target semantics, planned outputs, step timing anchors, source bindings, and draft editor. Accept when an L1 pipeline can be saved before eggs or dishes exist without fabricating physical records.
2. **Deterministic backward planning**: L1 and L3 examples, interval validation, availability, missing-input states, actual/locked anchors, and plan comparison. Accept when D0/egg-age distinctions, calendar D5, delayed laying, absent counts, contradictory constraints, and workday conflicts are covered by tests.
3. **Execution and replanning**: materialize real outputs on recorded operations, maintain one reminder per step, preserve history, and validate stale plans and deletion dependencies. Accept when time simulation and repeated apply/retry cannot activate planned material or duplicate tasks.
4. **AI and reference integration**: expose consistent read-only context, reference provenance, editable model proposals, then connect one provider behind the shared cloud/local interface. Accept when unsupported operations, invented IDs, missing facts, stale context, malformed output, and provider failure all leave records intact.
5. **Later researcher-authored workflows**: richer branching, repeated attempts, additional material/resource types, and transgenesis only after the researcher defines that workflow.

## Source checks for this proposal

- [FlyBase Developmental Ontology](https://github.com/FlyBase/drosophila-developmental-ontology): official repository and public README opened on September 10, 2026. It organizes Drosophila developmental stages and exposes versioned ontology files under CC BY 4.0. Proposed use: stage vocabulary and provenance; not a complete timing protocol.
- [Sun and Heckscher, 2016, Using Linear Agarose Channels to Study Drosophila Larval Crawling Behavior](https://app.jove.com/t/54892/using-linear-agarose-channels-to-study-drosophila-larval-crawling): publisher page and publicly returned preparation text opened on September 10, 2026; DOI 10.3791/54892. Its staging description distinguishes egg collections from age after hatching and notes temperature-dependent timelines. This supports separating timing anchors; it is not the user's L1 dissection protocol, and none of its quantities or preparation schedule are imported here.

Other searched publisher/ontology pages returned access challenges. They are not represented as verified full-text support for this proposal. The user's one-day virgin collection rule, current D5 larval preset, and editable egg-hatching estimate remain lab rules unless the researcher changes them.
