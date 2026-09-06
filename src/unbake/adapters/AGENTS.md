# adapters/

External system integrations and DTO mapping. Dependencies point inward:
`models/` and `evaluation/` must not import from concrete adapters. `naembii/`
is a working example of a publish target — extraction and evaluation run fully
without its configuration.
