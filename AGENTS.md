# Working on Faultline

Before designing, changing, or reviewing Jev questions, evidence inputs, scoring policies, transport, or cost/performance experiments, use the installed `typesafe-ai` skill (`typesafe:typesafe-ai` in the TypeSafe plugin). Read the live provider documentation it points to for the part you are changing.

Follow [Faultline's Jev guidance](skills/faultline/references/jev.md) for evidence, experiments, and interpretation. If the companion skill is unavailable, use the linked official documentation directly and state that fallback. [Installation](docs/install.md) includes the companion skill command; it is not a runtime dependency.

Check the current implementation before describing a feature as shipped. Provider examples and successful experiments do not automatically change Faultline's evaluator, thresholds, execution guards, or spending authorization.

Keep consumer-repository source, identifiable reports, and credentials out of this repository. Store private experiment evidence in that consumer's ignored workspace; use synthetic or properly anonymized examples here.
