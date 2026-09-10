# Assistant interaction design

Status: interactive design prototype. The application has not acquired an AI connection or experiment-planning backend through this artifact.

Open [assistant-design.html](assistant-design.html) in a browser. It is one standalone file with no packages, external assets, network calls, or laboratory-database writes. All changes live in page memory and reset on reload. Example bottle A and example vial B are fictional records for interaction review, not copied laboratory data. The displayed dates are examples.

## Screen and content boundaries

The experiment is the primary screen. The assistant is a narrow, dismissible panel attached to that experiment, with its name and target time as context. The screen contains inputs, concrete source information, editable steps, missing-input messages, and date conflicts. There is no explanatory welcome card, architectural narrative, product promise, or account of the user's design requirements.

The target operation, date, time window, genotype, and quantity sit above materials. The researcher can select a source and choose Parents or Offspring for L1, with an optional selected quantity that remains unknown when unfilled. A source's eclosion estimate is visible only when it matters to that selection. Source selection does not perform a transfer or imply using every adult. L3 can use the source culture or a proposed new culture.

Steps are an editable ordered list. Each has a name, dates/times, and any relevant user-authored timing or stage-acceptance requirement. L1 explicitly separates laying, egg collection, and Petri-dish incubation. Add, remove, and move controls work directly in the list; the target step cannot be removed. Missing requirements appear only after Check draft, with empty date/time fields marked instead of repeating an unscheduled sentence in every row. Actual time-order and future-operation weekday conflicts appear beside the relevant step as values change. Recorded source setup is historical, so it is exempt from future-operation weekday checks. The target step follows the target fields, and editing its times updates those fields.

The assistant has no fabricated conversation, generated answer, or simulated connection. Its prompt and Send button remain disabled. Connection settings accept separate cloud and local endpoint/model drafts; saving one does not enable the assistant. No credential input is presented because the artifact cannot securely store or use a credential. The production connection screen will add actual credential handling, connection validation, and a verified connection state when that integration exists.

## Walkthrough

1. Edit the target date, time, genotype, or quantity. The assistant's context and target step update immediately. Use Check draft to summarize current input and date conflicts.
2. Change Adults to Offspring. The source's estimated eclosion date appears. Select example vial B and move the target before September 30 to see a material-timing warning. A mismatched target genotype is also indicated.
3. Fill an egg-laying date/time window, then schedule egg collection. Add an incubation timing rule and L1 acceptance criteria in their own steps. These fields begin blank: the prototype does not invent a biological dissection interval or treat a hatch estimate as L1 readiness. Missing-input prose appears only after Check draft; per-step success prose remains hidden.
4. Add a step, rename it, enter a time, move it, and remove it. The list order is the prototype's dependency order. Schedule a step on a weekend, overlap it with its immediate predecessor, or place it after the target to see a specific conflict.
5. Choose L3 dissection. Its collection date initially matches the example target date, while collection time and collection-to-dissection interval are intentionally unfilled. For a new culture, calendar D5 derives the proposed setup date from the collection date: September 28 gives September 23. The day offset is editable. Using an existing source exposes its recorded setup date and identifies a mismatch with the chosen collection day. None of these dates assert an observed stage.
6. Switch back to L1. Each operation's step draft is retained in page memory. The common target and material fields remain shared.
7. Close and reopen the assistant. Open Connection, draft a cloud endpoint/model, switch to a local profile, and draft its values separately. Save draft updates the selected profile caption; the assistant remains disconnected and sending remains unavailable. Cancel dismisses unsaved profile edits. Reload clears both experiment edits and profile drafts.

## What the prototype checks

- Required target date/time, target genotype and quantity.
- Step names; laying-window fields; incubation and stage-acceptance requirements; L3 collection time and interval.
- Within-day start/end order, immediate predecessor order, operations after the target, and the selected weekday-only availability setting.
- Selected source versus target genotype and estimated offspring-eclosion date.
- L3 calendar-day relation for a proposed new culture or an existing source.

These are local form/date checks, not a scheduling solver, inventory allocation check, protocol interpretation, or biological validation. User-written interval and acceptance text is preserved but not interpreted. Full duration propagation, lay windows across dates, flexible work hours, equipment, selected-cohort anchors, quantity sufficiency, planned versus actual execution, and immutable plan versions belong in the production planner described in [experiment-planner-design.md](experiment-planner-design.md). The prototype deliberately does not expose an Apply plan action because there is no validated solver result or plan-application backend.

## Production assistant behavior

The assistant should receive the current draft and a versioned snapshot of relevant containers, batches, source relationships, observations, forecasts, and availability. Requested changes should arrive as structured proposals, each attached to a concrete step or material choice. A proposal needs a visible before/after change and, when useful, a directly accessible supporting record or reference. Accepting a proposal changes the draft; applying reviewed, validated work is a separate production operation.

If a necessary duration, stage criterion, material quantity, or source fact is missing, the assistant should ask for that specific input against the relevant step. It should not fill uncertainty with protocol-like prose or claim a source's target cross genotype proves selected offspring genotype. Reference links belong with claims or timing rules that use them, not as permanent instructional paragraphs in unrelated forms.

Cloud and local providers share this structured proposal contract and deterministic validation. The provider's endpoint/model/credential configuration belongs in Connection; transport and data-model details belong in documentation. A real connection failure should display a concise actionable error. Manual draft editing remains available when the model is unavailable.

## Implementation notes

The artifact uses static HTML/CSS and a small vanilla-JavaScript state model. User text is rendered through input values or `textContent`, never inserted as HTML. Content Security Policy disables network connections, forms cannot navigate, and the page has no fetch or storage calls. Controls have native labels or accessible names, visible keyboard focus, and a live region for structural actions. The assistant becomes a dismissible drawer on smaller screens and begins closed there.

Production UI copy should move into the existing English message catalog, with the established locale-registration interface. The prototype has a small message map for repeated validation states but is not a complete localization implementation. Transgenesis is not represented; its later workflow will be authored by the researcher.

## Review performed

The standalone script passed syntax checking. A visible-browser walkthrough checked the initial L1 canvas, switching to L3, D5 setup-date recalculation, a collection date beyond the target with no hour entered, on-demand missing-field feedback, adding/renaming/reordering/removing a custom step, closing/reopening the assistant, and separate cloud/local profile drafts. Saving a connection draft left sending disabled. Reload reset the sample state. The prototype was visually inspected on desktop; smaller-screen CSS has not been tested on a physical mobile device.
