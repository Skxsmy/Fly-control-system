# Assistant and experiment-planner interaction

Status: the main application now includes an optional, connected, read-only assistant and AI connection settings. The editable experiment canvas remains a separate design prototype. A deterministic solver for researcher-authored experiment workflows and reviewed plan application are not implemented.

## Main application entry points

**Assistant** is a page in the main navigation. Opening it from a container preselects that container as workspace context. **Connection** and the unconfigured state's **Connect a model** lead to **Protocols & settings → AI connection**. Connection setup is part of the application; opening the standalone HTML prototype is not required.

The conversation shows the active model and connection type, message history, a composer, and the latest request's state. A separate context panel selects laboratory data. An optional target date and the **Plan L1 dissection** and **Plan L3 dissection** actions help begin a message. These buttons populate editable text; they do not generate a fake answer or create an experiment. When set, the target date is included explicitly in the outbound message and the displayed user message.

The interface keeps practical explanations at the point of use: which data will be sent, what saving a key means, why a selected record is unavailable, and how to correct a failed request. Design rationale, conversation history about the product, and engineering limitations remain in documentation. A response is labeled **Assistant suggestion**, without an Apply action that would imply a working experiment execution backend.

## Connect a cloud or local model

1. Open **Protocols & settings → AI connection**.
2. Select **Cloud API** or **Local model**. The implemented adapter uses the OpenAI-compatible Chat Completions format. Enter the server's base URL, including `/v1` when required, rather than the full `/chat/completions` route.
3. Enter the exact model ID exposed by that provider or local server. Cloud connections require HTTPS; local connections require localhost or a loopback address. Start a local server before testing it.
4. Supply a key when the server requires authentication. An empty replacement field preserves the saved key. **Remove saved key** explicitly schedules its removal on save. Changing the server origin drops a prior saved key unless a replacement is entered.
5. **Save connection** saves the visible profile without making a model request. **Save and test** saves it and requests a short response from that model, without sending laboratory records. A success result means that the tested endpoint/model returned text. Authentication, model, connection, and timeout failures show specific corrections.
6. Return to **Assistant** and send a message.

Cloud and local profiles have independent saved values. Switching profile controls preserves the other profile's unsaved fields in the open form; saving one profile does not silently save the hidden profile. A key typed or autofilled into the visible form is captured before switching controls. Key values are never returned by the settings API and are not persisted in browser storage. On Windows, saved credentials use user-bound DPAPI protection in a configuration file outside the laboratory database. They are excluded from database backups. Profile-specific environment keys are supported by the backend for deployments without Windows key storage; configuration details are in [README.md](../README.md).

Requests carry the connection revision that the user saw. If another tab or process changes the active connection before a chat or test request, the backend rejects it before contacting a model. Chat then reloads the connection, clears the prior transcript, and keeps the unsent message. It does not automatically resend to the changed provider.

## Workspace context and conversation

**Include workspace data** is enabled initially. The user can include all containers or select individual containers and their source ancestors. The snapshot also includes related temperature records, activity, reminders, egg batches, and cooling plans; laboratory settings, weekly availability, date exceptions, and general reminders supply scheduling context. Genotypes and notes are included, so the composer identifies cloud transmission when a cloud connection is active. A local connection sends requests to the configured local server and has no automatic cloud fallback.

The backend reads one consistent snapshot without reconciling or changing laboratory records. Labels and notes are passed as record data, not as instructions. The model receives explicit distinctions between physical operations and planned work, observed stages and estimates, parental genotypes and selected-genotype targets, and container D0 and egg-laying anchors. Unknown quantities, stages, or selection results are not supplied as fabricated facts.

Each response shows counts for the data actually included. Oversized snapshots produce a request error and require fewer selected containers or disabling workspace data; individual records are not silently truncated. Selecting a container includes its ancestors, rather than unrelated descendants or siblings. A missing selected container produces a correction message and can be cleared from the selection.

Changing the selected scope or turning workspace data on/off clears the existing conversation while preserving the unsent message. This prevents earlier record excerpts in model replies from leaking into a narrower data selection. Changing the active connection also starts a new conversation. **New conversation** clears the transcript without discarding an unsent message.

