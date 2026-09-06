# extraction/

Prompts are versioned artifacts: the first line of each `prompts/*.md` carries a
`<!-- version: x.y.z -->` comment — bump it on any content change. Prompt version
and hash are recorded in provenance. Port signatures enforce isolation: the
blind extractor takes only a video reference.
