# Project conventions

## Product UI

- Keep the interface in English and use translation keys for future languages.
- Show labels, record data, controls, and concise feedback needed for the current task.
- Do not put design rationale, conversation history, user requirements, implementation details, migration explanations, blanket disclaimers, or repetitive instructions into product screens.
- Do not move unwanted prose into tooltips or collapsed help merely to retain it. Keep engineering explanations in project documentation.
- Show a warning when a specific record or attempted action requires attention. Identify the actual issue and available correction. Preserve meaningful destructive-action consequences.
- Prefer clear labels and units to helper paragraphs. Keep estimated and observed values accurately labeled without repeating general caveats.
- Do not use UI design skills for this project; the user explicitly requested direct design work.

## Experimental workflows

- The researcher defines experimental steps and biological timing rules. AI may propose editable plans; it must not silently invent or replace protocols.
- Virgin collection uses one configured culture day with three windows. Do not add collection days.
- Third-instar collection currently uses the researcher's calendar D5 preset.
- Transgenesis is deferred until the researcher defines its workflow.
- Keep planned work separate from recorded physical operations. Keep genotype targets separate from verified selected genotypes.
- AI architecture supports cloud and local connections; implement one first. Do not present an unconnected model or an unimplemented planner as working.

## Verification

- Test with an isolated database. Never insert demonstration or test cultures into the personal workspace.
- Preserve existing form behavior, accessibility, and validation when editing UI copy.