Conversation state is held only in page memory. Navigation within the app retains it; reloading or closing the browser tab loses it. It is not part of the SQLite database, backup, or browser storage. The next request contains at most 12 previous messages in complete user/assistant pairs, within a character budget. When older exchanges are omitted, the interface displays the number still sent. Individual replies are not silently shortened to fit history.

**Cancel request** stops the UI request and retains the draft. A failure also retains the draft for editing and retry. Sending displays a pending message and loading state without inventing a response. Model text is rendered as text with preserved line breaks, never executable HTML. The API key is a transport credential, not a message or workspace field.

## What the current assistant does

The assistant can discuss a target experiment, identify relevant existing records, ask for missing inputs, and propose an L1 or L3 schedule in conversation. It has no tools for changing containers, reminders, physical-operation records, or experiment plans. It cannot browse or verify sources. No answer is a deterministic feasibility result or a saved execution plan.

Its domain instructions retain the researcher's rules: virgin collection has one configured culture day and three windows; vial/bottle third-instar collection uses the editable 25°C-equivalent D5 preset with recorded temperature history; transgenesis remains deferred. L1 discussions may follow adults → egg laying → egg batch → Petri dish → stage observation → dissection, reusing suitable existing material. Hourly egg protocols do not use the culture temperature multiplier. A hatch estimate is not treated as a guaranteed L1 dissection interval. A suggested schedule with missing timing or suitability information remains a draft requiring those inputs.

Future structured suggestions need a concrete step or material target, editable before/after changes, and deterministic validation before application. The current text response does not implement these features. See [experiment-planner-design.md](experiment-planner-design.md) for the planned workflow and solver model.

## Backup and restore in the application

**Protocols & settings → Backup & restore** provides both directions. **Download backup** exports a consistent SQLite copy of laboratory records and workspace settings. **Import backup** accepts a Flykeeper database file up to 64 MB, checks it, and compares incoming/current record counts and time zones before replacement.

Typing `RESTORE` confirms replacement of the current workspace, not a merge. The application saves a recovery backup first. Invalid records, unsupported schemas, an expired preview, or a changed current workspace prevent applying the preview. The completed restore refreshes the app and clears in-memory assistant context. **Download recovery backup** retrieves the pre-restore copy, which can be imported through the same flow. AI profiles and API keys are outside the restored database and remain unchanged.

These consequences belong in the import UI because they affect the current action. The former documentation requiring a stopped app and manual file replacement is no longer the normal restore flow.

## Experiment-canvas design reference

Open [assistant-design.html](assistant-design.html) separately to review the proposed experiment editor. It remains one standalone file with fictional example cultures, no network calls, and no laboratory-database writes. Its model connection and assistant controls remain nonfunctional. Page reload resets its sample edits and connection drafts. This is distinct from the connected Assistant in the main application.

The prototype places a target operation, time window, genotype, and quantity above materials and editable steps. For L1, it separates adult selection, egg laying, egg collection, and Petri-dish incubation. The researcher supplies incubation rules and stage-acceptance criteria. Parents/Offspring selection does not imply moving all adults. The target step follows the target fields; steps can be named, added, reordered, or removed.

For L3, a proposed new culture uses the editable D5 relation to infer setup from a collection date. For an existing culture, the prototype exposes the recorded setup and flags a mismatch with that relation. Collection-to-dissection timing remains a separate input. Example dates do not establish an observed biological stage.

**Check draft** shows missing fields and simple local date conflicts: start/end order, immediate predecessor order, work after the target, and an optional weekday-only schedule. These checks do not implement duration propagation, real availability windows, inventory allocation, protocol interpretation, biological validation, planned-versus-actual execution, or immutable plan versions. The prototype has no Apply plan action.

Its JavaScript uses input values or `textContent`, with network access disabled by Content Security Policy. Controls have labels and keyboard focus. The assistant panel becomes a drawer at smaller widths. Its small validation message map is not a full localization implementation; production assistant strings already use the application's English translation catalog.

## Verification scope

The original standalone prototype had a syntax check and visible-browser walkthrough of L1/L3 switching, D5 date calculation, missing fields, step editing, and disconnected profile drafts. That historical walkthrough applies only to the prototype.

The integrated components have passed TypeScript checking and targeted lint. Backend verification uses isolated test databases and controlled provider responses. This document does not claim that a user's live cloud account, installed local model, or current production backup has been exercised; end-to-end application verification is reported separately after it is completed.
