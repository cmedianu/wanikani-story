# Cast pack format

A *cast pack* keeps a series' characters visually consistent across chapter
illustrations. The pattern (locked prose spec + reference model sheet passed
as an image ref on every render) is adapted from Trevin Chow's
[illo-skill](https://github.com/tmchow/illo-skill) character packs (MIT),
generalized from a single mascot to a small narrative cast.

A pack is a directory at `<data_dir>/series/<slug>/character/`:

```
cast.md                     # the locked specs (this format)
reference.<style>.png       # the cast model sheet for that style — every
                            # character, neutral pose, white background, no
                            # text; generated once, then approved and never
                            # regenerated casually
```

The sheet is named for the style it renders (`reference.manga-bw.png`,
`reference.manga-color.png`), so a series can change its look without losing
the old art. The `Style:` line in `cast.md` selects which one is live; every
render resolves `reference.<style>.png` and `../style-anchor.<style>.png`
from it. Switching a series back is a one-word edit — never overwrite or
delete the sheet of a style you are leaving.

The cast sheet is passed as an image reference on **every** panel render.
After chapter 1, the first accepted panel becomes a second reference (the
*style anchor*) so all chapters read as one artist. Anchors are per-style
too: a B&W anchor drags a color prompt back to ink, so a style switch starts
a fresh anchor from the first accepted panel in the new style.

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

## Style blocks

One block per style; the `Style:` line in `cast.md` picks one, and it is
copied verbatim into every generation prompt.

### manga-bw

Print-first — survives a grayscale printer with nothing lost:

> STYLE: black-and-white shōnen manga ink illustration — clean confident
> ink linework, screentone/halftone dot shading, high contrast, pure white
> paper background, dynamic manga composition; no color, no gray gradients
> (tone dots only), no photorealism, no 3D render look.

### manga-color

> STYLE: full-color anime/manga illustration — clean confident black ink
> linework, flat cel shading with crisp shadow shapes, warm saturated but
> natural palette, pure white paper background, high value contrast so the
> image still reads when printed in grayscale; no screentone dots, no
> gradients or airbrush, no photorealism, no 3D render look.

Color costs contrast on a B&W printer — cel colors of similar lightness
collapse into one gray. The "high value contrast" clause is load-bearing;
keep it, and print color chapters on a color printer where it matters.

**Value ladder.** Hue does not survive grayscale; lightness does. Pick the
palette so that any two areas which *touch* sit on different rungs — light
(200–255), mid (110–170), dark (40–90). Garments that meet (hoodie/shorts,
coat/saddle) are the ones that collapse. Verify rather than trust the
prompt, once, on the approved sheet:

```bash
convert reference.manga-color.png -colorspace Gray gray.png   # then look at it
convert gray.png -format "%[pixel:p{X,Y}]" info:              # sample a region
```

Adjacent areas need ~30/255 between them when a black ink line separates
them (the linework does part of the work) and ~40 where they meet without
one; below that they read as a single shape on a B&W printer. Re-roll the
sheet with one of them moved a rung, and record the measured values in the
pack's **Colors** bullet so later panels can be spot-checked against it.

A color pack needs colors *in the locked designs* (hair, eyes, skin, each
garment, the animal's coat), not just in the style block — otherwise the
model re-picks them every panel and the cast drifts. When converting an
existing B&W pack, pass the old sheet as the image ref and change only the
rendering, so the recolored cast stays the same characters.

## Hard rule: no text in images

Every prompt must end with:

> TEXT: absolutely no text, lettering, writing, signs, sound-effect
> characters, kanji, kana, letters, numbers, watermarks, or signatures
> anywhere in the image.

Image models emit garbled pseudo-kanji; a learner who trusts that every
character on the page is known will try to read it. Reject any render that
contains writing of any kind.
