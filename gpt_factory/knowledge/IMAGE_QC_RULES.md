# Image Quality-Control Rules

## Critical failure

An image fails immediately when it contains:

- malformed or duplicated major components,
- wrong subject count,
- embedded text or watermark,
- a collage or split-screen layout,
- a fundamentally wrong location, era, time, or weather,
- a sensational event not supported by the story,
- a composition that cannot support the planned movement.

## Repairable issue

An image may still pass for local repair when it only needs:

- a modest crop,
- a small exposure adjustment,
- a background blur,
- removal of an unimportant edge object,
- later replacement of abstract monitor content.

## QC report fields

For every asset record:

- prompt adherence,
- continuity confidence,
- geometry confidence,
- composition confidence,
- animation suitability,
- failed checks,
- retry performed,
- final decision: passed or review_required.

Never claim certainty when visual evidence is ambiguous.
