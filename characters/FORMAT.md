# Cast pack format

A *cast pack* keeps a series' characters visually consistent across chapter
illustrations. The pattern (locked prose spec + reference model sheet passed
as an image ref on every render) is adapted from Trevin Chow's
[illo-skill](https://github.com/tmchow/illo-skill) character packs (MIT),
generalized from a single mascot to a small narrative cast.

A pack is a directory at `<data_dir>/series/<slug>/character/`:

```
cast.md          # the locked specs (this format)
reference.png    # the cast model sheet — every character, neutral pose,
                 # white background, no text; generated once, then approved
                 # and never regenerated casually
```

The cast sheet is passed as an image reference on **every** panel render.
After chapter 1, the first accepted panel becomes a second reference (the
*style anchor*) so all chapters read as one artist.

## cast.md

```markdown
# <Series title> — cast

Style: **manga-bw**   <!-- the series' locked look; see Style block below -->

## <Character name> (<role>)

### Locked design
- **Body**: build, height, distinguishing shapes. Size relative to others.
- **Face/head**: hair, eyes, expressions allowed.
- **Clothes**: the fixed outfit (characters keep one outfit, like a manga).
- Explicit NEVERs (things models love to add: extra accessories, wrong
  colors, aging up/down).

### Prompt spec
> One paragraph, copied verbatim into every generation prompt that includes
> this character. Restate the locked design as drawing instructions.

## <Next character> …
```

Keep 1–3 characters locked; incidental characters are described per-prompt
and are allowed to drift.

## Style block (manga-bw)

Chapters print grayscale, so the default look is print-first:

> STYLE: black-and-white shōnen manga ink illustration — clean confident
> ink linework, screentone/halftone dot shading, high contrast, pure white
> paper background, dynamic manga composition; no color, no gray gradients
> (tone dots only), no photorealism, no 3D render look.

## Hard rule: no text in images

Every prompt must end with:

> TEXT: absolutely no text, lettering, writing, signs, sound-effect
> characters, kanji, kana, letters, numbers, watermarks, or signatures
> anywhere in the image.

Image models emit garbled pseudo-kanji; a learner who trusts that every
character on the page is known will try to read it. Reject any render that
contains writing of any kind.
