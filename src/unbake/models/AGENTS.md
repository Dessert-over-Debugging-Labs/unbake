# models/

Serialization contracts (pydantic). JSON uses camelCase aliases; Python uses
snake_case. Status enums carry a short Korean gloss in comments — keep that
pattern when adding values. Extra fields from LLM output are ignored; missing
required fields still fail validation.
